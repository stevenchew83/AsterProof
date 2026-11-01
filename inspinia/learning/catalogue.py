"""Bounded catalogue navigation over canonical identities and current publications."""

from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models import Q
from django.urls import reverse

from inspinia.learning.publication import visible_publications
from inspinia.pages.catalogue_browser import canonical_concept
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueSubject

ROLE_LABELS = {
    "lemma": "Theorem or lemma",
    "method": "Method",
    "technique": "Technique",
    "object": "Object",
    "proof_role": "Proof method",
    "canonical_subtopic": "Subtopic",
}


def explore_url(**values):
    query = urlencode({key: value for key, value in values.items() if value})
    return reverse("learning:explore") + ("?" + query if query else "")


def subject_rows():
    rows = list(CatalogueSubject.objects.annotate(area_total=Count("areas", distinct=True)))
    for row in rows:
        row.explore_url = explore_url(subject=row.pk)
        row.concept_total = (
            CatalogueConcept.objects.filter(
                redirect__isnull=True,
                memberships__area__subject=row,
            )
            .distinct()
            .count()
        )
    return rows


def _filter_prerequisites(query, mode):
    if not mode:
        return query, True
    from inspinia.pages.catalogue_models import CatalogueState
    from inspinia.pages.prerequisite_models import PrerequisiteGraphState

    graph = PrerequisiteGraphState.objects.filter(pk=1).first()
    marker = CatalogueState.objects.filter(pk=1).values_list("source_revision", flat=True).first()
    if not graph or not graph.is_valid or marker is None or graph.validated_catalogue_revision != marker:
        return query.none(), False
    targets = {dependent for _prerequisite, dependent in graph.snapshot}
    return (query.filter(pk__in=targets) if mode == "has" else query.exclude(pk__in=targets)), True


def catalogue_context(params, user):  # noqa: C901 - Bounded, independent catalogue filters.
    subject = CatalogueSubject.objects.filter(pk=str(params.get("subject", ""))[:40]).first()
    area = CatalogueArea.objects.select_related("subject").filter(pk=str(params.get("area", ""))[:180]).first()
    if area:
        subject = area.subject
    concept = canonical_concept(str(params.get("concept", ""))[:160]) if params.get("concept") else None
    q = str(params.get("q", "")).strip()[:160]
    role = params.get("role", "")
    role = role if role in ROLE_LABELS else ""
    level = params.get("level", "")
    level = level if level in {"core", "advanced", "specialist"} else ""
    availability = params.get("availability", "")
    availability = availability if availability in {"available", "missing"} else ""
    query = CatalogueConcept.objects.filter(redirect__isnull=True)
    if area:
        query = query.filter(memberships__area=area)
    elif subject:
        query = query.filter(memberships__area__subject=subject)
    if concept:
        query = query.filter(pk=concept.pk)
    for token in q.split():
        query = query.filter(Q(name__icontains=token) | Q(aliases__label__icontains=token))
    if role:
        query = query.filter(Q(roles__icontains=role) | Q(aliases__role=role))
    published = visible_publications(user=user)
    if level:
        published = published.filter(revision__metadata__level=level)
        query = query.filter(teaching_revision_links__revision__current_publications__in=published)
    query = query.annotate(
        note_total=Count(
            "teaching_revision_links__revision__current_publications",
            filter=Q(teaching_revision_links__revision__current_publications__in=published),
            distinct=True,
        ),
    )
    if availability == "available":
        query = query.filter(note_total__gt=0)
    elif availability == "missing":
        query = query.filter(note_total=0)
    prerequisite_filter = params.get("prerequisites", "")
    prerequisite_filter = prerequisite_filter if prerequisite_filter in {"has", "none"} else ""
    query, prerequisite_available = _filter_prerequisites(query, prerequisite_filter)
    page = Paginator(query.distinct().order_by("name", "pk"), 30).get_page(params.get("page"))
    for row in page:
        row.learning_url = reverse("learning:concept", args=[row.pk])
    areas = CatalogueArea.objects.select_related("subject")
    if subject:
        areas = areas.filter(subject=subject)
    areas = list(
        areas.annotate(
            concept_total=Count(
                "memberships",
                filter=Q(memberships__concept__redirect__isnull=True),
                distinct=True,
            ),
        ),
    )
    for row in areas:
        row.learning_url = reverse("learning:area", args=[row.pk])
    return {
        "subjects": subject_rows(),
        "subject": subject,
        "area": area,
        "concept": concept,
        "areas": areas,
        "page": page,
        "q": q,
        "role": role,
        "level": level,
        "prerequisite_filter": prerequisite_filter,
        "prerequisite_available": prerequisite_available,
        "filter_query": urlencode({key: value for key, value in params.items() if key != "page"}),
        "availability": availability,
        "roles": ROLE_LABELS.items(),
        "show_concepts": bool(subject or area or concept or q or role or level or availability),
    }
