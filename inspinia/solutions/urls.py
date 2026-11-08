from django.urls import path

from inspinia.solutions.admin_collections import admin_collection_edit_view
from inspinia.solutions.admin_collections import admin_collection_selection_view
from inspinia.solutions.admin_collections import admin_collections_view
from inspinia.solutions.admin_sharing import admin_public_shares_view
from inspinia.solutions.collection_views import collection_edit_view
from inspinia.solutions.prototype_views import synthetic_review_detail
from inspinia.solutions.prototype_views import synthetic_review_hint
from inspinia.solutions.prototype_views import synthetic_review_workspace
from inspinia.solutions.public_views import public_collection_view
from inspinia.solutions.public_views import public_solution_image_view
from inspinia.solutions.public_views import public_solution_view
from inspinia.solutions.review_views import solution_review_create_view
from inspinia.solutions.review_views import solution_review_reveal_view
from inspinia.solutions.review_views import solution_review_status_view
from inspinia.solutions.solution_picker import problem_solution_create_view
from inspinia.solutions.statement_authoring import statement_solution_start_view
from inspinia.solutions.views import admin_problem_solution_pdf_view
from inspinia.solutions.views import my_solution_list_view
from inspinia.solutions.views import problem_solution_edit_view
from inspinia.solutions.views import problem_solution_list_view
from inspinia.solutions.views import problem_solution_pdf_view
from inspinia.solutions.views import problem_solution_share_view
from inspinia.solutions.views import solution_body_image_upload_view
from inspinia.solutions.views import solution_guide_preference_view

from . import evaluation_views as evaluation
from .evaluation_consent_views import solution_reuse_consent_create_view
from .evaluation_consent_views import solution_reuse_consent_withdraw_view
from .forum_urls import urlpatterns as forum_patterns
from .image_urls import urlpatterns as image_patterns

app_name = "solutions"

urlpatterns = [
    *image_patterns,
    *forum_patterns,
    path("admin/review-prototype/", synthetic_review_workspace, name="synthetic_review_workspace"),
    path("admin/review-prototype/<uuid:review_id>/", synthetic_review_detail, name="synthetic_review_detail"),
    path("admin/review-prototype/<uuid:review_id>/hints/", synthetic_review_hint, name="synthetic_review_hint"),
    path(
        "problems/<uuid:problem_uuid>/benchmark-consent/",
        solution_reuse_consent_create_view,
        name="solution_reuse_consent_create",
    ),
    path(
        "benchmark-consents/<uuid:consent_id>/withdraw/",
        solution_reuse_consent_withdraw_view,
        name="solution_reuse_consent_withdraw",
    ),
    path("evaluation/", evaluation.evaluation_workspace, name="evaluation_workspace"),
    path("evaluation/families/new/", evaluation.evaluation_family_create, name="evaluation_family_create"),
    path(
        "evaluation/families/<uuid:family_id>/cases/new/",
        evaluation.evaluation_case_create,
        name="evaluation_case_create",
    ),
    path("evaluation/cases/<uuid:case_id>/", evaluation.evaluation_case_detail, name="evaluation_case_detail"),
    path("evaluation/cases/<uuid:case_id>/judge/", evaluation.evaluation_judgment, name="evaluation_judgment"),
    path(
        "evaluation/cases/<uuid:case_id>/adjudicate/",
        evaluation.evaluation_adjudication,
        name="evaluation_adjudication",
    ),
    path(
        "evaluation/cases/<uuid:case_id>/assets/<uuid:asset_id>/",
        evaluation.evaluation_asset,
        name="evaluation_asset",
    ),
    path("evaluation/snapshots/new/", evaluation.evaluation_snapshot_create, name="evaluation_snapshot_create"),
    path("evaluation/profiles/new/", evaluation.evaluation_profile_create, name="evaluation_profile_create"),
    path(
        "evaluation/snapshots/<uuid:snapshot_id>/protocols/new/",
        evaluation.evaluation_protocol_create,
        name="evaluation_protocol_create",
    ),
    path(
        "evaluation/protocols/<uuid:protocol_id>/",
        evaluation.evaluation_protocol_detail,
        name="evaluation_protocol_detail",
    ),
    path(
        "evaluation/snapshots/<uuid:snapshot_id>/import/",
        evaluation.evaluation_run_import,
        name="evaluation_run_import",
    ),
    path("evaluation/runs/<uuid:run_id>/", evaluation.evaluation_run_detail, name="evaluation_run_detail"),
    path(
        "evaluation/runs/<uuid:run_id>/cases/<uuid:case_id>/judge/",
        evaluation.evaluation_finding_judgment,
        name="evaluation_finding_judgment",
    ),
    path(
        "evaluation/runs/<uuid:run_id>/cases/<uuid:case_id>/adjudicate/",
        evaluation.evaluation_finding_adjudication,
        name="evaluation_finding_adjudication",
    ),
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
    path("problems/<uuid:problem_uuid>/reviews/", solution_review_create_view, name="solution_review_create"),
    path(
        "problems/<uuid:problem_uuid>/reviews/<uuid:review_id>/",
        solution_review_status_view,
        name="solution_review_status",
    ),
    path(
        "problems/<uuid:problem_uuid>/reviews/<uuid:review_id>/findings/<str:finding_id>/reveal/",
        solution_review_reveal_view,
        name="solution_review_reveal",
    ),
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
