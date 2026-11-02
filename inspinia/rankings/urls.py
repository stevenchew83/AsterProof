from django.urls import path

from inspinia.rankings.analysis_views import ranking_analysis_export_view
from inspinia.rankings.analysis_views import ranking_analysis_view
from inspinia.rankings.correction_views import correction_detail
from inspinia.rankings.correction_views import correction_history
from inspinia.rankings.correction_views import correction_new
from inspinia.rankings.correction_views import correction_queue
from inspinia.rankings.correction_views import import_conflict_action
from inspinia.rankings.result_views import assessment_results_view
from inspinia.rankings.result_views import olympiad_sheet_import_view
from inspinia.rankings.result_views import result_history_view
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
    path("analysis/corrections/", correction_queue, name="correction_queue"),
    path("analysis/corrections/new/", correction_new, name="correction_new"),
    path("analysis/corrections/history/", correction_history, name="correction_history"),
    path("analysis/corrections/<int:pk>/", correction_detail, name="correction_detail"),
    path("analysis/import-conflicts/<int:pk>/", import_conflict_action, name="import_conflict_action"),
    path("analysis/", ranking_analysis_view, name="analysis"),
    path("analysis/export/", ranking_analysis_export_view, name="analysis_export"),
    path("", ranking_table_view, name="ranking_table"),
    path("results/", assessment_results_view, name="assessment_results"),
    path("history/", result_history_view, name="result_history"),
    path("imports/olympiad/", olympiad_sheet_import_view, name="olympiad_sheet_import"),
    path("export/csv/", ranking_export_csv_view, name="ranking_export_csv"),
    path("export/xlsx/", ranking_export_xlsx_view, name="ranking_export_xlsx"),
    path("dashboard/", ranking_dashboard_view, name="dashboard"),
    path("students/", students_list_view, name="students_list"),
    path("students/<int:student_id>/", student_detail_view, name="student_detail"),
    path("assessments/", assessments_list_view, name="assessments_list"),
    path("formulas/", formulas_list_view, name="formulas_list"),
    path("imports/", import_center_view, name="import_center"),
]
