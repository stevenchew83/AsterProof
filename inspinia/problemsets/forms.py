from django import forms

from inspinia.problemsets.models import ProblemList


class ProblemListForm(forms.ModelForm):
    class Meta:
        model = ProblemList
        fields = ("title", "description", "hide_source", "hide_topic", "hide_mohs", "hide_subtopics")
        labels = {
            "hide_mohs": "Hide MOHS",
            "hide_source": "Hide original source",
            "hide_subtopics": "Hide subtopics",
            "hide_topic": "Hide topic",
        }
        help_texts = {
            "hide_mohs": "Remove difficulty labels from the public and workspace list views.",
            "hide_source": "Use custom titles or generic problem numbers without revealing contest source.",
            "hide_subtopics": "Hide searchable topic-technique tags on public and workspace list views.",
            "hide_topic": "Remove broad topic labels from the public and workspace list views.",
        }
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Geometry warmups, Shortlist inequalities, ...",
                },
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "What should another student use this list for?",
                },
            ),
            "hide_source": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "hide_topic": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "hide_mohs": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "hide_subtopics": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_title(self) -> str:
        title = (self.cleaned_data["title"] or "").strip()
        if not title:
            msg = "List title is required."
            raise forms.ValidationError(msg)
        return title

    def clean_description(self) -> str:
        return (self.cleaned_data["description"] or "").strip()


class ProblemListAddProblemForm(forms.Form):
    problem_uuid = forms.UUIDField(
        label="Problem UUID",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Paste a problem UUID",
            },
        ),
    )


class ProblemListSearchForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "type": "search",
                "placeholder": "Title, author, contest, topic, tag...",
            },
        ),
    )

    def clean_q(self) -> str:
        return (self.cleaned_data["q"] or "").strip()
