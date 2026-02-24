from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponseNotFound
from django.shortcuts import render

from inspinia.backoffice.services import get_effective_feature_flags
from inspinia.catalog.models import Problem
from inspinia.progress.models import ProblemProgress
from inspinia.progress.models import ProblemStatus
from inspinia.users.models import User


@login_required
def personal_dashboard(request):
    if not get_effective_feature_flags().get("profiles_analytics", True):
        return HttpResponseNotFound("Analytics are disabled.")
    progress = ProblemProgress.objects.filter(user=request.user)
    total_solved = progress.filter(status=ProblemStatus.SOLVED).count()
    total_attempted = progress.exclude(status=ProblemStatus.UNATTEMPTED).count()
    total_problems = Problem.objects.exclude(status="hidden").count()
    return render(
        request,
        "analytics/personal_dashboard.html",
        {
            "total_solved": total_solved,
            "total_attempted": total_attempted,
            "total_problems": total_problems,
            "completion_rate": (100 * total_solved / total_problems) if total_problems else 0,
        },
    )


def trending(request):
    if not get_effective_feature_flags().get("profiles_analytics", True):
        return HttpResponseNotFound("Analytics are disabled.")
    trending_problems = Problem.objects.exclude(status="hidden").annotate(fav_count=Count("favourites")).order_by("-fav_count")[:20]
    trending_users = (
        User.objects.filter(show_in_leaderboards=True, is_banned=False)
        .annotate(solved_count=Count("problem_progress"))
        .order_by("-solved_count")[:20]
    )
    return render(
        request,
        "analytics/trending.html",
        {"trending_problems": trending_problems, "trending_users": trending_users},
    )


def leaderboard(request):
    if not get_effective_feature_flags().get("profiles_analytics", True):
        return HttpResponseNotFound("Analytics are disabled.")
    rows = User.objects.filter(
        show_in_leaderboards=True,
        profile_visibility="public",
        is_profile_hidden=False,
        is_banned=False,
    ).order_by("-rating", "id")[:100]
    return render(request, "analytics/leaderboard.html", {"rows": rows})
