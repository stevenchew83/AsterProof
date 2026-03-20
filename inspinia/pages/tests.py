from http import HTTPStatus
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.problem_import import ProblemImportValidationError
from inspinia.pages.problem_import import dataframe_from_excel
from inspinia.pages.problem_import import import_problem_dataframe
from inspinia.pages.statement_import import LATEX_STATEMENT_SAMPLE
from inspinia.pages.statement_import import import_problem_statements
from inspinia.pages.statement_import import parse_contest_problem_statements
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_RECORD_COUNT = 1
EXPECTED_ONE_TECHNIQUE = 1
EXPECTED_TWO_TECHNIQUES = 2
UPDATED_MOHS = 5
WORKBOOK_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPECTED_EXPORT_COLUMNS = [
    "PROBLEM UUID",
    "YEAR",
    "TOPIC",
    "MOHS",
    "CONTEST",
    "PROBLEM",
    "CONTEST PROBLEM",
    "Topic tags",
    "Confidence",
    "IMO slot guess",
    "Rationale",
    "Pitfalls",
]
EXPECTED_CONTEST_TOTAL = 2
EXPECTED_CONTEST_PROBLEM_TOTAL = 3
EXPECTED_AVERAGE_PROBLEMS_PER_CONTEST = 1.5
EXPECTED_TECHNIQUE_DENSITY = 1.5
EXPECTED_MULTI_YEAR_CONTESTS = 1
EXPECTED_TOPIC_TAG_TOTAL = 3
EXPECTED_TAGGED_PROBLEM_TOTAL = 2
EXPECTED_AVERAGE_TAGS_PER_PROBLEM = 2.0
SPAIN_OLYMPIAD_YEAR = 2026
SPAIN_OLYMPIAD_NAME = "Spain Mathematical Olympiad"
EXPECTED_STATEMENT_PROBLEM_TOTAL = 6
EXPECTED_STATEMENT_DAY_TOTAL = 2
EXPECTED_STATEMENT_SET_TOTAL = 2
EXPECTED_STATEMENT_ROW_TOTAL = 3
EXPECTED_AVERAGE_STATEMENTS_PER_SET = 1.5
EXPECTED_STATEMENT_OVERALL_LINK_RATE = 33.33
EXPECTED_SPAIN_STATEMENT_LINK_RATE = 50.0
NEPAL_OLYMPIAD_YEAR = 2026
NEPAL_OLYMPIAD_NAME = "Nepal National Olympiad (IMO Pre-TST)"
EXPECTED_NEPAL_STATEMENT_PROBLEM_TOTAL = 8
NEPAL_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "nepal_statement_sample.txt"
).read_text(encoding="utf-8")
APMO_YEAR = 2025
APMO_NAME = "APMO"
EXPECTED_APMO_STATEMENT_PROBLEM_TOTAL = 5
APMO_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "apmo_statement_sample.txt"
).read_text(encoding="utf-8")
ISL_YEAR = 2024
ISL_NAME = "ISL"
EXPECTED_ISL_STATEMENT_PROBLEM_TOTAL = 7
ISL_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "isl_statement_sample.txt"
).read_text(encoding="utf-8")
EGMO_YEAR = 2025
EGMO_NAME = "EGMO"
EXPECTED_EGMO_STATEMENT_PROBLEM_TOTAL = 6
EGMO_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "egmo_statement_sample.txt"
).read_text(encoding="utf-8")
ELMO_REVENGE_YEAR = 2022
ELMO_REVENGE_NAME = "ELMO Revenge"
EXPECTED_ELMO_REVENGE_PROBLEM_TOTAL = 6
EXPECTED_ELMO_REVENGE_BONUS_NUMBER = 3
ELMO_REVENGE_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "elmo_revenge_sample.txt"
).read_text(encoding="utf-8")
CHINA_TST_YEAR = 2026
CHINA_TST_NAME = "China Team Selection Test"
EXPECTED_CHINA_TST_PROBLEM_TOTAL = 12
CHINA_TST_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "china_team_selection_test_sample.txt"
).read_text(encoding="utf-8")
BALKAN_SHORTLIST_YEAR = 2024
BALKAN_SHORTLIST_NAME = "Balkan MO Shortlist"
EXPECTED_BALKAN_SHORTLIST_PROBLEM_TOTAL = 8
BALKAN_SHORTLIST_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "balkan_shortlist_sample.txt"
).read_text(encoding="utf-8")


def _analytics_rows(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _workbook_bytes(*rows: dict) -> bytes:
    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


def _xlsx_upload(*rows: dict) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "analytics.xlsx",
        _workbook_bytes(*rows),
        content_type=WORKBOOK_CONTENT_TYPE,
    )


def test_dataframe_from_excel_strips_headers_and_requires_columns():
    workbook_bytes = _workbook_bytes(
        {
            " YEAR ": 2026,
            " TOPIC ": "NT",
            " MOHS ": 4,
            " CONTEST ": "ISRAEL TST",
            " PROBLEM ": "P2",
            " CONTEST PROBLEM ": "ISRAEL TST 2026 P2",
            " Topic tags ": "Topic tags: NT - LTE",
        },
    )

    dataframe = dataframe_from_excel(workbook_bytes)

    assert list(dataframe.columns) == [
        "YEAR",
        "TOPIC",
        "MOHS",
        "CONTEST",
        "PROBLEM",
        "CONTEST PROBLEM",
        "Topic tags",
    ]

    missing_column_bytes = _workbook_bytes(
        {
            "YEAR": 2026,
            "TOPIC": "NT",
            "MOHS": 4,
            "CONTEST": "ISRAEL TST",
            "PROBLEM": "P2",
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
        },
    )

    with pytest.raises(ProblemImportValidationError, match="Missing required column"):
        dataframe_from_excel(missing_column_bytes)


def test_import_problem_dataframe_creates_records_and_normalized_fields():
    dataframe = _analytics_rows(
        {
            "YEAR": 2026,
            "TOPIC": "NT",
            "MOHS": 4,
            "CONTEST": None,
            "PROBLEM": None,
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
            "Topic tags": "Topic tags: NT - LTE, parity",
            "SOLVE DATE": "2026-01-15",
            "Confidence": "High",
            "IMO slot guess": "IMO slot guess: P1/4",
            "Rationale": "Rationale: Short parity punchline.",
            "Pitfalls": "Common pitfalls: Greedy reasoning.",
        },
    )

    result = import_problem_dataframe(dataframe, replace_tags=False)

    assert result.n_records == EXPECTED_RECORD_COUNT
    assert result.n_techniques == EXPECTED_TWO_TECHNIQUES
    assert result.warnings == []

    record = ProblemSolveRecord.objects.get(year=2026)
    assert record.contest == "ISRAEL TST"
    assert record.problem == "P2"
    assert record.imo_slot_guess_value == "1,4"
    assert record.rationale_value == "Short parity punchline."
    assert record.pitfalls_value == "Greedy reasoning."
    assert list(
        record.topic_techniques.order_by("technique").values_list("technique", flat=True),
    ) == ["LTE", "PARITY"]


def test_import_problem_dataframe_merges_domains_and_refreshes_derived_values():
    initial_dataframe = _analytics_rows(
        {
            "YEAR": 2026,
            "TOPIC": "ALG",
            "MOHS": 4,
            "CONTEST": "ISRAEL TST",
            "PROBLEM": "P2",
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
            "Topic tags": "Topic tags: ALG - invariants",
            "IMO slot guess": "IMO slot guess: P1/4",
            "Rationale": "Rationale: Initial explanation.",
            "Pitfalls": "Common pitfalls: Initial pitfall.",
        },
    )
    import_problem_dataframe(initial_dataframe, replace_tags=False)

    updated_dataframe = _analytics_rows(
        {
            "YEAR": 2026,
            "TOPIC": "ALG",
            "MOHS": UPDATED_MOHS,
            "CONTEST": "ISRAEL TST",
            "PROBLEM": "P2",
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
            "Topic tags": "Topic tags: COMB - invariants; NT - LTE",
            "IMO slot guess": "IMO slot guess: P2/5",
            "Rationale": "Rationale: Updated explanation.",
            "Pitfalls": "Common pitfalls: Updated pitfall.",
        },
    )

    result = import_problem_dataframe(updated_dataframe, replace_tags=False)

    assert result.n_records == EXPECTED_RECORD_COUNT
    assert result.n_techniques == EXPECTED_TWO_TECHNIQUES

    record = ProblemSolveRecord.objects.get(
        year=2026,
        contest="ISRAEL TST",
        problem="P2",
    )
    assert record.mohs == UPDATED_MOHS
    assert record.imo_slot_guess_value == "2,5"
    assert record.rationale_value == "Updated explanation."
    assert record.pitfalls_value == "Updated pitfall."

    invariants = ProblemTopicTechnique.objects.get(record=record, technique="INVARIANTS")
    assert invariants.domains == ["ALG", "COMB"]
    assert ProblemTopicTechnique.objects.get(record=record, technique="LTE").domains == ["NT"]


def test_import_problem_dataframe_adopts_existing_statement_problem_uuid():
    statement = ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="ISRAEL TST",
        problem_number=2,
        day_label="Day 1",
        statement_latex="Imported from statement preview",
    )

    dataframe = _analytics_rows(
        {
            "YEAR": 2026,
            "TOPIC": "ALG",
            "MOHS": 4,
            "CONTEST": "ISRAEL TST",
            "PROBLEM": "P2",
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
            "Topic tags": "Topic tags: ALG - invariants",
        },
    )

    result = import_problem_dataframe(dataframe, replace_tags=False)

    assert result.n_records == EXPECTED_RECORD_COUNT
    record = ProblemSolveRecord.objects.get(
        year=2026,
        contest="ISRAEL TST",
        problem="P2",
    )
    statement.refresh_from_db()
    assert record.problem_uuid == statement.problem_uuid
    assert statement.linked_problem == record


def test_import_problem_dataframe_replaces_existing_tags_when_requested():
    initial_dataframe = _analytics_rows(
        {
            "YEAR": 2026,
            "TOPIC": "ALG",
            "MOHS": 4,
            "CONTEST": "ISRAEL TST",
            "PROBLEM": "P2",
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
            "Topic tags": "Topic tags: ALG - invariants; NT - LTE",
        },
    )
    import_problem_dataframe(initial_dataframe, replace_tags=False)

    replacement_dataframe = _analytics_rows(
        {
            "YEAR": 2026,
            "TOPIC": "GEO",
            "MOHS": UPDATED_MOHS,
            "CONTEST": "ISRAEL TST",
            "PROBLEM": "P2",
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
            "Topic tags": "Topic tags: GEO - angle chasing",
        },
    )

    result = import_problem_dataframe(replacement_dataframe, replace_tags=True)

    assert result.n_records == EXPECTED_RECORD_COUNT
    assert result.n_techniques == EXPECTED_ONE_TECHNIQUE

    record = ProblemSolveRecord.objects.get(
        year=2026,
        contest="ISRAEL TST",
        problem="P2",
    )
    techniques = list(record.topic_techniques.values_list("technique", "domains"))
    assert techniques == [("ANGLE CHASING", ["GEO"])]


def test_problem_topic_technique_save_uppercases_technique_and_domains():
    record = ProblemSolveRecord.objects.create(
        year=2026,
        topic="GEO",
        mohs=4,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
    )

    tag = ProblemTopicTechnique.objects.create(
        record=record,
        technique="angle chasing",
        domains=["geo", "Geo", "combinatorics"],
    )

    assert tag.technique == "ANGLE CHASING"
    assert tag.domains == ["GEO", "COMBINATORICS"]


def test_parse_contest_problem_statements_extracts_contest_days_and_problem_blocks():
    parsed_import = parse_contest_problem_statements(LATEX_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == SPAIN_OLYMPIAD_YEAR
    assert parsed_import.contest_name == SPAIN_OLYMPIAD_NAME
    assert len(parsed_import.problems) == EXPECTED_STATEMENT_PROBLEM_TOTAL
    assert len({problem.day_label for problem in parsed_import.problems}) == EXPECTED_STATEMENT_DAY_TOTAL
    assert [problem.day_label for problem in parsed_import.problems[:3]] == ["Day 1"] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:]] == ["Day 2"] * 3
    assert parsed_import.problems[0].problem_number == 1
    assert "Find the value of a positive integer" in parsed_import.problems[0].statement_latex
    assert "Determine, as a function of $n$" in parsed_import.problems[4].statement_latex


def test_parse_contest_problem_statements_supports_p_prefixed_problems_and_scrape_metadata():
    parsed_import = parse_contest_problem_statements(NEPAL_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == NEPAL_OLYMPIAD_YEAR
    assert parsed_import.contest_name == NEPAL_OLYMPIAD_NAME
    assert len(parsed_import.problems) == EXPECTED_NEPAL_STATEMENT_PROBLEM_TOTAL
    assert all(problem.day_label == "" for problem in parsed_import.problems)
    assert parsed_import.problems[0].problem_code == "P1"
    assert parsed_import.problems[-1].problem_code == "P8"
    assert "Problems from the 2026 Nepal National Olympiad" not in parsed_import.problems[0].statement_latex
    assert "(Proposed by Prajit Adhikari, Nepal)" in parsed_import.problems[0].statement_latex
    assert "Thapakazi" not in parsed_import.problems[0].statement_latex
    assert "AshAuktober" not in parsed_import.problems[2].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "every real root of $P$ is greater than or equal to $1$" in parsed_import.problems[0].statement_latex
    assert (
        "(Proposed by Prajit Adhikari, Nepal and Kritesh Dhakal, Nepal)"
        in parsed_import.problems[-1].statement_latex
    )
    assert "Determine when equality holds." in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_subtitle_line_before_numbered_apmo_problems():
    parsed_import = parse_contest_problem_statements(APMO_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == APMO_YEAR
    assert parsed_import.contest_name == APMO_NAME
    assert len(parsed_import.problems) == EXPECTED_APMO_STATEMENT_PROBLEM_TOTAL
    assert all(problem.day_label == "" for problem in parsed_import.problems)
    assert [problem.problem_number for problem in parsed_import.problems] == [1, 2, 3, 4, 5]
    assert "Asian-Pacific MO 2025" not in parsed_import.problems[0].statement_latex
    assert "Aiden-1089" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "circle $\\Gamma$" in parsed_import.problems[0].statement_latex
    assert "rooster is on a cell assigned $0$" in parsed_import.problems[3].statement_latex
    assert "$\\text{\\emph{Observation:}}$" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_isl_sections_and_alpha_numeric_codes():
    parsed_import = parse_contest_problem_statements(ISL_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == ISL_YEAR
    assert parsed_import.contest_name == ISL_NAME
    assert len(parsed_import.problems) == EXPECTED_ISL_STATEMENT_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == [
        "A1",
        "A2",
        "C1",
        "G1",
        "N1",
        "N6",
        "N7",
    ]
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Algebra",
        "Algebra",
        "Combinatorics",
        "Geometry",
        "Number Theory",
        "Number Theory",
        "Number Theory",
    ]
    assert "IMO Shortlist 2024" not in parsed_import.problems[0].statement_latex
    assert "EthanWYX2009" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "Proposed by Santiago Rodríguez, Colombia" in parsed_import.problems[0].statement_latex
    assert "$\\text{\\emph{n-good}}$" in parsed_import.problems[5].statement_latex
    assert "Determine all integers $n$ such that every polynomial" in parsed_import.problems[5].statement_latex


def test_parse_contest_problem_statements_supports_day_headers_with_dates():
    parsed_import = parse_contest_problem_statements(EGMO_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == EGMO_YEAR
    assert parsed_import.contest_name == EGMO_NAME
    assert len(parsed_import.problems) == EXPECTED_EGMO_STATEMENT_PROBLEM_TOTAL
    assert [problem.problem_number for problem in parsed_import.problems] == [1, 2, 3, 4, 5, 6]
    assert [problem.day_label for problem in parsed_import.problems[:3]] == [
        "Day 1 · April 13, 2025",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:]] == [
        "Day 2 · April 14, 2025",
    ] * 3
    assert parsed_import.problems[0].problem_code == "P1"
    assert "April 13, 2025" not in parsed_import.problems[0].statement_latex
    assert "EeEeRUT" not in parsed_import.problems[0].statement_latex
    assert "Here $\\gcd(a, b)$ is the largest positive integer" in parsed_import.problems[0].statement_latex
    assert "Proposed by Paulius Aleknavičius, Lithuania" in parsed_import.problems[0].statement_latex
    assert "What is the largest possible value of $\\frac{R}{C}$?" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_elmo_subsections_and_bonus_problem():
    parsed_import = parse_contest_problem_statements(ELMO_REVENGE_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == ELMO_REVENGE_YEAR
    assert parsed_import.contest_name == ELMO_REVENGE_NAME
    assert len(parsed_import.problems) == EXPECTED_ELMO_REVENGE_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == [
        "P1",
        "P2",
        "BONUS",
        "P1",
        "P2",
        "P3",
    ]
    assert [problem.day_label for problem in parsed_import.problems] == [
        "ELMO",
        "ELMO",
        "ELMO",
        "ELSMO",
        "ELSMO",
        "ELSMO",
    ]
    assert parsed_import.problems[2].problem_number == EXPECTED_ELMO_REVENGE_BONUS_NUMBER
    assert "Gogobao" not in parsed_import.problems[2].statement_latex
    assert "Determine, with proof, if there exists an odd prime" in parsed_import.problems[2].statement_latex
    assert "DottedCaculator" not in parsed_import.problems[3].statement_latex
    assert "Same as ELMO 5" in parsed_import.problems[4].statement_latex


def test_parse_contest_problem_statements_supports_round_test_headers_and_solution_metadata():
    parsed_import = parse_contest_problem_statements(CHINA_TST_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == CHINA_TST_YEAR
    assert parsed_import.contest_name == CHINA_TST_NAME
    assert len(parsed_import.problems) == EXPECTED_CHINA_TST_PROBLEM_TOTAL
    assert [problem.problem_number for problem in parsed_import.problems] == list(range(1, 13))
    assert [problem.day_label for problem in parsed_import.problems[:3]] == ["Round One · Test 1"] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:6]] == ["Round One · Test 2"] * 3
    assert [problem.day_label for problem in parsed_import.problems[6:9]] == ["Round One · Test 3"] * 3
    assert [problem.day_label for problem in parsed_import.problems[9:]] == ["Round One · Test 4"] * 3
    assert "Round One" not in parsed_import.problems[0].statement_latex
    assert "Solution" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "steven_zhang123" not in parsed_import.problems[0].statement_latex
    assert "EeEeRUT" not in parsed_import.problems[0].statement_latex
    assert "Scilyse" not in parsed_import.problems[3].statement_latex
    assert "Fibonacci sequence" in parsed_import.problems[0].statement_latex
    assert "the complete graph $K_{2026}$" in parsed_import.problems[4].statement_latex
    assert "family of subsets of $A$" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_balkan_shortlist_equation_continuations():
    parsed_import = parse_contest_problem_statements(BALKAN_SHORTLIST_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == BALKAN_SHORTLIST_YEAR
    assert parsed_import.contest_name == BALKAN_SHORTLIST_NAME
    assert len(parsed_import.problems) == EXPECTED_BALKAN_SHORTLIST_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "C1",
        "G1",
        "N1",
    ]
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Algebra",
        "Algebra",
        "Algebra",
        "Algebra",
        "Algebra",
        "Combinatorics",
        "Geometry",
        "Number Theory",
    ]
    assert "Balkan MO Shortlist 2024" not in parsed_import.problems[0].statement_latex
    assert "MuradSafarli" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "\\]and determine all the cases when the equality occurs." in parsed_import.problems[3].statement_latex
    assert "proposed by Sardor Gafforov from Uzbekistan." in parsed_import.problems[4].statement_latex
    assert all(problem.problem_code != "P3" for problem in parsed_import.problems)


def test_import_problem_statements_creates_rows_and_links_existing_problem_records():
    linked_record = ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        contest=SPAIN_OLYMPIAD_NAME,
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )

    result = import_problem_statements(parse_contest_problem_statements(LATEX_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_STATEMENT_PROBLEM_TOTAL
    assert result.updated_count == 0
    assert result.linked_problem_count == EXPECTED_RECORD_COUNT

    statement = ContestProblemStatement.objects.get(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
    )
    assert statement.linked_problem == linked_record
    assert statement.problem_uuid == linked_record.problem_uuid
    assert statement.day_label == "Day 1"
    assert statement.problem_code == "P1"
    assert statement.contest_year_problem == f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1"


def test_import_problem_statements_supports_alpha_numeric_codes_across_sections():
    linked_record = ProblemSolveRecord.objects.create(
        year=ISL_YEAR,
        topic="ALG",
        mohs=4,
        contest=ISL_NAME,
        problem="A1",
        contest_year_problem=f"{ISL_NAME} {ISL_YEAR} A1",
    )

    result = import_problem_statements(parse_contest_problem_statements(ISL_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_ISL_STATEMENT_PROBLEM_TOTAL
    assert result.updated_count == 0
    assert result.linked_problem_count == EXPECTED_RECORD_COUNT
    assert ContestProblemStatement.objects.filter(contest_name=ISL_NAME, contest_year=ISL_YEAR).count() == (
        EXPECTED_ISL_STATEMENT_PROBLEM_TOTAL
    )

    algebra_one = ContestProblemStatement.objects.get(
        contest_year=ISL_YEAR,
        contest_name=ISL_NAME,
        problem_code="A1",
    )
    combinatorics_one = ContestProblemStatement.objects.get(
        contest_year=ISL_YEAR,
        contest_name=ISL_NAME,
        problem_code="C1",
    )
    assert algebra_one.problem_number == 1
    assert combinatorics_one.problem_number == 1
    assert algebra_one.day_label == "Algebra"
    assert combinatorics_one.day_label == "Combinatorics"
    assert algebra_one.linked_problem == linked_record
    assert algebra_one.problem_uuid == linked_record.problem_uuid
    assert combinatorics_one.problem_code == "C1"


def test_import_problem_statements_supports_duplicate_numeric_codes_in_different_sections():
    result = import_problem_statements(parse_contest_problem_statements(ELMO_REVENGE_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_ELMO_REVENGE_PROBLEM_TOTAL
    assert result.updated_count == 0
    assert ContestProblemStatement.objects.filter(
        contest_year=ELMO_REVENGE_YEAR,
        contest_name=ELMO_REVENGE_NAME,
    ).count() == EXPECTED_ELMO_REVENGE_PROBLEM_TOTAL

    elmo_one = ContestProblemStatement.objects.get(
        contest_year=ELMO_REVENGE_YEAR,
        contest_name=ELMO_REVENGE_NAME,
        day_label="ELMO",
        problem_code="P1",
    )
    elsmo_one = ContestProblemStatement.objects.get(
        contest_year=ELMO_REVENGE_YEAR,
        contest_name=ELMO_REVENGE_NAME,
        day_label="ELSMO",
        problem_code="P1",
    )
    bonus = ContestProblemStatement.objects.get(
        contest_year=ELMO_REVENGE_YEAR,
        contest_name=ELMO_REVENGE_NAME,
        day_label="ELMO",
        problem_code="BONUS",
    )
    assert elmo_one.problem_number == 1
    assert elsmo_one.problem_number == 1
    assert bonus.problem_number == EXPECTED_ELMO_REVENGE_BONUS_NUMBER
    assert "odd prime $p$" in bonus.statement_latex


def test_home_requires_login(client):
    response = client.get(reverse("pages:home"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:home')}"


def test_home_allows_authenticated_access(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:home"))

    assert response.status_code == HTTPStatus.OK


def test_latex_preview_requires_login(client):
    response = client.get(reverse("pages:latex_preview"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:latex_preview')}"


def test_problem_statement_list_requires_login(client):
    response = client.get(reverse("pages:problem_statement_list"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:problem_statement_list')}"


@override_settings(DEBUG=False)
def test_problem_statement_analytics_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:problem_statement_dashboard"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_latex_preview_allows_authenticated_access(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:latex_preview"))

    assert response.status_code == HTTPStatus.OK
    assert "LaTeX preview" in response.content.decode("utf-8")


def test_problem_statement_list_shows_statement_rows_and_link_counts(client):
    user = UserFactory()
    client.force_login(user)
    linked_record = ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        contest=SPAIN_OLYMPIAD_NAME,
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )
    linked_statement = ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        day_label="Day 1",
        statement_latex="Linked statement preview text",
        linked_problem=linked_record,
    )
    ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=NEPAL_OLYMPIAD_NAME,
        problem_number=8,
        day_label="",
        statement_latex="Unlinked statement preview text",
    )

    response = client.get(reverse("pages:problem_statement_list"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["statement_total"] == EXPECTED_CONTEST_TOTAL
    assert response.context["statement_stats"] == {
        "contest_total": EXPECTED_CONTEST_TOTAL,
        "linked_total": EXPECTED_RECORD_COUNT,
        "unlinked_total": EXPECTED_RECORD_COUNT,
        "year_range_label": str(SPAIN_OLYMPIAD_YEAR),
    }
    linked_row = next(
        row
        for row in response.context["statement_table_rows"]
        if row["contest_year_problem"] == f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1"
    )
    assert linked_row["problem_uuid"] == str(linked_statement.problem_uuid)
    assert linked_row["linked_problem_label"] == linked_record.contest_year_problem
    assert linked_row["linked_problem_url"].endswith("#spain-mathematical-olympiad-2026-p1")
    assert "Problem statements" in response.content.decode("utf-8")


def test_problem_statement_analytics_groups_rows_by_contest_and_year_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    linked_record = ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        contest=SPAIN_OLYMPIAD_NAME,
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )
    ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        day_label="Day 1",
        statement_latex="Linked statement preview text",
        linked_problem=linked_record,
    )
    ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=2,
        day_label="Day 1",
        statement_latex="Second Spain statement",
    )
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name=NEPAL_OLYMPIAD_NAME,
        problem_number=1,
        day_label="Day 1",
        statement_latex="Nepal statement",
    )

    response = client.get(reverse("pages:problem_statement_dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["statement_dashboard_total"] == EXPECTED_STATEMENT_SET_TOTAL
    assert response.context["statement_dashboard_statement_total"] == EXPECTED_STATEMENT_ROW_TOTAL
    assert response.context["statement_dashboard_stats"] == {
        "average_statements_per_set": EXPECTED_AVERAGE_STATEMENTS_PER_SET,
        "contest_total": EXPECTED_CONTEST_TOTAL,
        "linked_total": 1,
        "overall_link_rate": EXPECTED_STATEMENT_OVERALL_LINK_RATE,
        "year_range_label": "2025-2026",
    }
    assert response.context["statement_dashboard_leaders"]["biggest"]["contest_year_label"] == (
        f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR}"
    )
    dashboard_row = next(
        row
        for row in response.context["statement_dashboard_rows"]
        if row["contest_year_label"] == f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR}"
    )
    assert dashboard_row["statement_count"] == EXPECTED_STATEMENT_SET_TOTAL
    assert dashboard_row["linked_count"] == 1
    assert dashboard_row["unlinked_count"] == 1
    assert dashboard_row["link_rate"] == EXPECTED_SPAIN_STATEMENT_LINK_RATE
    response_html = response.content.decode("utf-8")
    assert "Problem statement analytics" in response_html
    assert reverse("pages:problem_statement_dashboard") in response_html


def test_latex_preview_parse_action_builds_structured_preview_without_saving(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "preview", "source_text": LATEX_STATEMENT_SAMPLE},
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestProblemStatement.objects.count() == 0
    assert response.context["parsed_statement_payload"]["contest_name"] == SPAIN_OLYMPIAD_NAME
    assert response.context["parsed_statement_payload"]["contest_year"] == SPAIN_OLYMPIAD_YEAR
    assert response.context["parsed_statement_payload"]["problem_count"] == EXPECTED_STATEMENT_PROBLEM_TOTAL
    assert response.context["statement_save_preview"] == {
        "create_count": EXPECTED_STATEMENT_PROBLEM_TOTAL,
        "existing_count": 0,
        "existing_problem_codes": [],
        "unchanged_count": 0,
        "unchanged_problem_codes": [],
        "update_count": 0,
        "update_problem_codes": [],
    }


def test_latex_preview_parse_action_shows_duplicate_warning_summary(client):
    user = UserFactory()
    client.force_login(user)
    parsed_import = parse_contest_problem_statements(LATEX_STATEMENT_SAMPLE)
    ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        day_label=parsed_import.problems[0].day_label,
        statement_latex=parsed_import.problems[0].statement_latex,
    )
    ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=2,
        day_label="Day 9",
        statement_latex="Outdated statement",
    )

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "preview", "source_text": LATEX_STATEMENT_SAMPLE},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["statement_save_preview"] == {
        "create_count": 4,
        "existing_count": 2,
        "existing_problem_codes": ["P1", "P2"],
        "unchanged_count": 1,
        "unchanged_problem_codes": ["P1"],
        "update_count": 1,
        "update_problem_codes": ["P2"],
    }
    assert "Duplicate check before save" in response.content.decode("utf-8")


@override_settings(DEBUG=False)
def test_latex_preview_save_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "save", "source_text": LATEX_STATEMENT_SAMPLE},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert ContestProblemStatement.objects.count() == 0


def test_latex_preview_save_upserts_statement_rows_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        contest=SPAIN_OLYMPIAD_NAME,
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )

    response = client.post(
        reverse("pages:latex_preview"),
        {"action": "save", "source_text": LATEX_STATEMENT_SAMPLE},
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestProblemStatement.objects.count() == EXPECTED_STATEMENT_PROBLEM_TOTAL
    assert response.context["statement_import_result"] == {
        "created_count": EXPECTED_STATEMENT_PROBLEM_TOTAL,
        "linked_problem_count": EXPECTED_RECORD_COUNT,
        "updated_count": 0,
    }
    saved_statement = ContestProblemStatement.objects.get(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
    )
    assert saved_statement.day_label == "Day 1"
    assert saved_statement.linked_problem is not None
    assert saved_statement.problem_uuid == saved_statement.linked_problem.problem_uuid


def test_import_problem_statements_updates_existing_rows():
    statement = ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        day_label="Day 1",
        statement_latex="Old statement",
    )

    result = import_problem_statements(parse_contest_problem_statements(LATEX_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_STATEMENT_PROBLEM_TOTAL - 1
    assert result.updated_count == 1

    saved_statement = ContestProblemStatement.objects.get(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
    )
    assert saved_statement.problem_uuid == statement.problem_uuid
    assert saved_statement.day_label == "Day 1"
    assert "Find the value of a positive integer" in saved_statement.statement_latex


@override_settings(DEBUG=False)
def test_home_exposes_live_library_index_for_authenticated_user(client):
    user = UserFactory()
    client.force_login(user)
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=4,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
    )

    response = client.get(reverse("pages:home"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["library_access_enabled"] is True
    assert response.context["library_overview"]["contest_total"] == EXPECTED_RECORD_COUNT
    assert reverse("users:profile") in response.content.decode("utf-8")
    assert any(
        entry["type"] == "Contest" and entry["label"] == "ISRAEL TST"
        for entry in response.context["search_entries"]
    )
    assert reverse("pages:problem_list") in response.content.decode("utf-8")


def test_problem_list_prioritizes_statement_backed_contests(client):
    user = UserFactory()
    client.force_login(user)
    statement_ready = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2026 P1",
    )
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=4,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
    )
    ContestProblemStatement.objects.create(
        linked_problem=statement_ready,
        contest_year=2026,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Prove that $1+1=2$.",
    )

    response = client.get(reverse("pages:problem_list"))

    assert response.status_code == HTTPStatus.OK
    contest_directory = response.context["contest_directory"]
    assert [row["contest"] for row in contest_directory] == ["IMO", "ISRAEL TST"]
    assert contest_directory[0]["has_statements"] is True
    assert contest_directory[0]["statement_problem_count"] == 1
    assert response.context["problem_listing_stats"]["statement_ready_total"] == 1
    assert "Statement-backed first" in response.content.decode("utf-8")


def test_contest_problem_list_shows_imported_statement_text(client):
    user = UserFactory()
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2026 P1",
    )
    ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=2026,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Prove that $1+1=2$.",
    )

    response = client.get(reverse("pages:contest_problem_list", args=["imo"]))

    assert response.status_code == HTTPStatus.OK
    assert response.context["contest_problem_stats"]["statement_total"] == 1
    assert response.context["statement_rendering_enabled"] is True
    first_problem = response.context["grouped_years"][0]["problems"][0]
    assert first_problem["has_statement"] is True
    assert first_problem["statement_day_label"] == "Day 1"
    assert first_problem["statement_latex"] == "Prove that $1+1=2$."
    content = response.content.decode("utf-8")
    assert "Statement-backed problems rise to the front" in content
    assert "Prove that $1+1=2$." in content
    assert "Statement import updated" in content


def test_home_exposes_live_library_index_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    record = ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=4,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
    )
    ProblemTopicTechnique.objects.create(record=record, technique="LTE", domains=["NT"])

    response = client.get(reverse("pages:home"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["library_access_enabled"] is True
    assert response.context["library_overview"]["contest_total"] == EXPECTED_RECORD_COUNT
    assert response.context["library_overview"]["problem_total"] == EXPECTED_RECORD_COUNT
    contest_entry = next(
        entry
        for entry in response.context["search_entries"]
        if entry["type"] == "Contest" and entry["label"] == "ISRAEL TST"
    )
    assert contest_entry["href"] == reverse("pages:contest_problem_list", args=["israel-tst"])

    problem_entry = next(
        entry
        for entry in response.context["search_entries"]
        if entry["type"] == "Problem" and entry["label"] == "ISRAEL TST 2026 P2"
    )
    assert (
        problem_entry["href"]
        == reverse("pages:contest_problem_list", args=["israel-tst"]) + "#israel-tst-2026-p2"
    )

    topic_entry = next(
        entry
        for entry in response.context["search_entries"]
        if entry["type"] == "Topic tag" and entry["label"] == "LTE"
    )
    assert topic_entry["href"] == reverse("pages:problem_list") + "?q=LTE"
