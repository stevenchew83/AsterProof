from django.urls import path

from inspinia.pages.views import contest_analytics_view
from inspinia.pages.views import contest_problem_list_view
from inspinia.pages.views import dashboard_analytics_view
from inspinia.pages.views import latex_preview_view
from inspinia.pages.views import problem_import_view
from inspinia.pages.views import problem_list_view
from inspinia.pages.views import problem_statement_list_view
from inspinia.pages.views import root_page_view
from inspinia.pages.views import topic_tag_analytics_view

app_name = "pages"

urlpatterns = [
    path("", root_page_view, name="home"),
    path("dashboard/", dashboard_analytics_view, name="dashboard"),
    path("dashboard/contests/", contest_analytics_view, name="contest_dashboard"),
    path("dashboard/topic-tags/", topic_tag_analytics_view, name="topic_tag_dashboard"),
    path("dashboard/problem-statements/", problem_statement_list_view, name="problem_statement_list"),
    path("tools/latex-preview/", latex_preview_view, name="latex_preview"),
    path("problems/", problem_list_view, name="problem_list"),
    path("problems/contests/<slug:contest_slug>/", contest_problem_list_view, name="contest_problem_list"),
    path("import-problems/", problem_import_view, name="problem_import"),
]
