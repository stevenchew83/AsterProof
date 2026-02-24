from django.urls import path

from .views import autosave_note
from .views import note_editor

app_name = "notes"

urlpatterns = [
    path("problem/<int:problem_id>/", note_editor, name="editor"),
    path("problem/<int:problem_id>/autosave/", autosave_note, name="autosave"),
]
