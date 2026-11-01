"""Phase-one community proof publication, private attempts, and human moderation."""

import hashlib
import uuid
from types import SimpleNamespace

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from inspinia.solutions.sharing import whatsapp_share_url
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role

from .community_forms import CONTENT_FIELDS
from .community_models import CommunityProblem
from .community_models import CommunityProblemReview
from .proof_forms import AttemptForm
from .proof_forms import ContentReportForm
from .proof_forms import PublicationForm
from .proof_forms import PublicationReviewForm
from .proof_forms import SolutionPublicationForm
from .proof_library import MAX_ASSETS
from .proof_library import MAX_ATTEMPT_BYTES
from .proof_library import active_publications
from .proof_library import ensure_statement_revision
from .proof_library import normalize_image
from .proof_library import public_snapshot
from .proof_library import public_solutions
from .proof_library import public_url
from .proof_library import publish_solution
from .proof_library import rate_limit
from .proof_library import require_admin
from .proof_library import save_attempt
from .proof_library import share_problem
from .proof_library import statement_approved
from .proof_models import CommunityAttempt
from .proof_models import CommunityContentReport
from .proof_models import CommunityPrivateAsset
from .proof_models import CommunitySolution
from .proof_models import CommunitySolutionAsset
from .proof_models import ModerationEvent
from .proof_models import ProblemPublication

MAX_MODERATION_REASON = 2000


def _member(request):
    if not user_can_access_app_features(request.user):
        raise PermissionDenied


def _errors(form, error):
    if isinstance(error, ObjectDoesNotExist):
        raise Http404 from error
    for message in error.messages:
        form.add_error(None, message)


def _public_page(request, template, context=None, *, status=200, noindex=False):
    values = {
        "page_title": "Community Proof Library",
        "page_description": "Explore and solve community mathematics problems.",
        "canonical_url": settings.PUBLIC_SITE_ORIGIN.rstrip("/") + request.path,
        "social_image_url": settings.PUBLIC_SITE_ORIGIN.rstrip("/") + static("images/asterproof-social.png"),
        "public_operator_name": settings.PUBLIC_OPERATOR_NAME,
        "hide_newsletter": True,
        "has_math": True,
        "active_nav": "community",
        "noindex": noindex,
        **(context or {}),
    }
    response = render(request, "pages/proof/" + template + ".html", values, status=status)
    response["Referrer-Policy"] = "same-origin"
    if noindex:
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def _unavailable(request):
    return _public_page(request, "public_unavailable", status=404, noindex=True)


def _media_prefix(token, solution_id):
    url = reverse("pages:proof_public_asset", args=[token, solution_id, "asset-placeholder"])
    return url.removesuffix("asset-placeholder")


def _decorate_solutions(solutions, token):
    rows = list(solutions)
    for solution in rows:
        solution.current_revision.media_prefix = _media_prefix(token, solution.pk)
    return rows


@never_cache
@require_GET
def proof_public_list(request):
    rows = active_publications().filter(visibility=ProblemPublication.Visibility.PUBLIC).order_by("-consented_at")
    return _public_page(
        request, "public_list", {"publications": Paginator(rows, 20).get_page(request.GET.get("page"))},
    )


@never_cache
@require_GET
def proof_public_problem(request, token):
    publication = active_publications().filter(token=token).first()
    if publication is None:
        return _unavailable(request)
    solutions = public_solutions(publication)
    current = solutions.filter(current_revision__statement_revision_id=publication.statement_revision_id)
    historical = solutions.exclude(current_revision__statement_revision_id=publication.statement_revision_id)
    current_page = Paginator(current, 10).get_page(request.GET.get("solutions_page"))
    historical_page = Paginator(historical, 10).get_page(request.GET.get("historical_page"))
    revision = publication.statement_revision
    return _public_page(
        request,
        "public_problem",
        {
            "publication": publication,
            "revision": revision,
            "snapshot": revision.snapshot,
            "token": token,
            "solutions": _decorate_solutions(current_page.object_list, token),
            "solutions_page": current_page,
            "solution_count": current.count(),
            "historical_solutions": _decorate_solutions(historical_page.object_list, token),
            "historical_page": historical_page,
            "page_title": revision.snapshot["title"],
            "whatsapp_url": whatsapp_share_url(settings.PUBLIC_SITE_ORIGIN.rstrip("/") + request.path),
        },
        noindex=publication.visibility != ProblemPublication.Visibility.PUBLIC,
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def proof_sharing(request, problem_id):
    _member(request)
    problem = get_object_or_404(CommunityProblem, pk=problem_id, author=request.user)
    publication = ProblemPublication.objects.filter(problem=problem).first()
    revision = problem.statement_revisions.filter(number=problem.version).first()
    initial = {
        "version": publication.version if publication else 0,
        "visibility": publication.visibility if publication else "private",
        "public_credit": publication.public_credit if publication else "Community contributor",
        "statement_revision": revision.pk if revision else None,
    }
    form = PublicationForm(request.POST or None, initial=initial)
    review_token = ""
    if request.method == "POST":
        if request.POST.get("action") == "stop":
            # Stopping does not require a fresh consent or a complete public form.
            data = {**initial, "version": request.POST.get("version")}
            form = PublicationForm({**data, "visibility": "private"})
        if form.is_valid():
            try:
                rate_limit(request.user, "sharing")
                publication, revision, review_token = share_problem(
                    request.user,
                    problem.pk,
                    form.cleaned_data,
                    action=request.POST.get("action", "preview"),
                    token=request.POST.get("review_token", ""),
                )
                if request.POST.get("action") in {"publish", "stop"}:
                    messages.success(request, "Sharing settings saved.")
                    return redirect("pages:proof_sharing", problem_id=problem.pk)
                form = PublicationForm(
                    initial={
                        **form.cleaned_data,
                        "version": publication.version,
                        "statement_revision": revision.pk,
                    },
                )
            except (ValidationError, ObjectDoesNotExist) as error:
                _errors(form, error)
    url = settings.PUBLIC_SITE_ORIGIN.rstrip("/") + public_url(publication) if publication else ""
    return render(
        request,
        "pages/proof/sharing.html",
        {
            "problem": problem,
            "publication": publication,
            "revision": revision,
            "snapshot": revision.snapshot if revision else public_snapshot(problem),
            "form": form,
            "review_token": review_token,
            "public_url": url if publication and active_publications().filter(pk=publication.pk).exists() else "",
            "whatsapp_url": whatsapp_share_url(url) if url else "",
            "can_publish": bool(
                revision and statement_approved(revision) and not (publication and publication.is_held),
            ),
        },
    )


def _attempt_response(request, revision, attempt=None):
    form = AttemptForm(
        request.POST or None,
        initial={
            "title": attempt.title if attempt else "",
            "body_source": attempt.body_source if attempt else "",
            "version": attempt.version if attempt else 0,
            "statement_revision": revision.pk,
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            rate_limit(request.user, "attempt-save", 200)
            saved = save_attempt(request.user, revision, form.cleaned_data, attempt_id=attempt.pk if attempt else None)
            messages.success(request, "Your private attempt is saved. Nothing was published.")
            return redirect("pages:proof_attempt_edit", attempt_id=saved.pk)
        except (ValidationError, ObjectDoesNotExist) as error:
            _errors(form, error)
    media_prefix = ""
    if attempt:
        media_prefix = reverse("pages:proof_attempt_asset", args=[attempt.pk, "asset-placeholder"]).removesuffix(
            "asset-placeholder",
        )
    return render(
        request,
        "pages/proof/attempt.html",
        {
            "problem": revision.problem,
            "revision": revision,
            "snapshot": revision.snapshot,
            "attempt": attempt,
            "form": form,
            "attempt_media_prefix": media_prefix,
            "upload_url": reverse("pages:proof_attempt_upload", args=[attempt.pk]) if attempt else "",
        },
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def proof_attempt(request, token):
    _member(request)
    publication = get_object_or_404(active_publications(), token=token)
    attempt = CommunityAttempt.objects.filter(
        owner=request.user,
        problem_id=publication.problem_id,
        statement_revision=publication.statement_revision,
    ).first()
    return _attempt_response(request, publication.statement_revision, attempt)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def proof_attempt_edit(request, attempt_id):
    _member(request)
    attempt = get_object_or_404(
        CommunityAttempt.objects.select_related("statement_revision", "statement_revision__problem"),
        pk=attempt_id,
        owner=request.user,
    )
    return _attempt_response(request, attempt.statement_revision, attempt)


@login_required
@never_cache
@require_POST
def proof_attempt_upload(request, attempt_id):
    _member(request)
    attempt = get_object_or_404(CommunityAttempt, pk=attempt_id, owner=request.user)
    try:
        rate_limit(request.user, "image-upload", 40)
        data = normalize_image(request.FILES.get("image"))
        with transaction.atomic():
            attempt = CommunityAttempt.objects.select_for_update().get(pk=attempt.pk, owner=request.user)
            used = sum(len(value) for value in attempt.assets.values_list("data", flat=True))
            if used + len(data) > MAX_ATTEMPT_BYTES or attempt.assets.count() >= MAX_ASSETS:
                msg = "This attempt has reached its image limit."
                raise ValidationError(msg)  # noqa: TRY301 - Return image validation as a safe HTTP 400.
            name = f"solution_body_images/{uuid.uuid4().hex}.png"
            CommunityPrivateAsset.objects.create(
                attempt=attempt,
                name=name,
                data=data,
                content_type="image/png",
                sha256=hashlib.sha256(data).hexdigest(),
            )
        return JsonResponse({"path": name})
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=400)


def _asset_response(asset):
    data = bytes(asset.data)
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise Http404
    response = HttpResponse(data, content_type=asset.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = 'inline; filename="diagram.png"'
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@login_required
@never_cache
@require_GET
def proof_attempt_asset(request, attempt_id, asset_name):
    _member(request)
    asset = get_object_or_404(
        CommunityPrivateAsset, attempt_id=attempt_id, attempt__owner=request.user, name=asset_name,
    )
    return _asset_response(asset)


@login_required
@never_cache
@require_GET
def proof_solution_asset(request, solution_id, revision_id, asset_name):
    _member(request)
    asset = get_object_or_404(
        CommunitySolutionAsset.objects.select_related("revision__solution"),
        revision_id=revision_id,
        revision__solution_id=solution_id,
        name=asset_name,
    )
    if asset.revision.solution.author_id != request.user.pk and not user_has_admin_role(request.user):
        raise Http404
    return _asset_response(asset)


def _review_media_prefix(revision):
    return reverse(
        "pages:proof_solution_asset",
        args=[
            revision.solution_id,
            revision.pk,
            "asset-placeholder",
        ],
    ).removesuffix("asset-placeholder")


@never_cache
@require_GET
def proof_public_asset(request, token, solution_id, asset_name):
    publication = active_publications().filter(token=token).first()
    if not publication:
        return _unavailable(request)
    solution = public_solutions(publication).filter(pk=solution_id).first()
    if not solution:
        return _unavailable(request)
    asset = get_object_or_404(CommunitySolutionAsset, revision_id=solution.current_revision_id, name=asset_name)
    return _asset_response(asset)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def proof_solution_publish(request, attempt_id):
    _member(request)
    attempt = get_object_or_404(
        CommunityAttempt.objects.select_related("statement_revision", "problem"),
        pk=attempt_id,
        owner=request.user,
    )
    solution_id = request.POST.get("solution_id") or request.GET.get("solution")
    solution = None
    if solution_id:
        try:
            solution_id = uuid.UUID(str(solution_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise Http404 from error
        solution = get_object_or_404(CommunitySolution, pk=solution_id, author=request.user, problem=attempt.problem)
    form = SolutionPublicationForm(
        request.POST or None,
        initial={
            "title": attempt.title or "My solution",
            "version": attempt.version,
            "public_credit": "Community contributor",
            "solution_id": solution.pk if solution else None,
        },
    )
    review_token = ""
    if request.method == "POST" and form.is_valid():
        try:
            rate_limit(request.user, "proof-publication", 20)
            solution, review_token = publish_solution(
                request.user,
                attempt.pk,
                form.cleaned_data,
                action=request.POST.get("action", "preview"),
                token=request.POST.get("review_token", ""),
                solution_id=form.cleaned_data.get("solution_id"),
            )
            if request.POST.get("action") == "submit":
                messages.success(request, "Your selected proof was submitted for publication moderation.")
                return redirect("pages:proof_solution_owner", solution_id=solution.pk)
        except (ValidationError, ObjectDoesNotExist) as error:
            _errors(form, error)
    return render(
        request,
        "pages/proof/solution_publish.html",
        {
            "attempt": attempt,
            "solution": solution,
            "revision": attempt.statement_revision,
            "snapshot": attempt.statement_revision.snapshot,
            "form": form,
            "body_source": attempt.body_source,
            "review_token": review_token,
            "attempt_media_prefix": reverse(
                "pages:proof_attempt_asset",
                args=[attempt.pk, "asset-placeholder"],
            ).removesuffix("asset-placeholder"),
        },
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def proof_solution_owner(request, solution_id):
    _member(request)
    solution = get_object_or_404(
        CommunitySolution.objects.select_related("current_revision", "current_revision__statement_revision"),
        pk=solution_id,
        author=request.user,
    )
    if request.method == "POST":
        with transaction.atomic():
            CommunityProblem.objects.select_for_update().get(pk=solution.problem_id)
            current = CommunitySolution.objects.select_for_update().get(pk=solution.pk, author=request.user)
            if request.POST.get("action") != "withdraw" or str(current.version) != request.POST.get("version"):
                return HttpResponse("Reload the current solution before withdrawing it.", status=409)
            current.status, current.version = CommunitySolution.Status.WITHDRAWN, current.version + 1
            current.save()
            ModerationEvent.objects.create(
                problem_id=current.problem_id,
                solution=current,
                solution_revision=current.current_revision,
                actor=request.user,
                action="proof_withdrawn",
            )
        return redirect("pages:proof_solution_owner", solution_id=solution.pk)
    revision = solution.current_revision
    if not revision:
        raise Http404
    revision.media_prefix = _review_media_prefix(revision)
    return render(
        request,
        "pages/proof/solution_owner.html",
        {
            "solution": solution,
            "proof_revision": revision,
            "snapshot": revision.statement_revision.snapshot,
            "revision": revision.statement_revision,
            "problem": revision.statement_revision.problem,
            "attempt": revision.source_attempt,
        },
    )


def _moderation_action(request, problem, solution=None):
    action = request.POST.get("action", "review")
    if action not in {"hold", "release", "resolve_report"}:
        return False
    reason = (request.POST.get("reason") or request.POST.get("notes") or "").strip()
    if not reason or len(reason) > MAX_MODERATION_REASON:
        msg = "Provide a reason of at most 2,000 characters."
        raise ValidationError(msg)
    if action == "resolve_report":
        report = get_object_or_404(
            CommunityContentReport.objects.select_for_update(),
            pk=request.POST.get("report_id"),
            problem=problem,
        )
        report.status, report.reviewed_by = "resolved", request.user
        report.save()
    elif solution:
        if str(solution.version) != request.POST.get("control_version"):
            message = "The publication controls changed. Reload before changing a hold."
            raise ValidationError(message)
        solution.is_held = action == "hold"
        solution.version += 1
        solution.save()
    else:
        publication, _ = ProblemPublication.objects.select_for_update().get_or_create(problem=problem)
        if str(publication.version) != request.POST.get("control_version"):
            message = "The publication controls changed. Reload before changing a hold."
            raise ValidationError(message)
        publication.is_held, publication.hold_reason = action == "hold", reason
        publication.version += 1
        publication.save()
    ModerationEvent.objects.create(
        problem=problem,
        solution=solution,
        actor=request.user,
        action=action,
        reason=reason,
    )
    return True


@transaction.atomic
def _review(request, problem_id, data, solution_id=None):
    problem = CommunityProblem.objects.select_for_update().get(pk=problem_id)
    solution = None
    if solution_id:
        solution = CommunitySolution.objects.select_for_update().get(pk=solution_id, problem=problem)
    if _moderation_action(request, problem, solution):
        return
    current_version = solution.version if solution else problem.version
    if current_version != data["version"]:
        msg = "The submitted version changed. Reload before deciding."
        raise ValidationError(msg)
    decision = data["decision"]
    if solution:
        if solution.status != CommunitySolution.Status.PENDING:
            message = (
                "Only an author's pending submission can receive a publication decision. Use hold controls otherwise."
            )
            raise ValidationError(message)
        if not solution.current_revision_id:
            msg = "This contribution has no saved proof to review."
            raise ValidationError(msg)
        solution.status, solution.version = decision, solution.version + 1
        solution.save()
        revision = solution.current_revision.statement_revision
    else:
        revision = ensure_statement_revision(problem)
        problem.status, problem.review_notes = decision, data["notes"]
        problem.reviewed_by, problem.reviewed_at = request.user, timezone.now()
        problem.save(update_fields=["status", "review_notes", "reviewed_by", "reviewed_at", "updated_at"])
        CommunityProblemReview.objects.create(
            problem=problem,
            version=problem.version,
            reviewer=request.user,
            decision=decision,
            notes=data["notes"],
            content_snapshot={
                name: getattr(problem, name).isoformat()
                if name == "embargo_until" and getattr(problem, name)
                else getattr(problem, name)
                for name in CONTENT_FIELDS
            },
        )
    ModerationEvent.objects.create(
        problem=problem,
        solution=solution,
        statement_revision=revision,
        solution_revision=solution.current_revision if solution else None,
        actor=request.user,
        action=("proof_" if solution else "statement_") + decision,
        reason=data["notes"],
    )


def _moderation_response(request, problem, solution=None):
    revision = (
        solution.current_revision.statement_revision
        if solution and solution.current_revision
        else problem.statement_revisions.filter(number=problem.version).first()
    )
    form = PublicationReviewForm(
        request.POST or None, initial={"version": solution.version if solution else problem.version},
    )
    if request.method == "POST":
        action = request.POST.get("action", "review")
        if action not in {"review", "hold", "release", "resolve_report"}:
            form.add_error(None, "Choose a valid moderation action.")
            action = "invalid"
        if action in {"hold", "release", "resolve_report"} or form.is_valid():
            try:
                _review(
                    request,
                    problem.pk,
                    form.cleaned_data if action == "review" else {},
                    solution.pk if solution else None,
                )
                messages.success(request, "Publication moderation saved. This does not verify a mathematical proof.")
                return redirect(request.path)
            except (ValidationError, ObjectDoesNotExist) as error:
                _errors(form, error)
    proof_revision = solution.current_revision if solution else None
    if proof_revision:
        proof_revision.media_prefix = _review_media_prefix(proof_revision)
    publication = ProblemPublication.objects.filter(problem=problem).first()
    return render(
        request,
        "pages/proof/moderation.html",
        {
            "problem": problem,
            "revision": revision,
            "snapshot": revision.snapshot if revision else public_snapshot(problem),
            "solution": solution,
            "proof_revision": proof_revision,
            "form": form,
            "control_version": solution.version if solution else publication.version if publication else 0,
            "events": problem.moderation_events.select_related("actor").order_by("-created_at")[:50],
            "reports": problem.content_reports.select_related("reporter").filter(status="open")[:50],
            "pending_solutions": problem.community_solutions.filter(status="pending").select_related(
                "current_revision",
            ),
        },
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def proof_moderation(request, problem_id):
    require_admin(request.user)
    return _moderation_response(request, get_object_or_404(CommunityProblem, pk=problem_id))


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def proof_solution_moderation(request, solution_id):
    require_admin(request.user)
    solution = get_object_or_404(
        CommunitySolution.objects.select_related("current_revision", "problem"), pk=solution_id,
    )
    return _moderation_response(request, solution.problem, solution)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def proof_report(request, token, solution_id=None):
    _member(request)
    publication = get_object_or_404(active_publications(), token=token)
    solution = get_object_or_404(public_solutions(publication), pk=solution_id) if solution_id else None
    form = ContentReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            rate_limit(request.user, "content-report", 10)
            CommunityContentReport.objects.create(
                problem_id=publication.problem_id,
                solution=solution,
                reporter=request.user,
                **form.cleaned_data,
            )
            messages.success(request, "Your report was sent privately to the publication moderators.")
            return redirect(public_url(publication))
        except ValidationError as error:
            _errors(form, error)
    return render(
        request,
        "pages/proof/report.html",
        {
            "problem": SimpleNamespace(title=publication.statement_revision.snapshot["title"]),
            "snapshot": publication.statement_revision.snapshot,
            "solution": solution,
            "form": form,
            "token": token,
        },
    )
