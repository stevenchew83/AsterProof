"""Library-compatible metadata without inventing contest identities for originals."""

from django import forms
from django.core.validators import MaxLengthValidator
from django.utils import timezone

from .community_models import CommunityProblem

CONTENT_FIELDS = (
    "title",
    "statement_latex",
    "topic",
    "mohs",
    "topic_tags",
    "core_ideas",
    "rationale",
    "pitfalls",
    "source_kind",
    "source_details",
    "source_url",
    "contest_name",
    "contest_year",
    "problem_code",
    "solution_outline",
    "solution_known",
    "embargo_until",
    "public_hint",
)
MIN_CONTEST_YEAR = 1900


class CommunityProblemForm(forms.ModelForm):
    sharing_confirmed = forms.BooleanField(
        label=(
            "I can submit this statement and attribution for publication review. "
            "It stays private until I explicitly share an approved version."
        ),
    )
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput, required=False)

    class Meta:
        model = CommunityProblem
        fields = CONTENT_FIELDS
        labels = {
            "statement_latex": "Problem statement",
            "topic": "Subject",
            "mohs": "Proposed MOHS (0-60)",
            "rationale": "Why this difficulty?",
            "source_kind": "Problem origin",
            "source_details": "Author or source",
            "source_url": "Source link",
            "solution_outline": "Solution outline",
            "solution_known": "I know a solution or an approach",
            "embargo_until": "Competition embargo ends (optional)",
            "public_hint": "Optional hint to publish",
        }
        help_texts = {
            "statement_latex": (
                "Use plain text and LaTeX. Include assumptions, variable domains, and the exact question."
            ),
            "topic_tags": (
                "Separate techniques, objects, or theorems with commas."
            ),
            "source_details": (
                "Credit the original author and source, or describe when you created the problem."
            ),
            "core_ideas": "The main observation or approach; a full proof is optional.",
            "solution_outline": "Optional supporting evidence for reviewers. It is never shown on the community list.",
            "mohs": "Leave blank if the difficulty is unknown. Zero is a difficulty value, not unknown.",
            "public_hint": (
                "Only this hint can appear publicly after you preview and share it. "
                "Your private outline stays private."
            ),
            "embargo_until": (
                "Disclose any competition embargo. Sharing stays blocked until it ends and publication is approved."
            ),
        }
        widgets = {
            "statement_latex": forms.Textarea(attrs={"rows": 6, "spellcheck": "false"}),
            "core_ideas": forms.Textarea(attrs={"rows": 2}),
            "rationale": forms.Textarea(attrs={"rows": 2}),
            "pitfalls": forms.Textarea(attrs={"rows": 2}),
            "solution_outline": forms.Textarea(attrs={"rows": 4}),
            "public_hint": forms.Textarea(attrs={"rows": 3}),
            "embargo_until": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-check-input"
                if isinstance(field.widget, forms.CheckboxInput)
                else ("form-select" if isinstance(field.widget, forms.Select) else "form-control")
            )
        limits = {
            "statement_latex": 12000,
            "core_ideas": 2000,
            "rationale": 2000,
            "pitfalls": 2000,
            "solution_outline": 6000,
            "public_hint": 2000,
        }
        for name, limit in limits.items():
            self.fields[name].max_length = limit
            self.fields[name].validators.append(MaxLengthValidator(limit))
            self.fields[name].widget.attrs["maxlength"] = limit
        placeholders = {
            "title": "A short, descriptive title",
            "statement_latex": "Define the setting, then state what to prove or find…",
            "mohs": "0-60",
            "topic_tags": "e.g. AM-GM, SYMMETRY",
            "core_ideas": "What makes the problem work?",
            "rationale": "What is the main obstacle for the solver?",
            "source_details": "Author, publication, or composition context",
            "source_url": "https://…",
            "contest_name": "Contest name",
            "problem_code": "e.g. A1",
            "pitfalls": "Common traps or easily missed cases",
            "solution_outline": "A sketch or supporting argument for the reviewers",
        }
        for name, placeholder in placeholders.items():
            self.fields[name].widget.attrs["placeholder"] = placeholder
        for name in ("mohs", "topic_tags", "core_ideas", "rationale", "solution_known"):
            self.fields[name].required = False
        for name, prompt in (("topic", "Choose a subject"), ("source_kind", "Choose an origin")):
            self.fields[name].choices = [
                (value, label if value else prompt) for value, label in self.fields[name].choices
            ]
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            field_id = self[name].id_for_label
            descriptions = [f"{field_id}_errors"]
            if field.help_text:
                descriptions.insert(0, f"{field_id}_helptext")
            field.widget.attrs["aria-describedby"] = " ".join(descriptions)
        if self.instance.pk:
            self.fields["version"].initial = self.instance.version

    def clean(self):
        data = super().clean()
        for name in ("statement_latex",):
            if name in data and not data[name].strip():
                self.add_error(name, "This field is required.")
        if (
            data.get("contest_year") is not None
            and not MIN_CONTEST_YEAR <= data["contest_year"] <= timezone.localdate().year + 1
        ):
            self.add_error("contest_year", "Use a year between 1900 and next year.")
        contest_fields = ("contest_name", "contest_year", "problem_code")
        if any(data.get(name) for name in contest_fields) and not all(data.get(name) for name in contest_fields):
            self.add_error(
                "contest_name",
                "For a contest problem, supply the contest name, year, and problem code together.",
            )
        if data.get("problem_code"):
            data["problem_code"] = data["problem_code"].strip().upper()
        if data.get("topic_tags"):
            data["topic_tags"] = ", ".join(
                dict.fromkeys(part.strip().upper() for part in data["topic_tags"].split(",") if part.strip()),
            )
            if not data["topic_tags"]:
                self.add_error("topic_tags", "Enter at least one tag.")
        return data


class CommunityReviewForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    decision = forms.ChoiceField(
        choices=[
            (CommunityProblem.Status.APPROVED, "Approve"),
            (CommunityProblem.Status.CHANGES_REQUESTED, "Request changes"),
            (CommunityProblem.Status.DECLINED, "Decline"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    notes = forms.CharField(
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        help_text="Visible to the author and other signed-in users.",
    )

    def clean(self):
        data = super().clean()
        if data.get("decision") != CommunityProblem.Status.APPROVED and not data.get("notes"):
            self.add_error("notes", "Explain the requested changes or reason for declining.")
        return data
