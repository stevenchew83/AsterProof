"""Validated, bookmarkable filters for the ranking analysis workspace."""

from django import forms
from django.utils import timezone

TABS = [
    ("overview", "Overview"),
    ("students", "Students"),
    ("schools", "Schools"),
    ("compare", "Compare"),
    ("quality", "Data quality"),
]
ISSUES = [
    ("", "All issues"),
    ("birth", "Missing birth year"),
    ("current_school", "Missing current school"),
    ("attribution", "School at assessment unverified"),
    ("scale", "Score maximum unverified"),
    ("date", "Assessment date unverified"),
    ("definition", "Assessment definition unverified"),
    ("duplicate", "Same-name identity reviews"),
    ("aliases", "Labels / school names to review"),
    ("range", "Score outside verified range"),
]


class RankingAnalysisFilterForm(forms.Form):
    tab = forms.ChoiceField(choices=TABS)
    season = forms.ChoiceField(required=False)
    assessment = forms.ChoiceField(required=False)
    band = forms.ChoiceField(required=False, label="Category")
    band_missing = forms.BooleanField(required=False, label="Only category not recorded")
    compare_band_missing = forms.BooleanField(required=False, label="Only comparison category not recorded")
    school_basis = forms.ChoiceField(
        choices=[("assessment", "School at assessment · verified"), ("current", "Current recorded school")],
        label="School basis",
    )
    school_id = forms.ChoiceField(required=False, label="School")
    q = forms.CharField(max_length=255, required=False, label="Student name")
    birth_year = forms.IntegerField(min_value=1900, required=False)
    student = forms.IntegerField(min_value=1, max_value=2**63 - 1, required=False)
    compare_assessment = forms.ChoiceField(required=False, label="Compare with")
    compare_band = forms.ChoiceField(required=False, label="Comparison category")
    compare_mode = forms.ChoiceField(
        required=False,
        choices=[("percentile", "Cohort percentile"), ("raw", "Raw score"), ("percentage", "Verified percentage")],
    )
    issue = forms.ChoiceField(choices=ISSUES, required=False)
    order = forms.CharField(required=False, max_length=32)
    page = forms.IntegerField(required=False, min_value=1)
    score_min = forms.DecimalField(required=False, max_digits=12, decimal_places=4)
    score_max = forms.DecimalField(required=False, max_digits=12, decimal_places=4)
    score_end = forms.ChoiceField(required=False, choices=[("", ""), ("inclusive", "Inclusive")])
    outcome_field = forms.ChoiceField(
        required=False, choices=[("", ""), ("medal", "Medal"), ("band", "Category"), ("status_text", "Status")],
    )
    outcome_value = forms.CharField(max_length=64, required=False)

    def __init__(self, *args, assessments, schools, bands, compare_bands, **kwargs):
        super().__init__(*args, **kwargs)
        years = sorted({row.season_year for row in assessments}, reverse=True)
        self.fields["season"].choices = [("", "All seasons"), *[(str(year), str(year)) for year in years]]
        options = [(str(row.pk), f"{row.display_name} · {row.result_count} records") for row in assessments]
        self.fields["assessment"].choices = [("", "All assessments in season"), *options]
        self.fields["compare_assessment"].choices = [("", "Select an assessment"), *options]
        self.fields["band"].choices = [
            ("", "All categories"),
            *[(value, value or "Category not recorded") for value in bands if value],
        ]
        self.fields["compare_band"].choices = [
            ("", "All categories"),
            *[(value, value) for value in compare_bands if value],
        ]
        self.fields["school_id"].choices = [
            ("", "All schools"),
            ("unknown", "Unknown / unverified"),
            *[(str(row["id"]), row["name"]) for row in schools],
        ]
        self.fields["birth_year"].max_value = timezone.now().year
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
                continue
            field.widget.attrs["class"] = (
                "form-select form-select-sm"
                if isinstance(field.widget, forms.Select)
                else "form-control form-control-sm"
            )
        self.fields["q"].widget.attrs["placeholder"] = "Search all matching students"

    def clean(self):
        data = super().clean()
        if (
            data.get("score_min") is not None
            and data.get("score_max") is not None
            and data["score_min"] > data["score_max"]
        ):
            message = "The lower score bound must not exceed the upper bound."
            raise forms.ValidationError(message)
        if data.get("outcome_value") and not data.get("outcome_field"):
            message = "Choose an outcome field for the outcome filter."
            raise forms.ValidationError(message)
        if data.get("band_missing") and data.get("band"):
            self.add_error("band", "Choose a category or Category not recorded, not both.")
        if data.get("compare_band_missing") and data.get("compare_band"):
            self.add_error("compare_band", "Choose a comparison category or Category not recorded, not both.")
        if data.get("birth_year") and data["birth_year"] > timezone.now().year:
            self.add_error("birth_year", "Birth year cannot be in the future.")
        return data
