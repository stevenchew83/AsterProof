from django import template
from django.conf import settings

from inspinia.pages.study_help_access import can_use_study_help
from inspinia.pages.study_help_access import draft_pilot_statement
from inspinia.pages.study_help_models import StudyHelpPolicy

register = template.Library()


@register.inclusion_tag("pages/partials/draft-study-help.html", takes_context=True)
def draft_study_help(context, statement):
    enabled = settings.STUDY_HELP_ENABLED
    if settings.STUDY_HELP_DRAFT_HINT_PILOT_ENABLED:
        enabled = draft_pilot_statement(statement) and can_use_study_help(
            context["request"].user,
            StudyHelpPolicy.objects.filter(pk=1).first(),
        )
    return {
        "problem_statement": statement if enabled and statement.is_active else None,
        "study_help_draft": True,
    }
