"""Managed image readers, included in the existing solutions namespace."""

from django.urls import path

from .image_access import public_solution_asset_view
from .image_access import solution_editor_image_view
from .image_access import solution_image_view

urlpatterns = [
    path("entries/<int:solution_pk>/assets/<path:image_path>", solution_image_view, name="solution_image"),
    path(
        "problems/<uuid:problem_uuid>/assets/<path:image_path>",
        solution_editor_image_view, name="solution_editor_image",
    ),
    path(
        "shared/<uuid:token>/assets/<uuid:revision>/<path:image_path>",
        public_solution_asset_view, name="public_solution_asset",
    ),
]
