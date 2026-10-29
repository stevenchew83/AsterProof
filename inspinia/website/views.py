from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods

from inspinia.solutions.examples import INEQUALITY_BLOCKS
from inspinia.training.markdown import render_markdown

from .forms import NewsletterForm
from .models import LibraryArea
from .models import LibraryConcept
from .models import LibraryLecture
from .models import Subject
from .newsletter import confirm_subscription
from .newsletter import request_subscription
from .newsletter import subscriber_from_token
from .newsletter import unsubscribe
from .solution_preview import solution_preview_context

SUBJECT_DESCRIPTIONS = {
    Subject.ALGEBRA: ("A", "Find structure in expressions, equations, and inequalities."),
    Subject.GEOMETRY: ("G", "See the relationships behind a construction."),
    Subject.NUMBER_THEORY: ("N", "Explore the patterns and arithmetic of integers."),
    Subject.COMBINATORICS: ("C", "Learn to count, organise, and reason discretely."),
}


def _subjects():
    return [
        {
            "slug": value,
            "title": label,
            "symbol": SUBJECT_DESCRIPTIONS[value][0],
            "description": SUBJECT_DESCRIPTIONS[value][1],
            "url": reverse("website:library_subject", kwargs={"subject": value}),
        }
        for value, label in Subject.choices
    ]


def _subject(slug):
    return next((row for row in _subjects() if row["slug"] == slug), None)


def _concepts():
    return LibraryConcept.objects.filter(is_published=True, area__is_published=True).select_related("area")


def _lectures():
    return LibraryLecture.objects.filter(
        is_published=True,
        concept__is_published=True,
        concept__area__is_published=True,
    ).select_related("concept", "concept__area")


def _page(request, template, *, status=200, **context):
    context.setdefault("newsletter_form", NewsletterForm(auto_id="newsletter_%s"))
    context.update(
        {
            "public_contact_email": settings.PUBLIC_CONTACT_EMAIL,
            "public_operator_name": settings.PUBLIC_OPERATOR_NAME,
            "public_subjects": _subjects(),
            "canonical_url": settings.PUBLIC_SITE_ORIGIN.rstrip("/") + request.path,
        },
    )
    response = render(request, "website/" + template + ".html", context, status=status)
    if context.get("noindex"):
        response["X-Robots-Tag"] = "noindex, nofollow"
        # no-referrer can turn form POST origins into "null" in browsers,
        # which correctly fails Django's CSRF checks. Keep tokens on-site.
        response["Referrer-Policy"] = "same-origin"
        response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def home_view(request):
    return _page(
        request, "home", page_title="A little insight. Infinite possibilities.", active_nav="home",
        has_math=True, **solution_preview_context(request),
    )


@require_GET
def problem_solving_view(request):
    workspace_url = reverse("pages:problem_statement_list")
    if not request.user.is_authenticated:
        workspace_url = reverse("account_login") + "?" + urlencode({"next": workspace_url})
    return _page(
        request,
        "problem_solving",
        page_title="Problem solving",
        page_description=(
            "Find olympiad problems by topic and MOHS difficulty, write proofs with live preview, "
            "and follow your personal progress in AsterProof."
        ),
        active_nav="problem_solving",
        has_math=True,
        hide_newsletter=True,
        workspace_url=workspace_url,
        example_blocks=INEQUALITY_BLOCKS,
        example_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    )


@require_GET
def about_view(request):
    return _page(request, "about", page_title="About", active_nav="about")


@require_GET
def contact_view(request):
    return _page(request, "contact", page_title="Contact", active_nav="contact")


@require_GET
def privacy_view(request):
    return _page(request, "privacy", page_title="Privacy Policy")


@require_GET
def terms_view(request):
    return _page(request, "terms", page_title="Terms of Use")


@require_GET
def library_view(request):
    query = request.GET.get("q", "").strip()[:100]
    concepts = _concepts().annotate(lecture_count=Count("lectures", filter=Q(lectures__is_published=True)))
    lectures = _lectures()
    areas = LibraryArea.objects.filter(is_published=True)
    if query:
        concepts = concepts.filter(Q(title__icontains=query) | Q(summary__icontains=query))
        lectures = lectures.filter(Q(title__icontains=query) | Q(summary__icontains=query))
        areas = areas.filter(Q(title__icontains=query) | Q(summary__icontains=query))
    return _page(
        request,
        "library",
        page_title="The Library",
        active_nav="library",
        query=query,
        concepts=list(concepts[:12]),
        lectures=list(lectures[:12]) if query else [],
        areas=list(areas[:12]),
    )


@require_GET
def library_subject_view(request, subject):
    subject_row = _subject(subject)
    if subject_row is None:
        raise Http404
    areas = LibraryArea.objects.filter(is_published=True, subject=subject).annotate(
        concept_count=Count("concepts", filter=Q(concepts__is_published=True)),
    )
    return _page(
        request,
        "library_subject",
        page_title=subject_row["title"],
        active_nav="library",
        subject=subject_row,
        areas=areas,
        breadcrumbs=[("Library", reverse("website:library"))],
    )


@require_GET
def library_area_view(request, subject, area_slug):
    area = get_object_or_404(LibraryArea, subject=subject, slug=area_slug, is_published=True)
    concepts = (
        _concepts()
        .filter(area=area)
        .annotate(
            lecture_count=Count("lectures", filter=Q(lectures__is_published=True)),
        )
    )
    return _page(
        request,
        "library_area",
        page_title=area.title,
        active_nav="library",
        area=area,
        concepts=concepts,
        rendered_content=render_markdown(area.body_markdown),
        has_math=bool(area.body_markdown),
        breadcrumbs=[
            ("Library", reverse("website:library")),
            (
                area.get_subject_display(),
                reverse(
                    "website:library_subject",
                    kwargs={"subject": subject},
                ),
            ),
        ],
    )


@require_GET
def library_concept_view(request, subject, area_slug, concept_slug):
    concept = get_object_or_404(_concepts(), area__subject=subject, area__slug=area_slug, slug=concept_slug)
    prerequisites = concept.prerequisites.filter(is_published=True, area__is_published=True).exclude(pk=concept.pk)
    return _page(
        request,
        "library_concept",
        page_title=concept.title,
        active_nav="library",
        concept=concept,
        lectures=_lectures().filter(concept=concept),
        prerequisites=prerequisites,
        rendered_content=render_markdown(concept.body_markdown),
        has_math=bool(concept.body_markdown),
        breadcrumbs=[("Library", reverse("website:library")), (concept.area.title, concept.area.get_absolute_url())],
    )


@require_GET
def library_lecture_view(request, subject, area_slug, concept_slug, lecture_slug):
    lecture = get_object_or_404(
        _lectures(),
        concept__area__subject=subject,
        concept__area__slug=area_slug,
        concept__slug=concept_slug,
        slug=lecture_slug,
    )
    return _page(
        request,
        "library_lecture",
        page_title=lecture.title,
        active_nav="library",
        lecture=lecture,
        rendered_content=render_markdown(lecture.body_markdown),
        has_math=True,
        breadcrumbs=[
            ("Library", reverse("website:library")),
            (lecture.concept.title, lecture.concept.get_absolute_url()),
        ],
    )


@transaction.non_atomic_requests
@require_http_methods(["GET", "POST"])
def newsletter_subscribe_view(request):
    form = NewsletterForm(request.POST if request.method == "POST" else None, auto_id="newsletter_%s")
    if request.method == "POST" and form.is_valid():
        if not form.cleaned_data["company"]:
            request_subscription(request, form.cleaned_data["email"])
        return redirect(reverse("website:newsletter_subscribe") + "?sent=1")
    return _page(
        request,
        "newsletter",
        page_title="Stay curious",
        newsletter_form=form,
        newsletter_mode="sent" if request.method == "GET" and request.GET.get("sent") == "1" else "subscribe",
        hide_newsletter=True,
        noindex=True,
    )


@transaction.non_atomic_requests
@require_http_methods(["GET", "POST"])
def newsletter_confirm_view(request, token):
    with transaction.atomic():
        subscriber = subscriber_from_token(token, for_update=request.method == "POST")
        confirmed = bool(subscriber and request.method == "POST" and confirm_subscription(subscriber))
    return _page(
        request,
        "newsletter",
        page_title="Confirm your subscription",
        newsletter_mode="confirm",
        valid_link=subscriber is not None,
        action_completed=confirmed,
        hide_newsletter=True,
        noindex=True,
    )


@transaction.non_atomic_requests
@require_http_methods(["GET", "POST"])
def newsletter_unsubscribe_view(request, token):
    with transaction.atomic():
        subscriber = subscriber_from_token(token, unsubscribe=True, for_update=request.method == "POST")
        completed = bool(subscriber and request.method == "POST")
        if completed:
            unsubscribe(subscriber)
    return _page(
        request,
        "newsletter",
        page_title="Newsletter preferences",
        newsletter_mode="unsubscribe",
        valid_link=subscriber is not None,
        action_completed=completed,
        hide_newsletter=True,
        noindex=True,
    )
