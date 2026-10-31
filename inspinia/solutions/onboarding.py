"""Getting-started progress comes from the owner's saved work, never tour clicks."""

from django.urls import reverse

from inspinia.users.models import User


def solution_guide_context(user, solutions, *, writer_draft):
    shared = next((solution for solution in solutions if solution.public_share_count), None)
    # Editor validation requires content in every saved block. Image uploads can
    # create a solution record without blocks; those are still unfinished drafts.
    saved = next((solution for solution in solutions if solution.block_count), None)
    current = shared or saved or next(iter(solutions), None)
    has_saved_content = bool(shared or saved)
    create_url = reverse("solutions:problem_solution_create")
    if writer_draft:
        from inspinia.solutions.writer_drafts import writer_handoff_url

        create_url = writer_handoff_url()
    editor_url = reverse("solutions:problem_solution_edit", args=[current.problem.problem_uuid]) if current else ""
    share_url = reverse("solutions:problem_solution_share", args=[current.problem.problem_uuid]) if current else ""
    return {
        "visible": user.solution_guide_status == User.SolutionGuideStatus.ACTIVE,
        "chosen": bool(current),
        "saved": has_saved_content,
        "shared": bool(shared),
        "completed_steps": int(bool(current)) + int(has_saved_content) + int(bool(shared)),
        "start_url": create_url,
        "editor_url": editor_url,
        "share_url": share_url,
    }
