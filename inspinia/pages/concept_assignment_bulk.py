"""Consistent, scoped exports and pure local previews. This module has no apply path."""

import gzip
import json
import os
import re
import uuid
from collections import Counter
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from django.db import connection
from django.db import transaction
from django.utils import timezone

from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_registry import digest
from inspinia.pages.concept_assignment_service import IMAGE_FIELDS
from inspinia.pages.concept_assignment_service import MAX_BATCH
from inspinia.pages.concept_assignment_service import AssignmentConflictError
from inspinia.pages.concept_assignment_service import build_review_preview
from inspinia.pages.concept_assignment_service import published_solution_evidence
from inspinia.pages.concept_assignment_service import storage_ready
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.concept_assignment_trace import source_uuid_query
from inspinia.pages.models import ProblemConceptAssignment

SUBJECTS = ("Algebra", "Number Theory", "Geometry", "Combinatorics")
VERSION = 1
MAX_PROBLEMS = 20000
MAX_DECISIONS = 20000
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
MAX_PACKET_BYTES = 8 * 1024 * 1024
YEAR_DIGITS = 4
MAX_FILTER_LENGTH = 200
MAX_PROTECTED_KEYS = 200000
ENGINE_FILES = (
    "concept_assignment_bulk.py",
    "concept_assignment_service.py",
    "concept_assignment_trace.py",
    "concept_assignment_registry.py",
    "concept_assignment_source_export.py",
    "concept_alias_policy.py",
    "concept_alias_context.py",
    "combinatorics_concept_context.py",
)


class BulkReviewError(ValueError):
    pass


def engine_fingerprint():
    import hashlib

    root = Path(__file__).parent
    return digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ENGINE_FILES})


def seal(document):
    return {**document, "sha256": digest(document)}


def verify(document, kind):
    if not isinstance(document, dict) or document.get("kind") != kind or document.get("version") != VERSION:
        message = "Unsupported bulk review document."
        raise BulkReviewError(message)
    content = {key: value for key, value in document.items() if key != "sha256"}
    if document.get("sha256") != digest(content):
        message = "Document checksum does not match; regenerate the artifact."
        raise BulkReviewError(message)


def read_document(path):
    path = Path(path)
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        message = "Document exceeds the size limit."
        raise BulkReviewError(message)
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rb") as handle:
        content = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        message = "Decompressed document exceeds the size limit."
        raise BulkReviewError(message)
    try:
        return json.loads(content)
    except (UnicodeDecodeError, ValueError) as exc:
        message = "Document must contain UTF-8 JSON."
        raise BulkReviewError(message) from exc


def document_bytes(document, *, compressed=False):
    content = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    if len(content) > MAX_DOCUMENT_BYTES:
        message = "Snapshot exceeds 64 MiB; select a smaller source scope."
        raise BulkReviewError(message)
    return gzip.compress(content, mtime=0) if compressed else content


def write_document(path, document):
    """Never overwrite an existing artifact; exported mathematical content stays private."""
    path = Path(path)
    content = document_bytes(document, compressed=path.suffix == ".gz")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def normalize_scope(scope):
    if not isinstance(scope, dict) or set(scope) - {"subject", "year", "contest", "q", "problem_uuids"}:
        message = "Select a subject/filter scope or explicit problem UUIDs."
        raise BulkReviewError(message)
    if scope.get("problem_uuids"):
        if any(scope.get(key) for key in ("subject", "year", "contest", "q")):
            message = "Explicit UUIDs cannot be combined with subject filters."
            raise BulkReviewError(message)
        values = scope["problem_uuids"]
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_PROBLEMS:
            message = "Explicit UUID scope exceeds the problem limit."
            raise BulkReviewError(message)
        return {"problem_uuids": sorted({str(uuid.UUID(str(value))) for value in values})}
    subject = scope.get("subject")
    if subject not in SUBJECTS:
        message = "Choose one of the four subjects for a complete scoped snapshot."
        raise BulkReviewError(message)
    year = str(scope.get("year") or "")
    if year and (not year.isdigit() or len(year) != YEAR_DIGITS):
        message = "Year must contain four digits."
        raise BulkReviewError(message)
    if any(
        not isinstance(scope.get(key, ""), str) or len(scope.get(key, "")) > MAX_FILTER_LENGTH
        for key in ("contest", "q")
    ):
        message = "Source filters must be strings of at most 200 characters."
        raise BulkReviewError(message)
    return {"subject": subject, "year": year, "contest": scope.get("contest", ""), "q": scope.get("q", "")}


@contextmanager
def read_only_snapshot():
    """One read-only transaction; restore SQLite's connection setting after rollback."""
    if connection.vendor == "postgresql":
        if connection.in_atomic_block:
            message = "Bulk export requires its own read-only transaction."
            raise BulkReviewError(message)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = '15s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
            yield
    elif connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA query_only")
            previous = cursor.fetchone()[0]
            cursor.execute("PRAGMA query_only = ON")
        try:
            with transaction.atomic():
                yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"PRAGMA query_only = {int(previous)}")
    else:
        message = "Snapshot consistency is supported only for PostgreSQL and SQLite."
        raise BulkReviewError(message)


def capture_snapshot(scope):
    scope = normalize_scope(scope)
    sources, records, proofs = {}, {}, {}
    encoded_size = len(document_bytes(REGISTRY.definitions))
    with read_only_snapshot():
        if not storage_ready():
            message = "The assignment review schema must be installed before a complete snapshot."
            raise BulkReviewError(message)
        keys = scope.get("problem_uuids")
        if keys is None:
            keys = [str(key) for key in source_uuid_query(**scope, include_inactive=True)[: MAX_PROBLEMS + 1]]
        if not keys or len(keys) > MAX_PROBLEMS:
            message = "Source scope is empty or exceeds 20,000 problems; narrow the filters."
            raise BulkReviewError(message)
        for start in range(0, len(keys), MAX_BATCH):
            batch = keys[start : start + MAX_BATCH]
            loaded = load_sources(batch)
            sources.update(loaded)
            encoded_size += len(document_bytes(loaded))
            records.update({key: [] for key in batch})
            query = ProblemConceptAssignment.objects.filter(problem_uuid__in=batch).order_by("concept_id")
            for row in query.values("problem_uuid", "updated_at", *IMAGE_FIELDS):
                key = str(row.pop("problem_uuid"))
                row["updated_at"] = row["updated_at"].isoformat()
                records[key].append(row)
            published = {str(key): value for key, value in published_solution_evidence(batch).items()}
            proofs.update(published)
            encoded_size += len(document_bytes({key: records[key] for key in batch})) + len(document_bytes(published))
            if encoded_size > MAX_DOCUMENT_BYTES:
                message = "Snapshot exceeds 64 MiB; select a smaller source scope."
                raise BulkReviewError(message)
        if set(sources) != set(keys):
            message = "A selected problem is missing; no partial snapshot was exported."
            raise BulkReviewError(message)
        result = {
            "kind": "concept-review-snapshot",
            "version": VERSION,
            "captured_at_utc": timezone.now().isoformat(),
            "scope": scope,
            "registry_fingerprint": REGISTRY.fingerprint,
            "engine_fingerprint": engine_fingerprint(),
            "registry": {
                "definitions": REGISTRY.definitions,
                "areas": REGISTRY.areas,
                "redirects": REGISTRY.redirects,
            },
            "sources": sources,
            "records": records,
            "published_solutions": proofs,
            "source_writes": 0,
            "consistency": "repeatable_read_read_only" if connection.vendor == "postgresql" else "sqlite_read_only",
            "counts": {
                "problems": len(sources),
                "assignment_rows": sum(len(rows) for rows in records.values()),
                "published_solutions": len(proofs),
                "with_statement": sum(bool(source["statement_text"]) for source in sources.values()),
                "current_dispositions": dict(
                    Counter(row["disposition"] for rows in records.values() for row in rows if row["is_current"]),
                ),
            },
        }
        result = seal(result)
        document_bytes(result)  # Enforce bounds before releasing the snapshot transaction.
    return result


def validate_snapshot(snapshot):
    verify(snapshot, "concept-review-snapshot")
    normalize_scope(snapshot["scope"])
    sources, records, proofs = snapshot["sources"], snapshot["records"], snapshot["published_solutions"]
    if not isinstance(sources, dict) or not 1 <= len(sources) <= MAX_PROBLEMS or set(sources) != set(records):
        message = "Snapshot must include complete source and assignment groups."
        raise BulkReviewError(message)
    for key, source in sources.items():
        if str(uuid.UUID(key)) != key or source["problem_uuid"] != key:
            message = "Source identity does not match its snapshot key."
            raise BulkReviewError(message)
        ids = [row["concept_id"] for row in records[key]]
        if len(ids) != len(set(ids)):
            message = "Snapshot contains duplicate assignment identities."
            raise BulkReviewError(message)
    if any(proof["problem_uuid"] not in sources or str(proof["reference"]) != key for key, proof in proofs.items()):
        message = "Published evidence belongs to a different scope."
        raise BulkReviewError(message)


def baselines(snapshot):
    by_problem = defaultdict(dict)
    for key, proof in snapshot["published_solutions"].items():
        by_problem[proof["problem_uuid"]][key] = proof
    return {
        key: {
            "source": digest(source),
            "assignments": digest(snapshot["records"][key]),
            "published_evidence": digest(by_problem[key]),
        }
        for key, source in snapshot["sources"].items()
    }


def make_packet(snapshot, decisions, protected_keys=()):
    validate_snapshot(snapshot)
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= MAX_DECISIONS:
        message = "A review packet requires between 1 and 20,000 explicit decisions."
        raise BulkReviewError(message)
    if not isinstance(protected_keys, (list, tuple)) or len(protected_keys) > MAX_PROTECTED_KEYS:
        message = "Protected keys must be a bounded list of problem UUID|concept ID pairs."
        raise BulkReviewError(message)
    for key in protected_keys:
        problem, separator, concept = str(key).partition("|")
        if (
            not separator
            or problem not in snapshot["sources"]
            or REGISTRY.canonical(concept) not in REGISTRY.definitions
        ):
            message = "A protected key is outside the snapshot or canonical catalog."
            raise BulkReviewError(message)
    packet = seal(
        {
            "kind": "concept-review-packet",
            "version": VERSION,
            "snapshot_sha256": snapshot["sha256"],
            "scope": snapshot["scope"],
            "registry_fingerprint": snapshot["registry_fingerprint"],
            "engine_fingerprint": snapshot["engine_fingerprint"],
            "baselines": baselines(snapshot),
            "protected_keys": sorted(set(protected_keys)),
            "decisions": decisions,
            "operation_namespace": str(uuid.uuid4()),
        },
    )
    if len(document_bytes(packet)) > MAX_PACKET_BYTES:
        message = "Review packet exceeds 8 MiB; split the decision selection."
        raise BulkReviewError(message)
    return packet


def _batches(decisions):
    grouped, touched = defaultdict(list), set()
    for decision in decisions:
        key = str(uuid.UUID(str(decision["problem_uuid"])))
        cid = REGISTRY.canonical(str(decision["concept_id"]))
        targets = [cid]
        if decision.get("action") == "replace":
            targets.append(REGISTRY.canonical(str(decision.get("replacement_concept_id", ""))))
        for target in targets:
            pair = key + "|" + target
            if pair in touched:
                message = f"Duplicate or conflicting decision for {pair}."
                raise BulkReviewError(message)
            touched.add(pair)
        grouped[key].append(decision)
    batches, current = [], []
    for key in sorted(grouped):
        group = grouped[key]
        if len(group) > MAX_BATCH:
            message = "One problem exceeds the 250-decision batch limit."
            raise BulkReviewError(message)
        if current and len(current) + len(group) > MAX_BATCH:
            batches.append(current)
            current = []
        current.extend(group)
    return [*batches, current] if current else batches


def validate_packet(packet):
    verify(packet, "concept-review-packet")
    normalize_scope(packet["scope"])
    uuid.UUID(packet["operation_namespace"])
    values = packet["baselines"]
    if not isinstance(values, dict) or not 1 <= len(values) <= MAX_PROBLEMS:
        message = "Packet baseline scope is invalid."
        raise BulkReviewError(message)
    for key, row in values.items():
        uuid.UUID(key)
        if not isinstance(row, dict) or set(row) != {"source", "assignments", "published_evidence"}:
            message = "Every baseline must contain source, assignment and published-evidence hashes."
            raise BulkReviewError(message)
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in row.values()):
            message = "Baseline hashes must be SHA-256 strings."
            raise BulkReviewError(message)
    protected = packet["protected_keys"]
    if not isinstance(protected, list) or len(protected) > MAX_PROTECTED_KEYS:
        message = "Protected keys must be a bounded list."
        raise BulkReviewError(message)
    for pair in protected:
        if not isinstance(pair, str) or pair.partition("|")[0] not in values or not pair.partition("|")[2]:
            message = "Protected assignments must belong to the packet scope."
            raise BulkReviewError(message)
    if len(document_bytes(packet)) > MAX_PACKET_BYTES:
        message = "Review packet exceeds 8 MiB."
        raise BulkReviewError(message)


def review_packet(snapshot, packet):  # noqa: C901, PLR0912 - aggregate all conflicts
    """Pure, all-or-nothing preview. No database access or implicit decisions."""
    validate_snapshot(snapshot)
    validate_packet(packet)
    conflicts, batches = [], []
    protected = set(packet["protected_keys"])
    for key, expected in (
        ("registry_fingerprint", REGISTRY.fingerprint),
        ("engine_fingerprint", engine_fingerprint()),
    ):
        if snapshot[key] != expected or packet[key] != expected:
            conflicts.append({"code": key.upper() + "_CHANGED"})
    if normalize_scope(packet["scope"]) != snapshot["scope"]:
        conflicts.append({"code": "SCOPE_CHANGED"})
    current = baselines(snapshot)
    for key in sorted(set(current) | set(packet["baselines"])):
        old, new = packet["baselines"].get(key), current.get(key)
        if old is None or new is None:
            conflicts.append({"code": "SCOPE_CHANGED", "problem_uuid": key})
            continue
        for field in ("source", "assignments", "published_evidence"):
            if old.get(field) != new[field]:
                conflicts.append({"code": field.upper() + "_CHANGED", "problem_uuid": key})  # noqa: PERF401
    try:
        decisions = packet["decisions"]
        if not isinstance(decisions, list) or not 1 <= len(decisions) <= MAX_DECISIONS:
            message = "Decision selection is empty or exceeds the limit."
            raise BulkReviewError(message)  # noqa: TRY301 - return this validation failure in the report
        selected = _batches(decisions)
        if not conflicts:
            records = {
                key: [SimpleNamespace(**row) for row in rows if row["is_current"]]
                for key, rows in snapshot["records"].items()
            }
            proofs = {int(key): proof for key, proof in snapshot["published_solutions"].items()}
            for index, batch in enumerate(selected, 1):
                keys = {str(uuid.UUID(str(d["problem_uuid"]))) for d in batch}
                if not keys <= snapshot["sources"].keys():
                    conflicts.append({"code": "DECISION_OUTSIDE_SNAPSHOT", "batch": index})
                    continue
                try:
                    report = build_review_preview(
                        batch,
                        sources={key: snapshot["sources"][key] for key in keys},
                        records={key: records[key] for key in keys},
                        proofs=proofs,
                        operation_id=uuid.uuid5(uuid.UUID(packet["operation_namespace"]), str(index)),
                    )
                    for change in report["changes"]:
                        pair = change["problem_uuid"] + "|" + change["concept_id"]
                        if pair in protected:
                            conflicts.append({"code": "PROTECTED_ASSIGNMENT", "key": pair, "batch": index})
                    batches.append(report)
                except (AssignmentConflictError, ValueError, KeyError, TypeError) as exc:
                    conflicts.append({"code": "INVALID_DECISION", "batch": index, "reason": str(exc)})
    except (BulkReviewError, ValueError, KeyError, TypeError) as exc:
        conflicts.append({"code": "INVALID_PACKET", "reason": str(exc)})
    # A conflict in any scope or batch prevents producing executable batch lists.
    return seal(
        {
            "kind": "concept-review-dry-run",
            "version": VERSION,
            "packet_sha256": packet["sha256"],
            "ready": not conflicts,
            "conflicts": conflicts,
            "batches": [] if conflicts else batches,
            "decision_count": len(packet["decisions"]) if isinstance(packet.get("decisions"), list) else 0,
            "row_changes": 0 if conflicts else sum(len(batch["changes"]) for batch in batches),
            "protected_keys": len(packet["protected_keys"]),
            "baseline_problems": len(current),
            "source_writes": 0,
            "assignment_writes": 0,
        },
    )


def check_live_packet(packet):
    validate_packet(packet)
    return review_packet(capture_snapshot(packet["scope"]), packet)
