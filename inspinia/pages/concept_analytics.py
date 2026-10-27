"""Read-only, statement-first coverage of the mathematical concept catalogue."""

from collections import Counter
from collections import defaultdict
from itertools import batched
from statistics import median

from django.core.paginator import Paginator
from django.urls import reverse
from django.utils.http import urlencode

from inspinia.pages.concept_assignment_service import catalogue_definitions
from inspinia.pages.concept_assignment_service import observed_area_memberships
from inspinia.pages.concept_assignment_service import projection_enabled
from inspinia.pages.concept_assignment_service import projection_payloads
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.statement_concept_coverage import TAG_FIELDS
from inspinia.pages.statement_concept_coverage import TagCoverageResolver
from inspinia.pages.statement_concept_coverage import _coverage
from inspinia.pages.statement_concept_coverage import statement_coverage_payloads
from inspinia.pages.technique_concepts import CONCEPTS
from inspinia.pages.technique_concepts import SUBJECT_LABELS

PAGE_SIZE = 25
SOURCE_BATCH_SIZE = 256
SUBJECTS = ("Algebra", "Combinatorics", "Geometry", "Number Theory")


def _subject(value):
    return SUBJECT_LABELS.get(str(value).strip().casefold(), "")


def _area_key(concept):
    return f"{concept.get('subject', 'Algebra')}:{concept['area']}"


def _compact_coverage(payload, refs, *, assignment_mode):
    concepts = []
    for concept in payload["concept_coverage"]:
        if assignment_mode:
            key = (concept["id"], concept["subject"], concept["area_id"])
            reference = {field: concept[field] for field in ("id", "subject", "area_id", "area")}
        else:
            key = concept["id"]
            reference = {"id": key}
        concepts.append(refs.setdefault(key, reference))
    return {
        "concept_coverage": tuple(concepts),
        "concept_coverage_status": payload["concept_coverage_status"],
        "concept_source_tags": payload["concept_source_tags"],
    }


def library_coverage_rows(filters):
    """Return lightweight active library identities with authoritative concept mappings."""
    statements = (
        ContestProblemStatement.objects.filter(is_active=True)
        .select_related("linked_problem")
        .only(
            "id",
            "problem_uuid",
            "contest_year",
            "contest_name",
            "problem_code",
            "topic",
            "mohs",
            "is_active",
            "linked_problem_id",
            "statement_uuid",
            "linked_problem__topic",
            "linked_problem__mohs",
        )
    )
    # Any statement owns its archive link, including an inactive statement.
    archive = ProblemSolveRecord.objects.filter(is_active=True, statement_entries__isnull=True)
    options = {
        "contests": sorted(
            set(statements.order_by().values_list("contest_name", flat=True).distinct())
            | set(archive.order_by().values_list("contest", flat=True).distinct()),
        ),
        "years": sorted(
            set(statements.order_by().values_list("contest_year", flat=True).distinct())
            | set(archive.order_by().values_list("year", flat=True).distinct()),
            reverse=True,
        ),
    }
    for key, statement_field, archive_field in (
        ("contest", "contest_name", "contest"),
        ("year", "contest_year", "year"),
    ):
        if filters[key]:
            statements = statements.filter(**{statement_field: filters[key]})
            archive = archive.filter(**{archive_field: filters[key]})
    resolver = TagCoverageResolver()
    # Explorer rows need identity membership and status, not a full set of role
    # dictionaries for every problem/concept occurrence in the library.
    concept_refs = {}
    assignment_mode = projection_enabled()

    rows = {}
    for batch in batched(statements.order_by("id").iterator(chunk_size=SOURCE_BATCH_SIZE), SOURCE_BATCH_SIZE):
        payloads = statement_coverage_payloads(batch, resolver=resolver)
        for statement in batch:
            rows.setdefault(
                str(statement.problem_uuid),
                {
                    "statement_id": statement.pk,
                    "statement_uuid": statement.statement_uuid,
                    "problem_uuid": statement.problem_uuid,
                    "problem_id": statement.linked_problem_id,
                    "label": f"{statement.contest_name} {statement.contest_year} {statement.problem_code}",
                    "contest": statement.contest_name,
                    "year": statement.contest_year,
                    "subject": _subject(effective_topic(statement)),
                    "mohs": effective_mohs(statement),
                    **_compact_coverage(payloads[statement.pk], concept_refs, assignment_mode=assignment_mode),
                },
            )
    archive = archive.order_by("id").values("id", "problem_uuid", "contest", "year", "problem", "topic", "mohs")
    for batch in batched(archive.iterator(chunk_size=SOURCE_BATCH_SIZE), SOURCE_BATCH_SIZE):
        if assignment_mode:
            mapped = projection_payloads(load_sources([r["problem_uuid"] for r in batch]))
        else:
            tags = defaultdict(list)
            for tag in ProblemTopicTechnique.objects.filter(record_id__in=[r["id"] for r in batch]).order_by(
                "technique", "id",
            ).values("record_id", *TAG_FIELDS):
                tags[tag["record_id"]].append(tag)
            mapped = {
                str(r["problem_uuid"]): _coverage(tags[r["id"]], topic=r["topic"], active=True, resolver=resolver)
                for r in batch
            }
        for record in batch:
            rows.setdefault(
                str(record["problem_uuid"]),
                {
                    "statement_id": None,
                    "problem_id": record["id"],
                    "problem_uuid": record["problem_uuid"],
                    "label": f"{record['contest']} {record['year']} {record['problem']}",
                    "contest": record["contest"],
                    "year": record["year"],
                    "subject": _subject(record["topic"]),
                    "mohs": record["mohs"],
                    **_compact_coverage(
                        mapped[str(record["problem_uuid"])], concept_refs, assignment_mode=assignment_mode,
                    ),
                },
            )
    return rows, options


def library_problem_url(problem):
    """Resolve links only for visible rows or explicitly exported problems."""
    if problem["statement_id"]:
        return reverse("pages:problem_statement_detail", args=[problem["statement_uuid"]])
    return reverse("solutions:problem_solution_list", args=[problem["problem_uuid"]])


def _concept_row(cid, definition, problems):
    difficulties = [p["mohs"] for p in problems.values() if p["mohs"] is not None]
    return {
        "id": cid,
        "label": definition["label"],
        "subject": definition.get("subject", "Algebra"),
        "area": definition["area_label"],
        "area_key": _area_key(definition),
        "problem_count": len(problems),
        "contest_count": len({p["contest"] for p in problems.values()}),
        "median_mohs": median(difficulties) if difficulties else None,
        "rated_count": len(difficulties),
    }


def build_concept_analytics_context(params):  # noqa: C901, PLR0912, PLR0915
    filters = {
        key: str(params.get(key, "")).strip()
        for key in (
            "subject",
            "area",
            "contest",
            "year",
            "q",
            "state",
            "sort",
            "concept",
        )
    }
    filters["subject"] = _subject(filters["subject"] or params.get("topic", "") or params.get("domain", ""))
    if filters["year"] and not (
        filters["year"].isascii() and filters["year"].isdigit() and len(filters["year"]) == 4  # noqa: PLR2004
    ):
        filters["year"] = ""
    if filters["state"] not in {"covered", "gaps"}:
        filters["state"] = ""
    if filters["sort"] not in {"name", "fewest", "mohs"}:
        filters["sort"] = "problems"

    def link(**changes):
        values = {**filters, **changes}
        query = urlencode({k: v for k, v in values.items() if v and not (k == "sort" and v == "problems")})
        return reverse("pages:topic_tag_dashboard") + (f"?{query}" if query else "")

    library, options = library_coverage_rows(filters)
    assignment_mode = projection_enabled()
    definitions = (
        catalogue_definitions(filters["subject"], filters["area"], observed=observed_area_memberships(library))
        if assignment_mode
        else CONCEPTS
    )
    if assignment_mode:
        from inspinia.pages.concept_assignment_registry import REGISTRY

        filters["concept"] = REGISTRY.canonical(filters["concept"])
    catalogue = {
        cid: c
        for cid, c in definitions.items()
        if not filters["subject"] or c.get("subject", "Algebra") == filters["subject"]
    }
    area_options = sorted(
        {(_area_key(c), c["area_label"], c.get("subject", "Algebra")) for c in CONCEPTS.values()},
        key=lambda a: (a[2], a[1]),
    )
    if projection_enabled():
        from inspinia.pages.concept_assignment_registry import REGISTRY

        area_options = sorted(
            {
                (f"{a['subject']}:{a['area']}", a["label"], a["subject"])
                for d in REGISTRY.definitions.values()
                for a in d["area_memberships"]
            },
        )
    if filters["area"]:
        catalogue = {cid: c for cid, c in catalogue.items() if _area_key(c) == filters["area"]}
    scoped = {}
    for uuid, problem in library.items():
        ids = {
            c["id"]
            for c in problem["concept_coverage"]
            if (
                not assignment_mode
                or (
                    (not filters["subject"] or c["subject"] == filters["subject"])
                    and (not filters["area"] or f"{c['subject']}:{c.get('area_id', '')}" == filters["area"])
                )
            )
        } & catalogue.keys()
        if filters["area"] and not ids:
            continue
        if filters["subject"] and problem["subject"] != filters["subject"] and not ids:
            continue
        scoped[uuid] = {**problem, "concept_ids": ids}
    by_concept = defaultdict(dict)
    for uuid, problem in scoped.items():
        for cid in problem["concept_ids"]:
            by_concept[cid][uuid] = problem
    concepts = [_concept_row(cid, definition, by_concept[cid]) for cid, definition in catalogue.items()]
    areas = {}
    for concept in concepts:
        definition = catalogue[concept["id"]]
        memberships = definition.get(
            "area_memberships",
            [{"subject": concept["subject"], "area": definition["area"], "label": concept["area"]}],
        )
        for membership in memberships:
            key = f"{membership['subject']}:{membership['area']}"
            if filters["subject"] and membership["subject"] != filters["subject"]:
                continue
            if filters["area"] and key != filters["area"]:
                continue
            matches = by_concept[concept["id"]]
            if assignment_mode:
                matches = {
                    uuid: p
                    for uuid, p in matches.items()
                    if any(
                        c["id"] == concept["id"]
                        and c["subject"] == membership["subject"]
                        and c["area"] == membership["label"]
                        for c in p["concept_coverage"]
                    )
                }
            area = areas.setdefault(
                key,
                {
                    "key": key,
                    "label": membership["label"],
                    "subject": membership["subject"],
                    "total": 0,
                    "covered": 0,
                    "problems": set(),
                },
            )
            area["total"] += 1
            area["covered"] += bool(matches)
            area["problems"].update(matches)
    for area in areas.values():
        area.update(
            problem_count=len(area.pop("problems")),
            percent=round(100 * area["covered"] / area["total"]),
            url=link(area=area["key"], concept=""),
        )
    area_rows = sorted(areas.values(), key=lambda a: (-a["problem_count"], a["subject"], a["label"]))
    covered = sum(bool(c["problem_count"]) for c in concepts)
    quality = Counter(p["concept_coverage_status"] for p in scoped.values())
    review = sorted(
        (p for p in scoped.values() if p["concept_coverage_status"] != "Mapped"),
        key=lambda p: (-p["year"], p["label"]),
    )
    review_page = Paginator(review, PAGE_SIZE).get_page(params.get("review_page"))
    query = filters["q"].casefold().split()
    matching = [
        c for c in concepts if all(token in f"{c['label']} {c['area']} {c['subject']}".casefold() for token in query)
    ]
    if filters["state"]:
        matching = [c for c in matching if bool(c["problem_count"]) == (filters["state"] == "covered")]
    ordering = {
        "name": lambda c: (c["label"].casefold(), c["subject"]),
        "fewest": lambda c: (c["problem_count"], c["label"].casefold()),
        "mohs": lambda c: (-(c["median_mohs"] if c["median_mohs"] is not None else -1), c["label"].casefold()),
        "problems": lambda c: (-c["problem_count"], c["label"].casefold()),
    }
    matching.sort(key=ordering[filters["sort"]])
    page = Paginator(matching, PAGE_SIZE).get_page(params.get("page"))
    explorer_page = page.number if page.number > 1 else ""
    for concept in page.object_list:
        concept["url"] = link(concept=concept["id"], page=explorer_page) + "#concept-detail"
    selected = next((c for c in concepts if c["id"] == filters["concept"]), None)
    problem_page = None
    if selected:
        problem_page = Paginator(
            sorted(by_concept[selected["id"]].values(), key=lambda p: (-p["year"], p["label"])),
            PAGE_SIZE,
        ).get_page(params.get("problem_page"))
    for problem in [*review_page.object_list, *(problem_page.object_list if problem_page else ())]:
        problem["url"] = library_problem_url(problem)
    active = [
        {"label": label, "value": filters[key], "url": link(**{key: "", "concept": ""})}
        for key, label in (("subject", "Subject"), ("area", "Area"), ("contest", "Contest"), ("year", "Year"))
        if filters[key]
    ]
    for item in active:
        if item["label"] == "Area" and filters["area"] in areas:
            item["value"] = areas[filters["area"]]["label"]
        if item["label"] == "Subject":
            item["url"] = link(subject="", area="", concept="")
    return {
        "filters": filters,
        "subjects": SUBJECTS,
        "area_options": area_options,
        "filter_options": options,
        "active_filters": active,
        "reset_url": reverse("pages:topic_tag_dashboard"),
        "scope_inputs": {k: filters[k] for k in ("subject", "area", "contest", "year") if filters[k]},
        "stats": {
            "problems": len(scoped),
            "mapped": sum(bool(p["concept_ids"]) for p in scoped.values()),
            "areas": sum(bool(a["problem_count"]) for a in area_rows),
            "catalogue": len(concepts),
            "covered": covered,
            "gaps": len(concepts) - covered,
            "percent": round(100 * covered / len(concepts)) if concepts else 0,
        },
        "area_rows": area_rows,
        "concept_page": page,
        "selected_concept": selected,
        "problem_page": problem_page,
        "close_detail_url": link(concept="", page=explorer_page),
        "problem_pagination_url": link(page=explorer_page),
        "quality": {
            "mapped": quality["Mapped"],
            "untagged": quality["Untagged"],
            "review": sum(v for k, v in quality.items() if k not in {"Mapped", "Untagged"}),
            "total": len(review),
            "rows": review_page.object_list,
            "page": review_page,
            "expanded": bool(params.get("review_page")),
        },
        "state_tabs": [
            {"label": label, "value": value, "count": count, "url": link(state=value, concept="")}
            for value, label, count in (
                ("", "All concepts", len(concepts)),
                ("covered", "With problems", covered),
                ("gaps", "Coverage gaps", len(concepts) - covered),
            )
        ],
        "pagination_url": link(),
    }
