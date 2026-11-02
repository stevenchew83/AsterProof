# ruff: noqa: PLR2004 -- Exact catalogue counts are intentional scope assertions.
import json
from collections import Counter
from pathlib import Path

from inspinia.training.content_packs import DATA
from inspinia.training.content_packs import rollout_manifest
from inspinia.training.taxonomy import TRAINING_TAXONOMY


def test_whole_module_exact_area_accounting_and_honest_release_states():
    seed = json.loads((Path(__file__).parents[1] / "pages/migrations/0038_catalogue_seed.json").read_text())
    manifest = rollout_manifest()
    areas = manifest["areas"]
    assert len(areas) == len({area["id"] for area in areas}) == 45
    assert {area["id"] for area in areas} == {area["id"] for area in seed["areas"]}
    assert {subject["id"] for subject in manifest["subjects"]} == {subject["id"] for subject in seed["subjects"]}
    waves = Counter(area["milestone"] for area in areas)
    assert waves["M1"] == 1
    assert sum(value for key, value in waves.items() if key.startswith("M2")) == 19
    assert waves["M3"] == 17
    assert waves["M4"] == 8
    assert all(area["status"] == "draft" and area["rights_status"] == "unreviewed" for area in areas)
    assert all(area["public_release"] == "not_released" for area in areas)
    assert all(area["canonical_practice_link_status"] == "pending_review" for area in areas)
    assert manifest["coverage"]["accepted_areas"] == 0
    assert manifest["coverage"]["released_areas"] == 0


def test_every_area_retains_exact_canonical_metadata_and_a_private_pack_reference():
    manifest = rollout_manifest()
    seed = json.loads((Path(__file__).parents[1] / "pages/migrations/0038_catalogue_seed.json").read_text())
    canonical = {row["id"] for row in seed["concepts"] if not row["redirect_id"]}
    for area in manifest["areas"]:
        assert area["entry_note_key"]
        assert area["owner"] == "Steven"
        assert area["pack"]
        assert set(area["covered_concept_ids"]) <= canonical
    assert len({area["pack"] for area in manifest["areas"]}) == 13


def test_all_nine_foundations_competencies_are_metadata_separate_from_catalogue_subjects():
    manifest = rollout_manifest()
    expected = next(topic for topic in TRAINING_TAXONOMY if topic["slug"] == "foundations")["subtopics"]
    competencies = manifest["foundations"]["competencies"]
    assert [item["title"] for item in competencies] == expected
    assert len({item["note_key"] for item in competencies}) == 9
    assert not any(subject["id"] == "foundations" for subject in manifest["subjects"])
    assert manifest["foundations"]["catalogue_subject"] is None


def test_public_package_contains_metadata_without_manuscript_or_exercise_sources():
    forbidden = {"body_source", "exercise_source", "inline_source", "hints", "answer"}

    def inspect(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(rollout_manifest())
    assert not list((DATA / "pathways").glob("*.json"))
    assert not list((Path(__file__).parents[1] / "learning/data/teaching_briefs").glob("*.json"))
