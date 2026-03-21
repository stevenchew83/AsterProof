from django import forms
from django.forms import BaseInlineFormSet
from django.forms import inlineformset_factory

from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType


class ProblemSolutionForm(forms.ModelForm):
    class Meta:
        model = ProblemSolution
        fields = ["title", "summary"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Optional solution title",
                },
            ),
            "summary": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional short summary of the idea or style of this solution",
                },
            ),
        }


class ProblemSolutionBlockForm(forms.ModelForm):
    class Meta:
        model = ProblemSolutionBlock
        fields = ["block_type", "title", "body_format", "body_source"]
        widgets = {
            "block_type": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Optional visible heading like Claim 1, Therefore, or When n is even",
                },
            ),
            "body_format": forms.Select(attrs={"class": "form-select"}),
            "body_source": forms.Textarea(
                attrs={
                    "class": "form-control font-monospace",
                    "rows": 7,
                    "spellcheck": "false",
                    "placeholder": "Write the block body here. LaTeX is rendered in the preview.",
                },
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["block_type"].queryset = SolutionBlockType.objects.order_by("sort_order", "label", "id")
        self.fields["block_type"].required = False
        self.fields["title"].required = False
        self.fields["body_source"].required = True


class BaseProblemSolutionBlockFormSet(BaseInlineFormSet):
    def add_fields(self, form, index) -> None:
        super().add_fields(form, index)
        order_field = form.fields.get("ORDER")
        delete_field = form.fields.get("DELETE")
        if order_field is not None:
            order_field.widget = forms.NumberInput(
                attrs={
                    "class": "form-control solution-order-input",
                    "min": "1",
                    "step": "1",
                },
            )
            order_field.initial = (index or 0) + 1
        if delete_field is not None:
            delete_field.widget = forms.CheckboxInput(
                attrs={"class": "form-check-input d-none solution-delete-input"},
            )

    def clean(self) -> None:
        super().clean()
        non_deleted_total = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            body_source = (form.cleaned_data.get("body_source") or "").strip()
            if body_source:
                non_deleted_total += 1

        if non_deleted_total == 0:
            msg = "Add at least one solution block before saving."
            raise forms.ValidationError(msg)


ProblemSolutionBlockFormSet = inlineformset_factory(
    ProblemSolution,
    ProblemSolutionBlock,
    form=ProblemSolutionBlockForm,
    formset=BaseProblemSolutionBlockFormSet,
    extra=1,
    can_delete=True,
    can_order=True,
)
