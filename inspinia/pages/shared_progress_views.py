from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from inspinia.pages.shared_progress import shared_progress_comparison_context
from inspinia.pages.shared_progress import shared_progress_context
from inspinia.pages.shared_progress import shared_progress_section_url
from inspinia.pages.shared_progress_comparison import comparison_query_string
from inspinia.pages.shared_progress_comparison import completion_comparison
from inspinia.pages.shared_progress_comparison import coverage_comparison
from inspinia.pages.shared_progress_comparison import training_comparison
from inspinia.pages.technique_progress import technique_progress_summary
from inspinia.pages.views import _render_completion_progress_analytics
from inspinia.training.progress import training_progress_summary


@login_required
@require_safe
def shared_progress_view(request, learner: str, section: str = "completions"):
    context = shared_progress_context(request.user, learner=learner, section=section)
    subject = context["shared_progress_subject"]
    if section == "completions":
        query = comparison_query_string(request.GET)
        if query and context["shared_progress_compare_url"]:
            context["shared_progress_compare_url"] += f"?{query}"
        if query:
            for entry in context["shared_progress_learners"]:
                entry["url"] += f"?{query}"
        return _render_completion_progress_analytics(
            request,
            selected_user=subject,
            can_select_user=False,
            page_title=f"{context['shared_progress_label']}'s progress",
            reset_url_name="pages:my_completion_progress_analytics",
            extra_context={
                **context,
                "completion_progress_can_edit_difficulty": False,
                "completion_progress_reset_url": shared_progress_section_url(learner, section),
            },
        )
    if section == "techniques":
        context["coverage"] = technique_progress_summary(subject)
        stats = context["coverage"]["stats"]
        context["shared_progress_coverage_remaining"] = (
            stats["tagged_statement_total"] - stats["completed_statement_total"]
        )
    else:
        context["training"] = training_progress_summary(subject)
        topics = context["training"]["topics"]
        context["shared_progress_training_completed"] = sum(topic["completed"] for topic in topics)
        context["shared_progress_training_total"] = sum(topic["total"] for topic in topics)
        context["shared_progress_training_topics"] = [
            {
                **topic,
                "practice_subtopics": [row for row in topic["subtopics"] if row["total"]],
                "empty_subtopics": [row for row in topic["subtopics"] if not row["total"]],
            }
            for topic in topics
        ]
    return render(request, "pages/shared-progress.html", context)


@never_cache
@login_required
@require_safe
def shared_progress_comparison_view(request, section: str = "completions"):
    context = shared_progress_comparison_context(request.user, section=section)
    learners = context["shared_progress_learners"]
    if section == "completions":
        context.update(completion_comparison(learners, request.GET))
        query = comparison_query_string(context["comparison_filters"])
        for learner in learners:
            learner["url"] += f"?{query}"
        context["shared_progress_compare_url"] += f"?{query}"
    elif section == "techniques":
        context.update(coverage_comparison(learners))
    else:
        context.update(training_comparison(learners))
    return render(request, "pages/shared-progress-comparison.html", context)
