"""One-student paste import with an immutable source and an atomic reviewed receipt."""

import hashlib
import json
import secrets

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.utils import timezone

from inspinia.rankings.achievement_forms import AchievementRowForm
from inspinia.rankings.imports.achievement_text import KIND
from inspinia.rankings.imports.achievement_text import MAX_ROWS
from inspinia.rankings.imports.achievement_text import normalized
from inspinia.rankings.imports.achievement_text import parse_achievement_text
from inspinia.rankings.imports.achievement_text import series_key
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.achievement_records import result_fingerprint
from inspinia.rankings.services.corrections import apply_proposal
from inspinia.rankings.services.corrections import create_proposal
from inspinia.rankings.services.import_protection import ranking_write_lock
from inspinia.users.roles import user_has_admin_role

MAX_LABEL = 160


def require_import_admin(actor):
    if not actor.is_active or not user_has_admin_role(actor):
        raise PermissionDenied


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def student_records(student_id):
    return list(
        StudentResult.objects.filter(student_id=student_id).select_related("assessment", "profile")
        .prefetch_related("claims").order_by("pk"),
    )


def existing_choices(records):
    return [
        (str(row.pk), f"{row.assessment.season_year} · {row.assessment.display_name} · record {row.pk}")
        for row in records
    ]


def _matches(row, records):
    key, title = series_key(row["title"]), normalized(row["title"])
    return [
        record.pk for record in records
        if record.assessment.season_year == row["year"] and (
            title in {normalized(record.assessment.display_name), normalized(record.assessment.code)}
            or (key and key == series_key(f"{record.assessment.code} {record.assessment.display_name}"))
        )
    ]


def _state(student_id, records):
    return _digest({
        "student": Student.objects.get(pk=student_id).updated_at.isoformat(),
        "records": [
            [row.pk, row.updated_at.isoformat(), row.assessment.updated_at.isoformat(), result_fingerprint(row),
             row.profile.updated_at.isoformat() if hasattr(row, "profile") else None,
             [[claim.pk, claim.updated_at.isoformat()] for claim in row.claims.all()]]
            for row in records
        ],
    })


def owned_batch(*, batch_id, student_id, actor, lock=False):
    require_import_admin(actor)
    batches = ImportBatch.objects.select_for_update() if lock else ImportBatch.objects
    batch = batches.get(pk=batch_id, created_by=actor, import_type=ImportBatch.ImportType.ASSESSMENT_RESULTS)
    if batch.summary_json.get("kind") != KIND or batch.summary_json.get("student_id") != student_id:
        message = "This is not an achievement paste for this student."
        raise ValueError(message)
    return batch


def prepare_paste(*, student, actor, source_text, source_label, default_evidence):
    require_import_admin(actor)
    if not source_label.strip() or len(source_label) > MAX_LABEL:
        message = "Provide a source label of at most 160 characters."
        raise ValueError(message)
    parsed = parse_achievement_text(source_text, default_evidence=default_evidence)
    digest = hashlib.sha256(source_text.encode()).hexdigest()
    previous = ImportBatch.objects.filter(
        import_type=ImportBatch.ImportType.ASSESSMENT_RESULTS, status=ImportBatch.Status.APPLIED,
        summary_json__kind=KIND, summary_json__student_id=student.pk, summary_json__source_sha256=digest,
        created_by=actor,
    ).first()
    if previous:
        return previous
    records = student_records(student.pk)
    for row in parsed["rows"]:
        matches = _matches(row, records)
        if len(matches) == 1:
            row["existing_result"] = str(matches[0])
            row["warnings"].append(
                "Possible existing event selected: link for context only; no existing value will change.",
            )
        elif matches:
            row["include"] = False
            row["warnings"].append(
                "Several existing records match. Choose the correct record or exclude this suggestion.",
            )
    return ImportBatch.objects.create(
        import_type=ImportBatch.ImportType.ASSESSMENT_RESULTS, original_filename=f"{source_label}.txt",
        status=ImportBatch.Status.PREVIEWED, created_by=actor,
        summary_json={
            "kind": KIND, "student_id": student.pk, "source_label": source_label.strip(),
            "source_text": source_text, "source_sha256": digest, "default_evidence": default_evidence,
            **parsed,
        },
    )


def _review_rows(summary, rows, records):
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or len(rows) < len(summary["rows"]):
        message = "Review all suggested rows, up to 80 rows per import."
        raise ValueError(message)
    reviewed, seen = [], set()
    for index, values in enumerate(rows):
        source = summary["rows"][index] if index < len(summary["rows"]) else {}
        source = {**source, "evidence": source.get("evidence", summary["default_evidence"])}
        form = AchievementRowForm(values, source=source, existing_choices=existing_choices(records))
        if not form.is_valid():
            message = f"Row {index + 1}: {form.errors.as_text()}"
            raise ValueError(message)
        row = form.cleaned_data
        if not row.get("include"):
            reviewed.append({"include": False})
            continue
        if not row["existing_result"] and _matches(row, records):
            message = f"Row {index + 1}: this event may already exist. Link an existing record or exclude this row."
            raise ValueError(message)
        key = ("link", row["existing_result"]) if row["existing_result"] else (row["year"], normalized(row["title"]))
        # Different labels for the same known competition must not create duplicate medals.
        series = (row["year"], series_key(row["title"])) if series_key(row["title"]) else key
        if key in seen or series in seen:
            message = f"Row {index + 1}: duplicate event. Keep one row with its separate award, score and placing."
            raise ValueError(message)
        seen.update((key, series))
        row.update(source_line=source.get("source_line"), excerpt=source.get("excerpt", ""))
        reviewed.append(row)
    return reviewed


def review_paste(*, batch_id, student_id, actor, rows):
    with ranking_write_lock():
        batch = owned_batch(batch_id=batch_id, student_id=student_id, actor=actor, lock=True)
        if batch.status != ImportBatch.Status.PREVIEWED:
            message = "This paste has already been consumed. Start a new preview."
            raise ValueError(message)
        records = student_records(student_id)
        summary = batch.summary_json
        summary["reviewed_rows"] = _review_rows(summary, rows, records)
        summary["review_state"] = _state(student_id, records)
        summary["review_nonce"] = secrets.token_hex(24)
        summary["reviewed_at"] = timezone.now().isoformat()
        batch.save(update_fields=["summary_json", "updated_at"])
        return batch


def _profile(result, row, detail=""):
    return {"kind": "profile", "target_id": result.pk, "values": {
        "record_type": row["record_type"], "discipline": row["discipline"], "scope": "unknown",
        "scope_detail": detail, "participation": "unknown", "featured": False, "active": True,
    }}


def _claims(result, row, summary, batch_id):
    state = row["evidence"]
    status = "conflicting" if "conflicting" in state else "pending" if "pending" in state else "reported"
    source = "family" if state.startswith("family") else "research"
    evidence = (
        f"Pasted source batch {batch_id}; source line {row.get('source_line') or 'manual review'}. "
        "Not independently verified during import.\n"
        f"{row.get('excerpt', '')}\nReview notes: {row.get('notes', '')}"
    )[:4000]
    operations = []
    for claim_type, label in (("award", row["outcome"]), ("score", row["score"]), ("ranking", row["ranking"])):
        if label in ("", None):
            continue
        operations.append({"kind": "claim", "target_id": result.pk, "values": {
            "claim_type": claim_type, "claim_label": label,
            "award_kind": "unknown", "verification_status": status, "source_type": source,
            "source_label": summary["source_label"], "evidence": evidence, "active": True,
        }})
    return operations


def _new_result(*, row, batch, actor):
    code = f"PASTE_{_digest([row['year'], normalized(row['title'])])[:24]}"
    assessment, created = Assessment.objects.get_or_create(
        code=code, season_year=row["year"], defaults={
            "display_name": row["title"], "category": Assessment.Category.OTHER,
            "result_type": Assessment.ResultType.MIXED, "is_ranked_by_default": False,
        },
    )
    if not created and (
        assessment.is_ranked_by_default or normalized(assessment.display_name) != normalized(row["title"])
    ):
        message = "The target event changed. Prepare a fresh preview."
        raise ValueError(message)
    return StudentResult.objects.create(
        student_id=batch.summary_json["student_id"], assessment=assessment, raw_score=row["score"],
        medal=row["outcome"] if row["outcome"].casefold() in {"gold", "silver", "bronze"} else "",
        status_text=row["outcome"], band=row["band"],
        remarks=f"Pasted source batch {batch.pk}.\n{row.get('excerpt', '')}\nReview notes: {row['notes']}",
        source_file_name=f"achievement-paste-{batch.pk}.txt", imported_by=actor, imported_at=timezone.now(),
    )


def _context_result(batch, actor):
    year = timezone.localdate(batch.created_at).year
    assessment = Assessment.objects.create(
        code=f"ACHIEVEMENT_CONTEXT_{_digest(batch.pk)[:12]}",
        season_year=year, display_name=f"Pasted achievement context — {batch.summary_json['source_label']}",
        category=Assessment.Category.OTHER, result_type=Assessment.ResultType.TEXT, is_ranked_by_default=False,
    )
    return StudentResult.objects.create(
        student_id=batch.summary_json["student_id"], assessment=assessment, band="Context record",
        status_text="Pasted source; not independently verified", remarks=batch.summary_json["source_text"],
        source_file_name=f"achievement-paste-{batch.pk}.txt", imported_by=actor, imported_at=timezone.now(),
    )


def apply_paste(*, batch_id, student_id, actor, nonce):
    require_import_admin(actor)
    with ranking_write_lock():
        batch = owned_batch(batch_id=batch_id, student_id=student_id, actor=actor, lock=True)
        summary = batch.summary_json
        if batch.status != ImportBatch.Status.PREVIEWED:
            message = "This paste has already been consumed. Nothing was imported again."
            raise ValueError(message)
        if not nonce or not secrets.compare_digest(str(nonce), summary.get("review_nonce", "")):
            message = "Review the current rows before applying; this confirmation is missing or superseded."
            raise ValueError(message)
        records = student_records(student_id)
        if summary.get("review_state") != _state(student_id, records):
            message = "This student's records changed after review. Review the rows again; nothing was imported."
            raise ValueError(message)
        if ImportBatch.objects.filter(
            status=ImportBatch.Status.APPLIED, summary_json__kind=KIND,
            summary_json__student_id=student_id, summary_json__source_sha256=summary["source_sha256"],
        ).exists():
            message = "This exact source text was already imported for this student. Nothing was imported again."
            raise ValueError(message)
        reviewed = _review_rows(summary, summary["reviewed_rows"], records)
        created_ids, linked_ids, operations = [], [], []
        for row in reviewed:
            if not row.get("include"):
                continue
            if row["existing_result"]:
                linked_ids.append(int(row["existing_result"]))
                continue
            result = _new_result(row=row, batch=batch, actor=actor)
            created_ids.append(result.pk)
            operations.extend([_profile(result, row), *_claims(result, row, summary, batch.pk)])
        context = _context_result(batch, actor)
        operations.append(_profile(context, {"record_type": "context", "discipline": "other"}, (
            f"Source captured {timezone.localdate(batch.created_at)}. "
            "The context year is the capture year, not an event year."
        )))
        try:
            proposal = create_proposal(
                actor=actor, reason=f"Reviewed achievement paste import batch {batch.pk}; original source retained.",
                evidence="", operations=operations, submit=True,
            )
            apply_proposal(proposal_id=proposal.pk, actor=actor)
        except ValidationError as exc:
            message = " ".join(exc.messages)
            raise ValueError(message) from exc
        summary["receipt"] = {
            "created_result_ids": created_ids, "linked_result_ids": linked_ids,
            "context_result_id": context.pk, "correction_id": proposal.pk, "applied_at": timezone.now().isoformat(),
        }
        batch.status = ImportBatch.Status.APPLIED
        batch.save(update_fields=["status", "summary_json", "updated_at"])
        return batch
