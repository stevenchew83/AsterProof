from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render

from inspinia.core.permissions import require_learning_state_allowed
from inspinia.progress.models import ProblemFavourite
from inspinia.progress.models import ProblemProgress
from inspinia.progress.models import ProblemStatus


@login_required
def update_problem_status(request, problem_id: int):
    blocked = require_learning_state_allowed(request.user)
    if blocked:
        return blocked
    status = request.POST.get("status")
    if status not in ProblemStatus.values:
        return HttpResponseBadRequest("Invalid status")
    progress, _ = ProblemProgress.objects.get_or_create(user=request.user, problem_id=problem_id)
    progress.status = status
    progress.save()
    return render(request, "progress/partials/status_chip.html", {"progress": progress})


@login_required
def toggle_favourite(request, problem_id: int):
    blocked = require_learning_state_allowed(request.user)
    if blocked:
        return blocked
    fav = ProblemFavourite.objects.filter(user=request.user, problem_id=problem_id)
    is_favourited = False
    if fav.exists():
        fav.delete()
    else:
        ProblemFavourite.objects.create(user=request.user, problem_id=problem_id)
        is_favourited = True
    return render(
        request,
        "progress/partials/favourite_button.html",
        {"problem_id": problem_id, "is_favourited": is_favourited},
    )


@login_required
def favourites_page(request):
    favourites = ProblemFavourite.objects.filter(user=request.user).select_related("problem")
    return render(request, "progress/favourites.html", {"favourites": favourites})
