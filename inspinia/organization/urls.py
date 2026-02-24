from django.urls import path

from .views import activity_timeline
from .views import add_problem_to_list
from .views import create_list
from .views import my_lists

app_name = "organization"

urlpatterns = [
    path("", my_lists, name="lists"),
    path("new/", create_list, name="create"),
    path("<int:list_id>/add/<int:problem_id>/", add_problem_to_list, name="add_problem"),
    path("activity/", activity_timeline, name="activity"),
]
