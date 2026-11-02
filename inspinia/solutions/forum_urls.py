from django.urls import path

from . import forum_views as views

urlpatterns = [
    path("entries/<int:solution_pk>/", views.solution_detail, name="solution_detail"),
    path("entries/<int:solution_pk>/actions/<str:action>/", views.forum_action, name="forum_action"),
    path("entries/<int:solution_pk>/history/", views.forum_history, name="forum_history"),
    path(
        "entries/<int:solution_pk>/comments/<int:comment_pk>/",
        views.forum_comment_replies,
        name="forum_comment_replies",
    ),
    path("review-queue/", views.forum_review_queue, name="forum_review_queue"),
    path("admin/forum/", views.forum_admin_queue, name="forum_admin_queue"),
]
