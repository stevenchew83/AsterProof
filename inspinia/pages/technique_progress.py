from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlencode

from django.db.models import F
from django.urls import reverse

from inspinia.pages.completion_record_fields import is_completion_status_solved
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.topic_labels import display_topic_label
from inspinia.users.models import User
from inspinia.users.roles import user_has_admin_role

NEXT_GAP_LIMIT = 6


def technique_progress_user_options() -> list[dict[str, str]]:
    options = []
    for user in User.objects.filter(is_active=True).order_by("name", "email", "id"):
        user_label = user.name or user.email
        options.append(
            {
                "label": user_label if user_label == user.email else f"{user_label} ({user.email})",
                "value": str(user.pk),
            },
        )
    return options


def resolve_technique_progress_user(
    *,
    request_user: User,
    raw_user_id: str,
) -> tuple[User, bool]:
    can_select_user = user_has_admin_role(request_user)
    if not can_select_user:
        return request_user, False

    selected_user = None
    if raw_user_id:
        try:
            selected_user_id = int(raw_user_id)
        except (TypeError, ValueError):
            selected_user_id = None
        if selected_user_id is not None:
            selected_user = User.objects.filter(pk=selected_user_id, is_active=True).first()
    return selected_user or request_user, True


def build_technique_progress_context(
    *,
    request_user: User,
    raw_user_id: str = "",
) -> dict[str, object]:
    selected_user, can_select_user = resolve_technique_progress_user(
        request_user=request_user,
        raw_user_id=raw_user_id,
    )
    tagged_rows = _tagged_statement_rows(user=selected_user)
    technique_rows = _aggregate_progress_rows(
        tagged_rows,
        label_key="technique",
        type_label="Technique",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    subtopic_rows = _aggregate_progress_rows(
        tagged_rows,
        label_key="subtopic",
        type_label="Subtopic",
        selected_user=selected_user,
        can_select_user=can_select_user,
    )
    tagged_statement_ids = {row["statement_id"] for row in tagged_rows}
    completed_statement_ids = {
        row["statement_id"]
        for row in tagged_rows
        if row["is_solved"]
    }
    tagged_statement_total = len(tagged_statement_ids)
    completed_statement_total = len(completed_statement_ids)
    stats = {
        "completion_percent": _percent(completed_statement_total, tagged_statement_total),
        "completed_statement_total": completed_statement_total,
        "incomplete_subtopic_total": sum(1 for row in subtopic_rows if row["remaining"]),
        "incomplete_technique_total": sum(1 for row in technique_rows if row["remaining"]),
        "subtopic_total": len(subtopic_rows),
        "tagged_statement_total": tagged_statement_total,
        "technique_total": len(technique_rows),
    }
    next_gaps = sorted(
        [
            *[dict(row, type="Subtopic") for row in subtopic_rows if row["remaining"]],
            *[dict(row, type="Technique") for row in technique_rows if row["remaining"]],
        ],
        key=lambda row: (-int(row["remaining"]), 0 if row["type"] == "Subtopic" else 1, str(row["label"]).casefold()),
    )[:NEXT_GAP_LIMIT]

    return {
        "technique_progress_can_select_user": can_select_user,
        "technique_progress_filters": {
            "user": str(selected_user.pk) if can_select_user else "",
        },
        "technique_progress_has_completed": bool(completed_statement_ids),
        "technique_progress_has_tagged_statements": bool(tagged_statement_ids),
        "technique_progress_next_gaps": next_gaps,
        "technique_progress_quick_update_url": reverse("pages:completion_quick_update"),
        "technique_progress_selected_user": selected_user,
        "technique_progress_stats": stats,
        "technique_progress_subtopic_rows": subtopic_rows,
        "technique_progress_technique_rows": technique_rows,
        "technique_progress_user_options": technique_progress_user_options() if can_select_user else [],
    }


def _tagged_statement_rows(*, user: User) -> list[dict[str, object]]:
    statements = list(
        ContestProblemStatement.objects.filter(is_active=True)
        .select_related("linked_problem")
        .order_by("-contest_year", "contest_name", "problem_number", "problem_code", "id"),
    )
    if not statements:
        return []

    statement_ids = [statement.id for statement in statements]
    linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.linked_problem_id is not None
        },
    )
    statement_tags = _statement_tags_by_statement_id(statement_ids)
    linked_tags = _problem_tags_by_record_id(linked_problem_ids)
    completion_by_statement_id = _completion_by_statement_id(
        statements=statements,
        user=user,
    )

    rows = []
    seen_statement_labels: set[tuple[int, str]] = set()
    for statement in statements:
        tags = statement_tags.get(statement.id) or linked_tags.get(statement.linked_problem_id, [])
        if not tags:
            continue
        completion = completion_by_statement_id.get(statement.id)
        is_solved = completion is not None and is_completion_status_solved(completion.status)
        fallback_topic = display_topic_label(effective_topic(statement)) if effective_topic(statement) else ""
        for tag in tags:
            technique = str(tag["technique"] or "").strip()
            if not technique:
                continue
            dedupe_key = (statement.id, technique.casefold())
            if dedupe_key in seen_statement_labels:
                continue
            seen_statement_labels.add(dedupe_key)
            main_topic = str(tag.get("main_topic") or "").strip()
            rows.append(
                {
                    "is_solved": is_solved,
                    "main_topic": display_topic_label(main_topic) if main_topic else fallback_topic,
                    "statement_id": statement.id,
                    "subtopic": str(tag.get("canonical_subtopic") or "").strip() or technique,
                    "technique": technique,
                },
            )
    return rows


def _statement_tags_by_statement_id(statement_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    tags_by_statement_id: dict[int, list[dict[str, object]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()
    for tag_row in (
        StatementTopicTechnique.objects.filter(statement_id__in=statement_ids)
        .values("statement_id", "technique", "main_topic", "canonical_subtopic")
        .order_by("technique", "statement_id", "id")
    ):
        statement_id = int(tag_row["statement_id"])
        technique = str(tag_row["technique"] or "")
        dedupe_key = (statement_id, technique.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tags_by_statement_id[statement_id].append(tag_row)
    return tags_by_statement_id


def _problem_tags_by_record_id(record_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    tags_by_record_id: dict[int, list[dict[str, object]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()
    if not record_ids:
        return tags_by_record_id
    for tag_row in (
        ProblemTopicTechnique.objects.filter(record_id__in=record_ids)
        .values("record_id", "technique", "main_topic", "canonical_subtopic")
        .order_by("technique", "record_id", "id")
    ):
        record_id = int(tag_row["record_id"])
        technique = str(tag_row["technique"] or "")
        dedupe_key = (record_id, technique.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tags_by_record_id[record_id].append(tag_row)
    return tags_by_record_id


def _completion_by_statement_id(
    *,
    statements: list[ContestProblemStatement],
    user: User,
) -> dict[int, UserProblemCompletion]:
    statement_ids = [statement.id for statement in statements]
    linked_problem_ids = sorted(
        {
            statement.linked_problem_id
            for statement in statements
            if statement.linked_problem_id is not None
        },
    )
    completion_by_statement_id = {
        completion.statement_id: completion
        for completion in UserProblemCompletion.objects.filter(
            user=user,
            statement_id__in=statement_ids,
        ).order_by(F("completion_date").desc(nulls_last=True), "-updated_at", "-id")
        if completion.statement_id is not None
    }
    if not linked_problem_ids:
        return completion_by_statement_id

    legacy_completion_by_problem_id = {
        completion.problem_id: completion
        for completion in UserProblemCompletion.objects.filter(
            user=user,
            problem_id__in=linked_problem_ids,
        ).order_by(F("completion_date").desc(nulls_last=True), "-updated_at", "-id")
        if completion.problem_id is not None
    }
    for statement in statements:
        if statement.id in completion_by_statement_id:
            continue
        if statement.linked_problem_id in legacy_completion_by_problem_id:
            completion_by_statement_id[statement.id] = legacy_completion_by_problem_id[statement.linked_problem_id]
    return completion_by_statement_id


def _aggregate_progress_rows(
    tagged_rows: list[dict[str, object]],
    *,
    label_key: str,
    type_label: str,
    selected_user: User,
    can_select_user: bool,
) -> list[dict[str, object]]:
    buckets: dict[str, dict[str, object]] = {}
    for tagged_row in tagged_rows:
        label = str(tagged_row[label_key] or "").strip()
        if not label:
            continue
        bucket = buckets.setdefault(
            label,
            {
                "label": label,
                "main_topics": set(),
                "solved_statement_ids": set(),
                "statement_ids": set(),
                "type": type_label,
            },
        )
        bucket["statement_ids"].add(tagged_row["statement_id"])
        if tagged_row["is_solved"]:
            bucket["solved_statement_ids"].add(tagged_row["statement_id"])
        main_topic = str(tagged_row.get("main_topic") or "").strip()
        if main_topic:
            bucket["main_topics"].add(main_topic)

    rows = []
    for bucket in buckets.values():
        statement_ids = bucket["statement_ids"]
        solved_statement_ids = bucket["solved_statement_ids"]
        total = len(statement_ids)
        solved = len(solved_statement_ids)
        remaining = total - solved
        label = str(bucket["label"])
        main_topics = sorted(bucket["main_topics"])
        rows.append(
            {
                "completion_percent": _percent(solved, total),
                "label": label,
                "main_topic_label": ", ".join(main_topics),
                "practice_url": _practice_url(
                    label,
                    selected_user=selected_user,
                    can_select_user=can_select_user,
                ),
                "remaining": remaining,
                "solved": solved,
                "total": total,
                "type": bucket["type"],
            },
        )
    return sorted(
        rows,
        key=lambda row: (
            int(row["remaining"]) == 0,
            -int(row["remaining"]),
            str(row["label"]).casefold(),
        ),
    )


def _practice_url(label: str, *, selected_user: User, can_select_user: bool) -> str:
    query: dict[str, str] = {}
    if can_select_user:
        query["target_user_id"] = str(selected_user.pk)
    query["subtopics"] = label
    return f"{reverse('pages:completion_quick_update')}?{urlencode(query)}"


def _percent(numerator: int, denominator: int) -> int:
    if not denominator:
        return 0
    return round((numerator / denominator) * 100)
