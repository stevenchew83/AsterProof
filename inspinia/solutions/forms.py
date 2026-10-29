from django import forms
from django.forms import BaseInlineFormSet
from django.forms import inlineformset_factory

from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType

PREVIEW_BLOCK_LIMIT = 32
PREVIEW_BODY_LIMIT = 12_000
PREVIEW_TOTAL_LIMIT = 64_000


PDF_DISPLAY_FIELDS = ("pdf_show_author", "pdf_show_date", "pdf_show_footer")


def _pdf_display_option(label, part):
    return forms.BooleanField(
        label=label, required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input m-0", f"data-pdf-show-{part}": ""}),
    )


class PdfDisplayOptionsMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Older clients and inline draft forms do not submit these controls.
        if self.is_bound and self.add_prefix("pdf_options_present") not in self.data:
            self.data = self.data.copy()
            for name in PDF_DISPLAY_FIELDS:
                self.data[self.add_prefix(name)] = self.initial.get(name, self.fields[name].initial)


class ProblemSolutionForm(PdfDisplayOptionsMixin, forms.ModelForm):
    pdf_options_present = forms.CharField(required=False, initial="1", widget=forms.HiddenInput)
    pdf_show_author = _pdf_display_option("Show author", "author")
    pdf_show_date = _pdf_display_option("Show date", "date")
    pdf_show_footer = _pdf_display_option("Show footer (page numbers)", "footer")

    class Meta:
        model = ProblemSolution
        fields = ["title", "summary", *PDF_DISPLAY_FIELDS]
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
        self.fields["block_type"].required = False
        self.fields["title"].required = False
        self.fields["body_source"].required = True


class BaseProblemSolutionBlockFormSet(BaseInlineFormSet):
    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        if not hasattr(self, "_shared_block_type_queryset"):
            self._shared_block_type_queryset = SolutionBlockType.objects.order_by(
                "sort_order",
                "label",
                "id",
            )
        form.fields["block_type"].queryset = self._shared_block_type_queryset
        return form

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


class SolutionPreviewForm(PdfDisplayOptionsMixin, forms.Form):
    pdf_options_present = forms.CharField(required=False, initial="1", widget=forms.HiddenInput)
    pdf_show_author = _pdf_display_option("Show author", "author")
    pdf_show_date = _pdf_display_option("Show date", "date")
    pdf_show_footer = _pdf_display_option("Show footer (page numbers)", "footer")
    author_name = forms.CharField(
        max_length=100, required=False, label="Author name (optional)",
        widget=forms.TextInput(attrs={"class": "form-control", "data-pdf-author-input": ""}),
    )
    title = forms.CharField(
        max_length=160, required=False, label="Document title",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "My solution"}),
    )
    problem_statement = forms.CharField(
        max_length=PREVIEW_BODY_LIMIT, required=False, label="Problem statement (optional)",
        widget=forms.Textarea(attrs={"class": "form-control font-monospace", "rows": 4, "spellcheck": "false"}),
    )


class SolutionPreviewBlockForm(ProblemSolutionBlockForm):
    body_source = forms.CharField(
        max_length=PREVIEW_BODY_LIMIT,
        widget=forms.Textarea(attrs={
            "class": "form-control font-monospace", "rows": 3, "spellcheck": "false",
            "placeholder": "Write text and LaTeX here.",
        }),
    )


class BaseSolutionPreviewBlockFormSet(BaseProblemSolutionBlockFormSet):
    def clean(self):
        if self.initial_form_count():
            msg = "This tool exports the blocks you enter here, not saved solution records."
            raise forms.ValidationError(msg)
        super().clean()
        total = sum(
            len(form.cleaned_data.get("body_source") or "")
            for form in self.forms
            if getattr(form, "cleaned_data", None) and not form.cleaned_data.get("DELETE")
        )
        if total > PREVIEW_TOTAL_LIMIT:
            msg = f"Keep the solution within {PREVIEW_TOTAL_LIMIT:,} characters."
            raise forms.ValidationError(msg)


SolutionPreviewBlockFormSet = inlineformset_factory(
    ProblemSolution, ProblemSolutionBlock, form=SolutionPreviewBlockForm,
    formset=BaseSolutionPreviewBlockFormSet, extra=0, can_delete=True, can_order=True,
    max_num=PREVIEW_BLOCK_LIMIT, absolute_max=PREVIEW_BLOCK_LIMIT, validate_max=True,
)
