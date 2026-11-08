"""Small HTML forms for the member solution forum."""

from django import forms

VERDICTS = (
    ("correct", "Correct"),
    ("minor_gaps", "Minor gaps"),
    ("partial", "Partially correct"),
    ("incorrect", "Incorrect"),
    ("undetermined", "Unable to determine"),
)


class ForumForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs["class"] = "form-select" if isinstance(
                    field.widget, forms.Select,
                ) else "form-control"


class AssessmentForm(ForumForm):
    target_key = forms.CharField(widget=forms.HiddenInput)
    assessment_head = forms.CharField(required=False, widget=forms.HiddenInput)
    verdict = forms.ChoiceField(choices=VERDICTS)
    feedback = forms.CharField(max_length=12_000, widget=forms.Textarea(attrs={"rows": 4}), label="Overall feedback")
    gaps = forms.CharField(
        required=False, max_length=12_000, widget=forms.Textarea(attrs={"rows": 3}), label="Gaps or errors",
    )
    next_steps = forms.CharField(
        required=False, max_length=12_000, widget=forms.Textarea(attrs={"rows": 3}), label="Suggested next steps",
    )


class VerificationForm(ForumForm):
    target_key = forms.CharField(widget=forms.HiddenInput)
    decision_head = forms.CharField(required=False, widget=forms.HiddenInput)
    assessment_basis = forms.CharField(required=False, widget=forms.HiddenInput)
    verdict = forms.ChoiceField(choices=VERDICTS)
    reason = forms.CharField(
        max_length=12_000, widget=forms.Textarea(attrs={"rows": 4}), label="Decision and explanation",
    )


class CommentForm(ForumForm):
    body = forms.CharField(
        max_length=8_000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Ask a question or share an observation…"}),
        label="Comment",
    )
    parent_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
