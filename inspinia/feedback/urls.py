from django.urls import path

from .views import create_feedback
from .views import create_problem_submission
from .views import feedback_board
from .views import my_feedback

app_name = "feedback"

urlpatterns = [
    path("", feedback_board, name="board"),
    path("mine/", my_feedback, name="mine"),
    path("new/", create_feedback, name="create"),
    path("submission/new/", create_problem_submission, name="create_problem_submission"),
]
