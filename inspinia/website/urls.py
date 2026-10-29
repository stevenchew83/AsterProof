from django.urls import path

from . import backend
from . import views
from .solution_preview import solution_preview_view

app_name = "website"

urlpatterns = [
    path("tools/solution-preview/", solution_preview_view, name="solution_preview"),
    path("problem-solving/", views.problem_solving_view, name="problem_solving"),
    path("manage/newsletter/", backend.index, name="newsletter_dashboard"),
    path("manage/newsletter/automation/", backend.automation_settings, name="newsletter_automation"),
    path("manage/newsletter/bounces/", backend.bounce_import, name="newsletter_bounces"),
    path("manage/newsletter/holds/<uuid:pk>/clear/", backend.clear_sending_hold, name="newsletter_clear_hold"),
    path("manage/newsletter/subscribers/", backend.subscribers, name="newsletter_subscribers"),
    path("manage/newsletter/subscribers/<uuid:pk>/", backend.subscriber, name="newsletter_subscriber"),
    path("manage/newsletter/drafts/new/", backend.campaign_editor, name="newsletter_campaign_new"),
    path("manage/newsletter/campaigns/<uuid:pk>/", backend.campaign_editor, name="newsletter_campaign"),
    path("manage/newsletter/campaigns/<uuid:pk>/preview/", backend.campaign_preview, name="newsletter_preview"),
    path("manage/newsletter/campaigns/<uuid:pk>/send/", backend.campaign_send, name="newsletter_send"),
    path("manage/newsletter/campaigns/<uuid:pk>/status/", backend.campaign_status, name="newsletter_status"),
    path("manage/newsletter/campaigns/<uuid:pk>/schedule/", backend.campaign_schedule, name="newsletter_schedule"),
    path(
        "manage/newsletter/campaigns/<uuid:pk>/cancel-schedule/",
        backend.campaign_cancel_schedule, name="newsletter_cancel_schedule",
    ),
    path("manage/newsletter/campaigns/<uuid:pk>/next/", backend.campaign_step, name="newsletter_send_next"),
    path("manage/newsletter/campaigns/<uuid:pk>/resume/", backend.campaign_resume, name="newsletter_resume"),
    path("manage/newsletter/campaigns/<uuid:pk>/pause/", backend.campaign_pause, name="newsletter_pause"),
    path("manage/newsletter/campaigns/<uuid:pk>/review/", backend.campaign_interrupted, name="newsletter_interrupted"),
    path("manage/newsletter/campaigns/<uuid:pk>/duplicate/", backend.campaign_duplicate, name="newsletter_duplicate"),
    path("manage/newsletter/history/", backend.history, name="newsletter_history"),
    path("about/", views.about_view, name="about"),
    path("contact/", views.contact_view, name="contact"),
    path("privacy/", views.privacy_view, name="privacy"),
    path("terms/", views.terms_view, name="terms"),
    path("newsletter/subscribe/", views.newsletter_subscribe_view, name="newsletter_subscribe"),
    path("newsletter/confirm/<str:token>/", views.newsletter_confirm_view, name="newsletter_confirm"),
    path("newsletter/unsubscribe/<str:token>/", views.newsletter_unsubscribe_view, name="newsletter_unsubscribe"),
    path("library/", views.library_view, name="library"),
    path("library/<slug:subject>/", views.library_subject_view, name="library_subject"),
    path("library/<slug:subject>/<slug:area_slug>/", views.library_area_view, name="library_area"),
    path(
        "library/<slug:subject>/<slug:area_slug>/<slug:concept_slug>/",
        views.library_concept_view,
        name="library_concept",
    ),
    path(
        "library/<slug:subject>/<slug:area_slug>/<slug:concept_slug>/<slug:lecture_slug>/",
        views.library_lecture_view,
        name="library_lecture",
    ),
]
