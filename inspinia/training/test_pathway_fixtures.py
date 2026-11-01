"""Generic private-pack fixtures; real unreviewed manuscripts never enter public tests."""

import json

import pytest


@pytest.fixture
def private_content_packs(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "public-media")
    root = tmp_path / "private-packs"
    for section in ("teaching_briefs", "pathways"):
        (root / section).mkdir(parents=True)
    for key, size, foundations in (("inequalities_pilot_v1", 6, False), ("foundations_v1", 9, True)):
        notes = []
        items = []
        for position in range(size):
            note_key = f"fixture-{position}"
            notes.append(
                {
                    "key": note_key,
                    "kind": "lecture",
                    "area_id": None if foundations else "Algebra:inequalities",
                    "concept_ids": ["induction" if foundations else "am-gm"],
                    "title": f"Synthetic document {position}",
                    "summary": "Private boundary fixture.",
                    "body_source": (
                        f"Generic non-mathematical test document {position}. This is not a starter manuscript."
                    ),
                    "audience": "Synthetic fixture",
                    "publication_status": "draft",
                    "rights": {"status": "unreviewed"},
                    "practice": {
                        "inline_source": "Generic test activity.",
                        "hints": ["Generic test hint."],
                        "canonical_problem_uuid": None,
                    },
                },
            )
            items.append(
                {
                    "key": note_key,
                    "kind": "document_reference",
                    "title": f"Synthetic document {position}",
                    "pack_note_key": note_key,
                    "requires_approved_document": True,
                },
            )
        pack = {"version": 1, "id": key, "title": "Synthetic private pack", "status": "draft", "notes": notes}
        path = {
            "version": 1,
            "id": key,
            "title": "Synthetic private pathway",
            "subject": None if foundations else "algebra",
            "is_foundations": foundations,
            "status": "draft",
            "items": items,
        }
        (root / "teaching_briefs" / f"{key}.json").write_text(json.dumps(pack))
        (root / "pathways" / f"{key}.json").write_text(json.dumps(path))
    settings.LEARNING_CONTENT_PACK_ROOT = str(root)
    return root
