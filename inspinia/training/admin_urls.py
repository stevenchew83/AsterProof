from django.urls import path

from inspinia.training.views import admin_levels_view
from inspinia.training.views import admin_users_view

app_name = "training_admin"

urlpatterns = [
    path("users/", admin_users_view, name="users"),
    path("levels/", admin_levels_view, name="levels"),
]
