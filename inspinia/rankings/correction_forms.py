"""Human-readable, field-whitelisted correction forms."""

from django import forms

from inspinia.rankings.models import OutcomeAlias
from inspinia.rankings.models import ResultClaim
from inspinia.rankings.models import ResultProfile
from inspinia.rankings.models import School
from inspinia.rankings.models import Student
from inspinia.rankings.models import StudentIdentityReview
from inspinia.rankings.models import StudentResult
from inspinia.rankings.profile_models import EvidenceSource
from inspinia.rankings.profile_models import EvidenceStatus
from inspinia.rankings.services.corrections import current_values


class IdentityStudentChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.full_name} · #{obj.pk} · birth year {obj.birth_year or 'not recorded'}"


class CorrectionForm(forms.Form):
    reason = forms.CharField(
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Explain what is incorrect and why the proposed value is supported.",
    )
    evidence = forms.CharField(
        max_length=4000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Reference the source or review decision. Do not include identity numbers or private notes.",
    )

    def __init__(self, *args, kind, target_id, hints=None, **kwargs):  # noqa: C901, PLR0912 - Typed field sets.
        super().__init__(*args, **kwargs)
        self.kind, self.target_id = kind, target_id
        hints = hints or {}
        initial = current_values(kind, target_id, hints)
        dynamic = {}
        if kind == "student":
            dynamic = {
                "full_name": forms.CharField(max_length=255),
                "birth_year": forms.IntegerField(required=False, min_value=1900),
                "school_id": forms.ModelChoiceField(
                    label="Current school",
                    queryset=School.objects.order_by("name"),
                    required=False,
                ),
            }
        elif kind == "result":
            dynamic = {
                "raw_score": forms.DecimalField(
                    label="Raw score",
                    max_digits=10,
                    decimal_places=2,
                    min_value=0,
                    required=False,
                ),
                "medal": forms.CharField(max_length=32, required=False),
                "band": forms.CharField(label="Category", max_length=32, required=False),
                "status_text": forms.CharField(label="Status", max_length=64, required=False),
            }
        elif kind == "assessment":
            dynamic = {
                "display_name": forms.CharField(max_length=255),
                "assessment_date": forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"})),
            }
        elif kind == "metadata":
            dynamic = {
                "family": forms.CharField(max_length=64, required=False),
                "definition": forms.CharField(
                    required=False,
                    max_length=4000,
                    widget=forms.Textarea(attrs={"rows": 3}),
                ),
                "definition_verified": forms.BooleanField(required=False),
                "date_verified": forms.BooleanField(required=False),
            }
        elif kind == "scale":
            dynamic = {
                "band": forms.CharField(
                    label="Category (blank for no recorded category)",
                    max_length=32,
                    required=False,
                ),
                "max_score": forms.DecimalField(
                    label="Paper maximum",
                    max_digits=10,
                    decimal_places=2,
                    min_value=0,
                    required=False,
                ),
                "verified": forms.BooleanField(label="Maximum verified against source", required=False),
                "comparable_scope": forms.CharField(
                    label="Comparable paper scope",
                    max_length=80,
                    required=False,
                    help_text=(
                        "Use the same reviewed scope only for comparable paper levels. "
                        "Percentages do not establish equal difficulty."
                    ),
                ),
            }
        elif kind == "attribution":
            dynamic = {
                "school_id": forms.ModelChoiceField(
                    label="School at this assessment",
                    queryset=School.objects.order_by("name"),
                ),
                "verified": forms.BooleanField(label="School attribution verified", required=False, initial=True),
            }
        elif kind == "school_alias":
            dynamic = {
                "alias": forms.CharField(label="Alternate school spelling", max_length=255),
                "active": forms.BooleanField(required=False, initial=True),
            }
        elif kind == "outcome_alias":
            dynamic = {
                "field": forms.ChoiceField(choices=OutcomeAlias.Field.choices),
                "alias": forms.CharField(label="Recorded spelling", max_length=64),
                "canonical": forms.CharField(label="Canonical label", max_length=64),
                "active": forms.BooleanField(required=False, initial=True),
            }
        elif kind == "identity":
            dynamic = {
                "second_student_id": IdentityStudentChoice(
                    label="Other student",
                    queryset=Student.objects.exclude(pk=target_id).order_by("full_name"),
                ),
                "decision": forms.ChoiceField(choices=StudentIdentityReview.Decision.choices),
                "active": forms.BooleanField(required=False, initial=True),
            }
        elif kind == "profile":
            dynamic = {
                "record_type": forms.ChoiceField(choices=ResultProfile.RecordType.choices),
                "discipline": forms.ChoiceField(choices=ResultProfile.Discipline.choices),
                "scope": forms.ChoiceField(choices=ResultProfile.Scope.choices),
                "scope_detail": forms.CharField(required=False, max_length=255,
                                                help_text="Record the exact stage or region, such as Kedah-Perlis."),
                "participation": forms.ChoiceField(choices=ResultProfile.Participation.choices),
                "featured": forms.BooleanField(required=False, label="Selected highlight",
                                               help_text="Also requires a reviewed award/ranking claim and source."),
                "active": forms.BooleanField(required=False, initial=True, label="Use this classification"),
            }
        elif kind == "claim":
            dynamic = {
                "claim_type": forms.ChoiceField(choices=ResultClaim.ClaimType.choices, initial="award"),
                "claim_label": forms.CharField(
                    max_length=255, label="Specific claim",
                    help_text="Review awards and rankings separately. Scores use two decimals.",
                ),
                "award_kind": forms.ChoiceField(choices=ResultClaim.AwardKind.choices,
                                                help_text="Use Not classified for a score or ranking claim."),
                "verification_status": forms.ChoiceField(choices=EvidenceStatus.choices),
                "source_type": forms.ChoiceField(choices=EvidenceSource.choices),
                "source_label": forms.CharField(max_length=255, required=False),
                "source_url": forms.URLField(max_length=500, required=False),
                "active": forms.BooleanField(required=False, initial=True, label="Use this claim"),
            }
            if not initial and hints.get("claim_type") == "score":
                result = StudentResult.objects.get(pk=target_id)
                if result.raw_score is not None:
                    dynamic["claim_label"].initial = format(result.raw_score, ".2f")
        for name, field in dynamic.items():
            if name in initial:
                field.initial = initial[name]
            elif name in hints:
                field.initial = hints[name]
            self.fields[name] = field
        # Put correction fields before the reason/source fields.
        self.order_fields([*dynamic, "reason", "evidence"])
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-check-input"
                if isinstance(field.widget, forms.CheckboxInput)
                else "form-select"
                if isinstance(field.widget, forms.Select)
                else "form-control"
            )

    def operations(self):
        values = {name: self.cleaned_data[name] for name in self.fields if name not in {"reason", "evidence"}}
        for name in ("school_id", "second_student_id"):
            if name in values:
                values[name] = values[name].pk if values[name] else None
        if self.kind == "school_alias":
            values["school_id"] = self.target_id
        if self.kind in {"attribution", "identity", "scale", "claim"}:
            values["evidence"] = self.cleaned_data["evidence"]
        return [{"kind": self.kind, "target_id": self.target_id, "values": values}]
