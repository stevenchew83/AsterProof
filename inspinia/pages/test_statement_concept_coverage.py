"""Canonical library coverage, source precedence and single-line table contracts."""

import csv
import io
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueProgressFact
from inspinia.pages.statement_concept_coverage import statement_concept_search
from inspinia.pages.statement_concept_coverage import statement_coverage_payloads
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def statement(number, *, topic="A", linked=None, active=True):
    return ContestProblemStatement.objects.create(
        contest_name="COVERAGE TEST",
        contest_year=2026,
        problem_number=number,
        problem_code=f"P{number}",
        statement_latex="Find x.",
        topic=topic,
        linked_problem=linked,
        is_active=active,
    )


def tag(  # noqa: PLR0913 -- explicit source-tag dimensions
    parent,
    *,
    caption="AM-GM",
    methods=(),
    objects=(),
    lemmas=(),
    topic="ALG",
    family="",
    status="",
):
    model, relation = (
        (StatementTopicTechnique, "statement")
        if isinstance(parent, ContestProblemStatement)
        else (
            ProblemTopicTechnique,
            "record",
        )
    )
    return model.objects.create(
        **{
            relation: parent,
            "technique": caption,
            "main_topic": topic,
            "domains": [topic] if topic else [],
            "canonical_subtopic": family,
            "technique_tags": list(methods),
            "object_tags": list(objects),
            "lemma_theorem_tags": list(lemmas),
            "normalization_status": status,
        },
    )


def canonical_matches(text):
    return set(ContestProblemStatement.objects.filter(statement_concept_search(text)).values_list("pk", flat=True))


def test_roles_merge_into_one_concept_and_full_coverage_survives_export(client):
    client.force_login(UserFactory())
    row = statement(1)
    tag(row, methods=["AM-GM"], lemmas=["AM-GM"])
    tag(row, caption="VIETA", lemmas=["VIETA"])
    tag(row, caption="FACTORIZATION")
    tag(row, caption="COMPLETING SQUARE")
    response = client.get(reverse("pages:problem_statement_list"))
    assert response.status_code == HTTPStatus.OK
    payload = response.context["statement_datatable_rows"][0]
    coverage = payload["concept_coverage"]
    assert {c["id"] for c in coverage} == {"am-gm", "vieta", "factorization", "completing-square"}
    amgm = next(c for c in coverage if c["id"] == "am-gm")
    assert amgm["roles"] == ["lemma", "method", "technique"]
    assert payload["concept_areas"] == ["Inequalities and optimization", "Polynomials and algebraic manipulation"]
    assert payload["concept_coverage_status"] == "Mapped"
    exported = next(csv.DictReader(io.StringIO(response.context["statement_copy_tsv"]), delimiter="\t"))
    for concept in coverage:
        assert concept["display"] in exported["Coverage"]
    assert exported["Area"] == ", ".join(payload["concept_areas"])
    assert exported["Original tags"] == ", ".join(payload["concept_source_tags"])
    assert not TechniqueProgressFact.objects.exists()
    html = response.content.decode()
    assert "<th>Area</th>" in html
    assert ">Coverage</th>" in html
    assert 'order: [[7, "desc"]]' in html
    assert "statement-taxonomy-modal" in html
    assert "statement-signal-stack" not in html
    assert "flex-column flex-xl-row" not in html


def test_priority_context_is_same_source_and_independent_support_survives():
    good, beta, neighbor, rank, held = [statement(n) for n in range(1, 6)]
    tag(
        good,
        caption="ALG-POLYNOMIAL SUMS; SYMMETRY; EXPANSION",
        methods=["EXPANSION"],
        objects=["POLYNOMIAL SUMS"],
        family="Polynomials and algebraic manipulation",
    )
    tag(beta, caption="BETA-EXPANSION", methods=["EXPANSION"], family="Analytic estimates and asymptotics")
    tag(
        neighbor,
        caption="ALG-POLYNOMIAL SUMS; SYMMETRY; EXPANSION",
        methods=["EXPANSION"],
        family="Polynomials and algebraic manipulation",
    )
    tag(neighbor, caption="OTHER SOURCE", objects=["POLYNOMIAL SUMS"])
    tag(
        rank,
        caption="MINIMAL-RANK IDEMPOTENT",
        methods=["RANK", "MATRIX FACTORIZATION"],
        lemmas=["RANK-NULLITY"],
        family="Algebraic structures and linear algebra",
    )
    tag(held, caption="RANK", methods=["RANK ARGUMENT"], objects=["MATRIX RANK"])
    payloads = statement_coverage_payloads([good, beta, neighbor, rank, held])
    assert "expansion" in {c["id"] for c in payloads[good.pk]["concept_coverage"]}
    for row in (beta, neighbor):
        assert "expansion" not in {c["id"] for c in payloads[row.pk]["concept_coverage"]}
        assert payloads[row.pk]["concept_coverage_status"] == "Needs review"
    for row in (rank, held):
        assert "rank" in {c["id"] for c in payloads[row.pk]["concept_coverage"]}
    assert "RANK ARGUMENT (method)" in payloads[held.pk]["concept_review_labels"]
    assert canonical_matches("Algebraic expansion") == {good.pk}
    assert canonical_matches("Matrix rank") == {rank.pk, held.pk}


def test_statement_precedence_includes_suppressed_rows_and_explicit_subject():
    problems = [
        ProblemSolveRecord.objects.create(year=2026, contest="COVERAGE", problem=f"P{i}", topic="A", mohs=10)
        for i in range(1, 5)
    ]
    for problem in problems:
        tag(problem, topic="")
    fallback = statement(1, topic="", linked=problems[0])
    own = statement(2, linked=problems[1])
    tag(own, caption="UNRESOLVED SOURCE")
    suppressed = statement(3, linked=problems[2])
    tag(suppressed, status="invalid")
    foreign = statement(4, topic="G", linked=problems[3])
    payloads = statement_coverage_payloads([fallback, own, suppressed, foreign])
    assert [c["id"] for c in payloads[fallback.pk]["concept_coverage"]] == ["am-gm"]
    assert payloads[own.pk]["concept_coverage"] == []
    assert payloads[suppressed.pk]["concept_coverage_status"] == "No valid tags"
    assert payloads[foreign.pk]["concept_coverage"] == []
    assert canonical_matches("AM-GM") == {fallback.pk}


@pytest.mark.parametrize(
    ("topic", "source_topic", "caption", "kind", "expected"),
    [
        ("N", "NT", "LTE", "lemma", "nt-lte"),
        ("G", "GEO", "ANGLE", "object", "geo-angles"),
        ("C", "COMB", "DOUBLE COUNTING", "method", "comb-double-counting"),
    ],
)
def test_other_subjects_use_their_canonical_registry(topic, source_topic, caption, kind, expected):
    row = statement(1, topic=topic)
    fields = (
        {"lemmas": [caption]}
        if kind == "lemma"
        else {
            "objects" if kind == "object" else "methods": [caption],
        }
    )
    tag(row, caption="SOURCE", topic=source_topic, **fields)
    payload = statement_coverage_payloads([row])[row.pk]
    assert expected in {c["id"] for c in payload["concept_coverage"]}
    concept = next(c for c in payload["concept_coverage"] if c["id"] == expected)
    assert canonical_matches(concept["label"]) == {row.pk}


def test_canonical_library_search_runs_before_latest_100_cap(client):
    client.force_login(UserFactory())
    old = statement(1)
    tag(old)
    ContestProblemStatement.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=1))
    for number in range(2, 104):
        statement(number)
    response = client.get(reverse("pages:problem_statement_list"), {"q": "optimization"})
    assert response.status_code == HTTPStatus.OK
    assert response.context["statement_filtered_total"] == 1
    assert response.context["statement_datatable_rows"][0]["statement_uuid"] == str(old.statement_uuid)


def test_tag_reads_are_batched_and_do_not_rewrite_source(django_assert_num_queries):
    problems = [
        ProblemSolveRecord.objects.create(year=2026, contest="COVERAGE", problem=f"P{i}", topic="A", mohs=10)
        for i in range(1, 6)
    ]
    for problem in problems:
        tag(problem)
    rows = [statement(n, linked=problem) for n, problem in enumerate(problems, 1)]
    before = list(ProblemTopicTechnique.objects.values())
    with django_assert_num_queries(2):
        payloads = statement_coverage_payloads(rows)
    assert all([c["id"] for c in p["concept_coverage"]] == ["am-gm"] for p in payloads.values())
    assert list(ProblemTopicTechnique.objects.values()) == before
    assert not TechniqueProgressFact.objects.exists()


def test_untagged_and_inactive_statements_are_explicit():
    untagged, inactive = statement(1), statement(2, active=False)
    tag(inactive)
    payloads = statement_coverage_payloads([untagged, inactive])
    assert payloads[untagged.pk]["concept_coverage_status"] == "Untagged"
    assert payloads[inactive.pk]["concept_coverage_status"] == "Inactive"
    assert payloads[inactive.pk]["concept_coverage"] == []
    assert canonical_matches("AM-GM") == set()


def test_same_unresolved_caption_is_shown_once_with_its_roles():
    row = statement(1)
    tag(row, caption="MATRIX METHOD", methods=["MATRIX METHOD"])
    payload = statement_coverage_payloads([row])[row.pk]
    assert payload["concept_review_labels"] == ["MATRIX METHOD (method, technique)"]
    assert payload["concept_coverage"] == []


def test_copied_rows_preserve_one_row_per_problem_with_multiline_source_captions():
    from inspinia.pages.views import _statement_table_rows_copy_tsv

    result = _statement_table_rows_copy_tsv(
        [
            {
                "contest_name": "Contest\nDay 1",
                "concept_source_tags": ["UNKNOWN\tCAPTION\r\nSECOND LINE"],
            },
        ],
    )
    rows = list(csv.DictReader(io.StringIO(result), delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["Contest"] == "Contest Day 1"
    assert rows[0]["Original tags"] == "UNKNOWN CAPTION SECOND LINE"
