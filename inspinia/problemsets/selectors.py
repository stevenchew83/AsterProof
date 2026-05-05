from __future__ import annotations

from django.db.models import Count
from django.db.models import F
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.asymptote_render import build_statement_render_segments
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.topic_labels import display_topic_label
from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.models import ProblemListVote


def problem_label(problem: ProblemSolveRecord) -> str:
    return problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"


def author_label(user) -> str:
    return user.name or user.email


def vote_annotations(queryset):
    return queryset.annotate(
        item_count=Count("items", distinct=True),
        upvote_count=Count("votes", filter=Q(votes__value=ProblemListVote.Value.UP), distinct=True),
        downvote_count=Count("votes", filter=Q(votes__value=ProblemListVote.Value.DOWN), distinct=True),
    ).annotate(score=F("upvote_count") - F("downvote_count"))


def public_problem_lists_queryset(search_text: str = ""):
    queryset = vote_annotations(
        ProblemList.objects.filter(visibility=ProblemList.Visibility.PUBLIC)
        .select_related("author")
        .prefetch_related("items__problem"),
    )

    search_text = (search_text or "").strip()
    if search_text:
        queryset = queryset.filter(
            Q(title__icontains=search_text)
            | Q(description__icontains=search_text)
            | Q(author__email__icontains=search_text)
            | Q(author__name__icontains=search_text)
            | Q(items__problem__contest__icontains=search_text)
            | Q(items__problem__problem__icontains=search_text)
            | Q(items__problem__contest_year_problem__icontains=search_text)
            | Q(items__problem__topic__icontains=search_text)
            | Q(items__problem__topic_tags__icontains=search_text)
            | Q(items__problem__topic_techniques__technique__icontains=search_text),
        ).distinct()

    return queryset.order_by("-score", "-published_at", "-updated_at", "-id")


def my_problem_lists_queryset(user):
    return vote_annotations(
        ProblemList.objects.filter(author=user).select_related("author").prefetch_related("items__problem"),
    ).order_by("-updated_at", "-id")


def problem_list_summary_rows(problem_lists: list[ProblemList]) -> list[dict]:
    return [
        {
            "author_label": author_label(problem_list.author),
            "description": problem_list.description,
            "detail_url": reverse("problemsets:detail", args=[problem_list.list_uuid]),
            "downvote_count": getattr(problem_list, "downvote_count", 0),
            "edit_url": reverse("problemsets:edit", args=[problem_list.list_uuid]),
            "item_count": getattr(problem_list, "item_count", problem_list.items.count()),
            "public_url": problem_list.public_url(),
            "score": getattr(problem_list, "score", 0),
            "share_token": str(problem_list.share_token),
            "title": problem_list.title,
            "upvote_count": getattr(problem_list, "upvote_count", 0),
            "visibility": problem_list.visibility,
            "visibility_label": problem_list.get_visibility_display(),
            "updated_at_label": timezone.localtime(problem_list.updated_at).strftime("%Y-%m-%d %H:%M"),
        }
        for problem_list in problem_lists
    ]


def problem_list_vote_totals(problem_list: ProblemList) -> dict[str, int]:
    rows = problem_list.votes.values("value").annotate(total=Count("id"))
    counts = {row["value"]: row["total"] for row in rows}
    upvotes = counts.get(ProblemListVote.Value.UP, 0)
    downvotes = counts.get(ProblemListVote.Value.DOWN, 0)
    return {
        "downvote_count": downvotes,
        "score": upvotes - downvotes,
        "upvote_count": upvotes,
    }


def problem_list_item_rows(problem_list: ProblemList, *, include_inactive: bool = False) -> list[dict]:
    item_queryset = problem_list.items.select_related("problem").order_by("position", "id")
    if not include_inactive:
        item_queryset = item_queryset.filter(problem__is_active=True)
    items = list(item_queryset)
    if not items:
        return []

    problems = [item.problem for item in items]
    problem_ids = [problem.id for problem in problems]
    latest_statement_by_problem_id = _latest_statement_by_problem_id(problem_ids)
    topic_tags_by_problem_id = _topic_tags_by_problem_id(problem_ids)

    rows: list[dict] = []
    for item in items:
        problem = item.problem
        statement = latest_statement_by_problem_id.get(problem.id)
        topic_label = (
            display_topic_label(effective_topic(statement))
            if statement is not None
            else display_topic_label(problem.topic)
        )
        mohs = effective_mohs(statement) if statement is not None else problem.mohs
        topic_tags = topic_tags_by_problem_id.get(problem.id) or _raw_topic_tags(problem.topic_tags)
        rows.append(
            {
                "id": item.id,
                "is_active": problem.is_active,
                "mohs": mohs,
                "position": item.position,
                "problem": problem,
                "problem_label": problem_label(problem),
                "problem_uuid": str(problem.problem_uuid),
                "statement": statement,
                "statement_render_segments": (
                    build_statement_render_segments(statement.statement_latex) if statement is not None else []
                ),
                "topic_label": topic_label,
                "topic_tags": topic_tags,
            },
        )
    return rows


def _latest_statement_by_problem_id(problem_ids: list[int]) -> dict[int, ContestProblemStatement]:
    statements = list(
        ContestProblemStatement.objects.filter(is_active=True, linked_problem_id__in=problem_ids)
        .select_related("linked_problem")
        .order_by("linked_problem_id", "-updated_at", "-id"),
    )
    latest_by_problem_id: dict[int, ContestProblemStatement] = {}
    for statement in statements:
        if statement.linked_problem_id in latest_by_problem_id:
            continue
        latest_by_problem_id[statement.linked_problem_id] = statement
    return latest_by_problem_id


def _topic_tags_by_problem_id(problem_ids: list[int]) -> dict[int, list[str]]:
    rows = ProblemTopicTechnique.objects.filter(record_id__in=problem_ids).order_by("record_id", "technique")
    tags_by_problem_id: dict[int, list[str]] = {}
    for row in rows:
        tags_by_problem_id.setdefault(row.record_id, []).append(row.technique)
    return tags_by_problem_id


def _raw_topic_tags(topic_tags: str | None) -> list[str]:
    raw_value = (topic_tags or "").strip()
    if not raw_value:
        return []
    return [piece.strip() for piece in raw_value.replace(";", "\n").splitlines() if piece.strip()]
