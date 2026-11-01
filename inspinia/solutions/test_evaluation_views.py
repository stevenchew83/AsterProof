"""Offline coach workspace access, blind annotation and private asset delivery."""

import json
from datetime import timedelta
from http import HTTPStatus
from io import BytesIO

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.db import transaction
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from inspinia.solutions import evaluation as ev
from inspinia.solutions.evaluation_models import CoachJudgment
from inspinia.solutions.evaluation_models import EvaluationAuditEvent
from inspinia.solutions.evaluation_models import EvaluationCase
from inspinia.solutions.evaluation_models import EvaluationDatasetSnapshot
from inspinia.solutions.evaluation_models import EvaluationFindingJudgment
from inspinia.solutions.evaluation_models import EvaluationRun
from inspinia.solutions.evaluation_models import ReviewerProfile
from inspinia.solutions.evaluation_navigation import evaluation_workspace as evaluation_navigation
from inspinia.solutions.evaluation_views import PAGE_SIZE
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def judgment():
    return {
        "assessment": "no_issues_found",
        "input_sufficiency": "present",
        "problem_integrity": "no_known_defect",
        "logical_validity": "valid",
        "proof_completeness": "complete",
        "justification": "sufficient",
        "method": "alternative",
        "task_compliance": "met",
        "explanation": "The argument is valid.",
        "defects": [],
    }


def image_bytes():
    output = BytesIO()
    Image.new("RGB", (30, 20), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def workspace():
    admin = UserFactory(is_superuser=True, role="admin")
    curator = UserFactory(role="trainer", is_approved=True)
    ev.grant(admin, curator, "curator", ev.WORKSPACE)
    family = ev.create_family(
        curator,
        {"title": "Neutral family", "domain": "ALG", "metadata": {"mutation": "SECRET-MUTATION-NOTE"}},
    )
    data = {
        "statement": "For real x, prove x squared is nonnegative.",
        "source": "CASE-SOURCE: A square is nonnegative. </textarea><script>alert(1)</script>",
        "language": "en",
        "completeness": "present",
        "problem_integrity": "no_known_defect",
        "provenance": {
            "source": "Coach original",
            "rights": "Author permission",
            "permitted_uses": ["benchmark"],
            "construction": "coach_original",
            "retention_until": (timezone.now() + timedelta(days=90)).isoformat(),
        },
    }
    case = ev.create_case(
        curator,
        family,
        data,
        assets=[{"data": image_bytes(), "role": "official_diagram", "description": "Official diagram"}],
    )
    reviewers = [UserFactory(role="trainer", is_approved=True) for _ in range(2)]
    for reviewer in reviewers:
        ev.grant(admin, reviewer, "reviewer", case, expertise="Algebra")
    return {"admin": admin, "curator": curator, "family": family, "case": case, "reviewers": reviewers, "data": data}


def make_run(workspace):
    case = workspace["case"]
    for reviewer in workspace["reviewers"]:
        ev.submit_judgment(reviewer, case, judgment(), case.bundle.digest)
    custodian = UserFactory(role="trainer", is_approved=True)
    ev.grant(workspace["admin"], custodian, "custodian", case)
    snapshot = ev.freeze_dataset(
        custodian,
        "Local synthetic benchmark",
        [
            {"case_id": str(case.pk), "partition": "final_test"},
        ],
        {"rubric_version": "math-v1"},
    )
    profile = ev.create_profile(
        workspace["curator"],
        {
            "name": "Offline fixture profile",
            "model": "fake-local",
            "prompt": "Review reasoning.",
            "rubric": "math-v1",
            "output_schema": {},
            "preprocessing": "rgb-png-2048-v1",
            "reasoning": "medium",
            "output_limit": 1000,
            "timeout": 10,
            "retry_policy": "none",
            "pricing": {"input": 0, "output": 0},
        },
    )
    reports = {
        str(case.pk): {
            "status": "completed",
            "assessment": "no_issues_found",
            "findings": [],
            "summary": "REPORT-SUMMARY",
        },
    }
    protocol = {
        "min_usable_coverage": 0.5,
        "min_finding_precision": 1,
        "min_defect_recall": 1,
        "min_families": 1,
        "partition": "final_test",
    }
    run = ev.import_run(custodian, snapshot, profile, reports, protocol)
    return custodian, snapshot, profile, run


def test_workspace_requires_assignment_and_keeps_source_private(client, workspace):
    url = reverse("solutions:evaluation_workspace")
    assert client.get(url).status_code == HTTPStatus.FOUND
    client.force_login(UserFactory())
    assert client.get(url).status_code == HTTPStatus.FORBIDDEN
    detail = client.get(reverse("solutions:evaluation_case_detail", args=[workspace["case"].pk]))
    assert detail.status_code == HTTPStatus.NOT_FOUND
    assert b"CASE-SOURCE" not in detail.content


def test_independent_reviewer_cannot_see_other_judgment_or_curation_notes(client, workspace):
    case = workspace["case"]
    original = judgment() | {"explanation": "SECRET-FIRST-JUDGMENT"}
    ev.submit_judgment(workspace["reviewers"][0], case, original, case.bundle.digest)
    client.force_login(workspace["reviewers"][1])
    response = client.get(reverse("solutions:evaluation_case_detail", args=[case.pk]))
    assert response.status_code == HTTPStatus.OK
    assert b"CASE-SOURCE" in response.content
    assert b"SECRET-FIRST-JUDGMENT" not in response.content
    assert b"SECRET-MUTATION-NOTE" not in response.content
    assert b"<script>alert(1)</script>" not in response.content
    assert b"&lt;/textarea&gt;&lt;script&gt;" in response.content
    assert "no-store" in response["Cache-Control"]
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"


def test_workspace_lists_only_assigned_cases_without_mathematical_labels(client, workspace):
    client.force_login(workspace["reviewers"][0])
    response = client.get(reverse("solutions:evaluation_workspace"))
    assert response.status_code == HTTPStatus.OK
    assert str(workspace["case"].pk).encode() in response.content
    assert b"CASE-SOURCE" not in response.content
    assert b"SECRET-MUTATION-NOTE" not in response.content


def test_http_judgment_submission_preserves_independent_record(client, workspace):
    case = workspace["case"]
    client.force_login(workspace["reviewers"][0])
    data = judgment()
    data.pop("defects")
    data |= {"expected_digest": case.bundle.digest, "defects-TOTAL_FORMS": "0", "defects-INITIAL_FORMS": "0"}
    response = client.post(reverse("solutions:evaluation_judgment", args=[case.pk]), data)
    assert response.status_code == HTTPStatus.FOUND
    assert CoachJudgment.objects.get(case=case).payload["logical_validity"] == "valid"
    assert EvaluationAuditEvent.objects.filter(target_id=case.pk, kind="judgment_submitted").exists()


def test_judgment_form_rejects_stale_input_and_forged_defect_management(client, workspace):
    client.force_login(workspace["reviewers"][0])
    case = workspace["case"]
    data = judgment()
    data.pop("defects")
    data |= {"expected_digest": "stale", "defects-TOTAL_FORMS": "0", "defects-INITIAL_FORMS": "0"}
    response = client.post(reverse("solutions:evaluation_judgment", args=[case.pk]), data)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not CoachJudgment.objects.filter(case=case).exists()
    data.update(expected_digest=case.bundle.digest)
    data.pop("defects-TOTAL_FORMS")
    response = client.post(reverse("solutions:evaluation_judgment", args=[case.pk]), data)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not CoachJudgment.objects.filter(case=case).exists()


def test_workspace_mutations_enforce_csrf(workspace):
    client = Client(enforce_csrf_checks=True)
    client.force_login(workspace["curator"])
    response = client.post(reverse("solutions:evaluation_family_create"), {"title": "Another family", "domain": "ALG"})
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_case_asset_requires_assignment_and_is_private_normalized_png(client, workspace):
    case = workspace["case"]
    asset = case.bundle.assets.get()
    url = reverse("solutions:evaluation_asset", args=[case.pk, asset.pk])
    client.force_login(UserFactory())
    assert client.get(url).status_code == HTTPStatus.NOT_FOUND
    client.force_login(workspace["reviewers"][0])
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "image/png"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]
    assert response.content == bytes(asset.normalized)
    assert EvaluationAuditEvent.objects.filter(target_id=case.pk, kind="asset_served").exists()


def test_audit_failure_does_not_serve_proof(client, workspace, monkeypatch):
    client.force_login(workspace["reviewers"][0])

    def fail(*_args, **_kwargs):
        message = "audit unavailable"
        raise RuntimeError(message)

    monkeypatch.setattr(ev, "audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        client.get(reverse("solutions:evaluation_case_detail", args=[workspace["case"].pk]))


def test_custodian_sees_pending_report_then_finding_evaluator_completes_annotation(client, workspace):
    custodian, _snapshot, _profile, run = make_run(workspace)
    client.force_login(custodian)
    response = client.get(reverse("solutions:evaluation_run_detail", args=[run.pk]))
    assert response.status_code == HTTPStatus.OK
    assert b"REPORT-SUMMARY" in response.content
    assert b"assessments remain" in response.content
    evaluator = UserFactory(role="trainer", is_approved=True)
    ev.grant(workspace["admin"], evaluator, "finding_evaluator", workspace["case"], expertise="Algebra")
    client.force_login(evaluator)
    url = reverse("solutions:evaluation_finding_judgment", args=[run.pk, workspace["case"].pk])
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert b"REPORT-SUMMARY" in response.content
    response = client.post(
        url,
        {
            "useful": "true",
            "report_spoiler": "false",
            "abstention_appropriate": "false",
            "findings-TOTAL_FORMS": "0",
            "findings-INITIAL_FORMS": "0",
        },
    )
    assert response.status_code == HTTPStatus.FOUND
    assert EvaluationFindingJudgment.objects.filter(run=run, case=workspace["case"]).exists()
    client.force_login(custodian)
    response = client.get(reverse("solutions:evaluation_run_detail", args=[run.pk]))
    assert response.status_code == HTTPStatus.OK
    assert b"Usable coverage" in response.content
    assert b"Model readiness untested" in response.content


def test_developer_receives_aggregate_once_without_case_content(client, workspace):
    custodian, snapshot, _profile, run = make_run(workspace)
    ev.grant(workspace["admin"], custodian, "finding_evaluator", workspace["case"], expertise="Algebra")
    ev.assess_findings(custodian, run, workspace["case"], {"useful": True, "report_spoiler": False, "findings": []})
    developer = UserFactory(role="trainer", is_approved=True)
    ev.grant(workspace["admin"], developer, "developer", snapshot)
    client.force_login(developer)
    url = reverse("solutions:evaluation_run_detail", args=[run.pk])
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    for forbidden in ["CASE-SOURCE", "REPORT-SUMMARY", str(workspace["case"].pk)]:
        assert forbidden.encode() not in response.content
    assert client.get(url).status_code == HTTPStatus.CONFLICT


def test_freeze_form_rejects_malformed_membership_without_traceback(client, workspace):
    ev.grant(workspace["admin"], workspace["curator"], "custodian", workspace["case"])
    client.force_login(workspace["curator"])
    response = client.post(
        reverse("solutions:evaluation_snapshot_create"),
        {
            "name": "Invalid",
            "membership": json.dumps(["not a row"]),
            "protocol": "{}",
        },
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_case_preparation_form_creates_frozen_input_without_review(client, workspace):
    client.force_login(workspace["curator"])
    response = client.post(
        reverse("solutions:evaluation_case_create", args=[workspace["family"].pk]),
        {
            "statement": "Prove 1 + 1 = 2.",
            "source": "This follows from addition.",
            "language": "English",
            "conditions": "Use ordinary integer arithmetic.",
            "completeness": "present",
            "problem_integrity": "no_known_defect",
            "source_reference": "An original local case",
            "rights": "Author permission",
            "permitted_uses": ["benchmark"],
            "construction": "coach_original",
            "retention_until": (timezone.now() + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M"),
            "assets-TOTAL_FORMS": "0",
            "assets-INITIAL_FORMS": "0",
        },
    )
    assert response.status_code == HTTPStatus.FOUND
    created = EvaluationCase.objects.exclude(pk=workspace["case"].pk).get()
    assert created.bundle.payload["source"] == "This follows from addition."
    assert not created.judgments.exists()


def test_http_profile_snapshot_and_report_import_stay_offline(client, workspace):
    actor = workspace["curator"]
    case = workspace["case"]
    for reviewer in workspace["reviewers"]:
        ev.submit_judgment(reviewer, case, judgment(), case.bundle.digest)
    ev.grant(workspace["admin"], actor, "custodian", case)
    client.force_login(actor)
    profile_data = {
        "name": "Frozen local profile",
        "model": "fake-local",
        "prompt": "Review reasoning.",
        "rubric": "math-v1",
        "output_schema": {},
        "preprocessing": "rgb-png-2048-v1",
        "reasoning": "medium",
        "output_limit": 1000,
        "timeout": 10,
        "retry_policy": "none",
        "pricing": {"input": 0, "output": 0},
    }
    response = client.post(reverse("solutions:evaluation_profile_create"), {"payload": json.dumps(profile_data)})
    assert response.status_code == HTTPStatus.FOUND
    profile = ReviewerProfile.objects.get()
    response = client.post(
        reverse("solutions:evaluation_snapshot_create"),
        {
            "name": "Frozen through HTTP",
            "membership": json.dumps([{"case_id": str(case.pk), "partition": "validation"}]),
            "protocol": json.dumps({"rubric_version": "math-v1"}),
        },
    )
    assert response.status_code == HTTPStatus.FOUND
    snapshot = EvaluationDatasetSnapshot.objects.get()
    url = reverse("solutions:evaluation_run_import", args=[snapshot.pk])
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert f'value="{profile.pk}"'.encode() in response.content
    response = client.post(
        url,
        {
            "profile": str(profile.pk),
            "partition": "validation",
            "reports": json.dumps(
                {
                    str(case.pk): {
                        "status": "completed",
                        "assessment": "no_issues_found",
                        "findings": [],
                    },
                },
            ),
            "protocol": json.dumps({"min_usable_coverage": 0.5}),
        },
    )
    assert response.status_code == HTTPStatus.FOUND
    assert EvaluationRun.objects.get().origin == "manual_import"


def test_http_root_defect_can_describe_an_omission_without_source_quote(client, workspace):
    case = workspace["case"]
    client.force_login(workspace["reviewers"][0])
    data = judgment()
    data.pop("defects")
    data |= {
        "assessment": "gap_found",
        "logical_validity": "invalid",
        "explanation": "A necessary case is absent.",
        "expected_digest": case.bundle.digest,
        "defects-TOTAL_FORMS": "1",
        "defects-INITIAL_FORMS": "0",
        "defects-0-significance": "fatal",
        "defects-0-explanation": "The exceptional case was omitted.",
        "defects-0-justification": "The claim quantifies over the exceptional case too.",
    }
    response = client.post(reverse("solutions:evaluation_judgment", args=[case.pk]), data)
    assert response.status_code == HTTPStatus.FOUND
    defect = CoachJudgment.objects.get(case=case).payload["defects"][0]
    assert defect["root_id"] == defect["id"]
    assert defect["spans"] == []


def test_assigned_case_and_family_lists_have_separate_server_pagination(client, workspace):
    for number in range(PAGE_SIZE):
        ev.create_case(workspace["curator"], workspace["family"], workspace["data"])
        ev.create_family(workspace["curator"], {"title": f"Additional family {number}", "domain": "ALG"})
    client.force_login(workspace["curator"])
    response = client.get(reverse("solutions:evaluation_workspace"))
    assert len(response.context["page_obj"]) == PAGE_SIZE
    assert len(response.context["family_page"]) == PAGE_SIZE
    response = client.get(reverse("solutions:evaluation_workspace"), {"page": "2", "family_page": "2"})
    assert len(response.context["page_obj"]) == 1
    assert len(response.context["family_page"]) == 1


def test_evaluation_navigation_anonymous_never_queries_database(django_assert_num_queries):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    with django_assert_num_queries(0):
        assert evaluation_navigation(request) == {"evaluation_workspace_available": False}


def test_evaluation_navigation_reflects_assignments_without_granting_access(workspace):
    request = RequestFactory().get("/")
    request.user = UserFactory(role="trainer", is_approved=True)
    assert not evaluation_navigation(request)["evaluation_workspace_available"]
    request.user = workspace["reviewers"][0]
    before = ev.EvaluationAssignment.objects.count()
    assert evaluation_navigation(request)["evaluation_workspace_available"]
    assert ev.EvaluationAssignment.objects.count() == before


def test_evaluation_navigation_missing_table_does_not_break_outer_transaction(workspace, monkeypatch):
    request = RequestFactory().get("/")
    request.user = workspace["reviewers"][0]

    def missing_table(_user):
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM asterproof_deliberately_missing_evaluation_navigation_table")

    monkeypatch.setattr(ev, "assignments", missing_table)
    with transaction.atomic():
        assert not evaluation_navigation(request)["evaluation_workspace_available"]
        assert EvaluationCase.objects.filter(pk=workspace["case"].pk).exists()


def test_case_form_preserves_explicit_learner_revision_consent_binding(workspace):
    from inspinia.solutions.evaluation_forms import CaseForm

    case = workspace["case"]
    data = {
        "statement": "A statement",
        "source": "A proof",
        "language": "English",
        "completeness": "present",
        "problem_integrity": "no_known_defect",
        "source_reference": "An authorized source",
        "rights": "Permission",
        "permitted_uses": ["benchmark"],
        "construction": "learner_submission",
        "consent_reference": "Consent record",
        "learner_id": workspace["reviewers"][0].pk,
        "source_revision_id": str(case.pk),
        "source_digest": case.bundle.digest,
        "retention_until": (timezone.now() + timedelta(days=90)).isoformat(),
    }
    form = CaseForm(data)
    assert form.is_valid(), form.errors
    payload = form.payload()["provenance"]
    assert payload["learner_id"] == data["learner_id"]
    assert payload["source_revision_id"] == data["source_revision_id"]
    assert payload["source_digest"] == data["source_digest"]


def test_http_finding_adjudication_preserves_originals_and_unblocks_report(client, workspace):
    custodian, _snapshot, _profile, run = make_run(workspace)
    case = workspace["case"]
    originals = []
    for useful in (True, False):
        evaluator = UserFactory(role="trainer", is_approved=True)
        ev.grant(workspace["admin"], evaluator, "finding_evaluator", case, expertise="Algebra")
        originals.append(
            ev.assess_findings(
                evaluator,
                run,
                case,
                {
                    "useful": useful,
                    "report_spoiler": False,
                    "abstention_appropriate": False,
                    "findings": [],
                },
            ),
        )
    original_payloads = {item.pk: item.payload for item in originals}
    adjudicator = UserFactory(role="trainer", is_approved=True)
    ev.grant(workspace["admin"], adjudicator, "adjudicator", case, expertise="Algebra")
    client.force_login(adjudicator)
    url = reverse("solutions:evaluation_finding_adjudication", args=[run.pk, case.pk])
    response = client.get(reverse("solutions:evaluation_case_detail", args=[case.pk]))
    assert url.encode() in response.content
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert b"Preserved report assessments" in response.content
    data = {
        "useful": "true",
        "report_spoiler": "false",
        "abstention_appropriate": "false",
        "findings-TOTAL_FORMS": "0",
        "findings-INITIAL_FORMS": "0",
    }
    response = client.post(url, data)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert EvaluationFindingJudgment.objects.filter(run=run, case=case).count() == len(originals)
    data["reason"] = "The report correctly identifies that the complete elementary proof has no defect."
    response = client.post(url, data)
    assert response.status_code == HTTPStatus.FOUND
    final = EvaluationFindingJudgment.objects.filter(run=run, case=case).exclude(pk__in=original_payloads).get()
    assert set(final.payload["_adjudicates"]) == {str(key) for key in original_payloads}
    assert final.payload["_reason"] == data["reason"]
    for original in originals:
        original.refresh_from_db()
        assert original.payload == original_payloads[original.pk]
    client.force_login(custodian)
    response = client.get(reverse("solutions:evaluation_run_detail", args=[run.pk]))
    assert response.status_code == HTTPStatus.OK
    assert b"Usable coverage" in response.content


def test_finding_adjudication_does_not_disclose_open_round_or_developer_content(client, workspace):
    _custodian, snapshot, _profile, run = make_run(workspace)
    case = workspace["case"]
    evaluator = UserFactory(role="trainer", is_approved=True)
    ev.grant(workspace["admin"], evaluator, "finding_evaluator", case, expertise="Algebra")
    original = ev.assess_findings(
        evaluator,
        run,
        case,
        {
            "useful": True,
            "report_spoiler": False,
            "findings": [],
        },
    )
    adjudicator = UserFactory(role="trainer", is_approved=True)
    ev.grant(workspace["admin"], adjudicator, "adjudicator", case, expertise="Algebra")
    url = reverse("solutions:evaluation_finding_adjudication", args=[run.pk, case.pk])
    client.force_login(adjudicator)
    response = client.get(url)
    assert response.status_code == HTTPStatus.CONFLICT
    assert str(original.pk).encode() not in response.content
    assert b"REPORT-SUMMARY" not in response.content
    developer = UserFactory(role="trainer", is_approved=True)
    ev.grant(workspace["admin"], developer, "developer", snapshot)
    client.force_login(developer)
    response = client.get(url)
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert b"REPORT-SUMMARY" not in response.content
