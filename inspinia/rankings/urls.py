from django.urls import path

from inspinia.rankings.views import ranking_table_view

app_name = "rankings"

urlpatterns = [
    path("", ranking_table_view, name="ranking_table"),
]

