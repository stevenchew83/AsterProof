from __future__ import annotations

from django.db import IntegrityError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from inspinia.pages.models import ProblemSolveRecord
from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.models import ProblemListItem
from inspinia.problemsets.models import ProblemListVote


class ProblemListServiceError(ValueError):
    """Raised when a user action cannot be applied to a problem list."""


def add_problem_to_list(problem_list: ProblemList, problem_uuid) -> ProblemListItem:
    problem = ProblemSolveRecord.objects.filter(problem_uuid=problem_uuid, is_active=True).first()
    if problem is None:
        msg = "Select an active contest problem."
        raise ProblemListServiceError(msg)

    with transaction.atomic():
        locked_list = ProblemList.objects.select_for_update().get(pk=problem_list.pk)
        if ProblemListItem.objects.filter(problem_list=locked_list, problem=problem).exists():
            msg = "That problem is already in this list."
            raise ProblemListServiceError(msg)

        next_position = (locked_list.items.aggregate(max_position=Max("position"))["max_position"] or 0) + 1
        try:
            return ProblemListItem.objects.create(
                problem_list=locked_list,
                problem=problem,
                position=next_position,
            )
        except IntegrityError as exc:
            msg = "Could not add that problem. Refresh and try again."
            raise ProblemListServiceError(msg) from exc


def remove_problem_list_item(problem_list: ProblemList, item_id: int) -> None:
    with transaction.atomic():
        item = ProblemListItem.objects.select_for_update().filter(problem_list=problem_list, pk=item_id).first()
        if item is None:
            msg = "Problem list item was not found."
            raise ProblemListServiceError(msg)
        item.delete()
        _renumber_items(problem_list)


def reorder_problem_list_items(problem_list: ProblemList, item_ids: list[int]) -> None:
    with transaction.atomic():
        items = list(
            ProblemListItem.objects.select_for_update()
            .filter(problem_list=problem_list)
            .order_by("position", "id"),
        )
        current_ids = [item.id for item in items]
        if sorted(current_ids) != sorted(item_ids) or len(current_ids) != len(item_ids):
            msg = "Submitted order does not match the current list items."
            raise ProblemListServiceError(msg)

        item_by_id = {item.id: item for item in items}
        temp_base = len(items) + 1000
        for offset, item in enumerate(items, start=1):
            item.position = temp_base + offset
        ProblemListItem.objects.bulk_update(items, ["position"])

        reordered_items = [item_by_id[item_id] for item_id in item_ids]
        for position, item in enumerate(reordered_items, start=1):
            item.position = position
        ProblemListItem.objects.bulk_update(reordered_items, ["position"])


def set_problem_list_visibility(problem_list: ProblemList, visibility: str) -> ProblemList:
    if visibility not in {ProblemList.Visibility.PRIVATE, ProblemList.Visibility.PUBLIC}:
        msg = "Choose private or public visibility."
        raise ProblemListServiceError(msg)

    if visibility == problem_list.visibility:
        return problem_list

    problem_list.visibility = visibility
    if visibility == ProblemList.Visibility.PUBLIC and problem_list.published_at is None:
        problem_list.published_at = timezone.now()
    if visibility == ProblemList.Visibility.PRIVATE:
        problem_list.published_at = None
    problem_list.save(update_fields=["visibility", "published_at", "updated_at"])
    return problem_list


def toggle_problem_list_vote(problem_list: ProblemList, user, value: int) -> int:
    if problem_list.author_id == user.id:
        msg = "Authors cannot vote on their own lists."
        raise ProblemListServiceError(msg)
    if not problem_list.is_public:
        msg = "Only public lists can receive votes."
        raise ProblemListServiceError(msg)
    if value not in {ProblemListVote.Value.DOWN, ProblemListVote.Value.UP}:
        msg = "Choose thumbs up or thumbs down."
        raise ProblemListServiceError(msg)

    vote = ProblemListVote.objects.filter(problem_list=problem_list, user=user).first()
    if vote is not None and vote.value == value:
        vote.delete()
        return 0
    if vote is not None:
        vote.value = value
        vote.save(update_fields=["value", "updated_at"])
        return value

    ProblemListVote.objects.create(problem_list=problem_list, user=user, value=value)
    return value


def _renumber_items(problem_list: ProblemList) -> None:
    items = list(ProblemListItem.objects.filter(problem_list=problem_list).order_by("position", "id"))
    if not items:
        return
    temp_base = len(items) + 1000
    for offset, item in enumerate(items, start=1):
        item.position = temp_base + offset
    ProblemListItem.objects.bulk_update(items, ["position"])
    for position, item in enumerate(items, start=1):
        item.position = position
    ProblemListItem.objects.bulk_update(items, ["position"])
