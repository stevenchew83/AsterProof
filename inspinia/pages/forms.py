from django import forms


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
