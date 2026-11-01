"""Indexed lexical candidates; scores are evidence for review, never equivalence."""

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from time import monotonic

from django.db import transaction
from django.db.models import Case
from django.db.models import Count
from django.db.models import IntegerField
from django.db.models import Q
from django.db.models import Value
from django.db.models import When
from django.urls import reverse
from django.utils import timezone

from .community_models import StatementSimilarityDocument
from .community_models import StatementSimilarityIndex
from .community_models import StatementSimilaritySource
from .community_models import StatementSimilarityTerm
from .models import ContestProblemStatement

INDEX_VERSION = 1
MAX_SOURCE_LENGTH = 12000
MAX_CANDIDATES = 200
MAX_RESULTS = 8
MIN_SCORE = 0.55
MAX_BUILD_SECONDS = 600
TOKEN_RE = re.compile(r"\\[a-zA-Z]+|[^\W_]+|[^\w\s]", re.UNICODE)
ASY_RE = re.compile(r"\[asy\].*?\[/asy\]", re.IGNORECASE | re.DOTALL)
STOP_WORDS = {
    "a",
    "an",
    "the",
    "of",
    "to",
    "in",
    "on",
    "for",
    "and",
    "or",
    "is",
    "are",
    "be",
    "that",
    "let",
    "prove",
    "show",
    "find",
    "all",
    "such",
    "with",
    "if",
    "then",
}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def normalized_tokens(text):
    text = unicodedata.normalize("NFKC", ASY_RE.sub(" [diagram] ", text)).casefold()
    for symbol, command in (("≥", r"\geq"), ("≤", r"\leq"), ("≠", r"\neq")):
        text = text.replace(symbol, command + " ")
    text = re.sub(r"\\(?:left|right|displaystyle|textstyle)\b|\\[,;!: ]", " ", text)
    for command, replacement in (
        ("dfrac", "frac"),
        ("tfrac", "frac"),
        ("geqslant", "geq"),
        ("leqslant", "leq"),
        ("ge", "geq"),
        ("le", "leq"),
    ):
        text = re.sub(r"\\" + command + r"\b", lambda _, replacement=replacement: "\\" + replacement, text)
    text = text.replace("$", " ").replace(r"\(", " ").replace(r"\)", " ")
    text = text.replace(r"\[", " ").replace(r"\]", " ")
    return TOKEN_RE.findall(text)


def representations(text):
    tokens = normalized_tokens(text)
    variables = {}
    structure = []
    for token in tokens:
        if len(token) == 1 and token.isalpha():
            variables.setdefault(token, f"var{len(variables)}")
            structure.append(variables[token])
        else:
            structure.append(token)
    return " ".join(tokens), " ".join(structure)


def terms_for(text):
    # Word and short token-pair postings retrieve short formulas as well as prose.
    tokens = text.split()
    words = {token for token in tokens if token not in STOP_WORDS and len(token) > 1}
    pairs = {" ".join(tokens[i : i + 2]) for i in range(len(tokens) - 1)}
    return {digest(term) for term in words | pairs}


def index_ready():
    index = StatementSimilarityIndex.objects.filter(pk=1, version=INDEX_VERSION).first()
    return bool(index and index.signature == library_signature())


def library_signature():
    # Revision triggers also detect bulk/direct updates that omit updated_at.
    revision = StatementSimilaritySource.objects.filter(pk=1).values_list("revision", flat=True).first()
    return {"revision": revision}


def rebuild_similarity_index(*, max_seconds=MAX_BUILD_SECONDS):
    """Off-request rebuild; publish atomically only if the source stays unchanged."""
    started = monotonic()
    _, created = StatementSimilaritySource.objects.get_or_create(pk=1)
    if created:
        StatementSimilarityIndex.objects.update(signature={})
    signature = library_signature()
    with transaction.atomic():
        index, _ = StatementSimilarityIndex.objects.select_for_update().get_or_create(pk=1)
        if index.signature == signature and index.version == INDEX_VERSION:
            return 0
        StatementSimilarityDocument.objects.all().delete()
        count = 0
        source = ContestProblemStatement.objects.filter(is_active=True).order_by("pk")
        for statement in source.only("pk", "statement_latex").iterator(chunk_size=200):
            if monotonic() - started > max_seconds:
                message = "Similarity index build timed out; previous publication retained."
                raise TimeoutError(message)
            # Bound each comparison; long archive statements remain searchable by
            # their opening text. Results disclose this limitation.
            text, structure = representations(statement.statement_latex[:MAX_SOURCE_LENGTH])
            document = StatementSimilarityDocument.objects.create(
                statement=statement,
                normalized_text=text,
                structure_text=structure,
                text_digest=digest(text),
                structure_digest=digest(structure),
            )
            StatementSimilarityTerm.objects.bulk_create(
                [StatementSimilarityTerm(document=document, term=term) for term in terms_for(text)],
                batch_size=500,
            )
            count += 1
        if library_signature() != signature:
            message = "Library changed during indexing; previous publication retained."
            raise RuntimeError(message)
        index.signature, index.version, index.built_at = signature, INDEX_VERSION, timezone.now()
        index.save()
        return count


def _score(text, structure, candidate):
    if digest(text) == candidate.text_digest:
        return 1.0, "Matching wording"
    if digest(structure) == candidate.structure_digest:
        return 0.96, "Similar structure / renamed variables"
    words, other_words = set(text.split()), set(candidate.normalized_text.split())
    overlap = 2 * len(words & other_words) / max(1, len(words) + len(other_words))
    # Compare a bounded prefix; token overlap also handles reordered prose and
    # offsets SequenceMatcher's treatment of very common symbols.
    sequence = SequenceMatcher(None, text[:2000], candidate.normalized_text[:2000], autojunk=True).ratio()
    return max(sequence, overlap * 0.9), "Related wording"


def check_statement_similarity(statement):
    signature = library_signature()
    index = StatementSimilarityIndex.objects.filter(pk=1, version=INDEX_VERSION).first()
    if not index or index.signature != signature:
        return {
            "available": False,
            "matches": [],
            "message": (
                "The library similarity index is being prepared or needs refreshing. "
                "Please try again after an admin refreshes it."
            ),
        }
    text, structure = representations(statement[:MAX_SOURCE_LENGTH])
    terms = terms_for(text)
    rare = list(
        StatementSimilarityTerm.objects.filter(term__in=terms)
        .values("term")
        .annotate(frequency=Count("pk"))
        .order_by("frequency", "term")
        .values_list("term", flat=True)[:12],
    )
    candidates = list(
        StatementSimilarityTerm.objects.filter(term__in=rare)
        .values("document_id")
        .annotate(shared=Count("pk"))
        .order_by("-shared", "document_id")[: MAX_CANDIDATES + 1],
    )
    ids = [row["document_id"] for row in candidates[:MAX_CANDIDATES]]
    documents = (
        StatementSimilarityDocument.objects.filter(
            Q(pk__in=ids) | Q(text_digest=digest(text)) | Q(structure_digest=digest(structure)),
            statement__is_active=True,
        )
        .select_related("statement")
        .annotate(
            priority=Case(
                When(text_digest=digest(text), then=Value(0)),
                When(structure_digest=digest(structure), then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
        )
        .order_by("priority", "pk")[:MAX_CANDIDATES]
    )
    matches = []
    for document in documents:
        score, reason = _score(text, structure, document)
        if score >= MIN_SCORE:
            row = document.statement
            matches.append(
                {
                    "statement_uuid": str(row.statement_uuid),
                    "label": row.contest_year_problem,
                    "url": reverse("pages:problem_statement_detail", args=[row.statement_uuid]),
                    "preview": row.statement_latex[:1000],
                    "score": round(score * 100, 1),
                    "reason": reason,
                },
            )
    matches.sort(key=lambda row: (-row["score"], row["label"]))
    if library_signature() != signature:
        return {
            "available": False,
            "matches": [],
            "message": "The library changed during the check. Please check again.",
        }
    return {
        "available": True,
        "matches": matches[:MAX_RESULTS],
        "signature": signature,
        "checked_at": timezone.now().isoformat(),
        "candidate_limit_reached": len(candidates) > MAX_CANDIDATES,
        "message": (
            "Text and structure candidates only. Scores do not measure mathematical equivalence or originality. "
            "Translations, substantial rewording, and diagrams may be missed; "
            "archive text is limited to 12,000 characters."
        ),
    }
