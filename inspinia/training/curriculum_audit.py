"""Bounded, read-only identity inventory; fingerprints never export private text."""

from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db.models import Count

from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueConceptArea
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.training.content_packs import rollout_manifest
from inspinia.training.models import Material
from inspinia.training.models import Problem
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic
from inspinia.training.taxonomy import TRAINING_TAXONOMY

MAX_AUDIT_ROWS = 500
MAX_CANONICAL_NODES = 5000


def _normalise(value):
    return " ".join(value.casefold().split())


def audit_learning_scope(*, area_id=None, subject_id=None, limit=200):  # noqa: C901, PLR0915 - Bounded inventory only.
    """No writes, inferred migrations, account details, source bodies or permissions."""
    from inspinia.learning.legacy import source_fingerprint
    from inspinia.learning.models import LegacyContentLink
    from inspinia.website.models import LibraryArea
    from inspinia.website.models import LibraryConcept
    from inspinia.website.models import LibraryLecture

    if type(limit) is not int or not 1 <= limit <= MAX_AUDIT_ROWS:
        msg = "Choose an audit sample limit between 1 and 500."
        raise ValidationError(msg)
    areas = CatalogueArea.objects.all()
    if subject_id:
        if not CatalogueSubject.objects.filter(pk=subject_id).exists():
            msg = "Unknown catalogue subject."
            raise ValidationError(msg)
        areas = areas.filter(subject_id=subject_id)
    if area_id:
        areas = areas.filter(pk=area_id)
        if not areas.exists():
            msg = "Unknown area in the selected subject."
            raise ValidationError(msg)
    area_rows = list(areas.values("id", "name", "subject_id")[: MAX_AUDIT_ROWS + 1])
    if len(area_rows) > MAX_AUDIT_ROWS:
        msg = "The catalogue exceeds the reviewed area bound."
        raise ValidationError(msg)
    area_ids = {row["id"] for row in area_rows}
    concepts = CatalogueConcept.objects.filter(redirect__isnull=True, memberships__area_id__in=area_ids).distinct()
    canonical = list(concepts.values("id", "name")[: MAX_CANONICAL_NODES + 1])
    if len(canonical) > MAX_CANONICAL_NODES:
        msg = "The catalogue exceeds the reviewed concept bound."
        raise ValidationError(msg)
    names = defaultdict(set)
    for row in canonical:
        names[_normalise(row["name"])].add(row["id"])
    area_names = defaultdict(set)
    for row in area_rows:
        area_names[_normalise(row["name"])].add(row["id"])
    subjects = {row["subject_id"] for row in area_rows}
    training_topics = Topic.objects.filter(slug__in=subjects | {"foundations"})
    sources = {
        "material": Material.objects.filter(subtopic__topic__in=training_topics),
        "area": LibraryArea.objects.filter(subject__in=subjects),
        "concept": LibraryConcept.objects.filter(area__subject__in=subjects),
        "lecture": LibraryLecture.objects.filter(concept__area__subject__in=subjects),
    }
    inventory = {}
    for kind, query in sources.items():
        count = query.count()
        rows = list(query.order_by("pk")[:limit])
        links = {
            getattr(link, f"{kind}_id"): link
            for link in LegacyContentLink.objects.filter(**{f"{kind}_id__in": [row.pk for row in rows]})
        }
        items = []
        for source in rows:
            explicit = getattr(source, "catalogue_area_id", None) or getattr(source, "catalogue_concept_id", None)
            candidates = area_names if kind == "area" else names
            proposed = sorted(candidates.get(_normalise(source.title), set()))
            link = links.get(source.pk)
            fingerprint = source_fingerprint(source)
            items.append(
                {
                    "id": source.pk,
                    "fingerprint": fingerprint,
                    "canonical_id": explicit,
                    "candidate_ids": proposed,
                    "candidate_state": "explicit"
                    if explicit
                    else "ambiguous"
                    if len(proposed) > 1
                    else "candidate_only"
                    if proposed
                    else "unmapped",
                    "reviewed_document_id": str(link.document_id) if link else None,
                    "mapping_current": bool(link and link.source_fingerprint == fingerprint),
                    "cutover": bool(link and link.is_cutover),
                },
            )
        inventory[kind] = {"count": count, "sampled": len(items), "truncated": count > len(items), "items": items}
    duplicates = {}
    for label, model, field in (
        ("areas", LibraryArea, "catalogue_area_id"),
        ("concepts", LibraryConcept, "catalogue_concept_id"),
    ):
        duplicates[label] = list(
            model.objects.filter(**{f"{field}__isnull": False})
            .values(field)
            .annotate(count=Count("pk"))
            .filter(count__gt=1)
            .order_by(field)[:limit],
        )
    foundations = next(row for row in TRAINING_TAXONOMY if row["slug"] == "foundations")
    legacy_foundations = list(Subtopic.objects.filter(topic__slug="foundations").values("id", "title")[:limit])
    manifest = rollout_manifest()
    planned = {row["id"]: row for row in manifest["areas"]}
    return {
        "scope": {"subject_id": subject_id, "area_id": area_id, "limit": limit},
        "catalogue_revision": CatalogueState.objects.filter(pk=1).values_list("source_revision", flat=True).first(),
        "catalogue": {
            "subjects": sorted(subjects),
            "areas": len(area_rows),
            "canonical_concepts": len(canonical),
            "concept_placements": CatalogueConceptArea.objects.filter(area_id__in=area_ids).count(),
        },
        "areas": [
            {
                "id": row["id"],
                "rollout_owner": "Steven",
                "status": planned.get(row["id"], {}).get("status", "unassigned"),
                "milestone": planned.get(row["id"], {}).get("milestone"),
            }
            for row in area_rows
        ],
        "legacy": inventory,
        "duplicate_canonical_pages": duplicates,
        "training_problem_count": Problem.objects.filter(subtopic__topic__in=training_topics).count(),
        "training_problem_identity": "Separate legacy IDs; no canonical problem UUID inferred.",
        "foundations": [
            {
                "competency": title,
                "legacy_subtopic_ids": [
                    row["id"] for row in legacy_foundations if _normalise(row["title"]) == _normalise(title)
                ],
                "mapping": "unreviewed",
            }
            for title in foundations["subtopics"]
        ],
        "effects": "Read-only candidate inventory; no title-based links, publication, points or source changes.",
    }
