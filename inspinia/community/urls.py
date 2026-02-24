from django.urls import path

from .views import add_comment
from .views import create_solution
from .views import report_comment
from .views import report_solution
from .views import submit_trusted_suggestion
from .views import solutions_for_problem
from .views import vote_solution

app_name = "community"

urlpatterns = [
    path("problem/<int:problem_id>/solutions/", solutions_for_problem, name="problem_solutions"),
    path("problem/<int:problem_id>/solutions/new/", create_solution, name="create_solution"),
    path("solutions/<int:solution_id>/vote/", vote_solution, name="vote_solution"),
    path("solutions/<int:solution_id>/report/", report_solution, name="report_solution"),
    path("problem/<int:problem_id>/comments/new/", add_comment, name="add_comment"),
    path("comments/<int:comment_id>/report/", report_comment, name="report_comment"),
    path("problem/<int:problem_id>/suggestions/new/", submit_trusted_suggestion, name="trusted_suggestion"),
]
