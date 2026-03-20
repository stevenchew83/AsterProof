from django.urls import path

from inspinia.pages.views import dashboard_analytics_view
from inspinia.pages.views import problem_import_view
from inspinia.pages.views import root_page_view

app_name = "pages"

urlpatterns = [
    path("", root_page_view, name="home"),
    path("dashboard/", dashboard_analytics_view, name="dashboard"),
    path("import-problems/", problem_import_view, name="problem_import"),
]
