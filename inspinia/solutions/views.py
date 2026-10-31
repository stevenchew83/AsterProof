import logging
import re
import uuid
from collections import Counter
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldError
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import DatabaseError
from django.db import IntegrityError
from django.db import transaction
from django.db.models import Avg
from django.db.models import Count
from django.db.models import Max
from django.db.models import Prefetch
from django.db.models import Q
from django.http import FileResponse
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from PIL import Image
from PIL import UnidentifiedImageError

from inspinia.pages.asymptote_render import build_statement_render_segments
from inspinia.pages.completion_record_fields import is_completion_status_solved
from inspinia.pages.contest_links import contest_dashboard_listing_url
from inspinia.pages.models import DIFFICULTY_RATING_MAX
from inspinia.pages.models import DIFFICULTY_RATING_MIN
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import PageViewEvent
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.models import UserProblemDifficultyRating
from inspinia.pages.page_views import PageViewPayload
from inspinia.pages.page_views import record_page_view
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_concept_coverage import statement_coverage_payloads
from inspinia.pages.topic_labels import display_topic_label
from inspinia.problemsets.selectors import problem_list_add_target_rows
from inspinia.solutions.forms import ProblemSolutionBlockFormSet
from inspinia.solutions.forms import ProblemSolutionForm
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.models import SolutionBodyImage
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.pdf_latex import SolutionPdfCompileError
from inspinia.solutions.pdf_latex import SolutionPdfCompileParams
from inspinia.solutions.pdf_latex import SolutionPdfError
from inspinia.solutions.pdf_latex import SolutionPdfMissingBodyImagesError
from inspinia.solutions.pdf_latex import SolutionPdfToolError
from inspinia.solutions.pdf_latex import compile_solution_to_pdf
from inspinia.solutions.pdf_latex import solution_pdf_date_display
from inspinia.solutions.sharing import build_public_snapshot
from inspinia.solutions.sharing import public_description
from inspinia.solutions.sharing import public_preview_image
from inspinia.solutions.sharing import public_share_url
from inspinia.solutions.sharing import snapshot_digest
from inspinia.solutions.sharing import whatsapp_share_url
from inspinia.solutions.writer_drafts import WRITER_DRAFT_SESSION_KEY
from inspinia.solutions.writer_drafts import get_writer_draft
from inspinia.solutions.writer_drafts import writer_editor_initial
from inspinia.solutions.writer_drafts import writer_handoff_url
from inspinia.users.roles import user_has_admin_role

logger = logging.getLogger(__name__)

STATEMENT_BACKED_PROBLEM_LIST_LIMIT = 100

SOLUTION_BODY_IMAGE_MAX_BYTES = 3 * 1024 * 1024
SOLUTION_BODY_IMAGE_ALLOWED_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/pjpeg", "image/gif", "image/webp"},
)


def _solution_media_base_url(request) -> str:
    media = settings.MEDIA_URL
    url = (
        media
        if media.startswith(("http://", "https://"))
        else request.build_absolute_uri(media)
    )
    if not url.endswith("/"):
        url += "/"
    return url


def _absolute_media_file_url(request, file_url: str) -> str:
    if file_url.startswith(("http://", "https://")):
        return file_url
    return request.build_absolute_uri(file_url)


def _build_contest_slug_maps(contest_names: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    contest_to_slug: dict[str, str] = {}
    slug_to_contest: dict[str, str] = {}

    for contest_name in sorted({name for name in contest_names if name}):
        base_slug = slugify(contest_name) or "contest"
        contest_slug = base_slug
        suffix = 2
        while contest_slug in slug_to_contest:
            contest_slug = f"{base_slug}-{suffix}"
            suffix += 1
        contest_to_slug[contest_name] = contest_slug
        slug_to_contest[contest_slug] = contest_name

    return contest_to_slug, slug_to_contest


def _problem_anchor(problem_label: str, fallback: str) -> str:
    return slugify(problem_label) or slugify(fallback) or "problem"


def _problem_solution_prefetch():
    return Prefetch(
        "blocks",
        queryset=ProblemSolutionBlock.objects.select_related("block_type").order_by("position", "id"),
    )


def _topic_tag_display_rows(tag_rows) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_techniques: set[str] = set()
    for tag_row in tag_rows:
        technique = (tag_row.technique or "").strip()
        if not technique or technique in seen_techniques:
            continue
        seen_techniques.add(technique)
        rows.append(
            {
                "domains_label": ", ".join(tag_row.domains or []),
                "technique": technique,
            },
        )
    return rows


def _problem_context_topic_tag_rows(
    *,
    problem: ProblemSolveRecord,
    statement_entry: ContestProblemStatement | None,
) -> list[dict[str, str]]:
    if statement_entry is not None:
        statement_rows = _topic_tag_display_rows(
            StatementTopicTechnique.objects.filter(statement=statement_entry).order_by("technique", "id"),
        )
        if statement_rows:
            return statement_rows

    return _topic_tag_display_rows(
        ProblemTopicTechnique.objects.filter(record=problem).order_by("technique", "id"),
    )


def _require_admin_tools_access(request) -> None:
    if not settings.DEBUG and not user_has_admin_role(request.user):
        raise PermissionDenied


def _solution_pdf_http_response(request, solution: ProblemSolution):
    """Return PDF file response or render an error/unavailable template (blocks should be prefetched)."""
    problem = solution.problem
    problem_data = _problem_context(problem)
    problem_label = problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
    blocks = list(solution.blocks.all())
    statement_row = (
        ContestProblemStatement.objects.filter(linked_problem_id=problem.pk)
        .only("statement_latex")
        .first()
    )
    problem_statement_latex = (statement_row.statement_latex if statement_row else "") or ""

    try:
        pdf_bytes = compile_solution_to_pdf(
            solution,
            blocks,
            SolutionPdfCompileParams(
                media_root=Path(settings.MEDIA_ROOT),
                problem_label=problem_label,
                timeout=settings.SOLUTION_PDF_LATEX_TIMEOUT,
                latex_binary=settings.SOLUTION_PDF_LATEX_BINARY,
                problem_statement_latex=problem_statement_latex,
            ),
        )
    except SolutionPdfToolError as exc:
        return render(
            request,
            "solutions/solution_pdf_unavailable.html",
            {
                "problem_data": problem_data,
                "detail": (
                    "Install TeX Live (with KOMA-Script) and latexmk on the server, "
                    "or set SOLUTION_PDF_LATEX_BINARY to a suitable driver."
                ),
                "reason": str(exc),
            },
            status=503,
        )
    except SolutionPdfCompileError as exc:
        logger.warning("solution_pdf_compile_error solution_id=%s", solution.pk)
        return render(
            request,
            "solutions/solution_pdf_error.html",
            {
                "problem_data": problem_data,
                "log_tail": exc.log_tail,
            },
            status=500,
        )
    except SolutionPdfMissingBodyImagesError as exc:
        missing_paths = ", ".join(exc.missing_paths)
        return render(
            request,
            "solutions/solution_pdf_unavailable.html",
            {
                "problem_data": problem_data,
                "reason": "Pasted solution images are missing from server storage.",
                "detail": f"Pasted body images are missing from server storage: {missing_paths}",
            },
            status=500,
        )
    except SolutionPdfError as exc:
        return render(
            request,
            "solutions/solution_pdf_unavailable.html",
            {
                "problem_data": problem_data,
                "reason": str(exc),
            },
            status=500,
        )

    base = slugify(problem_label) or "solution"
    slug = slugify(solution.title or "solution") or "solution"
    filename = f"{base}-{slug}.pdf"[:200]
    return FileResponse(
        BytesIO(pdf_bytes),
        as_attachment=True,
        filename=filename,
        content_type="application/pdf",
    )


def _problem_context(problem: ProblemSolveRecord) -> dict:
    # Distinct active contests only — avoid scanning every ProblemSolveRecord row
    # (matches the dashboard contest listing slug generation).
    contest_names = list(
        ProblemSolveRecord.objects.filter(is_active=True)
        .values_list("contest", flat=True)
        .distinct(),
    )
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(contest_names)
    problem_label = problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
    contest_slug = contest_to_slug.get(problem.contest)
    contest_url = ""
    if contest_slug is not None:
        contest_url = contest_dashboard_listing_url(problem.contest)

    statement_entry = (
        ContestProblemStatement.objects.filter(linked_problem=problem)
        .order_by("-updated_at", "-id")
        .first()
    )
    return {
        "contest_archive_url": contest_url,
        "editor_url": reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]),
        "problem": problem,
        "problem_anchor": _problem_anchor(problem_label, f"{problem.year}-{problem.problem}"),
        "problem_label": problem_label,
        "problem_mohs": effective_mohs(statement_entry) if statement_entry else problem.mohs,
        "solutions_url": reverse("solutions:problem_solution_list", args=[problem.problem_uuid]),
        "statement_entry": statement_entry,
        "statement_render_segments": (
            build_statement_render_segments(statement_entry.statement_latex) if statement_entry else []
        ),
        "topic_tag_rows": _problem_context_topic_tag_rows(problem=problem, statement_entry=statement_entry),
    }


def _solution_status_badge(status: str) -> str:
    return {
        ProblemSolution.Status.ARCHIVED: "text-bg-secondary",
        ProblemSolution.Status.DRAFT: "text-bg-warning",
        ProblemSolution.Status.PUBLISHED: "text-bg-success",
        ProblemSolution.Status.SUBMITTED: "text-bg-info",
    }.get(status, "text-bg-light")


def _solution_reference_url(solution: ProblemSolution) -> str:
    problem_url = reverse("solutions:problem_solution_list", args=[solution.problem.problem_uuid])
    return f"{problem_url}?{urlencode({'solution': solution.id})}#solution-{solution.id}"


def _solution_card_rows(solutions: list[ProblemSolution]) -> list[dict]:
    rows = []
    for solution in solutions:
        blocks = [] if hasattr(solution, "block_count") else list(solution.blocks.all())
        problem_url = reverse("solutions:problem_solution_list", args=[solution.problem.problem_uuid])
        rows.append(
            {
                "anchor": f"solution-{solution.id}",
                "author_label": solution.author.name or solution.author.email,
                "blocks": blocks,
                "block_count": solution.block_count if hasattr(solution, "block_count") else len(blocks),
                "edit_url": reverse("solutions:problem_solution_edit", args=[solution.problem.problem_uuid]),
                "id": solution.id,
                "is_published": solution.status == ProblemSolution.Status.PUBLISHED,
                "has_public_link": bool(getattr(solution, "public_share_count", 0)),
                "share_manage_url": reverse("solutions:problem_solution_share", args=[solution.problem.problem_uuid]),
                "problem_label": (
                    solution.problem.contest_year_problem
                    or f"{solution.problem.contest} {solution.problem.year} {solution.problem.problem}"
                ),
                "problem_url": problem_url,
                "status": solution.status,
                "status_badge_class": _solution_status_badge(solution.status),
                "status_label": solution.get_status_display(),
                "summary": solution.summary,
                "title": solution.title or "Untitled solution",
                "updated_at_label": timezone.localtime(solution.updated_at).strftime("%Y-%m-%d %H:%M"),
                "view_url": _solution_reference_url(solution),
            },
        )
    return rows


def _difficulty_rating_payload(
    *,
    user_rating: int | None,
    average_rating: object,
    rating_count: int,
) -> dict[str, object]:
    average_value = None
    average_display = "—"
    if average_rating is not None and rating_count:
        average_value = round(float(average_rating), 1)
        average_display = f"{average_value:.1f}"

    return {
        "user_difficulty_rating": user_rating if user_rating is not None else "",
        "average_difficulty_rating": average_value,
        "average_difficulty_display": average_display,
        "difficulty_rating_count": int(rating_count or 0),
    }


def _solution_page_difficulty_payload(
    *,
    statement: ContestProblemStatement | None,
    user,
) -> dict[str, object]:
    if statement is None:
        return _difficulty_rating_payload(user_rating=None, average_rating=None, rating_count=0)

    stats = UserProblemDifficultyRating.objects.filter(statement=statement).aggregate(
        average_rating=Avg("rating"),
        rating_count=Count("id"),
    )
    user_rating = (
        UserProblemDifficultyRating.objects.filter(user=user, statement=statement)
        .values_list("rating", flat=True)
        .first()
    )
    return _difficulty_rating_payload(
        user_rating=user_rating,
        average_rating=stats["average_rating"],
        rating_count=stats["rating_count"],
    )


def _solution_completion_state_kind(*, is_solved: bool, completion_date) -> str:
    if not is_solved:
        return "unsolved"
    if completion_date is None:
        return "unknown"
    return "solved"


def _solution_completion_state_label(*, is_solved: bool, completion_date) -> str:
    if not is_solved:
        return "Unsolved"
    if completion_date is None:
        return "Solved without exact date"
    return f"Solved on {completion_date.isoformat()}"


def _solution_page_completion_payload(
    *,
    problem: ProblemSolveRecord,
    statement: ContestProblemStatement | None,
    user,
) -> dict[str, object]:
    completion = None
    if statement is not None:
        completion = UserProblemCompletion.objects.filter(user=user, statement=statement).first()
        if completion is None:
            completion = UserProblemCompletion.objects.filter(
                user=user,
                statement__isnull=True,
                problem=problem,
            ).first()
    else:
        completion = UserProblemCompletion.objects.filter(user=user, problem=problem).first()

    is_solved = completion is not None and is_completion_status_solved(completion.status)
    completion_date = completion.completion_date if completion is not None else None
    return {
        "completion_date": completion_date.isoformat() if completion_date is not None else "",
        "is_solved": is_solved,
        "state_kind": _solution_completion_state_kind(
            is_solved=is_solved,
            completion_date=completion_date,
        ),
        "state_label": _solution_completion_state_label(
            is_solved=is_solved,
            completion_date=completion_date,
        ),
    }


def _solution_form_context(solution: ProblemSolution, post_data=None) -> tuple[ProblemSolutionForm, object]:
    return (
        ProblemSolutionForm(post_data, instance=solution, prefix="solution"),
        ProblemSolutionBlockFormSet(post_data, instance=solution, prefix="blocks"),
    )


def _save_solution_form_request(
    *,
    form: ProblemSolutionForm,
    formset,
    problem: ProblemSolveRecord,
    request,
    action: str,
) -> tuple[ProblemSolution, str, str]:
    with transaction.atomic():
        solution = form.save(commit=False)
        solution.problem = problem
        solution.author = request.user
        message_text, message_level = _apply_editor_action(solution, action)
        solution.save()
        formset.instance = solution
        _save_solution_blocks(formset, solution)
    return solution, message_text, message_level


def _selected_solution_id(request) -> int | None:
    selected_solution_value = (request.GET.get("solution") or "").strip()
    if not selected_solution_value.isdigit():
        return None
    return int(selected_solution_value)


def _inline_draft_block_form(formset):
    return formset.forms[0] if formset is not None and formset.forms else None


def _problem_solution_list_inline_form_context(
    *,
    request,
    problem: ProblemSolveRecord,
    existing_solution: ProblemSolution | None,
    post_data=None,
) -> dict[str, object]:
    if existing_solution is not None and post_data is None and request.GET.get("edit") != "1":
        return {
            "inline_draft_block_form": None,
            "inline_draft_form": None,
            "inline_draft_formset": None,
        }

    solution = existing_solution or ProblemSolution(
        problem=problem,
        author=request.user,
        status=ProblemSolution.Status.DRAFT,
    )
    form, formset = _solution_form_context(solution, post_data)
    plain_block_type = SolutionBlockType.objects.filter(slug="plain").only("id").first()
    return {
        "inline_draft_block_form": _inline_draft_block_form(formset),
        "inline_draft_form": form,
        "inline_draft_formset": formset,
        "plain_block_type_id": str(plain_block_type.pk) if plain_block_type else "",
        "solution_body_image_upload_url": reverse(
            "solutions:solution_body_image_upload", args=[problem.problem_uuid],
        ),
        "solution_status_label": ProblemSolution.Status(solution.status).label,
        "public_share": (
            SolutionPublicShare.objects.filter(solution=solution, is_active=True).first() if solution.pk else None
        ),
        "pdf_author_name": (request.user.name or "").strip() or "Unknown",
        "pdf_date_label": solution_pdf_date_display(solution),
    }


def _solution_list_context(  # noqa: PLR0913
    *,
    request,
    problem: ProblemSolveRecord,
    problem_data: dict,
    solution_queryset,
    selected_solution_id: int | None,
    inline_form_context: dict[str, object] | None = None,
    show_inline_draft_editor: bool = False,
) -> dict:
    admin_view = user_has_admin_role(request.user)
    my_solution = solution_queryset.filter(author=request.user).first()
    if admin_view:
        visible_solutions = list(
            solution_queryset.order_by("-published_at", "-updated_at", "-id"),
        )
        visible_solution_rows = _solution_card_rows(visible_solutions)
        visible_solution_title = "All user solutions"
        visible_solution_empty_message = "No saved solutions are available for this problem yet."
    else:
        visible_solutions = list(
            solution_queryset.filter(status=ProblemSolution.Status.PUBLISHED)
            .exclude(author=request.user)
            .order_by("-published_at", "-updated_at", "-id"),
        )
        visible_solution_rows = _solution_card_rows(visible_solutions)
        visible_solution_title = "Published solutions"
        visible_solution_empty_message = "No other published solutions are available for this problem yet."
    published_total = solution_queryset.filter(status=ProblemSolution.Status.PUBLISHED).count()
    statement_entry = problem_data["statement_entry"]
    inline_form_context = inline_form_context or _problem_solution_list_inline_form_context(
        request=request,
        problem=problem,
        existing_solution=my_solution,
    )
    return {
        "admin_view": admin_view,
        "completion_problem_uuid": str(problem.problem_uuid),
        "completion_save_url": reverse("pages:completion_board_toggle"),
        "completion_state": _solution_page_completion_payload(
            problem=problem,
            statement=statement_entry,
            user=request.user,
        ),
        "completion_statement_uuid": str(statement_entry.statement_uuid) if statement_entry else "",
        "completion_today": timezone.localdate().isoformat(),
        "difficulty_rating": _solution_page_difficulty_payload(statement=statement_entry, user=request.user),
        "difficulty_rating_max": DIFFICULTY_RATING_MAX,
        "difficulty_rating_min": DIFFICULTY_RATING_MIN,
        "difficulty_rating_save_url": reverse("pages:problem_statement_difficulty_rating_save"),
        "difficulty_rating_statement_uuid": str(statement_entry.statement_uuid) if statement_entry else "",
        **inline_form_context,
        "my_solution_row": _solution_card_rows([my_solution])[0] if my_solution is not None else None,
        "problem_data": problem_data,
        "problem_list_add_targets": problem_list_add_target_rows(request.user),
        "problem_list_next_url": request.get_full_path(),
        "selected_solution_id": selected_solution_id,
        "show_inline_draft_editor": show_inline_draft_editor or request.GET.get("edit") == "1",
        "solution_media_base_url": _solution_media_base_url(request),
        "visible_solution_empty_message": visible_solution_empty_message,
        "visible_solution_rows": visible_solution_rows,
        "visible_solution_title": visible_solution_title,
        "solution_stats": {
            "published_total": published_total,
            "visible_total": len(visible_solutions) + (0 if admin_view else (1 if my_solution is not None else 0)),
        },
    }


def _record_solution_page_view(request, problem: ProblemSolveRecord, *, published_total: int) -> None:
    problem_label = problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
    record_page_view(
        request,
        payload=PageViewPayload(
            view_type=PageViewEvent.ViewType.SOLUTION,
            label=problem_label,
            object_uuid=problem.problem_uuid,
            contest_name=problem.contest,
            contest_year=problem.year,
            metadata={"published_total": published_total},
        ),
    )


def _solution_list_response(  # noqa: PLR0913
    request,
    *,
    problem: ProblemSolveRecord,
    problem_data: dict,
    solution_queryset,
    selected_solution_id: int | None,
    inline_form_context: dict[str, object] | None = None,
    show_inline_draft_editor: bool = False,
):
    context = _solution_list_context(
        request=request,
        problem=problem,
        problem_data=problem_data,
        solution_queryset=solution_queryset,
        selected_solution_id=selected_solution_id,
        inline_form_context=inline_form_context,
        show_inline_draft_editor=show_inline_draft_editor,
    )
    _record_solution_page_view(
        request,
        problem,
        published_total=context["solution_stats"]["published_total"],
    )
    return render(request, "solutions/problem-solution-list.html", context)


def _statement_preview_text(statement_latex: str, *, max_length: int = 220) -> str:
    collapsed = re.sub(r"\s+", " ", (statement_latex or "").strip())
    if len(collapsed) <= max_length:
        return collapsed
    return f"{collapsed[: max_length - 1].rstrip()}…"


def _statement_backed_problem_rows(user) -> tuple[list[dict], dict[str, bool | int]]:
    latest_statement_by_problem_id: dict[int, ContestProblemStatement] = {}
    for statement in (
        ContestProblemStatement.objects.filter(linked_problem__isnull=False)
        .select_related("linked_problem")
        .order_by("-updated_at", "-id")
    ):
        if statement.linked_problem_id in latest_statement_by_problem_id:
            continue
        latest_statement_by_problem_id[statement.linked_problem_id] = statement
        if len(latest_statement_by_problem_id) >= STATEMENT_BACKED_PROBLEM_LIST_LIMIT:
            break

    if not latest_statement_by_problem_id:
        return [], {"is_capped": False, "limit": STATEMENT_BACKED_PROBLEM_LIST_LIMIT}

    capped_problem_ids = list(latest_statement_by_problem_id.keys())
    list_is_capped = len(capped_problem_ids) >= STATEMENT_BACKED_PROBLEM_LIST_LIMIT and (
        ContestProblemStatement.objects.filter(linked_problem__isnull=False)
        .exclude(linked_problem_id__in=capped_problem_ids)
        .exists()
    )

    statements = list(latest_statement_by_problem_id.values())
    problem_ids = [statement.linked_problem_id for statement in statements if statement.linked_problem_id is not None]
    solution_status_by_problem_id = {
        row["problem_id"]: row["status"]
        for row in ProblemSolution.objects.filter(
            author=user,
            problem_id__in=problem_ids,
        ).values("problem_id", "status")
    }
    contest_to_slug, _slug_to_contest = _build_contest_slug_maps(
        [statement.linked_problem.contest for statement in statements if statement.linked_problem is not None],
    )

    rows: list[dict] = []
    for statement in sorted(
        statements,
        key=lambda row: (
            -int(row.linked_problem.year),
            row.linked_problem.contest,
            row.linked_problem.problem,
            row.problem_code,
        ),
    ):
        problem = statement.linked_problem
        if problem is None:
            continue

        problem_label = problem.contest_year_problem or f"{problem.contest} {problem.year} {problem.problem}"
        solution_status = solution_status_by_problem_id.get(problem.id, "")
        contest_slug = contest_to_slug.get(problem.contest)
        contest_archive_url = ""
        if contest_slug:
            contest_archive_url = contest_dashboard_listing_url(
                problem.contest,
                year=int(problem.year),
            ) + "#" + _problem_anchor(
                problem_label,
                f"{problem.year}-{problem.problem}",
            )

        rows.append(
            {
                "contest_archive_url": contest_archive_url,
                "editor_button_label": "Continue solution" if solution_status else "Start solution",
                "editor_url": reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]),
                "has_solution": bool(solution_status),
                "problem_label": problem_label,
                "problem_topic": display_topic_label(problem.topic),
                "problem_mohs": problem.mohs,
                "problem_url": reverse("solutions:problem_solution_list", args=[problem.problem_uuid]),
                "solution_status_badge_class": (
                    _solution_status_badge(solution_status) if solution_status else "text-bg-light"
                ),
                "solution_status_label": (
                    ProblemSolution.Status(solution_status).label if solution_status else "Not started"
                ),
                "statement_label": (
                    f"{statement.problem_code} · {statement.day_label}"
                    if statement.day_label
                    else statement.problem_code
                ),
                "statement_preview": _statement_preview_text(statement.statement_latex),
                "statement_updated_at_label": timezone.localtime(statement.updated_at).strftime("%Y-%m-%d"),
            },
        )

    return rows, {
        "is_capped": list_is_capped,
        "limit": STATEMENT_BACKED_PROBLEM_LIST_LIMIT,
    }


def _save_solution_blocks(formset, solution: ProblemSolution) -> None:
    ordered_forms = [
        form
        for form in formset.ordered_forms
        if getattr(form, "cleaned_data", None) and not form.cleaned_data.get("DELETE")
    ]
    deleted_blocks = [
        form.instance
        for form in formset.forms
        if getattr(form, "cleaned_data", None) and form.cleaned_data.get("DELETE") and form.instance.pk
    ]
    existing_blocks = [form.instance for form in ordered_forms if form.instance.pk]
    if existing_blocks:
        max_position = solution.blocks.aggregate(max_position=Max("position"))["max_position"] or 0
        temp_base = max_position + len(existing_blocks) + 1000
        for offset, block in enumerate(existing_blocks, start=1):
            block.position = temp_base + offset
        ProblemSolutionBlock.objects.bulk_update(existing_blocks, ["position"])

    for deleted_block in deleted_blocks:
        deleted_block.delete()

    for position, form in enumerate(ordered_forms, start=1):
        block = form.save(commit=False)
        block.solution = solution
        block.parent_block = None
        block.position = position
        block.save()


def _apply_editor_action(solution: ProblemSolution, action: str) -> tuple[str, str]:
    now = timezone.now()
    if action == "publish":
        solution.status = ProblemSolution.Status.PUBLISHED
        solution.published_at = now
        if solution.submitted_at is None:
            solution.submitted_at = now
        return "Published solution.", "success"
    if action == "save_draft":
        solution.status = ProblemSolution.Status.DRAFT
        solution.published_at = None
        solution.submitted_at = None
        return "Saved draft.", "success"
    if not solution.status:
        solution.status = ProblemSolution.Status.DRAFT
    return "Saved changes.", "success"


@login_required
@never_cache
def my_solution_list_view(request):
    solutions = list(
        ProblemSolution.objects.filter(author=request.user)
        .select_related("problem", "author")
        .annotate(
            block_count=Count("blocks"),
            public_share_count=Count("public_share", filter=Q(public_share__is_active=True), distinct=True),
        )
        .order_by("-updated_at", "-id"),
    )
    status_counts = Counter(solution.status for solution in solutions)
    context = {
        "my_solution_rows": _solution_card_rows(solutions),
        "writer_draft": get_writer_draft(request),
        "writer_handoff_url": writer_handoff_url(),
        "my_solution_stats": {
            "draft_total": status_counts[ProblemSolution.Status.DRAFT],
            "published_total": status_counts[ProblemSolution.Status.PUBLISHED],
            "submitted_total": status_counts[ProblemSolution.Status.SUBMITTED],
            "total": len(solutions),
        },
    }
    return render(request, "solutions/my-solution-list.html", context)


@login_required
@never_cache
def problem_solution_create_view(request):
    statement_problem_rows, statement_problem_list_meta = _statement_backed_problem_rows(request.user)
    writer_draft = get_writer_draft(request) if request.GET.get("from_writer") == "1" else None
    if writer_draft:
        for row in statement_problem_rows:
            if not row["has_solution"]:
                row["editor_url"] += "?" + urlencode({"from_writer": writer_draft["token"]})
                row["editor_button_label"] = "Continue with this problem"
    started_total = sum(1 for row in statement_problem_rows if row["has_solution"])
    context = {
        "create_stats": {
            "ready_total": len(statement_problem_rows) - started_total,
            "started_total": started_total,
            "statement_problem_total": len(statement_problem_rows),
        },
        "statement_problem_list_is_capped": statement_problem_list_meta["is_capped"],
        "statement_problem_list_limit": statement_problem_list_meta["limit"],
        "statement_problem_rows": statement_problem_rows,
        "writer_draft": writer_draft,
    }
    return render(request, "solutions/problem-solution-create.html", context)


@login_required
def problem_solution_list_view(request, problem_uuid):
    problem = get_object_or_404(ProblemSolveRecord, problem_uuid=problem_uuid)
    problem_data = _problem_context(problem)
    solution_queryset = (
        ProblemSolution.objects.filter(problem=problem)
        .select_related("author", "problem")
        .prefetch_related(_problem_solution_prefetch())
    )
    selected_solution_id = _selected_solution_id(request)
    if selected_solution_id is not None and not solution_queryset.filter(pk=selected_solution_id).exists():
        selected_solution_id = None

    my_solution = solution_queryset.filter(author=request.user).first()
    if request.method == "POST":
        inline_form_context = _problem_solution_list_inline_form_context(
            request=request,
            problem=problem,
            existing_solution=my_solution,
            post_data=request.POST,
        )
        form = inline_form_context["inline_draft_form"]
        formset = inline_form_context["inline_draft_formset"]
        if form is not None and formset is not None and form.is_valid() and formset.is_valid():
            action = request.POST.get("action") or "save_draft"
            solution, message_text, message_level = _save_solution_form_request(
                form=form,
                formset=formset,
                problem=problem,
                request=request,
                action=action,
            )
            getattr(messages, message_level)(request, message_text)
            return redirect(_solution_reference_url(solution))
        return _solution_list_response(
            request,
            problem=problem,
            problem_data=problem_data,
            solution_queryset=solution_queryset,
            selected_solution_id=selected_solution_id,
            inline_form_context=inline_form_context,
            show_inline_draft_editor=True,
        )

    return _solution_list_response(
        request,
        problem=problem,
        problem_data=problem_data,
        solution_queryset=solution_queryset,
        selected_solution_id=selected_solution_id,
    )


@login_required
@never_cache
def problem_solution_edit_view(request, problem_uuid):
    problem = get_object_or_404(ProblemSolveRecord, problem_uuid=problem_uuid)
    solution = ProblemSolution.objects.filter(problem=problem, author=request.user).first()
    draft = get_writer_draft(request)
    writer_token = request.POST.get("writer_draft_token") or request.GET.get("from_writer")
    writer_import = draft if draft and writer_token == draft["token"] else None
    existing_solution = solution is not None
    if request.method == "GET" and writer_token and (not writer_import or existing_solution):
        messages.warning(
            request, "Your writing has not replaced any saved solution. Choose an unused problem to continue.",
        )
        return redirect(writer_handoff_url())
    if solution is None:
        solution = ProblemSolution(problem=problem, author=request.user, status=ProblemSolution.Status.DRAFT)

    form, formset = _solution_form_context(solution, request.POST or None)
    if writer_import and request.method == "GET":
        initial, blocks = writer_editor_initial(writer_import)
        form = ProblemSolutionForm(instance=solution, prefix="solution", initial=initial)
        formset = ProblemSolutionBlockFormSet(instance=solution, prefix="blocks", initial=blocks)
        formset.extra = len(blocks)
    if request.method == "POST" and writer_token and (
        not writer_import or existing_solution or request.POST.get("action") == "publish"
    ):
        form.add_error(None, (
            "This handoff cannot be saved here. Your writing is still in this form; "
            "return to the problem picker to continue with your pending draft."
        ))

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        action = "save_draft" if writer_import else request.POST.get("action") or "save"
        try:
            solution, message_text, message_level = _save_solution_form_request(
                form=form, formset=formset, problem=problem, request=request, action=action,
            )
        except IntegrityError:
            if not writer_import:
                raise
            form.add_error(None, (
                "A solution could not be created for this problem. Your pending draft is still available; "
                "choose another problem and try again."
            ))
        else:
            if writer_import:
                request.session.pop(WRITER_DRAFT_SESSION_KEY, None)
            getattr(messages, message_level)(request, message_text)
            return redirect("solutions:problem_solution_edit", problem.problem_uuid)

    current_status = solution.status or ProblemSolution.Status.DRAFT
    problem_data = _problem_context(problem)
    coverage_source = problem_data["statement_entry"] or ContestProblemStatement(
        linked_problem=problem, topic=problem.topic, is_active=problem.is_active,
    )
    editor_coverage = statement_coverage_payloads([coverage_source])[coverage_source.pk]
    plain_block_type = SolutionBlockType.objects.filter(slug="plain").only("id").first()
    context = {
        "form": form,
        "formset": formset,
        "public_share": (
            SolutionPublicShare.objects.filter(solution=solution, is_active=True).first() if solution.pk else None
        ),
        "writer_import": writer_import,
        "plain_block_type_id": str(plain_block_type.id) if plain_block_type is not None else "",
        "problem_data": problem_data,
        "completion_state": _solution_page_completion_payload(
            problem=problem, statement=problem_data["statement_entry"], user=request.user,
        ),
        "solution_body_image_upload_url": reverse(
            "solutions:solution_body_image_upload",
            args=[problem.problem_uuid],
        ),
        "solution_media_base_url": _solution_media_base_url(request),
        "editor_coverage": editor_coverage,
        "solution_status_badge_class": _solution_status_badge(current_status),
        "solution_status_label": ProblemSolution.Status(current_status).label,
        "pdf_author_name": (request.user.name or "").strip() or "Unknown",
        "pdf_date_label": solution_pdf_date_display(solution),
    }
    return render(request, "solutions/problem-solution-editor.html", context)


@login_required
@never_cache
@transaction.atomic
def problem_solution_share_view(request, problem_uuid):
    queryset = ProblemSolution.objects.select_related("author", "problem")
    if request.method == "POST":
        # All share mutations lock the same owner row, including first creation.
        queryset = queryset.select_for_update(of=("self",))
    solution = get_object_or_404(queryset, problem__problem_uuid=problem_uuid, author=request.user)
    share = SolutionPublicShare.objects.filter(solution=solution).first()
    if request.method == "POST":
        return _change_solution_sharing(request, solution, share)
    if request.method != "GET":
        return HttpResponseBadRequest("Use GET to review or POST to change sharing.")
    review_error = ""
    try:
        snapshot = _public_snapshot(solution)
    except ValidationError as exc:
        snapshot = None
        review_error = " ".join(exc.messages)
        if not _sharing_json_request(request):
            messages.error(request, review_error)
    share_url = public_share_url(share) if share and share.is_active else ""
    context = {
        "solution": solution,
        "snapshot": snapshot,
        "share": share,
        "share_url": share_url,
        "whatsapp_url": whatsapp_share_url(share_url),
        "preview_description": public_description(snapshot) if snapshot else "",
        "share_outdated": bool(share and share.is_active and (
            share.source_updated_at != solution.updated_at or snapshot is None
            or snapshot_digest(share.snapshot) != snapshot_digest(snapshot)
        )),
        "solution_media_url": settings.MEDIA_URL,
        "review_snapshot": True,
        "review_digest": snapshot_digest(snapshot) if snapshot else "",
    }
    if _sharing_json_request(request):
        return JsonResponse({
            "is_active": bool(share_url),
            "can_share": snapshot is not None,
            "share_url": share_url,
            "whatsapp_url": context["whatsapp_url"] if share_url else "",
            "preview_url": share_url or reverse("solutions:problem_solution_share", args=[problem_uuid]),
            "review_url": reverse("solutions:problem_solution_share", args=[problem_uuid]),
            "source_version": solution.updated_at.isoformat(),
            "share_revision": str(share.revision) if share else "",
            "review_digest": context["review_digest"],
            "has_saved_changes": context["share_outdated"],
            "saved_title": snapshot["title"] if snapshot else solution.title,
            "saved_author": snapshot["author"] if snapshot else "",
            "saved_date": snapshot["date"] if snapshot else "",
            "shared_at": timezone.localtime(share.updated_at).strftime("%d %b %Y, %H:%M") if share_url else "",
            "error": review_error,
        })
    return render(request, "solutions/problem-solution-share.html", context)


def _sharing_json_request(request):
    return "application/json" in request.headers.get("Accept", "")


def _sharing_result(request, solution, message, *, status=HTTPStatus.OK):
    if _sharing_json_request(request):
        return JsonResponse({"ok": status == HTTPStatus.OK, "message": message}, status=status)
    level = "success" if status == HTTPStatus.OK else "warning"
    getattr(messages, level)(request, message)
    return redirect("solutions:problem_solution_share", solution.problem.problem_uuid)


def _sharing_action_error(request, solution, share):
    expected_revision = str(share.revision) if share else ""
    if request.POST.get("share_revision", "") != expected_revision:
        return "Sharing changed in another tab. Review the current version before trying again."
    if request.POST["action"] == "stop":
        return ""
    if request.POST.get("source_version") != solution.updated_at.isoformat():
        return "Your saved solution changed. Review its latest saved version before sharing."
    if (request.POST["action"] == "update") != bool(share and share.is_active):
        return "Review the current sharing settings before trying again."
    return ""


def _change_solution_sharing(request, solution, share):
    action = request.POST.get("action")
    if action not in {"create", "update", "stop"}:
        return (
            _sharing_result(request, solution, "Unknown sharing action.", status=400)
            if _sharing_json_request(request) else HttpResponseBadRequest("Unknown sharing action.")
        )
    error = _sharing_action_error(request, solution, share)
    if error:
        return _sharing_result(request, solution, error, status=409)
    if action == "stop":
        if share and share.is_active:
            share.is_active = False
            share.snapshot = {}
            share.preview_image = b""
            share.revision = uuid.uuid4()
            share.save()
        return _sharing_result(request, solution, "Public sharing stopped. Your saved solution is unchanged.")
    try:
        snapshot = _public_snapshot(solution)
    except ValidationError as exc:
        return _sharing_result(request, solution, " ".join(exc.messages), status=400)
    if request.POST.get("review_digest") != snapshot_digest(snapshot):
        return _sharing_result(
            request, solution, "The saved preview changed. Review it again before sharing.", status=409,
        )
    _write_shared_snapshot(solution, share, snapshot)
    message = "Shared version updated." if action == "update" else "Public link created."
    return _sharing_result(request, solution, message)


def _write_shared_snapshot(solution, share, snapshot):
    if share is None:
        share = SolutionPublicShare(solution=solution)
    elif not share.is_active:
        share.token = uuid.uuid4()
    share.snapshot = snapshot
    share.preview_image = public_preview_image()
    share.source_updated_at = solution.updated_at
    share.revision = uuid.uuid4()
    share.is_active = True
    share.save()


def _public_snapshot(solution):
    problem_data = _problem_context(solution.problem)
    source = problem_data["statement_entry"] or ContestProblemStatement(
        linked_problem=solution.problem, topic=solution.problem.topic, is_active=solution.problem.is_active,
    )
    coverage = statement_coverage_payloads([source])[source.pk]
    return build_public_snapshot(solution, problem_data, coverage)


@login_required
def problem_solution_pdf_view(request, problem_uuid):
    problem = get_object_or_404(ProblemSolveRecord, problem_uuid=problem_uuid)
    solution = (
        ProblemSolution.objects.filter(problem=problem, author=request.user)
        .select_related("author")
        .prefetch_related(_problem_solution_prefetch())
        .first()
    )
    problem_data = _problem_context(problem)
    if solution is None:
        return render(
            request,
            "solutions/solution_pdf_unavailable.html",
            {
                "problem_data": problem_data,
                "reason": "Save your solution at least once before downloading a PDF.",
            },
            status=404,
        )
    return _solution_pdf_http_response(request, solution)


@login_required
def admin_problem_solution_pdf_view(request, solution_pk: int):
    """Admin inventory: download any user's solution as Evan-format PDF (same pipeline as author PDF)."""
    _require_admin_tools_access(request)
    solution = get_object_or_404(
        ProblemSolution.objects.select_related("author", "problem").prefetch_related(_problem_solution_prefetch()),
        pk=solution_pk,
    )
    return _solution_pdf_http_response(request, solution)


@login_required
@require_POST
def solution_body_image_upload_view(request, problem_uuid):  # noqa: C901, PLR0911
    problem = get_object_or_404(ProblemSolveRecord, problem_uuid=problem_uuid)
    upload = request.FILES.get("image")
    if upload is None:
        return JsonResponse({"error": "Missing image file."}, status=400)

    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in SOLUTION_BODY_IMAGE_ALLOWED_TYPES:
        return JsonResponse({"error": "Unsupported image type."}, status=400)

    if upload.size is not None and upload.size > SOLUTION_BODY_IMAGE_MAX_BYTES:
        return JsonResponse({"error": "Image too large."}, status=400)

    data = upload.read()
    if len(data) > SOLUTION_BODY_IMAGE_MAX_BYTES:
        return JsonResponse({"error": "Image too large."}, status=400)

    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError):
        return JsonResponse({"error": "Invalid image file."}, status=400)

    # Django 5.1+ FileField.pre_save rejects nameless ContentFile in some paths.
    image_file = ContentFile(data, name="paste.png")
    try:
        with transaction.atomic():
            solution, _created = ProblemSolution.objects.get_or_create(
                problem=problem,
                author=request.user,
                defaults={"status": ProblemSolution.Status.DRAFT},
            )
            row = SolutionBodyImage(
                solution=solution,
                uploaded_by=request.user,
            )
            row.file.save("paste.png", image_file, save=True)
    except FieldError as exc:
        logger.exception("solution_body_image_field_error")
        payload = {"error": "Could not store the image."}
        if settings.DEBUG:
            payload["detail"] = str(exc)
        return JsonResponse(payload, status=500)
    except DatabaseError as exc:
        logger.exception("solution_body_image_database_error")
        payload = {
            "error": (
                "Database error while saving the image. If you recently pulled code, run "
                "`python manage.py migrate` (especially the `solutions` app)."
            ),
        }
        if settings.DEBUG:
            payload["detail"] = str(exc)
        return JsonResponse(payload, status=500)
    except OSError as exc:
        logger.exception("solution_body_image_io_error")
        payload = {"error": "Could not write the image to server storage (check MEDIA_ROOT permissions)."}
        if settings.DEBUG:
            payload["detail"] = str(exc)
        return JsonResponse(payload, status=500)

    canonical_path = row.file.name.replace("\\", "/")
    return JsonResponse(
        {
            "path": canonical_path,
            "url": _absolute_media_file_url(request, row.file.url),
        },
    )
