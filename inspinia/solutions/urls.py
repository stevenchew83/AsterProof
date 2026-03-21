from django.urls import path

from inspinia.solutions.views import my_solution_list_view
from inspinia.solutions.views import problem_solution_edit_view
from inspinia.solutions.views import problem_solution_list_view

app_name = "solutions"

urlpatterns = [
    path("", my_solution_list_view, name="my_solution_list"),
    path("problems/<uuid:problem_uuid>/", problem_solution_list_view, name="problem_solution_list"),
    path("problems/<uuid:problem_uuid>/draft/", problem_solution_edit_view, name="problem_solution_edit"),
]
