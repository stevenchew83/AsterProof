"""Shared-concept progress uses accepted assignments in their problem context."""

from collections import defaultdict

from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_service import observed_area_memberships


def assignment_catalogue_rows(library, counts, subjects, *, subject="", area_key=""):
    by_concept = defaultdict(dict)
    by_area = defaultdict(dict)
    subject_problems = {value: {} for value in subjects}
    for uuid, problem in library.items():
        for concept in problem["concept_coverage"]:
            context = concept["subject"]
            key = f"{context}:{concept['area_id']}"
            if context in subject_problems:
                subject_problems[context][uuid] = problem
            if (not subject or context == subject) and (not area_key or key == area_key):
                by_concept[concept["id"]][uuid] = problem
                by_area[key][uuid] = problem
    concepts, areas = [], {}
    observed = observed_area_memberships(library)
    for cid, definition in REGISTRY.definitions.items():
        contexts = [*definition["area_memberships"]]
        contexts.extend(a for a in observed[cid] if a not in contexts)
        memberships = [
            a
            for a in contexts
            if (not subject or a["subject"] == subject) and (not area_key or f"{a['subject']}:{a['area']}" == area_key)
        ]
        if not memberships:
            continue
        chosen = memberships[0]
        row = {
            "id": cid,
            "label": definition["label"],
            "subject": chosen["subject"],
            "subjects": definition["subjects"],
            "area": chosen["label"],
            "area_key": f"{chosen['subject']}:{chosen['area']}",
            "area_keys": [f"{a['subject']}:{a['area']}" for a in memberships],
            "search_text": " ".join([cid, *(caption for _, caption in definition["aliases"])]).casefold(),
            **counts(by_concept[cid]),
        }
        concepts.append(row)
        for membership in memberships:
            key = f"{membership['subject']}:{membership['area']}"
            matching = {
                uuid: p
                for uuid, p in by_concept[cid].items()
                if any(
                    c["id"] == cid and c["subject"] == membership["subject"] and c["area_id"] == membership["area"]
                    for c in p["concept_coverage"]
                )
            }
            area = areas.setdefault(
                key,
                {
                    "id": key,
                    "label": membership["label"],
                    "subject": membership["subject"],
                    "concepts": 0,
                    "available": 0,
                    "practiced": 0,
                },
            )
            area["concepts"] += 1
            area["available"] += bool(matching)
            area["practiced"] += any(p["is_solved"] for p in matching.values())
    for key, area in areas.items():
        area.update(counts(by_area[key]))
    return concepts, list(areas.values()), subject_problems, by_concept
