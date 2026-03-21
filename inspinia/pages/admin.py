from django import forms
from django.contrib import admin

from .contest_names import normalize_text_list
from .models import ContestMetadata
from .models import ContestProblemStatement
from .models import ProblemSolveRecord
from .models import ProblemTopicTechnique
from .models import UserProblemCompletion


class ProblemTopicTechniqueInline(admin.TabularInline):
    model = ProblemTopicTechnique
    extra = 0


class ContestMetadataAdminForm(forms.ModelForm):
    countries_text = forms.CharField(
        required=False,
        label="Countries",
        help_text="Enter one country per line or separate entries with commas.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    tags_text = forms.CharField(
        required=False,
        label="Tags",
        help_text="Enter one tag per line or separate entries with commas.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = ContestMetadata
        fields = ("contest", "full_name", "countries_text", "description_markdown", "tags_text")
        widgets = {
            "description_markdown": forms.Textarea(
                attrs={"rows": 10},
            ),
        }
        help_texts = {
            "description_markdown": "Store raw Markdown for the contest description.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get("instance")
        if instance is not None:
            self.fields["countries_text"].initial = "\n".join(instance.countries or [])
            self.fields["tags_text"].initial = "\n".join(instance.tags or [])

    @staticmethod
    def _parse_text_list(raw_value: str) -> list[str]:
        pieces = [
            entry
            for line in (raw_value or "").splitlines()
            for entry in line.split(",")
        ]
        return normalize_text_list(pieces)

    def clean_countries_text(self):
        return self._parse_text_list(self.cleaned_data["countries_text"])

    def clean_tags_text(self):
        return self._parse_text_list(self.cleaned_data["tags_text"])

    def save(self, commit=True):  # noqa: FBT002 - Django ModelForm.save uses this signature
        instance = super().save(commit=False)
        instance.countries = self.cleaned_data["countries_text"]
        instance.tags = self.cleaned_data["tags_text"]
        if commit:
            instance.save()
        return instance


@admin.register(ProblemSolveRecord)
class ProblemSolveRecordAdmin(admin.ModelAdmin):
    list_display = (
        "problem_uuid",
        "year",
        "topic",
        "mohs",
        "contest",
        "problem",
        "imo_slot_guess_value",
        "rationale_value",
        "pitfalls_value",
    )
    search_fields = ("problem_uuid", "contest", "problem", "contest_year_problem")
    list_filter = ("year", "topic", "contest")
    inlines = (ProblemTopicTechniqueInline,)


@admin.register(ProblemTopicTechnique)
class ProblemTopicTechniqueAdmin(admin.ModelAdmin):
    list_display = ("record", "technique", "domains")
    search_fields = ("technique",)


@admin.register(UserProblemCompletion)
class UserProblemCompletionAdmin(admin.ModelAdmin):
    list_display = ("user", "problem", "completion_date", "updated_at")
    search_fields = (
        "user__email",
        "problem__contest",
        "problem__problem",
        "problem__contest_year_problem",
        "problem__problem_uuid",
    )
    list_filter = ("completion_date", "problem__contest", "problem__year")


@admin.register(ContestProblemStatement)
class ContestProblemStatementAdmin(admin.ModelAdmin):
    list_display = (
        "problem_uuid",
        "contest_year_problem",
        "day_label",
        "linked_problem",
        "updated_at",
    )
    search_fields = (
        "problem_uuid",
        "contest_name",
        "contest_year_problem",
        "problem_code",
        "statement_latex",
        "linked_problem__contest_year_problem",
    )
    list_filter = ("contest_year", "contest_name", "day_label")


@admin.register(ContestMetadata)
class ContestMetadataAdmin(admin.ModelAdmin):
    form = ContestMetadataAdminForm
    list_display = (
        "contest_uuid",
        "contest",
        "full_name",
        "countries_preview",
        "tags_preview",
        "updated_at",
    )
    search_fields = ("contest", "full_name", "description_markdown")
    readonly_fields = ("contest_uuid", "created_at", "updated_at")

    @admin.display(description="Countries")
    def countries_preview(self, obj: ContestMetadata) -> str:
        return ", ".join(obj.countries or []) or "-"

    @admin.display(description="Tags")
    def tags_preview(self, obj: ContestMetadata) -> str:
        return ", ".join(obj.tags or []) or "-"
