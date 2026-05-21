from django.urls import path

from inspinia.training.views import archive_view
from inspinia.training.views import create_view
from inspinia.training.views import index_view
from inspinia.training.views import manage_view
from inspinia.training.views import material_detail_view
from inspinia.training.views import publish_view
from inspinia.training.views import save_problems_view
from inspinia.training.views import subtopic_create_view
from inspinia.training.views import subtopic_detail_view
from inspinia.training.views import subtopic_manage_view
from inspinia.training.views import subtopic_toggle_view
from inspinia.training.views import subtopic_update_view
from inspinia.training.views import topic_detail_view
from inspinia.training.views import update_view

app_name = "training"

urlpatterns = [
    path("", index_view, name="index"),
    path("topics/<slug:topic_slug>/", topic_detail_view, name="topic_detail"),
    path("topics/<slug:topic_slug>/<slug:subtopic_slug>/", subtopic_detail_view, name="subtopic_detail"),
    path("materials/<uuid:material_uuid>/<slug:slug>/", material_detail_view, name="material_detail"),
    path("manage/", manage_view, name="manage"),
    path("manage/new/", create_view, name="create"),
    path("manage/<uuid:material_uuid>/", update_view, name="update"),
    path("manage/<uuid:material_uuid>/problems/", save_problems_view, name="save_problems"),
    path("manage/<uuid:material_uuid>/publish/", publish_view, name="publish"),
    path("manage/<uuid:material_uuid>/archive/", archive_view, name="archive"),
    path("manage/subtopics/", subtopic_manage_view, name="subtopic_manage"),
    path("manage/subtopics/new/", subtopic_create_view, name="subtopic_create"),
    path("manage/subtopics/<uuid:subtopic_uuid>/", subtopic_update_view, name="subtopic_update"),
    path("manage/subtopics/<uuid:subtopic_uuid>/toggle/", subtopic_toggle_view, name="subtopic_toggle"),
]

