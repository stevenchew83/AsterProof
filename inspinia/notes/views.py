from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from inspinia.core.permissions import require_learning_state_allowed
from inspinia.core.markdown import render_markdown_with_math
from inspinia.notes.models import PrivateNote


@login_required
def note_editor(request, problem_id: int):
    note, _ = PrivateNote.objects.get_or_create(user=request.user, problem_id=problem_id)
    rendered = render_markdown_with_math(note.content)
    return render(
        request,
        "notes/editor.html",
        {"note": note, "problem_id": problem_id, "rendered_note_html": rendered},
    )


@login_required
def autosave_note(request, problem_id: int):
    blocked = require_learning_state_allowed(request.user)
    if blocked:
        return blocked
    note, _ = PrivateNote.objects.get_or_create(user=request.user, problem_id=problem_id)
    note.content = request.POST.get("content", "")
    note.save(update_fields=["content", "updated_at"])
    return JsonResponse(
        {
            "saved": True,
            "updated_at": note.updated_at.isoformat(),
            "rendered_html": render_markdown_with_math(note.content),
        },
    )
