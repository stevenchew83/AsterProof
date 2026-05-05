from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from inspinia.problemsets.forms import ProblemListAddProblemForm
from inspinia.problemsets.forms import ProblemListForm
from inspinia.problemsets.forms import ProblemListSearchForm
from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.selectors import author_label
from inspinia.problemsets.selectors import my_problem_lists_queryset
from inspinia.problemsets.selectors import problem_list_item_rows
from inspinia.problemsets.selectors import problem_list_summary_rows
from inspinia.problemsets.selectors import problem_list_vote_totals
from inspinia.problemsets.selectors import public_problem_lists_queryset
from inspinia.problemsets.services import ProblemListServiceError
from inspinia.problemsets.services import add_problem_to_list
from inspinia.problemsets.services import remove_problem_list_item
from inspinia.problemsets.services import reorder_problem_list_items
from inspinia.problemsets.services import set_problem_list_visibility
from inspinia.problemsets.services import toggle_problem_list_vote


@login_required
def my_lists_view(request):
    problem_lists = list(my_problem_lists_queryset(request.user))
    return render(
        request,
        "problemsets/my-lists.html",
        {
            "problem_list_rows": problem_list_summary_rows(problem_lists),
            "problem_list_stats": {
                "private_total": sum(1 for row in problem_lists if row.visibility == ProblemList.Visibility.PRIVATE),
                "public_total": sum(1 for row in problem_lists if row.visibility == ProblemList.Visibility.PUBLIC),
                "total": len(problem_lists),
            },
        },
    )


@login_required
def discover_view(request):
    form = ProblemListSearchForm(request.GET or None)
    search_text = ""
    if form.is_valid():
        search_text = form.cleaned_data["q"]
    problem_lists = list(public_problem_lists_queryset(search_text))
    return render(
        request,
        "problemsets/discover.html",
        {
            "form": form,
            "problem_list_rows": problem_list_summary_rows(problem_lists),
            "problem_list_search_query": search_text,
        },
    )


@login_required
def create_view(request):
    form = ProblemListForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        problem_list = form.save(commit=False)
        problem_list.author = request.user
        problem_list.visibility = ProblemList.Visibility.PRIVATE
        problem_list.save()
        messages.success(request, "Created problem list.")
        return redirect("problemsets:edit", problem_list.list_uuid)
    return render(request, "problemsets/create.html", {"form": form})


@login_required
def detail_view(request, list_uuid):
    problem_list = _get_visible_problem_list(request.user, list_uuid)
    user_vote = None
    if problem_list.is_public:
        user_vote = problem_list.votes.filter(user=request.user).values_list("value", flat=True).first()
    is_author = problem_list.author_id == request.user.id
    return render(
        request,
        "problemsets/detail.html",
        {
            "can_vote": problem_list.is_public and not is_author,
            "is_author": is_author,
            "problem_list": problem_list,
            "problem_list_author_label": author_label(problem_list.author),
            "problem_list_items": problem_list_item_rows(problem_list, include_inactive=is_author),
            "problem_list_public_url": problem_list.public_url(),
            "problem_list_votes": problem_list_vote_totals(problem_list),
            "user_vote": user_vote,
        },
    )


@login_required
def edit_view(request, list_uuid):
    problem_list = get_object_or_404(ProblemList, list_uuid=list_uuid, author=request.user)
    form = ProblemListForm(request.POST or None, instance=problem_list)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved list details.")
        return redirect("problemsets:edit", problem_list.list_uuid)
    return render(
        request,
        "problemsets/edit.html",
        {
            "add_problem_form": ProblemListAddProblemForm(),
            "form": form,
            "problem_list": problem_list,
            "problem_list_items": problem_list_item_rows(problem_list, include_inactive=True),
            "problem_list_public_url": problem_list.public_url(),
            "problem_list_votes": problem_list_vote_totals(problem_list),
        },
    )


@login_required
@require_POST
def add_item_view(request, list_uuid):
    problem_list = get_object_or_404(ProblemList, list_uuid=list_uuid, author=request.user)
    form = ProblemListAddProblemForm(request.POST)
    if form.is_valid():
        try:
            add_problem_to_list(problem_list, form.cleaned_data["problem_uuid"])
        except ProblemListServiceError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Added problem to list.")
    else:
        messages.error(request, "Paste a valid problem UUID.")
    return redirect("problemsets:edit", problem_list.list_uuid)


@login_required
@require_POST
def remove_item_view(request, list_uuid, item_id: int):
    problem_list = get_object_or_404(ProblemList, list_uuid=list_uuid, author=request.user)
    try:
        remove_problem_list_item(problem_list, item_id)
    except ProblemListServiceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Removed problem from list.")
    return redirect("problemsets:edit", problem_list.list_uuid)


@login_required
@require_POST
def reorder_items_view(request, list_uuid):
    problem_list = get_object_or_404(ProblemList, list_uuid=list_uuid, author=request.user)
    raw_item_ids = request.POST.getlist("item_order")
    try:
        item_ids = [int(item_id) for item_id in raw_item_ids]
        reorder_problem_list_items(problem_list, item_ids)
    except (TypeError, ValueError, ProblemListServiceError) as exc:
        message = str(exc) if isinstance(exc, ProblemListServiceError) else "Submitted order is invalid."
        messages.error(request, message)
    else:
        messages.success(request, "Updated problem sequence.")
    return redirect("problemsets:edit", problem_list.list_uuid)


@login_required
@require_POST
def toggle_visibility_view(request, list_uuid):
    problem_list = get_object_or_404(ProblemList, list_uuid=list_uuid, author=request.user)
    next_visibility = (
        ProblemList.Visibility.PRIVATE if problem_list.is_public else ProblemList.Visibility.PUBLIC
    )
    try:
        set_problem_list_visibility(problem_list, next_visibility)
    except ProblemListServiceError as exc:
        messages.error(request, str(exc))
    else:
        success_message = (
            "Published list with share link."
            if next_visibility == ProblemList.Visibility.PUBLIC
            else "Made list private."
        )
        messages.success(
            request,
            success_message,
        )
    return redirect("problemsets:edit", problem_list.list_uuid)


@login_required
@require_POST
def vote_view(request, list_uuid):
    problem_list = get_object_or_404(
        ProblemList,
        list_uuid=list_uuid,
        visibility=ProblemList.Visibility.PUBLIC,
    )
    try:
        value = int(request.POST.get("value", "0"))
        toggle_problem_list_vote(problem_list, request.user, value)
    except (TypeError, ValueError, ProblemListServiceError) as exc:
        message = str(exc) if isinstance(exc, ProblemListServiceError) else "Choose thumbs up or thumbs down."
        messages.error(request, message)
    else:
        messages.success(request, "Updated vote.")
    next_url = request.POST.get("next") or ""
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("problemsets:detail", problem_list.list_uuid)


def public_detail_view(request, share_token, slug):
    problem_list = get_object_or_404(
        ProblemList.objects.select_related("author"),
        share_token=share_token,
        visibility=ProblemList.Visibility.PUBLIC,
    )
    if slug != problem_list.public_slug:
        raise Http404
    return render(
        request,
        "problemsets/public-detail.html",
        {
            "problem_list": problem_list,
            "problem_list_author_label": author_label(problem_list.author),
            "problem_list_items": problem_list_item_rows(problem_list),
            "problem_list_votes": problem_list_vote_totals(problem_list),
        },
    )


def _get_visible_problem_list(user, list_uuid):
    problem_list = get_object_or_404(ProblemList.objects.select_related("author"), list_uuid=list_uuid)
    if problem_list.author_id == user.id or problem_list.is_public:
        return problem_list
    raise Http404
