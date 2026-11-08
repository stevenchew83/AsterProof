"""Role-gated preview, decision and history screens for ranking corrections."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from inspinia.rankings.correction_forms import CorrectionForm
from inspinia.rankings.models import Assessment
from inspinia.rankings.models import RankingCorrection
from inspinia.rankings.models import RankingCorrectionItem
from inspinia.rankings.models import RankingImportConflict
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentResult
from inspinia.rankings.services.corrections import FIELDS
from inspinia.rankings.services.corrections import StaleCorrection
from inspinia.rankings.services.corrections import apply_proposal
from inspinia.rankings.services.corrections import create_proposal
from inspinia.rankings.services.corrections import resolve_import_conflict
from inspinia.rankings.services.corrections import reverse_proposal
from inspinia.rankings.services.corrections import transition_proposal
from inspinia.rankings.views import _require_rankings_access
from inspinia.users.roles import user_has_admin_role

MAX_PK_DIGITS = 19

TARGET_MODELS = {
    "student": Student,
    "identity": Student,
    "result": StudentResult,
    "attribution": StudentResult,
    "profile": StudentResult,
    "claim": StudentResult,
    "school_alias": School,
    "assessment": Assessment,
    "metadata": Assessment,
    "scale": Assessment,
    "outcome_alias": Assessment,
}


def _common(request):
    _require_rankings_access(request)
    return {"can_apply_corrections": user_has_admin_role(request.user), "current": "analysis"}


def _profile_target_choices(kind, targets, target):
    if kind not in {"profile", "claim"}:
        return targets
    # Profile links identify a result; never render the full result archive in a select.
    return targets.filter(pk=target.pk) if target else targets.order_by("-pk")[:200]


@login_required
@never_cache
@require_http_methods(["GET"])
def correction_queue(request):
    context = _common(request)
    status = request.GET.get("status", "submitted")
    if status not in [*RankingCorrection.Status.values, "all"]:
        raise Http404
    proposals = RankingCorrection.objects.select_related("created_by", "decided_by").prefetch_related("items")
    if status != "all":
        proposals = proposals.filter(status=status)
    conflict_page = Paginator(
        RankingImportConflict.objects.filter(status="pending").select_related("batch", "correction"), 50,
    ).get_page(request.GET.get("conflict_page"))
    conflicts = list(conflict_page)
    for conflict in conflicts:
        conflict.has_unresolved_school = any(
            isinstance(operation.get("values", {}).get("school_id"), str)
            and operation["values"]["school_id"].startswith("new:")
            for operation in conflict.operations
        )
    context.update(
        page_obj=Paginator(proposals, 50).get_page(request.GET.get("page")),
        selected_status=status,
        statuses=RankingCorrection.Status.choices,
        history=False,
        conflicts=conflicts,
        conflict_count=RankingImportConflict.objects.filter(status="pending").count(),
        conflict_page_obj=conflict_page,
        schools=School.objects.only("pk", "name").order_by("name"),
    )
    return render(request, "pages/rankings/correction-queue.html", context)


@login_required
@never_cache
@require_http_methods(["GET"])
def correction_history(request):
    context = _common(request)
    proposals = (
        RankingCorrection.objects.exclude(status__in=["draft", "submitted"])
        .select_related("created_by", "decided_by")
        .prefetch_related("items")
    )
    context.update(
        page_obj=Paginator(proposals, 50).get_page(request.GET.get("page")),
        selected_status="all",
        history=True,
        conflicts=[],
    )
    return render(request, "pages/rankings/correction-queue.html", context)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def correction_new(request):  # noqa: C901 - One preview endpoint handles all typed correction forms.
    context = _common(request)
    params = request.POST if request.method == "POST" else request.GET
    kind = params.get("kind", "student")
    if kind not in FIELDS:
        raise Http404
    targets = TARGET_MODELS[kind].objects.all()
    if kind in {"result", "attribution", "profile", "claim"}:
        targets = targets.select_related("student", "assessment")
    target = None
    target_id = "" if request.method == "GET" and params.get("choose_type") else params.get("target", "")
    if target_id:
        if (
            len(str(target_id)) > MAX_PK_DIGITS
            or not str(target_id).isascii()
            or not str(target_id).isdigit()
            or not 0 < int(target_id) < 2**63
        ):
            raise Http404
        target = get_object_or_404(targets, pk=int(target_id))
    hints = {
        key: params[key] for key in ("band", "alias", "field", "second_student_id", "claim_type") if params.get(key)
    }
    if "second_student_id" in hints:
        if (
            len(hints["second_student_id"]) > MAX_PK_DIGITS
            or not hints["second_student_id"].isascii()
            or not hints["second_student_id"].isdigit()
        ):
            raise Http404
        hints["second_student_id"] = int(hints["second_student_id"])
    form, status = None, 200
    if target:
        form = CorrectionForm(request.POST or None, kind=kind, target_id=target.pk, hints=hints)
        if request.method == "POST" and form.is_valid():
            try:
                proposal = create_proposal(
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                    evidence=form.cleaned_data["evidence"],
                    operations=form.operations(),
                )
            except (ValidationError, ObjectDoesNotExist, ValueError) as exc:
                form.add_error(
                    None,
                    exc.messages
                    if isinstance(exc, ValidationError)
                    else "A selected record changed or is unavailable. Refresh the form.",
                )
                status = 400
            else:
                return redirect("rankings:correction_detail", pk=proposal.pk)
        elif request.method == "POST":
            status = 400
    elif request.method == "POST":
        raise Http404
    context.update(
        kind=kind,
        kinds=RankingCorrectionItem.Kind.choices,
        target=target,
        targets=_profile_target_choices(kind, targets, target),
        form=form,
        hints=hints,
    )
    return render(request, "pages/rankings/correction-new.html", context, status=status)


def _require_review_confirmation(value):
    if value != "yes":
        message = "Confirm that you reviewed the exact before/after values."
        raise ValidationError(message)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def correction_detail(request, pk):
    context = _common(request)
    proposal = get_object_or_404(
        RankingCorrection.objects.select_related("created_by", "decided_by", "reverses"),
        pk=pk,
    )
    status = 200
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "apply":
                if not context["can_apply_corrections"]:
                    raise PermissionDenied
                _require_review_confirmation(request.POST.get("confirm"))
                apply_proposal(proposal_id=proposal.pk, actor=request.user)
            elif action == "reverse":
                reverse = reverse_proposal(
                    proposal_id=proposal.pk,
                    actor=request.user,
                    reason=request.POST.get("reason", ""),
                )
                return redirect("rankings:correction_detail", pk=reverse.pk)
            else:
                transition_proposal(
                    proposal_id=proposal.pk,
                    actor=request.user,
                    action=action,
                    reason=request.POST.get("reason", ""),
                )
            messages.success(request, "Correction action recorded.")
            return redirect("rankings:correction_detail", pk=proposal.pk)
        except StaleCorrection as exc:
            context["action_error"], status = str(exc), 409
        except ValidationError as exc:
            context["action_error"], status = " ".join(exc.messages), 400
    items_page = Paginator(proposal.items.all(), 50).get_page(request.GET.get("page"))
    display_items = _display_items(list(items_page))
    context.update(
        proposal=proposal,
        items=display_items,
        item_count=items_page.paginator.count,
        items_page=items_page,
        can_manage_own=proposal.created_by_id == request.user.pk,
        closed=proposal.status not in {"draft", "submitted"},
    )
    return render(request, "pages/rankings/correction-detail.html", context, status=status)


@login_required
@never_cache
@require_http_methods(["POST"])
def import_conflict_action(request, pk):
    _common(request)
    if not user_has_admin_role(request.user):
        raise PermissionDenied
    get_object_or_404(RankingImportConflict, pk=pk)
    try:
        conflict = resolve_import_conflict(
            conflict_id=pk,
            actor=request.user,
            action=request.POST.get("action"),
            school_id=request.POST.get("school_id"),
        )
    except (ValidationError, ObjectDoesNotExist, ValueError) as exc:
        messages.error(
            request,
            " ".join(exc.messages)
            if isinstance(exc, ValidationError)
            else "Choose existing records in a new correction; this held row cannot be applied automatically.",
        )
    else:
        if conflict.correction_id and conflict.status == "pending":
            return redirect("rankings:correction_detail", pk=conflict.correction_id)
        messages.success(request, "Held import row resolved. The original partial-import receipt is preserved.")
    return redirect("rankings:correction_queue")


def _display_items(items):
    """Resolve human-readable review context in bounded bulk queries."""
    student_ids, result_ids, assessment_ids, school_ids = set(), set(), set(), set()
    for item in items:
        if item.kind in {"student", "identity"}:
            student_ids.add(item.target_id)
            if item.kind == "identity":
                student_ids.add(item.changes.get("second_student_id"))
        elif item.kind in {"result", "attribution", "profile", "claim"}:
            result_ids.add(item.target_id)
        elif item.kind in {"assessment", "metadata", "scale", "outcome_alias"}:
            assessment_ids.add(item.target_id)
        elif item.kind == "school_alias":
            school_ids.add(item.target_id)
        for values in (item.before.get("values", {}), item.changes):
            if values.get("school_id"):
                school_ids.add(values["school_id"])
    students = Student.objects.filter(pk__in=student_ids).only("id", "full_name", "birth_year").in_bulk()
    results = (
        StudentResult.objects.filter(pk__in=result_ids)
        .select_related("student", "assessment")
        .only(
            "id",
            "band",
            "student_id",
            "assessment_id",
            "student__id",
            "student__full_name",
            "assessment__id",
            "assessment__display_name",
        )
        .in_bulk()
    )
    assessments = (
        Assessment.objects.filter(pk__in=assessment_ids)
        .only(
            "id",
            "display_name",
            "assessment_date",
        )
        .in_bulk()
    )
    schools = School.objects.filter(pk__in=school_ids).only("id", "name").in_bulk()
    return [_display_item(item, students, results, assessments, schools) for item in items]


def _display_item(item, students, results, assessments, schools):
    values = item.before.get("values", {})
    label = f"Unavailable {item.kind.replace('_', ' ')} #{item.target_id}"
    if item.kind in {"student", "identity"} and item.target_id in students:
        student = students[item.target_id]
        label = f"{student.full_name} · birth year {student.birth_year or 'not recorded'} · student #{student.pk}"
        other = students.get(item.changes.get("second_student_id"))
        if item.kind == "identity" and other:
            label += f" / {other.full_name} · birth year {other.birth_year or 'not recorded'} · student #{other.pk}"
    elif item.kind in {"result", "attribution", "profile", "claim"} and item.target_id in results:
        result = results[item.target_id]
        label = (
            f"{result.student.full_name} · {result.assessment.display_name} · "
            f"category {result.band or 'not recorded'} · result #{result.pk}"
        )
    elif item.kind in {"assessment", "metadata", "scale", "outcome_alias"} and item.target_id in assessments:
        assessment = assessments[item.target_id]
        date_label = assessment.assessment_date.isoformat() if assessment.assessment_date else "date not recorded"
        label = f"{assessment.display_name} · {date_label} · assessment #{assessment.pk}"
    elif item.kind == "school_alias" and item.target_id in schools:
        school = schools[item.target_id]
        label = f"Canonical school: {school.name} · school #{school.pk}"
    dependency = ""
    if item.kind == "metadata" and item.changes.get("date_verified"):
        reviewed_date = item.before.get("dependency", {}).get("assessment_date") or "not recorded"
        dependency = f"Assessment date under review: {reviewed_date}"
    fields = []
    for key, value in item.changes.items():
        fields.append(
            {
                "name": key.replace("_", " ").capitalize(),
                "before": values.get(key),
                "after": value,
                "before_label": _review_value_label(key, values.get(key), schools),
                "after_label": _review_value_label(key, value, schools),
            },
        )
    return {
        "kind": item.get_kind_display(),
        "target_id": item.target_id,
        "target_label": label,
        "dependency_context": dependency,
        "existed": item.before.get("exists"),
        "fields": fields,
    }


def _review_value_label(key, value, schools):
    if key == "school_id" and value in schools:
        school = schools[value]
        return f"{school.name} · school #{school.pk}"
    return "—" if value is None else value
