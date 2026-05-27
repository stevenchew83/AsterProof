from django.urls import path

from inspinia.training.views import admin_levels_view
from inspinia.training.views import admin_users_view
from inspinia.training.views import dashboard_view
from inspinia.training.views import material_detail_view
from inspinia.training.views import my_submissions_view
from inspinia.training.views import problem_detail_view
from inspinia.training.views import roadmap_view
from inspinia.training.views import submission_detail_view
from inspinia.training.views import subtopic_detail_view
from inspinia.training.views import topic_detail_view
from inspinia.training.views import trainer_dashboard_view
from inspinia.training.views import trainer_material_preview_view
from inspinia.training.views import trainer_materials_view
from inspinia.training.views import trainer_problems_view
from inspinia.training.views import trainer_submissions_view
from inspinia.training.views import trainer_topics_view

app_name = "training"

urlpatterns = [
    path("dashboard/", dashboard_view, name="dashboard"),
    path("training/", roadmap_view, name="roadmap"),
    path("submissions/", my_submissions_view, name="my_submissions"),
    path("training/<slug:topic_slug>/", topic_detail_view, name="topic_detail"),
    path("training/<slug:topic_slug>/<slug:subtopic_slug>/", subtopic_detail_view, name="subtopic_detail"),
    path("materials/<slug:material_slug>/", material_detail_view, name="material_detail"),
    path("problems/<slug:problem_slug>/", problem_detail_view, name="problem_detail"),
    path("submissions/<int:submission_id>/", submission_detail_view, name="submission_detail"),
    path("trainer/", trainer_dashboard_view, name="trainer_dashboard"),
    path("trainer/topics/", trainer_topics_view, name="trainer_topics"),
    path("trainer/materials/", trainer_materials_view, name="trainer_materials"),
    path("trainer/materials/preview/", trainer_material_preview_view, name="trainer_material_preview"),
    path("trainer/problems/", trainer_problems_view, name="trainer_problems"),
    path("trainer/submissions/", trainer_submissions_view, name="trainer_submissions"),
    path("trainer/submissions/<int:submission_id>/", submission_detail_view, name="trainer_submission_detail"),
    path("admin/users/", admin_users_view, name="admin_users"),
    path("admin/levels/", admin_levels_view, name="admin_levels"),
]
