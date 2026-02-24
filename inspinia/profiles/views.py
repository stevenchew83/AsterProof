from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render

from inspinia.backoffice.models import Report
from inspinia.core.visibility import can_view_profile
from inspinia.users.models import User


def profile_detail(request, user_id: int):
    profile_user = get_object_or_404(User, id=user_id)
    if not can_view_profile(request.user, profile_user):
        return HttpResponseForbidden("This profile is private.")
    return render(request, "profiles/detail.html", {"profile_user": profile_user})


@login_required
def edit_profile(request):
    if request.method == "POST":
        request.user.display_name = request.POST.get("display_name", "")
        request.user.bio = request.POST.get("bio", "")
        request.user.country = request.POST.get("country", "")
        request.user.profile_visibility = request.POST.get("profile_visibility", "public")
        request.user.show_in_leaderboards = request.POST.get("show_in_leaderboards") == "on"
        request.user.save()
        return redirect("profiles:detail", user_id=request.user.id)
    return render(request, "profiles/edit.html", {"profile_user": request.user})


@login_required
def report_profile(request, user_id: int):
    profile_user = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        try:
            severity = int(request.POST.get("severity", "1"))
        except (TypeError, ValueError):
            severity = 1
        Report.objects.create(
            reporter=request.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=profile_user.id,
            reason_code=request.POST.get("reason_code", "other"),
            details=request.POST.get("details", ""),
            severity=severity,
        )
    return redirect("profiles:detail", user_id=profile_user.id)
