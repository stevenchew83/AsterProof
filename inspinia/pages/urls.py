from django.urls import path

from pages.views import (
    dashboard_analytics_view,
    dynamic_pages_view,
    problem_import_view,
    root_page_view,
)

app_name = "inspinia"

urlpatterns = [
    path("", root_page_view, name="home"),
    path("dashboard/", dashboard_analytics_view, name="dashboard"),
    path("import-problems/", problem_import_view, name="problem_import"),
    path("<str:template_name>/", dynamic_pages_view, name="dynamic_pages"),
]
