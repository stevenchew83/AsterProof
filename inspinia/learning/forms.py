"""Bounded authoring forms; publication authority is enforced by services."""

import json

from django import forms

from inspinia.learning.models import ContentDocument
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept

METADATA_LIMIT = 16_000


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            field.widget.attrs["class"] = css


class NewDocumentForm(StyledForm):
    kind = forms.ChoiceField(choices=ContentDocument.Kind.choices, initial="lecture")
    area = forms.ModelChoiceField(queryset=CatalogueArea.objects.select_related("subject"), required=False)
    concept = forms.ModelChoiceField(
        queryset=CatalogueConcept.objects.filter(redirect__isnull=True),
        required=False,
    )
    title = forms.CharField(max_length=180)
    use_template = forms.BooleanField(required=False, initial=True, label="Start with teaching prompts")

    def clean(self):
        data = super().clean()
        if data.get("kind") == "overview" and not data.get("area"):
            self.add_error("area", "Choose the area for this overview.")
        if data.get("kind") == "concept" and not data.get("concept"):
            self.add_error("concept", "Choose the concept for this explanation.")
        return data


class DocumentEditForm(StyledForm):
    title = forms.CharField(max_length=180)
    summary = forms.CharField(max_length=320, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    body_source = forms.CharField(
        required=False, max_length=64_000, widget=forms.Textarea(attrs={"rows": 24, "spellcheck": "true"}),
    )
    metadata = forms.JSONField(required=False, widget=forms.HiddenInput())
    edit_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput())
    editor_context = forms.CharField(max_length=4000, widget=forms.HiddenInput())
    operation_id = forms.UUIDField(required=False, widget=forms.HiddenInput())
    rights_confirmed = forms.BooleanField(
        required=False, label="I have permission to submit this writing and its assets",
    )
    source_permissions = forms.CharField(
        max_length=4000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Sources, attribution and permission details",
    )
    editorial_changes_allowed = forms.BooleanField(required=False)
    public_credit = forms.CharField(max_length=180, required=False, label="Public credit (optional)")

    def clean_metadata(self):
        value = self.cleaned_data.get("metadata") or {}
        if not isinstance(value, dict) or len(json.dumps(value)) > METADATA_LIMIT:
            message = "Keep the document details within the editor limit."
            raise forms.ValidationError(message)
        allowed = {
            "concepts",
            "assets",
            "audience",
            "level",
            "objectives",
            "attribution",
            "source_url",
            "estimated_minutes",
        }
        return {key: item for key, item in value.items() if key in allowed}


class IssueForm(StyledForm):
    description = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 5}))
    token = forms.CharField(max_length=4000, widget=forms.HiddenInput())
    website = forms.CharField(required=False, max_length=200, widget=forms.HiddenInput())

    def clean_website(self):
        if self.cleaned_data.get("website"):
            message = "The report could not be submitted."
            raise forms.ValidationError(message)
        return ""


class PathwayForm(StyledForm):
    slug = forms.SlugField(max_length=100)
    title = forms.CharField(max_length=180)
    summary = forms.CharField(max_length=320, required=False)
    audience = forms.CharField(max_length=320, required=False)
    readiness = forms.JSONField(required=False, initial=list)
    items = forms.JSONField(widget=forms.Textarea(attrs={"rows": 16}))
    subject_id = forms.CharField(max_length=40, required=False, label="Canonical subject ID (optional)")
    area_id = forms.CharField(max_length=180, required=False, label="Canonical area ID (optional)")
    is_foundations = forms.BooleanField(required=False, label="Foundations cross-topic pathway")
    expected_version = forms.IntegerField(min_value=0, initial=0, label="Current pathway version (0 for new)")
    public = forms.BooleanField(required=False, label="Also release the pathway publicly")
