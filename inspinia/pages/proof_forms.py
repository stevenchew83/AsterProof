"""Forms for explicit community publication and owner-only private work."""

from django import forms

from .proof_library import MAX_BODY
from .proof_models import CommunityContentReport
from .proof_models import ProblemPublication


class ProofForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            field.widget.attrs.setdefault(
                "class",
                "form-check-input"
                if isinstance(field.widget, forms.CheckboxInput)
                else "form-select"
                if isinstance(field.widget, forms.Select)
                else "form-control",
            )


class PublicationForm(ProofForm):
    visibility = forms.ChoiceField(choices=ProblemPublication.Visibility.choices)
    public_credit = forms.CharField(max_length=128, required=False, label="Public display name")
    consent = forms.BooleanField(
        required=False,
        label="I have permission to share this statement and attribution with anyone who can access this page.",
    )
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput, initial=0)
    statement_revision = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def clean_public_credit(self):
        credit = self.cleaned_data["public_credit"].strip()
        if "@" in credit:
            msg = "Use a display name rather than an email address."
            raise forms.ValidationError(msg)
        return credit or "Community contributor"


class AttemptForm(ProofForm):
    title = forms.CharField(max_length=160, required=False)
    body_source = forms.CharField(
        required=False,
        max_length=MAX_BODY,
        strip=False,
        label="Your private attempt",
        widget=forms.Textarea(attrs={"rows": 18, "spellcheck": "false", "data-solution-source": ""}),
    )
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput, initial=0)
    statement_revision = forms.UUIDField(widget=forms.HiddenInput)


class SolutionPublicationForm(ProofForm):
    title = forms.CharField(max_length=160, initial="My solution")
    summary = forms.CharField(max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    public_credit = forms.CharField(max_length=128, required=False, label="Public display name")
    consent = forms.BooleanField(
        required=False,
        label="I have permission to publish this selected proof and its selected images.",
    )
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    solution_id = forms.UUIDField(required=False, widget=forms.HiddenInput)

    clean_public_credit = PublicationForm.clean_public_credit


class PublicationReviewForm(ProofForm):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    decision = forms.ChoiceField(
        choices=[
            ("approved", "Approve publication"),
            ("changes_requested", "Request changes"),
            ("declined", "Decline"),
        ],
    )
    notes = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    check_content = forms.BooleanField(required=False, label="I checked completeness and safe publication content.")
    check_rights = forms.BooleanField(
        required=False, label="I checked attribution, source, and permission to publish.",
    )
    check_embargo = forms.BooleanField(required=False, label="I checked any disclosed competition embargo.")

    def clean(self):
        data = super().clean()
        if data.get("decision") == "approved":
            for name in ("check_content", "check_rights", "check_embargo"):
                if not data.get(name):
                    self.add_error(name, "Complete this publication check before approving.")
        elif not data.get("notes"):
            self.add_error("notes", "Explain the changes requested or reason for declining.")
        return data


class ContentReportForm(ProofForm):
    reason = forms.ChoiceField(choices=CommunityContentReport.Reason.choices)
    details = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 5}))
