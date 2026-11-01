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
)
MIN_CONTEST_YEAR = 1900


class CommunityProblemForm(forms.ModelForm):
    sharing_confirmed = forms.BooleanField(
        label=(
            "I can share this statement and its attribution. "
            "It will be visible to signed-in users, including before review."
        ),
    )
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput, required=False)

    class Meta:
        model = CommunityProblem
        fields = CONTENT_FIELDS
        labels = {
            "statement_latex": "Problem statement (text and LaTeX)",
            "mohs": "Proposed MOHS difficulty (0-60)",
            "rationale": "Why this difficulty?",
            "source_details": "Author / source attribution",
            "solution_outline": "Solution outline (private to you and admins)",
        }
        help_texts = {
            "statement_latex": (
                "Include all assumptions, variable domains, and the exact question. Diagram code stays as source."
            ),
            "topic_tags": (
                "Separate techniques, objects, or theorems with commas; use library terminology where possible."
            ),
            "source_details": (
                "For originals, give the author and composition context; otherwise give the original source."
            ),
            "core_ideas": "Describe the main mathematical ideas without claiming a complete proof.",
            "solution_outline": "Optional supporting evidence for reviewers. It is never shown on the community list.",
        }
        widgets = {
            "statement_latex": forms.Textarea(attrs={"rows": 10, "spellcheck": "false"}),
            "core_ideas": forms.Textarea(attrs={"rows": 3}),
            "rationale": forms.Textarea(attrs={"rows": 3}),
            "pitfalls": forms.Textarea(attrs={"rows": 2}),
            "solution_outline": forms.Textarea(attrs={"rows": 5}),
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
        }
        for name, limit in limits.items():
            self.fields[name].max_length = limit
            self.fields[name].validators.append(MaxLengthValidator(limit))
            self.fields[name].widget.attrs["maxlength"] = limit
        if self.instance.pk:
            self.fields["version"].initial = self.instance.version

    def clean(self):
        data = super().clean()
        for name in ("statement_latex", "core_ideas", "rationale"):
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
