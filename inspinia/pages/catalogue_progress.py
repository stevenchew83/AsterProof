"""Personal progress over published memberships, without rebuilding source mappings."""

from collections import defaultdict

from django.core.paginator import Paginator
from django.db.models import BooleanField
from django.db.models import Case
from django.db.models import Count
from django.db.models import Exists
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django.db.models.functions import Lower
from django.db.models.functions import Trim
from django.urls import reverse
from django.utils.http import urlencode

from inspinia.pages.catalogue_browser import canonical_concept
from inspinia.pages.catalogue_browser import concept_problem_url
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueConceptArea
from inspinia.pages.catalogue_models import CatalogueProblem
from inspinia.pages.catalogue_snapshots import SnapshotChangedError
from inspinia.pages.catalogue_snapshots import current_snapshot
from inspinia.pages.catalogue_snapshots import scope_counts
from inspinia.pages.catalogue_snapshots import user_progress_summary
from inspinia.pages.completion_record_fields import SOLVED_STATUSES
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.technique_progress import resolve_technique_progress_user
from inspinia.pages.technique_progress import technique_progress_user_options

SUBJECTS = {
    "algebra": "Algebra",
    "combinatorics": "Combinatorics",
    "geometry": "Geometry",
    "number-theory": "Number Theory",
}
PAGE_SIZE = 25


def progress_problem_query(user, snapshot, concept_id, *, area="", subject=""):
    link_filters = {"concept_links__concept_id": concept_id}
    if area:
        link_filters["concept_links__area_id"] = area
    elif subject:
        link_filters["concept_links__area__subject__name"] = subject
    query = CatalogueProblem.objects.filter(snapshot=snapshot, **link_filters)
    own = UserProblemCompletion.objects.filter(user=user, statement_id=OuterRef("statement_id"))
    legacy = UserProblemCompletion.objects.filter(user=user, problem_id=OuterRef("problem_id"))
    return (
        query.distinct()
        .annotate(
            status=Lower(
                Trim(
                    Coalesce(
                        Subquery(own.values("status")[:1]),
                        Subquery(legacy.values("status")[:1]),
                        Value("unattempted"),
                    ),
                ),
            ),
            completion_date=Case(
                When(Exists(own), then=Subquery(own.values("completion_date")[:1])),
                default=Subquery(legacy.values("completion_date")[:1]),
            ),
        )
        .annotate(
            is_solved=Case(
                When(status__in=SOLVED_STATUSES, then=Value(value=True)),
                default=Value(value=False),
                output_field=BooleanField(),
            ),
        )
    )


def display_problem(row):
    return {
        **row,
        "url": concept_problem_url(row),
        "status_label": dict(UserProblemCompletion.Status.choices).get(row["status"], "Unattempted"),
    }


def build_progress_context(*, request_user, params, topic_slug=""):  # noqa: C901, PLR0912, PLR0915
    if topic_slug and topic_slug not in SUBJECTS:
        raise ValueError(topic_slug)
    user, can_select = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=str(params.get("user", "")),
    )
    subject = SUBJECTS.get(topic_slug, "")
    filters = {k: str(params.get(k, "")).strip() for k in ("area", "concept", "q", "state", "mode", "sort")}
    filters["q"] = filters["q"][:160]
    filters["user"] = str(user.pk) if can_select else ""
    if filters["mode"] not in {"areas", "concepts", "problems"}:
        filters["mode"] = "areas"
    if filters["state"] not in {"available", "remaining", "completed", "empty"}:
        filters["state"] = "available"
    if filters["sort"] not in {"name", "progress"}:
        filters["sort"] = "remaining"

    current_route = (
        reverse("pages:technique_progress_topic_detail", args=[topic_slug])
        if topic_slug
        else reverse("pages:technique_dashboard")
    )

    def link(*, slug=topic_slug, **changes):
        route = current_route if slug == topic_slug else (
            reverse("pages:technique_progress_topic_detail", args=[slug])
            if slug
            else reverse("pages:technique_dashboard")
        )
        query = urlencode({k: v for k, v in {**filters, **changes}.items() if v})
        return route + ("?" + query if query else "")

    base = {
        "selected_user": user,
        "can_select_user": can_select,
        "user_options": technique_progress_user_options() if can_select else [],
        "subject": subject,
        "filters": filters,
        "catalogue_url": reverse("pages:topic_tag_dashboard"),
    }
    snapshot = current_snapshot()
    if snapshot is None:
        return {**base, "progress_unavailable": True}
    try:
        personal = user_progress_summary(user, snapshot)
    except SnapshotChangedError:
        return {**base, "progress_unavailable": True}
    area_metadata = {a["id"]: a for a in CatalogueArea.objects.values("id", "name", "subject__name")}
    memberships = defaultdict(set)
    for cid, area_id in CatalogueConceptArea.objects.values_list("concept_id", "area_id"):
        memberships[cid].add(area_id)
    # Reviewed problem contexts can differ from a concept's default location.
    # Preserve these accepted contexts in progress without changing the catalogue.
    for key in snapshot.totals:
        if key.startswith("ca:"):
            area_id, cid = key[3:].rsplit(":", 1)
            memberships[cid].add(area_id)
    scope_areas = [a for a in area_metadata.values() if not subject or a["subject__name"] == subject]
    if filters["area"] not in {a["id"] for a in scope_areas}:
        filters["area"] = ""
    selected_area = area_metadata.get(filters["area"])
    concepts = []
    for c in CatalogueConcept.objects.filter(redirect__isnull=True).values("id", "name"):
        locations = sorted(
            a
            for a in memberships[c["id"]]
            if a in area_metadata
            and (not subject or area_metadata[a]["subject__name"] == subject)
            and (not selected_area or a == selected_area["id"])
        )
        if not locations:
            continue
        chosen = area_metadata[locations[0]]
        key = (
            f"ca:{selected_area['id']}:{c['id']}"
            if selected_area
            else f"cs:{subject}:{c['id']}"
            if subject
            else f"c:{c['id']}"
        )
        concepts.append(
            {
                "id": c["id"],
                "label": c["name"],
                "subject": chosen["subject__name"],
                "area": chosen["name"],
                "area_key": chosen["id"],
                "area_keys": locations,
                **scope_counts(snapshot, personal, key),
            },
        )
    areas = []
    for a in scope_areas:
        if selected_area and a["id"] != selected_area["id"]:
            continue
        children = [c for c in concepts if a["id"] in c["area_keys"]]
        areas.append(
            {
                "id": a["id"],
                "label": a["name"],
                "subject": a["subject__name"],
                "concepts": len(children),
                "available": sum(bool(c["total"]) for c in children),
                "practiced": sum(
                    bool(scope_counts(snapshot, personal, f"ca:{a['id']}:{c['id']}")["solved"]) for c in children
                ),
                **scope_counts(snapshot, personal, f"a:{a['id']}"),
            },
        )
    selected = None
    if filters["concept"] and CatalogueConcept.objects.filter(pk=filters["concept"]).exists():
        canonical = canonical_concept(filters["concept"])
        selected = next((c for c in concepts if c["id"] == canonical.pk), None)
    if not selected:
        filters["concept"] = ""
        if filters["mode"] == "problems":
            filters["mode"] = "concepts"
    else:
        filters["concept"] = selected["id"]
    for c in concepts:
        c["url"] = (
            link(
                concept=c["id"],
                mode="problems",
                q="",
                state="remaining" if c["remaining"] else "completed" if c["total"] else "available",
            )
            + "#progress-explorer"
        )
    for a in areas:
        a["url"] = link(area=a["id"], concept="", mode="concepts", state="available", q="") + "#progress-explorer"
    scope = f"a:{selected_area['id']}" if selected_area else f"s:{subject}" if subject else "all"
    stats = {
        **scope_counts(snapshot, personal, scope),
        "practiced": sum(bool(c["solved"]) for c in concepts),
        "concepts": sum(bool(c["total"]) for c in concepts),
        "areas": sum(bool(a["total"]) for a in areas),
    }
    subject_rows = [
        {
            "label": name,
            **scope_counts(snapshot, personal, f"s:{name}"),
            "active": name == subject,
            "url": link(slug=slug, area="", concept="", mode="areas", q=""),
        }
        for slug, name in SUBJECTS.items()
    ]

    def state_matches(row, state):
        return {
            "available": row["total"] > 0,
            "remaining": row["remaining"] > 0,
            "completed": row["total"] > 0 and row["remaining"] == 0,
            "empty": row["total"] == 0,
        }[state]

    rows = concepts if filters["mode"] == "concepts" else areas
    state_tabs = [
        {
            "value": state,
            "label": label,
            "count": sum(state_matches(r, state) for r in rows),
            "url": link(state=state, concept="") + "#progress-explorer",
        }
        for state, label in (
            ("available", "With problems"),
            ("remaining", "To practice"),
            ("completed", "Completed"),
            ("empty", "No problems"),
        )
    ]
    if filters["mode"] == "problems":
        query = progress_problem_query(user, snapshot, selected["id"], area=filters["area"], subject=subject)
        counts = query.aggregate(
            total=Count("id", distinct=True),
            solved=Count("id", filter=Q(status__in=SOLVED_STATUSES), distinct=True),
        )
        state_tabs = [
            {"value": state, "label": label, "count": count, "url": link(state=state) + "#progress-explorer"}
            for state, label, count in (
                ("available", "All problems", counts["total"]),
                ("remaining", "Remaining", counts["total"] - counts["solved"]),
                ("completed", "Completed", counts["solved"]),
            )
        ]
        if filters["state"] in {"remaining", "completed"}:
            query = query.filter(is_solved=filters["state"] == "completed")
        else:
            filters["state"] = "available"
        for token in filters["q"].split():
            query = query.filter(label__icontains=token)
        query = query.order_by("is_solved", F("mohs").asc(nulls_last=True), "-year", "label").values(
            "statement_id",
            "problem_id",
            "statement_uuid",
            "problem_uuid",
            "label",
            "subject",
            "mohs",
            "status",
            "is_solved",
            "completion_date",
        )
        page = Paginator(query, PAGE_SIZE).get_page(params.get("page"))
        page.object_list = [display_problem(p) for p in page.object_list]
        export_rows = (display_problem(p) for p in query.iterator()) if params.get("export") == "csv" else []
    else:
        matching = [r for r in rows if state_matches(r, filters["state"])]
        for token in filters["q"].casefold().split():
            alias_ids = (
                set(CatalogueConcept.objects.filter(aliases__label__icontains=token).values_list("id", flat=True))
                if filters["mode"] == "concepts"
                else set()
            )
            matching = [
                r
                for r in matching
                if token in f"{r['label']} {r['subject']} {r.get('area', '')} {r['id']}".casefold()
                or r["id"] in alias_ids
            ]
        sorts = {
            "name": lambda r: (r["label"].casefold(), r["subject"]),
            "progress": lambda r: (-r["percent"], -r["solved"], r["label"].casefold()),
            "remaining": lambda r: (-r["remaining"], r["label"].casefold()),
        }
        matching.sort(key=sorts[filters["sort"]])
        page, export_rows = Paginator(matching, PAGE_SIZE).get_page(params.get("page")), matching
    candidates = sorted(
        (c for c in concepts if c["remaining"]),
        key=lambda c: (not bool(c["solved"]), -c["remaining"], c["label"].casefold()),
    )[:4]
    notes = None
    if selected:
        from inspinia.pages.concept_progress import _study_notes

        notes = _study_notes(selected["id"])
    return {
        **base,
        "snapshot": snapshot,
        "stats": stats,
        "subject_rows": subject_rows,
        "scope_areas": sorted(
            ({"id": a["id"], "label": a["name"], "subject": a["subject__name"]} for a in scope_areas),
            key=lambda a: a["label"],
        ),
        "selected_area": {"id": selected_area["id"], "label": selected_area["name"]} if selected_area else None,
        "selected_concept": selected,
        "selected_summary": selected,
        "study_notes": notes,
        "practice_rows": candidates,
        "progress_page": page,
        "state_tabs": state_tabs,
        "mode_tabs": [
            {
                "label": label,
                "value": mode,
                "url": link(mode=mode, concept="", state="available", q="") + "#progress-explorer",
            }
            for mode, label in (("areas", "Areas"), ("concepts", "Concepts"))
        ],
        "all_subjects_url": link(slug="", area="", concept="", mode="areas", q=""),
        "clear_area_url": link(area="", concept="", q="", mode="areas", state="available"),
        "back_to_concepts_url": link(concept="", mode="concepts", state="available", q="") + "#progress-explorer",
        "pagination_url": link(),
        "form_url": reverse("pages:technique_progress_topic_detail", args=[topic_slug])
        if topic_slug
        else reverse("pages:technique_dashboard"),
        "export_url": link(export="csv"),
        "export_rows": export_rows,
        "completion_url": reverse("pages:completion_quick_update")
        + ("?" + urlencode({"target_user_id": user.pk}) if can_select else ""),
        "unmapped_total": snapshot.unmapped.get(subject or "all", 0),
    }
