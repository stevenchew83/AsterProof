from datetime import timedelta
from http import HTTPStatus
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.asymptote_render import AsymptoteRenderResult
from inspinia.pages.asymptote_render import _extract_svg_markup
from inspinia.pages.asymptote_render import build_statement_render_segments
from inspinia.pages.models import ContestMetadata
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.problem_import import ProblemImportValidationError
from inspinia.pages.problem_import import dataframe_from_excel
from inspinia.pages.problem_import import import_problem_dataframe
from inspinia.pages.statement_import import LATEX_STATEMENT_SAMPLE
from inspinia.pages.statement_import import import_problem_statements
from inspinia.pages.statement_import import parse_contest_problem_statements
from inspinia.solutions.models import ProblemSolution
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_RECORD_COUNT = 1
EXPECTED_ONE_TECHNIQUE = 1
EXPECTED_TWO_TECHNIQUES = 2
EXPECTED_MULTI_CONTEST_RENAME_TOTAL = 2
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
USA_TST_YEAR = 2025
USA_TST_NAME = "USA Team Selection Test for IMO"
EXPECTED_USA_TST_PROBLEM_TOTAL = 2
USA_TST_STATEMENT_SAMPLE = (
    "2025 USA Team Selection Test for IMO3\n"
    "Day I Thursday, December 12, 2024\n"
    "1\tLet $n$ be a positive integer.\n"
    "\n"
    "Day 2 Thursday, January 9, 2025\n"
    "2\tLet $a_1, a_2, \\dots$ be real.\n"
)
USA_EGMO_TST_YEAR = 2020
USA_EGMO_TST_NAME = "USA EGMO Team Selection Test"
EXPECTED_USA_EGMO_TST_PROBLEM_TOTAL = 6
USA_EGMO_TST_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "usa_egmo_team_selection_test_sample.txt"
).read_text(encoding="utf-8")
TOURNAMENT_OF_TOWNS_YEAR = 2025
TOURNAMENT_OF_TOWNS_NAME = "TOURNAMENT OF TOWNS"
EXPECTED_TOURNAMENT_OF_TOWNS_PROBLEM_TOTAL = 2
TOURNAMENT_OF_TOWNS_STATEMENT_SAMPLE = (
    "2024/2025 TOURNAMENT OF TOWNS3\n"
    "46th internationl tournament of towns\n"
    "Junior A-Level Paper, Fall 2024\n"
    "P1\tBaron Munchausen took several cards and wrote a positive integer on each one.\n"
    "\n"
    "Maxim Didin\n"
    "\n"
    "gnoka\n"
    "view topic\n"
    "Senior A-Level Paper, Fall 2024\n"
    "P1\tPeter writes a positive integer on the whiteboard.\n"
    "\n"
    "Maxim Didin\n"
    "\n"
    "gnoka\n"
    "view topic\n"
)
SEASON_FIRST_TOURNAMENT_OF_TOWNS_YEAR = 2024
SEASON_FIRST_TOURNAMENT_OF_TOWNS_NAME = "Tournament of Towns"
EXPECTED_SEASON_FIRST_TOURNAMENT_OF_TOWNS_PROBLEM_TOTAL = 3
SEASON_FIRST_TOURNAMENT_OF_TOWNS_STATEMENT_SAMPLE = (
    "2023/2024 Tournament of Towns3\n"
    "45th International Tournament of Towns\n"
    "Fall 2023, Senior A-level\n"
    "1\tSenior one.\n"
    "\n"
    "Alexey Glebov\n"
    "\n"
    "gnoka\n"
    "view topic\n"
    "Fall 2023, Junior A-level\n"
    "1\t1. Junior one.\n"
    "\n"
    "Egor Bakaev\n"
    "\n"
    "gnoka\n"
    "view topic\n"
    "2\t2. Junior two.\n"
    "\n"
    "gnoka\n"
    "view topic\n"
)
TOURNAMENT_OF_TOWNS_2019_YEAR = 2019
TOURNAMENT_OF_TOWNS_2019_NAME = "Tournament Of Towns"
EXPECTED_TOURNAMENT_OF_TOWNS_2019_PROBLEM_TOTAL = 5
TOURNAMENT_OF_TOWNS_2019_STATEMENT_SAMPLE = (
    "2019 Tournament Of Towns3\n"
    "Tournament Of Towns year 2019\n"
    "Spring 2019\n"
    "Junior O-Level\n"
    "1\tJunior O one.\n"
    "\n"
    "(Alexandr Shapovalov)\n"
    "\n"
    "parmenides51\n"
    "view topic\n"
    "Junior A-Level\n"
    "1\tJunior A one.\n"
    "\n"
    "(Mikhail Evdokimov)\n"
    "\n"
    "parmenides51\n"
    "view topic\n"
    "Senior A-Level\n"
    "2\tsame as Junior A p2\n"
    "3\tSenior A three.\n"
    "\n"
    "(Egor Bakaev, Ilya Bogdanov, Pavel Kozhevnikov, Vladimir Rastorguev) (Junior version here)\n"
    "note\n"
    "\n"
    "parmenides51\n"
    "view topic\n"
    "Fall 2019\n"
    "Junior O-Level\n"
    "1\tFallback username dots.\n"
    "\n"
    "L.Lawliet03\n"
    "view topic\n"
)
EXPECTED_LINKED_PROBLEM_MOHS = 4
EXPECTED_USER_ACTIVITY_TOTAL = 3
EXPECTED_USER_ACTIVITY_DATED_TOTAL = 2
EXPECTED_USER_ACTIVITY_UNKNOWN_DATE_TOTAL = 1
EXPECTED_USER_ACTIVITY_CONTEST_TOTAL = 3
EXPECTED_USER_ACTIVITY_VISUAL_TOTAL = 2
EXPECTED_DONE_ONLY_COMPLETION_TOTAL = 4
EXPECTED_DONE_ONLY_EXACT_TOTAL = 0
FAKE_ASYMPTOTE_SVG = '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" /></svg>'


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


def test_parse_contest_problem_statements_supports_roman_day_headers_with_dates():
    parsed_import = parse_contest_problem_statements(USA_TST_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == USA_TST_YEAR
    assert parsed_import.contest_name == USA_TST_NAME
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Day I · Thursday, December 12, 2024",
        "Day 2 · Thursday, January 9, 2025",
    ]


def test_parse_contest_problem_statements_supports_tst_headers_and_strips_trailing_credits():
    parsed_import = parse_contest_problem_statements(USA_EGMO_TST_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == USA_EGMO_TST_YEAR
    assert parsed_import.contest_name == USA_EGMO_TST_NAME
    assert len(parsed_import.problems) == EXPECTED_USA_EGMO_TST_PROBLEM_TOTAL
    assert [problem.problem_number for problem in parsed_import.problems] == [1, 2, 3, 4, 5, 6]
    assert [problem.day_label for problem in parsed_import.problems[:3]] == [
        "TST #1 · Thursday, December 12th, 2019",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:]] == [
        "TST #2 · Thursday, January 23rd, 2020",
    ] * 3
    assert "TST #2" not in parsed_import.problems[2].statement_latex
    assert "Andrew Gu" not in parsed_import.problems[1].statement_latex
    assert "Carl Schildkraut and Milan Haiman" not in parsed_import.problems[2].statement_latex
    assert "Proposed by Ankan Bhattacharya" not in parsed_import.problems[3].statement_latex
    assert "Proposed by Yang Liu" not in parsed_import.problems[4].statement_latex
    assert "a1267ab" not in parsed_import.problems[1].statement_latex
    assert "alifenix-" not in parsed_import.problems[3].statement_latex
    assert "view topic" not in parsed_import.problems[1].statement_latex
    assert "There exists a point $Q$ on the circumcircle" not in parsed_import.problems[1].statement_latex
    assert "there exists a point $Q$ on the circumcircle" in parsed_import.problems[1].statement_latex
    assert "What are the possible values of $r$" in parsed_import.problems[2].statement_latex


def test_parse_contest_problem_statements_supports_tournament_of_towns_sections_and_metadata():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P1"]
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Junior A-Level Paper, Fall 2024",
        "Senior A-Level Paper, Fall 2024",
    ]
    assert "Maxim Didin" not in parsed_import.problems[0].statement_latex
    assert "gnoka" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "Baron Munchausen took several cards" in parsed_import.problems[0].statement_latex
    assert "Peter writes a positive integer on the whiteboard." in parsed_import.problems[1].statement_latex


def test_parse_contest_problem_statements_supports_season_first_tournament_of_towns_sections():
    parsed_import = parse_contest_problem_statements(SEASON_FIRST_TOURNAMENT_OF_TOWNS_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == SEASON_FIRST_TOURNAMENT_OF_TOWNS_YEAR
    assert parsed_import.contest_name == SEASON_FIRST_TOURNAMENT_OF_TOWNS_NAME
    assert len(parsed_import.problems) == EXPECTED_SEASON_FIRST_TOURNAMENT_OF_TOWNS_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Fall 2023, Senior A-level",
        "Fall 2023, Junior A-level",
        "Fall 2023, Junior A-level",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P1", "P2"]
    assert parsed_import.problems[1].statement_latex == "Junior one."
    assert parsed_import.problems[2].statement_latex == "Junior two."
    assert "Alexey Glebov" not in parsed_import.problems[0].statement_latex
    assert "gnoka" not in parsed_import.problems[1].statement_latex
    assert "view topic" not in parsed_import.problems[2].statement_latex


def test_parse_contest_problem_statements_supports_split_season_and_level_tournament_headers():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2019_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_2019_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_2019_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_2019_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Spring 2019 · Junior O-Level",
        "Spring 2019 · Junior A-Level",
        "Spring 2019 · Senior A-Level",
        "Spring 2019 · Senior A-Level",
        "Fall 2019 · Junior O-Level",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P1", "P2", "P3", "P1"]
    assert parsed_import.problems[2].statement_latex == "same as Junior A p2"
    assert parsed_import.problems[3].statement_latex == "Senior A three."
    assert "Junior version here" not in parsed_import.problems[3].statement_latex
    assert "note" not in parsed_import.problems[3].statement_latex
    assert "parmenides51" not in parsed_import.problems[0].statement_latex
    assert "L.Lawliet03" not in parsed_import.problems[4].statement_latex


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


def test_import_problem_statements_persists_long_day_labels():
    result = import_problem_statements(parse_contest_problem_statements(USA_TST_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_USA_TST_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_labels = list(
        ContestProblemStatement.objects.filter(
            contest_year=USA_TST_YEAR,
            contest_name=USA_TST_NAME,
        )
        .order_by("problem_number")
        .values_list("day_label", flat=True),
    )
    assert saved_labels == [
        "Day I · Thursday, December 12, 2024",
        "Day 2 · Thursday, January 9, 2025",
    ]


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


def test_import_problem_statements_supports_tournament_of_towns_duplicate_codes_across_sections():
    result = import_problem_statements(parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_PROBLEM_TOTAL
    assert result.updated_count == 0
    assert ContestProblemStatement.objects.filter(
        contest_year=TOURNAMENT_OF_TOWNS_YEAR,
        contest_name=TOURNAMENT_OF_TOWNS_NAME,
    ).count() == EXPECTED_TOURNAMENT_OF_TOWNS_PROBLEM_TOTAL

    junior_problem = ContestProblemStatement.objects.get(
        contest_year=TOURNAMENT_OF_TOWNS_YEAR,
        contest_name=TOURNAMENT_OF_TOWNS_NAME,
        day_label="Junior A-Level Paper, Fall 2024",
        problem_code="P1",
    )
    senior_problem = ContestProblemStatement.objects.get(
        contest_year=TOURNAMENT_OF_TOWNS_YEAR,
        contest_name=TOURNAMENT_OF_TOWNS_NAME,
        day_label="Senior A-Level Paper, Fall 2024",
        problem_code="P1",
    )
    assert junior_problem.problem_number == 1
    assert senior_problem.problem_number == 1
    assert "Maxim Didin" not in junior_problem.statement_latex


def test_import_problem_statements_supports_season_first_tournament_of_towns_sections():
    result = import_problem_statements(
        parse_contest_problem_statements(SEASON_FIRST_TOURNAMENT_OF_TOWNS_STATEMENT_SAMPLE),
    )

    assert result.created_count == EXPECTED_SEASON_FIRST_TOURNAMENT_OF_TOWNS_PROBLEM_TOTAL
    assert result.updated_count == 0
    assert ContestProblemStatement.objects.filter(
        contest_year=SEASON_FIRST_TOURNAMENT_OF_TOWNS_YEAR,
        contest_name=SEASON_FIRST_TOURNAMENT_OF_TOWNS_NAME,
    ).count() == EXPECTED_SEASON_FIRST_TOURNAMENT_OF_TOWNS_PROBLEM_TOTAL

    senior_problem = ContestProblemStatement.objects.get(
        contest_year=SEASON_FIRST_TOURNAMENT_OF_TOWNS_YEAR,
        contest_name=SEASON_FIRST_TOURNAMENT_OF_TOWNS_NAME,
        day_label="Fall 2023, Senior A-level",
        problem_code="P1",
    )
    junior_problem = ContestProblemStatement.objects.get(
        contest_year=SEASON_FIRST_TOURNAMENT_OF_TOWNS_YEAR,
        contest_name=SEASON_FIRST_TOURNAMENT_OF_TOWNS_NAME,
        day_label="Fall 2023, Junior A-level",
        problem_code="P1",
    )
    assert senior_problem.statement_latex == "Senior one."
    assert junior_problem.statement_latex == "Junior one."


def test_import_problem_statements_supports_split_season_and_level_tournament_headers():
    result = import_problem_statements(parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2019_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_2019_PROBLEM_TOTAL
    assert result.updated_count == 0
    assert ContestProblemStatement.objects.filter(
        contest_year=TOURNAMENT_OF_TOWNS_2019_YEAR,
        contest_name=TOURNAMENT_OF_TOWNS_2019_NAME,
    ).count() == EXPECTED_TOURNAMENT_OF_TOWNS_2019_PROBLEM_TOTAL

    spring_junior_o = ContestProblemStatement.objects.get(
        contest_year=TOURNAMENT_OF_TOWNS_2019_YEAR,
        contest_name=TOURNAMENT_OF_TOWNS_2019_NAME,
        day_label="Spring 2019 · Junior O-Level",
        problem_code="P1",
    )
    spring_senior_a = ContestProblemStatement.objects.get(
        contest_year=TOURNAMENT_OF_TOWNS_2019_YEAR,
        contest_name=TOURNAMENT_OF_TOWNS_2019_NAME,
        day_label="Spring 2019 · Senior A-Level",
        problem_code="P3",
    )
    fall_junior_o = ContestProblemStatement.objects.get(
        contest_year=TOURNAMENT_OF_TOWNS_2019_YEAR,
        contest_name=TOURNAMENT_OF_TOWNS_2019_NAME,
        day_label="Fall 2019 · Junior O-Level",
        problem_code="P1",
    )
    assert spring_junior_o.statement_latex == "Junior O one."
    assert spring_senior_a.statement_latex == "Senior A three."
    assert fall_junior_o.statement_latex == "Fallback username dots."


def test_build_statement_render_segments_preserves_text_around_asymptote_blocks(monkeypatch):
    def fake_render(asy_code: str) -> AsymptoteRenderResult:
        assert "draw((0,0)--(1,1));" in asy_code
        return AsymptoteRenderResult(
            svg_markup=FAKE_ASYMPTOTE_SVG,
            backend="remote",
        )

    monkeypatch.setattr("inspinia.pages.asymptote_render.render_asymptote_svg", fake_render)

    segments = build_statement_render_segments(
        "Before $x$.\n[asy]\nsize(100);\ndraw((0,0)--(1,1));\n[/asy]\nAfter $y$.",
    )

    assert [segment["kind"] for segment in segments] == ["text", "asymptote", "text"]
    assert segments[0]["content"] == "Before $x$.\n"
    assert segments[1]["svg_markup"] == FAKE_ASYMPTOTE_SVG
    assert segments[1]["backend_label"] == "Rendered via Asymptote Web Application"
    assert "size(100);" in segments[1]["code"]
    assert segments[2]["content"] == "\nAfter $y$."


def test_extract_svg_markup_strips_unsafe_svg_content():
    svg_markup = _extract_svg_markup(
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        b"<script>alert(1)</script>"
        b'<circle cx="5" cy="5" r="4" onclick="alert(1)" href="javascript:alert(1)" />'
        b"</svg>",
    )

    assert svg_markup.startswith("<svg")
    assert "<script" not in svg_markup
    assert "onload" not in svg_markup
    assert "onclick" not in svg_markup
    assert "javascript:" not in svg_markup


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


def test_contest_rename_requires_login(client):
    response = client.get(reverse("pages:contest_rename"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:contest_rename')}"


def test_contest_details_requires_login(client):
    response = client.get(reverse("pages:contest_details"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:contest_details')}"


def test_statement_render_preview_requires_login(client):
    response = client.post(
        reverse("pages:statement_render_preview"),
        {"source_text": "[asy]draw((0,0)--(1,1));[/asy]"},
    )
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:statement_render_preview')}"


def test_problem_statement_list_requires_login(client):
    response = client.get(reverse("pages:problem_statement_list"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:problem_statement_list')}"


def test_user_activity_dashboard_requires_login(client):
    response = client.get(reverse("pages:user_activity_dashboard"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:user_activity_dashboard')}"


@override_settings(DEBUG=False)
def test_problem_statement_list_recheck_links_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)
    matching_problem = ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        contest=SPAIN_OLYMPIAD_NAME,
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )
    statement = ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Needs relink",
    )

    response = client.post(
        reverse("pages:problem_statement_list"),
        {"action": "recheck_links"},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    statement.refresh_from_db()
    matching_problem.refresh_from_db()
    assert statement.linked_problem is None


@override_settings(DEBUG=False)
def test_problem_statement_analytics_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:problem_statement_dashboard"))

    assert response.status_code == HTTPStatus.FORBIDDEN


@override_settings(DEBUG=False)
def test_contest_rename_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:contest_rename"))

    assert response.status_code == HTTPStatus.FORBIDDEN


@override_settings(DEBUG=False)
def test_contest_details_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:contest_details"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_contest_rename_renders_inventory_filter_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="USOMO",
        problem="P1",
        contest_year_problem="USOMO 2026 P1",
    )
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name="USA MO",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Source statement",
    )

    response = client.get(reverse("pages:contest_rename"))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert 'id="contest-inventory-filter"' in response_html
    assert 'id="contest-inventory-table"' in response_html
    assert 'id="contest-inventory-match-count"' in response_html
    assert 'id="contest-source-selection-count"' in response_html
    assert "Filter contests, years, or counts" in response_html


def test_contest_details_renders_editor_for_selected_contest(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="USOMO",
        problem="P1",
        contest_year_problem="USOMO 2026 P1",
    )
    ContestMetadata.objects.create(
        contest="USOMO",
        full_name="United States of America Mathematical Olympiad",
        countries=["United States"],
        description_markdown="## Overview\n\nNational olympiad.",
        tags=["Olympiad"],
    )

    response = client.get(reverse("pages:contest_details"), {"contest": "USOMO"})

    assert response.status_code == HTTPStatus.OK
    assert response.context["selected_contest"] == "USOMO"
    response_html = response.content.decode("utf-8")
    assert "Contest details" in response_html
    assert 'id="contest-details-filter"' in response_html
    assert 'id="contest-details-table"' in response_html
    assert 'id="contest-detail-selector"' in response_html
    assert "United States of America Mathematical Olympiad" in response_html
    assert "Description (Markdown)" in response_html


def test_contest_metadata_normalizes_fields():
    metadata = ContestMetadata.objects.create(
        contest="  USA MO  ",
        full_name="  United   States   Mathematical Olympiad  ",
        countries=[" United States ", "united states", " Canada "],
        description_markdown="\n# Overview\n\nTop national olympiad.\n",
        tags=["Olympiad", " olympiad ", " National "],
    )

    metadata.refresh_from_db()

    assert metadata.contest == "USA MO"
    assert metadata.full_name == "United States Mathematical Olympiad"
    assert metadata.countries == ["United States", "Canada"]
    assert metadata.description_markdown == "# Overview\n\nTop national olympiad."
    assert metadata.tags == ["Olympiad", "National"]


def test_contest_details_saves_metadata_for_selected_contest(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="USOMO",
        problem="P1",
        contest_year_problem="USOMO 2026 P1",
    )

    response = client.post(
        reverse("pages:contest_details"),
        {
            "contest": "USOMO",
            "full_name": "United States of America Mathematical Olympiad",
            "countries_text": "United States\nCanada",
            "tags_text": "Olympiad, National",
            "description_markdown": "## Overview\n\nNational olympiad.",
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    metadata = ContestMetadata.objects.get(contest="USOMO")
    assert metadata.full_name == "United States of America Mathematical Olympiad"
    assert metadata.countries == ["United States", "Canada"]
    assert metadata.tags == ["Olympiad", "National"]
    assert metadata.description_markdown == "## Overview\n\nNational olympiad."
    assert any(
        'Saved contest details for "USOMO".' in str(message)
        for message in response.context["messages"]
    )


def test_latex_preview_allows_authenticated_access(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:latex_preview"))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "LaTeX preview" in response_html
    assert 'hdots: "\\\\dots"' in response_html
    assert 'overarc: ["\\\\overset{\\\\frown}{#1}", 1]' in response_html
    assert 'vspace: ["\\\\kern0pt", 1]' in response_html


def test_problem_statement_list_shows_statement_rows_and_link_counts(client):
    user = UserFactory()
    client.force_login(user)
    linked_record = ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        confidence="35M / 33M",
        contest=SPAIN_OLYMPIAD_NAME,
        imo_slot_guess="P2/5",
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )
    ProblemTopicTechnique.objects.create(record=linked_record, technique="LTE", domains=["NT"])
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
    now = timezone.now()
    ContestProblemStatement.objects.filter(pk=linked_statement.pk).update(updated_at=now)
    ContestProblemStatement.objects.filter(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=NEPAL_OLYMPIAD_NAME,
        problem_number=8,
    ).update(updated_at=now - timedelta(days=1))

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
    assert response.context["statement_table_rows"][0]["contest_year_problem"] == (
        f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1"
    )
    assert linked_row["problem_uuid"] == str(linked_statement.problem_uuid)
    assert linked_row["linked_problem_label"] == linked_record.contest_year_problem
    assert linked_row["linked_problem_url"].endswith("#spain-mathematical-olympiad-2026-p1")
    assert linked_row["linked_problem_topic_tags"] == ["LTE"]
    assert linked_row["linked_problem_topic_tag_links"][0]["label"] == "LTE"
    assert linked_row["linked_problem_topic_tag_links"][0]["url"].endswith("?tag=LTE")
    assert linked_row["linked_problem_mohs"] == EXPECTED_LINKED_PROBLEM_MOHS
    assert linked_row["linked_problem_mohs_url"].endswith("?mohs=4")
    assert linked_row["linked_problem_confidence"] == "35M / 33M"
    assert "?q=35M+%2F+33M" in linked_row["linked_problem_confidence_url"]
    assert linked_row["linked_problem_imo_slot_guess_value"] == "2,5"
    assert "?q=2%2C5" in linked_row["linked_problem_imo_slot_url"]
    response_html = response.content.decode("utf-8")
    assert "Problem statements" in response_html
    assert 'id="statement-mohs-min"' in response_html
    assert 'id="statement-mohs-max"' in response_html
    assert 'id="problem-statements-copy"' in response_html
    assert "Copy filtered rows" in response_html
    assert "Filter linked rows by MOHS range" in response_html
    assert "visible: false" in response_html
    assert "formatImoSlotLabel" in response_html
    assert "var updatedAtColumnIndex = statementColumns.length - 1;" in response_html
    assert 'pre: [[updatedAtColumnIndex, "desc"]]' in response_html
    assert "updated_at_sort" in response_html
    assert "renderChipLinks" not in response_html


def test_problem_statement_list_recheck_links_updates_matching_rows_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    matching_problem = ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        contest=SPAIN_OLYMPIAD_NAME,
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )
    statement = ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Needs relink",
    )

    response = client.post(
        reverse("pages:problem_statement_list"),
        {"action": "recheck_links"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    statement.refresh_from_db()
    matching_problem.refresh_from_db()
    assert statement.linked_problem == matching_problem
    assert statement.problem_uuid == matching_problem.problem_uuid
    assert response.context["statement_stats"]["linked_total"] == EXPECTED_RECORD_COUNT
    assert response.context["statement_stats"]["unlinked_total"] == 0
    response_html = response.content.decode("utf-8")
    assert 'id="problem-statements-recheck-links"' in response_html
    assert "Recheck problem links" in response_html
    assert (
        "Rechecked 1 statement row(s): 1 linked, 1 newly linked, 0 skipped, "
        "0 still unlinked, 1 updated."
    ) in response_html


def test_problem_statement_list_recheck_links_skips_ambiguous_duplicate_codes(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    matching_problem = ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        contest=SPAIN_OLYMPIAD_NAME,
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )
    first_statement = ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Duplicate candidate A",
    )
    second_statement = ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        problem_code="P1",
        day_label="Day 2",
        statement_latex="Duplicate candidate B",
    )

    response = client.post(
        reverse("pages:problem_statement_list"),
        {"action": "recheck_links"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    first_statement.refresh_from_db()
    second_statement.refresh_from_db()
    matching_problem.refresh_from_db()
    assert first_statement.linked_problem is None
    assert second_statement.linked_problem is None
    assert response.context["statement_stats"]["linked_total"] == 0
    assert response.context["statement_stats"]["unlinked_total"] == EXPECTED_CONTEST_TOTAL
    response_html = response.content.decode("utf-8")
    assert (
        "Rechecked 2 statement row(s): 0 linked, 0 newly linked, 2 skipped, "
        "2 still unlinked, 0 updated."
    ) in response_html


def test_contest_problem_list_search_matches_hidden_confidence(client):
    user = UserFactory()
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        confidence="35M / 33M",
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2026 P1",
    )

    response = client.get(
        reverse("pages:contest_problem_list", args=["imo"]),
        {"q": "35M / 33M"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["matching_problem_total"] == 1
    filtered_problem = response.context["grouped_years"][0]["problems"][0]
    assert filtered_problem["problem"] == problem.problem


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
    heatmap_payload = response.context["charts_payload"]["statementCountHeatmap"]
    assert heatmap_payload["years"] == ["2025", "2026"]
    assert heatmap_payload["max_value"] == EXPECTED_STATEMENT_SET_TOTAL
    assert heatmap_payload["series"][0]["name"] == SPAIN_OLYMPIAD_NAME
    assert heatmap_payload["series"][0]["data"] == [
        {"x": "2025", "y": 0},
        {"x": "2026", "y": EXPECTED_STATEMENT_SET_TOTAL},
    ]
    year_bar_payload = response.context["charts_payload"]["statementYearBarChart"]
    assert year_bar_payload["labels"] == ["2025", "2026"]
    assert year_bar_payload["values"] == [1, EXPECTED_STATEMENT_ROW_TOTAL - 1]
    response_html = response.content.decode("utf-8")
    assert "Problem statement analytics" in response_html
    assert 'id="chart-statement-heatmap"' in response_html
    assert 'id="chart-year-bars"' in response_html
    assert "Contest-year statement heatmap" in response_html
    assert "Statement rows by year" in response_html
    assert "Bar graph of year-only imported statement coverage across the archive." in response_html
    assert "Contest-year statement volume" not in response_html
    assert "Link rate by contest-year" not in response_html
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
    assert 'footnotesize: ""' in response.content.decode("utf-8")


def test_statement_render_preview_returns_rendered_asymptote_html(client, monkeypatch):
    user = UserFactory()
    client.force_login(user)

    def fake_render(_asy_code: str) -> AsymptoteRenderResult:
        return AsymptoteRenderResult(
            svg_markup=FAKE_ASYMPTOTE_SVG,
            backend="remote",
        )

    monkeypatch.setattr("inspinia.pages.asymptote_render.render_asymptote_svg", fake_render)

    response = client.post(
        reverse("pages:statement_render_preview"),
        {"source_text": "Figure below.\n[asy]\ndraw((0,0)--(1,1));\n[/asy]\nProve $x=y$."},
    )

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["ok"] is True
    assert payload["has_asymptote"] is True
    assert "Asymptote" in payload["html"]
    assert "Rendered via Asymptote Web Application" in payload["html"]
    assert FAKE_ASYMPTOTE_SVG in payload["html"]
    assert "Figure below." in payload["html"]
    assert "Prove $x=y$." in payload["html"]


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


def test_user_activity_dashboard_exposes_solution_workspace_navigation(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert reverse("solutions:my_solution_list") in response.content.decode("utf-8")


def test_user_activity_dashboard_shows_only_current_users_completion_history(client):
    user = UserFactory()
    other_user = UserFactory()
    client.force_login(user)
    today = timezone.localdate()
    recent_date = today - timedelta(days=2)
    earlier_date = today - timedelta(days=35)

    recent_problem = ProblemSolveRecord.objects.create(
        year=today.year,
        topic="ALG",
        mohs=5,
        contest="IMO",
        problem="P1",
        contest_year_problem=f"IMO {today.year} P1",
    )
    earlier_problem = ProblemSolveRecord.objects.create(
        year=today.year - 1,
        topic="NT",
        mohs=4,
        contest="BMO",
        problem="P2",
        contest_year_problem=f"BMO {today.year - 1} P2",
    )
    undated_problem = ProblemSolveRecord.objects.create(
        year=today.year - 2,
        topic="GEO",
        mohs=6,
        contest="EGMO",
        problem="P3",
        contest_year_problem=f"EGMO {today.year - 2} P3",
    )
    other_problem = ProblemSolveRecord.objects.create(
        year=today.year,
        topic="COMB",
        mohs=3,
        contest="USA TST",
        problem="P4",
        contest_year_problem=f"USA TST {today.year} P4",
    )

    UserProblemCompletion.objects.create(
        user=user,
        problem=recent_problem,
        completion_date=recent_date,
    )
    UserProblemCompletion.objects.create(
        user=user,
        problem=earlier_problem,
        completion_date=earlier_date,
    )
    UserProblemCompletion.objects.create(
        user=user,
        problem=undated_problem,
        completion_date=None,
    )
    UserProblemCompletion.objects.create(
        user=other_user,
        problem=other_problem,
        completion_date=today - timedelta(days=1),
    )

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["activity_total"] == EXPECTED_USER_ACTIVITY_TOTAL
    assert response.context["activity_stats"]["contest_total"] == EXPECTED_USER_ACTIVITY_CONTEST_TOTAL
    assert response.context["activity_stats"]["dated_total"] == EXPECTED_USER_ACTIVITY_DATED_TOTAL
    assert (
        response.context["activity_stats"]["unknown_date_total"]
        == EXPECTED_USER_ACTIVITY_UNKNOWN_DATE_TOTAL
    )
    assert response.context["activity_stats"]["latest_completion_date"] == recent_date
    assert response.context["activity_stats"]["current_year_total"] == sum(
        1 for value in (recent_date, earlier_date) if value.year == today.year
    )
    assert response.context["activity_filter_options"] == {
        "completion_years": sorted({str(recent_date.year), str(earlier_date.year)}, reverse=True),
        "contests": ["BMO", "EGMO", "IMO"],
        "date_statuses": ["Known date", "Unknown date"],
        "mohs_values": [4, 5, 6],
        "topics": ["ALG", "GEO", "NT"],
    }
    assert response.context["activity_heatmap"]["exact_total"] == EXPECTED_USER_ACTIVITY_DATED_TOTAL
    assert response.context["activity_heatmap"]["estimated_total"] == EXPECTED_DONE_ONLY_EXACT_TOTAL
    assert response.context["activity_heatmap"]["total_in_window"] == EXPECTED_USER_ACTIVITY_VISUAL_TOTAL
    assert response.context["activity_heatmap"]["uses_estimated_placements"] is False
    assert len(response.context["activity_heatmap_sections"]) == 1
    assert response.context["activity_heatmap_sections"][0]["is_latest"] is True
    assert (
        response.context["activity_heatmap_sections"][0]["heatmap"]["exact_total"]
        == EXPECTED_USER_ACTIVITY_DATED_TOTAL
    )
    assert response.context["activity_heatmap"]["weeks"][0]["month_label"] == (
        today - timedelta(days=364)
    ).strftime("%b")
    assert (
        sum(response.context["activity_charts_payload"]["completionsByMonth"]["exact_values"])
        == EXPECTED_USER_ACTIVITY_DATED_TOTAL
    )
    assert (
        sum(response.context["activity_charts_payload"]["completionsByMonth"]["estimated_values"])
        == EXPECTED_DONE_ONLY_EXACT_TOTAL
    )
    assert (
        sum(response.context["activity_charts_payload"]["completionsByMonth"]["values"])
        == EXPECTED_USER_ACTIVITY_VISUAL_TOTAL
    )
    recent_cell = next(
        day
        for week in response.context["activity_heatmap"]["weeks"]
        for day in week["days"]
        if day["date"] == recent_date.isoformat()
    )
    assert recent_cell["count"] == 1
    assert recent_cell["title"].startswith(recent_date.strftime("%a, %d %b %Y"))
    assert all(
        day["estimated_count"] == 0
        for week in response.context["activity_heatmap"]["weeks"]
        for day in week["days"]
    )
    table_rows = response.context["activity_table_rows"]
    assert [row["problem_label"] for row in table_rows] == [
        recent_problem.contest_year_problem,
        earlier_problem.contest_year_problem,
        undated_problem.contest_year_problem,
    ]
    assert table_rows[0]["problem_url"].endswith(f"#imo-{today.year}-p1")
    assert table_rows[2]["completion_date"] == "Unknown"
    response_html = response.content.decode("utf-8")
    assert "My activity" in response_html
    assert "Completion heatmaps" in response_html
    assert 'id="chart-user-completions-by-month"' in response_html
    assert 'id="user-activity-table"' in response_html
    assert 'id="completion-year-filter"' in response_html
    assert "estimated from" not in response_html
    assert "Zero-completion days stay visible" in response_html
    assert 'class="activity-heatmap-grid"' in response_html
    assert 'class="activity-heatmap-weekdays"' in response_html
    assert "Current window" in response_html
    assert "excluded from these time-based visuals" in response_html
    assert "--activity-heatmap-level-4: #216e39;" in response_html
    assert "--activity-heatmap-level-4: #39d353;" in response_html
    assert 'order: [[0, "desc"], [2, "asc"], [1, "asc"]]' in response_html
    assert reverse("pages:user_activity_dashboard") in response_html


def test_user_activity_dashboard_exposes_previous_year_windows_for_older_history(client):
    user = UserFactory()
    client.force_login(user)
    today = timezone.localdate()
    old_date = today - timedelta(days=400)
    recent_date = today - timedelta(days=10)

    old_problem = ProblemSolveRecord.objects.create(
        year=old_date.year,
        topic="ALG",
        mohs=4,
        contest="Old Contest",
        problem="P1",
        contest_year_problem=f"Old Contest {old_date.year} P1",
    )
    recent_problem = ProblemSolveRecord.objects.create(
        year=recent_date.year,
        topic="NT",
        mohs=5,
        contest="Recent Contest",
        problem="P2",
        contest_year_problem=f"Recent Contest {recent_date.year} P2",
    )
    UserProblemCompletion.objects.create(
        user=user,
        problem=old_problem,
        completion_date=old_date,
    )
    UserProblemCompletion.objects.create(
        user=user,
        problem=recent_problem,
        completion_date=recent_date,
    )

    response = client.get(reverse("pages:user_activity_dashboard"))

    previous_window_end = today - timedelta(days=365)
    previous_window_start = previous_window_end - timedelta(days=364)

    assert response.status_code == HTTPStatus.OK
    assert [section["is_latest"] for section in response.context["activity_heatmap_sections"]] == [
        False,
        True,
    ]
    assert response.context["activity_heatmap"]["exact_total"] == 1
    assert response.context["activity_heatmap"]["total_in_window"] == 1
    earlier_section = response.context["activity_heatmap_sections"][0]
    latest_section = response.context["activity_heatmap_sections"][1]
    assert earlier_section["is_latest"] is False
    assert latest_section["is_latest"] is True
    assert earlier_section["heatmap"]["start_label"] == previous_window_start.isoformat()
    assert earlier_section["heatmap"]["end_label"] == previous_window_end.isoformat()
    assert earlier_section["heatmap"]["exact_total"] == 1
    assert latest_section["heatmap"]["end_label"] == today.isoformat()
    old_cell = next(
        day
        for week in earlier_section["heatmap"]["weeks"]
        for day in week["days"]
        if day["date"] == old_date.isoformat()
    )
    assert old_cell["count"] == 1
    response_html = response.content.decode("utf-8")
    assert 'id="activity-window-select"' not in response_html
    assert previous_window_start.isoformat() in response_html
    assert previous_window_end.isoformat() in response_html
    assert today.isoformat() in response_html
    assert response_html.index(previous_window_end.isoformat()) < response_html.index(today.isoformat())


def test_user_activity_dashboard_estimates_done_rows_across_heatmap_months(client):
    user = UserFactory()
    client.force_login(user)
    today = timezone.localdate()
    unknown_problems = [
        ProblemSolveRecord.objects.create(
            year=today.year - index,
            topic="NT",
            mohs=4 + index,
            contest=f"Contest {index + 1}",
            problem=f"P{index + 1}",
            contest_year_problem=f"Contest {index + 1} {today.year - index} P{index + 1}",
        )
        for index in range(4)
    ]
    for problem in unknown_problems:
        UserProblemCompletion.objects.create(
            user=user,
            problem=problem,
            completion_date=None,
        )

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["activity_stats"]["dated_total"] == EXPECTED_DONE_ONLY_EXACT_TOTAL
    assert response.context["activity_stats"]["unknown_date_total"] == EXPECTED_DONE_ONLY_COMPLETION_TOTAL
    assert response.context["activity_heatmap"]["exact_total"] == EXPECTED_DONE_ONLY_EXACT_TOTAL
    assert response.context["activity_heatmap"]["estimated_total"] == EXPECTED_DONE_ONLY_EXACT_TOTAL
    assert response.context["activity_heatmap"]["total_in_window"] == EXPECTED_DONE_ONLY_EXACT_TOTAL
    assert response.context["activity_heatmap"]["uses_estimated_placements"] is False
    assert response.context["activity_heatmap_sections"] == []
    assert sum(
        day["count"]
        for week in response.context["activity_heatmap"]["weeks"]
        for day in week["days"]
    ) == EXPECTED_DONE_ONLY_EXACT_TOTAL
    assert all(
        day["estimated_count"] == 0
        for week in response.context["activity_heatmap"]["weeks"]
        for day in week["days"]
    )
    assert (
        sum(response.context["activity_charts_payload"]["completionsByMonth"]["exact_values"])
        == EXPECTED_DONE_ONLY_EXACT_TOTAL
    )
    assert (
        sum(response.context["activity_charts_payload"]["completionsByMonth"]["estimated_values"])
        == EXPECTED_DONE_ONLY_EXACT_TOTAL
    )
    assert (
        sum(response.context["activity_charts_payload"]["completionsByMonth"]["values"])
        == EXPECTED_DONE_ONLY_EXACT_TOTAL
    )
    response_html = response.content.decode("utf-8")
    assert "No exact completion dates are available yet." in response_html
    assert "excluded from the heatmaps" in response_html


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
    assert 'id="contest-problem-table"' in content
    assert "sortable table layout" in content
    assert "Prove that $1+1=2$." in content
    assert 'footnotesize: ""' in content
    assert 'overarc: ["\\\\overset{\\\\frown}{#1}", 1]' in content
    assert "Statement import updated" not in content
    assert "UUID:" not in content


def test_contest_problem_list_exposes_solution_workspace_links(client):
    user = UserFactory()
    other_user = UserFactory()
    hidden_draft_author = UserFactory()
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2026 P1",
    )
    ProblemSolution.objects.create(
        problem=problem,
        author=user,
        status=ProblemSolution.Status.DRAFT,
        title="My draft",
    )
    ProblemSolution.objects.create(
        problem=problem,
        author=other_user,
        status=ProblemSolution.Status.PUBLISHED,
        title="Published solution",
    )
    ProblemSolution.objects.create(
        problem=problem,
        author=hidden_draft_author,
        status=ProblemSolution.Status.DRAFT,
        title="Hidden draft",
    )

    response = client.get(reverse("pages:contest_problem_list", args=["imo"]))

    assert response.status_code == HTTPStatus.OK
    first_problem = response.context["grouped_years"][0]["problems"][0]
    assert first_problem["published_solution_total"] == 1
    assert first_problem["has_my_solution"] is True
    assert first_problem["my_solution_status"] == ProblemSolution.Status.DRAFT
    assert first_problem["my_solution_status_label"] == "Draft"
    assert first_problem["solutions_url"] == reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
    assert first_problem["solution_editor_url"] == reverse(
        "solutions:problem_solution_edit",
        args=[problem.problem_uuid],
    )
    response_html = response.content.decode("utf-8")
    assert "Solution page" in response_html
    assert "Edit my draft" in response_html
    assert reverse("solutions:problem_solution_list", args=[problem.problem_uuid]) in response_html
    assert reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]) in response_html


def test_contest_problem_list_filters_by_year_mohs_topic_and_tag(client):
    user = UserFactory()
    client.force_login(user)
    tagged_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=4,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2026 P1",
        confidence="35M / 33M",
    )
    other_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=5,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2025 P2",
        confidence="31M / 30M",
    )
    another_tagged_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=6,
        contest="IMO",
        problem="P3",
        contest_year_problem="IMO 2026 P3",
    )
    ProblemTopicTechnique.objects.create(record=tagged_problem, technique="LTE", domains=["NT"])
    ProblemTopicTechnique.objects.create(
        record=other_problem,
        technique="INVARIANTS",
        domains=["ALG"],
    )
    ProblemTopicTechnique.objects.create(
        record=another_tagged_problem,
        technique="LTE",
        domains=["NT"],
    )
    ContestProblemStatement.objects.create(
        linked_problem=tagged_problem,
        contest_year=2026,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Show that $n=n$.",
    )

    response = client.get(
        reverse("pages:contest_problem_list", args=["imo"]),
        {"year": "2026", "mohs": "4", "topic": "NT", "tag": "LTE"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["selected_year"] == "2026"
    assert response.context["selected_mohs"] == "4"
    assert response.context["selected_topic"] == "NT"
    assert response.context["selected_tag"] == "LTE"
    assert response.context["matching_problem_total"] == EXPECTED_RECORD_COUNT
    assert response.context["filter_options"]["mohs_values"] == [4, 5, 6]
    assert response.context["filter_options"]["tags"] == ["INVARIANTS", "LTE"]
    filtered_problem = response.context["grouped_years"][0]["problems"][0]
    assert filtered_problem["problem"] == "P1"
    assert filtered_problem["topic_tags"][0]["technique"] == "LTE"
    page = response.content.decode("utf-8")
    assert "problem-tag-pill" in page
    assert "LTE" in page
    assert "Confidence:" not in page
    assert "> Imported</span>" not in page


def test_contest_problem_list_renders_asymptote_statement_blocks(client, monkeypatch):
    user = UserFactory()
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="GEO",
        mohs=6,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2026 P2",
    )
    ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=2026,
        contest_name="IMO",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="See the figure.\n[asy]\ndraw((0,0)--(1,1));\n[/asy]\nProve $x=y$.",
    )

    def fake_render(_asy_code: str) -> AsymptoteRenderResult:
        return AsymptoteRenderResult(
            svg_markup=FAKE_ASYMPTOTE_SVG,
            backend="remote",
        )

    monkeypatch.setattr("inspinia.pages.asymptote_render.render_asymptote_svg", fake_render)

    response = client.get(reverse("pages:contest_problem_list", args=["imo"]))

    assert response.status_code == HTTPStatus.OK
    first_problem = response.context["grouped_years"][0]["problems"][0]
    assert first_problem["has_statement"] is True
    assert first_problem["statement_has_asymptote"] is True
    assert [segment["kind"] for segment in first_problem["statement_render_segments"]] == [
        "text",
        "asymptote",
        "text",
    ]
    response_html = response.content.decode("utf-8")
    assert "Rendered via Asymptote Web Application" in response_html
    assert FAKE_ASYMPTOTE_SVG in response_html
    assert "Show Asymptote source" in response_html


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


def test_contest_rename_updates_problem_and_statement_rows_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_name = "Old Team Selection Test"
    target_name = "National Team Selection Test"
    expected_renamed_total = 2
    linked_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest=source_name,
        problem="P1",
        contest_year_problem=f"{source_name} 2026 P1",
    )
    blank_label_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="NT",
        mohs=4,
        contest=source_name,
        problem="P2",
        contest_year_problem="",
    )
    linked_statement = ContestProblemStatement.objects.create(
        linked_problem=linked_problem,
        contest_year=2026,
        contest_name=source_name,
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Linked statement",
    )
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name=source_name,
        problem_number=2,
        problem_code="P2",
        day_label="",
        statement_latex="Standalone statement",
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": [source_name],
            "new_contest_name": f"  {target_name}  ",
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert ProblemSolveRecord.objects.filter(contest=source_name).count() == 0
    assert ProblemSolveRecord.objects.filter(contest=target_name).count() == expected_renamed_total
    updated_linked_problem = ProblemSolveRecord.objects.get(pk=linked_problem.pk)
    updated_blank_label_problem = ProblemSolveRecord.objects.get(pk=blank_label_problem.pk)
    assert updated_linked_problem.contest_year_problem == f"{target_name} 2026 P1"
    assert updated_blank_label_problem.contest_year_problem == ""

    assert ContestProblemStatement.objects.filter(contest_name=source_name).count() == 0
    assert (
        ContestProblemStatement.objects.filter(contest_name=target_name).count()
        == expected_renamed_total
    )
    updated_linked_statement = ContestProblemStatement.objects.get(pk=linked_statement.pk)
    assert updated_linked_statement.contest_year_problem == f"{target_name} 2026 P1"
    assert updated_linked_statement.linked_problem_id == linked_problem.pk
    assert any(
        f'Renamed "{source_name}" into "{target_name}"' in str(message)
        for message in response.context["messages"]
    )


def test_contest_rename_updates_contest_metadata_for_single_source(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_name = "USOMO"
    target_name = "USAMO"
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest=source_name,
        problem="P1",
        contest_year_problem=f"{source_name} 2026 P1",
    )
    ContestMetadata.objects.create(
        contest=source_name,
        full_name="United States of America Mathematical Olympiad",
        countries=["United States"],
        description_markdown="## Overview\n\nCanonical archive contest.",
        tags=["Olympiad", "National"],
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": [source_name],
            "new_contest_name": target_name,
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestMetadata.objects.filter(contest=source_name).count() == 0
    metadata = ContestMetadata.objects.get(contest=target_name)
    assert metadata.full_name == "United States of America Mathematical Olympiad"
    assert metadata.countries == ["United States"]
    assert metadata.description_markdown == "## Overview\n\nCanonical archive contest."
    assert metadata.tags == ["Olympiad", "National"]


def test_contest_rename_merges_into_existing_target_without_conflicts(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_name = "USOMO"
    target_name = "USAMO"
    ProblemSolveRecord.objects.create(
        year=2024,
        topic="ALG",
        mohs=4,
        contest=target_name,
        problem="P1",
        contest_year_problem=f"{target_name} 2024 P1",
    )
    source_statement = ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name=source_name,
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Typoed contest name statement",
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": [source_name],
            "new_contest_name": target_name,
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert ProblemSolveRecord.objects.filter(contest=target_name).count() == 1
    assert ContestProblemStatement.objects.filter(contest_name=source_name).count() == 0
    updated_statement = ContestProblemStatement.objects.get(pk=source_statement.pk)
    assert updated_statement.contest_name == target_name
    assert updated_statement.contest_year_problem == f"{target_name} 2026 P2"
    assert any(
        f'Merged "{source_name}" into "{target_name}"' in str(message)
        for message in response.context["messages"]
    )


def test_contest_rename_merges_contest_metadata_into_existing_target(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_name = "USOMO"
    target_name = "USAMO"
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest=source_name,
        problem="P1",
        contest_year_problem=f"{source_name} 2026 P1",
    )
    ContestMetadata.objects.create(
        contest=source_name,
        full_name="United States of America Mathematical Olympiad",
        countries=["United States"],
        description_markdown="## Overview\n\nCanonical archive contest.",
        tags=["Olympiad", "National"],
    )
    ContestMetadata.objects.create(
        contest=target_name,
        full_name="United States of America Mathematical Olympiad",
        countries=["Canada"],
        description_markdown="## Overview\n\nCanonical archive contest.",
        tags=["Team selection"],
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": [source_name],
            "new_contest_name": target_name,
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestMetadata.objects.filter(contest=source_name).count() == 0
    assert ContestMetadata.objects.filter(contest=target_name).count() == 1
    metadata = ContestMetadata.objects.get(contest=target_name)
    assert metadata.countries == ["Canada", "United States"]
    assert metadata.tags == ["Team selection", "Olympiad", "National"]


def test_contest_rename_rejects_problem_key_collision_when_merging(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_name = "USOMO"
    target_name = "USAMO"
    ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=5,
        contest=source_name,
        problem="P1",
        contest_year_problem=f"{source_name} 2025 P1",
    )
    ProblemSolveRecord.objects.create(
        year=2025,
        topic="NT",
        mohs=4,
        contest=target_name,
        problem="P1",
        contest_year_problem=f"{target_name} 2025 P1",
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": [source_name],
            "new_contest_name": target_name,
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert ProblemSolveRecord.objects.filter(contest=source_name).count() == 1
    assert (
        'Cannot update contest names to "USAMO" because these problem rows would collide after the update: 2025 P1.'
        in response.context["form"].non_field_errors()[0]
    )


def test_contest_rename_rejects_statement_key_collision_when_merging(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_name = "USOMO"
    target_name = "USAMO"
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name=source_name,
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Typoed source statement",
    )
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name=target_name,
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Existing target statement",
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": [source_name],
            "new_contest_name": target_name,
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestProblemStatement.objects.filter(contest_name=source_name).count() == 1
    assert ContestProblemStatement.objects.filter(contest_name=target_name).count() == 1
    assert (
        'Cannot update contest names to "USAMO" because these statement rows would collide '
        "after the update: 2025 Day 1 P2."
        in response.context["form"].non_field_errors()[0]
    )


def test_contest_rename_rejects_conflicting_contest_metadata_full_names(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_names = ["USOMO", "USA MO"]
    target_name = "USAMO"
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest=source_names[0],
        problem="P1",
        contest_year_problem=f"{source_names[0]} 2026 P1",
    )
    ProblemSolveRecord.objects.create(
        year=2025,
        topic="NT",
        mohs=4,
        contest=source_names[1],
        problem="P2",
        contest_year_problem=f"{source_names[1]} 2025 P2",
    )
    ContestMetadata.objects.create(
        contest=source_names[0],
        full_name="United States of America Mathematical Olympiad",
    )
    ContestMetadata.objects.create(
        contest=source_names[1],
        full_name="USA Mathematical Olympiad",
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": source_names,
            "new_contest_name": target_name,
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestMetadata.objects.filter(contest=target_name).count() == 0
    assert ContestMetadata.objects.filter(contest__in=source_names).count() == EXPECTED_MULTI_CONTEST_RENAME_TOTAL
    assert (
        'Cannot update contest names to "USAMO" because contest metadata has conflicting full name '
        "values across: USA MO, USOMO."
        in response.context["form"].non_field_errors()[0]
    )


def test_contest_rename_updates_multiple_source_contests_into_one_target(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_names = ["USOMO", "USA MO"]
    target_name = "USAMO"
    first_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=5,
        contest=source_names[0],
        problem="P1",
        contest_year_problem=f"{source_names[0]} 2025 P1",
    )
    second_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="GEO",
        mohs=4,
        contest=source_names[1],
        problem="P2",
        contest_year_problem=f"{source_names[1]} 2026 P2",
    )
    first_statement = ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name=source_names[0],
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="First source statement",
    )
    second_statement = ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name=source_names[1],
        problem_number=2,
        problem_code="P2",
        day_label="Day 2",
        statement_latex="Second source statement",
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": source_names,
            "new_contest_name": target_name,
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert ProblemSolveRecord.objects.filter(contest__in=source_names).count() == 0
    assert (
        ProblemSolveRecord.objects.filter(contest=target_name).count()
        == EXPECTED_MULTI_CONTEST_RENAME_TOTAL
    )
    assert ContestProblemStatement.objects.filter(contest_name__in=source_names).count() == 0
    assert (
        ContestProblemStatement.objects.filter(contest_name=target_name).count()
        == EXPECTED_MULTI_CONTEST_RENAME_TOTAL
    )
    assert ProblemSolveRecord.objects.get(pk=first_problem.pk).contest_year_problem == f"{target_name} 2025 P1"
    assert ProblemSolveRecord.objects.get(pk=second_problem.pk).contest_year_problem == f"{target_name} 2026 P2"
    assert (
        ContestProblemStatement.objects.get(pk=first_statement.pk).contest_year_problem
        == f"{target_name} 2025 P1"
    )
    assert (
        ContestProblemStatement.objects.get(pk=second_statement.pk).contest_year_problem
        == f"{target_name} 2026 P2"
    )
    assert any(
        f'Updated 2 contest names into "{target_name}"' in str(message)
        for message in response.context["messages"]
    )


def test_contest_rename_rejects_problem_key_collision_across_selected_sources(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_names = ["USOMO", "USA MO"]
    target_name = "USAMO"
    ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=5,
        contest=source_names[0],
        problem="P1",
        contest_year_problem=f"{source_names[0]} 2025 P1",
    )
    ProblemSolveRecord.objects.create(
        year=2025,
        topic="NT",
        mohs=4,
        contest=source_names[1],
        problem="P1",
        contest_year_problem=f"{source_names[1]} 2025 P1",
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": source_names,
            "new_contest_name": target_name,
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert (
        ProblemSolveRecord.objects.filter(contest__in=source_names).count()
        == EXPECTED_MULTI_CONTEST_RENAME_TOTAL
    )
    assert ProblemSolveRecord.objects.filter(contest=target_name).count() == 0
    assert (
        'Cannot update contest names to "USAMO" because these problem rows would collide after the '
        "update: 2025 P1."
        in response.context["form"].non_field_errors()[0]
    )


def test_contest_rename_rejects_statement_key_collision_across_selected_sources(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    source_names = ["USOMO", "USA MO"]
    target_name = "USAMO"
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name=source_names[0],
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="First source statement",
    )
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name=source_names[1],
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Second source statement",
    )

    response = client.post(
        reverse("pages:contest_rename"),
        {
            "source_contests": source_names,
            "new_contest_name": target_name,
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert (
        ContestProblemStatement.objects.filter(contest_name__in=source_names).count()
        == EXPECTED_MULTI_CONTEST_RENAME_TOTAL
    )
    assert ContestProblemStatement.objects.filter(contest_name=target_name).count() == 0
    assert (
        'Cannot update contest names to "USAMO" because these statement rows would collide after the '
        "update: 2025 Day 1 P2."
        in response.context["form"].non_field_errors()[0]
    )
