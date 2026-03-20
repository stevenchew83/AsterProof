from django.urls import path

from .views import manage_user_roles_view
from .views import user_detail_view
from .views import user_redirect_view
from .views import user_update_view

app_name = "users"
urlpatterns = [
    path("~redirect/", view=user_redirect_view, name="redirect"),
    path("~update/", view=user_update_view, name="update"),
    path("manage-roles/", view=manage_user_roles_view, name="manage_roles"),
    path("<int:pk>/", view=user_detail_view, name="detail"),
]
