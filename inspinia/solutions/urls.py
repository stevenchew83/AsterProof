from django.urls import path

from inspinia.solutions.admin_sharing import admin_public_shares_view
from inspinia.solutions.public_views import public_solution_image_view
from inspinia.solutions.public_views import public_solution_view
from inspinia.solutions.views import admin_problem_solution_pdf_view
from inspinia.solutions.views import my_solution_list_view
from inspinia.solutions.views import problem_solution_create_view
from inspinia.solutions.views import problem_solution_edit_view
from inspinia.solutions.views import problem_solution_list_view
from inspinia.solutions.views import problem_solution_pdf_view
from inspinia.solutions.views import problem_solution_share_view
from inspinia.solutions.views import solution_body_image_upload_view

app_name = "solutions"

urlpatterns = [
    path("admin/shared/", admin_public_shares_view, name="admin_public_shares"),
    path("shared/<uuid:token>/", public_solution_view, name="public_solution"),
    path("shared/<uuid:token>/preview/<uuid:revision>.jpg", public_solution_image_view, name="public_solution_image"),
    path("", my_solution_list_view, name="my_solution_list"),
    path("new/", problem_solution_create_view, name="problem_solution_create"),
    path("problems/<uuid:problem_uuid>/", problem_solution_list_view, name="problem_solution_list"),
    path(
        "problems/<uuid:problem_uuid>/body-images/",
        solution_body_image_upload_view,
        name="solution_body_image_upload",
    ),
    path("problems/<uuid:problem_uuid>/draft/", problem_solution_edit_view, name="problem_solution_edit"),
    path("problems/<uuid:problem_uuid>/share/", problem_solution_share_view, name="problem_solution_share"),
    path(
        "problems/<uuid:problem_uuid>/draft/pdf/",
        problem_solution_pdf_view,
        name="problem_solution_pdf",
    ),
    path(
        "admin/solutions/<int:solution_pk>/pdf/",
        admin_problem_solution_pdf_view,
        name="admin_problem_solution_pdf",
    ),
]
