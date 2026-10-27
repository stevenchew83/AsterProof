"""Catalogue-only navigation; problem examples use published memberships on demand."""

from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models import Q
from django.http import Http404
from django.urls import reverse
from django.utils.http import urlencode

from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueConceptAlias
from inspinia.pages.catalogue_models import CatalogueConceptRelation
from inspinia.pages.catalogue_models import CatalogueProblem
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.pages.catalogue_snapshots import current_snapshot
from inspinia.pages.technique_concepts import SUBJECT_LABELS

PAGE_SIZE = 25
ROLE_LABELS = {
    "technique": "Technique",
    "canonical_subtopic": "Topic",
    "object": "Object",
    "method": "Method",
    "lemma": "Lemma / theorem",
    "proof_role": "Proof role",
    "role": "Proof role",
}


def catalogue_url(**params):
    query = urlencode({k: v for k, v in params.items() if v})
    return reverse("pages:topic_tag_dashboard") + (f"?{query}" if query else "")


def concept_problem_url(row):
    if row["statement_uuid"]:
        return reverse("pages:problem_statement_detail", args=[row["statement_uuid"]])
    return reverse("solutions:problem_solution_list", args=[row["problem_uuid"]])


def canonical_concept(cid):
    if not cid:
        return None
    concept, seen = CatalogueConcept.objects.filter(pk=cid).first(), set()
    if concept is None:
        message = "Concept was not found."
        raise Http404(message)
    while concept.redirect_id:
        if concept.pk in seen:
            message = "Concept redirect is unavailable."
            raise Http404(message)
        seen.add(concept.pk)
        concept = CatalogueConcept.objects.get(pk=concept.redirect_id)
    return concept


def build_catalogue_context(params):  # noqa: C901, PLR0912, PLR0915
    raw_subject = str(params.get("subject") or params.get("topic") or params.get("domain") or "").strip()
    raw_subject = SUBJECT_LABELS.get(raw_subject.casefold(), raw_subject)
    subject = (
        CatalogueSubject.objects.filter(Q(pk=raw_subject) | Q(name__iexact=raw_subject)).first()
        if raw_subject
        else None
    )
    area = CatalogueArea.objects.select_related("subject").filter(pk=params.get("area", "")).first()
    if area:
        subject = area.subject
    concept = canonical_concept(str(params.get("concept", "")).strip())
    locations = []
    if concept:
        locations = list(
            CatalogueArea.objects.filter(memberships__concept=concept)
            .select_related("subject")
            .order_by("subject__position", "name", "pk"),
        )
        if not area or area.pk not in {a.pk for a in locations}:
            choices = [a for a in locations if not subject or a.subject_id == subject.pk]
            primary = concept.metadata.get("primary_area")
            area = next((a for a in choices if a.pk == primary), next(iter(choices or locations), None))
        if area:
            subject = area.subject
    q = str(params.get("q", "")).strip()[:160]
    role = str(params.get("role", "")).strip()
    if role == "role":
        role = "proof_role"
    if role not in ROLE_LABELS:
        role = ""
    scope = {"subject": subject.pk if subject else "", "area": area.pk if area else ""}
    search_scope = {**scope, "q": q, "role": role}
    breadcrumbs = [{"label": "All subjects", "url": catalogue_url()}]
    if subject:
        breadcrumbs.append({"label": subject.name, "url": catalogue_url(subject=subject.pk)})
    if area:
        breadcrumbs.append({"label": area.name, "url": catalogue_url(**scope)})
    if concept:
        # Parent links are explicit relationships, not inferred from matching words.
        ancestors, seen = [], {concept.pk}
        child = concept
        while len(ancestors) < 12:  # noqa: PLR2004 - bound malformed/cyclic curator data.
            parent = (
                CatalogueConceptRelation.objects.filter(
                    target=child,
                    kind="narrower",
                    source__redirect__isnull=True,
                )
                .select_related("source")
                .order_by("source_id")
                .first()
            )
            if not parent or parent.source_id in seen:
                break
            child = parent.source
            seen.add(child.pk)
            ancestors.append({"label": child.name, "url": catalogue_url(**scope, concept=child.pk)})
        breadcrumbs.extend(reversed(ancestors))
        breadcrumbs.append({"label": concept.name, "url": catalogue_url(**scope, concept=concept.pk)})
    subjects = list(CatalogueSubject.objects.annotate(area_count=Count("areas", distinct=True)))
    for row in subjects:
        row.url = catalogue_url(subject=row.pk)
    areas = (
        list(
            CatalogueArea.objects.filter(subject=subject).annotate(
                concept_count=Count("memberships", filter=Q(memberships__concept__redirect__isnull=True)),
            ),
        )
        if subject
        else []
    )
    for row in areas:
        row.url = catalogue_url(subject=subject.pk, area=row.pk)
    rows, level = [], "subjects"
    if concept or area or q or role:
        level = "concepts"
        query = CatalogueConcept.objects.filter(redirect__isnull=True)
        if concept:
            query = query.filter(incoming_relations__source=concept, incoming_relations__kind="narrower")
        elif area:
            query = query.filter(memberships__area=area)
        elif subject:
            query = query.filter(memberships__area__subject=subject)
        if role:
            query = query.filter(aliases__role__in=["role", "proof_role"] if role == "proof_role" else [role])
        for token in q.split():
            query = query.filter(
                Q(name__icontains=token) | Q(pk__icontains=token) | Q(aliases__label__icontains=token),
            )
        page = Paginator(query.distinct().order_by("name", "pk"), PAGE_SIZE).get_page(params.get("page"))
        rows = [
            {
                "id": c.pk,
                "name": c.name,
                "description": c.description,
                "roles": [ROLE_LABELS.get(r, r.replace("_", " ").title()) for r in c.roles],
                "url": catalogue_url(**scope, concept=c.pk),
            }
            for c in page
        ]
    elif subject:
        level = "areas"
        page = Paginator(areas, PAGE_SIZE).get_page(params.get("page"))
        rows = [{"id": a.pk, "name": a.name, "count": a.concept_count, "url": a.url} for a in page]
    else:
        page = Paginator(subjects, PAGE_SIZE).get_page(params.get("page"))
        rows = [{"id": s.pk, "name": s.name, "count": s.area_count, "url": s.url} for s in page]
    tab = "problems" if concept and params.get("tab") == "problems" else "structure"
    examples, snapshot, examples_unavailable = None, None, False
    if tab == "problems":
        snapshot = current_snapshot()
        if snapshot:
            link_filters = {"concept_links__concept": concept}
            if area:
                link_filters["concept_links__area"] = area
            query = CatalogueProblem.objects.filter(snapshot=snapshot, **link_filters)
            examples = Paginator(query.distinct().order_by("-year", "label"), PAGE_SIZE).get_page(params.get("page"))
            for p in examples:
                p.url = concept_problem_url({"statement_uuid": p.statement_uuid, "problem_uuid": p.problem_uuid})
        else:
            examples_unavailable = True
    return {
        "selected_subject": subject,
        "selected_area": area,
        "selected_concept": concept,
        "subjects": subjects,
        "areas": areas,
        "breadcrumbs": breadcrumbs,
        "rows": rows,
        "level": level,
        "page": page,
        "q": q,
        "role": role,
        "role_options": {key: label for key, label in ROLE_LABELS.items() if key != "role"},
        "scope_inputs": scope,
        "tab": tab,
        "root_url": catalogue_url(),
        "up_url": breadcrumbs[-2]["url"] if len(breadcrumbs) > 1 else "",
        "heading": concept.name
        if concept
        else area.name
        if area
        else subject.name
        if subject
        else "Mathematics catalogue",
        "pagination_url": catalogue_url(**search_scope, concept=concept.pk if concept else "", tab=tab),
        "structure_url": catalogue_url(**scope, concept=concept.pk if concept else ""),
        "examples_url": catalogue_url(**scope, concept=concept.pk if concept else "", tab="problems"),
        "examples": examples,
        "examples_unavailable": examples_unavailable,
        "snapshot": snapshot,
        "aliases": Paginator(concept.aliases.select_related("subject"), PAGE_SIZE).get_page(params.get("alias_page"))
        if concept
        else [],
        "locations": [
            {
                "label": f"{a.subject.name} / {a.name}",
                "url": catalogue_url(
                    subject=a.subject_id,
                    area=a.pk,
                    concept=concept.pk,
                ),
            }
            for a in locations
        ],
        "held_aliases": CatalogueConceptAlias.objects.filter(
            Q(subject=subject) if subject else Q(),
            concept__isnull=True,
        ).select_related("subject")[:25]
        if not concept
        else [],
        "related": [
            {"name": r.target.name, "url": catalogue_url(**scope, concept=r.target_id)}
            for r in (
                CatalogueConceptRelation.objects.filter(source=concept, kind="related").select_related("target")[:25]
            )
        ]
        if concept
        else [],
        "progress_url": reverse("pages:technique_dashboard")
        + (
            "?"
            + urlencode(
                {
                    "area": area.pk if area else "",
                    "concept": concept.pk if concept else "",
                    "mode": "problems" if concept else "concepts",
                },
            )
            if area or concept
            else ""
        ),
    }
