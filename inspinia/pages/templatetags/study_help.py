from django import template
from django.conf import settings

register = template.Library()


@register.inclusion_tag("pages/partials/draft-study-help.html")
def draft_study_help(statement):
    return {
        "problem_statement": statement if settings.STUDY_HELP_ENABLED and statement.is_active else None,
        "study_help_draft": True,
    }
