"""Presentation data for the fixed, read-only learner dashboards."""

from collections import Counter
from collections import defaultdict
from statistics import median

from inspinia.pages.completion_progress import completion_progress_charts_payload
from inspinia.pages.completion_progress import completion_progress_stats
from inspinia.pages.completion_progress import completion_progress_topic_mohs_matrix_payload
from inspinia.pages.completion_progress import dedupe_completion_progress_rows
from inspinia.pages.completion_record_areas import completion_record_area_metadata
from inspinia.pages.shared_progress_comparison import comparison_query_string


def shared_completion_overview_context(*, context, completions, filtered_rows, comparison_rows, today):
    """Keep dated performance separate from undated history and raw record counts."""
    dated_rows = dedupe_completion_progress_rows(row for row in filtered_rows if row.completion_date is not None)
    stats = completion_progress_stats(dated_rows, today=today)
    streak_stats = completion_progress_stats(dedupe_completion_progress_rows(comparison_rows), today=today)
    date_range = context["completion_progress_date_range"]
    visible_ids = {row.completion_id for row in filtered_rows}
    visible_completions = [completion for completion in completions if completion.pk in visible_ids]
    metadata = completion_record_area_metadata(visible_completions) if visible_completions else {}
    completions_by_id = {completion.pk: completion for completion in visible_completions}
    table_rows = []
    for row, table_row in zip(filtered_rows, context["completion_progress_table_rows"], strict=True):
        areas = metadata[row.completion_id]
        table_rows.append(
            {
                **table_row,
                "areas": "; ".join(areas["areas"]) or areas["area_mapping_status"],
                "record_status": completions_by_id[row.completion_id].get_status_display(),
                "problem_url": table_row["problem_url"] or areas["statement_url"],
            },
        )
    topic_counts = Counter(row.topic or "Unlinked" for row in dated_rows)
    topic_mohs = defaultdict(list)
    for row in dated_rows:
        if row.mohs is not None:
            topic_mohs[row.topic or "Unlinked"].append(row.mohs)
    topics = [
        {
            "label": label,
            "count": count,
            "percent": round(count / len(dated_rows) * 100),
            "median_mohs": median(topic_mohs[label]) if topic_mohs[label] else None,
            "url": context["completion_progress_reset_url"]
            + "?"
            + comparison_query_string({**context["completion_progress_filters"], "topic": label}),
        }
        for label, count in topic_counts.most_common()
    ]
    heatmap = context["completion_progress_contest_heatmap"]
    subject_caption = f"solved by {context['shared_progress_label']}"
    for row in heatmap.get("rows", []):
        for cell in row["cells"]:
            cell["title"] = cell["title"].replace("solved by you", subject_caption)
    for series in heatmap.get("chart", {}).get("series", []):
        for point in series["data"]:
            if "title" in point:
                point["title"] = point["title"].replace("solved by you", subject_caption)
    return {
        "shared_progress_period_stats": stats,
        "shared_progress_streak_stats": streak_stats,
        "shared_progress_topics": topics,
        "shared_progress_calendar_sections": list(reversed(context["completion_progress_yearly_heatmap"]["sections"])),
        "completion_progress_table_rows": table_rows,
        "completion_progress_charts_payload": completion_progress_charts_payload(
            dated_rows,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
        ),
        "completion_progress_topic_mohs_matrix": completion_progress_topic_mohs_matrix_payload(dated_rows),
    }
