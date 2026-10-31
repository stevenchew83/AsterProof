from django.urls import path

from inspinia.solutions.admin_collections import admin_collection_edit_view
from inspinia.solutions.admin_collections import admin_collection_selection_view
from inspinia.solutions.admin_collections import admin_collections_view
from inspinia.solutions.admin_sharing import admin_public_shares_view
from inspinia.solutions.collection_views import collection_edit_view
from inspinia.solutions.public_views import public_collection_view
from inspinia.solutions.public_views import public_solution_image_view
from inspinia.solutions.public_views import public_solution_view
from inspinia.solutions.statement_authoring import statement_solution_start_view
from inspinia.solutions.views import admin_problem_solution_pdf_view
from inspinia.solutions.views import my_solution_list_view
from inspinia.solutions.views import problem_solution_create_view
from inspinia.solutions.views import problem_solution_edit_view
from inspinia.solutions.views import problem_solution_list_view
from inspinia.solutions.views import problem_solution_pdf_view
from inspinia.solutions.views import problem_solution_share_view
from inspinia.solutions.views import solution_body_image_upload_view
from inspinia.solutions.views import solution_guide_preference_view

app_name = "solutions"

urlpatterns = [
    path("admin/collections/", admin_collections_view, name="admin_collections"),
    path("admin/collections/selection/", admin_collection_selection_view, name="admin_collection_selection"),
    path("admin/collections/new/", admin_collection_edit_view, name="admin_collection_create"),
    path("admin/collections/<int:collection_pk>/", admin_collection_edit_view, name="admin_collection_edit"),
    path("admin/shared/", admin_public_shares_view, name="admin_public_shares"),
    path("shared/collections/<uuid:token>/", public_collection_view, name="public_collection"),
    path("shared/<uuid:token>/", public_solution_view, name="public_solution"),
    path("shared/<uuid:token>/preview/<uuid:revision>.jpg", public_solution_image_view, name="public_solution_image"),
    path("", my_solution_list_view, name="my_solution_list"),
    path("guide/", solution_guide_preference_view, name="solution_guide_preference"),
    path("new/", problem_solution_create_view, name="problem_solution_create"),
    path("statements/<uuid:statement_uuid>/write/", statement_solution_start_view, name="statement_solution_start"),
    path("collections/new/", collection_edit_view, name="collection_create"),
    path("collections/<int:collection_pk>/", collection_edit_view, name="collection_edit"),
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
