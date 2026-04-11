from django.urls import path

from inspinia.rankings.views import assessments_list_view
from inspinia.rankings.views import formulas_list_view
from inspinia.rankings.views import import_center_view
from inspinia.rankings.views import ranking_dashboard_view
from inspinia.rankings.views import ranking_export_csv_view
from inspinia.rankings.views import ranking_export_xlsx_view
from inspinia.rankings.views import ranking_table_view
from inspinia.rankings.views import student_detail_view
from inspinia.rankings.views import students_list_view

app_name = "rankings"

urlpatterns = [
    path("", ranking_table_view, name="ranking_table"),
    path("export/csv/", ranking_export_csv_view, name="ranking_export_csv"),
    path("export/xlsx/", ranking_export_xlsx_view, name="ranking_export_xlsx"),
    path("dashboard/", ranking_dashboard_view, name="dashboard"),
    path("students/", students_list_view, name="students_list"),
    path("students/<int:student_id>/", student_detail_view, name="student_detail"),
    path("assessments/", assessments_list_view, name="assessments_list"),
    path("formulas/", formulas_list_view, name="formulas_list"),
    path("imports/", import_center_view, name="import_center"),
]
