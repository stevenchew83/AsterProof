from __future__ import annotations

from django import forms

from inspinia.rankings.models import Assessment
from inspinia.rankings.models import StudentSelectionStatus

_EXCEL_ACCEPT = ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class RankingTableFilterForm(forms.Form):
    season = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "Season"}),
    )
    division = forms.CharField(
        required=False,
        max_length=32,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Division"}),
    )
    school = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "School"}),
    )
    state = forms.CharField(
        required=False,
        max_length=64,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "State"}),
    )
    selection_status = forms.ChoiceField(
        required=False,
        choices=[("", "All statuses"), *StudentSelectionStatus.Status.choices],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    active = forms.ChoiceField(
        required=False,
        choices=[("", "All"), ("1", "Active"), ("0", "Inactive")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    q = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Search name or school"}),
    )
    formula = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput(),
    )

    def clean_division(self) -> str:
        return (self.cleaned_data.get("division") or "").strip()

    def clean_school(self) -> str:
        return (self.cleaned_data.get("school") or "").strip()

    def clean_state(self) -> str:
        return (self.cleaned_data.get("state") or "").strip()

    def clean_q(self) -> str:
        return (self.cleaned_data.get("q") or "").strip()


class StudentMasterImportForm(forms.Form):
    file = forms.FileField(
        label="Student master file",
        help_text="Upload a .csv or .xlsx file with student master columns.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": f".csv,text/csv,{_EXCEL_ACCEPT}",
            },
        ),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        name = (getattr(uploaded, "name", "") or "").lower()
        if not name.endswith((".csv", ".xlsx")):
            msg = "Please upload a .csv or .xlsx file."
            raise forms.ValidationError(msg)
        return uploaded


class AssessmentResultImportForm(forms.Form):
    file = forms.FileField(
        label="Assessment result file",
        help_text="Upload a .csv or .xlsx file with one row per student result.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": f".csv,text/csv,{_EXCEL_ACCEPT}",
            },
        ),
    )
    assessment = forms.ModelChoiceField(
        queryset=Assessment.objects.order_by("-season_year", "sort_order", "code"),
        required=False,
        empty_label="Create from fields below",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    assessment_code = forms.CharField(
        required=False,
        max_length=32,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Assessment code"}),
    )
    assessment_display_name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Assessment display name"}),
    )
    season_year = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "Season year"}),
    )
    category = forms.ChoiceField(
        required=False,
        choices=Assessment.Category.choices,
        initial=Assessment.Category.CONTEST,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    division_scope = forms.CharField(
        required=False,
        max_length=32,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Division scope"}),
    )

    student_identifier_column = forms.CharField(
        required=True,
        max_length=128,
        initial="student_identifier",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    raw_score_column = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    medal_column = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    band_column = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    status_text_column = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    remarks_column = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    source_url_column = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        name = (getattr(uploaded, "name", "") or "").lower()
        if not name.endswith((".csv", ".xlsx")):
            msg = "Please upload a .csv or .xlsx file."
            raise forms.ValidationError(msg)
        return uploaded

    def clean_assessment_code(self) -> str:
        return (self.cleaned_data.get("assessment_code") or "").strip().upper()

    def clean_assessment_display_name(self) -> str:
        return (self.cleaned_data.get("assessment_display_name") or "").strip()

    def clean_division_scope(self) -> str:
        return (self.cleaned_data.get("division_scope") or "").strip()

    def clean(self):
        cleaned = super().clean()
        existing_assessment = cleaned.get("assessment")
        assessment_code = cleaned.get("assessment_code")
        assessment_display_name = cleaned.get("assessment_display_name")
        season_year = cleaned.get("season_year")
        if existing_assessment is None and not (assessment_code and assessment_display_name and season_year):
            msg = (
                "Select an existing assessment or provide assessment code, display name, and season year "
                "to create one."
            )
            raise forms.ValidationError(msg)

        if not cleaned.get("student_identifier_column"):
            self.add_error("student_identifier_column", "Student identifier column is required.")

        mapping_columns = [
            cleaned.get("raw_score_column"),
            cleaned.get("medal_column"),
            cleaned.get("band_column"),
            cleaned.get("status_text_column"),
            cleaned.get("remarks_column"),
            cleaned.get("source_url_column"),
        ]
        if not any(mapping_columns):
            msg = "Configure at least one result column (score/medal/band/status/remarks/url)."
            raise forms.ValidationError(msg)
        return cleaned


class LegacyWideImportForm(forms.Form):
    file = forms.FileField(
        label="Legacy ranking sheet",
        help_text="Upload the existing wide .csv or .xlsx spreadsheet.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": f".csv,text/csv,{_EXCEL_ACCEPT}",
            },
        ),
    )
    season_year = forms.IntegerField(
        required=True,
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "Season year"}),
    )
    default_division = forms.CharField(
        required=False,
        max_length=32,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Division (optional)"}),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        name = (getattr(uploaded, "name", "") or "").lower()
        if not name.endswith((".csv", ".xlsx")):
            msg = "Please upload a .csv or .xlsx file."
            raise forms.ValidationError(msg)
        return uploaded

    def clean_default_division(self) -> str:
        return (self.cleaned_data.get("default_division") or "").strip()
