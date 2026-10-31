"""Start authoring from the canonical statement identity, without manual linking."""

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord


@login_required
@require_POST
@transaction.atomic
def statement_solution_start_view(request, statement_uuid):
    statement = get_object_or_404(
        ContestProblemStatement.objects.select_for_update(), statement_uuid=statement_uuid, is_active=True,
    )
    if statement.linked_problem_id is None:
        # The legacy editor stores solutions against this row. Reuse the statement's
        # UUID rather than guessing a match by contest/year/code (which can repeat).
        problem, _created = ProblemSolveRecord.objects.get_or_create(
            problem_uuid=statement.problem_uuid,
            defaults={
                "contest": statement.contest_name,
                "year": statement.contest_year,
                "problem": statement.problem_code,
                "contest_year_problem": statement.contest_year_problem,
                "topic": statement.topic or "",
                "mohs": statement.mohs,
                "is_active": True,
            },
        )
        statement.linked_problem = problem
        statement.save(update_fields={"linked_problem", "updated_at"})
    return redirect("solutions:problem_solution_edit", statement.problem_uuid)
