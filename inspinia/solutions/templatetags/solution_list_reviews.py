from django import template

from inspinia.solutions.my_solution_reviews import author_review_summaries

register = template.Library()


@register.simple_tag
def with_author_review_status(user, rows):
    """Enrich only the personal table while retaining the frozen solution reader."""
    summaries = author_review_summaries(user, [row["id"] for row in rows])
    return [{**row, "ai_review": summaries.get(row["id"])} for row in rows]
