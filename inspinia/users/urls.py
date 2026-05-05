from django.urls import path

from .views import approval_pending_view
from .views import event_log_view
from .views import manage_user_roles_view
from .views import public_profile_update_view
from .views import public_profile_view
from .views import session_monitor_view
from .views import user_detail_view
from .views import user_redirect_view
from .views import user_update_view

app_name = "users"
urlpatterns = [
    path("approval-pending/", view=approval_pending_view, name="approval_pending"),
    path("~redirect/", view=user_redirect_view, name="redirect"),
    path("~update/", view=user_update_view, name="update"),
    path("profile/", view=public_profile_view, name="profile"),
    path("profile/edit/", view=public_profile_update_view, name="profile_edit"),
    path("manage-roles/", view=manage_user_roles_view, name="manage_roles"),
    path("monitor/events/", view=event_log_view, name="event_log"),
    path("monitor/sessions/", view=session_monitor_view, name="session_monitor"),
    path("<int:pk>/", view=user_detail_view, name="detail"),
]
