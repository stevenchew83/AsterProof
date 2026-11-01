"""Explicit, bounded inputs for the offline coach workspace."""

import json
import uuid

from django import forms
from django.forms import formset_factory

DOMAINS = [("ALG", "Algebra"), ("GEO", "Geometry"), ("NT", "Number theory"), ("COM", "Combinatorics")]
ASSESSMENTS = [
    ("no_issues_found", "No issues found"),
    ("gap_found", "Gap found"),
    ("incomplete", "Incomplete"),
    ("unable_to_assess", "Unable to assess"),
]
YES_NO = [("true", "Yes"), ("false", "No")]
MAX_JSON_BYTES = 1_048_576
MAX_IMAGE_BYTES = 3_000_000
MAX_SNAPSHOT_CASES = 2_000
MAX_DEFECTS = 32


class WorkspaceForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if field.widget.is_hidden:
                continue
            if (
                isinstance(field, forms.ChoiceField)
                and not isinstance(field, (forms.MultipleChoiceField, forms.ModelChoiceField))
                and field.required
            ):
                if not any(value == "" for value, _label in field.choices):
                    field.choices = [("", "Choose an outcome"), *field.choices]
            field.widget.attrs.setdefault(
                "class",
                "form-select" if isinstance(field.widget, forms.Select) else "form-control",
            )
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs["class"] = "list-unstyled"
            if field.help_text:
                field.widget.attrs["aria-describedby"] = f"{self[name].auto_id}_helptext"

    def clean(self):
        cleaned = super().clean()
        for value in cleaned.values():
            if isinstance(value, (dict, list)) and (
                len(json.dumps(value, ensure_ascii=False).encode()) > MAX_JSON_BYTES
            ):
                message = "Keep each structured input below 1 MB."
                raise forms.ValidationError(message)
        return cleaned


class FamilyForm(WorkspaceForm):
    title = forms.CharField(
        max_length=200,
        help_text="Use a neutral problem-family title, without expected errors or verdicts.",
    )
    domain = forms.ChoiceField(choices=DOMAINS)
    metadata = forms.JSONField(
        required=False,
        initial=dict,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Optional curation metadata. This is hidden from independent reviewers.",
    )

    def clean_metadata(self):
        value = self.cleaned_data.get("metadata") or {}
        if not isinstance(value, dict):
            message = "Use a metadata object."
            raise forms.ValidationError(message)
        return value


class CaseForm(WorkspaceForm):
    statement = forms.CharField(
        max_length=30_000,
        widget=forms.Textarea(attrs={"rows": 6}),
        label="Complete problem statement",
    )
    source = forms.CharField(max_length=100_000, widget=forms.Textarea(attrs={"rows": 12}), label="Proof source")
    language = forms.CharField(max_length=40, initial="English")
    conditions = forms.CharField(
        required=False,
        max_length=8_000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Restrictions, conventions and permitted methods",
    )
    completeness = forms.ChoiceField(
        choices=[
            ("present", "Required input present"),
            ("partial", "Partial input"),
            ("missing_essential_context", "Essential context missing"),
            ("unreadable", "Unreadable"),
            ("unresolved", "Not yet established"),
        ],
    )
    problem_integrity = forms.ChoiceField(
        choices=[
            ("no_known_defect", "No known problem defect"),
            ("suspected_defect", "Suspected problem defect"),
            ("confirmed_defect", "Confirmed problem defect"),
            ("unresolved", "Not yet established"),
        ],
    )
    source_reference = forms.CharField(
        max_length=2_000,
        label="Source and provenance",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    rights = forms.CharField(
        max_length=2_000,
        label="Rights or reuse permission",
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    permitted_uses = forms.MultipleChoiceField(
        choices=[
            ("benchmark", "Benchmark reuse"),
            ("development", "Development diagnostics"),
        ],
        widget=forms.CheckboxSelectMultiple,
    )
    construction = forms.ChoiceField(
        choices=[
            ("learner_submission", "Authentic learner submission"),
            ("coach_original", "Coach original"),
            ("public_source", "Public source"),
            ("controlled_mutation", "Controlled mathematical mutation"),
            ("synthetic", "Synthetic fixture"),
        ],
    )
    consent_reference = forms.CharField(
        required=False,
        max_length=2_000,
        help_text="Required for authentic learner submissions.",
    )
    learner_id = forms.IntegerField(
        required=False,
        min_value=1,
        label="Learner account identifier",
        help_text="Authentic learner reuse requires current consent bound to this author, revision and source digest.",
    )
    source_revision_id = forms.UUIDField(required=False, label="Authorized source revision identifier")
    source_digest = forms.CharField(
        required=False,
        min_length=64,
        max_length=64,
        label="Authorized source SHA-256 digest",
    )
    lawful_eligibility = forms.CharField(
        required=False,
        max_length=2_000,
        label="Documented learner reuse eligibility",
    )
    withdrawal_policy = forms.CharField(required=False, max_length=2_000, label="Applicable withdrawal policy")
    retention_until = forms.DateTimeField(
        label="Permission / retention deadline",
        help_text="Use YYYY-MM-DD HH:MM in the displayed account timezone.",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "iso-8601"],
    )

    def payload(self):
        data = self.cleaned_data
        return {
            **{
                key: data[key]
                for key in ("statement", "source", "language", "conditions", "completeness", "problem_integrity")
            },
            "provenance": {
                "source": data["source_reference"],
                "rights": data["rights"],
                "permitted_uses": data["permitted_uses"],
                "construction": data["construction"],
                "retention_until": data["retention_until"].isoformat(),
                "learner_id": data.get("learner_id"),
                "source_revision_id": str(data["source_revision_id"]) if data.get("source_revision_id") else "",
                "source_digest": data.get("source_digest", ""),
                **{key: data.get(key, "") for key in ("consent_reference", "lawful_eligibility", "withdrawal_policy")},
            },
        }


class AssetForm(WorkspaceForm):
    image = forms.FileField(required=False)
    role = forms.ChoiceField(
        choices=[("official_diagram", "Official problem diagram"), ("supporting_image", "Supporting proof image")],
    )
    description = forms.CharField(required=False, max_length=300)

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and image.size > MAX_IMAGE_BYTES:
            message = "Each image must be at most 3 MB."
            raise forms.ValidationError(message)
        return image


AssetFormSet = formset_factory(AssetForm, extra=4, max_num=4, validate_max=True, absolute_max=4)


class JudgmentForm(WorkspaceForm):
    expected_digest = forms.CharField(max_length=64, widget=forms.HiddenInput)
    assessment = forms.ChoiceField(choices=ASSESSMENTS)
    input_sufficiency = forms.ChoiceField(choices=CaseForm.base_fields["completeness"].choices)
    problem_integrity = forms.ChoiceField(choices=CaseForm.base_fields["problem_integrity"].choices)
    logical_validity = forms.ChoiceField(
        choices=[("valid", "Valid"), ("invalid", "Invalid"), ("uncertain", "Expert uncertainty")],
    )
    proof_completeness = forms.ChoiceField(
        choices=[("complete", "Complete"), ("incomplete", "Incomplete"), ("undetermined", "Undetermined")],
    )
    justification = forms.ChoiceField(
        choices=[
            ("sufficient", "Sufficient"),
            ("compressed_acceptable", "Compressed but acceptable"),
            ("missing_substantial", "Substantial justification missing"),
            ("undetermined", "Undetermined"),
        ],
    )
    method = forms.ChoiceField(
        choices=[
            ("conventional", "Conventional"),
            ("alternative", "Valid alternative method"),
            ("advanced", "Advanced method"),
            ("unresolved", "Not recognized / unresolved"),
        ],
    )
    task_compliance = forms.ChoiceField(
        choices=[("met", "Restrictions met"), ("unmet", "Restrictions not met"), ("undetermined", "Undetermined")],
    )
    explanation = forms.CharField(
        max_length=12_000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Explain the mathematical judgment independently of the expected method.",
    )

    def payload(self, defects):
        return {key: value for key, value in self.cleaned_data.items() if key != "expected_digest"} | {
            "defects": defects,
        }


class AdjudicationForm(JudgmentForm):
    reason = forms.CharField(
        max_length=12_000,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Explain how the independent judgments were reconciled. Originals are preserved.",
    )


def _uuid_list(value):
    if not value.strip():
        return []
    try:
        return [str(uuid.UUID(part.strip())) for part in value.split(",")]
    except ValueError as error:
        message = "Use comma-separated defect identifiers."
        raise forms.ValidationError(message) from error


class DefectForm(WorkspaceForm):
    id = forms.UUIDField(required=False, label="Defect identifier", widget=forms.TextInput(attrs={"readonly": True}))
    significance = forms.ChoiceField(
        required=False,
        choices=[
            ("", "No defect in this row"),
            ("minor", "Minor"),
            ("consequential", "Consequential"),
            ("fatal", "Fatal"),
        ],
    )
    explanation = forms.CharField(
        required=False,
        max_length=6_000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Mathematical defect",
    )
    justification = forms.CharField(
        required=False,
        max_length=6_000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Supporting mathematical explanation",
    )
    quote = forms.CharField(
        required=False,
        max_length=4_000,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Exact source passage, if one exists. Leave blank for omissions or implicit hypotheses.",
    )
    root_id = forms.UUIDField(
        required=False,
        label="Root defect identifier",
        help_text="Leave blank for an independent root defect.",
    )
    depends_on = forms.CharField(
        required=False,
        max_length=600,
        label="Dependency identifiers",
        help_text="Optional comma-separated defect identifiers.",
    )

    def clean(self):
        data = super().clean()
        if not any(
            data.get(key) for key in ("significance", "explanation", "justification", "quote", "root_id", "depends_on")
        ):
            return data
        for field in ("significance", "explanation", "justification"):
            if not data.get(field):
                self.add_error(field, "Complete this field for a recorded defect.")
        data["id"] = data.get("id") or uuid.uuid4()
        data["depends_on"] = _uuid_list(data.get("depends_on", ""))
        return data

    def payload(self):
        data = self.cleaned_data
        if not data.get("significance"):
            return None
        identifier = str(data["id"])
        return {
            "id": identifier,
            "significance": data["significance"],
            "explanation": data["explanation"],
            "justification": data["justification"],
            "root_id": str(data.get("root_id") or identifier),
            "depends_on": data.get("depends_on", []),
            "spans": [{"quote": data["quote"]}] if data.get("quote") else [],
        }


DefectFormSet = formset_factory(
    DefectForm,
    extra=MAX_DEFECTS,
    max_num=MAX_DEFECTS,
    validate_max=True,
    absolute_max=MAX_DEFECTS,
)


class SnapshotForm(WorkspaceForm):
    name = forms.CharField(max_length=200)
    membership = forms.JSONField(
        widget=forms.Textarea(attrs={"rows": 10}),
        help_text=(
            'List of {"case_id": "UUID", "partition": "development|validation|final_test"}. '
            "Related families must stay together."
        ),
    )
    protocol = forms.JSONField(
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Frozen rubric version, sampling and split decisions. This action never approves a model.",
    )

    def clean_membership(self):
        value = self.cleaned_data["membership"]
        if not isinstance(value, list) or not value or len(value) > MAX_SNAPSHOT_CASES:
            message = "Select between 1 and 2,000 explicit case revisions."
            raise forms.ValidationError(message)
        if any(
            not isinstance(row, dict)
            or row.get("partition")
            not in {
                "development",
                "validation",
                "final_test",
            }
            for row in value
        ):
            message = "Every row needs a case UUID and a known partition."
            raise forms.ValidationError(message)
        try:
            for row in value:
                uuid.UUID(row["case_id"])
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            message = "Every row needs a case UUID and a known partition."
            raise forms.ValidationError(message) from error
        return value

    def clean_protocol(self):
        return _object(self.cleaned_data["protocol"])


class RunImportForm(WorkspaceForm):
    profile = forms.ModelChoiceField(queryset=None, label="Frozen reviewer profile")
    partition = forms.ChoiceField(
        choices=[
            ("development", "Development"),
            ("validation", "Internal validation"),
            ("final_test", "Locked final test"),
        ],
        help_text="Import every case in this frozen partition. This does not authorize a provider run.",
    )
    reports = forms.JSONField(
        widget=forms.Textarea(attrs={"rows": 12}),
        help_text="Paste the report document. Every import remains unverified model evidence.",
    )
    protocol = forms.JSONField(
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Frozen evaluation and risk-coverage rules.",
    )

    def __init__(self, *args, profiles, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile"].queryset = profiles
        self.fields["profile"].label_from_instance = lambda obj: obj.payload.get("name", obj.digest[:16])

    def clean_reports(self):
        return _object(self.cleaned_data["reports"])

    def clean_protocol(self):
        return _object(self.cleaned_data["protocol"])


class FindingReviewForm(WorkspaceForm):
    useful = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Did this report provide useful mathematical feedback?",
    )
    report_spoiler = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Does any report field disclose an unapproved solution?",
    )
    abstention_appropriate = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="If the reviewer abstained, was that justified?",
    )


class FindingAssessmentForm(WorkspaceForm):
    finding_id = forms.CharField(max_length=64, widget=forms.HiddenInput)
    supported = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Mathematically supported",
    )
    material = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Material allegation",
    )
    localization_correct = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Correctly localized",
    )
    severity_correct = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Proportionate severity",
    )
    context_correct = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Consistent with the full proof context",
    )
    hint_correct = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Hints mathematically sound",
    )
    spoiler = forms.TypedChoiceField(
        choices=YES_NO,
        coerce=lambda value: value == "true",
        label="Unapproved spoiler present",
    )
    matched_defect_ids = forms.CharField(
        required=False,
        max_length=600,
        label="Matched ground-truth defect identifiers",
    )

    def clean_matched_defect_ids(self):
        return _uuid_list(self.cleaned_data["matched_defect_ids"])


class FindingAdjudicationForm(FindingReviewForm):
    reason = forms.CharField(
        max_length=4_000,
        widget=forms.Textarea(attrs={"rows": 5}),
        label="Mathematical adjudication reason",
        help_text="Explain how the two report assessments are reconciled. Both original assessments remain unchanged.",
    )


FindingAssessmentFormSet = formset_factory(
    FindingAssessmentForm,
    extra=0,
    max_num=8,
    validate_max=True,
    absolute_max=8,
)


class ProfileForm(WorkspaceForm):
    payload = forms.JSONField(
        widget=forms.Textarea(attrs={"rows": 16}),
        label="Complete frozen reviewer profile",
        help_text=(
            "Include model, prompt, rubric, output_schema, preprocessing, reasoning, output_limit, "
            "timeout, retry_policy (none), and pricing. Creating a profile makes no API request."
        ),
    )

    def clean_payload(self):
        return _object(self.cleaned_data["payload"])


def _object(value):
    if not isinstance(value, dict):
        message = "Use a JSON object."
        raise forms.ValidationError(message)
    return value
