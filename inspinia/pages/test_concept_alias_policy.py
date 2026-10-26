"""Alias meaning, original-source context and lifecycle remain independent of scores."""

import json
from copy import deepcopy

import pytest
from django.core.cache import cache

from inspinia.pages import concept_alias_policy as policy
from inspinia.pages.concept_alias_context import annotate_alias_context
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueProgressFact
from inspinia.pages.problem_import import prepare_topic_tag_entries
from inspinia.pages.technique_concepts import ALGEBRA_CONCEPTS
from inspinia.pages.technique_concepts import CATALOG
from inspinia.pages.technique_concepts import CONCEPTS
from inspinia.pages.technique_concepts import concept_fact_filter
from inspinia.pages.technique_concepts import concept_for
from inspinia.pages.technique_concepts import concepts_for_fact
from inspinia.pages.technique_progress import _scoped_subtopic_gap_rows
from inspinia.pages.technique_progress import technique_progress_gap_rows_for_benchmark_export
from inspinia.pages.technique_progress_catalog import rebuild_technique_progress_catalog
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
POLYNOMIAL_FAMILY = "Polynomials and algebraic manipulation"
LINEAR_FAMILY = "Algebraic structures and linear algebra"
EXPANSION_SOURCE = "ALG-POLYNOMIAL SUMS; SYMMETRY; EXPANSION"


def statement(number, *, topic="A", linked=None):
    return ContestProblemStatement.objects.create(
        contest_name="ALIAS POLICY TEST", contest_year=2026, problem_number=number,
        problem_code=f"A{number}", topic=topic, linked_problem=linked, statement_latex="Find x.",
    )


def tag(parent, *, technique=EXPANSION_SOURCE, family=POLYNOMIAL_FAMILY,  # noqa: PLR0913 -- explicit source dimensions
        methods=("EXPANSION",), objects=("POLYNOMIAL SUMS",), lemmas=(), main="ALG", domains=None):
    model, relation = (StatementTopicTechnique, "statement") if isinstance(parent, ContestProblemStatement) else (
        ProblemTopicTechnique, "record",
    )
    return model.objects.create(**{
        relation: parent, "technique": technique, "canonical_subtopic": family,
        "technique_tags": list(methods), "object_tags": list(objects), "lemma_theorem_tags": list(lemmas),
        "main_topic": main, "domains": ["ALG"] if domains is None else domains,
    })


def selected(cid):
    return set(TechniqueProgressFact.objects.filter(concept_fact_filter(cid)).values_list("statement_id", flat=True))


def projected(cid, *, family=""):
    facts = annotate_alias_context(list(TechniqueProgressFact.objects.values(
        "statement_id", "linked_problem_id", "layer", "label", "main_topic", "main_topic_labels",
    )), canonical_subtopic=family)
    return {fact["statement_id"] for fact in facts if cid in concepts_for_fact(fact)}


@pytest.mark.parametrize(("kind", "caption", "target"), [
    ("method", "SUBSTITUTION", "substitution"),
    ("method", "LINEAR RECURRENCE", "linear-recurrences"),
    ("object", "FINITE DIFFERENCES", "finite-differences"),
    ("object", "TELESCOPING", "telescoping"),
    ("object", "MATRIX RANK", "rank"),
])
def test_confirmed_identity_corrections_keep_original_role(kind, caption, target):
    assert concept_for(kind, caption) == target
    assert not concept_for(kind, caption, topic="Geometry")
    result = policy.alias_resolution("Algebra", kind, caption)
    assert result.resolution == "EXACT"
    assert result.concept_ids == (target,)


@pytest.mark.parametrize(("kind", "caption"), [
    ("method", "RANK"), ("object", "RANK"), ("technique", "RANK"),
    ("method", "RANK ARGUMENT"), ("method", "MATRIX METHOD"),
    ("method", "EXPANSION"), ("technique", "EXPANSION"),
])
def test_generic_priority_captions_do_not_guess_without_context(kind, caption):
    assert not concept_for(kind, caption)
    assert not policy.alias_resolution("Algebra", kind, caption).concept_ids


def test_all_original_profiles_and_specialized_identities_survive():
    for original in CATALOG["concepts"]:
        assert ALGEBRA_CONCEPTS[original["concept_id"]]["profiles"] == original["profiles"]
    assert "integer-domain-functional-equations" in CONCEPTS
    assert "integer-valued-polynomials" in CONCEPTS
    assert "harmonic-sums" in CONCEPTS
    assert "nt-fermat-two-squares" in CONCEPTS
    assert "nt-sum-two-squares" in CONCEPTS
    assert CONCEPTS["rank"]["label"] == "Matrix rank"


def test_expansion_uses_same_source_and_excludes_beta_and_generic_cases():
    good = statement(1)
    tag(good)
    beta = statement(2)
    tag(beta, technique="BETA-EXPANSION", family="Analytic estimates and asymptotics", objects=["BETA-EXPANSION"])
    generic = statement(3)
    tag(generic, technique="EXPANSION", family="Additive number theory and zero-sum methods", objects=[])
    neighbor = statement(4)
    tag(neighbor, objects=[])
    tag(neighbor, technique="OTHER SOURCE", objects=["POLYNOMIAL SUMS"], methods=[])
    rebuild_technique_progress_catalog()
    assert projected("expansion") == selected("expansion") == {good.pk}
    assert not selected("algebraic-identities")


def test_matrix_rank_needs_explicit_source_evidence_and_keeps_independent_support():
    good = statement(1)
    tag(good, technique="MINIMAL-RANK IDEMPOTENT", family=LINEAR_FAMILY,
        methods=["RANK", "MATRIX FACTORIZATION"], objects=["MINIMAL RANK/IDEMPOTENT"], lemmas=["RANK-NULLITY"])
    held = statement(2)
    tag(held, technique="RANK", family=LINEAR_FAMILY, methods=["RANK ARGUMENT"], objects=["RANK"])
    independent = statement(3)
    tag(independent, technique="RANK", family=LINEAR_FAMILY, methods=["RANK"], objects=["MATRIX RANK"])
    rebuild_technique_progress_catalog()
    assert projected("rank") == selected("rank") == {good.pk, independent.pk}
    assert not selected("determinants")


def test_two_squares_retains_representation_and_requires_named_theorem_context():
    good = statement(1, topic="N")
    tag(good, technique="SUM OF TWO SQUARES", family="Diophantine equations and descent",
        methods=[], objects=["SUM OF TWO SQUARES"], lemmas=["SUM OF TWO SQUARES", "FERMAT TWO-SQUARE THEOREM"],
        main="NT", domains=["NT"])
    held = statement(2, topic="N")
    tag(held, technique="UNSPECIFIED TWO-SQUARE RESULT", family="Diophantine equations and descent",
        methods=[], objects=["SUM OF TWO SQUARES"], lemmas=["SUM OF TWO SQUARES"], main="NT", domains=["NT"])
    rebuild_technique_progress_catalog()
    assert projected("nt-fermat-two-squares") == selected("nt-fermat-two-squares") == {good.pk}
    assert projected("nt-sum-two-squares") == selected("nt-sum-two-squares") == {good.pk, held.pk}


def test_statement_tags_and_subject_precedence_block_linked_context():
    problems = [
        ProblemSolveRecord.objects.create(year=2026, contest="ALIAS TEST", problem=f"P{i}", topic="A", mohs=10)
        for i in range(1, 4)
    ]
    for problem in problems:
        tag(problem, main="", domains=[])
    fallback = statement(1, topic="", linked=problems[0])
    overridden = statement(2, linked=problems[1])
    tag(overridden, technique="EXPANSION", objects=[])
    foreign = statement(3, topic="N", linked=problems[2])
    rebuild_technique_progress_catalog()
    assert projected("expansion") == selected("expansion") == {fallback.pk}
    assert overridden.pk not in selected("expansion")
    assert foreign.pk not in selected("expansion")


def test_context_does_not_leak_to_another_family_in_subtopic_or_gap_counts():
    user = UserFactory()
    row = statement(1)
    tag(row)
    other_family = "Analytic estimates and asymptotics"
    tag(row, technique="BETA-EXPANSION", family=other_family, objects=["BETA-EXPANSION"])
    rebuild_technique_progress_catalog()
    cache.clear()
    previews = _scoped_subtopic_gap_rows(user=user, gap_topic="algebra")
    assert any(r["label"] == "Algebraic expansion" and r["canonical_subtopic_labels"] == [POLYNOMIAL_FAMILY]
               for r in previews)
    assert not any(r["label"] == "Algebraic expansion" and r["canonical_subtopic_labels"] == [other_family]
                   for r in previews)
    rows = technique_progress_gap_rows_for_benchmark_export(
        request_user=user, raw_kind="all", raw_topic="algebra", raw_canonical_subtopic=other_family,
    )
    assert not any(r.get("concept_id") == "expansion" for r in rows)


def test_conflicting_context_rules_hold_instead_of_selecting_the_first_target():
    binding = deepcopy(policy.BINDINGS[("Algebra", "method", "expansion")])
    conflict = {**binding["context_rules"][0], "id": "conflict", "concept_id": "algebraic-identities"}
    binding["context_rules"].append(conflict)
    source = {"technique": EXPANSION_SOURCE, "canonical_subtopic": POLYNOMIAL_FAMILY,
              "main_topic": "ALG", "domains": ["ALG"], "technique_tags": ["EXPANSION"],
              "object_tags": ["POLYNOMIAL SUMS"]}
    decision = policy.resolve_binding(binding, source=source)
    assert decision.concept_ids == ()
    assert decision.held_reason == "CONTRADICTORY_SOURCE_CONTEXT"


def test_deprecated_exact_caption_is_readable_but_normalizes_new_assignments(monkeypatch):
    binding = {"id": "DEPRECATED-TEST", "subject": "Algebra", "kind": "method", "caption": "OLD SUBSTITUTION",
               "resolution": "EXACT", "lifecycle": "DEPRECATED", "concept_id": "substitution",
               "context_rules": [], "canonical_caption": "SUBSTITUTION"}
    policy.validate_policy({"bindings": [binding]})
    monkeypatch.setitem(policy.BINDINGS, ("Algebra", "method", "old substitution"), binding)
    assert policy.alias_resolution("Algebra", "method", "OLD SUBSTITUTION").concept_ids == ("substitution",)
    source = {"technique": "LEGACY SOURCE", "canonical_subtopic": POLYNOMIAL_FAMILY, "main_topic": "ALG",
              "domains": ["ALG"], "technique_tags": ["OLD SUBSTITUTION"], "raw_tag": "ORIGINAL SOURCE"}
    monkeypatch.setattr("inspinia.pages.problem_import.classified_topic_tag_entries", lambda **_kw: [deepcopy(source)])
    result = prepare_topic_tag_entries("LEGACY SOURCE", topic="A", active=True, problem_uuid=None, canonicalize=False)
    assert result[0]["technique_tags"] == ["SUBSTITUTION"]
    assert "ORIGINAL SOURCE" in result[0]["raw_tag"]
    assert "OLD SUBSTITUTION" in result[0]["raw_tag"]
    assert source["technique_tags"] == ["OLD SUBSTITUTION"]


def test_invalid_policy_and_unresolved_deprecated_assignments_fail_closed(monkeypatch):
    bad = {"id": "BAD", "subject": "Algebra", "kind": "method", "caption": "UNDEFINED",
           "resolution": "CONTEXTUAL", "lifecycle": "ACTIVE", "concept_id": None, "context_rules": []}
    with pytest.raises(ValueError, match="Contextual aliases"):
        policy.validate_policy({"bindings": [bad]})
    held = {**bad, "resolution": "AMBIGUOUS", "lifecycle": "DEPRECATED"}
    monkeypatch.setitem(policy.BINDINGS, ("Algebra", "method", "undefined"), held)
    with pytest.raises(ValueError, match="source review"):
        policy.normalize_alias_assignments({"main_topic": "ALG", "domains": ["ALG"], "technique_tags": ["UNDEFINED"]})


def test_packaged_catalogs_are_not_rewritten_by_runtime_alias_policy():
    assert json.loads(policy.POLICY_PATH.read_text()) == policy.POLICY
    captured_alias_count = 543
    assert sum(len(c["aliases"]) for c in CATALOG["concepts"]) == captured_alias_count
