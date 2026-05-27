from __future__ import annotations

from django import forms
from django.forms import modelformset_factory

from inspinia.training.models import LevelThreshold
from inspinia.training.models import Material
from inspinia.training.models import Problem
from inspinia.training.models import Submission
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic


class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            current_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{current_class} {css_class}".strip()


class TopicForm(BootstrapModelForm):
    class Meta:
        model = Topic
        fields = ["title", "slug", "description", "order", "is_published"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class SubtopicForm(BootstrapModelForm):
    class Meta:
        model = Subtopic
        fields = [
            "topic",
            "title",
            "slug",
            "category",
            "level",
            "is_imo_syllabus",
            "description",
            "order",
            "is_published",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class MaterialForm(BootstrapModelForm):
    class Meta:
        model = Material
        fields = [
            "subtopic",
            "title",
            "slug",
            "content_markdown",
            "estimated_minutes",
            "completion_points",
            "order",
            "is_published",
        ]
        widgets = {
            "content_markdown": forms.Textarea(
                attrs={
                    "rows": 16,
                    "class": "font-monospace training-material-editor-input",
                    "data-preview-source": "id_content_markdown",
                    "spellcheck": "true",
                },
            ),
        }


class CheckpointProblemForm(BootstrapModelForm):
    slug = forms.SlugField(
        required=False,
        help_text="Leave blank to generate from the title.",
    )

    def __init__(self, *args, locked_subtopic: Subtopic | None = None, **kwargs):
        self.locked_subtopic = locked_subtopic
        super().__init__(*args, **kwargs)
        if locked_subtopic is not None:
            self.fields["subtopic"].initial = locked_subtopic.pk
            self.fields["subtopic"].required = False
            self.fields["subtopic"].widget = forms.HiddenInput()

    class Meta:
        model = Problem
        fields = [
            "subtopic",
            "title",
            "slug",
            "statement_markdown",
            "difficulty",
            "max_points",
            "order",
            "is_published",
        ]
        widgets = {
            "statement_markdown": forms.Textarea(
                attrs={
                    "rows": 5,
                    "class": "font-monospace",
                    "placeholder": "State the checkpoint problem. Use $...$ or $$...$$ for math.",
                },
            ),
        }

    def clean_subtopic(self) -> Subtopic:
        if self.locked_subtopic is not None:
            return self.locked_subtopic
        return self.cleaned_data["subtopic"]


class ProblemForm(BootstrapModelForm):
    tags_text = forms.CharField(
        required=False,
        help_text="Comma-separated tags; stored uppercase.",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IDENTITIES, FACTORING"}),
    )

    class Meta:
        model = Problem
        fields = [
            "subtopic",
            "title",
            "slug",
            "statement_markdown",
            "difficulty",
            "mohs_rating",
            "source",
            "tags_text",
            "expected_method",
            "max_points",
            "official_solution_markdown",
            "order",
            "is_published",
        ]
        widgets = {
            "statement_markdown": forms.Textarea(attrs={"rows": 8, "class": "font-monospace"}),
            "official_solution_markdown": forms.Textarea(attrs={"rows": 8, "class": "font-monospace"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["tags_text"].initial = ", ".join(self.instance.tags or [])

    def clean_tags_text(self) -> list[str]:
        value = self.cleaned_data.get("tags_text") or ""
        return [chunk.strip().upper() for chunk in value.split(",") if chunk.strip()]

    def save(self, commit=True):  # noqa: FBT002 - Django ModelForm.save uses this signature.
        instance = super().save(commit=False)
        instance.tags = self.cleaned_data["tags_text"]
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class SubmissionForm(BootstrapModelForm):
    class Meta:
        model = Submission
        fields = ["solution_markdown"]
        widgets = {
            "solution_markdown": forms.Textarea(
                attrs={
                    "rows": 10,
                    "class": "form-control font-monospace",
                    "placeholder": "Write your proof. Use $...$ for inline math.",
                },
            ),
        }


class ReviewForm(forms.Form):
    status = forms.ChoiceField(choices=Submission.Status.choices, widget=forms.Select(attrs={"class": "form-select"}))
    awarded_points = forms.IntegerField(
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}),
    )
    comment_body = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "rows": 4,
                "placeholder": "Leave feedback for the student.",
            },
        ),
    )

    def __init__(self, *args, problem: Problem, **kwargs):
        self.problem = problem
        super().__init__(*args, **kwargs)
        self.fields["awarded_points"].widget.attrs["max"] = problem.max_points
        self.fields["awarded_points"].help_text = f"Partial points may range from 0 to {problem.max_points}."

    def clean_awarded_points(self) -> int:
        value = self.cleaned_data.get("awarded_points")
        return int(value or 0)

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")
        awarded_points = int(cleaned_data.get("awarded_points") or 0)
        if status == Submission.Status.PARTIALLY_ACCEPTED and awarded_points > self.problem.max_points:
            self.add_error("awarded_points", f"Points cannot exceed {self.problem.max_points}.")
        return cleaned_data


LevelThresholdFormSet = modelformset_factory(
    LevelThreshold,
    fields=["level_number", "name", "minimum_points"],
    extra=0,
    widgets={
        "level_number": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 10}),
        "name": forms.TextInput(attrs={"class": "form-control"}),
        "minimum_points": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
    },
)
