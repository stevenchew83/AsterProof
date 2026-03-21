from django import forms

from inspinia.pages.contest_rename import PROJECT_CONTEST_NAME_MAX_LENGTH
from inspinia.pages.contest_rename import normalize_contest_name


class ProblemXlsxImportForm(forms.Form):
    file = forms.FileField(
        label="Excel workbook",
        help_text=(
            "Upload a .xlsx file with columns YEAR, TOPIC, MOHS, CONTEST, PROBLEM, "
            "CONTEST PROBLEM, Topic tags, ..."
        ),
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": (
                    ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            },
        ),
    )
    replace_tags = forms.BooleanField(
        required=False,
        initial=False,
        label="Replace existing parsed topic tags for each imported problem",
        help_text="If checked, delete all parsed techniques for a row before inserting from this file. "
        "Otherwise, merge domains when the same technique appears again.",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        name = getattr(uploaded, "name", "") or ""
        if not name.lower().endswith(".xlsx"):
            msg = "Please upload an .xlsx file."
            raise forms.ValidationError(msg)
        return uploaded


class ProblemStatementImportForm(forms.Form):
    source_text = forms.CharField(
        label="Contest text",
        strip=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "form": "latex-preview-form",
                "id": "latex-preview-input",
                "rows": 24,
                "spellcheck": "false",
            },
        ),
    )


class ProblemCompletionPasteForm(forms.Form):
    source_text = forms.CharField(
        label="Completion rows",
        strip=False,
        help_text=(
            "Paste lines like `PROBLEM UUID<TAB>2025-08-28`. "
            "You can also use `Done` when the problem is completed but the exact date is unknown."
        ),
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "rows": 12,
                "spellcheck": "false",
                "placeholder": (
                    "PROBLEM UUID\tDate\n"
                    "003d6ee5-ded7-47f9-a901-f78ea9c5788b\t2025-08-28\n"
                    "009792e6-3039-4a52-b5d3-2ff3a32d5287\tDone"
                ),
            },
        ),
    )

    def clean_source_text(self):
        text = self.cleaned_data["source_text"]
        if not text.strip():
            msg = "Paste at least one completion row."
            raise forms.ValidationError(msg)
        return text


class ContestRenameForm(forms.Form):
    source_contests = forms.MultipleChoiceField(
        label="Contest names to update",
        required=True,
        help_text="Tick one or more source contest names, then enter the canonical target name.",
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Select at least one contest to update."},
    )
    new_contest_name = forms.CharField(
        label="New contest name",
        max_length=PROJECT_CONTEST_NAME_MAX_LENGTH,
        help_text="Whitespace is normalized before saving.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter the updated contest name",
            },
        ),
    )

    def __init__(self, *args, contest_choices: list[tuple[str, str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_contests"].choices = contest_choices or []

    def clean_source_contests(self):
        selected_contests = self.cleaned_data["source_contests"]
        ordered_contests: list[str] = []
        seen_contests: set[str] = set()
        for contest_name in selected_contests:
            if contest_name in seen_contests:
                continue
            ordered_contests.append(contest_name)
            seen_contests.add(contest_name)
        return ordered_contests

    def clean_new_contest_name(self):
        return normalize_contest_name(self.cleaned_data["new_contest_name"])

    def clean(self):
        cleaned_data = super().clean()
        source_contests = cleaned_data.get("source_contests") or []
        new_contest_name = cleaned_data.get("new_contest_name")
        if source_contests and new_contest_name and new_contest_name in source_contests:
            msg = (
                "Pick a different contest name."
                if len(source_contests) == 1
                else "Uncheck the target contest name from the source selections."
            )
            raise forms.ValidationError(msg)
        return cleaned_data
