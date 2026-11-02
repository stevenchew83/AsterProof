"""One object boundary for member solutions and their forum content."""

from django.db.models import Q

from inspinia.solutions.models import ProblemSolution
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role


def visible_solutions(user):
    queryset = ProblemSolution.objects.all()
    if not user_can_access_app_features(user):
        return queryset.none()
    if user_has_admin_role(user):
        return queryset
    return queryset.filter(Q(author=user) | Q(status=ProblemSolution.Status.PUBLISHED))


def can_read_solution(user, solution):
    return user_can_access_app_features(user) and (
        user_has_admin_role(user)
        or solution.author_id == user.pk
        or solution.status == ProblemSolution.Status.PUBLISHED
    )
