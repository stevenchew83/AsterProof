from django.urls import path

from .views import favourites_page
from .views import toggle_favourite
from .views import update_problem_status

app_name = "progress"

urlpatterns = [
    path("favourites/", favourites_page, name="favourites"),
    path("problem/<int:problem_id>/status/", update_problem_status, name="update_status"),
    path("problem/<int:problem_id>/favourite/", toggle_favourite, name="toggle_favourite"),
]
