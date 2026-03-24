from django.urls import path

from inspinia.solutions.views import my_solution_list_view
from inspinia.solutions.views import problem_solution_create_view
from inspinia.solutions.views import problem_solution_edit_view
from inspinia.solutions.views import problem_solution_list_view
from inspinia.solutions.views import problem_solution_pdf_view
from inspinia.solutions.views import solution_body_image_upload_view

app_name = "solutions"

urlpatterns = [
    path("", my_solution_list_view, name="my_solution_list"),
    path("new/", problem_solution_create_view, name="problem_solution_create"),
    path("problems/<uuid:problem_uuid>/", problem_solution_list_view, name="problem_solution_list"),
    path(
        "problems/<uuid:problem_uuid>/body-images/",
        solution_body_image_upload_view,
        name="solution_body_image_upload",
    ),
    path("problems/<uuid:problem_uuid>/draft/", problem_solution_edit_view, name="problem_solution_edit"),
    path(
        "problems/<uuid:problem_uuid>/draft/pdf/",
        problem_solution_pdf_view,
        name="problem_solution_pdf",
    ),
]
