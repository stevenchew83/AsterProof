from django import forms

from inspinia.pages.contest_names import PROJECT_CONTEST_NAME_MAX_LENGTH
from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.contest_names import normalize_text_list


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


class ProblemStatementCsvImportForm(forms.Form):
    file = forms.FileField(
        label="Problem statement CSV",
        help_text=(
            "Upload a .csv file with columns PROBLEM UUID, LINKED PROBLEM UUID, CONTEST YEAR, "
            "CONTEST NAME, DAY LABEL, PROBLEM NUMBER, PROBLEM CODE, and STATEMENT LATEX."
        ),
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".csv,text/csv",
            },
        ),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        name = getattr(uploaded, "name", "") or ""
        if not name.lower().endswith(".csv"):
            msg = "Please upload a .csv file."
            raise forms.ValidationError(msg)
        return uploaded


class StatementMetadataWorkbookForm(forms.Form):
    file = forms.FileField(
        label="Statement metadata workbook",
        help_text=(
            "Upload a .xlsx file keyed by statement PROBLEM UUID with TOPIC, MOHS, "
            "Confidence, IMO slot guess, and Topic tags columns."
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
        label="Replace existing parsed topic tags for each matched problem",
        help_text=(
            "If checked, delete all parsed techniques for each touched problem before "
            "rebuilding from the workbook Topic tags column."
        ),
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


class HandleSummaryParserForm(forms.Form):
    source_text = forms.CharField(
        label="Handle summaries",
        strip=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "form": "handle-summary-parser-form",
                "id": "handle-summary-parser-input",
                "rows": 24,
                "spellcheck": "false",
                "placeholder": (
                    "Handle: Polynomial from a sector into a strip\n"
                    "Estimated MOHS: 8M-12M\n"
                    "IMO slot guess: P1/4\n"
                    "Topic tags: Alg/CA - polynomials over C; asymptotic leading term\n"
                    "Confidence: High"
                ),
            },
        ),
    )

    def clean_source_text(self):
        text = self.cleaned_data["source_text"]
        if not text.strip():
            msg = "Paste at least one Handle block."
            raise forms.ValidationError(msg)
        return text


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


class ContestMetadataForm(forms.Form):
    contest = forms.ChoiceField(widget=forms.HiddenInput())
    full_name = forms.CharField(
        required=False,
        label="Full contest name",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter the full contest name",
            },
        ),
    )
    countries_text = forms.CharField(
        required=False,
        label="Countries",
        help_text="Enter one country per line or separate entries with commas.",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "United States\nCanada",
            },
        ),
    )
    tags_text = forms.CharField(
        required=False,
        label="Tags",
        help_text="Enter one tag per line or separate entries with commas.",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Olympiad\nNational",
            },
        ),
    )
    description_markdown = forms.CharField(
        required=False,
        label="Description (Markdown)",
        help_text="Store raw Markdown for the contest description.",
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "rows": 12,
                "placeholder": "# Overview\n\nAdd the contest background, format, and notable details.",
            },
        ),
    )

    def __init__(self, *args, contest_choices: list[tuple[str, str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contest"].choices = contest_choices or []

    @staticmethod
    def _parse_text_list(raw_value: str) -> list[str]:
        parts = [
            entry
            for line in (raw_value or "").splitlines()
            for entry in line.split(",")
        ]
        return normalize_text_list(parts)

    def clean_contest(self):
        return normalize_contest_name(self.cleaned_data["contest"])

    def clean_full_name(self):
        return normalize_contest_name(self.cleaned_data["full_name"])

    def clean_countries_text(self):
        return self._parse_text_list(self.cleaned_data["countries_text"])

    def clean_tags_text(self):
        return self._parse_text_list(self.cleaned_data["tags_text"])

    def clean_description_markdown(self):
        return (self.cleaned_data["description_markdown"] or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        has_content = any(
            [
                cleaned_data.get("full_name"),
                cleaned_data.get("countries_text"),
                cleaned_data.get("tags_text"),
                cleaned_data.get("description_markdown"),
            ],
        )
        if cleaned_data.get("contest") and not has_content:
            msg = "Add at least one contest detail before saving."
            raise forms.ValidationError(msg)
        return cleaned_data
