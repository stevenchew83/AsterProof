from __future__ import annotations

from django import forms

from inspinia.training.models import TrainingMaterial
from inspinia.training.models import TrainingSubtopic
from inspinia.training.models import TrainingTopic


class TrainingMaterialForm(forms.ModelForm):
    subtopics = forms.ModelMultipleChoiceField(
        queryset=TrainingSubtopic.objects.none(),
        required=False,
        to_field_name="subtopic_uuid",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 10}),
    )

    class Meta:
        model = TrainingMaterial
        fields = ("title", "summary", "body_source", "estimated_minutes", "subtopics")
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Inversion: first transformations",
                },
            ),
            "summary": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "What should students understand after this module?",
                },
            ),
            "body_source": forms.Textarea(
                attrs={
                    "class": "form-control font-monospace",
                    "rows": 16,
                    "placeholder": "## Lesson\n\nUse Markdown and TeX math like $a^2+b^2 \\ge 2ab$.",
                },
            ),
            "estimated_minutes": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 0,
                    "placeholder": "30",
                },
            ),
        }
        labels = {
            "body_source": "Lesson body",
            "estimated_minutes": "Estimated minutes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subtopic_queryset = TrainingSubtopic.objects.filter(
            is_active=True,
            topic__is_active=True,
        ).select_related("topic")
        self.fields["subtopics"].queryset = subtopic_queryset
        self.fields["subtopics"].choices = self._grouped_subtopic_choices(subtopic_queryset)
        if self.instance.pk and not self.is_bound:
            self.fields["subtopics"].initial = list(self.instance.subtopics.values_list("subtopic_uuid", flat=True))

    def clean_title(self) -> str:
        title = (self.cleaned_data["title"] or "").strip()
        if not title:
            msg = "Title is required."
            raise forms.ValidationError(msg)
        return title

    def clean_summary(self) -> str:
        return (self.cleaned_data["summary"] or "").strip()

    def clean_body_source(self) -> str:
        return (self.cleaned_data["body_source"] or "").strip()

    @staticmethod
    def _grouped_subtopic_choices(queryset) -> list[tuple[str, list[tuple[object, str]]]]:
        groups: list[tuple[str, list[tuple[object, str]]]] = []
        current_topic_id = None
        current_label = ""
        current_choices: list[tuple[object, str]] = []
        for subtopic in queryset.order_by("topic__sort_order", "topic__title", "sort_order", "title"):
            if current_topic_id != subtopic.topic_id:
                if current_choices:
                    groups.append((current_label, current_choices))
                current_topic_id = subtopic.topic_id
                current_label = subtopic.topic.title
                current_choices = []
            current_choices.append((subtopic.subtopic_uuid, subtopic.title))
        if current_choices:
            groups.append((current_label, current_choices))
        return groups


class TrainingSubtopicForm(forms.ModelForm):
    class Meta:
        model = TrainingSubtopic
        fields = ("topic", "title", "description", "is_active")
        widgets = {
            "topic": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Spiral similarity",
                },
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional curator notes for this subtopic.",
                },
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = TrainingTopic.objects.filter(is_active=True).order_by("sort_order", "title")

    def clean_title(self) -> str:
        title = (self.cleaned_data["title"] or "").strip()
        if not title:
            msg = "Subtopic title is required."
            raise forms.ValidationError(msg)
        return title

    def clean_description(self) -> str:
        return (self.cleaned_data["description"] or "").strip()
