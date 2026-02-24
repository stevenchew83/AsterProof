from django.urls import path

from .views import contest_detail
from .views import contest_list
from .views import register_contest
from .views import run_rating_update
from .views import scoreboard
from .views import submit_solution

app_name = "contests"

urlpatterns = [
    path("", contest_list, name="list"),
    path("<int:contest_id>/", contest_detail, name="detail"),
    path("<int:contest_id>/register/", register_contest, name="register"),
    path("<int:contest_id>/scoreboard/", scoreboard, name="scoreboard"),
    path("<int:contest_id>/rate/", run_rating_update, name="rate"),
    path("<int:contest_id>/submit/<int:problem_id>/", submit_solution, name="submit"),
]
