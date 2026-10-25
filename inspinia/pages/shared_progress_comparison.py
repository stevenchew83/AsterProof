"""Read-only comparisons using the existing individual progress calculations."""

from collections import Counter
from urllib.parse import urlencode

from django.utils import timezone

from inspinia.pages.completion_progress import COMPLETION_PROGRESS_RANGE_OPTIONS
from inspinia.pages.completion_progress import CompletionProgressFilters
from inspinia.pages.completion_progress import completion_progress_filter_options
from inspinia.pages.completion_progress import completion_progress_stats
from inspinia.pages.completion_progress import dedupe_completion_progress_rows
from inspinia.pages.completion_progress import filter_completion_progress_rows
from inspinia.pages.completion_progress import normalize_completion_progress_rows
from inspinia.pages.completion_progress import resolve_completion_progress_date_range
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.technique_progress import technique_progress_summary
from inspinia.training.progress import training_progress_summary

COMPLETION_FILTER_KEYS = ("range", "start", "end", "contest", "topic", "mohs_min", "mohs_max", "solution_status", "q")


def comparison_query_string(params) -> str:
    return urlencode({key: params[key] for key in COMPLETION_FILTER_KEYS if params.get(key)})


def completion_comparison(learners: list[dict], params) -> dict:
    today = timezone.localdate()
    date_range = resolve_completion_progress_date_range(
        raw_range=(params.get("range") or "").strip(),
        raw_start=(params.get("start") or "").strip(),
        raw_end=(params.get("end") or "").strip(),
        today=today,
    )
    filters = {key: (params.get(key) or "").strip() for key in COMPLETION_FILTER_KEYS}
    filters.update(range=date_range.range_key, start=date_range.start_label, end=date_range.end_label)
    completions = UserProblemCompletion.objects.filter(
        user_id__in=[entry["user"].pk for entry in learners],
    ).select_related("user", "problem", "statement", "statement__linked_problem")
    all_rows = normalize_completion_progress_rows(completions)
    row_filters = CompletionProgressFilters(
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        contest=filters["contest"],
        topic=filters["topic"],
        mohs_min=filters["mohs_min"],
        mohs_max=filters["mohs_max"],
        solution_status=filters["solution_status"],
        search_query=filters["q"],
    )
    stats = {}
    topic_counts = {}
    for learner in learners:
        rows = dedupe_completion_progress_rows(
            filter_completion_progress_rows(
                [row for row in all_rows if row.user_id == learner["user"].pk],
                row_filters,
            ),
        )
        stats[learner["slug"]] = completion_progress_stats(rows, today=today)
        topic_counts[learner["slug"]] = Counter(row.topic or "Unlinked" for row in rows)
    metric_labels = (
        ("solved_total", "Recorded problems"),
        ("active_day_total", "Active days"),
        ("current_streak", "Current streak (days)"),
        ("longest_streak", "Longest streak (days)"),
        ("average_mohs", "Average MOHS"),
        ("total_mohs", "Total MOHS"),
        ("missing_date_total", "Undated records"),
        ("missing_mohs_total", "Records without MOHS"),
    )
    return {
        "comparison_completion_stats": stats,
        "comparison_metric_rows": [
            {"label": label, "alex": stats["alex"][key], "ben": stats["ben"][key]} for key, label in metric_labels
        ],
        "comparison_topic_rows": [
            {"label": label, "alex": topic_counts["alex"][label], "ben": topic_counts["ben"][label]}
            for label in sorted(set(topic_counts["alex"]) | set(topic_counts["ben"]))
        ],
        "comparison_date_range": date_range,
        "comparison_filters": filters,
        "comparison_filter_options": completion_progress_filter_options(all_rows),
        "comparison_range_options": COMPLETION_PROGRESS_RANGE_OPTIONS,
    }


def coverage_comparison(learners: list[dict]) -> dict:
    coverage = {entry["slug"]: technique_progress_summary(entry["user"]) for entry in learners}
    return {
        "comparison_coverage": coverage,
        "comparison_coverage_totals": [
            {
                "label": "All tagged problems",
                **{
                    slug: {
                        "solved": payload["stats"]["completed_statement_total"],
                        "total": payload["stats"]["tagged_statement_total"],
                        "completion_percent": payload["stats"]["completion_percent"],
                    }
                    for slug, payload in coverage.items()
                },
            },
        ],
        "comparison_coverage_is_current": all(
            payload["technique_progress_catalog_is_current"] for payload in coverage.values()
        ),
        "comparison_coverage_groups": [
            {"label": label, "rows": _pair_coverage_rows(coverage["alex"][key], coverage["ben"][key])}
            for key, label in (
                ("main_topic_rows", "Topics"),
                ("subtopic_rows", "Subtopics"),
                ("technique_rows", "Techniques"),
            )
        ],
    }


def _pair_coverage_rows(alex_rows: list[dict], ben_rows: list[dict]) -> list[dict]:
    alex = {row["label"]: row for row in alex_rows}
    ben = {row["label"]: row for row in ben_rows}
    labels = list(dict.fromkeys([*alex, *ben]))
    return [{"label": label, "alex": alex.get(label), "ben": ben.get(label)} for label in labels]


def training_comparison(learners: list[dict]) -> dict:
    training = {entry["slug"]: training_progress_summary(entry["user"]) for entry in learners}
    totals = {}
    for slug, payload in training.items():
        total = sum(topic["total"] for topic in payload["topics"])
        completed = sum(topic["completed"] for topic in payload["topics"])
        totals[slug] = {
            "total": total,
            "completed": completed,
            "percent": round(completed / total * 100) if total else 0,
        }
    topics_by_learner = {
        slug: {topic["id"]: topic for topic in payload["topics"]} for slug, payload in training.items()
    }
    topic_ids = list(dict.fromkeys([*topics_by_learner["alex"], *topics_by_learner["ben"]]))
    topics = []
    for topic_id in topic_ids:
        alex = topics_by_learner["alex"].get(topic_id)
        ben = topics_by_learner["ben"].get(topic_id)
        subtopics = {
            slug: {row["id"]: row for row in (topic or {}).get("subtopics", [])}
            for slug, topic in (("alex", alex), ("ben", ben))
        }
        subtopic_ids = list(dict.fromkeys([*subtopics["alex"], *subtopics["ben"]]))
        topics.append(
            {
                "title": (alex or ben)["title"],
                "alex": alex,
                "ben": ben,
                "subtopics": [
                    {
                        "title": (subtopics["alex"].get(pk) or subtopics["ben"][pk])["title"],
                        "alex": subtopics["alex"].get(pk),
                        "ben": subtopics["ben"].get(pk),
                    }
                    for pk in subtopic_ids
                ],
            },
        )
    return {
        "comparison_training": training,
        "comparison_training_topics": topics,
        "comparison_training_totals": [{"title": "Published materials and problems", **totals}],
    }
