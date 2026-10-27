"""Assignment evidence, review safety, and cross-page acceptance contracts."""

import json
import uuid
from http import HTTPStatus
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from inspinia.pages.catalogue_snapshots import rebuild_library_snapshot
from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_registry import AssignmentRegistry
from inspinia.pages.concept_assignment_registry import RegistryError
from inspinia.pages.concept_assignment_registry import digest
from inspinia.pages.concept_assignment_service import AssignmentConflictError
from inspinia.pages.concept_assignment_service import accepted_problem_ids
from inspinia.pages.concept_assignment_service import activate_projection
from inspinia.pages.concept_assignment_service import apply_refresh
from inspinia.pages.concept_assignment_service import apply_review
from inspinia.pages.concept_assignment_service import audit_sources
from inspinia.pages.concept_assignment_service import preview_review
from inspinia.pages.concept_assignment_service import verify_seed
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.concept_assignment_trace import trace_source
from inspinia.pages.models import ConceptAssignmentReviewBatch
from inspinia.pages.models import ConceptAssignmentReviewEvent
from inspinia.pages.models import ConceptAssignmentState
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemConceptAssignment
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.statement_concept_coverage import statement_coverage_payloads
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def source_problem():
    problem = ProblemSolveRecord.objects.create(
        contest="ASSIGNMENT TEST",
        year=2026,
        problem="P2",
        topic="ALG",
        mohs=35,
    )
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name=problem.contest,
        contest_year=2026,
        problem_number=2,
        problem_code="P2",
        topic="A",
        statement_latex="Let x be real. Write floor(x) for the greatest integer not exceeding x.",
    )
    return problem, statement


def add_tag(statement, caption="AM-GM", **fields):
    return StatementTopicTechnique.objects.create(
        statement=statement,
        technique=caption,
        main_topic="ALG",
        domains=["ALG"],
        **fields,
    )


def sources_for(problem):
    return load_sources([problem.problem_uuid])


def seed(problem):
    report = audit_sources(sources_for(problem))
    return apply_refresh(report)


def confirm(problem, concept="floor-ceiling", **changes):
    decision = {
        "problem_uuid": str(problem.problem_uuid),
        "concept_id": concept,
        "action": "confirm",
        "roles": ["object"],
        "rationale": "The statement explicitly defines the floor function.",
        "evidence": {"kind": "statement", "quote": "greatest integer not exceeding x"},
    }
    decision.update(changes)
    return decision


def enable(settings):
    settings.CONCEPT_ASSIGNMENTS_ENABLED = True
    ConceptAssignmentState.objects.update_or_create(
        singleton_key=1,
        defaults={"enabled": True, "initial_seed_complete": True},
    )


def test_trace_holds_structured_specialists_and_retains_exact_fields(source_problem):
    problem, statement = source_problem
    add_tag(
        statement,
        "FLOOR / ROUNDING / APPROXIMATION",
        object_tags=["Farey fraction", "Beatty sequence", "FLOOR FUNCTION"],
        technique_tags=["ROUNDING"],
    )
    tag = StatementTopicTechnique.objects.get(statement=statement)
    tag.domains = ["ALG", "NT"]
    tag.save()
    trace = trace_source(sources_for(problem)[str(problem.problem_uuid)])
    candidates = {c["id"]: c for c in trace["candidates"]}
    assert {
        "nt-farey",
        "nt-beatty",
        "floor-ceiling",
        "nearest-integer",
        "nt-rounding",
    } <= candidates.keys()
    assert not any(c["auto_eligible"] for c in candidates.values())
    evidence = candidates["nt-farey"]["evidence"][0]
    assert evidence["field"] == "object_tags"
    assert evidence["source_row_id"] == tag.pk
    assert evidence["source_model"] == "StatementTopicTechnique"
    assert {"STRUCTURED_ONLY", "SPECIALIST_REVIEW", "CROSS_SUBJECT"} <= set(evidence["reasons"])
    assert not ProblemConceptAssignment.objects.exists()


def test_direct_tag_is_accepted_once_and_second_refresh_is_unchanged(source_problem):
    problem, statement = source_problem
    add_tag(statement, technique_tags=["AM-GM"], lemma_theorem_tags=["AM-GM"])
    result = seed(problem)
    assert result["assignments_changed"] == 1
    row = ProblemConceptAssignment.objects.get()
    assert row.disposition == "accepted"
    assert {e["field"] for e in row.evidence} == {"technique", "technique_tags", "lemma_theorem_tags"}
    again = audit_sources(sources_for(problem))
    assert again["changes"] == []
    assert apply_refresh(again)["assignments_changed"] == 0


@pytest.mark.parametrize("status", ["invalid", "corrupt", "metadata", "needs_review"])
def test_uncertain_sources_do_not_auto_accept(source_problem, status):
    problem, statement = source_problem
    add_tag(statement, normalization_status=status)
    candidates = trace_source(sources_for(problem)[str(problem.problem_uuid)])["candidates"]
    assert not any(c["auto_eligible"] for c in candidates)


def test_statement_sources_suppress_linked_fallback_even_when_invalid(source_problem):
    problem, statement = source_problem
    ProblemTopicTechnique.objects.create(record=problem, technique="AM-GM", main_topic="ALG", domains=["ALG"])
    add_tag(statement, "BAD DATA", normalization_status="invalid")
    source = sources_for(problem)[str(problem.problem_uuid)]
    assert source["effective_source"] == "statement"
    assert trace_source(source)["candidates"] == []


def test_approved_shared_merge_preserves_memberships_and_context():
    manifest = {
        "approved_merges": [
            {
                "sources": ["nt-floor-ceiling"],
                "target": "floor-ceiling",
                "reviewed_by": "test reviewer",
                "reason": "Equivalent mathematical family.",
                "evidence": "Both definitions retain floor and ceiling functions.",
            },
        ],
        "proposals": [],
    }
    registry = AssignmentRegistry(manifest=manifest)
    assert registry.canonical("nt-floor-ceiling") == "floor-ceiling"
    assert registry.definitions["floor-ceiling"]["subjects"] == ["Algebra", "Number Theory"]
    assert (
        registry.presentation("nt-floor-ceiling", "Algebra")["area"]
        == "Discrete functions, rounding, and finite dynamics"
    )
    assert (
        registry.presentation("floor-ceiling", "Number Theory")["area"]
        == "Rational approximation, floors, and fractional parts"
    )
    assert registry.resolve("Number Theory", "object", "floor function", {})["ids"] == ["floor-ceiling"]


def test_registry_rejects_unreviewed_merge_and_cycles():
    with pytest.raises(RegistryError):
        AssignmentRegistry(
            manifest={"approved_merges": [{"sources": ["nt-floor-ceiling"], "target": "floor-ceiling"}]},
        )
    evidence = {"reviewed_by": "reviewer", "reason": "test", "evidence": "test"}
    with pytest.raises(RegistryError, match="cycle"):
        AssignmentRegistry(
            manifest={
                "approved_merges": [
                    {**evidence, "sources": ["nt-floor-ceiling"], "target": "floor-ceiling"},
                    {**evidence, "sources": ["floor-ceiling"], "target": "nt-floor-ceiling"},
                ],
            },
        )


def test_review_preview_is_read_only_and_apply_is_idempotent(source_problem):
    problem, statement = source_problem
    add_tag(statement, "FLOOR / ROUNDING / APPROXIMATION", object_tags=["FLOOR FUNCTION"])
    admin = UserFactory(role="admin")
    report = preview_review([confirm(problem)])
    assert not ProblemConceptAssignment.objects.exists()
    assert not ConceptAssignmentReviewBatch.objects.exists()
    assert report["changes"][0]["after"]["evidence"][-1]["kind"] == "statement"
    assert any(d["dimension"] == "concept" and d["delta"] == 1 for d in report["count_deltas"])
    receipt = apply_review(report, admin)
    assert receipt == apply_review(report, admin)
    assert ConceptAssignmentReviewEvent.objects.count() == 1
    assert StatementTopicTechnique.objects.get().technique == "FLOOR / ROUNDING / APPROXIMATION"


def test_stale_preview_is_rejected_without_partial_writes(source_problem):
    problem, statement = source_problem
    admin = UserFactory(role="admin")
    report = preview_review([confirm(problem)])
    statement.statement_latex = "A different mathematical statement."
    statement.save()
    with pytest.raises(AssignmentConflictError):
        apply_review(report, admin)
    assert not ConceptAssignmentReviewBatch.objects.exists()
    assert not ProblemConceptAssignment.objects.exists()


def test_rejected_concept_stays_rejected_after_rebuild(source_problem):
    problem, statement = source_problem
    add_tag(statement)
    seed(problem)
    admin = UserFactory(role="admin")
    decision = confirm(problem, "am-gm", action="reject", rationale="This tag does not describe the problem.")
    apply_review(preview_review([decision]), admin)
    assert audit_sources(sources_for(problem))["changes"] == []
    assert ProblemConceptAssignment.objects.get().disposition == "rejected"


def test_human_statement_evidence_becomes_stale_and_does_not_resurrect(source_problem, settings):
    problem, statement = source_problem
    admin = UserFactory(role="admin")
    apply_review(preview_review([confirm(problem)]), admin)
    enable(settings)
    assert len(statement_coverage_payloads([statement])[statement.pk]["concept_coverage"]) == 1
    statement.statement_latex = "The statement no longer defines a floor function."
    statement.save()
    coverage = statement_coverage_payloads([statement])[statement.pk]
    assert coverage["concept_coverage"] == []
    assert "EVIDENCE_CHANGED" in coverage["concept_suggestions"][0]["reasons"]
    apply_refresh(audit_sources(sources_for(problem)))
    assert ProblemConceptAssignment.objects.get().is_stale


def test_changed_source_array_order_does_not_invalidate_fingerprint(source_problem):
    problem, statement = source_problem
    tag = add_tag(statement, object_tags=["A", "B"])
    first = sources_for(problem)[str(problem.problem_uuid)]["source_fingerprint"]
    tag.object_tags = ["B", "A"]
    tag.save()
    assert sources_for(problem)[str(problem.problem_uuid)]["source_fingerprint"] == first


def test_missing_and_private_solution_evidence_is_rejected(source_problem):
    from inspinia.solutions.models import ProblemSolution

    problem, _ = source_problem
    user = UserFactory()
    draft = ProblemSolution.objects.create(problem=problem, author=user)
    with pytest.raises(AssignmentConflictError, match="published solution"):
        preview_review(
            [confirm(problem, evidence={"kind": "published_solution", "reference": draft.pk, "quote": "a proof"})],
        )
    with pytest.raises(AssignmentConflictError, match="supporting excerpt"):
        preview_review([confirm(problem, evidence={"kind": "statement", "quote": ""})])


def test_withdrawn_solution_evidence_is_not_exposed_in_public_projection(source_problem, settings):
    from inspinia.solutions.models import ProblemSolution
    from inspinia.solutions.models import ProblemSolutionBlock
    from inspinia.solutions.models import SolutionBlockType

    problem, statement = source_problem
    admin = UserFactory(role="admin")
    solution = ProblemSolution.objects.create(problem=problem, author=admin, status="published")
    ProblemSolutionBlock.objects.create(
        solution=solution,
        block_type=SolutionBlockType.objects.get(slug="proof"),
        position=1,
        body_source="Private after withdrawal: floor functions give the bound.",
    )
    apply_review(
        preview_review(
            [
                confirm(
                    problem,
                    evidence={
                        "kind": "published_solution",
                        "reference": solution.pk,
                        "quote": "floor functions give the bound",
                    },
                ),
            ],
        ),
        admin,
    )
    enable(settings)
    assert statement_coverage_payloads([statement])[statement.pk]["concept_coverage"]
    solution.status = "draft"
    solution.save()
    payload = statement_coverage_payloads([statement])[statement.pk]
    assert payload["concept_coverage"] == []
    assert "Private after withdrawal" not in json.dumps(payload)


def test_feature_disabled_preserves_legacy_payload_without_new_state_reads(source_problem):
    _, statement = source_problem
    add_tag(statement)
    payload = statement_coverage_payloads([statement])[statement.pk]
    assert "assignment_projection" not in payload
    assert payload["concept_coverage"][0]["id"] == "am-gm"


def test_library_progress_and_filter_share_accepted_membership(source_problem, settings):
    from inspinia.pages.concept_analytics import build_concept_analytics_context
    from inspinia.pages.concept_progress import build_concept_progress_context
    from inspinia.pages.views import _completion_quick_update_apply_layer_filter

    problem, statement = source_problem
    add_tag(statement)
    add_tag(statement, "FLOOR / ROUNDING / APPROXIMATION", object_tags=["FLOOR FUNCTION"])
    seed(problem)
    enable(settings)
    user = UserFactory()
    payload = statement_coverage_payloads([statement])[statement.pk]
    assert [c["id"] for c in payload["concept_coverage"]] == ["am-gm"]
    assert accepted_problem_ids("am-gm") == [str(problem.problem_uuid)]
    assert accepted_problem_ids("floor-ceiling") == []
    result = _completion_quick_update_apply_layer_filter(
        ContestProblemStatement.objects.all(),
        raw_kind="concepts",
        raw_tag="am-gm",
    )
    assert list(result.values_list("id", flat=True)) == [statement.pk]
    analytics = build_concept_analytics_context({"concept": "am-gm"})
    assert analytics["selected_concept"]["problem_count"] == 1
    rebuild_library_snapshot()  # Scheduled publication precedes progress reads.
    progress = build_concept_progress_context(request_user=user, params={"concept": "am-gm", "mode": "problems"})
    assert progress["selected_summary"]["total"] == 1
    assert len(progress["progress_page"]) == 1
    exported = build_concept_progress_context(
        request_user=user, params={"concept": "am-gm", "mode": "problems", "export": "csv"},
    )
    assert len(list(exported["export_rows"])) == 1


def test_seed_activation_requires_complete_current_evidence(source_problem, settings):
    problem, statement = source_problem
    add_tag(statement)
    settings.CONCEPT_ASSIGNMENTS_ENABLED = True
    with pytest.raises(AssignmentConflictError, match="complete seed"):
        activate_projection(digest(verify_seed()))
    seed(problem)
    verification = verify_seed()
    activate_projection(digest(verification), operation_id=uuid.uuid4())
    state = ConceptAssignmentState.objects.get()
    assert state.enabled
    assert state.initial_seed_complete


@pytest.mark.parametrize(
    "route",
    ["concept_assignment_review", "concept_assignment_preview", "concept_assignment_apply"],
)
def test_review_routes_deny_non_admin_even_in_debug(client, route):
    client.force_login(UserFactory())
    with override_settings(DEBUG=True):
        response = (
            client.get(reverse("pages:" + route))
            if route == "concept_assignment_review"
            else client.post(reverse("pages:" + route))
        )
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_admin_html_and_signed_preview_apply_flow(client, source_problem):
    problem, _ = source_problem
    admin = UserFactory(role="admin")
    client.force_login(admin)
    detail = client.get(reverse("pages:concept_assignment_detail", args=[problem.problem_uuid]))
    assert detail.status_code == HTTPStatus.OK
    assert "Private drafts are excluded" in detail.content.decode()
    preview = client.post(
        reverse("pages:concept_assignment_preview"),
        data=json.dumps({"decisions": [confirm(problem)]}),
        content_type="application/json",
        HTTP_ACCEPT="application/json",
    )
    assert preview.status_code == HTTPStatus.OK
    result = preview.json()
    assert not ProblemConceptAssignment.objects.exists()
    response = client.post(
        reverse("pages:concept_assignment_apply"),
        {"token": result["token"]},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["assignments_changed"] == 1
    assert (
        client.get(reverse("pages:concept_assignment_receipt", args=[result["report"]["operation_id"]])).status_code
        == HTTPStatus.OK
    )
    assert (
        client.post(
            reverse("pages:concept_assignment_apply"),
            {"token": result["token"]},
            HTTP_ACCEPT="application/json",
        ).json()
        == response.json()
    )
    assert (
        client.post(reverse("pages:concept_assignment_apply"), {"token": result["token"] + "tampered"}).status_code
        == HTTPStatus.CONFLICT
    )


def test_audit_command_is_read_only_and_exports_formula_safe_csv(source_problem, tmp_path):
    from inspinia.pages.concept_assignment_views import report_csv

    problem, statement = source_problem
    add_tag(statement)
    output = StringIO()
    directory = tmp_path / "audit"
    call_command(
        "audit_concept_assignments",
        problem_uuid=[str(problem.problem_uuid)],
        output_directory=directory,
        stdout=output,
    )
    assert json.loads(output.getvalue())["source_writes"] == 0
    assert not ProblemConceptAssignment.objects.exists()
    report = json.loads((directory / "batch-00001.json").read_text())
    report["traces"][0]["label"] = "=1+1"
    assert "'=1+1" in report_csv(report)


@pytest.mark.parametrize(
    ("topic", "subject", "caption", "expected"),
    [
        ("A", "ALG", "AM-GM", "am-gm"),
        ("N", "NT", "Divisibility", "nt-divisibility"),
        ("G", "GEO", "Angle chasing", "geo-angle-chasing"),
        ("C", "COMB", "PIGEONHOLE PRINCIPLE", "pigeonhole"),
    ],
)
def test_direct_acceptance_in_all_four_subjects(source_problem, topic, subject, caption, expected):
    problem, statement = source_problem
    statement.topic = topic
    statement.save()
    StatementTopicTechnique.objects.create(
        statement=statement,
        technique=caption,
        main_topic=subject,
        domains=[subject],
    )
    seed(problem)
    assert ProblemConceptAssignment.objects.get(disposition="accepted").concept_id == expected


def test_shared_concept_counts_once_and_uses_each_problems_context():
    from inspinia.pages.concept_assignment_progress import assignment_catalogue_rows
    from inspinia.pages.concept_progress import _counts

    library = {}
    for subject in ("Algebra", "Number Theory"):
        library[subject] = {
            "is_solved": False,
            "mohs": 20,
            "concept_coverage": [REGISTRY.presentation("nt-floor-ceiling", subject, ["object"])],
        }
    concepts, areas, subjects, _ = assignment_catalogue_rows(
        library,
        _counts,
        ["Algebra", "Number Theory", "Geometry", "Combinatorics"],
    )
    assert next(c for c in concepts if c["id"] == "floor-ceiling")["total"] == len(library)
    assert not any(c["id"] == "nt-floor-ceiling" for c in concepts)
    assert len(subjects["Algebra"]) == len(subjects["Number Theory"]) == 1
    assert sum(a["total"] for a in areas if a["id"] in {"Algebra:discrete", "Number Theory:approximation"}) == len(
        library,
    )


def test_identity_normalization_archives_duplicates_and_preserves_reviewers(source_problem):
    problem, _ = source_problem
    admin = UserFactory(role="admin")
    report = preview_review([confirm(problem)])
    apply_review(report, admin)
    old_registry = AssignmentRegistry(manifest={"approved_merges": [], "proposals": []})
    row = ProblemConceptAssignment.objects.get()
    row.concept_signature = old_registry.signature("floor-ceiling")
    row.save()
    other = ProblemConceptAssignment.objects.create(
        problem_uuid=problem.problem_uuid,
        concept_id="nt-floor-ceiling",
        disposition="accepted",
        decision_origin="reviewed",
        roles=["method"],
        subject_context="Number Theory",
        evidence=row.evidence,
        source_fingerprint=row.source_fingerprint,
        concept_signature=old_registry.signature("nt-floor-ceiling"),
        reviewed_by=admin,
    )
    audit = audit_sources(sources_for(problem))
    assert not audit["conflicts"]
    assert any(c.get("action") == "retire_identity" for c in audit["changes"])
    apply_refresh(audit)
    assert ProblemConceptAssignment.objects.filter(is_current=True).count() == 1
    other.refresh_from_db()
    assert not other.is_current
    row.refresh_from_db()
    assert row.roles == ["method", "object"]
    assert row.reviewed_by_id == admin.pk
    assert audit_sources(sources_for(problem))["changes"] == []


def test_conflicting_identity_reviews_need_explicit_human_resolution(source_problem):
    problem, _ = source_problem
    admin = UserFactory(role="admin")
    apply_review(preview_review([confirm(problem)]), admin)
    row = ProblemConceptAssignment.objects.get()
    ProblemConceptAssignment.objects.create(
        problem_uuid=problem.problem_uuid,
        concept_id="nt-floor-ceiling",
        disposition="rejected",
        decision_origin="reviewed",
        roles=[],
        evidence=[],
        source_fingerprint=row.source_fingerprint,
        concept_signature=REGISTRY.signature("floor-ceiling"),
        reviewed_by=admin,
    )
    report = audit_sources(sources_for(problem))
    assert any(c["reason"] == "CONFLICTING_REVIEW_DECISIONS" for c in report["conflicts"])
    with pytest.raises(AssignmentConflictError):
        apply_refresh(report)
    preview = preview_review([confirm(problem)])
    assert any(c.get("action") == "retire_identity" for c in preview["changes"])
    apply_review(preview, admin)
    assert ProblemConceptAssignment.objects.filter(is_current=True).count() == 1


def test_normalization_only_change_does_not_remove_supported_coverage(source_problem, settings):
    problem, statement = source_problem
    tag = add_tag(statement, object_tags=["A", "B"])
    seed(problem)
    enable(settings)
    tag.object_tags = ["B", "A"]
    tag.save()
    assert statement_coverage_payloads([statement])[statement.pk]["concept_coverage"]


def test_review_maximum_and_duplicate_actions_fail_before_writes(source_problem):
    problem, _ = source_problem
    decision = confirm(problem)
    with pytest.raises(AssignmentConflictError):
        preview_review([decision] * 251)
    with pytest.raises(AssignmentConflictError):
        preview_review([decision, decision])
    assert not ConceptAssignmentReviewBatch.objects.exists()


def test_review_endpoints_require_csrf_even_for_admin(source_problem):
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    client.force_login(UserFactory(role="admin"))
    for name in ("concept_assignment_preview", "concept_assignment_apply"):
        assert client.post(reverse("pages:" + name), {}).status_code == HTTPStatus.FORBIDDEN


def test_active_library_filter_and_legacy_gap_url_use_accepted_projection(client, source_problem, settings):
    problem, statement = source_problem
    add_tag(statement)
    add_tag(statement, "GENERIC FLOOR", object_tags=["FLOOR FUNCTION"])
    seed(problem)
    enable(settings)
    client.force_login(UserFactory())
    yes = client.get(reverse("pages:problem_statement_list"), {"concept": "am-gm"})
    no = client.get(reverse("pages:problem_statement_list"), {"concept": "floor-ceiling"})
    assert yes.context["statement_filtered_total"] == 1
    assert no.context["statement_filtered_total"] == 0
    rebuild_library_snapshot()  # Scheduled publication precedes progress reads.
    gaps = client.get(reverse("pages:technique_progress_gaps"), {"format": "datatable"}).json()
    assert any(row["id"] == "am-gm" for row in gaps["data"])
    assert not any(row["id"] == "floor-ceiling" for row in gaps["data"])


def test_projection_query_count_does_not_grow_per_statement(source_problem, settings):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _, statement = source_problem
    enable(settings)
    with CaptureQueriesContext(connection) as small:
        statement_coverage_payloads([statement])
    rows = [statement]
    rows.extend(
        ContestProblemStatement.objects.create(
            contest_name="BATCH",
            contest_year=2026,
            problem_number=index + 1,
            problem_code=f"P{index + 1}",
            topic="A",
            statement_latex="Prove.",
        )
        for index in range(6)
    )
    with CaptureQueriesContext(connection) as large:
        statement_coverage_payloads(rows)
    assert len(large) <= len(small) + 1


def test_registry_keeps_alias_collisions_ambiguous():
    definitions = {
        key: {
            "concept_id": key,
            "subject": "Algebra",
            "area": "unit",
            "area_label": "Unit",
            "label": key,
            "aliases": [["technique", "UNIT COLLISION"]],
        }
        for key in ("first", "second")
    }
    registry = AssignmentRegistry(definitions=definitions, manifest={"approved_merges": [], "proposals": []})
    assert registry.resolve("Algebra", "technique", "UNIT COLLISION", {})["ids"] == ["first", "second"]


def test_unmapped_queue_finds_problem_by_uuid_after_other_rows_seeded(client, source_problem):
    problem, statement = source_problem
    add_tag(statement)
    seed(problem)
    other = ContestProblemStatement.objects.create(
        contest_name="UNMAPPED",
        contest_year=2026,
        problem_code="A9",
        problem_number=9,
        topic="A",
        statement_latex="Determine x.",
    )
    admin = UserFactory(is_superuser=True)
    client.force_login(admin)
    response = client.get(
        reverse("pages:concept_assignment_review"),
        {"state": "unmapped", "q": str(other.problem_uuid)},
    )
    assert response.status_code == HTTPStatus.OK
    assert [r["problem_uuid"] for r in response.context["rows"]] == [str(other.problem_uuid)]
    assert "No mapped concepts" in response.content.decode()


def test_review_hold_and_replacement_preserve_the_source(source_problem):
    problem, statement = source_problem
    tag = add_tag(statement)
    admin = UserFactory(is_superuser=True)
    seed(problem)
    hold = preview_review([confirm(problem, "am-gm", action="hold")])
    apply_review(hold, admin)
    assert ProblemConceptAssignment.objects.get(concept_id="am-gm").disposition == "suggested"
    assert audit_sources(sources_for(problem))["changes"] == []
    replacement = preview_review([confirm(problem, "am-gm", action="replace", replacement_concept_id="floor-ceiling")])
    apply_review(replacement, admin)
    assert ProblemConceptAssignment.objects.get(concept_id="am-gm").disposition == "rejected"
    assert ProblemConceptAssignment.objects.get(concept_id="floor-ceiling").disposition == "accepted"
    assert StatementTopicTechnique.objects.get(pk=tag.pk).technique == "AM-GM"
    assert audit_sources(sources_for(problem))["changes"] == []


def test_library_export_separates_accepted_suggestions_and_basis(source_problem, settings):
    from inspinia.pages.views import _statement_table_rows_copy_tsv

    problem, statement = source_problem
    add_tag(statement)
    add_tag(statement, "GENERIC FLOOR", object_tags=["FLOOR FUNCTION"])
    seed(problem)
    enable(settings)
    payload = statement_coverage_payloads([statement])[statement.pk]
    text = _statement_table_rows_copy_tsv([payload])
    header, row = (line.split("\t") for line in text.splitlines())
    values = dict(zip(header, row, strict=True))
    assert "AM" in values["Coverage"]
    assert "Floor" not in values["Coverage"]
    assert "Floor" in values["Suggestions (not counted)"]
    assert "Exact legacy tag" in values["Acceptance basis"]


def test_review_operation_id_cannot_be_reused_for_different_decisions(source_problem):
    problem, _ = source_problem
    admin = UserFactory(is_superuser=True)
    report = preview_review([confirm(problem)])
    apply_review(report, admin)
    changed = preview_review([confirm(problem, action="reject")], operation_id=report["operation_id"])
    with pytest.raises(AssignmentConflictError, match="different review"):
        apply_review(changed, admin)


def test_shared_concept_does_not_inherit_another_concepts_area():
    from inspinia.pages.concept_assignment_progress import assignment_catalogue_rows
    from inspinia.pages.concept_progress import _counts

    library = {
        "one": {
            "is_solved": False,
            "mohs": 20,
            "concept_coverage": [
                REGISTRY.presentation("floor-ceiling", "Algebra"),
                REGISTRY.presentation("nt-farey", "Number Theory"),
            ],
        },
    }
    _, areas, _, _ = assignment_catalogue_rows(library, _counts, ["Algebra", "Number Theory"])
    area = next(a for a in areas if a["id"] == "Number Theory:approximation")
    assert area["available"] == 1


def test_invalid_progress_area_restores_supported_scope(source_problem, settings):
    from inspinia.pages.concept_progress import build_concept_progress_context

    problem, statement = source_problem
    add_tag(statement)
    seed(problem)
    enable(settings)
    rebuild_library_snapshot()  # Scheduled publication precedes progress reads.
    context = build_concept_progress_context(
        request_user=UserFactory(),
        params={"area": "invalid", "mode": "concepts"},
        topic_slug="algebra",
    )
    assert context["filters"]["area"] == ""
    assert any(row["id"] == "am-gm" for row in context["export_rows"])


def test_identity_merge_cannot_revalidate_an_unrecognized_definition(source_problem, settings):
    problem, _ = source_problem
    admin = UserFactory(is_superuser=True)
    apply_review(preview_review([confirm(problem)]), admin)
    ProblemConceptAssignment.objects.filter(problem_uuid=problem.problem_uuid).update(
        concept_id="nt-floor-ceiling",
        concept_signature="unrecognized-definition",
    )
    apply_refresh(audit_sources(sources_for(problem)))
    row = ProblemConceptAssignment.objects.get(concept_id="floor-ceiling")
    assert row.is_stale
    enable(settings)
    payload = statement_coverage_payloads([source_problem[1]])[source_problem[1].pk]
    assert payload["concept_coverage"] == []
    assert "EVIDENCE_CHANGED" in payload["concept_suggestions"][0]["reasons"]


def test_delegated_agent_review_preserves_origin_and_avoids_false_human_label(source_problem, settings):
    problem, statement = source_problem
    admin = UserFactory(is_superuser=True)
    decision = confirm(problem, rationale="Codex review delegated by the user: the statement defines floor.")
    decision["review_metadata"] = {
        "origin": "agent_assisted",
        "reviewer": "Codex",
        "statement_sha256": digest(statement.statement_latex),
        "source_statement_uuid": str(statement.statement_uuid),
    }
    report = preview_review([decision])
    apply_review(report, admin)
    batch = ConceptAssignmentReviewBatch.objects.get(operation_id=report["operation_id"])
    assert batch.manifest["decisions"][0]["review_metadata"] == decision["review_metadata"]
    assert batch.actor_id == admin.pk
    enable(settings)
    payload = statement_coverage_payloads([statement])[statement.pk]
    assert payload["concept_coverage"][0]["support_basis"] == "Evidence reviewed"


def test_reviewed_area_context_is_shared_by_library_analytics_and_progress(source_problem, settings):
    from inspinia.pages.concept_analytics import build_concept_analytics_context
    from inspinia.pages.concept_progress import build_concept_progress_context

    problem, statement = source_problem
    statement.statement_latex = "For a positive real a, prove a^2 >= 0 by considering its sign."
    statement.save()
    decision = confirm(
        problem,
        "sign-analysis",
        roles=["method"],
        area_context="Algebra:inequalities",
        evidence={"kind": "statement", "quote": "positive real a"},
        rationale="Positivity analysis is used in this inequality.",
    )
    report = preview_review([decision])
    apply_review(report, UserFactory(is_superuser=True))
    enable(settings)
    coverage = statement_coverage_payloads([statement])[statement.pk]
    assert coverage["concept_coverage"][0]["area_id"] == "inequalities"
    assert coverage["concept_areas"] == ["Inequalities and optimization"]
    assert REGISTRY.definitions["sign-analysis"]["area"] == "equations"
    analytics = build_concept_analytics_context(
        {"subject": "Algebra", "area": "Algebra:inequalities", "concept": "sign-analysis"},
    )
    assert analytics["selected_concept"]["problem_count"] == 1
    rebuild_library_snapshot()  # Scheduled publication precedes progress reads.
    progress = build_concept_progress_context(
        request_user=UserFactory(),
        params={"area": "Algebra:inequalities", "concept": "sign-analysis", "mode": "problems"},
        topic_slug="algebra",
    )
    assert progress["selected_summary"]["total"] == 1
    assert str(problem.problem_uuid) in accepted_problem_ids("sign-analysis")


@pytest.mark.parametrize("area", ["Algebra:missing", "Geometry:Discrete geometry and constructions"])
def test_review_area_context_rejects_unknown_or_wrong_subject(source_problem, area):
    problem, _ = source_problem
    with pytest.raises(AssignmentConflictError, match="reviewed area"):
        preview_review([confirm(problem, area_context=area)])


def test_area_and_explicit_subject_context_must_agree(source_problem):
    problem, _ = source_problem
    with pytest.raises(AssignmentConflictError, match="contexts disagree"):
        preview_review([confirm(problem, subject_context="Number Theory", area_context="Algebra:inequalities")])


def test_agent_review_rejects_changed_full_statement_even_when_excerpt_survives(source_problem):
    problem, statement = source_problem
    decision = confirm(problem)
    decision["review_metadata"] = {"origin": "agent_assisted", "statement_sha256": digest(statement.statement_latex)}
    statement.statement_latex += " A condition elsewhere has changed."
    statement.save()
    with pytest.raises(AssignmentConflictError, match="reviewed statement changed"):
        preview_review([decision])


def test_agent_review_requires_full_statement_hash(source_problem):
    problem, _ = source_problem
    decision = confirm(problem)
    decision["review_metadata"] = {"origin": "agent_assisted"}
    with pytest.raises(AssignmentConflictError, match="full statement hash"):
        preview_review([decision])


def test_all_reviewed_shared_ids_redirect_and_seven_scope_groups_stay_separate():
    assert REGISTRY.canonical("comb-am-gm") == "am-gm"
    assert REGISTRY.canonical("comb-cauchy-schwarz") == "cauchy-schwarz"
    assert REGISTRY.canonical("comb-ham-sandwich") == "geo-ham-sandwich"
    assert REGISTRY.canonical("nt-factorization") == "factorization"
    assert REGISTRY.canonical("nt-prime-factorization") != "factorization"
    assert REGISTRY.canonical("comb-generating-functions") != "generating-functions"
    assert REGISTRY.canonical("comb-log-concavity") != "log-concavity"
    assert REGISTRY.canonical("nt-rounding") != "nearest-integer"
    assert len(REGISTRY.definitions) == 1109  # noqa: PLR2004 - reviewed frozen identity count


def test_snapshot_preview_is_identical_to_live_preview_without_database_queries(
    source_problem,
    django_assert_num_queries,
):
    from inspinia.pages.concept_assignment_service import build_review_preview

    problem, _ = source_problem
    decision = confirm(problem, area_context="Algebra:inequalities")
    expected = preview_review([decision])
    sources = sources_for(problem)
    with django_assert_num_queries(0):
        replay = build_review_preview([decision], sources=sources, operation_id=expected["operation_id"])
    assert replay == expected


def test_conflicting_explicit_area_reviews_are_held_during_identity_merge(source_problem):
    from inspinia.pages.concept_assignment_service import project_source

    problem, _ = source_problem
    admin = UserFactory(is_superuser=True)
    apply_review(preview_review([confirm(problem, area_context="Algebra:discrete")]), admin)
    row = ProblemConceptAssignment.objects.get()
    ProblemConceptAssignment.objects.create(
        problem_uuid=problem.problem_uuid,
        concept_id="nt-floor-ceiling",
        disposition="accepted",
        decision_origin="reviewed",
        roles=["object"],
        area_context="Algebra:inequalities",
        evidence=row.evidence,
        source_fingerprint=row.source_fingerprint,
        concept_signature=REGISTRY.signature("floor-ceiling"),
    )
    sources = sources_for(problem)
    audit = audit_sources(sources)
    assert audit["conflicts"][0]["reason"] == "CONFLICTING_REVIEW_CONTEXTS"
    assert not audit["changes"]
    coverage = project_source(sources[str(problem.problem_uuid)], list(ProblemConceptAssignment.objects.all()))
    assert coverage["concept_coverage"] == []
    assert "CONFLICTING_REVIEW_CONTEXTS" in coverage["concept_suggestions"][0]["reasons"]


def test_inactive_archive_owner_does_not_seed_an_active_statements_tags(source_problem):
    problem, _ = source_problem
    ProblemTopicTechnique.objects.create(record=problem, technique="AM-GM", main_topic="ALG", domains=["ALG"])
    problem.is_active = False
    problem.save()
    sources = sources_for(problem)
    trace = trace_source(sources[str(problem.problem_uuid)])
    assert trace["candidates"] == []
    assert trace["excluded"][0]["reason"] == "INACTIVE"
    assert audit_sources(sources)["changes"] == []


@pytest.mark.parametrize("action", ["confirm", "reject", "hold"])
def test_review_statement_uuid_guard_applies_to_every_decision(source_problem, action):
    problem, statement = source_problem
    decision = confirm(problem, action=action)
    decision["review_metadata"] = {
        "origin": "agent_assisted",
        "statement_sha256": digest(statement.statement_latex),
        "source_statement_uuid": str(uuid.uuid4()),
    }
    with pytest.raises(AssignmentConflictError, match="identity changed"):
        preview_review([decision])


def test_problem_area_override_does_not_move_another_problem(source_problem, settings):
    from inspinia.pages.concept_analytics import build_concept_analytics_context

    first, statement = source_problem
    statement.statement_latex = "Prove x^2 >= 0 by sign analysis."
    statement.save()
    second = ProblemSolveRecord.objects.create(contest="OTHER AREA", year=2026, problem="P1", topic="ALG", mohs=35)
    other = ContestProblemStatement.objects.create(
        linked_problem=second,
        contest_name="OTHER AREA",
        contest_year=2026,
        problem_code="P1",
        problem_number=1,
        topic="A",
        statement_latex="Solve f(x) = 0 by considering its sign.",
    )
    decisions = [
        confirm(
            first,
            "sign-analysis",
            roles=["method"],
            area_context="Algebra:inequalities",
            evidence={"kind": "statement", "quote": "by sign analysis"},
        ),
        confirm(
            second, "sign-analysis", roles=["method"], evidence={"kind": "statement", "quote": "considering its sign"},
        ),
    ]
    apply_review(preview_review(decisions), UserFactory(is_superuser=True))
    enable(settings)
    payloads = statement_coverage_payloads([statement, other])
    assert payloads[statement.pk]["concept_coverage"][0]["area_id"] == "inequalities"
    assert payloads[other.pk]["concept_coverage"][0]["area_id"] == "equations"
    for area in ("inequalities", "equations"):
        context = build_concept_analytics_context(
            {"subject": "Algebra", "area": "Algebra:" + area, "concept": "sign-analysis"},
        )
        assert context["selected_concept"]["problem_count"] == 1
