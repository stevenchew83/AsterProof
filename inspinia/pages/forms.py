from django import forms


class ProblemXlsxImportForm(forms.Form):
    file = forms.FileField(
        label="Excel workbook",
        help_text="Upload a .xlsx file with columns YEAR, TOPIC, MOHS, CONTEST, PROBLEM, CONTEST PROBLEM, Topic tags, …",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
            raise forms.ValidationError("Please upload an .xlsx file.")
        return uploaded
