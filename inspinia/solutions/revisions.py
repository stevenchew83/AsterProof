"""Explicit document saves with immutable revisions and scoped concurrency tokens."""

from dataclasses import dataclass

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.document_source import CONVERSION_VERSION
from inspinia.solutions.document_source import PDF_OPTION_FIELDS
from inspinia.solutions.document_source import SYNTAX_VERSION
from inspinia.solutions.document_source import solution_source
from inspinia.solutions.document_source import source_digest
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionRevision

DOCUMENT_SOURCE_LIMIT = 64_000
SUMMARY_LIMIT = 12_000
TITLE_LIMIT = 160
CONTEXT_TTL = 7 * 24 * 60 * 60
CONTEXT_SALT = "asterproof.solution-document-editor.v1"


class InvalidEditorContext(ValueError):  # noqa: N818 - Public save-service contract.
    pass


class StaleSolutionVersion(ValueError):  # noqa: N818 - Public save-service contract.
    pass


class InvalidDocument(ValueError):  # noqa: N818 - Public save-service contract.
    pass


class DocumentWritesDisabled(InvalidDocument):
    pass


@dataclass(frozen=True)
class SaveDocumentResult:
    solution: ProblemSolution
    revision: SolutionRevision
    changed: bool


def editor_context(user, problem_uuid, *, solution=None):
    existing = (
        {"pk": solution.pk, "edit_version": solution.edit_version} if solution is not None
        else ProblemSolution.objects.filter(
            author_id=user.pk, problem__problem_uuid=problem_uuid,
        ).values("pk", "edit_version").first()
    )
    return signing.dumps({
        "version": 1, "author": str(user.pk), "problem": str(problem_uuid),
        "solution": existing["pk"] if existing else None,
        "edit_version": existing["edit_version"] if existing else 0,
    }, salt=CONTEXT_SALT)


def validate_editor_context(token, user, problem_uuid):
    try:
        value = signing.loads(token, salt=CONTEXT_SALT, max_age=CONTEXT_TTL)
    except (signing.BadSignature, TypeError, ValueError) as error:
        message = "This editor session is invalid or expired. Reload the editor before saving."
        raise InvalidEditorContext(message) from error
    if (
        not isinstance(value, dict) or value.get("version") != 1
        or not user.pk or value.get("author") != str(user.pk)
        or value.get("problem") != str(problem_uuid)
        or type(value.get("edit_version")) is not int or value["edit_version"] < 0
    ):
        message = "This editor belongs to a different account or problem. Reload before saving."
        raise InvalidEditorContext(message)
    return value


def _validated_document(source, title, summary, pdf_options, *, legacy_source=""):
    if not all(isinstance(value, str) for value in (source, title, summary)):
        message = "The solution document must contain text."
        raise InvalidDocument(message)
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in source + title + summary:
        message = "The solution contains an unsupported null character."
        raise InvalidDocument(message)
    normalized_legacy = legacy_source.replace("\r\n", "\n").replace("\r", "\n")
    if len(source) > DOCUMENT_SOURCE_LIMIT and source != normalized_legacy:
        message = f"Keep the solution within {DOCUMENT_SOURCE_LIMIT:,} characters."
        raise InvalidDocument(message)
    if len(title) > TITLE_LIMIT or len(summary) > SUMMARY_LIMIT:
        message = "The solution title or key idea is too long."
        raise InvalidDocument(message)
    if not isinstance(pdf_options, dict) or any(
        type(pdf_options.get(name)) is not bool for name in PDF_OPTION_FIELDS
    ):
        message = "Choose the PDF display options before saving."
        raise InvalidDocument(message)
    return source, title.strip(), summary


def _locked_solution(solution, user, context, base_version):
    if solution.author_id is not None and solution.author_id != user.pk:
        message = "Only the author can save this solution."
        raise InvalidEditorContext(message)
    problem = ProblemSolveRecord.objects.select_for_update().get(pk=solution.problem_id)
    payload = validate_editor_context(context, user, problem.problem_uuid)
    if type(base_version) is not int or payload["edit_version"] != base_version:
        message = "This solution has changed. Reload the latest version before saving."
        raise StaleSolutionVersion(message)
    current = ProblemSolution.objects.select_for_update().filter(problem=problem, author=user).first()
    if current is not None:
        placeholder = (
            payload.get("solution") is None and current.edit_version == 0
            and current.current_revision_id is None and not current.blocks.exists()
        )
        if current.edit_version != base_version or (payload.get("solution") != current.pk and not placeholder):
            message = "This solution has changed. Reload the latest version before saving."
            raise StaleSolutionVersion(message)
        return current
    if base_version != 0 or payload.get("solution") is not None:
        message = "This solution is no longer available. Reload before saving."
        raise StaleSolutionVersion(message)
    return ProblemSolution(problem=problem, author=user)


def _apply_action(solution, action):
    if action not in {"save", "save_draft", "publish"}:
        message = "Choose a valid solution save action."
        raise InvalidDocument(message)
    before = (solution.status, solution.published_at, solution.submitted_at)
    if action == "publish" and solution.status != ProblemSolution.Status.PUBLISHED:
        solution.status = ProblemSolution.Status.PUBLISHED
        solution.published_at = timezone.now()
        solution.submitted_at = solution.submitted_at or solution.published_at
    elif action == "save_draft":
        solution.status = ProblemSolution.Status.DRAFT
        solution.published_at = solution.submitted_at = None
    elif not solution.status:
        solution.status = ProblemSolution.Status.DRAFT
    return before != (solution.status, solution.published_at, solution.submitted_at)


@transaction.atomic
def save_document(  # noqa: PLR0913
    *, solution, user, source, title, summary, pdf_options, base_version, context, action="save",
):
    if not settings.SOLUTION_DOCUMENT_WRITES_ENABLED:
        message = "Saving is temporarily unavailable. Your writing is still in this editor."
        raise DocumentWritesDisabled(message)
    current = _locked_solution(solution, user, context, base_version)
    previous_source = solution_source(current)
    source, title, summary = _validated_document(
        source, title, summary, pdf_options, legacy_source=previous_source,
    )
    if action == "publish" and not source.strip():
        message = "Write a solution before publishing it."
        raise InvalidDocument(message)
    action_changed = _apply_action(current, action)
    digest = source_digest(source, title, summary, pdf_options)
    revision = current.current_revision if current.current_revision_id else None
    document_changed = revision is None or digest != revision.source_digest
    if not document_changed and not action_changed:
        return SaveDocumentResult(current, revision, changed=False)
    if not current.pk:
        current.save()
    if document_changed:
        latest_sequence = current.revisions.order_by("-sequence").values_list("sequence", flat=True).first() or 0
        conversion = revision.conversion_version if revision else (
            CONVERSION_VERSION if current.blocks.exists() else 0
        )
        revision = SolutionRevision.objects.create(
            solution=current, sequence=latest_sequence + 1, body_source=source, title=title,
            summary=summary, syntax_version=SYNTAX_VERSION, source_digest=digest,
            conversion_version=conversion, **{name: pdf_options[name] for name in PDF_OPTION_FIELDS},
        )
    current.current_revision = revision
    current.title, current.summary = title, summary
    for name in PDF_OPTION_FIELDS:
        setattr(current, name, pdf_options[name])
    current.edit_version += 1
    # save() retains concept-evidence invalidation signals. updated_at also keeps
    # the historical SQLite catalogue trigger aware of the pointer change.
    current.save()
    return SaveDocumentResult(current, revision, changed=True)
