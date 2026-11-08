from django.urls import path

from . import views
from . import workflow_views

app_name = "learning"
urlpatterns = [
    path("", views.learn, name="learn"),
    path("explore/", views.explore, name="explore"),
    path("areas/<path:area_id>/", views.area_detail, name="area"),
    path("concepts/<str:concept_id>/", views.concept_detail, name="concept"),
    path("notes/new/", views.new_document, name="new"),
    path("notes/<uuid:document_id>/", views.document_read, name="read"),
    path("notes/<uuid:document_id>/suggest/", views.branch_document, name="branch"),
    path("notes/<uuid:document_id>/history/", workflow_views.history, name="history"),
    path("notes/<uuid:document_id>/withdraw/", views.withdraw, name="withdraw"),
    path("drafts/", views.my_drafts, name="my_drafts"),
    path("drafts/<uuid:draft_id>/", views.document_edit, name="edit"),
    path("drafts/<uuid:draft_id>/archive/", workflow_views.archive, name="archive"),
    path("drafts/<uuid:draft_id>/save/", views.draft_save, name="draft_save"),
    path("drafts/<uuid:draft_id>/preview/", views.draft_preview, name="draft_preview"),
    path("drafts/<uuid:draft_id>/images/", views.draft_upload, name="draft_upload"),
    path("drafts/<uuid:draft_id>/status/", views.draft_status, name="draft_status"),
    path("reports/", workflow_views.issues, name="issues"),
    path("notes/<uuid:document_id>/report/", workflow_views.report, name="report"),
    path("suggest/<str:kind>/<str:target_key>/", workflow_views.report, name="target_report"),
    path("drafts/<uuid:draft_id>/rebase/", workflow_views.rebase, name="rebase"),
    path("packs/", workflow_views.packs, name="packs"),
    path("packs/<slug:pack_key>/", workflow_views.packs, name="pack"),
    path("prerequisites/", workflow_views.prerequisites, name="prerequisites"),
    path("legacy/<str:kind>/<str:key>/", workflow_views.legacy_draft, name="legacy_draft"),
    path("legacy/<str:kind>/<str:key>/cutover/", workflow_views.legacy_cutover, name="legacy_cutover"),
    path("review/", views.review_queue, name="review_queue"),
    path("proposals/<uuid:proposal_id>/", views.proposal_detail, name="proposal"),
    path("receipts/<uuid:operation_id>/", views.receipt, name="receipt"),
    path("pathways/new/", views.pathway_editor, name="pathway_editor"),
    path("pathways/<slug:slug>/", views.pathway_detail, name="pathway"),
    path("pathways/<slug:slug>/read/<slug:item_key>/", views.mark_read, name="mark_read"),
]
