from django.urls import path

from inspinia.pages.views import completion_board_bulk_view
from inspinia.pages.views import completion_board_toggle_view
from inspinia.pages.views import completion_board_view
from inspinia.pages.views import contest_analytics_view
from inspinia.pages.views import contest_details_view
from inspinia.pages.views import contest_problem_list_view
from inspinia.pages.views import contest_rename_view
from inspinia.pages.views import dashboard_analytics_view
from inspinia.pages.views import handle_summary_parser_view
from inspinia.pages.views import latex_preview_view
from inspinia.pages.views import problem_import_view
from inspinia.pages.views import problem_list_view
from inspinia.pages.views import problem_statement_analytics_view
from inspinia.pages.views import problem_statement_duplicate_view
from inspinia.pages.views import problem_statement_linker_view
from inspinia.pages.views import problem_statement_list_view
from inspinia.pages.views import problem_statement_metadata_view
from inspinia.pages.views import root_page_view
from inspinia.pages.views import statement_render_preview_view
from inspinia.pages.views import topic_tag_analytics_view
from inspinia.pages.views import user_activity_dashboard_view

app_name = "pages"

urlpatterns = [
    path("", root_page_view, name="home"),
    path("dashboard/my-activity/", user_activity_dashboard_view, name="user_activity_dashboard"),
    path("dashboard/completion-board/", completion_board_view, name="completion_board"),
    path("dashboard/completion-board/toggle/", completion_board_toggle_view, name="completion_board_toggle"),
    path("dashboard/completion-board/bulk/", completion_board_bulk_view, name="completion_board_bulk"),
    path("dashboard/", dashboard_analytics_view, name="dashboard"),
    path("dashboard/contests/", contest_analytics_view, name="contest_dashboard"),
    path("dashboard/topic-tags/", topic_tag_analytics_view, name="topic_tag_dashboard"),
    path(
        "dashboard/problem-statements/analytics/",
        problem_statement_analytics_view,
        name="problem_statement_dashboard",
    ),
    path("dashboard/problem-statements/", problem_statement_list_view, name="problem_statement_list"),
    path(
        "tools/problem-statements/linker/",
        problem_statement_linker_view,
        name="problem_statement_linker",
    ),
    path(
        "tools/problem-statements/duplicates/",
        problem_statement_duplicate_view,
        name="problem_statement_duplicates",
    ),
    path(
        "tools/problem-statements/metadata/",
        problem_statement_metadata_view,
        name="problem_statement_metadata",
    ),
    path("tools/contest-details/", contest_details_view, name="contest_details"),
    path("tools/contest-rename/", contest_rename_view, name="contest_rename"),
    path("tools/handle-summary-parser/", handle_summary_parser_view, name="handle_summary_parser"),
    path("tools/latex-preview/", latex_preview_view, name="latex_preview"),
    path("tools/render-statement/", statement_render_preview_view, name="statement_render_preview"),
    path("problems/", problem_list_view, name="problem_list"),
    path("problems/contests/<slug:contest_slug>/", contest_problem_list_view, name="contest_problem_list"),
    path("import-problems/", problem_import_view, name="problem_import"),
]
