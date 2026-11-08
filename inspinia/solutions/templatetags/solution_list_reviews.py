from collections import Counter
from datetime import timedelta

from django import template
from django.utils import timezone

from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.my_solution_reviews import author_review_summaries

register = template.Library()


@register.simple_tag
def my_solution_workspace(user, rows):
    """Build the personal charts and table without changing the frozen reader."""
    ids = [row["id"] for row in rows]
    summaries = author_review_summaries(user, ids)
    creation_times = dict(
        ProblemSolution.objects.filter(author=user, pk__in=ids).values_list("pk", "created_at"),
    )
    status_counts = Counter(row["status"] for row in rows)
    week_counts = Counter()
    activity_week_count = 8
    today = timezone.localdate()
    first_week = today - timedelta(days=today.weekday(), weeks=activity_week_count - 1)
    workspace_rows = []

    for row in rows:
        solution_id = row["id"]
        workspace_row = {**row, "ai_review": summaries.get(solution_id)}
        created_at = creation_times.get(solution_id)
        if created_at is not None:
            created = timezone.localdate(created_at)
            week_index = (created - first_week).days // 7
            if 0 <= week_index < activity_week_count and created <= today:
                workspace_row["activity_week"] = week_index
                week_counts[week_index] += 1
        workspace_rows.append(workspace_row)

    return {
        "rows": workspace_rows,
        "statuses": [
            {"key": key, "label": label, "count": status_counts[key]}
            for key, label in ProblemSolution.Status.choices
            if status_counts[key]
        ],
        "activity": [
            {"key": index, "start": first_week + timedelta(weeks=index), "count": week_counts[index]}
            for index in range(activity_week_count)
        ],
        "activity_peak": max(week_counts.values(), default=1),
    }
