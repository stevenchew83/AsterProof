from django.urls import path

from .views import leaderboard
from .views import personal_dashboard
from .views import trending

app_name = "analytics"

urlpatterns = [
    path("dashboard/", personal_dashboard, name="dashboard"),
    path("trending/", trending, name="trending"),
    path("leaderboard/", leaderboard, name="leaderboard"),
]
