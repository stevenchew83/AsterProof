"""Bounded, editable suggestions; checking the source is a separate review."""

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet
from django.forms import formset_factory

from inspinia.rankings.imports.achievement_text import EVIDENCE_CHOICES
from inspinia.rankings.imports.achievement_text import MAX_ROWS
from inspinia.rankings.imports.achievement_text import parse_achievement_text
from inspinia.rankings.imports.achievement_text import score_value
from inspinia.rankings.models import ResultProfile


class AchievementSourceForm(forms.Form):
    source_label = forms.CharField(max_length=160, label="Source label", initial="Achievement research")
    default_evidence = forms.ChoiceField(
        label="Source provenance",
        choices=[("reported", "Supplied research / reported source"), ("family", "Family record")],
    )
    source_text = forms.CharField(
        label="Original achievement text", strip=False,
        widget=forms.Textarea(attrs={"rows": 15, "placeholder": "2025 SASMO — Gold\n2026 MCO — Bronze, 104 points"}),
    )

    def clean(self):
        cleaned = super().clean()
        if "source_text" in cleaned and "default_evidence" in cleaned:
            try:
                cleaned["parsed"] = parse_achievement_text(
                    cleaned["source_text"], default_evidence=cleaned["default_evidence"],
                )
            except ValueError as exc:
                self.add_error("source_text", str(exc))
        return cleaned


class AchievementRowForm(forms.Form):
    include = forms.BooleanField(required=False, label="Include row")
    year = forms.IntegerField(required=False, min_value=1900, max_value=2099, label="Event year")
    title = forms.CharField(required=False, max_length=255, label="Competition / event")
    outcome = forms.CharField(required=False, max_length=64, label="Award / recorded status")
    score = forms.CharField(required=False, label="Raw score")
    ranking = forms.CharField(required=False, max_length=255, label="Ranking / placing (with scope)")
    record_type = forms.ChoiceField(choices=ResultProfile.RecordType.choices, required=False, label="Record type")
    discipline = forms.ChoiceField(choices=ResultProfile.Discipline.choices, required=False)
    band = forms.CharField(required=False, max_length=32, label="Category / division")
    evidence = forms.ChoiceField(choices=EVIDENCE_CHOICES, required=False, label="Evidence status / provenance")
    existing_result = forms.ChoiceField(required=False, label="Existing record")
    notes = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, existing_choices=(), source=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = source or {}
        self.fields["existing_result"].choices = [("", "Create a new record"), *existing_choices]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("include"):
            # Excluded, incomplete suggestions remain only in the original context.
            self._errors.clear()
            return {"include": False}
        for field in ("year", "title", "record_type", "discipline", "evidence"):
            if not cleaned.get(field) and field not in self.errors:
                self.add_error(field, "Review this field before including the row.")
        if (
            self.source.get("evidence", "").startswith("family")
            and not cleaned.get("evidence", "").startswith("family")
        ):
            self.add_error(
                "evidence", "Keep family provenance; independently checked evidence uses the correction review.",
            )
        try:
            cleaned["score"] = score_value(cleaned.get("score"))
        except ValueError as exc:
            self.add_error("score", str(exc))
        if cleaned.get("record_type") == "achievement" and not (cleaned.get("outcome") or cleaned.get("ranking")):
            self.add_error(
                "outcome", "Enter an award or placing for achievements; otherwise use Score / participation.",
            )
        return cleaned


class AchievementFormSet(BaseFormSet):
    def __init__(self, *args, sources=(), existing_choices=(), **kwargs):
        self.sources, self.existing_choices = sources, existing_choices
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["existing_choices"] = self.existing_choices
        kwargs["source"] = self.sources[index] if index is not None and index < len(self.sources) else {}
        return kwargs

    def clean(self):
        super().clean()
        if self.total_form_count() < len(self.sources):
            message = "Some source suggestions are missing. Reload the review and explicitly exclude unwanted rows."
            raise ValidationError(message)


AchievementRows = formset_factory(
    AchievementRowForm, formset=AchievementFormSet, extra=0, max_num=MAX_ROWS,
    absolute_max=MAX_ROWS, validate_max=True,
)


def style_form(form):
    for field in form.fields.values():
        field.widget.attrs["class"] = (
            "form-check-input" if isinstance(field.widget, forms.CheckboxInput)
            else "form-select form-select-sm" if isinstance(field.widget, forms.Select)
            else "form-control form-control-sm"
        )
    return form
