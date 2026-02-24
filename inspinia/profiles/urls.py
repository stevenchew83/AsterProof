from django.urls import path

from .views import edit_profile
from .views import profile_detail
from .views import report_profile

app_name = "profiles"

urlpatterns = [
    path("me/edit/", edit_profile, name="edit"),
    path("<int:user_id>/report/", report_profile, name="report"),
    path("<int:user_id>/", profile_detail, name="detail"),
]
