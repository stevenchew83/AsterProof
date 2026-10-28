"""Search published problem memberships and load tags only for the visible page."""

from collections import defaultdict

from django.core.paginator import Paginator
from django.db.models import Exists
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Q

from inspinia.pages.catalogue_models import CatalogueProblem
from inspinia.pages.catalogue_models import CatalogueProblemConcept
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique

PAGE_SIZE = 25
MAX_MOHS_FILTER_DIGITS = 9
SORT_OPTIONS = {
    "mohs": "MOHS: low to high",
    "mohs_desc": "MOHS: high to low",
    "newest": "Newest first",
    "problem": "Problem name",
}


def problem_filters(params):
    filters = {"q": str(params.get("q", "")).strip()[:160]}
    for key in ("mohs_min", "mohs_max"):
        value = str(params.get(key, "")).strip()
        # Bound inputs to the database's integer range before constructing SQL.
        filters[key] = (
            str(int(value))
            if value.isascii() and value.isdecimal() and len(value) <= MAX_MOHS_FILTER_DIGITS
            else ""
        )
    sort = str(params.get("sort", "mohs"))
    filters["sort"] = sort if sort in SORT_OPTIONS else "mohs"
    return filters


def _search(query, text):
    own_tags = StatementTopicTechnique.objects.filter(statement_id=OuterRef("statement_id"))
    archive_tags = ProblemTopicTechnique.objects.filter(record_id=OuterRef("problem_id"))
    memberships = CatalogueProblemConcept.objects.filter(problem_id=OuterRef("pk"))
    for token in text.split():
        concepts = memberships.filter(
            Q(concept__name__icontains=token)
            | Q(concept__pk__icontains=token)
            | Q(concept__aliases__label__icontains=token),
        )
        query = query.filter(
            Q(label__icontains=token)
            | Q(problem_uuid__icontains=token)
            | Q(statement_uuid__icontains=token)
            | Q(Exists(concepts))
            | Q(Exists(own_tags.filter(technique__icontains=token)))
            | Q(~Exists(own_tags), Exists(archive_tags.filter(technique__icontains=token))),
        )
    return query


def _load_visible_details(problems):
    statement_tags = defaultdict(list)
    for statement_id, label in (
        StatementTopicTechnique.objects.filter(statement_id__in=[p.statement_id for p in problems if p.statement_id])
        .order_by("technique")
        .values_list("statement_id", "technique")
    ):
        statement_tags[statement_id].append(label)
    archive_tags = defaultdict(list)
    for record_id, label in (
        ProblemTopicTechnique.objects.filter(
            record_id__in=[p.problem_id for p in problems if p.problem_id and p.statement_id not in statement_tags],
        )
        .order_by("technique")
        .values_list("record_id", "technique")
    ):
        archive_tags[record_id].append(label)
    concepts = defaultdict(dict)
    for problem_id, concept_id, name in (
        CatalogueProblemConcept.objects.filter(problem_id__in=[p.pk for p in problems])
        .order_by("concept__name", "concept_id")
        .values_list("problem_id", "concept_id", "concept__name")
    ):
        concepts[problem_id][concept_id] = {"id": concept_id, "name": name}
    for problem in problems:
        problem.concepts = list(concepts[problem.pk].values())
        # Any own statement tag suppresses linked fallback, including invalid tags.
        problem.source_tags = statement_tags.get(problem.statement_id, archive_tags[problem.problem_id])


def problem_page(snapshot, params, *, area, concept):
    filters = problem_filters(params)
    memberships = CatalogueProblemConcept.objects.filter(problem_id=OuterRef("pk"))
    if area:
        memberships = memberships.filter(area=area)
    if concept:
        memberships = memberships.filter(concept=concept)
    query = CatalogueProblem.objects.filter(snapshot=snapshot).filter(Exists(memberships))
    query = _search(query, filters["q"])
    for key, lookup in (("mohs_min", "mohs__gte"), ("mohs_max", "mohs__lte")):
        if filters[key]:
            query = query.filter(**{lookup: int(filters[key])})
    ordering = {
        "mohs": [F("mohs").asc(nulls_last=True), "-year", "label", "pk"],
        "mohs_desc": [F("mohs").desc(nulls_last=True), "-year", "label", "pk"],
        "newest": ["-year", "label", "pk"],
        "problem": ["label", "pk"],
    }
    page = Paginator(query.order_by(*ordering[filters["sort"]]), PAGE_SIZE).get_page(params.get("page"))
    _load_visible_details(list(page))
    return page
