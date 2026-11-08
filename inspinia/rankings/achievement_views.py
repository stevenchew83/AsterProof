"""Admin-only paste, editable preview, final confirmation and import receipt."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from inspinia.rankings.achievement_forms import AchievementRows
from inspinia.rankings.achievement_forms import AchievementSourceForm
from inspinia.rankings.achievement_forms import style_form
from inspinia.rankings.imports.achievement_text import EVIDENCE_CHOICES
from inspinia.rankings.imports.achievement_text import KIND
from inspinia.rankings.imports.achievement_text import MAX_ROWS
from inspinia.rankings.models import ImportBatch
from inspinia.rankings.models import Student
from inspinia.rankings.services.achievement_import import apply_paste
from inspinia.rankings.services.achievement_import import existing_choices
from inspinia.rankings.services.achievement_import import owned_batch
from inspinia.rankings.services.achievement_import import prepare_paste
from inspinia.rankings.services.achievement_import import require_import_admin
from inspinia.rankings.services.achievement_import import review_paste
from inspinia.rankings.services.achievement_import import student_records
from inspinia.users.models import AuditEvent
from inspinia.users.monitoring import record_event


def _batch(request, student, batch_id):
    try:
        return owned_batch(batch_id=batch_id, student_id=student.pk, actor=request.user)
    except (ImportBatch.DoesNotExist, ValueError, TypeError) as exc:
        raise Http404 from exc


def _rows(batch, data=None):
    summary = batch.summary_json
    sources = summary["rows"]
    initial = []
    reviewed = summary.get("reviewed_rows", sources)
    for index, row in enumerate(reviewed):
        source = sources[index] if index < len(sources) else {}
        initial.append({**source, **row})
    if len(initial) < MAX_ROWS:
        initial.append({
            "include": False, "record_type": "achievement", "discipline": "unknown",
            "evidence": summary["default_evidence"],
        })
    forms = AchievementRows(
        data, initial=initial, sources=sources, prefix="rows",
        existing_choices=existing_choices(student_records(summary["student_id"])),
    )
    for form in forms:
        style_form(form)
    return forms


def _receipt_rows(batch):
    labels = dict(EVIDENCE_CHOICES)
    choices = dict(existing_choices(student_records(batch.summary_json["student_id"])))
    return [
        {
            **row, "evidence_label": labels[row["evidence"]],
            "evidence_tone": (
                "danger" if "conflicting" in row["evidence"]
                else "warning" if "pending" in row["evidence"] else "secondary"
            ),
            "existing_label": choices.get(row["existing_result"], ""),
        }
        for row in batch.summary_json.get("reviewed_rows", []) if row.get("include")
    ]


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def achievement_text_import(request, student_id):  # noqa: C901, PLR0912 - Three explicit review stages.
    require_import_admin(request.user)
    student = get_object_or_404(Student, pk=student_id)
    source_form, batch, rows, stage = AchievementSourceForm(), None, None, "source"
    if request.POST.get("batch_id") or request.GET.get("batch"):
        batch = _batch(request, student, request.POST.get("batch_id") or request.GET["batch"])
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "preview":
            source_form = AchievementSourceForm(request.POST)
            if source_form.is_valid():
                data = source_form.cleaned_data
                batch = prepare_paste(
                    student=student, actor=request.user, source_text=data["source_text"],
                    source_label=data["source_label"], default_evidence=data["default_evidence"],
                )
                record_event(
                    event_type=AuditEvent.EventType.IMPORT_PREVIEWED, request=request,
                    message=f"Previewed achievement paste batch {batch.pk}", metadata={"batch_id": batch.pk},
                )
                return redirect(f"{request.path}?batch={batch.pk}")
        elif action == "review" and batch:
            rows = _rows(batch, request.POST)
            if rows.is_valid():
                try:
                    batch = review_paste(
                        batch_id=batch.pk, student_id=student.pk, actor=request.user, rows=rows.cleaned_data,
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    return redirect(f"{request.path}?batch={batch.pk}")
        elif action == "apply" and batch:
            if request.POST.get("confirm") != "yes":
                messages.error(request, "Confirm that you reviewed the selected rows and the source text.")
            else:
                try:
                    batch = apply_paste(
                        batch_id=batch.pk, student_id=student.pk, actor=request.user, nonce=request.POST.get("nonce"),
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    record_event(
                        event_type=AuditEvent.EventType.IMPORT_COMPLETED, request=request,
                        message=f"Applied achievement paste batch {batch.pk}", metadata={"batch_id": batch.pk},
                    )
                    messages.success(request, "Achievement import recorded; the original source text is preserved.")
                    return redirect(f"{request.path}?batch={batch.pk}")
        else:
            raise Http404
    if batch:
        stage = "receipt" if batch.status == ImportBatch.Status.APPLIED else "review"
        editing = rows is not None or request.GET.get("edit") or not batch.summary_json.get("review_nonce")
        if stage == "review" and editing:
            stage = "edit"
            rows = rows if rows is not None else _rows(batch)
    empty_row = style_form(rows.empty_form) if rows is not None else None
    if empty_row is not None:
        empty_row.initial.update(
            record_type="achievement", discipline="unknown", evidence=batch.summary_json["default_evidence"],
        )
    return render(request, "pages/rankings/achievement-text-import.html", {
        "student": student, "source_form": style_form(source_form), "batch": batch, "rows": rows,
        "stage": stage, "empty_row": empty_row,
        "review_rows": _receipt_rows(batch) if batch and stage in {"review", "receipt"} else [],
        "recent_batches": ImportBatch.objects.filter(
            created_by=request.user, summary_json__kind=KIND, summary_json__student_id=student.pk,
        ).order_by("-pk")[:10],
    })
