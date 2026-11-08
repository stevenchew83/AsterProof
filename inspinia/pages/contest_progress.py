"""Presentation of the current user's contest progress and problem destinations."""

from django.urls import reverse


def _heatmap_cell(contest, year, code, counts):
    title = f"{contest} {year} {code}"
    if counts is None:
        return {
            "display": "", "problem_code": code, "solution_url": "", "state": "empty",
            "title": f"{title}: no statement",
        }
    total, solved = counts["problem_total"], counts["solved_total"]
    state = "unsolved" if solved == 0 else ("solved" if solved == total else "partial")
    display = "✓" if state == "solved" else "•"
    if total != 1:
        display = f"{solved}/{total}"
    noun = "statement" if total == 1 else "statements"
    return {
        "display": display, "problem_code": code, "solution_url": counts["solution_url"], "state": state,
        "title": f"{title}: {solved} of {total} {noun} completed by you",
    }


def contest_completion_heatmap(statements, solved_ids, contest):
    from inspinia.pages.views import _contest_completion_heatmap_chart_payload
    from inspinia.pages.views import _contest_heatmap_problem_code_groups
    from inspinia.pages.views import _problem_sort_key

    counts = {}
    for record in statements:
        code, year = str(record["problem_code"] or "").strip(), record["contest_year"]
        if not code or year is None:
            continue
        problem_uuid = record["linked_problem__problem_uuid"]
        cell = counts.setdefault((int(year), code), {
            "problem_total": 0, "solved_total": 0,
            "solution_url": reverse("solutions:problem_solution_list", args=[problem_uuid])
            if problem_uuid else reverse("pages:problem_statement_detail", args=[record["statement_uuid"]]),
        })
        cell["problem_total"] += 1
        cell["solved_total"] += int(record["id"] in solved_ids)
    codes = sorted({code for year, code in counts}, key=_problem_sort_key)
    years = sorted({year for year, code in counts}, reverse=True)
    rows = [
        {"year": year, "cells": [_heatmap_cell(contest, year, code, counts.get((year, code))) for code in codes]}
        for year in years
    ]
    return {
        "chart": _contest_completion_heatmap_chart_payload(rows),
        "filled_cell_total": len(counts),
        "has_partial_cells": any(cell["state"] == "partial" for row in rows for cell in row["cells"]),
        "problem_code_groups": _contest_heatmap_problem_code_groups(codes),
        "problem_code_total": len(codes), "problem_codes": codes, "rows": rows, "year_total": len(rows),
    }
