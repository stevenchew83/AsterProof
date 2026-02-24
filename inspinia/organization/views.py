from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render

from .models import ActivityEvent
from .models import ProblemList
from .models import ProblemListItem


@login_required
def my_lists(request):
    lists = ProblemList.objects.filter(owner=request.user).prefetch_related("items")
    return render(request, "organization/lists.html", {"lists": lists})


@login_required
def create_list(request):
    if request.method == "POST":
        ProblemList.objects.create(
            owner=request.user,
            title=request.POST.get("title", "Untitled list"),
            description=request.POST.get("description", ""),
            visibility=request.POST.get("visibility", "private"),
        )
    return redirect("organization:lists")


@login_required
def add_problem_to_list(request, list_id: int, problem_id: int):
    problem_list = get_object_or_404(ProblemList, id=list_id, owner=request.user)
    ProblemListItem.objects.get_or_create(problem_list=problem_list, problem_id=problem_id)
    return redirect("organization:lists")


@login_required
def activity_timeline(request):
    events = ActivityEvent.objects.filter(user=request.user).select_related("problem")[:200]
    return render(request, "organization/activity.html", {"events": events})
