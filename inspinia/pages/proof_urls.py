"""Public snapshot URLs are separate from authenticated community write routes."""

from django.urls import path

from . import proof_views as views

urlpatterns = [
    path("community/proofs/", views.proof_public_list, name="proof_public_list"),
    path("community/proofs/p/<uuid:token>/", views.proof_public_problem, name="proof_public_problem"),
    path(
        "community/proofs/p/<uuid:token>/solutions/<uuid:solution_id>/assets/<path:asset_name>",
        views.proof_public_asset,
        name="proof_public_asset",
    ),
    path("community/problems/<uuid:problem_id>/sharing/", views.proof_sharing, name="proof_sharing"),
    path("community/problems/<uuid:problem_id>/moderation/", views.proof_moderation, name="proof_moderation"),
    path("community/solve/<uuid:token>/", views.proof_attempt, name="proof_attempt"),
    path("community/attempts/<uuid:attempt_id>/", views.proof_attempt_edit, name="proof_attempt_edit"),
    path("community/attempts/<uuid:attempt_id>/images/", views.proof_attempt_upload, name="proof_attempt_upload"),
    path(
        "community/attempts/<uuid:attempt_id>/assets/<path:asset_name>",
        views.proof_attempt_asset,
        name="proof_attempt_asset",
    ),
    path("community/attempts/<uuid:attempt_id>/publish/", views.proof_solution_publish, name="proof_solution_publish"),
    path("community/contributions/<uuid:solution_id>/", views.proof_solution_owner, name="proof_solution_owner"),
    path(
        "community/contributions/<uuid:solution_id>/moderation/",
        views.proof_solution_moderation,
        name="proof_solution_moderation",
    ),
    path(
        "community/contributions/<uuid:solution_id>/revisions/<uuid:revision_id>/assets/<path:asset_name>",
        views.proof_solution_asset,
        name="proof_solution_asset",
    ),
    path("community/reports/<uuid:token>/", views.proof_report, name="proof_report"),
    path(
        "community/reports/<uuid:token>/solutions/<uuid:solution_id>/",
        views.proof_report,
        name="proof_solution_report",
    ),
]
