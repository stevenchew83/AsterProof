from django.urls import path

from inspinia.problemsets.views import add_item_view
from inspinia.problemsets.views import create_view
from inspinia.problemsets.views import detail_view
from inspinia.problemsets.views import discover_view
from inspinia.problemsets.views import edit_view
from inspinia.problemsets.views import my_lists_view
from inspinia.problemsets.views import problem_search_view
from inspinia.problemsets.views import public_detail_view
from inspinia.problemsets.views import remove_item_view
from inspinia.problemsets.views import reorder_items_view
from inspinia.problemsets.views import save_items_view
from inspinia.problemsets.views import toggle_visibility_view
from inspinia.problemsets.views import vote_view

app_name = "problemsets"

urlpatterns = [
    path("", my_lists_view, name="my_lists"),
    path("discover/", discover_view, name="discover"),
    path("new/", create_view, name="create"),
    path("<uuid:list_uuid>/", detail_view, name="detail"),
    path("<uuid:list_uuid>/edit/", edit_view, name="edit"),
    path("<uuid:list_uuid>/problem-search/", problem_search_view, name="problem_search"),
    path("<uuid:list_uuid>/add/", add_item_view, name="add_item"),
    path("<uuid:list_uuid>/items/save/", save_items_view, name="save_items"),
    path("<uuid:list_uuid>/items/<int:item_id>/remove/", remove_item_view, name="remove_item"),
    path("<uuid:list_uuid>/reorder/", reorder_items_view, name="reorder_items"),
    path("<uuid:list_uuid>/visibility/", toggle_visibility_view, name="toggle_visibility"),
    path("<uuid:list_uuid>/vote/", vote_view, name="vote"),
    path("share/<uuid:share_token>/<slug:slug>/", public_detail_view, name="public_detail"),
]
