from django.contrib import messages
from django.shortcuts import render
from django.template import TemplateDoesNotExist

from pages.forms import ProblemXlsxImportForm
from pages.problem_import import (
    ProblemImportValidationError,
    build_preview_payload,
    dataframe_from_excel,
    import_problem_dataframe,
)

# Create your views here.

# @login_required
def root_page_view(request):
    try:
        return render(request, 'pages/index.html')
    except TemplateDoesNotExist:
        return render(request, 'pages/error-404.html')


def dynamic_pages_view(request, template_name):
    try:
        return render(request, f'pages/{template_name}.html')
    except TemplateDoesNotExist:
        return render(request, f'pages/error-404.html')


def problem_import_view(request):
    """Upload analytics .xlsx, preview in a table, and/or upsert problems + topic techniques."""
    preview_payload: dict | None = None
    replace_tags_initial = request.method == "POST" and bool(request.POST.get("replace_tags"))

    if request.method == "POST":
        form = ProblemXlsxImportForm(request.POST, request.FILES)
        action = request.POST.get("action") or "import"

        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            replace_tags = form.cleaned_data["replace_tags"]
            replace_tags_initial = replace_tags

            try:
                raw = uploaded.read()
                df = dataframe_from_excel(raw)
            except ProblemImportValidationError as exc:
                messages.error(request, str(exc))
            else:
                if action == "preview":
                    preview_payload = build_preview_payload(df)
                    messages.info(
                        request,
                        f"Preview: showing {preview_payload['preview_row_count']} of "
                        f"{preview_payload['total_row_count']} row(s). "
                        "Upload the same file again and click Import to write to the database.",
                    )
                else:
                    result = import_problem_dataframe(df, replace_tags=replace_tags)
                    messages.success(
                        request,
                        f"Import finished. Upserted {result.n_records} problem record(s); "
                        f"touched {result.n_techniques} technique row(s).",
                    )
                    max_warn = 25
                    for w in result.warnings[:max_warn]:
                        messages.warning(request, w)
                    if len(result.warnings) > max_warn:
                        messages.warning(
                            request,
                            f"…and {len(result.warnings) - max_warn} more warnings (see server logs if needed).",
                        )

        form = ProblemXlsxImportForm(initial={"replace_tags": replace_tags_initial})
    else:
        form = ProblemXlsxImportForm()

    return render(
        request,
        "pages/problem-import.html",
        {"form": form, "preview_payload": preview_payload},
    )
