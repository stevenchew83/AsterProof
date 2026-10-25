from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_safe

from inspinia.pages.shared_progress import shared_progress_context
from inspinia.pages.shared_progress import shared_progress_section_url
from inspinia.pages.technique_progress import technique_progress_summary
from inspinia.pages.views import _render_completion_progress_analytics
from inspinia.training.progress import training_progress_summary


@login_required
@require_safe
def shared_progress_view(request, learner: str, section: str = "completions"):
    context = shared_progress_context(request.user, learner=learner, section=section)
    subject = context["shared_progress_subject"]
    if section == "completions":
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
    else:
        context["training"] = training_progress_summary(subject)
    return render(request, "pages/shared-progress.html", context)
