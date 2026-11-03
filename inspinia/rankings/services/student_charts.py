"""Read-only chart counts and filter links for achievement records."""

from collections import Counter
from urllib.parse import urlencode

from inspinia.rankings.models import ResultProfile
from inspinia.rankings.profile_models import EvidenceStatus

ACHIEVEMENT_EVIDENCE_PREFIX = "achievement_"


def matches_evidence(row, evidence):
    if evidence.startswith(ACHIEVEMENT_EVIDENCE_PREFIX):
        return row["has_outcome"] and row["evidence_status"] == evidence.removeprefix(ACHIEVEMENT_EVIDENCE_PREFIX)
    return not evidence or evidence in {claim["status"] for claim in row["claims"]} | {row["evidence_status"]}


def achievement_charts(records, filters, path):
    """Aggregate the complete filtered set, before pagination; never infer a medal."""
    records = [row for row in records if row["has_outcome"]]
    total = len(records)
    year_counts = Counter(row["year"] for row in records)
    discipline_counts = Counter(row["discipline"] for row in records)
    cells = Counter((row["year"], row["discipline"]) for row in records)
    evidence_counts = Counter(row["evidence_status"] for row in records)

    def link(**changes):
        values = {key: filters.get(key, "") for key in ("q", "year", "discipline", "evidence")}
        values.update(changes)
        query = urlencode({key: value for key, value in values.items() if value})
        return path + ("?" + query if query else "")

    def percent(count, denominator):
        # Strings keep CSS decimal separators independent of the request locale.
        return f"{100 * count / denominator:.4f}" if denominator else "0"

    disciplines = []
    for value, label in ResultProfile.Discipline.choices:
        if not discipline_counts[value]:
            continue
        active = filters.get("discipline") == value
        disciplines.append({
            "value": value, "label": label, "count": discipline_counts[value], "active": active,
            "url": link(discipline="" if active else value),
        })
    years = []
    maximum = max(year_counts.values(), default=0)
    for year, count in sorted(year_counts.items()):
        active = filters.get("year") == str(year)
        segments = []
        for discipline in disciplines:
            value = discipline["value"]
            segment_count = cells[year, value]
            if not segment_count:
                continue
            selected = active and discipline["active"]
            segments.append({
                "discipline": value, "label": discipline["label"], "count": segment_count,
                "height": percent(segment_count, count), "active": selected,
                "url": link(year="" if selected else str(year), discipline="" if selected else value),
            })
        years.append({
            "year": year, "count": count, "height": percent(count, maximum), "segments": segments,
            "cells": [cells[year, discipline["value"]] for discipline in disciplines],
            "active": active, "url": link(year="" if active else str(year)),
        })
    evidence = []
    for value, label in EvidenceStatus.choices:
        selection = ACHIEVEMENT_EVIDENCE_PREFIX + value
        active = filters.get("evidence") == selection
        count = evidence_counts[value]
        evidence.append({
            "value": value, "label": label, "count": count, "width": percent(count, total),
            "active": active, "url": link(evidence="" if active else selection),
        })
    return {"total": total, "years": years, "disciplines": disciplines, "evidence": evidence}
