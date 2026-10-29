from django.urls import path

from . import views

app_name = "website"

urlpatterns = [
    path("problem-solving/", views.problem_solving_view, name="problem_solving"),
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
