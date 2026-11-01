"""One read-only library over existing problem identities and user-owned progress."""

import uuid
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.db.models import Exists
from django.db.models import Max
from django.db.models import Min
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models.functions import Trim
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.algebra_tag_search import tag_token_query
from inspinia.pages.completion_record_fields import SOLVED_STATUSES
from inspinia.pages.contest_links import contest_dashboard_listing_url
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.shared_progress import shared_progress_learners
from inspinia.pages.statement_analytics import annotate_effective_statement_analytics
from inspinia.pages.statement_concept_coverage import problem_concept_search
from inspinia.pages.statement_concept_coverage import problem_coverage_payloads
from inspinia.pages.statement_concept_coverage import statement_concept_search
from inspinia.pages.topic_labels import display_topic_label
from inspinia.solutions.models import ProblemSolution

FILTER_KEYS = ("q", "year", "topic", "confidence", "mohs_min", "mohs_max", "concept")


def library_sources(*, active_only=False):
    """Pair by existing UUID/reference only; never merge matching human labels."""
    statements = ContestProblemStatement.objects.all()
    references = ContestProblemStatement.objects.filter(
        Q(linked_problem_id=OuterRef("pk")) | Q(problem_uuid=OuterRef("problem_uuid")),
    )
    problems = ProblemSolveRecord.objects.alias(_library_has_statement=Exists(references)).filter(
        _library_has_statement=False,
    )
    if active_only:
        statements = statements.filter(is_active=True)
        problems = problems.filter(is_active=True)
    return statements, problems


def solved_statements(statements, user):
    """Explicit statement progress takes precedence over the same user's legacy row."""
    own = UserProblemCompletion.objects.filter(user=user, statement_id=OuterRef("pk"))
    legacy = UserProblemCompletion.objects.filter(
        Q(problem_id=OuterRef("linked_problem_id")) | Q(problem__problem_uuid=OuterRef("problem_uuid")),
        user=user, statement__isnull=True, status__in=SOLVED_STATUSES,
    )
    return statements.alias(
        _library_has_progress=Exists(own),
        _library_solved=Exists(own.filter(status__in=SOLVED_STATUSES)),
        _library_legacy_solved=Exists(legacy),
    ).filter(Q(_library_solved=True) | Q(_library_has_progress=False, _library_legacy_solved=True))


def solved_problems(problems, user):
    return problems.filter(Exists(UserProblemCompletion.objects.filter(
        user=user, problem_id=OuterRef("pk"), status__in=SOLVED_STATUSES,
    )))


def progress_context(request):
    """Reuse existing shared-progress authority; never resolve arbitrary user IDs."""
    options = [{"value": "my", "label": "My progress", "user": request.user}]
    options.extend(
        {"value": row["slug"], "label": f"{row['label']}'s progress", "user": row["user"]}
        for row in shared_progress_learners(request.user)
        if row["user"].pk != request.user.pk
    )
    selected = request.GET.get("learner", "my") or "my"
    subject = next((row for row in options if row["value"] == selected), None)
    if subject is None:
        raise PermissionDenied
    return subject, [{"value": row["value"], "label": row["label"]} for row in options]


def _concept_filter(query, concept, *, statement):
    if not concept:
        return query
    from inspinia.pages.concept_assignment_registry import REGISTRY
    from inspinia.pages.concept_assignment_service import accepted_problem_ids
    from inspinia.pages.concept_assignment_service import projection_enabled

    canonical = REGISTRY.canonical(concept)
    if projection_enabled():
        return query.filter(problem_uuid__in=accepted_problem_ids(canonical))
    definition = REGISTRY.definitions.get(canonical)
    search = statement_concept_search if statement else problem_concept_search
    return query.filter(search(definition["label"] if definition else concept))


def filtered_sources(statements, problems, filters):
    from inspinia.pages.views import _filter_statement_queryset

    try:
        identity = uuid.UUID(filters.get("q") or "")
    except ValueError:
        identity = None
    statement_filters = {key: filters.get(key, "") for key in FILTER_KEYS if key != "concept"}
    if identity:
        statement_filters["q"] = ""
    statements = _filter_statement_queryset(statements, **statement_filters, include_concepts=True)
    if identity:
        statements = statements.filter(Q(problem_uuid=identity) | Q(statement_uuid=identity))
    problems = _filter_problem_metadata(problems, filters)
    problems = problems.filter(problem_uuid=identity) if identity else _search_problems(problems, filters.get("q", ""))
    return (
        _concept_filter(statements, filters.get("concept"), statement=True),
        _concept_filter(problems, filters.get("concept"), statement=False),
    )


def _filter_problem_metadata(problems, filters):
    from inspinia.pages.views import _statement_topic_filter_values

    year = filters.get("year", "")
    if year:
        problems = problems.none() if not year.isdigit() else problems.filter(year=int(year))
    if filters.get("topic"):
        problems = problems.filter(topic__in=_statement_topic_filter_values(filters["topic"]))
    if filters.get("confidence"):
        problems = problems.filter(confidence=filters["confidence"])
    for key, lookup in (("mohs_min", "mohs__gte"), ("mohs_max", "mohs__lte")):
        try:
            value = int(filters[key])
        except (ValueError, KeyError):
            continue
        problems = problems.filter(**{lookup: value})
    return problems


def _search_problems(problems, query):
    for token in query.split():
        tags = ProblemTopicTechnique.objects.filter(
            tag_token_query(token, source="problem"), record_id=OuterRef("pk"),
        )
        match = (
            Q(contest__icontains=token) | Q(contest_year_problem__icontains=token)
            | Q(problem__icontains=token) | Q(topic__icontains=token) | Q(confidence__icontains=token)
            | Q(imo_slot_guess_value__icontains=token) | Q(core_ideas_value__icontains=token)
            | Q(rationale_value__icontains=token) | Q(pitfalls_value__icontains=token)
            | Q(Exists(tags)) | problem_concept_search(token)
        )
        if token.isdigit():
            match |= Q(year=int(token))
        problems = problems.filter(match)
    return problems


def problem_rows(problems, *, viewer, progress_user):
    from inspinia.pages.views import _completion_board_state_kind
    from inspinia.pages.views import _completion_board_state_label
    from inspinia.pages.views import _difficulty_rating_payload
    from inspinia.pages.views import _format_imo_slot_label
    from inspinia.pages.views import _statement_completion_sort_value

    problems = list(problems)
    ids = [problem.pk for problem in problems]
    completions = {
        row.problem_id: row
        for row in UserProblemCompletion.objects.filter(user=progress_user, problem_id__in=ids)
    }
    visible_solutions = set(ProblemSolution.objects.filter(problem_id__in=ids).filter(
        Q(author=viewer) | Q(status=ProblemSolution.Status.PUBLISHED),
    ).values_list("problem_id", flat=True))
    coverage = problem_coverage_payloads(problems)
    rows = []
    for problem in problems:
        completion = completions.get(problem.pk)
        solved = completion is not None and completion.status in SOLVED_STATUSES
        date = completion.completion_date if solved else None
        solution_page = reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
        rows.append({
            "contest_name": problem.contest, "contest_year": problem.year,
            "contest_year_problem": (
                problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
            ),
            "day_label": "", "problem_code": problem.problem, "is_active": problem.is_active,
            "is_active_label": "Active" if problem.is_active else "Inactive",
            "is_linked": True, "has_statement": False, "statement_uuid": "",
            "problem_uuid": str(problem.problem_uuid), "linked_problem_uuid": str(problem.problem_uuid),
            "statement_detail_url": solution_page, "solution_start_url": "",
            "problem_destination_label": "View" if problem.pk in visible_solutions else "Start",
            "problem_destination_url": (
                solution_page if problem.pk in visible_solutions
                else reverse("solutions:problem_solution_edit", args=[problem.problem_uuid])
            ),
            "linked_problem_topic": display_topic_label(problem.topic), "linked_problem_mohs": problem.mohs,
            "linked_problem_mohs_url": (
                contest_dashboard_listing_url(problem.contest, mohs=problem.mohs) if problem.mohs is not None else ""
            ),
            "linked_problem_confidence": problem.confidence or "", "linked_problem_confidence_url": "",
            "linked_problem_imo_slot_guess_value": problem.imo_slot_guess_value or "",
            "linked_problem_imo_slot_display": _format_imo_slot_label(problem.imo_slot_guess_value or ""),
            "linked_problem_imo_slot_url": "", "linked_problem_topic_tag_links": [],
            "linked_problem_topic_tags": coverage[problem.pk]["concept_source_tags"],
            "user_completion_date": date.isoformat() if date else "",
            "user_completion_display": date.isoformat() if date else ("Unknown date" if solved else "Unsolved"),
            "user_completion_is_solved": solved,
            "user_completion_state_kind": _completion_board_state_kind(is_solved=solved, completion_date=date),
            "user_completion_state_label": _completion_board_state_label(is_solved=solved, completion_date=date),
            "user_completion_sort": _statement_completion_sort_value(is_solved=solved, completion_date=date),
            "updated_at": timezone.localtime(problem.created_at).strftime("%Y-%m-%d %H:%M"),
            "updated_at_sort": problem.created_at.isoformat(),
            **coverage[problem.pk],
            **_difficulty_rating_payload(user_rating=None, average_rating=None, rating_count=0),
        })
    return rows


def library_rows(statements, problems, *, viewer, progress_user, limit):
    from inspinia.pages.views import _statement_table_rows

    statements = list(statements.select_related("linked_problem").order_by("-updated_at", "-pk")[:limit])
    # An existing exact UUID match is sufficient for read-time metadata/history
    # fallback. Hydrate only these in-memory instances; never relink on a GET.
    existing = {
        problem.problem_uuid: problem for problem in ProblemSolveRecord.objects.filter(
            problem_uuid__in=[s.problem_uuid for s in statements if s.linked_problem_id is None],
        )
    }
    for statement in statements:
        if statement.linked_problem_id is None and statement.problem_uuid in existing:
            statement.linked_problem = existing[statement.problem_uuid]
    rows = _statement_table_rows(
        statements,
        user=viewer, progress_user=progress_user,
    )
    rows.extend(problem_rows(
        problems.order_by("-created_at", "-pk")[:limit], viewer=viewer, progress_user=progress_user,
    ))
    return sorted(rows, key=lambda row: row["updated_at_sort"], reverse=True)[:limit]


def shared_library_context(request):
    from inspinia.pages.views import ADMIN_TABLE_LATEST_LIMIT
    from inspinia.pages.views import _json_script_safe
    from inspinia.pages.views import _problem_statement_list_active_filter_chips
    from inspinia.pages.views import _problem_statement_list_filter_options
    from inspinia.pages.views import _problem_statement_list_loaded_summary
    from inspinia.pages.views import _statement_table_rows_copy_tsv

    subject, options = progress_context(request)
    statements, problems = library_sources()
    filters = {key: str(request.GET.get(key) or "").strip() for key in FILTER_KEYS}
    if not filters["concept"]:
        filters.pop("concept")
    if subject["value"] != "my":
        filters["learner"] = subject["value"]
    selected_statements, selected_problems = filtered_sources(statements, problems, filters)
    statement_total, problem_total = statements.count(), problems.count()
    total = statement_total + problem_total
    filtered_total = selected_statements.count() + selected_problems.count()
    rows = _json_script_safe(library_rows(
        selected_statements, selected_problems, viewer=request.user, progress_user=subject["user"],
        limit=ADMIN_TABLE_LATEST_LIMIT,
    ))
    statement_stats = annotate_effective_statement_analytics(statements).aggregate(
        linked_total=Count("pk", filter=Q(linked_problem__isnull=False)),
        needs_metadata=Count("pk", filter=Q(_eff_topic="") | Q(_eff_topic__isnull=True) | Q(_eff_mohs__isnull=True)),
        year_min=Min("contest_year"), year_max=Max("contest_year"),
    )
    problem_stats = problems.aggregate(
        needs_metadata=Count("pk", filter=Q(topic="") | Q(mohs__isnull=True)),
        year_min=Min("year"), year_max=Max("year"),
    )
    years = [value for value in (statement_stats["year_min"], statement_stats["year_max"],
                               problem_stats["year_min"], problem_stats["year_max"]) if value is not None]
    year_range = "Awaiting problem import"
    if years:
        year_range = str(min(years)) if min(years) == max(years) else f"{min(years)}-{max(years)}"
    filter_options = _problem_statement_list_filter_options(statements)
    filter_options["years"] = sorted(set(filter_options["years"]) | {
        str(year) for year in problems.order_by().values_list("year", flat=True).distinct()
    }, reverse=True)
    filter_options["topics"] = sorted(set(filter_options["topics"]) | {
        display_topic_label(topic) for topic in problems.order_by().values_list("topic", flat=True).distinct() if topic
    })
    filter_options["confidences"] = sorted(set(filter_options["confidences"]) | {
        confidence for confidence in problems.order_by().values_list("confidence", flat=True).distinct() if confidence
    })
    contest_total = statements.order_by().values_list("contest_name", flat=True).union(
        problems.order_by().values_list("contest", flat=True),
    ).count()
    solved_total = (
        solved_statements(statements, subject["user"]).count() + solved_problems(problems, subject["user"]).count()
    )
    chips = _problem_statement_list_active_filter_chips(filters)
    clear_url = reverse("pages:problem_statement_list")
    if subject["value"] != "my":
        clear_url += "?" + urlencode({"learner": subject["value"]})
    return {
        "statement_total": total,
        "statement_stats": {
            "contest_total": contest_total, "linked_total": statement_stats["linked_total"],
            "unlinked_total": statement_total - statement_stats["linked_total"], "year_range_label": year_range,
        },
        "library_stats": {
            "solved_total": solved_total,
            "needs_metadata": statement_stats["needs_metadata"] + problem_stats["needs_metadata"],
            "missing_statements": problem_total + statements.alias(_library_text=Trim("statement_latex")).filter(
                _library_text="",
            ).count(),
        },
        "library_progress_label": subject["label"], "library_progress_user": subject["user"],
        "library_progress_selection": subject["value"], "library_progress_options": options,
        "library_clear_url": clear_url,
        "statement_table_rows": rows, "statement_datatable_rows": rows,
        "statement_filtered_total": filtered_total, "statement_visible_total": len(rows),
        "statement_result_limit": ADMIN_TABLE_LATEST_LIMIT, "statement_is_capped": filtered_total > len(rows),
        "statement_list_filters": filters,
        "statement_loaded_summary": _problem_statement_list_loaded_summary(
            filtered_total=filtered_total, visible_total=len(rows),
        ),
        "statement_has_active_filters": bool(chips),
        "statement_has_advanced_filters": any(filters[key] for key in ("confidence", "mohs_min", "mohs_max")),
        "statement_active_filter_chips": chips,
        "statement_filter_years": filter_options["years"], "statement_filter_topics": filter_options["topics"],
        "statement_filter_confidences": filter_options["confidences"],
        "statement_copy_tsv": _statement_table_rows_copy_tsv(rows).replace(
            "Day\tSolved\t", f"Day\t{subject['label']}\t", 1,
        ),
    }
