from django.urls import path

from .views import problem_detail_view
from .views import problem_list_view
from .views import problem_quick_status_partial
from .views import report_problem

app_name = "catalog"

urlpatterns = [
    path("", problem_list_view, name="list"),
    path("<int:problem_id>/", problem_detail_view, name="detail"),
    path("<int:problem_id>/quick-status/", problem_quick_status_partial, name="quick_status"),
    path("<int:problem_id>/report/", report_problem, name="report_problem"),
]
