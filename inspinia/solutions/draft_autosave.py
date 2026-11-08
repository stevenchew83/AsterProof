from http import HTTPStatus

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.forms import PDF_DISPLAY_FIELDS
from inspinia.solutions.forms import ProblemSolutionForm
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import solution_slot_filter
from inspinia.solutions.revisions import InvalidDocument
from inspinia.solutions.revisions import InvalidEditorContext
from inspinia.solutions.revisions import StaleSolutionVersion
from inspinia.solutions.revisions import editor_context
from inspinia.solutions.revisions import save_document
from inspinia.solutions.views import _document_error_json


@login_required
@require_POST
@never_cache
def draft_autosave_view(request, problem_uuid, solution_pk=None):
    problem = get_object_or_404(ProblemSolveRecord, problem_uuid=problem_uuid)
    owned = ProblemSolution.objects.filter(problem=problem, author=request.user, **solution_slot_filter(solution_pk))
    solution = get_object_or_404(owned) if solution_pk is not None else owned.first()
    if solution is None:
        solution = ProblemSolution(problem=problem, author=request.user)
    if "writer_draft_token" in request.POST:
        return JsonResponse(
            {"error": "Save the imported draft manually first."}, status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    form = ProblemSolutionForm(request.POST, instance=solution, prefix="solution")
    if not form.is_valid():
        return JsonResponse({"error": next(iter(form.errors.values()))[0]}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
    data = form.cleaned_data
    try:
        result = save_document(
            solution=solution, user=request.user, source=data["body_source"], title=data["title"],
            summary=data["summary"], pdf_options={name: data[name] for name in PDF_DISPLAY_FIELDS},
            base_version=data["base_version"], context=data["editor_context"], action="autosave",
        )
    except (InvalidDocument, InvalidEditorContext, StaleSolutionVersion) as error:
        return _document_error_json(error)

    saved = result.solution
    return JsonResponse({
        "saved": True,
        "revision_id": str(saved.current_revision_id or ""),
        "edit_version": saved.edit_version,
        "editor_context": editor_context(request.user, problem_uuid, solution=saved),
    })
