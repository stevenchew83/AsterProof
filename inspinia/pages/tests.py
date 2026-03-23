import csv
import uuid
from datetime import date
from datetime import timedelta
from http import HTTPStatus
from io import BytesIO
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from inspinia.pages.asymptote_render import AsymptoteRenderResult
from inspinia.pages.asymptote_render import _extract_svg_markup
from inspinia.pages.asymptote_render import build_statement_render_segments
from inspinia.pages.handle_summary_parser import build_handle_summary_preview_payload
from inspinia.pages.handle_summary_parser import parse_handle_summary_text
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
EXPECTED_STATEMENT_EXPORT_COLUMNS = [
    "PROBLEM UUID",
    "LINKED PROBLEM UUID",
    "CONTEST YEAR",
    "CONTEST NAME",
    "CONTEST PROBLEM",
    "DAY LABEL",
    "PROBLEM NUMBER",
    "PROBLEM CODE",
    "STATEMENT LATEX",
]
EXPECTED_STATEMENT_METADATA_EXPORT_COLUMNS = [
    "PROBLEM UUID",
    "CONTEST YEAR",
    "CONTEST NAME",
    "CONTEST PROBLEM",
    "DAY LABEL",
    "PROBLEM NUMBER",
    "PROBLEM CODE",
    "STATEMENT LATEX",
    "TOPIC",
    "MOHS",
    "Confidence",
    "IMO slot guess",
    "Topic tags",
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
CHINA_TST_2024_YEAR = 2024
CHINA_TST_2024_NAME = "China Team Selection Test"
EXPECTED_CHINA_TST_2024_PROBLEM_TOTAL = 24
CHINA_TST_2024_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "china_team_selection_test_2024_sample.txt"
).read_text(encoding="utf-8")
CHINA_TST_2017_YEAR = 2017
CHINA_TST_2017_NAME = "China Team Selection Test"
EXPECTED_CHINA_TST_2017_PROBLEM_TOTAL = 5
CHINA_TST_2017_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "china_team_selection_test_2017_sample.txt"
).read_text(encoding="utf-8")
CHINA_SECOND_ROUND_2025_YEAR = 2025
CHINA_SECOND_ROUND_2025_NAME = "(China) National High School Mathematics League"
EXPECTED_CHINA_SECOND_ROUND_2025_PROBLEM_TOTAL = 8
CHINA_SECOND_ROUND_2025_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "china_second_round_2025_sample.txt"
).read_text(encoding="utf-8")
ISRAEL_TST_2026_YEAR = 2026
ISRAEL_TST_2026_NAME = "Israel TST"
EXPECTED_ISRAEL_TST_2026_PROBLEM_TOTAL = 9
ISRAEL_TST_2026_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "israel_tst_2026_sample.txt"
).read_text(encoding="utf-8")
IRAN_TST_2024_YEAR = 2024
IRAN_TST_2024_NAME = "Iran Team Selection Test"
EXPECTED_IRAN_TST_2024_PROBLEM_TOTAL = 12
IRAN_TST_2024_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "iran_tst_2024_sample.txt"
).read_text(encoding="utf-8")
RUSSIAN_TST_2022_YEAR = 2022
RUSSIAN_TST_2022_NAME = "Russian TST"
EXPECTED_RUSSIAN_TST_2022_PROBLEM_TOTAL = 24
RUSSIAN_TST_2022_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "russian_tst_2022_sample.txt"
).read_text(encoding="utf-8")
RUSSIAN_TST_2019_UNAVAILABLE_YEAR = 2019
RUSSIAN_TST_2019_UNAVAILABLE_NAME = "Russian TST"
EXPECTED_RUSSIAN_TST_2019_UNAVAILABLE_PROBLEM_TOTAL = 3
RUSSIAN_TST_2019_UNAVAILABLE_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "russian_tst_2019_unavailable_sample.txt"
).read_text(encoding="utf-8")
INDONESIA_TST_2025_YEAR = 2025
INDONESIA_TST_2025_NAME = "Indonesia TST"
EXPECTED_INDONESIA_TST_2025_PROBLEM_TOTAL = 17
INDONESIA_TST_2025_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "indonesia_tst_2025_sample.txt"
).read_text(encoding="utf-8")
INDONESIA_TST_2024_YEAR = 2024
INDONESIA_TST_2024_NAME = "Indonesia TST"
EXPECTED_INDONESIA_TST_2024_PROBLEM_TOTAL = 26
INDONESIA_TST_2024_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "indonesia_tst_2024_sample.txt"
).read_text(encoding="utf-8")
MALAYSIAN_IMO_TRAINING_CAMP_2025_YEAR = 2025
MALAYSIAN_IMO_TRAINING_CAMP_2025_NAME = "Malaysian IMO Training Camp"
EXPECTED_MALAYSIAN_IMO_TRAINING_CAMP_2025_PROBLEM_TOTAL = 13
MALAYSIAN_IMO_TRAINING_CAMP_2025_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "malaysian_imo_training_camp_2025_sample.txt"
).read_text(encoding="utf-8")
MALAYSIAN_IMO_TRAINING_CAMP_2024_YEAR = 2024
MALAYSIAN_IMO_TRAINING_CAMP_2024_NAME = "Malaysian IMO Training Camp"
EXPECTED_MALAYSIAN_IMO_TRAINING_CAMP_2024_PROBLEM_TOTAL = 24
MALAYSIAN_IMO_TRAINING_CAMP_2024_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "malaysian_imo_training_camp_2024_sample.txt"
).read_text(encoding="utf-8")
BIMO_2021_YEAR = 2021
BIMO_2021_NAME = "BIMO"
EXPECTED_BIMO_2021_PROBLEM_TOTAL = 5
BIMO_2021_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "bimo_2021_sample.txt"
).read_text(encoding="utf-8")
KOREAN_MO_WINTER_CAMP_2020_YEAR = 2020
KOREAN_MO_WINTER_CAMP_2020_NAME = "Korean MO winter camp"
EXPECTED_KOREAN_MO_WINTER_CAMP_2020_PROBLEM_TOTAL = 8
KOREAN_MO_WINTER_CAMP_2020_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "korean_mo_winter_camp_2020_sample.txt"
).read_text(encoding="utf-8")
ROMANIA_NATIONAL_OLYMPIAD_2025_YEAR = 2025
ROMANIA_NATIONAL_OLYMPIAD_2025_NAME = "Romania National Olympiad"
EXPECTED_ROMANIA_NATIONAL_OLYMPIAD_2025_PROBLEM_TOTAL = 16
ROMANIA_NATIONAL_OLYMPIAD_2025_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "romania_national_olympiad_2025_sample.txt"
).read_text(encoding="utf-8")
ROMANIA_NATIONAL_OLYMPIAD_2015_YEAR = 2015
ROMANIA_NATIONAL_OLYMPIAD_2015_NAME = "Romania National Olympiad"
EXPECTED_ROMANIA_NATIONAL_OLYMPIAD_2015_PROBLEM_TOTAL = 24
ROMANIA_NATIONAL_OLYMPIAD_2015_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "romania_national_olympiad_2015_sample.txt"
).read_text(encoding="utf-8")
KOREA_NATIONAL_OLYMPIAD_2021_YEAR = 2021
KOREA_NATIONAL_OLYMPIAD_2021_NAME = "Korea National Olympiad"
EXPECTED_KOREA_NATIONAL_OLYMPIAD_2021_PROBLEM_TOTAL = 6
KOREA_NATIONAL_OLYMPIAD_2021_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "korea_national_olympiad_2021_sample.txt"
).read_text(encoding="utf-8")
KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_YEAR = 2026
KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_NAME = "Korea Winter Program Practice Test"
EXPECTED_KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_PROBLEM_TOTAL = 6
KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "korea_winter_program_practice_test_2026_sample.txt"
).read_text(encoding="utf-8")
HANDLE_SUMMARY_PARSER_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "handle_summary_parser_sample.txt"
).read_text(encoding="utf-8")
HANDLE_SUMMARY_PARSER_RANGE_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "handle_summary_parser_range_sample.txt"
).read_text(encoding="utf-8")
EN_DASH = "\u2013"
EXPECTED_HANDLE_SUMMARY_ROWS = (
    {
        "confidence": "High",
        "handle": "Polynomial from a sector into a strip",
        "imo_slot": "P1/4",
        "mohs": 15,
        "topic_tags": (
            f"Alg/CA {EN_DASH} polynomials over C; asymptotic leading term; "
            "geometric image condition"
        ),
    },
    {
        "confidence": "Medium",
        "handle": "Cyclic quadrilateral with P, Q, K, T",
        "imo_slot": "P3/6",
        "mohs": 45,
        "topic_tags": (
            f"Geo {EN_DASH} cyclic quadrilateral; pole/polar; power of a point; "
            "projective/metric mix"
        ),
    },
    {
        "confidence": "Medium",
        "handle": "Red-blue cards with repeated averaging",
        "imo_slot": "P3/6",
        "mohs": 40,
        "topic_tags": (
            f"Comb/Alg {EN_DASH} dynamical process; extremal construction; "
            "invariant/potential; averaging"
        ),
    },
    {
        "confidence": "Medium-Low",
        "handle": "70-card stack, 30 colors, top-50/bottom-20",
        "imo_slot": "P2/5",
        "mohs": 35,
        "topic_tags": (
            f"Comb {EN_DASH} invariant/monovariant; extremal process; weighted "
            "potential; exact maximum"
        ),
    },
    {
        "confidence": "Medium",
        "handle": "Determine all λ in the symmetric inequality",
        "imo_slot": "P2/5",
        "mohs": 35,
        "topic_tags": (
            f"Alg {EN_DASH} symmetric inequalities; elementary symmetric sums; "
            "asymptotic extremals; smoothing"
        ),
    },
    {
        "confidence": "Medium",
        "handle": "Recurrence-permutation triples in Z_n",
        "imo_slot": "P3/6",
        "mohs": 40,
        "topic_tags": (
            f"NT/Alg/Comb {EN_DASH} linear recurrences mod n; CRT; "
            "characteristic polynomial; permutation structure"
        ),
    },
)
EXPECTED_HANDLE_SUMMARY_EXPORT_TSV = "\n".join(
    [
        "MOHS\tCONFIDENCE\tIMO SLOT\tTOPICS TAG",
        *(
            f'{row["mohs"]}\t{row["confidence"]}\t{row["imo_slot"]}\t{row["topic_tags"]}'
            for row in EXPECTED_HANDLE_SUMMARY_ROWS
        ),
    ]
)
BALKAN_SHORTLIST_YEAR = 2024
BALKAN_SHORTLIST_NAME = "Balkan MO Shortlist"
EXPECTED_BALKAN_SHORTLIST_PROBLEM_TOTAL = 8
BALKAN_SHORTLIST_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "balkan_shortlist_sample.txt"
).read_text(encoding="utf-8")
JOM_SHORTLIST_2015_YEAR = 2015
JOM_SHORTLIST_2015_NAME = "JOM Shortlist"
EXPECTED_JOM_SHORTLIST_2015_PROBLEM_TOTAL = 2
JOM_SHORTLIST_2015_STATEMENT_SAMPLE = (
    Path(__file__).resolve().parent / "testdata" / "jom_shortlist_2015_sample.txt"
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
CHINA_NATIONAL_OLYMPIAD_2026_YEAR = 2026
CHINA_NATIONAL_OLYMPIAD_2026_NAME = "China National Olympiad"
EXPECTED_CHINA_NATIONAL_OLYMPIAD_2026_PROBLEM_TOTAL = 4
CHINA_NATIONAL_OLYMPIAD_2026_STATEMENT_SAMPLE = (
    "2026 China National Olympiad3\n"
    "Day1\t2025.11.26\n"
    "1\tCompact day one.\n"
    "\n"
    "mathematics2004\n"
    "view topic\n"
    "2\tDay one second problem.\n"
    "\n"
    "CG40\n"
    "view topic\n"
    "Day2\t2025.11.27\n"
    "3\tCompact day two.\n"
    "\n"
    "MathMaxGreat\n"
    "view topic\n"
    "4\tVisible day two statement.\n"
    "Click to reveal hidden text\n"
)
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
TOURNAMENT_OF_TOWNS_2018_YEAR = 2018
TOURNAMENT_OF_TOWNS_2018_NAME = "Tournament Of Towns"
EXPECTED_TOURNAMENT_OF_TOWNS_2018_PROBLEM_TOTAL = 3
TOURNAMENT_OF_TOWNS_2018_STATEMENT_SAMPLE = (
    "2018 Tournament Of Towns3\n"
    "Spring 2018 A-level Junior\n"
    "1.\tThirty nine nonzero numbers are written in a row.\n"
    "\n"
    "Boris Frenkin\n"
    "\n"
    "Invert_DOG_about_centre_O\n"
    "view topic\n"
    "2.\tAladdin has several gold ingots.\n"
    "\n"
    "Alexandr Perepechko\n"
    "\n"
    "Invert_DOG_about_centre_O\n"
    "view topic\n"
    "3.\tYou are in a strange land and you don’t know the language.\n"
    "\n"
    "Nikolay Belukhov\n"
)
TOURNAMENT_OF_TOWNS_2016_YEAR = 2016
TOURNAMENT_OF_TOWNS_2016_NAME = "Tournament Of Towns"
EXPECTED_TOURNAMENT_OF_TOWNS_2016_PROBLEM_TOTAL = 4
TOURNAMENT_OF_TOWNS_2016_STATEMENT_SAMPLE = (
    "2016 Tournament Of Towns3\n"
    "Tournament Of Towns 2016\n"
    "Spring 2016 - Junior A-level\n"
    "1\tJunior spring one.\n"
    "Alexey Tolpygo\n"
    "\n"
    "utkarshgupta\n"
    "view topic\n"
    "Spring 2016 - Senior A-level\n"
    "1\tSame as Junior A-level P1\n"
    "Maxim Prasolov\n"
    "\n"
    "utkarshgupta\n"
    "view topic\n"
    "Oral Round\n"
    "1\tOral round one.\n"
    "Misha57\n"
    "view topic\n"
    "Fall 2016 - Senior A-level\n"
    "1\tFall senior one.\n"
    "(N. Chernyatevya)\n"
    "\n"
    "(Translated from here.)\n"
    "\n"
    "anantmudgal09\n"
    "view topic\n"
)
TOURNAMENT_OF_TOWNS_2010_YEAR = 2010
TOURNAMENT_OF_TOWNS_2010_NAME = "Tournament Of Towns"
EXPECTED_TOURNAMENT_OF_TOWNS_2010_PROBLEM_TOTAL = 4
TOURNAMENT_OF_TOWNS_2010_STATEMENT_SAMPLE = (
    "2010 Tournament Of Towns3\n"
    "Tournament Of Towns 2010\n"
    "Spring - Junior O-Level\n"
    "1\tJunior O one.\n"
    "\n"
    "Goutham\n"
    "view topic\n"
    "Spring - Junior A-Level\n"
    "1\tJunior A one.\n"
    "\n"
    "Goutham\n"
    "view topic\n"
    "Fall - Senior O-Level\n"
    "1\tSenior O one.\n"
    "\n"
    "Goutham\n"
    "view topic\n"
    "Fall - Senior A-Level\n"
    "1\tSenior A one.\n"
    "\n"
    "Goutham\n"
    "view topic\n"
)
TOURNAMENT_OF_TOWNS_2003_YEAR = 2003
TOURNAMENT_OF_TOWNS_2003_NAME = "Tournament Of Towns"
EXPECTED_TOURNAMENT_OF_TOWNS_2003_PROBLEM_TOTAL = 4
TOURNAMENT_OF_TOWNS_2003_STATEMENT_SAMPLE = (
    "2003 Tournament Of Towns3\n"
    "Tournament Of Towns 2003\n"
    "Spring Junior O-Level Paper\n"
    "1\tSpring junior O one.\n"
    "\n"
    "Amir Hossein\n"
    "view topic\n"
    "Spring Junior A-Level Paper\n"
    "1\tSpring junior A one.\n"
    "\n"
    "Amir Hossein\n"
    "view topic\n"
    "Fall Senior O-Level\n"
    "1\tFall senior O one.\n"
    "\n"
    "Goutham\n"
    "view topic\n"
    "Fall Senior A-Level\n"
    "1\tFall senior A one.\n"
    "\n"
    "Goutham\n"
    "view topic\n"
)
TOURNAMENT_OF_TOWNS_2002_YEAR = 2002
TOURNAMENT_OF_TOWNS_2002_NAME = "Tournament Of Towns"
EXPECTED_TOURNAMENT_OF_TOWNS_2002_PROBLEM_TOTAL = 4
TOURNAMENT_OF_TOWNS_2002_STATEMENT_SAMPLE = (
    "2002 Tournament Of Towns3\n"
    "Tournament Of Towns 2002\n"
    "I. Spring - Junior O-Level\n"
    "1\tSpring junior O one.\n"
    "\n"
    "joybangla\n"
    "view topic\n"
    "I. Spring - Senior - A-Level\n"
    "1\tSpring senior A one.\n"
    "\n"
    "joybangla\n"
    "view topic\n"
    "II. Fall - Junior - A-Level\n"
    "1\tFall junior A one.\n"
    "\n"
    "joybangla\n"
    "view topic\n"
    "II. Fall - Senior - O-Level\n"
    "1\tFall senior O one.\n"
    "\n"
    "joybangla\n"
    "view topic\n"
)
TOURNAMENT_OF_TOWNS_2002_MULTILINE_YEAR = 2002
TOURNAMENT_OF_TOWNS_2002_MULTILINE_NAME = "Tournament Of Towns"
EXPECTED_TOURNAMENT_OF_TOWNS_2002_MULTILINE_PROBLEM_TOTAL = 2
TOURNAMENT_OF_TOWNS_2002_MULTILINE_STATEMENT_SAMPLE = (
    "2002 Tournament Of Towns3\n"
    "Tournament Of Towns 2002\n"
    "I. Spring - Junior O-Level\n"
    "1\n"
    "Spring multiline one.\n"
    "Continues here.\n"
    "\n"
    "joybangla\n"
    "view topic\n"
    "II. Fall - Senior - A-Level\n"
    "1\n"
    "Fall multiline one.\n"
    "\n"
    "joybangla\n"
    "view topic\n"
)
TOURNAMENT_OF_TOWNS_1997_YEAR = 1997
TOURNAMENT_OF_TOWNS_1997_NAME = "Tournament Of Towns"
EXPECTED_TOURNAMENT_OF_TOWNS_1997_PROBLEM_TOTAL = 7
TOURNAMENT_OF_TOWNS_1997_STATEMENT_SAMPLE = (
    "1997 Tournament Of Towns3\n"
    "Tournament Of Towns 1997\n"
    "1997 Spring\n"
    "Juniors\n"
    "O Level\n"
    "(524) 1\tSpring junior O one.\n"
    "\n"
    "(AI Galochkin)\n"
    "\n"
    "parmenides51\n"
    "view topic\n"
    "A Level\n"
    "(529) 2\tSpring junior A two.\n"
    "\n"
    "(AK Tolpygo)\n"
    "\n"
    "parmenides51\n"
    "view topic\n"
    "Seniors\n"
    "O Level\n"
    "(536) 1\tSpring senior O one.\n"
    "\n"
    "(V Proizvolov)\n"
    "\n"
    "parmenides51\n"
    "view topic\n"
    "A Level\n"
    "1\tsame as JA2 (529)\n"
    "(541) 2\tSpring senior A two.\n"
    "\n"
    "parmenides51\n"
    "view topic\n"
    "Autumn 1997\n"
    "Juniors\n"
    "O Level\n"
    "(547) 1\tAutumn junior O one.\n"
    "\n"
    "(Folklore)\n"
    "\n"
    "parmenides51\n"
    "view topic\n"
    "A Level\n"
    "(551) 1\tAutumn junior A one.\n"
    "\n"
    "(A Berzinsh)\n"
)
EXPECTED_LINKED_PROBLEM_MOHS = 4
EXPECTED_USER_ACTIVITY_TOTAL = 3
EXPECTED_USER_ACTIVITY_DATED_TOTAL = 2
EXPECTED_USER_ACTIVITY_UNKNOWN_DATE_TOTAL = 1
EXPECTED_USER_ACTIVITY_CONTEST_TOTAL = 3
EXPECTED_USER_ACTIVITY_IMPORTED_TOTAL = 2
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


def _csv_upload(*rows: dict) -> SimpleUploadedFile:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    return SimpleUploadedFile(
        "problem-statements.csv",
        buffer.getvalue().encode("utf-8-sig"),
        content_type="text/csv",
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


def test_import_problem_dataframe_updates_duplicate_problem_key_row_by_problem_uuid():
    first_record = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=4,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
        topic_tags="Topic tags: ALG - first",
    )
    second_record = ProblemSolveRecord.objects.create(
        year=2026,
        topic="GEO",
        mohs=7,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
        topic_tags="Topic tags: GEO - second",
    )

    dataframe = _analytics_rows(
        {
            "PROBLEM UUID": str(second_record.problem_uuid),
            "YEAR": 2026,
            "TOPIC": "NT",
            "MOHS": UPDATED_MOHS,
            "CONTEST": "ISRAEL TST",
            "PROBLEM": "P2",
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
            "Topic tags": "Topic tags: NT - LTE",
        },
    )

    result = import_problem_dataframe(dataframe, replace_tags=True)

    assert result.n_records == EXPECTED_RECORD_COUNT
    first_record.refresh_from_db()
    second_record.refresh_from_db()
    assert first_record.topic == "ALG"
    assert first_record.mohs == 4
    assert second_record.topic == "NT"
    assert second_record.mohs == UPDATED_MOHS
    assert second_record.problem_uuid != first_record.problem_uuid


def test_import_problem_dataframe_skips_ambiguous_duplicate_problem_key_without_problem_uuid():
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=4,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
    )
    ProblemSolveRecord.objects.create(
        year=2026,
        topic="GEO",
        mohs=7,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
    )

    dataframe = _analytics_rows(
        {
            "YEAR": 2026,
            "TOPIC": "NT",
            "MOHS": UPDATED_MOHS,
            "CONTEST": "ISRAEL TST",
            "PROBLEM": "P2",
            "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
            "Topic tags": "Topic tags: NT - LTE",
        },
    )

    result = import_problem_dataframe(dataframe, replace_tags=True)

    assert result.n_records == 0
    assert any(
        "Add PROBLEM UUID to disambiguate." in warning
        for warning in result.warnings
    )


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


def test_parse_contest_problem_statements_supports_numbered_tst_day_headers():
    parsed_import = parse_contest_problem_statements(CHINA_TST_2024_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == CHINA_TST_2024_YEAR
    assert parsed_import.contest_name == CHINA_TST_2024_NAME
    assert len(parsed_import.problems) == EXPECTED_CHINA_TST_2024_PROBLEM_TOTAL
    assert [problem.problem_number for problem in parsed_import.problems] == list(range(1, 25))
    assert [problem.day_label for problem in parsed_import.problems[:3]] == [
        "TST #1 · Day 1 (March 5, 2024, Beijing)",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:6]] == [
        "TST #1 · Day 2 (March 6, 2024, Beijing)",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[6:9]] == [
        "TST #1 · Day 3 (March 10, 2024, Beijing)",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[9:]] == [
        "TST #1 · Day 4 (March 11, Beijing)",
    ] * 15
    assert "TST 1" not in parsed_import.problems[0].statement_latex
    assert "Created by Liang Xiao" not in parsed_import.problems[0].statement_latex
    assert "Proposed by Bin Wang" not in parsed_import.problems[2].statement_latex
    assert "EthanWYX2009" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "interior of each edge of $P$" in parsed_import.problems[0].statement_latex
    assert "there exists three elements $a,b,c\\in S$" in parsed_import.problems[3].statement_latex
    assert "at least $2024$ of these points is at most distance $1$ away from $l$" in (
        parsed_import.problems[-1].statement_latex
    )


def test_parse_contest_problem_statements_supports_split_tst_and_day_headers():
    parsed_import = parse_contest_problem_statements(CHINA_TST_2017_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == CHINA_TST_2017_YEAR
    assert parsed_import.contest_name == CHINA_TST_2017_NAME
    assert len(parsed_import.problems) == EXPECTED_CHINA_TST_2017_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P4", "P1", "P1", "P2"]
    assert [problem.day_label for problem in parsed_import.problems] == [
        "TST #1 · Day 1",
        "TST #1 · Day 2",
        "TST #2 · Day 1",
        "TST #5",
        "TST #5",
    ]
    assert "HuangZhen" not in parsed_import.problems[0].statement_latex
    assert "fattypiggy123" not in parsed_import.problems[2].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "solid regular octahedron" in parsed_import.problems[0].statement_latex
    assert "pairwise distinct in mod $m$" in parsed_import.problems[2].statement_latex
    assert "degree not greater than m" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_title_line_and_year_prefixed_sections():
    parsed_import = parse_contest_problem_statements(CHINA_SECOND_ROUND_2025_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == CHINA_SECOND_ROUND_2025_YEAR
    assert parsed_import.contest_name == CHINA_SECOND_ROUND_2025_NAME
    assert len(parsed_import.problems) == EXPECTED_CHINA_SECOND_ROUND_2025_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == [
        "P1",
        "P2",
        "P3",
        "P4",
        "P1",
        "P2",
        "P3",
        "P4",
    ]
    assert [problem.day_label for problem in parsed_import.problems[:4]] == ["China Second Round A"] * 4
    assert [problem.day_label for problem in parsed_import.problems[4:]] == ["China Second Round B"] * 4
    assert "steven_zhang123" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "lines \\(AD\\), \\(BE\\), and \\(CF\\) are concurrent." in parsed_import.problems[0].statement_latex
    assert "Alice guarantees that she can guess $N$" in parsed_import.problems[3].statement_latex
    assert "possible value of $b$" in parsed_import.problems[4].statement_latex
    assert "resulting number remains a multiple of $n$." in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_test_headers_with_dates():
    parsed_import = parse_contest_problem_statements(ISRAEL_TST_2026_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == ISRAEL_TST_2026_YEAR
    assert parsed_import.contest_name == ISRAEL_TST_2026_NAME
    assert len(parsed_import.problems) == EXPECTED_ISRAEL_TST_2026_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems[:3]] == ["P1", "P2", "P3"]
    assert [problem.day_label for problem in parsed_import.problems[:3]] == ["Test 1 · 17/11/2025"] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:6]] == ["Test 2 · 18/11/2025"] * 3
    assert [problem.day_label for problem in parsed_import.problems[6:]] == ["Test 4 · 28/1/2026"] * 3
    assert "Zsigmondy" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "$P,I,N$ are collinear." in parsed_import.problems[0].statement_latex
    assert "constant C, independent on the number of ants" in parsed_import.problems[4].statement_latex
    assert "at most $\\binom{n}{2}$ turns." in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_exam_day_headers():
    parsed_import = parse_contest_problem_statements(IRAN_TST_2024_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == IRAN_TST_2024_YEAR
    assert parsed_import.contest_name == IRAN_TST_2024_NAME
    assert len(parsed_import.problems) == EXPECTED_IRAN_TST_2024_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems[:3]] == ["P1", "P2", "P3"]
    assert [problem.day_label for problem in parsed_import.problems[:3]] == ["First exam · Day 1"] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:6]] == ["First exam · Day 2"] * 3
    assert [problem.day_label for problem in parsed_import.problems[6:9]] == ["Second exam · Day 1"] * 3
    assert [problem.day_label for problem in parsed_import.problems[9:]] == ["Second exam · Day 2"] * 3
    assert "Shayan-TayefehIR" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "Proposed by" not in parsed_import.problems[0].statement_latex
    assert "find the maximum possible number for the diameter of $G$" in parsed_import.problems[0].statement_latex
    assert "there doesn't exist square of a non-constant polynomial" in parsed_import.problems[7].statement_latex
    assert "the circle with diameter $RS$ is tangent to circumcircle" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_year_suffix_headers_with_day_dates():
    parsed_import = parse_contest_problem_statements(RUSSIAN_TST_2022_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == RUSSIAN_TST_2022_YEAR
    assert parsed_import.contest_name == RUSSIAN_TST_2022_NAME
    assert len(parsed_import.problems) == EXPECTED_RUSSIAN_TST_2022_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems[:3]] == ["P1", "P2", "P3"]
    assert [problem.day_label for problem in parsed_import.problems[:3]] == ["Day 1 · October 16, 2021"] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:6]] == ["Day 2 · October 17, 2021"] * 3
    assert [problem.day_label for problem in parsed_import.problems[6:9]] == ["Day 3 · January 12, 2022"] * 3
    assert [problem.day_label for problem in parsed_import.problems[9:12]] == ["Day 4 · January 13, 2022"] * 3
    assert [problem.day_label for problem in parsed_import.problems[12:15]] == ["Day 5 · February 16, 2022"] * 3
    assert [problem.day_label for problem in parsed_import.problems[15:18]] == ["Day 6 · February 17, 2022"] * 3
    assert [problem.day_label for problem in parsed_import.problems[18:21]] == ["Day 7 · May 12, 2022"] * 3
    assert [problem.day_label for problem in parsed_import.problems[21:]] == ["Day 8 · May 13, 2022"] * 3
    assert "amuthup" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "Carl Schildkraut" not in parsed_import.problems[0].statement_latex
    assert "Proposed by" not in parsed_import.problems[3].statement_latex
    assert "Pakawut Jiradilok" not in parsed_import.problems[2].statement_latex
    assert "Find the largest value of $m$ for which this task is $\\text{\\emph{not}}$ possible." in (
        parsed_import.problems[0].statement_latex
    )
    assert "Alice can move the red bead to $1$ in at most $2021$ moves." in parsed_import.problems[1].statement_latex
    assert "the rabbit can determine the cell in which the rabbit started." not in (
        parsed_import.problems[5].statement_latex
    )
    assert "the hunter can determine the cell in which the rabbit started." in (
        parsed_import.problems[5].statement_latex
    )
    assert "there exists a finite subset $B\\subset A$" in parsed_import.problems[8].statement_latex
    assert "has only finitely many solutions in positive integers." in parsed_import.problems[-2].statement_latex


def test_parse_contest_problem_statements_supports_unavailable_placeholder_problems():
    parsed_import = parse_contest_problem_statements(RUSSIAN_TST_2019_UNAVAILABLE_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == RUSSIAN_TST_2019_UNAVAILABLE_YEAR
    assert parsed_import.contest_name == RUSSIAN_TST_2019_UNAVAILABLE_NAME
    assert len(parsed_import.problems) == EXPECTED_RUSSIAN_TST_2019_UNAVAILABLE_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P2", "P3"]
    assert [problem.day_label for problem in parsed_import.problems] == ["Day 6 · May 7, 2019"] * 3
    assert parsed_import.problems[0].statement_latex == "Unavailable"
    assert "view topic" not in parsed_import.problems[1].statement_latex
    assert "Proposed by" not in parsed_import.problems[2].statement_latex


def test_parse_contest_problem_statements_supports_roman_tests_and_generic_sections():
    parsed_import = parse_contest_problem_statements(INDONESIA_TST_2025_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == INDONESIA_TST_2025_YEAR
    assert parsed_import.contest_name == INDONESIA_TST_2025_NAME
    assert len(parsed_import.problems) == EXPECTED_INDONESIA_TST_2025_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems[:3]] == [
        "Test I · Saturday, 8 March 2025",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:6]] == [
        "Test II · Sunday, 9 March 2025",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[6:11]] == [
        "APMO Unofficial",
    ] * 5
    assert [problem.day_label for problem in parsed_import.problems[11:14]] == [
        "Test III · Saturday, 15 March 2025",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[14:]] == [
        "Test IV · Sunday, 16 March 2025",
    ] * 3
    assert "KevinYang2.71" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "Time: 5 Hours" not in parsed_import.problems[0].statement_latex
    assert "all even cool numbers" in parsed_import.problems[1].statement_latex
    assert "$PQ$ is parallel to $AB$." in parsed_import.problems[2].statement_latex
    assert "$P$ strictly lies in the interior of circle $\\Gamma$" in parsed_import.problems[6].statement_latex
    assert "all integers $n$ such that every polynomial" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_round_test_headers_and_letter_codes():
    parsed_import = parse_contest_problem_statements(INDONESIA_TST_2024_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == INDONESIA_TST_2024_YEAR
    assert parsed_import.contest_name == INDONESIA_TST_2024_NAME
    assert len(parsed_import.problems) == EXPECTED_INDONESIA_TST_2024_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems[:4]] == ["A", "C", "G", "N"]
    assert [problem.day_label for problem in parsed_import.problems[:4]] == [
        "First Round · Test 1 (29 February 2024)",
    ] * 4
    assert [problem.day_label for problem in parsed_import.problems[4:8]] == [
        "First Round · Test 2 (3 March 2024)",
    ] * 4
    assert [problem.day_label for problem in parsed_import.problems[8:12]] == [
        "First Round · Test 3 (7 March 2024)",
    ] * 4
    assert [problem.day_label for problem in parsed_import.problems[12:17]] == [
        "Second Round · APMO 2024 (12 March 2024)",
    ] * 5
    assert [problem.day_label for problem in parsed_import.problems[17:20]] == [
        "Second Round · Test 1 (15 March 2024)",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[20:23]] == [
        "Second Round · Test 2 (17 March 2024)",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[23:]] == [
        "Second Round · Test 3 (19 March 2024)",
    ] * 3
    assert "amogususususus" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "$max\\{ |x|,|y|,|z|\\} \\le 1$." in parsed_import.problems[0].statement_latex
    assert "$EO$ passes through the center of $w$." in parsed_import.problems[2].statement_latex
    assert "the points $A, X$, and $Y$ are collinear." in parsed_import.problems[12].statement_latex
    assert "the common difference of such an arithmetic progression." in parsed_import.problems[11].statement_latex
    assert "the circumcircles of triangles $BXD$ and $CYE$" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_named_sections_with_separate_date_lines():
    parsed_import = parse_contest_problem_statements(MALAYSIAN_IMO_TRAINING_CAMP_2025_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == MALAYSIAN_IMO_TRAINING_CAMP_2025_YEAR
    assert parsed_import.contest_name == MALAYSIAN_IMO_TRAINING_CAMP_2025_NAME
    assert len(parsed_import.problems) == EXPECTED_MALAYSIAN_IMO_TRAINING_CAMP_2025_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems[:8]] == [
        "BIMO 1 Christmas Test · December 25, 2024",
    ] * 8
    assert [problem.day_label for problem in parsed_import.problems[8:]] == [
        "Junior Olympiad of Malaysia 2025 · January 19, 2025",
    ] * 5
    assert [problem.problem_code for problem in parsed_import.problems[:3]] == ["P1", "P2", "P3"]
    assert [problem.problem_code for problem in parsed_import.problems[8:11]] == ["P1", "P2", "P3"]
    assert "quacksaysduck" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "$v_p(q^n+n^q)$ unbounded" in parsed_import.problems[0].statement_latex
    assert "the minimum $n$ such that Megavan has a winning strategy." in parsed_import.problems[10].statement_latex
    assert "the points $I$, $V$, $A$, $N$ are concyclic." in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_named_sections_with_day_subsections():
    parsed_import = parse_contest_problem_statements(MALAYSIAN_IMO_TRAINING_CAMP_2024_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == MALAYSIAN_IMO_TRAINING_CAMP_2024_YEAR
    assert parsed_import.contest_name == MALAYSIAN_IMO_TRAINING_CAMP_2024_NAME
    assert len(parsed_import.problems) == EXPECTED_MALAYSIAN_IMO_TRAINING_CAMP_2024_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems[:5]] == [
        "Junior Olympiad of Malaysia 2024 · February 17, 2024",
    ] * 5
    assert [problem.day_label for problem in parsed_import.problems[5:10]] == [
        "APMO Camp Selection Test 2024 · February 17, 2024",
    ] * 5
    assert [problem.day_label for problem in parsed_import.problems[10:13]] == [
        "IMO Team Selection Test 2024 · Day 1 · April 13, 2024",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[13:16]] == [
        "IMO Team Selection Test 2024 · Day 2 · April 14, 2024",
    ] * 3
    assert [problem.day_label for problem in parsed_import.problems[16:20]] == [
        "Malaysian Squad Selection Test 2024 · Day 1 · August 24, 2024",
    ] * 4
    assert [problem.day_label for problem in parsed_import.problems[20:]] == [
        "Malaysian Squad Selection Test 2024 · Day 2 · August 25, 2024",
    ] * 4
    assert [problem.problem_code for problem in parsed_import.problems[10:16]] == [
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
        "P6",
    ]
    assert [problem.problem_code for problem in parsed_import.problems[16:]] == [
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
        "P6",
        "P7",
        "P8",
    ]
    assert "the_universe6626" not in parsed_import.problems[0].statement_latex
    assert "navi_09220114" not in parsed_import.problems[5].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "Proposed Ivan Chan Guan Yu" not in parsed_import.problems[20].statement_latex
    assert "$JB = JM$." in parsed_import.problems[0].statement_latex
    assert "the line $PZ$ always passes through a fixed point" in parsed_import.problems[6].statement_latex
    assert "$AX$ is parallel to $BC$." in parsed_import.problems[10].statement_latex
    assert "the line $KL$, $\\ell$, and the line through the centers" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_nested_bimo_sections():
    parsed_import = parse_contest_problem_statements(BIMO_2021_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == BIMO_2021_YEAR
    assert parsed_import.contest_name == BIMO_2021_NAME
    assert len(parsed_import.problems) == EXPECTED_BIMO_2021_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "BIMO 1 · Problem Solving Session",
        "Mock IMO Test",
        "Mock IMO Test",
        "Mock IMO Test",
        "BIMO 2 · Test 1 (Geometry)",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P1", "P2", "P3", "P2"]
    assert "navi_09220114" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "multiple that is good." in parsed_import.problems[0].statement_latex
    assert "$KM\\perp EF$." in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_hash_numbered_korean_winter_camp_problems():
    parsed_import = parse_contest_problem_statements(KOREAN_MO_WINTER_CAMP_2020_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == KOREAN_MO_WINTER_CAMP_2020_YEAR
    assert parsed_import.contest_name == KOREAN_MO_WINTER_CAMP_2020_NAME
    assert len(parsed_import.problems) == EXPECTED_KOREAN_MO_WINTER_CAMP_2020_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Korean MO winter camp Test 1",
    ] * 8
    assert [problem.problem_code for problem in parsed_import.problems] == [
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
        "P6",
        "P7",
        "P8",
    ]
    assert "MNJ2357" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "$Q(mn)$ and $Q(m)Q(n)$" in parsed_import.problems[2].statement_latex
    assert "hamiltonian circuit exist for the given graph" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_grade_sections_for_romania_national_olympiad():
    parsed_import = parse_contest_problem_statements(ROMANIA_NATIONAL_OLYMPIAD_2025_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == ROMANIA_NATIONAL_OLYMPIAD_2025_YEAR
    assert parsed_import.contest_name == ROMANIA_NATIONAL_OLYMPIAD_2025_NAME
    assert len(parsed_import.problems) == EXPECTED_ROMANIA_NATIONAL_OLYMPIAD_2025_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems[:4]] == ["Grade 9"] * 4
    assert [problem.day_label for problem in parsed_import.problems[4:8]] == ["Grade 10"] * 4
    assert [problem.day_label for problem in parsed_import.problems[8:12]] == ["Grade 11"] * 4
    assert [problem.day_label for problem in parsed_import.problems[12:]] == ["Grade 12"] * 4
    assert [problem.problem_code for problem in parsed_import.problems[:4]] == ["P1", "P2", "P3", "P4"]
    assert [problem.problem_code for problem in parsed_import.problems[12:]] == ["P1", "P2", "P3", "P4"]
    assert "Ciobi_" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "the equation has at most $2$ real solutions." in parsed_import.problems[2].statement_latex
    assert "has at least $p$ coefficients equal to $1$." in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_grade_level_sections_for_older_romania_national_olympiad():
    parsed_import = parse_contest_problem_statements(ROMANIA_NATIONAL_OLYMPIAD_2015_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == ROMANIA_NATIONAL_OLYMPIAD_2015_YEAR
    assert parsed_import.contest_name == ROMANIA_NATIONAL_OLYMPIAD_2015_NAME
    assert len(parsed_import.problems) == EXPECTED_ROMANIA_NATIONAL_OLYMPIAD_2015_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems[:4]] == ["Grade level 7"] * 4
    assert [problem.day_label for problem in parsed_import.problems[4:8]] == ["Grade level 8"] * 4
    assert [problem.day_label for problem in parsed_import.problems[8:12]] == ["Grade level 9"] * 4
    assert [problem.day_label for problem in parsed_import.problems[12:16]] == ["Grade level 10"] * 4
    assert [problem.day_label for problem in parsed_import.problems[16:20]] == ["Grade level 11"] * 4
    assert [problem.day_label for problem in parsed_import.problems[20:]] == ["Grade level 12"] * 4
    assert [problem.problem_code for problem in parsed_import.problems[:4]] == ["P1", "P2", "P3", "P4"]
    assert [problem.problem_code for problem in parsed_import.problems[20:]] == ["P1", "P2", "P3", "P4"]
    assert "parmenides51" not in parsed_import.problems[0].statement_latex
    assert "CatalinBordea" not in parsed_import.problems[8].statement_latex
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "then $M$ is the middle of $CD$." in parsed_import.problems[2].statement_latex
    assert "there exists a function $ \\xi" in parsed_import.problems[-1].statement_latex


def test_parse_contest_problem_statements_supports_part_headers_with_p_prefixed_problems():
    parsed_import = parse_contest_problem_statements(KOREA_NATIONAL_OLYMPIAD_2021_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == KOREA_NATIONAL_OLYMPIAD_2021_YEAR
    assert parsed_import.contest_name == KOREA_NATIONAL_OLYMPIAD_2021_NAME
    assert len(parsed_import.problems) == EXPECTED_KOREA_NATIONAL_OLYMPIAD_2021_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems[:3]] == ["Part 1"] * 3
    assert [problem.day_label for problem in parsed_import.problems[3:]] == ["Part 2"] * 3
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert "view topic" not in parsed_import.problems[0].statement_latex
    assert "Olympiadium" not in parsed_import.problems[1].statement_latex
    assert "KPBY0507" not in parsed_import.problems[2].statement_latex
    assert "Graph Wording" in parsed_import.problems[3].statement_latex
    assert "Define $(P, Q)-path$ a path from $P$ to $Q$" in parsed_import.problems[3].statement_latex
    assert "Let a 2021 degree polynomial" in parsed_import.problems[4].statement_latex
    assert "Prove that lines $BD$ and $AE$ meet on the line tangent to $\\omega$ at $F$." in parsed_import.problems[5].statement_latex


def test_parse_contest_problem_statements_supports_nested_test_division_day_sections():
    parsed_import = parse_contest_problem_statements(KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_YEAR
    assert parsed_import.contest_name == KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_NAME
    assert len(parsed_import.problems) == EXPECTED_KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P2", "P1", "P2", "P1", "P1"]
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Test 1 · Senior · Day 1",
        "Test 1 · Senior · Day 2",
        "Test 1 · Junior · Day 1",
        "Test 1 · Junior · Day 2",
        "Test 2 · Senior · Day 1",
        "Test 2 · Junior · Day 2",
    ]
    assert parsed_import.problems[0].statement_latex == "Senior test 1 day 1 statement."
    assert parsed_import.problems[3].statement_latex == "Junior test 1 day 2 statement."
    assert parsed_import.problems[-1].statement_latex == "Junior test 2 day 2 statement."
    assert all("Proposed by" not in problem.statement_latex for problem in parsed_import.problems)
    assert all("view topic" not in problem.statement_latex for problem in parsed_import.problems)
    assert all("sample_user_" not in problem.statement_latex for problem in parsed_import.problems)


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


def test_parse_contest_problem_statements_supports_middle_year_headers():
    parsed_import = parse_contest_problem_statements(JOM_SHORTLIST_2015_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == JOM_SHORTLIST_2015_YEAR
    assert parsed_import.contest_name == JOM_SHORTLIST_2015_NAME
    assert len(parsed_import.problems) == EXPECTED_JOM_SHORTLIST_2015_PROBLEM_TOTAL
    assert [problem.problem_code for problem in parsed_import.problems] == ["A1", "C1"]
    assert [problem.day_label for problem in parsed_import.problems] == [""] * 2
    assert "zschess" not in parsed_import.problems[0].statement_latex
    assert "view topic" not in parsed_import.problems[1].statement_latex
    assert "Shortlisted Problems to the Junior Olympiad of Malaysia" not in (
        parsed_import.problems[0].statement_latex
    )


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


def test_parse_contest_problem_statements_supports_compact_day_headers():
    parsed_import = parse_contest_problem_statements(CHINA_NATIONAL_OLYMPIAD_2026_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == CHINA_NATIONAL_OLYMPIAD_2026_YEAR
    assert parsed_import.contest_name == CHINA_NATIONAL_OLYMPIAD_2026_NAME
    assert len(parsed_import.problems) == EXPECTED_CHINA_NATIONAL_OLYMPIAD_2026_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Day 1 · 2025.11.26",
        "Day 1 · 2025.11.26",
        "Day 2 · 2025.11.27",
        "Day 2 · 2025.11.27",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P2", "P3", "P4"]
    assert parsed_import.problems[0].statement_latex == "Compact day one."
    assert parsed_import.problems[-1].statement_latex == "Visible day two statement."
    assert "Click to reveal hidden text" not in parsed_import.problems[-1].statement_latex


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


def test_parse_contest_problem_statements_supports_inline_tournament_season_level_headers():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2018_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_2018_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_2018_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_2018_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Spring 2018 · Junior A-Level",
        "Spring 2018 · Junior A-Level",
        "Spring 2018 · Junior A-Level",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P2", "P3"]
    assert "Invert_DOG_about_centre_O" not in parsed_import.problems[0].statement_latex
    assert "Nikolay Belukhov" not in parsed_import.problems[2].statement_latex
    assert parsed_import.problems[0].statement_latex == "Thirty nine nonzero numbers are written in a row."
    assert parsed_import.problems[2].statement_latex == "You are in a strange land and you don’t know the language."


def test_parse_contest_problem_statements_supports_hyphenated_tournament_season_level_headers():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2016_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_2016_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_2016_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_2016_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Spring 2016 · Junior A-Level",
        "Spring 2016 · Senior A-Level",
        "Oral Round",
        "Fall 2016 · Senior A-Level",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P1", "P1", "P1"]
    assert parsed_import.problems[1].statement_latex == "Same as Junior A-level P1"
    assert parsed_import.problems[2].statement_latex == "Oral round one."
    assert "utkarshgupta" not in parsed_import.problems[0].statement_latex
    assert "Misha57" not in parsed_import.problems[2].statement_latex
    assert "Translated from here." not in parsed_import.problems[3].statement_latex
    assert "Chernyatevya" not in parsed_import.problems[3].statement_latex


def test_parse_contest_problem_statements_supports_yearless_hyphenated_tournament_headers():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2010_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_2010_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_2010_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_2010_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Spring 2010 · Junior O-Level",
        "Spring 2010 · Junior A-Level",
        "Fall 2010 · Senior O-Level",
        "Fall 2010 · Senior A-Level",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P1", "P1", "P1"]
    assert parsed_import.problems[0].statement_latex == "Junior O one."
    assert parsed_import.problems[-1].statement_latex == "Senior A one."
    assert all(problem.day_label for problem in parsed_import.problems)


def test_parse_contest_problem_statements_supports_yearless_paper_tournament_headers():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2003_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_2003_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_2003_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_2003_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Spring 2003 · Junior O-Level",
        "Spring 2003 · Junior A-Level",
        "Fall 2003 · Senior O-Level",
        "Fall 2003 · Senior A-Level",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P1", "P1", "P1"]
    assert parsed_import.problems[0].statement_latex == "Spring junior O one."
    assert parsed_import.problems[-1].statement_latex == "Fall senior A one."
    assert all(problem.day_label for problem in parsed_import.problems)


def test_parse_contest_problem_statements_supports_round_prefixed_tournament_headers():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2002_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_2002_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_2002_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_2002_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Spring 2002 · Junior O-Level",
        "Spring 2002 · Senior A-Level",
        "Fall 2002 · Junior A-Level",
        "Fall 2002 · Senior O-Level",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P1", "P1", "P1"]
    assert parsed_import.problems[0].statement_latex == "Spring junior O one."
    assert parsed_import.problems[-1].statement_latex == "Fall senior O one."
    assert all(problem.day_label for problem in parsed_import.problems)


def test_parse_contest_problem_statements_supports_bare_numbered_multiline_problems():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2002_MULTILINE_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_2002_MULTILINE_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_2002_MULTILINE_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_2002_MULTILINE_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Spring 2002 · Junior O-Level",
        "Fall 2002 · Senior A-Level",
    ]
    assert parsed_import.problems[0].statement_latex == "Spring multiline one.\nContinues here."
    assert parsed_import.problems[1].statement_latex == "Fall multiline one."


def test_parse_contest_problem_statements_supports_1997_split_division_headers():
    parsed_import = parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_1997_STATEMENT_SAMPLE)

    assert parsed_import.contest_year == TOURNAMENT_OF_TOWNS_1997_YEAR
    assert parsed_import.contest_name == TOURNAMENT_OF_TOWNS_1997_NAME
    assert len(parsed_import.problems) == EXPECTED_TOURNAMENT_OF_TOWNS_1997_PROBLEM_TOTAL
    assert [problem.day_label for problem in parsed_import.problems] == [
        "Spring 1997 · Junior O-Level",
        "Spring 1997 · Junior A-Level",
        "Spring 1997 · Senior O-Level",
        "Spring 1997 · Senior A-Level",
        "Spring 1997 · Senior A-Level",
        "Autumn 1997 · Junior O-Level",
        "Autumn 1997 · Junior A-Level",
    ]
    assert [problem.problem_code for problem in parsed_import.problems] == ["P1", "P2", "P1", "P1", "P2", "P1", "P1"]
    assert parsed_import.problems[0].statement_latex == "Spring junior O one."
    assert parsed_import.problems[3].statement_latex == "same as JA2 (529)"
    assert parsed_import.problems[4].statement_latex == "Spring senior A two."
    assert parsed_import.problems[-1].statement_latex == "Autumn junior A one."
    assert "parmenides51" not in parsed_import.problems[0].statement_latex
    assert "AI Galochkin" not in parsed_import.problems[0].statement_latex


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


def test_import_problem_statements_supports_compact_day_headers():
    result = import_problem_statements(
        parse_contest_problem_statements(CHINA_NATIONAL_OLYMPIAD_2026_STATEMENT_SAMPLE)
    )

    assert result.created_count == EXPECTED_CHINA_NATIONAL_OLYMPIAD_2026_PROBLEM_TOTAL
    assert result.updated_count == 0
    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=CHINA_NATIONAL_OLYMPIAD_2026_YEAR,
            contest_name=CHINA_NATIONAL_OLYMPIAD_2026_NAME,
        ).order_by("problem_number")
    )
    assert len(saved_rows) == EXPECTED_CHINA_NATIONAL_OLYMPIAD_2026_PROBLEM_TOTAL
    assert [row.day_label for row in saved_rows] == [
        "Day 1 · 2025.11.26",
        "Day 1 · 2025.11.26",
        "Day 2 · 2025.11.27",
        "Day 2 · 2025.11.27",
    ]
    assert saved_rows[0].statement_latex == "Compact day one."
    assert saved_rows[-1].statement_latex == "Visible day two statement."
    assert "Click to reveal hidden text" not in saved_rows[-1].statement_latex


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


def test_import_problem_statements_persists_numbered_tst_day_labels():
    result = import_problem_statements(parse_contest_problem_statements(CHINA_TST_2024_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_CHINA_TST_2024_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=CHINA_TST_2024_YEAR,
            contest_name=CHINA_TST_2024_NAME,
        )
        .order_by("problem_number")
        .values_list("day_label", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:3]] == ["TST #1 · Day 1 (March 5, 2024, Beijing)"] * 3
    assert [row[0] for row in saved_rows[3:6]] == ["TST #1 · Day 2 (March 6, 2024, Beijing)"] * 3
    assert [row[0] for row in saved_rows[6:9]] == ["TST #1 · Day 3 (March 10, 2024, Beijing)"] * 3
    assert [row[0] for row in saved_rows[9:]] == ["TST #1 · Day 4 (March 11, Beijing)"] * 15
    assert "Created by Liang Xiao" not in saved_rows[0][1]
    assert "view topic" not in saved_rows[0][1]


def test_import_problem_statements_persists_split_tst_and_day_labels():
    result = import_problem_statements(parse_contest_problem_statements(CHINA_TST_2017_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_CHINA_TST_2017_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=CHINA_TST_2017_YEAR,
            contest_name=CHINA_TST_2017_NAME,
        )
        .order_by("day_label", "problem_number")
        .values_list("day_label", "statement_latex")
    )
    assert [row[0] for row in saved_rows] == [
        "TST #1 · Day 1",
        "TST #1 · Day 2",
        "TST #2 · Day 1",
        "TST #5",
        "TST #5",
    ]
    assert "HuangZhen" not in saved_rows[0][1]
    assert "view topic" not in saved_rows[0][1]


def test_import_problem_statements_persists_year_prefixed_section_labels():
    result = import_problem_statements(parse_contest_problem_statements(CHINA_SECOND_ROUND_2025_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_CHINA_SECOND_ROUND_2025_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=CHINA_SECOND_ROUND_2025_YEAR,
            contest_name=CHINA_SECOND_ROUND_2025_NAME,
        )
        .order_by("day_label", "problem_number")
        .values_list("day_label", "statement_latex")
    )
    assert [row[0] for row in saved_rows] == [
        "China Second Round A",
        "China Second Round A",
        "China Second Round A",
        "China Second Round A",
        "China Second Round B",
        "China Second Round B",
        "China Second Round B",
        "China Second Round B",
    ]
    assert "steven_zhang123" not in saved_rows[0][1]
    assert "view topic" not in saved_rows[0][1]


def test_import_problem_statements_persists_test_headers_with_dates():
    result = import_problem_statements(parse_contest_problem_statements(ISRAEL_TST_2026_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_ISRAEL_TST_2026_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=ISRAEL_TST_2026_YEAR,
            contest_name=ISRAEL_TST_2026_NAME,
        )
        .order_by("day_label", "problem_number")
        .values_list("day_label", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:3]] == ["Test 1 · 17/11/2025"] * 3
    assert [row[0] for row in saved_rows[3:6]] == ["Test 2 · 18/11/2025"] * 3
    assert [row[0] for row in saved_rows[6:]] == ["Test 4 · 28/1/2026"] * 3
    assert "Zsigmondy" not in saved_rows[0][1]
    assert "view topic" not in saved_rows[0][1]


def test_import_problem_statements_persists_exam_day_headers():
    result = import_problem_statements(parse_contest_problem_statements(IRAN_TST_2024_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_IRAN_TST_2024_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=IRAN_TST_2024_YEAR,
            contest_name=IRAN_TST_2024_NAME,
        )
        .order_by("day_label", "problem_number")
        .values_list("day_label", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:3]] == ["First exam · Day 1"] * 3
    assert [row[0] for row in saved_rows[3:6]] == ["First exam · Day 2"] * 3
    assert [row[0] for row in saved_rows[6:9]] == ["Second exam · Day 1"] * 3
    assert [row[0] for row in saved_rows[9:]] == ["Second exam · Day 2"] * 3
    assert "Shayan-TayefehIR" not in saved_rows[0][1]
    assert "view topic" not in saved_rows[0][1]


def test_import_problem_statements_persists_year_suffix_headers_with_day_dates():
    result = import_problem_statements(parse_contest_problem_statements(RUSSIAN_TST_2022_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_RUSSIAN_TST_2022_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=RUSSIAN_TST_2022_YEAR,
            contest_name=RUSSIAN_TST_2022_NAME,
        )
        .order_by("day_label", "problem_number")
        .values_list("day_label", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:3]] == ["Day 1 · October 16, 2021"] * 3
    assert [row[0] for row in saved_rows[3:6]] == ["Day 2 · October 17, 2021"] * 3
    assert [row[0] for row in saved_rows[6:9]] == ["Day 3 · January 12, 2022"] * 3
    assert [row[0] for row in saved_rows[9:12]] == ["Day 4 · January 13, 2022"] * 3
    assert [row[0] for row in saved_rows[12:15]] == ["Day 5 · February 16, 2022"] * 3
    assert [row[0] for row in saved_rows[15:18]] == ["Day 6 · February 17, 2022"] * 3
    assert [row[0] for row in saved_rows[18:21]] == ["Day 7 · May 12, 2022"] * 3
    assert [row[0] for row in saved_rows[21:]] == ["Day 8 · May 13, 2022"] * 3
    assert "amuthup" not in saved_rows[0][1]
    assert "view topic" not in saved_rows[0][1]
    assert "Pakawut Jiradilok" not in saved_rows[2][1]
    assert "Proposed by" not in saved_rows[3][1]


def test_import_problem_statements_persists_unavailable_placeholder_problems():
    result = import_problem_statements(
        parse_contest_problem_statements(RUSSIAN_TST_2019_UNAVAILABLE_STATEMENT_SAMPLE),
    )

    assert result.created_count == EXPECTED_RUSSIAN_TST_2019_UNAVAILABLE_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=RUSSIAN_TST_2019_UNAVAILABLE_YEAR,
            contest_name=RUSSIAN_TST_2019_UNAVAILABLE_NAME,
        )
        .order_by("problem_number")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert saved_rows == [
        ("Day 6 · May 7, 2019", "P1", "Unavailable"),
        (
            "Day 6 · May 7, 2019",
            "P2",
            "Prove that for every odd prime number $p{}$, the following congruence holds\n"
            "\\[\\sum_{n=1}^{p-1}n^{p-1}\\equiv (p-1)!+p\\pmod{p^2}.\\]",
        ),
        (
            "Day 6 · May 7, 2019",
            "P3",
            "Find the maximal value of\n"
            "\\[S = \\sqrt[3]{\\frac{a}{b+7}} + \\sqrt[3]{\\frac{b}{c+7}} + \\sqrt[3]{\\frac{c}{d+7}} + "
            "\\sqrt[3]{\\frac{d}{a+7}},\\]\n"
            "where $a$, $b$, $c$, $d$ are nonnegative real numbers which satisfy $a+b+c+d = 100$.",
        ),
    ]


def test_import_problem_statements_persists_roman_tests_and_generic_sections():
    result = import_problem_statements(parse_contest_problem_statements(INDONESIA_TST_2025_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_INDONESIA_TST_2025_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=INDONESIA_TST_2025_YEAR,
            contest_name=INDONESIA_TST_2025_NAME,
        )
        .order_by("day_label", "problem_number")
        .values_list("day_label", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:5]] == [
        "APMO Unofficial",
        "APMO Unofficial",
        "APMO Unofficial",
        "APMO Unofficial",
        "APMO Unofficial",
    ]
    assert [row[0] for row in saved_rows[5:8]] == [
        "Test I · Saturday, 8 March 2025",
        "Test I · Saturday, 8 March 2025",
        "Test I · Saturday, 8 March 2025",
    ]
    assert [row[0] for row in saved_rows[8:11]] == [
        "Test II · Sunday, 9 March 2025",
        "Test II · Sunday, 9 March 2025",
        "Test II · Sunday, 9 March 2025",
    ]
    assert [row[0] for row in saved_rows[11:14]] == [
        "Test III · Saturday, 15 March 2025",
        "Test III · Saturday, 15 March 2025",
        "Test III · Saturday, 15 March 2025",
    ]
    assert [row[0] for row in saved_rows[14:]] == [
        "Test IV · Sunday, 16 March 2025",
        "Test IV · Sunday, 16 March 2025",
        "Test IV · Sunday, 16 March 2025",
    ]
    assert "Time: 5 Hours" not in saved_rows[5][1]
    assert "view topic" not in saved_rows[5][1]


def test_import_problem_statements_persists_round_test_headers_and_letter_codes():
    result = import_problem_statements(parse_contest_problem_statements(INDONESIA_TST_2024_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_INDONESIA_TST_2024_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=INDONESIA_TST_2024_YEAR,
            contest_name=INDONESIA_TST_2024_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:4]] == ["First Round · Test 1 (29 February 2024)"] * 4
    assert [row[1] for row in saved_rows[:4]] == ["A", "C", "G", "N"]
    assert [row[0] for row in saved_rows[4:8]] == ["First Round · Test 2 (3 March 2024)"] * 4
    assert [row[0] for row in saved_rows[8:12]] == ["First Round · Test 3 (7 March 2024)"] * 4
    assert [row[0] for row in saved_rows[12:17]] == ["Second Round · APMO 2024 (12 March 2024)"] * 5
    assert [row[0] for row in saved_rows[17:20]] == ["Second Round · Test 1 (15 March 2024)"] * 3
    assert [row[0] for row in saved_rows[20:23]] == ["Second Round · Test 2 (17 March 2024)"] * 3
    assert [row[0] for row in saved_rows[23:]] == ["Second Round · Test 3 (19 March 2024)"] * 3
    assert "amogususususus" not in saved_rows[0][2]
    assert "view topic" not in saved_rows[0][2]


def test_import_problem_statements_persists_named_sections_with_separate_date_lines():
    result = import_problem_statements(
        parse_contest_problem_statements(MALAYSIAN_IMO_TRAINING_CAMP_2025_STATEMENT_SAMPLE),
    )

    assert result.created_count == EXPECTED_MALAYSIAN_IMO_TRAINING_CAMP_2025_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=MALAYSIAN_IMO_TRAINING_CAMP_2025_YEAR,
            contest_name=MALAYSIAN_IMO_TRAINING_CAMP_2025_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:8]] == ["BIMO 1 Christmas Test · December 25, 2024"] * 8
    assert [row[1] for row in saved_rows[:3]] == ["P1", "P2", "P3"]
    assert [row[0] for row in saved_rows[8:]] == ["Junior Olympiad of Malaysia 2025 · January 19, 2025"] * 5
    assert [row[1] for row in saved_rows[8:11]] == ["P1", "P2", "P3"]
    assert "quacksaysduck" not in saved_rows[0][2]
    assert "view topic" not in saved_rows[0][2]
    assert "the points $J$, $O$, $M$ are collinear." in saved_rows[8][2]


def test_import_problem_statements_persists_named_sections_with_day_subsections():
    result = import_problem_statements(
        parse_contest_problem_statements(MALAYSIAN_IMO_TRAINING_CAMP_2024_STATEMENT_SAMPLE),
    )

    assert result.created_count == EXPECTED_MALAYSIAN_IMO_TRAINING_CAMP_2024_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=MALAYSIAN_IMO_TRAINING_CAMP_2024_YEAR,
            contest_name=MALAYSIAN_IMO_TRAINING_CAMP_2024_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:5]] == ["Junior Olympiad of Malaysia 2024 · February 17, 2024"] * 5
    assert [row[0] for row in saved_rows[5:10]] == ["APMO Camp Selection Test 2024 · February 17, 2024"] * 5
    assert [row[0] for row in saved_rows[10:13]] == ["IMO Team Selection Test 2024 · Day 1 · April 13, 2024"] * 3
    assert [row[0] for row in saved_rows[13:16]] == ["IMO Team Selection Test 2024 · Day 2 · April 14, 2024"] * 3
    assert [row[0] for row in saved_rows[16:20]] == [
        "Malaysian Squad Selection Test 2024 · Day 1 · August 24, 2024",
    ] * 4
    assert [row[0] for row in saved_rows[20:]] == [
        "Malaysian Squad Selection Test 2024 · Day 2 · August 25, 2024",
    ] * 4
    assert [row[1] for row in saved_rows[10:16]] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert "view topic" not in saved_rows[0][2]
    assert "navi_09220114" not in saved_rows[5][2]
    assert "Proposed Ivan Chan Guan Yu" not in saved_rows[20][2]
    assert "the line $KL$, $\\ell$, and the line through the centers" in saved_rows[-1][2]


def test_import_problem_statements_persists_nested_bimo_sections():
    result = import_problem_statements(parse_contest_problem_statements(BIMO_2021_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_BIMO_2021_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=BIMO_2021_YEAR,
            contest_name=BIMO_2021_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [row[0] for row in saved_rows] == [
        "BIMO 1 · Problem Solving Session",
        "Mock IMO Test",
        "Mock IMO Test",
        "Mock IMO Test",
        "BIMO 2 · Test 1 (Geometry)",
    ]
    assert [row[1] for row in saved_rows] == ["P1", "P1", "P2", "P3", "P2"]
    assert "navi_09220114" not in saved_rows[0][2]
    assert "view topic" not in saved_rows[0][2]
    assert "$KM\\perp EF$." in saved_rows[-1][2]


def test_import_problem_statements_persists_hash_numbered_korean_winter_camp_problems():
    result = import_problem_statements(parse_contest_problem_statements(KOREAN_MO_WINTER_CAMP_2020_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_KOREAN_MO_WINTER_CAMP_2020_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=KOREAN_MO_WINTER_CAMP_2020_YEAR,
            contest_name=KOREAN_MO_WINTER_CAMP_2020_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [row[0] for row in saved_rows] == ["Korean MO winter camp Test 1"] * 8
    assert [row[1] for row in saved_rows] == ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]
    assert "MNJ2357" not in saved_rows[0][2]
    assert "view topic" not in saved_rows[0][2]
    assert "hamiltonian circuit exist for the given graph" in saved_rows[-1][2]


def test_import_problem_statements_persists_grade_sections_for_romania_national_olympiad():
    result = import_problem_statements(parse_contest_problem_statements(ROMANIA_NATIONAL_OLYMPIAD_2025_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_ROMANIA_NATIONAL_OLYMPIAD_2025_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=ROMANIA_NATIONAL_OLYMPIAD_2025_YEAR,
            contest_name=ROMANIA_NATIONAL_OLYMPIAD_2025_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:4]] == ["Grade 9"] * 4
    assert [row[0] for row in saved_rows[4:8]] == ["Grade 10"] * 4
    assert [row[0] for row in saved_rows[8:12]] == ["Grade 11"] * 4
    assert [row[0] for row in saved_rows[12:]] == ["Grade 12"] * 4
    assert [row[1] for row in saved_rows[:4]] == ["P1", "P2", "P3", "P4"]
    assert [row[1] for row in saved_rows[12:]] == ["P1", "P2", "P3", "P4"]
    assert "Ciobi_" not in saved_rows[0][2]
    assert "view topic" not in saved_rows[0][2]
    assert "has at least $p$ coefficients equal to $1$." in saved_rows[-1][2]


def test_import_problem_statements_persists_grade_level_sections_for_older_romania_national_olympiad():
    result = import_problem_statements(parse_contest_problem_statements(ROMANIA_NATIONAL_OLYMPIAD_2015_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_ROMANIA_NATIONAL_OLYMPIAD_2015_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=ROMANIA_NATIONAL_OLYMPIAD_2015_YEAR,
            contest_name=ROMANIA_NATIONAL_OLYMPIAD_2015_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:4]] == ["Grade level 7"] * 4
    assert [row[0] for row in saved_rows[4:8]] == ["Grade level 8"] * 4
    assert [row[0] for row in saved_rows[8:12]] == ["Grade level 9"] * 4
    assert [row[0] for row in saved_rows[12:16]] == ["Grade level 10"] * 4
    assert [row[0] for row in saved_rows[16:20]] == ["Grade level 11"] * 4
    assert [row[0] for row in saved_rows[20:]] == ["Grade level 12"] * 4
    assert [row[1] for row in saved_rows[:4]] == ["P1", "P2", "P3", "P4"]
    assert [row[1] for row in saved_rows[20:]] == ["P1", "P2", "P3", "P4"]
    assert "parmenides51" not in saved_rows[0][2]
    assert "CatalinBordea" not in saved_rows[8][2]
    assert "view topic" not in saved_rows[0][2]
    assert "there exists a function $ \\xi" in saved_rows[-1][2]


def test_import_problem_statements_persists_part_headers_with_p_prefixed_problems():
    result = import_problem_statements(
        parse_contest_problem_statements(KOREA_NATIONAL_OLYMPIAD_2021_STATEMENT_SAMPLE),
    )

    assert result.created_count == EXPECTED_KOREA_NATIONAL_OLYMPIAD_2021_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=KOREA_NATIONAL_OLYMPIAD_2021_YEAR,
            contest_name=KOREA_NATIONAL_OLYMPIAD_2021_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [row[0] for row in saved_rows[:3]] == ["Part 1"] * 3
    assert [row[0] for row in saved_rows[3:]] == ["Part 2"] * 3
    assert [row[1] for row in saved_rows] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert "view topic" not in saved_rows[0][2]
    assert "Olympiadium" not in saved_rows[1][2]
    assert "KPBY0507" not in saved_rows[4][2]
    assert "Graph Wording" in saved_rows[3][2]


def test_import_problem_statements_persists_nested_test_division_day_sections():
    result = import_problem_statements(
        parse_contest_problem_statements(KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_STATEMENT_SAMPLE),
    )

    assert result.created_count == EXPECTED_KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_PROBLEM_TOTAL
    assert result.updated_count == 0

    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_YEAR,
            contest_name=KOREA_WINTER_PROGRAM_PRACTICE_TEST_2026_NAME,
        )
        .order_by("id")
        .values_list("day_label", "problem_code", "statement_latex")
    )
    assert [(row[0], row[1]) for row in saved_rows] == [
        ("Test 1 · Senior · Day 1", "P1"),
        ("Test 1 · Senior · Day 2", "P2"),
        ("Test 1 · Junior · Day 1", "P1"),
        ("Test 1 · Junior · Day 2", "P2"),
        ("Test 2 · Senior · Day 1", "P1"),
        ("Test 2 · Junior · Day 2", "P1"),
    ]
    assert saved_rows[0][2] == "Senior test 1 day 1 statement."
    assert saved_rows[-1][2] == "Junior test 2 day 2 statement."


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


def test_import_problem_statements_supports_inline_tournament_season_level_headers():
    result = import_problem_statements(parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2018_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_2018_PROBLEM_TOTAL
    assert result.updated_count == 0
    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=TOURNAMENT_OF_TOWNS_2018_YEAR,
            contest_name=TOURNAMENT_OF_TOWNS_2018_NAME,
        ).order_by("problem_number")
    )
    assert len(saved_rows) == EXPECTED_TOURNAMENT_OF_TOWNS_2018_PROBLEM_TOTAL
    assert all(row.day_label == "Spring 2018 · Junior A-Level" for row in saved_rows)
    assert saved_rows[-1].statement_latex == "You are in a strange land and you don’t know the language."


def test_import_problem_statements_supports_hyphenated_tournament_season_level_headers():
    result = import_problem_statements(parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2016_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_2016_PROBLEM_TOTAL
    assert result.updated_count == 0
    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=TOURNAMENT_OF_TOWNS_2016_YEAR,
            contest_name=TOURNAMENT_OF_TOWNS_2016_NAME,
        ).order_by("day_label", "problem_number")
    )
    assert len(saved_rows) == EXPECTED_TOURNAMENT_OF_TOWNS_2016_PROBLEM_TOTAL
    assert [row.day_label for row in saved_rows] == [
        "Fall 2016 · Senior A-Level",
        "Oral Round",
        "Spring 2016 · Junior A-Level",
        "Spring 2016 · Senior A-Level",
    ]
    assert saved_rows[0].statement_latex == "Fall senior one."
    assert saved_rows[1].statement_latex == "Oral round one."


def test_import_problem_statements_supports_yearless_hyphenated_tournament_headers():
    result = import_problem_statements(parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2010_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_2010_PROBLEM_TOTAL
    assert result.updated_count == 0
    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=TOURNAMENT_OF_TOWNS_2010_YEAR,
            contest_name=TOURNAMENT_OF_TOWNS_2010_NAME,
        ).order_by("day_label", "problem_number")
    )
    assert len(saved_rows) == EXPECTED_TOURNAMENT_OF_TOWNS_2010_PROBLEM_TOTAL
    assert [row.day_label for row in saved_rows] == [
        "Fall 2010 · Senior A-Level",
        "Fall 2010 · Senior O-Level",
        "Spring 2010 · Junior A-Level",
        "Spring 2010 · Junior O-Level",
    ]
    assert saved_rows[0].statement_latex == "Senior A one."
    assert saved_rows[-1].statement_latex == "Junior O one."


def test_import_problem_statements_supports_yearless_paper_tournament_headers():
    result = import_problem_statements(parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2003_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_2003_PROBLEM_TOTAL
    assert result.updated_count == 0
    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=TOURNAMENT_OF_TOWNS_2003_YEAR,
            contest_name=TOURNAMENT_OF_TOWNS_2003_NAME,
        ).order_by("day_label", "problem_number")
    )
    assert len(saved_rows) == EXPECTED_TOURNAMENT_OF_TOWNS_2003_PROBLEM_TOTAL
    assert [row.day_label for row in saved_rows] == [
        "Fall 2003 · Senior A-Level",
        "Fall 2003 · Senior O-Level",
        "Spring 2003 · Junior A-Level",
        "Spring 2003 · Junior O-Level",
    ]
    assert saved_rows[0].statement_latex == "Fall senior A one."
    assert saved_rows[-1].statement_latex == "Spring junior O one."


def test_import_problem_statements_supports_round_prefixed_tournament_headers():
    result = import_problem_statements(parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2002_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_2002_PROBLEM_TOTAL
    assert result.updated_count == 0
    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=TOURNAMENT_OF_TOWNS_2002_YEAR,
            contest_name=TOURNAMENT_OF_TOWNS_2002_NAME,
        ).order_by("day_label", "problem_number")
    )
    assert len(saved_rows) == EXPECTED_TOURNAMENT_OF_TOWNS_2002_PROBLEM_TOTAL
    assert [row.day_label for row in saved_rows] == [
        "Fall 2002 · Junior A-Level",
        "Fall 2002 · Senior O-Level",
        "Spring 2002 · Junior O-Level",
        "Spring 2002 · Senior A-Level",
    ]
    assert saved_rows[0].statement_latex == "Fall junior A one."
    assert saved_rows[-1].statement_latex == "Spring senior A one."


def test_import_problem_statements_supports_bare_numbered_multiline_problems():
    result = import_problem_statements(
        parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_2002_MULTILINE_STATEMENT_SAMPLE)
    )

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_2002_MULTILINE_PROBLEM_TOTAL
    assert result.updated_count == 0
    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=TOURNAMENT_OF_TOWNS_2002_MULTILINE_YEAR,
            contest_name=TOURNAMENT_OF_TOWNS_2002_MULTILINE_NAME,
        ).order_by("day_label", "problem_number")
    )
    assert len(saved_rows) == EXPECTED_TOURNAMENT_OF_TOWNS_2002_MULTILINE_PROBLEM_TOTAL
    assert [row.day_label for row in saved_rows] == [
        "Fall 2002 · Senior A-Level",
        "Spring 2002 · Junior O-Level",
    ]
    assert saved_rows[0].statement_latex == "Fall multiline one."
    assert saved_rows[1].statement_latex == "Spring multiline one.\nContinues here."


def test_import_problem_statements_supports_1997_split_division_headers():
    result = import_problem_statements(parse_contest_problem_statements(TOURNAMENT_OF_TOWNS_1997_STATEMENT_SAMPLE))

    assert result.created_count == EXPECTED_TOURNAMENT_OF_TOWNS_1997_PROBLEM_TOTAL
    assert result.updated_count == 0
    saved_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=TOURNAMENT_OF_TOWNS_1997_YEAR,
            contest_name=TOURNAMENT_OF_TOWNS_1997_NAME,
        ).order_by("day_label", "problem_number")
    )
    assert len(saved_rows) == EXPECTED_TOURNAMENT_OF_TOWNS_1997_PROBLEM_TOTAL
    assert [row.day_label for row in saved_rows] == [
        "Autumn 1997 · Junior A-Level",
        "Autumn 1997 · Junior O-Level",
        "Spring 1997 · Junior A-Level",
        "Spring 1997 · Junior O-Level",
        "Spring 1997 · Senior A-Level",
        "Spring 1997 · Senior A-Level",
        "Spring 1997 · Senior O-Level",
    ]
    assert saved_rows[0].statement_latex == "Autumn junior A one."
    assert saved_rows[2].problem_code == "P2"
    assert saved_rows[4].statement_latex == "same as JA2 (529)"
    assert saved_rows[5].problem_code == "P2"
    assert saved_rows[-1].statement_latex == "Spring senior O one."


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


def test_handle_summary_parser_requires_login(client):
    response = client.get(reverse("pages:handle_summary_parser"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:handle_summary_parser')}"


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


def test_problem_statement_duplicates_requires_login(client):
    response = client.get(reverse("pages:problem_statement_duplicates"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:problem_statement_duplicates')}"


def test_problem_statement_linker_requires_login(client):
    response = client.get(reverse("pages:problem_statement_linker"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:problem_statement_linker')}"


def test_problem_statement_editor_requires_login(client):
    response = client.get(reverse("pages:problem_statement_editor"))
    login_url = reverse(settings.LOGIN_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{login_url}?next={reverse('pages:problem_statement_editor')}"


def test_problem_statement_editor_page_renders_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    response = client.get(reverse("pages:problem_statement_editor"))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Statement editor" in response_html
    assert "Statement editor scaffold." in response_html


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
def test_problem_statement_duplicates_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:problem_statement_duplicates"))

    assert response.status_code == HTTPStatus.FORBIDDEN


@override_settings(DEBUG=False)
def test_problem_statement_linker_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:problem_statement_linker"))

    assert response.status_code == HTTPStatus.FORBIDDEN


@override_settings(DEBUG=False)
def test_problem_statement_editor_forbids_non_admin_access_when_debug_is_off(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:problem_statement_editor"))

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
    assert "dataTables.bootstrap5.min.css" in response_html
    assert "dataTables.min.js" in response_html
    assert 'new DataTable("#contest-inventory-table"' in response_html
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


def test_contest_dashboard_rows_include_advanced_analytics_links(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="USAMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Statement one",
    )

    response = client.get(reverse("pages:contest_dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["contest_rows"][0]["detail_url"] == (
        reverse("pages:contest_advanced_dashboard") + "?contest=USAMO"
    )
    assert response.context["contest_total"] == 1
    assert response.context["contest_problem_total"] == 1
    response_html = response.content.decode("utf-8")
    assert "row.detail_url" in response_html


def test_contest_advanced_analytics_view_renders_selected_contest_breakdown(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    solution_author = UserFactory()
    client.force_login(admin_user)
    problem_one = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=6,
        contest="USAMO",
        problem="P1",
        contest_year_problem="USAMO 2026 P1",
        confidence="High",
    )
    problem_two = ProblemSolveRecord.objects.create(
        year=2025,
        topic="GEO",
        mohs=4,
        contest="USAMO",
        problem="P2",
        contest_year_problem="USAMO 2025 P2",
        confidence="Medium",
    )
    ProblemSolveRecord.objects.create(
        year=2024,
        topic="NT",
        mohs=7,
        contest="BMO",
        problem="P1",
        contest_year_problem="BMO 2024 P1",
    )
    ProblemTopicTechnique.objects.create(record=problem_one, technique="INVARIANT", domains=["C"])
    ProblemTopicTechnique.objects.create(record=problem_two, technique="ANGLE CHASE", domains=["G"])
    ContestProblemStatement.objects.create(
        linked_problem=problem_one,
        contest_year=2026,
        contest_name="USAMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Statement one",
    )
    ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name="USAMO",
        problem_number=2,
        problem_code="P2",
        day_label="Day 2",
        statement_latex="Unlinked statement two",
    )
    UserProblemCompletion.objects.create(
        user=solution_author,
        problem=problem_one,
        completion_date=date(2026, 1, 15),
    )
    UserProblemCompletion.objects.create(
        user=solution_author,
        problem=problem_two,
        completion_date=date(2025, 2, 5),
    )
    ProblemSolution.objects.create(
        problem=problem_one,
        author=solution_author,
        status=ProblemSolution.Status.PUBLISHED,
    )

    response = client.get(reverse("pages:contest_advanced_dashboard"), {"contest": "USAMO"})

    assert response.status_code == HTTPStatus.OK
    assert response.context["selected_contest"] == "USAMO"
    assert response.context["contest_stats"]["problem_count"] == 2
    assert response.context["contest_stats"]["statement_problem_total"] == 1
    assert response.context["contest_stats"]["statement_row_total"] == 2
    assert response.context["contest_stats"]["published_solution_total"] == 1
    assert response.context["public_contest_url"] == reverse("pages:contest_problem_list", args=["usamo"])
    heatmap = response.context["contest_completion_heatmap"]
    assert heatmap["problem_codes"] == ["P1", "P2"]
    heatmap_2026 = next(row for row in heatmap["rows"] if row["year"] == 2026)
    heatmap_2025 = next(row for row in heatmap["rows"] if row["year"] == 2025)
    heatmap_2026_p1 = next(cell for cell in heatmap_2026["cells"] if cell["problem_code"] == "P1")
    heatmap_2026_p2 = next(cell for cell in heatmap_2026["cells"] if cell["problem_code"] == "P2")
    heatmap_2025_p1 = next(cell for cell in heatmap_2025["cells"] if cell["problem_code"] == "P1")
    heatmap_2025_p2 = next(cell for cell in heatmap_2025["cells"] if cell["problem_code"] == "P2")
    assert heatmap_2026_p1["state"] == "solved"
    assert heatmap_2026_p1["display"] == "✓"
    assert heatmap_2026_p2["state"] == "empty"
    assert heatmap_2025_p1["state"] == "empty"
    assert heatmap_2025_p2["state"] == "unsolved"
    assert heatmap_2025_p2["display"] == "•"
    assert heatmap["chart"]["max_value"] == 3
    assert heatmap["chart"]["series"] == [
        {
            "name": "2026",
            "data": [
                {
                    "display": "✓",
                    "state": "solved",
                    "title": "USAMO 2026 P1: 1 of 1 statement row solved",
                    "x": "P1",
                    "y": 3,
                },
                {
                    "display": "",
                    "state": "empty",
                    "title": "USAMO 2026 P2: no statement row",
                    "x": "P2",
                    "y": 0,
                },
            ],
        },
        {
            "name": "2025",
            "data": [
                {
                    "display": "",
                    "state": "empty",
                    "title": "USAMO 2025 P1: no statement row",
                    "x": "P1",
                    "y": 0,
                },
                {
                    "display": "•",
                    "state": "unsolved",
                    "title": "USAMO 2025 P2: 0 of 1 statement row solved",
                    "x": "P2",
                    "y": 1,
                },
            ],
        },
    ]
    year_2026 = next(row for row in response.context["year_rows"] if row["year"] == 2026)
    year_2025 = next(row for row in response.context["year_rows"] if row["year"] == 2025)
    assert year_2026["problem_count"] == 1
    assert year_2026["statement_problem_total"] == 1
    assert year_2026["solved_problem_total"] == 1
    assert year_2026["solved_rate"] == 100.0
    assert year_2026["year_detail_url"] == (
        reverse("pages:contest_dashboard_listing") + "?contest=USAMO&year=2026"
    )
    assert year_2025["problem_count"] == 1
    assert year_2025["statement_problem_total"] == 0
    assert year_2025["solved_problem_total"] == 0
    assert year_2025["solved_rate"] == 0.0
    assert year_2025["year_detail_url"] == (
        reverse("pages:contest_dashboard_listing") + "?contest=USAMO&year=2025"
    )
    response_html = response.content.decode("utf-8")
    assert "Contest advanced analytics" in response_html
    assert "Completion heatmap" in response_html
    assert "Solved by at least one user" in response_html
    assert 'id="chart-contest-completion-heatmap"' in response_html
    assert "contest-advanced-heatmap-data" in response_html
    assert "plugins/apexcharts/apexcharts.min.js" in response_html
    assert "contest-completion-heatmap-table" not in response_html
    assert "Year breakdown" in response_html
    assert "Statement-linked" in response_html
    assert "Solved" in response_html
    assert "Solved rate" in response_html
    assert "year=2026" in response_html
    assert "Topic mix" in response_html
    assert "Recent statements" in response_html
    assert "USAMO (2 statements)" in response_html


def test_contest_dashboard_listing_view_filters_selected_contest_and_year_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    visible_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=6,
        contest="USAMO",
        problem="P1",
        contest_year_problem="USAMO 2026 P1",
    )
    hidden_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="GEO",
        mohs=4,
        contest="USAMO",
        problem="P2",
        contest_year_problem="USAMO 2026 P2",
    )
    ContestProblemStatement.objects.create(
        linked_problem=visible_problem,
        contest_year=2026,
        contest_name="USAMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Statement one",
    )

    response = client.get(
        reverse("pages:contest_dashboard_listing"),
        {"contest": "USAMO", "year": "2026"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["contest_title"] == "USAMO"
    assert response.context["selected_year"] == "2026"
    assert response.context["matching_problem_total"] == 1
    assert response.context["contest_back_label"] == "Back to advanced analytics"
    assert response.context["contest_back_url"] == (
        reverse("pages:contest_advanced_dashboard") + "?contest=USAMO"
    )
    assert response.context["completion_board_toggle_url"] == reverse("pages:completion_board_toggle")
    assert response.context["contest_listing_base_url"] == (
        reverse("pages:contest_dashboard_listing") + "?contest=USAMO"
    )
    grouped_years = response.context["grouped_years"]
    assert len(grouped_years) == 1
    assert grouped_years[0]["year"] == 2026
    assert grouped_years[0]["problems"][0]["label"] == visible_problem.contest_year_problem
    response_html = response.content.decode("utf-8")
    assert "Back to advanced analytics" in response_html
    assert "<th>#</th>" in response_html
    assert "js-year-select-all" in response_html
    assert "js-problem-select" in response_html
    assert "js-sort-header" in response_html
    assert "Set inactive" in response_html
    assert 'text-nowrap text-muted fw-semibold js-row-index">1<' in response_html
    assert "Solved date" in response_html
    assert "js-completion-save" in response_html
    assert "Unknown" in response_html
    assert "USAMO 2026 P1" in response_html
    assert hidden_problem.contest_year_problem not in response_html


def test_contest_dashboard_listing_hides_inactive_statement_rows(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    visible_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="ALG",
        mohs=5,
        contest="JBMO Shortlist",
        problem="P1",
        contest_year_problem="JBMO Shortlist 2024 P1",
    )
    hidden_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="GEO",
        mohs=4,
        contest="JBMO Shortlist",
        problem="P2",
        contest_year_problem="JBMO Shortlist 2024 P2",
    )
    active_statement = ContestProblemStatement.objects.create(
        linked_problem=visible_problem,
        contest_year=2024,
        contest_name="JBMO Shortlist",
        problem_number=1,
        problem_code="P1",
        day_label="Geometry",
        statement_latex="Visible statement",
        is_active=True,
    )
    ContestProblemStatement.objects.create(
        linked_problem=hidden_problem,
        contest_year=2024,
        contest_name="JBMO Shortlist",
        problem_number=2,
        problem_code="P2",
        day_label="Algebra",
        statement_latex="Hidden statement",
        is_active=False,
    )

    response = client.get(
        reverse("pages:contest_dashboard_listing"),
        {"contest": "JBMO Shortlist", "year": "2024"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["matching_problem_total"] == 1
    grouped_years = response.context["grouped_years"]
    assert len(grouped_years) == 1
    assert len(grouped_years[0]["problems"]) == 1
    assert grouped_years[0]["problems"][0]["label"] == active_statement.contest_year_problem
    response_html = response.content.decode("utf-8")
    assert "Visible statement" in response_html
    assert "Hidden statement" not in response_html


def test_contest_dashboard_listing_shows_unlinked_statement_rows_with_completion_controls(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    statement = ContestProblemStatement.objects.create(
        contest_year=2024,
        contest_name="JBMO Shortlist",
        problem_number=7,
        problem_code="P7",
        day_label="Number Theory",
        statement_latex="Unlinked statement row",
        is_active=True,
    )

    response = client.get(
        reverse("pages:contest_dashboard_listing"),
        {"contest": "JBMO Shortlist", "year": "2024"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["matching_problem_total"] == 1
    grouped_years = response.context["grouped_years"]
    assert len(grouped_years) == 1
    row = grouped_years[0]["problems"][0]
    assert row["statement_id"] == statement.id
    assert row["is_linked"] is False
    assert row["completion_state_kind"] == "unsolved"
    assert row["completion_display"] == "Unsolved"
    back_response = client.get(response.context["contest_back_url"])
    assert back_response.status_code == HTTPStatus.OK
    assert back_response.context["selected_contest"] == "JBMO Shortlist"
    response_html = response.content.decode("utf-8")
    assert "Unlinked statement row" in response_html
    assert "js-completion-save" in response_html
    assert "Link a problem first" not in response_html


def test_completion_board_toggle_accepts_statement_uuid_for_unlinked_statement(client):
    user = UserFactory()
    client.force_login(user)
    statement = ContestProblemStatement.objects.create(
        contest_year=2024,
        contest_name="JBMO Shortlist",
        problem_number=7,
        problem_code="P7",
        day_label="Number Theory",
        statement_latex="Unlinked statement row",
        is_active=True,
    )

    response = client.post(
        reverse("pages:completion_board_toggle"),
        {
            "action": "set_unknown",
            "statement_uuid": str(statement.statement_uuid),
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["statement_uuid"] == str(statement.statement_uuid)
    assert payload["is_solved"] is True
    assert payload["state_kind"] == "unknown"
    completion = UserProblemCompletion.objects.get(user=user, statement=statement)
    assert completion.problem is None
    assert completion.completion_date is None


def test_contest_dashboard_listing_bulk_update_sets_selected_rows_inactive(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    active_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="ALG",
        mohs=5,
        contest="JBMO Shortlist",
        problem="P1",
        contest_year_problem="JBMO Shortlist 2024 P1",
    )
    other_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="GEO",
        mohs=4,
        contest="JBMO Shortlist",
        problem="P2",
        contest_year_problem="JBMO Shortlist 2024 P2",
    )
    active_statement = ContestProblemStatement.objects.create(
        linked_problem=active_problem,
        contest_year=2024,
        contest_name="JBMO Shortlist",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Statement one",
        is_active=True,
    )
    other_statement = ContestProblemStatement.objects.create(
        linked_problem=other_problem,
        contest_year=2024,
        contest_name="JBMO Shortlist",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Statement two",
        is_active=True,
    )
    listing_url = reverse("pages:contest_dashboard_listing") + "?contest=JBMO+Shortlist&year=2024"

    response = client.post(
        reverse("pages:contest_dashboard_listing_bulk_update"),
        {
            "action": "set_inactive",
            "contest": "JBMO Shortlist",
            "next": listing_url,
            "statement_id": [str(active_statement.id)],
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    active_statement.refresh_from_db()
    other_statement.refresh_from_db()
    active_problem.refresh_from_db()
    other_problem.refresh_from_db()
    assert active_statement.is_active is False
    assert other_statement.is_active is True
    assert active_problem.is_active is True
    assert other_problem.is_active is True
    response_html = response.content.decode("utf-8")
    assert active_problem.contest_year_problem not in response_html
    assert other_problem.contest_year_problem in response_html


def test_contest_dashboard_listing_bulk_update_scopes_rows_to_selected_contest(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    selected_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="ALG",
        mohs=5,
        contest="JBMO Shortlist",
        problem="P1",
        contest_year_problem="JBMO Shortlist 2024 P1",
    )
    other_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="GEO",
        mohs=6,
        contest="USAMO",
        problem="P1",
        contest_year_problem="USAMO 2024 P1",
    )
    selected_statement = ContestProblemStatement.objects.create(
        linked_problem=selected_problem,
        contest_year=2024,
        contest_name="JBMO Shortlist",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Selected contest statement",
        is_active=True,
    )
    other_statement = ContestProblemStatement.objects.create(
        linked_problem=other_problem,
        contest_year=2024,
        contest_name="USAMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Other contest statement",
        is_active=True,
    )
    listing_url = reverse("pages:contest_dashboard_listing") + "?contest=JBMO+Shortlist&year=2024"

    response = client.post(
        reverse("pages:contest_dashboard_listing_bulk_update"),
        {
            "action": "set_inactive",
            "contest": "JBMO Shortlist",
            "next": listing_url,
            "statement_id": [str(other_statement.id)],
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    selected_statement.refresh_from_db()
    other_statement.refresh_from_db()
    assert selected_statement.is_active is True
    assert other_statement.is_active is True


def test_contest_dashboard_listing_bulk_update_redirects_to_dashboard_after_last_row_removed(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="ALG",
        mohs=5,
        contest="JBMO Shortlist",
        problem="P1",
        contest_year_problem="JBMO Shortlist 2024 P1",
    )
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_year=2024,
        contest_name="JBMO Shortlist",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Only statement",
        is_active=True,
    )
    listing_url = reverse("pages:contest_dashboard_listing") + "?contest=JBMO+Shortlist&year=2024"

    response = client.post(
        reverse("pages:contest_dashboard_listing_bulk_update"),
        {
            "action": "set_inactive",
            "contest": "JBMO Shortlist",
            "next": listing_url,
            "statement_id": [str(statement.id)],
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    statement.refresh_from_db()
    assert statement.is_active is False
    assert response.redirect_chain
    assert response.redirect_chain[-1][0].endswith(reverse("pages:contest_dashboard"))


def test_completion_board_toggle_accepts_problem_without_statement(client):
    user = UserFactory()
    client.force_login(user)
    problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="ALG",
        mohs=5,
        contest="BMO Shortlist",
        problem="P1",
        contest_year_problem="BMO Shortlist 2024 P1",
    )

    response = client.post(
        reverse("pages:completion_board_toggle"),
        {
            "action": "set_unknown",
            "problem_uuid": str(problem.problem_uuid),
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["problem_uuid"] == str(problem.problem_uuid)
    assert payload["is_solved"] is True
    assert payload["state_kind"] == "unknown"
    completion = UserProblemCompletion.objects.get(user=user, problem=problem)
    assert completion.completion_date is None


def test_completion_record_list_renders_admin_inventory(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    completion_user = UserFactory(name="Ada Lovelace")
    client.force_login(admin_user)
    problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=6,
        contest="USAMO",
        problem="P1",
        contest_year_problem="USAMO 2026 P1",
    )
    UserProblemCompletion.objects.create(
        user=completion_user,
        problem=problem,
        completion_date=date(2026, 7, 10),
    )
    ProblemSolution.objects.create(
        problem=problem,
        author=completion_user,
        status=ProblemSolution.Status.DRAFT,
    )

    response = client.get(reverse("pages:completion_record_list"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["completion_record_stats"]["record_total"] == 1
    assert response.context["completion_record_stats"]["solution_total"] == 1
    first_row = response.context["completion_record_rows"][0]
    assert first_row["user_label"] == "Ada Lovelace"
    assert first_row["completion_date"] == "2026-07-10"
    assert first_row["solution_status_label"] == "Draft"
    assert first_row["archive_url"].endswith("#usamo-2026-p1")
    assert first_row["problem_url"] == reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
    response_html = response.content.decode("utf-8")
    assert "Completion info listing" in response_html
    assert 'id="completion-record-table"' in response_html


def test_user_solution_record_list_renders_admin_inventory(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    solution_author = UserFactory(name="Mary Cartwright")
    client.force_login(admin_user)
    problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="GEO",
        mohs=5,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2025 P2",
    )
    solution = ProblemSolution.objects.create(
        problem=problem,
        author=solution_author,
        title="Circle setup",
        summary="Use inversion.",
        status=ProblemSolution.Status.PUBLISHED,
        published_at=timezone.now(),
    )
    solution.blocks.create(position=1, title="Idea", body_source="First block")

    response = client.get(reverse("pages:user_solution_record_list"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["user_solution_record_stats"]["solution_total"] == 1
    assert response.context["user_solution_record_stats"]["published_total"] == 1
    first_row = response.context["user_solution_record_rows"][0]
    assert first_row["user_label"] == "Mary Cartwright"
    assert first_row["title"] == "Circle setup"
    assert first_row["status_label"] == "Published"
    assert first_row["block_count"] == 1
    assert first_row["archive_url"].endswith("#imo-2025-p2")
    assert first_row["solution_url"] == (
        reverse("solutions:problem_solution_list", args=[problem.problem_uuid])
        + f"?solution={solution.id}#solution-{solution.id}"
    )
    response_html = response.content.decode("utf-8")
    assert "User solution listing" in response_html
    assert 'id="user-solution-record-table"' in response_html
    assert f'"solution_url": "{reverse("solutions:problem_solution_list", args=[problem.problem_uuid])}?solution={solution.id}#solution-{solution.id}"' in response_html


def test_completion_record_list_applies_query_filters(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    matching_user = UserFactory(name="Ada Lovelace", email="ada@example.com")
    other_user = UserFactory(name="Grace Hopper", email="grace@example.com")
    client.force_login(admin_user)

    problem_one = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=6,
        contest="USAMO",
        problem="P1",
        contest_year_problem="USAMO 2026 P1",
    )
    problem_two = ProblemSolveRecord.objects.create(
        year=2025,
        topic="GEO",
        mohs=5,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2025 P2",
    )
    UserProblemCompletion.objects.create(
        user=matching_user,
        problem=problem_one,
        completion_date=date(2026, 7, 10),
    )
    UserProblemCompletion.objects.create(
        user=other_user,
        problem=problem_two,
        completion_date=None,
    )
    ProblemSolution.objects.create(
        problem=problem_one,
        author=matching_user,
        status=ProblemSolution.Status.DRAFT,
    )

    response = client.get(
        reverse("pages:completion_record_list"),
        {
            "contest": "USAMO",
            "user": "ada@example.com",
            "date_status": "known",
            "solution_status": ProblemSolution.Status.DRAFT,
            "q": "Ada P1",
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["completion_record_filters"]["contest"] == "USAMO"
    assert response.context["completion_record_filters"]["user"] == "ada@example.com"
    assert response.context["completion_record_stats"]["record_total"] == 1
    assert len(response.context["completion_record_rows"]) == 1
    assert response.context["completion_record_rows"][0]["user_email"] == "ada@example.com"
    response_html = response.content.decode("utf-8")
    assert 'name="contest"' in response_html
    assert 'value="ada@example.com" selected' in response_html


def test_user_solution_record_list_applies_query_filters(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    matching_user = UserFactory(name="Mary Cartwright", email="mary@example.com")
    other_user = UserFactory(name="Emmy Noether", email="emmy@example.com")
    client.force_login(admin_user)

    problem_one = ProblemSolveRecord.objects.create(
        year=2025,
        topic="GEO",
        mohs=5,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2025 P2",
    )
    problem_two = ProblemSolveRecord.objects.create(
        year=2024,
        topic="ALG",
        mohs=4,
        contest="USAMO",
        problem="P1",
        contest_year_problem="USAMO 2024 P1",
    )
    ProblemSolution.objects.create(
        problem=problem_one,
        author=matching_user,
        title="Circle setup",
        summary="Use inversion.",
        status=ProblemSolution.Status.PUBLISHED,
        published_at=timezone.now(),
    )
    ProblemSolution.objects.create(
        problem=problem_two,
        author=other_user,
        title="Algebra draft",
        summary="Polynomial setup.",
        status=ProblemSolution.Status.DRAFT,
    )

    response = client.get(
        reverse("pages:user_solution_record_list"),
        {
            "contest": "IMO",
            "user": "mary@example.com",
            "status": ProblemSolution.Status.PUBLISHED,
            "q": "Circle P2",
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["user_solution_record_filters"]["contest"] == "IMO"
    assert response.context["user_solution_record_filters"]["user"] == "mary@example.com"
    assert response.context["user_solution_record_stats"]["solution_total"] == 1
    assert len(response.context["user_solution_record_rows"]) == 1
    assert response.context["user_solution_record_rows"][0]["user_email"] == "mary@example.com"
    response_html = response.content.decode("utf-8")
    assert 'name="status"' in response_html
    assert 'value="mary@example.com" selected' in response_html


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
    assert 'textbullet: "\\\\bullet"' in response_html
    assert 'hdots: "\\\\dots"' in response_html
    assert 'overarc: ["\\\\overset{\\\\frown}{#1}", 1]' in response_html
    assert 'vspace: ["\\\\kern0pt", 1]' in response_html


def test_handle_summary_parser_extracts_export_rows():
    parsed_rows = parse_handle_summary_text(HANDLE_SUMMARY_PARSER_SAMPLE)
    preview_payload = build_handle_summary_preview_payload(parsed_rows)
    first_expected_row = EXPECTED_HANDLE_SUMMARY_ROWS[0]

    assert len(parsed_rows) == 6
    assert parsed_rows[0].handle == first_expected_row["handle"]
    assert parsed_rows[0].mohs == first_expected_row["mohs"]
    assert parsed_rows[0].confidence == first_expected_row["confidence"]
    assert parsed_rows[0].imo_slot == first_expected_row["imo_slot"]
    assert parsed_rows[0].topic_tags == first_expected_row["topic_tags"]
    assert parsed_rows[3].confidence == "Medium-Low"
    assert preview_payload["row_count"] == 6
    assert preview_payload["export_tsv"] == EXPECTED_HANDLE_SUMMARY_EXPORT_TSV


def test_handle_summary_parser_accepts_mohs_ranges_and_uses_lower_bound():
    parsed_rows = parse_handle_summary_text(HANDLE_SUMMARY_PARSER_RANGE_SAMPLE)
    preview_payload = build_handle_summary_preview_payload(parsed_rows)

    assert len(parsed_rows) == 12
    assert [row.mohs for row in parsed_rows] == [8, 28, 40, 23, 34, 33, 26, 42, 45, 38, 46, 42]
    assert parsed_rows[0].handle == "Reciprocal square roots between 2026 and 2027"
    assert parsed_rows[0].mohs == 8
    assert parsed_rows[0].confidence == "High"
    assert parsed_rows[0].imo_slot == "P1/4"
    assert parsed_rows[0].topic_tags == "Alg/estimation; telescoping; integral comparison"
    assert parsed_rows[-1].handle == "No infinite arithmetic progression of chaotic integers"
    assert parsed_rows[-1].mohs == 42
    assert parsed_rows[-1].confidence == "Low"
    assert preview_payload["row_count"] == 12
    assert (
        preview_payload["export_tsv"].splitlines()[1]
        == "8\tHigh\tP1/4\tAlg/estimation; telescoping; integral comparison"
    )
    assert (
        preview_payload["export_tsv"].splitlines()[-1]
        == "42\tLow\tP3/6\tNT - additive forms; congruences; arithmetic progressions"
    )


def test_handle_summary_parser_accepts_open_ended_mohs_band_and_uses_lower_bound():
    parsed_rows = parse_handle_summary_text(
        "\n".join(
            [
                "Handle: Good n from harmonic numerators mod p",
                "Estimated MOHS: 50M+",
                "IMO slot guess: P3/6",
                "Topic tags: NT - harmonic numbers / p-adic congruences / sparse sets",
                "Confidence: Medium",
            ]
        )
    )
    preview_payload = build_handle_summary_preview_payload(parsed_rows)

    assert len(parsed_rows) == 1
    assert parsed_rows[0].mohs == 50
    assert preview_payload["row_count"] == 1
    assert (
        preview_payload["export_tsv"].splitlines()[1]
        == "50\tMedium\tP3/6\tNT - harmonic numbers / p-adic congruences / sparse sets"
    )


def test_handle_summary_parser_accepts_mohs_range_with_to_word():
    parsed_rows = parse_handle_summary_text(
        "\n".join(
            [
                "Handle: Red-blue averaging cards",
                "Estimated MOHS: 20M to 25M",
                "IMO slot guess: P1/4",
                "Topic tags: Comb – invariants; Alg – averaging",
                "Core ideas:",
                "Sort red and blue separately.",
                "Confidence: High",
            ]
        )
    )

    assert len(parsed_rows) == 1
    assert parsed_rows[0].mohs == 20
    assert parsed_rows[0].handle == "Red-blue averaging cards"


def test_handle_summary_parser_allows_authenticated_access(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:handle_summary_parser"))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Handle summary parser" in response_html
    assert "MOHS" in response_html
    assert "TOPICS TAG" in response_html
    assert 'id="handle-summary-parser-form"' in response_html


def test_problem_analytics_dashboard_exposes_contest_year_mohs_pivot_table(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    apmo_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="COMB",
        mohs=7,
        contest="APMO",
        problem="P1",
        contest_year_problem="APMO 2026 P1",
    )
    bmo_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=4,
        contest="BMO",
        problem="P1",
        contest_year_problem="BMO 2026 P1",
    )
    imo_problem_one = ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=4,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2025 P1",
    )
    imo_problem_two = ProblemSolveRecord.objects.create(
        year=2025,
        topic="GEO",
        mohs=4,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2025 P2",
    )
    ProblemSolveRecord.objects.create(
        year=2025,
        topic="NT",
        mohs=6,
        contest="IMO",
        problem="P3",
        contest_year_problem="IMO 2025 P3",
    )
    ProblemSolveRecord.objects.create(
        year=2024,
        topic="GEO",
        mohs=8,
        contest="EGMO",
        problem="P1",
        contest_year_problem="EGMO 2024 P1",
    )
    ProblemSolveRecord.objects.create(
        year=2023,
        topic="ALG",
        mohs=9,
        contest="USAMO",
        problem="P9",
        contest_year_problem="USAMO 2023 P9",
    )
    ContestProblemStatement.objects.create(
        problem_uuid=apmo_problem.problem_uuid,
        contest_year=2026,
        contest_name="APMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="APMO 2026 P1 statement",
    )
    ContestProblemStatement.objects.create(
        problem_uuid=bmo_problem.problem_uuid,
        contest_year=2026,
        contest_name="BMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="BMO 2026 P1 statement",
    )
    ContestProblemStatement.objects.create(
        problem_uuid=imo_problem_one.problem_uuid,
        contest_year=2025,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="IMO 2025 P1 statement",
    )
    ContestProblemStatement.objects.create(
        problem_uuid=imo_problem_two.problem_uuid,
        contest_year=2025,
        contest_name="IMO",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="IMO 2025 P2 statement",
    )
    ContestProblemStatement.objects.create(
        contest_year=2024,
        contest_name="EGMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="EGMO 2024 P1 statement",
    )
    ContestProblemStatement.objects.create(
        contest_year=2024,
        contest_name="JBMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="JBMO 2024 P1 statement",
    )

    response = client.get(reverse("pages:dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["analytics_total"] == 6
    assert response.context["charts_payload"]["byYear"]["labels"] == ["2024", "2025", "2026"]
    assert len(response.context["table_rows"]) == 6
    assert all(row["contest_year_problem"] != "USAMO 2023 P9" for row in response.context["table_rows"])
    pivot_payload = response.context["charts_payload"]["contestYearMohsPivotTable"]
    assert pivot_payload["contest_names"] == ["APMO", "BMO", "EGMO", "IMO", "JBMO"]
    assert pivot_payload["year_values"] == ["2026", "2025", "2024"]
    assert pivot_payload["mohs_values"] == ["4", "7", "8"]
    assert pivot_payload["table_rows"] == [
        {
            "contest_name": "APMO",
            "contest_year": 2026,
            "contest_year_label": "APMO 2026",
            "mohs_counts": {"4": 0, "7": 1, "8": 0},
        },
        {
            "contest_name": "BMO",
            "contest_year": 2026,
            "contest_year_label": "BMO 2026",
            "mohs_counts": {"4": 1, "7": 0, "8": 0},
        },
        {
            "contest_name": "EGMO",
            "contest_year": 2024,
            "contest_year_label": "EGMO 2024",
            "mohs_counts": {"4": 0, "7": 0, "8": 1},
        },
        {
            "contest_name": "IMO",
            "contest_year": 2025,
            "contest_year_label": "IMO 2025",
            "mohs_counts": {"4": 2, "7": 0, "8": 0},
        },
        {
            "contest_name": "JBMO",
            "contest_year": 2024,
            "contest_year_label": "JBMO 2024",
            "mohs_counts": {"4": 0, "7": 0, "8": 0},
        },
    ]
    response_html = response.content.decode("utf-8")
    assert "Problem analytics" in response_html
    assert "Contest-year vs MOHS pivot table" in response_html
    assert 'id="contest-year-mohs-search"' in response_html
    assert 'id="contest-year-mohs-contest-filter"' in response_html
    assert 'id="contest-year-mohs-year-filter"' in response_html
    assert 'id="contest-year-mohs-reset"' in response_html
    assert 'id="contest-year-mohs-pivot-table"' in response_html
    assert "Pivot DataTable with index, search, and filters." in response_html
    assert (
        "Problem statements define the rows, contest-year runs down the left, MOHS values sit across the top, "
        "and each cell shows the problem count." in response_html
    )


def test_technique_dashboard_exposes_filters_and_legacy_alias(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    imo_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=25,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2025 P1",
    )
    egmo_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="NT",
        mohs=35,
        contest="EGMO",
        problem="P2",
        contest_year_problem="EGMO 2024 P2",
    )
    bmo_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="COMB",
        mohs=20,
        contest="BMO",
        problem="P3",
        contest_year_problem="BMO 2025 P3",
    )
    ProblemTopicTechnique.objects.create(record=imo_problem, technique="LTE", domains=["NT"])
    ProblemTopicTechnique.objects.create(record=imo_problem, technique="PARITY", domains=["COMB"])
    ProblemTopicTechnique.objects.create(record=egmo_problem, technique="LTE", domains=["NT"])
    ProblemTopicTechnique.objects.create(record=bmo_problem, technique="INVARIANTS", domains=["ALG", "COMB"])

    response = client.get(reverse("pages:technique_dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["technique_total"] == 3
    assert response.context["technique_row_total"] == 4
    assert response.context["tagged_problem_total"] == 3
    assert response.context["technique_stats"] == {
        "contest_total": 3,
        "domain_total": 3,
        "topic_total": 3,
        "average_techniques_per_problem": 1.33,
    }
    assert response.context["technique_filter_options"] == {
        "contests": ["BMO", "EGMO", "IMO"],
        "domains": ["ALG", "COMB", "NT"],
        "topics": ["Algebra", "Combinatorics", "Number Theory"],
        "years": ["2025", "2024"],
    }
    lte_row = next(row for row in response.context["technique_rows"] if row["technique"] == "LTE")
    assert lte_row["problem_count"] == 2
    assert lte_row["contest_count"] == 2
    assert lte_row["topic_count"] == 2
    assert lte_row["domains"] == ["NT"]
    assert lte_row["years"] == ["2024", "2025"]
    assert lte_row["year_span_label"] == "2024-2025"
    assert lte_row["sample_contests_label"] == "EGMO, IMO"

    response_html = response.content.decode("utf-8")
    assert "Technique analytics" in response_html
    assert 'id="technique-dashboard-search"' in response_html
    assert 'id="technique-dashboard-contest-filter"' in response_html
    assert 'id="technique-dashboard-topic-filter"' in response_html
    assert 'id="technique-dashboard-domain-filter"' in response_html
    assert 'id="technique-dashboard-year-filter"' in response_html
    assert 'id="technique-dashboard-reset"' in response_html
    assert 'id="technique-analytics-table"' in response_html
    assert "ProblemTopicTechnique" in response_html

    legacy_response = client.get(reverse("pages:topic_tag_dashboard"))
    assert legacy_response.status_code == HTTPStatus.OK
    assert legacy_response.context["technique_total"] == 3


def test_problem_statement_linker_shows_rows_suggestions_and_candidate_groups(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    linked_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=25,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2025 P1",
    )
    suggested_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="GEO",
        mohs=30,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2025 P2",
    )
    linked_statement = ContestProblemStatement.objects.create(
        linked_problem=linked_problem,
        contest_year=2025,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Linked statement body",
    )
    suggested_statement = ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name="IMO",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Suggested statement body",
    )
    candidateless_statement = ContestProblemStatement.objects.create(
        contest_year=2024,
        contest_name="JBMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="No candidate statement body",
    )

    response = client.get(reverse("pages:problem_statement_linker"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["statement_linker_total"] == 3
    assert response.context["statement_linker_stats"] == {
        "contest_total": 2,
        "linked_total": 1,
        "suggested_total": 1,
        "unlinked_total": 2,
    }
    row_by_id = {row["statement_id"]: row for row in response.context["statement_linker_rows"]}
    assert row_by_id[linked_statement.id]["is_linked"] is True
    assert row_by_id[linked_statement.id]["linked_problem_label"] == "IMO 2025 P1"
    assert row_by_id[suggested_statement.id]["suggested_problem_id"] == suggested_problem.id
    assert row_by_id[suggested_statement.id]["suggestion_reason"] == "Problem code match"
    assert row_by_id[candidateless_statement.id]["candidate_count"] == 0
    candidate_group_key = row_by_id[suggested_statement.id]["candidate_group_key"]
    assert response.context["statement_linker_candidate_groups"][candidate_group_key] == [
        {
            "claimed_statement_label": "IMO 2025 P1 · Day 1",
            "is_claimed": True,
            "problem_id": linked_problem.id,
            "problem_label": "IMO 2025 P1",
            "option_label": "P1 · IMO 2025 P1 · Topic Algebra · MOHS 25",
        },
        {
            "claimed_statement_label": "",
            "is_claimed": False,
            "problem_id": suggested_problem.id,
            "problem_label": "IMO 2025 P2",
            "option_label": "P2 · IMO 2025 P2 · Topic Geometry · MOHS 30",
        },
    ]
    response_html = response.content.decode("utf-8")
    assert "Statement links" in response_html
    assert 'id="statement-linker-table"' in response_html
    assert 'id="statement-linker-search"' in response_html
    assert 'id="statement-linker-status-filter"' in response_html
    assert 'id="statement-linker-bulk-form"' in response_html
    assert 'id="statement-linker-save-staged"' in response_html
    assert "Save staged links" in response_html


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
    ProblemTopicTechnique.objects.create(record=linked_record, technique="ZSIGMONDY", domains=["NT"])
    UserProblemCompletion.objects.create(
        user=user,
        problem=linked_record,
        completion_date=date(2025, 8, 28),
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
    assert linked_row["linked_problem_topic"] == "Number Theory"
    assert linked_row["linked_problem_uuid"] == str(linked_record.problem_uuid)
    assert "linked_problem_label" not in linked_row
    assert "linked_problem_url" not in linked_row
    assert linked_row["linked_problem_topic_tags"] == ["LTE", "ZSIGMONDY"]
    assert linked_row["linked_problem_topic_tag_links"][0]["label"] == "LTE"
    assert linked_row["linked_problem_topic_tag_links"][0]["url"].endswith("?tag=LTE")
    assert linked_row["linked_problem_mohs"] == EXPECTED_LINKED_PROBLEM_MOHS
    assert linked_row["linked_problem_mohs_url"].endswith("?mohs=4")
    assert linked_row["linked_problem_confidence"] == "35M / 33M"
    assert "?q=35M+%2F+33M" in linked_row["linked_problem_confidence_url"]
    assert linked_row["linked_problem_imo_slot_guess_value"] == "2,5"
    assert "?q=2%2C5" in linked_row["linked_problem_imo_slot_url"]
    assert "statement_length" not in linked_row
    assert linked_row["problem_destination_label"] == "Start"
    response_html = response.content.decode("utf-8")
    assert "function renderTopicTagsCell(value)" in response_html
    assert 'join("<br>")' in response_html
    assert linked_row["problem_destination_url"] == reverse(
        "solutions:problem_solution_edit",
        args=[linked_record.problem_uuid],
    )
    assert linked_row["user_completion_date"] == "2025-08-28"
    assert linked_row["user_completion_display"] == "2025-08-28"
    assert linked_row["user_completion_state_kind"] == "solved"
    assert linked_row["user_completion_state_label"] == "Solved on 2025-08-28"
    assert "Problem statements" in response_html
    assert 'id="statement-year-filter"' in response_html
    assert 'id="statement-topic-filter"' in response_html
    assert 'id="statement-confidence-filter"' in response_html
    assert 'id="statement-mohs-min"' in response_html
    assert 'id="statement-mohs-max"' in response_html
    assert 'id="problem-statements-copy"' in response_html
    assert "Copy filtered rows" in response_html
    assert "Filter linked rows by metadata" in response_html
    assert 'data: "linked_problem_topic"' in response_html
    assert 'data: "user_completion_display"' in response_html
    assert 'data: "problem_destination_url"' in response_html
    assert 'title: "Solution"' in response_html
    assert 'title: "Chars"' not in response_html
    assert 'title: "Linked problem"' not in response_html
    assert 'title: "Preview"' not in response_html
    assert "formatImoSlotLabel" in response_html
    assert "populateFilterSelect" in response_html
    assert "statement-completion-save" not in response_html
    assert "statement-completion-date" not in response_html
    assert 'id="statement-completion-feedback"' not in response_html
    assert "statement_completion_toggle_url" not in response_html
    assert "data-completion-toggle-url=" not in response_html
    assert 'return column.data === "updated_at";' in response_html
    assert 'order: [[updatedAtColumnIndex, "desc"]]' in response_html
    assert "scrollX: true" in response_html
    assert 'class="statement-table-shell"' in response_html
    assert "table.columns.adjust();" in response_html
    assert "updated_at_sort" in response_html
    assert "renderChipLinks" not in response_html


def test_problem_detail_view_redirects_to_solution_editor_when_no_solution_exists(client):
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

    response = client.get(reverse("pages:problem_detail", args=[linked_record.problem_uuid]))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse(
        "solutions:problem_solution_edit",
        args=[linked_record.problem_uuid],
    )


def test_problem_detail_view_redirects_to_solution_page_when_visible_solution_exists(client):
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
    ProblemSolution.objects.create(
        problem=linked_record,
        author=user,
        title="My draft",
        status=ProblemSolution.Status.DRAFT,
    )

    response = client.get(reverse("pages:problem_detail", args=[linked_record.problem_uuid]))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse(
        "solutions:problem_solution_list",
        args=[linked_record.problem_uuid],
    )


def test_problem_statement_list_completion_toggle_updates_user_completion_date(client):
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
    statement = ContestProblemStatement.objects.create(
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Linked statement preview text",
        linked_problem=linked_record,
    )

    response = client.post(
        reverse("pages:completion_board_toggle"),
        {
            "action": "set_date",
            "completion_date": "2025-08-28",
            "problem_uuid": str(linked_record.problem_uuid),
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["completion_date"] == "2025-08-28"
    assert payload["is_solved"] is True
    assert payload["state_kind"] == "solved"
    assert payload["state_label"] == "Solved on 2025-08-28"
    assert payload["statement_uuid"] == str(statement.statement_uuid)
    completion = UserProblemCompletion.objects.get(user=user, statement=statement)
    assert completion.problem is None
    assert completion.completion_date == date(2025, 8, 28)


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


def test_problem_statement_linker_links_selected_problem_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    selected_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="N",
        mohs=20,
        contest="IMO",
        problem="P4",
        contest_year_problem="IMO 2025 P4",
    )
    statement = ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name="IMO",
        problem_number=4,
        problem_code="P4",
        day_label="Day 2",
        statement_latex="Unlinked statement",
    )

    response = client.post(
        reverse("pages:problem_statement_linker"),
        {
            "action": "link_selected",
            "statement_id": statement.id,
            "selected_problem_id": selected_problem.id,
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    statement.refresh_from_db()
    assert statement.linked_problem_id == selected_problem.id
    assert statement.problem_uuid == selected_problem.problem_uuid
    assert any(
        'Linked "IMO 2025 P4 · Day 2" to "IMO 2025 P4".' in str(message)
        for message in response.context["messages"]
    )


def test_problem_statement_linker_bulk_links_multiple_selected_problems_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    first_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="G",
        mohs=25,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2025 P1",
    )
    second_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="A",
        mohs=30,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2025 P2",
    )
    first_statement = ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1A",
        day_label="Day 1",
        statement_latex="First unlinked statement",
    )
    second_statement = ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name="IMO",
        problem_number=2,
        problem_code="P2A",
        day_label="Day 2",
        statement_latex="Second unlinked statement",
    )

    response = client.post(
        reverse("pages:problem_statement_linker"),
        {
            "action": "link_selected_bulk",
            "statement_ids": [first_statement.id, second_statement.id],
            "selected_problem_ids": [first_problem.id, second_problem.id],
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    first_statement.refresh_from_db()
    second_statement.refresh_from_db()
    assert first_statement.linked_problem_id == first_problem.id
    assert second_statement.linked_problem_id == second_problem.id
    assert first_statement.problem_uuid == first_problem.problem_uuid
    assert second_statement.problem_uuid == second_problem.problem_uuid
    assert any(
        "Saved 2 manual link(s)." in str(message)
        for message in response.context["messages"]
    )


def test_problem_statement_linker_clear_link_releases_claimed_uuid(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    linked_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="C",
        mohs=15,
        contest="IMO",
        problem="P5",
        contest_year_problem="IMO 2025 P5",
    )
    statement = ContestProblemStatement.objects.create(
        linked_problem=linked_problem,
        contest_year=2025,
        contest_name="IMO",
        problem_number=5,
        problem_code="P5",
        day_label="Day 2",
        statement_latex="Linked statement",
    )
    previous_uuid = statement.problem_uuid

    response = client.post(
        reverse("pages:problem_statement_linker"),
        {
            "action": "clear_link",
            "statement_id": statement.id,
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    statement.refresh_from_db()
    assert statement.linked_problem_id is None
    assert statement.problem_uuid != previous_uuid
    assert any(
        'Cleared the linked problem for "IMO 2025 P5 · Day 2".' in str(message)
        for message in response.context["messages"]
    )


def test_problem_statement_linker_rejects_problem_claimed_by_another_statement(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    claimed_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="A",
        mohs=35,
        contest="IMO",
        problem="P6",
        contest_year_problem="IMO 2025 P6",
    )
    ContestProblemStatement.objects.create(
        linked_problem=claimed_problem,
        contest_year=2025,
        contest_name="IMO",
        problem_number=6,
        problem_code="P6",
        day_label="Day 1",
        statement_latex="Claiming statement",
    )
    unlinked_statement = ContestProblemStatement.objects.create(
        contest_year=2025,
        contest_name="IMO",
        problem_number=6,
        problem_code="P6A",
        day_label="Day 2",
        statement_latex="Another statement",
    )

    response = client.post(
        reverse("pages:problem_statement_linker"),
        {
            "action": "link_selected",
            "statement_id": unlinked_statement.id,
            "selected_problem_id": claimed_problem.id,
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    unlinked_statement.refresh_from_db()
    assert unlinked_statement.linked_problem_id is None
    assert any(
        '"IMO 2025 P6" is already claimed by "IMO 2025 P6 · Day 1".' in str(message)
        for message in response.context["messages"]
    )


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


def test_problem_statement_duplicates_detects_exact_and_similar_matches_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    exact_text = "Determine all integers $n$ such that $n^2+n+1$ is prime."
    similar_text_a = (
        "Let $ABC$ be a triangle with circumcenter $O$. Prove that the reflections of $O$ "
        "across $AB$, $BC$, and $CA$ lie on a common circle centered at the nine-point center."
    )
    similar_text_b = (
        "Let $ABC$ be a triangle with circumcenter $O$. Prove that the reflections of $O$ "
        "across $AB$, $BC$, and $CA$ lie on the same circle centered at the nine-point center."
    )

    exact_problem_old = ProblemSolveRecord.objects.create(
        year=2024,
        topic="NT",
        mohs=5,
        contest="USAMO",
        problem="P1",
        contest_year_problem="USAMO 2024 P1",
    )
    exact_problem_new = ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=6,
        contest="USA TST",
        problem="P4",
        contest_year_problem="USA TST 2025 P4",
    )
    linked_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="GEO",
        mohs=6,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2024 P2",
    )
    ContestProblemStatement.objects.create(
        linked_problem=exact_problem_old,
        contest_year=2024,
        contest_name="USAMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex=exact_text,
    )
    ContestProblemStatement.objects.create(
        linked_problem=exact_problem_new,
        contest_year=2025,
        contest_name="USA TST",
        problem_number=4,
        problem_code="P4",
        day_label="Day 2",
        statement_latex=exact_text,
    )
    ContestProblemStatement.objects.create(
        linked_problem=linked_problem,
        contest_year=2024,
        contest_name="IMO",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex=similar_text_a,
    )
    ContestProblemStatement.objects.create(
        contest_year=2024,
        contest_name="ISL",
        problem_number=7,
        problem_code="G7",
        day_label="Geometry",
        statement_latex=similar_text_b,
    )
    ContestProblemStatement.objects.create(
        contest_year=2023,
        contest_name="BMO",
        problem_number=3,
        problem_code="P3",
        day_label="Round 1",
        statement_latex="Show that $1+1=2$.",
    )

    response = client.get(reverse("pages:problem_statement_duplicates"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["statement_duplicate_stats"] == {
        "statement_total": 5,
        "exact_duplicate_group_total": 1,
        "exact_duplicate_row_total": 2,
        "similar_pair_total": 1,
    }
    exact_rows = response.context["statement_duplicate_exact_rows"]
    assert len(exact_rows) == 1
    assert exact_rows[0]["duplicate_count"] == 2
    assert exact_rows[0]["problem_labels"] == "USAMO 2024 P1\nUSA TST 2025 P4"
    assert [item["label"] for item in exact_rows[0]["problem_items"]] == [
        "USAMO 2024 P1",
        "USA TST 2025 P4",
    ]
    assert [item["url"] for item in exact_rows[0]["problem_items"]] == [
        reverse("pages:problem_detail", args=[exact_problem_old.problem_uuid]),
        reverse("pages:problem_detail", args=[exact_problem_new.problem_uuid]),
    ]
    similar_rows = response.context["statement_duplicate_similar_rows"]
    assert len(similar_rows) == 1
    assert similar_rows[0]["similarity_percent"] >= 90
    assert "IMO 2024 P2" in similar_rows[0]["left_statement"]
    assert "ISL 2024 G7" in similar_rows[0]["right_statement"]
    response_html = response.content.decode("utf-8")
    assert "Statement duplicates" in response_html
    assert "Exact duplicate statement groups" in response_html
    assert "High-similarity statement pairs" in response_html
    assert 'id="statement-exact-duplicates-table"' in response_html
    assert 'id="statement-similarity-table"' in response_html
    assert reverse("pages:problem_detail", args=[exact_problem_new.problem_uuid]) in response_html
    assert reverse("pages:problem_detail", args=[exact_problem_old.problem_uuid]) in response_html
    assert reverse("pages:problem_statement_duplicates") in response_html


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
    assert dashboard_row["contest_year_url"] == (
        reverse("pages:contest_problem_list", args=[slugify(SPAIN_OLYMPIAD_NAME)])
        + f"?year={SPAIN_OLYMPIAD_YEAR}"
    )
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
    assert "contest_year_url" in response_html
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


def test_handle_summary_parser_post_builds_export_table(client):
    user = UserFactory()
    client.force_login(user)
    first_expected_row = EXPECTED_HANDLE_SUMMARY_ROWS[0]

    response = client.post(
        reverse("pages:handle_summary_parser"),
        {"source_text": HANDLE_SUMMARY_PARSER_SAMPLE},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context["preview_payload"]["row_count"] == 6
    assert response.context["preview_payload"]["rows"][0] == first_expected_row
    assert response.context["preview_payload"]["export_tsv"] == EXPECTED_HANDLE_SUMMARY_EXPORT_TSV
    response_html = response.content.decode("utf-8")
    assert "Parsed rows" in response_html
    assert "Copy TSV" in response_html
    assert "Recurrence-permutation triples in Z_n" in response_html


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


def test_problem_import_page_renders_statement_csv_tools_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    response = client.get(reverse("pages:problem_import"))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Export statement table" in response_html
    assert "Upload statement CSV" in response_html
    assert "?action=export_statement_xlsx" in response_html
    assert "Export statement XLSX" in response_html
    assert 'id="problem-statement-csv-import-form"' in response_html


def test_problem_import_page_exports_statement_workbook_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    linked_problem = ProblemSolveRecord.objects.create(
        year=SPAIN_OLYMPIAD_YEAR,
        topic="NT",
        mohs=4,
        contest=SPAIN_OLYMPIAD_NAME,
        problem="P1",
        contest_year_problem=f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
    )
    ContestProblemStatement.objects.create(
        linked_problem=linked_problem,
        contest_year=SPAIN_OLYMPIAD_YEAR,
        contest_name=SPAIN_OLYMPIAD_NAME,
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Exported statement",
    )

    response = client.get(reverse("pages:problem_import"), {"action": "export_statement_xlsx"})

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"].startswith(WORKBOOK_CONTENT_TYPE)
    assert response["Content-Disposition"].startswith(
        'attachment; filename="asterproof-problem-statements-',
    )
    exported_dataframe = pd.read_excel(BytesIO(response.content), dtype=str).fillna("")
    exported_rows = exported_dataframe.to_dict(orient="records")
    assert list(exported_dataframe.columns) == EXPECTED_STATEMENT_EXPORT_COLUMNS
    assert exported_rows == [{
        "PROBLEM UUID": str(linked_problem.problem_uuid),
        "LINKED PROBLEM UUID": str(linked_problem.problem_uuid),
        "CONTEST YEAR": str(SPAIN_OLYMPIAD_YEAR),
        "CONTEST NAME": SPAIN_OLYMPIAD_NAME,
        "CONTEST PROBLEM": f"{SPAIN_OLYMPIAD_NAME} {SPAIN_OLYMPIAD_YEAR} P1",
        "DAY LABEL": "Day 1",
        "PROBLEM NUMBER": "1",
        "PROBLEM CODE": "P1",
        "STATEMENT LATEX": "Exported statement",
    }]


def test_problem_statement_metadata_page_renders_tools_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Render the metadata table",
    )

    response = client.get(reverse("pages:problem_statement_metadata"))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    assert "Statement metadata" in response_html
    assert "Export metadata workbook" in response_html
    assert "Browser editor" in response_html
    assert "Save staged metadata" in response_html
    assert "?action=export" in response_html
    assert 'id="statement-metadata-import-form"' in response_html
    assert 'id="statement-metadata-table"' in response_html


def test_problem_statement_metadata_page_bulk_saves_staged_rows_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    existing_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="A",
        mohs=20,
        confidence="Low",
        contest="Israel TST",
        problem="P1",
        contest_year_problem="Israel TST 2026 P1",
        imo_slot_guess="P1/4",
        topic_tags="Alg - old tag",
    )
    update_statement = ContestProblemStatement.objects.create(
        linked_problem=existing_problem,
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Update this statement",
    )
    create_statement = ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=3,
        problem_code="P3",
        day_label="Day 2",
        statement_latex="Create this problem row",
    )

    response = client.post(
        reverse("pages:problem_statement_metadata"),
        {
            "action": "save_grid",
            "replace_tags": "on",
            "problem_uuid": [
                str(update_statement.problem_uuid),
                str(create_statement.problem_uuid),
            ],
            "topic": ["G", "N"],
            "mohs": ["28", "35"],
            "confidence": ["Medium", "Medium-Low"],
            "imo_slot_guess": ["P2/5", "P3/6"],
            "topic_tags": [
                "Geo - circles",
                "NT - multiplicative functions; prime divisors",
            ],
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    existing_problem.refresh_from_db()
    update_statement.refresh_from_db()
    create_statement.refresh_from_db()
    created_problem = ProblemSolveRecord.objects.get(problem_uuid=create_statement.problem_uuid)

    assert existing_problem.topic == "G"
    assert existing_problem.mohs == 28
    assert existing_problem.confidence == "Medium"
    assert existing_problem.imo_slot_guess == "P2/5"
    assert existing_problem.topic_tags == "Geo - circles"
    assert update_statement.linked_problem_id == existing_problem.id
    assert created_problem.topic == "N"
    assert created_problem.mohs == 35
    assert created_problem.confidence == "Medium-Low"
    assert created_problem.imo_slot_guess == "P3/6"
    assert created_problem.topic_tags == "NT - multiplicative functions; prime divisors"
    assert create_statement.linked_problem_id == created_problem.id
    assert any(
        "Statement metadata save finished. Processed 2 row(s): 1 created, 1 updated, 2 linked, 3 technique row(s) touched, 0 untouched staged row(s) skipped."
        in str(message)
        for message in response.context["messages"]
    )


def test_problem_statement_metadata_page_bulk_save_supports_duplicate_problem_keys_within_one_batch(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    first_statement = ContestProblemStatement.objects.create(
        contest_year=2012,
        contest_name="USA IMO Team Selection Test",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="First P2 statement row",
    )
    second_statement = ContestProblemStatement.objects.create(
        contest_year=2012,
        contest_name="USA IMO Team Selection Test",
        problem_number=2,
        problem_code="P2",
        day_label="Day 2",
        statement_latex="Second P2 statement row",
    )

    response = client.post(
        reverse("pages:problem_statement_metadata"),
        {
            "action": "save_grid",
            "replace_tags": "on",
            "problem_uuid": [
                str(first_statement.problem_uuid),
                str(second_statement.problem_uuid),
            ],
            "topic": ["G", "G"],
            "mohs": ["25", "25"],
            "confidence": ["Medium", "Medium"],
            "imo_slot_guess": ["P1/4", "P1/4"],
            "topic_tags": ["Geo - circles", "Geo - circles"],
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    first_statement.refresh_from_db()
    second_statement.refresh_from_db()
    matching_records = list(
        ProblemSolveRecord.objects.filter(
            year=2012,
            contest="USA IMO Team Selection Test",
            problem="P2",
        ).order_by("id")
    )
    assert len(matching_records) == 2
    assert {record.problem_uuid for record in matching_records} == {
        first_statement.problem_uuid,
        second_statement.problem_uuid,
    }
    assert first_statement.linked_problem_id is not None
    assert second_statement.linked_problem_id is not None
    assert first_statement.linked_problem.problem_uuid == first_statement.problem_uuid
    assert second_statement.linked_problem.problem_uuid == second_statement.problem_uuid
    assert any(
        "Statement metadata save finished. Processed 2 row(s): 2 created, 0 updated, 2 linked, 2 technique row(s) touched, 0 untouched staged row(s) skipped."
        in str(message)
        for message in response.context["messages"]
    )


def test_problem_statement_metadata_page_exports_workbook_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    linked_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="G",
        mohs=25,
        confidence="Medium",
        contest="Israel TST",
        problem="P1",
        contest_year_problem="Israel TST 2026 P1",
        imo_slot_guess="P1/4",
        topic_tags="Geo – circles; isogonality",
    )
    ContestProblemStatement.objects.create(
        linked_problem=linked_problem,
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="= foot(A, B, C);",
    )

    response = client.get(reverse("pages:problem_statement_metadata"), {"action": "export"})

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"].startswith(WORKBOOK_CONTENT_TYPE)
    assert response["Content-Disposition"].startswith(
        'attachment; filename="asterproof-statement-metadata-',
    )
    exported_dataframe = pd.read_excel(BytesIO(response.content), dtype=str).fillna("")
    exported_rows = exported_dataframe.to_dict(orient="records")
    assert list(exported_dataframe.columns) == EXPECTED_STATEMENT_METADATA_EXPORT_COLUMNS
    assert exported_rows == [{
        "PROBLEM UUID": str(linked_problem.problem_uuid),
        "CONTEST YEAR": "2026",
        "CONTEST NAME": "Israel TST",
        "CONTEST PROBLEM": "Israel TST 2026 P1",
        "DAY LABEL": "Day 1",
        "PROBLEM NUMBER": "1",
        "PROBLEM CODE": "P1",
        "STATEMENT LATEX": "= foot(A, B, C);",
        "TOPIC": "G",
        "MOHS": "25",
        "Confidence": "Medium",
        "IMO slot guess": "P1/4",
        "Topic tags": "Geo – circles; isogonality",
    }]


def test_problem_statement_metadata_page_imports_workbook_and_creates_problem_rows(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    statement = ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Backfill this statement",
    )

    response = client.post(
        reverse("pages:problem_statement_metadata"),
        {
            "replace_tags": "on",
            "file": _xlsx_upload(
                {
                    "PROBLEM UUID": str(statement.problem_uuid),
                    "CONTEST YEAR": 2026,
                    "CONTEST NAME": "Israel TST",
                    "CONTEST PROBLEM": "Israel TST 2026 P2",
                    "DAY LABEL": "Day 1",
                    "PROBLEM NUMBER": 2,
                    "PROBLEM CODE": "P2",
                    "STATEMENT LATEX": "Backfill this statement",
                    "TOPIC": "G",
                    "MOHS": 25,
                    "Confidence": "Medium",
                    "IMO slot guess": "P1/4",
                    "Topic tags": "Geo – circles; isogonality",
                },
                {
                    "PROBLEM UUID": str(uuid.uuid4()),
                    "CONTEST YEAR": 2026,
                    "CONTEST NAME": "Israel TST",
                    "CONTEST PROBLEM": "Israel TST 2026 P9",
                    "DAY LABEL": "Day 2",
                    "PROBLEM NUMBER": 9,
                    "PROBLEM CODE": "P9",
                    "TOPIC": "",
                    "MOHS": "",
                    "Confidence": "",
                    "IMO slot guess": "",
                    "Topic tags": "",
                },
            ),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    statement.refresh_from_db()
    created_problem = ProblemSolveRecord.objects.get(problem_uuid=statement.problem_uuid)
    assert statement.linked_problem_id == created_problem.id
    assert created_problem.year == 2026
    assert created_problem.contest == "Israel TST"
    assert created_problem.problem == "P2"
    assert created_problem.contest_year_problem == "Israel TST 2026 P2"
    assert created_problem.topic == "G"
    assert created_problem.mohs == 25
    assert created_problem.confidence == "Medium"
    assert created_problem.imo_slot_guess == "P1/4"
    assert created_problem.topic_tags == "Geo – circles; isogonality"
    saved_tags = list(
        ProblemTopicTechnique.objects.filter(record=created_problem).order_by("technique")
    )
    assert [(tag.technique, tag.domains) for tag in saved_tags] == [
        ("CIRCLES", ["GEO"]),
        ("ISOGONALITY", ["GEO"]),
    ]
    assert any(
        "Statement metadata import finished. Processed 1 row(s): 1 created, 0 updated, 1 linked, 2 technique row(s) touched, 1 untouched workbook row(s) skipped."
        in str(message)
        for message in response.context["messages"]
    )


def test_problem_statement_metadata_page_imports_multiple_rows_and_updates_existing_problem(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    existing_problem = ProblemSolveRecord.objects.create(
        year=2012,
        topic="A",
        mohs=20,
        confidence="Low",
        contest="Israel TST",
        problem="P1",
        contest_year_problem="Israel TST 2026 P1",
        imo_slot_guess="P1/4",
        topic_tags="Alg - old tag",
    )
    update_statement = ContestProblemStatement.objects.create(
        linked_problem=existing_problem,
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Update this statement",
    )
    create_statement = ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=3,
        problem_code="P3",
        day_label="Day 2",
        statement_latex="Create this problem row",
    )

    response = client.post(
        reverse("pages:problem_statement_metadata"),
        {
            "replace_tags": "on",
            "file": _xlsx_upload(
                {
                    "PROBLEM UUID": str(update_statement.problem_uuid),
                    "CONTEST YEAR": 2026,
                    "CONTEST NAME": "Israel TST",
                    "CONTEST PROBLEM": "Israel TST 2026 P1",
                    "DAY LABEL": "Day 1",
                    "PROBLEM NUMBER": 1,
                    "PROBLEM CODE": "P1",
                    "STATEMENT LATEX": "Update this statement",
                    "TOPIC": "G",
                    "MOHS": 28,
                    "Confidence": "Medium",
                    "IMO slot guess": "P2/5",
                    "Topic tags": "Geo - circles",
                },
                {
                    "PROBLEM UUID": str(create_statement.problem_uuid),
                    "CONTEST YEAR": 2026,
                    "CONTEST NAME": "Israel TST",
                    "CONTEST PROBLEM": "Israel TST 2026 P3",
                    "DAY LABEL": "Day 2",
                    "PROBLEM NUMBER": 3,
                    "PROBLEM CODE": "P3",
                    "STATEMENT LATEX": "Create this problem row",
                    "TOPIC": "N",
                    "MOHS": 35,
                    "Confidence": "Medium-Low",
                    "IMO slot guess": "P3/6",
                    "Topic tags": "NT - multiplicative functions; prime divisors",
                },
            ),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    existing_problem.refresh_from_db()
    update_statement.refresh_from_db()
    create_statement.refresh_from_db()
    created_problem = ProblemSolveRecord.objects.get(problem_uuid=create_statement.problem_uuid)

    assert existing_problem.year == 2026
    assert existing_problem.contest == "Israel TST"
    assert existing_problem.problem == "P1"
    assert existing_problem.contest_year_problem == "Israel TST 2026 P1"
    assert existing_problem.topic == "G"
    assert existing_problem.mohs == 28
    assert existing_problem.confidence == "Medium"
    assert existing_problem.imo_slot_guess == "P2/5"
    assert existing_problem.topic_tags == "Geo - circles"
    assert update_statement.linked_problem_id == existing_problem.id
    assert created_problem.topic == "N"
    assert created_problem.mohs == 35
    assert created_problem.confidence == "Medium-Low"
    assert created_problem.imo_slot_guess == "P3/6"
    assert created_problem.topic_tags == "NT - multiplicative functions; prime divisors"
    assert create_statement.linked_problem_id == created_problem.id
    assert any(
        "Statement metadata import finished. Processed 2 row(s): 1 created, 1 updated, 2 linked, 3 technique row(s) touched, 0 untouched workbook row(s) skipped."
        in str(message)
        for message in response.context["messages"]
    )


def test_problem_statement_metadata_import_creates_new_problem_row_for_different_uuid_same_key(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    existing_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="A",
        mohs=20,
        confidence="Low",
        contest="Israel TST",
        problem="P2",
        contest_year_problem="Israel TST 2026 P2",
        imo_slot_guess="P1/4",
        topic_tags="Alg - old tag",
    )
    statement = ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="Conflict statement",
    )

    response = client.post(
        reverse("pages:problem_statement_metadata"),
        {
            "replace_tags": "on",
            "file": _xlsx_upload(
                {
                    "PROBLEM UUID": str(statement.problem_uuid),
                    "CONTEST YEAR": 2026,
                    "CONTEST NAME": "Israel TST",
                    "CONTEST PROBLEM": "Israel TST 2026 P2",
                    "DAY LABEL": "Day 1",
                    "PROBLEM NUMBER": 2,
                    "PROBLEM CODE": "P2",
                    "STATEMENT LATEX": "Conflict statement",
                    "TOPIC": "G",
                    "MOHS": 25,
                    "Confidence": "Medium",
                    "IMO slot guess": "P1/4",
                    "Topic tags": "Geo – circles",
                },
            ),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    statement.refresh_from_db()
    existing_problem.refresh_from_db()
    created_problem = ProblemSolveRecord.objects.get(problem_uuid=statement.problem_uuid)
    assert statement.linked_problem_id == created_problem.id
    assert existing_problem.topic == "A"
    assert created_problem.topic == "G"
    assert created_problem.mohs == 25
    assert ProblemSolveRecord.objects.filter(
        year=2026,
        contest="Israel TST",
        problem="P2",
    ).count() == 2
    assert any(
        "Statement metadata import finished. Processed 1 row(s): 1 created, 0 updated, 1 linked, 1 technique row(s) touched, 0 untouched workbook row(s) skipped."
        in str(message)
        for message in response.context["messages"]
    )


def test_problem_import_page_imports_statement_csv_rows_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)
    linked_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="Israel TST",
        problem="P1",
        contest_year_problem="Israel TST 2026 P1",
    )
    existing_statement = ContestProblemStatement.objects.create(
        contest_year=2026,
        contest_name="Israel TST",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="Old statement text",
    )

    response = client.post(
        reverse("pages:problem_import"),
        {
            "action": "import_statement_csv",
            "statement_csv-file": _csv_upload(
                {
                    "PROBLEM UUID": str(existing_statement.problem_uuid),
                    "LINKED PROBLEM UUID": str(linked_problem.problem_uuid),
                    "CONTEST YEAR": "2026",
                    "CONTEST NAME": "  Israel   TST  ",
                    "CONTEST PROBLEM": "ignored on import",
                    "DAY LABEL": " Day 1 ",
                    "PROBLEM NUMBER": "1",
                    "PROBLEM CODE": "p1",
                    "STATEMENT LATEX": "Updated linked statement",
                },
                {
                    "PROBLEM UUID": "",
                    "LINKED PROBLEM UUID": "",
                    "CONTEST YEAR": "2025",
                    "CONTEST NAME": "APMO",
                    "CONTEST PROBLEM": "",
                    "DAY LABEL": "",
                    "PROBLEM NUMBER": "2",
                    "PROBLEM CODE": "",
                    "STATEMENT LATEX": "Fresh standalone statement",
                },
            ),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert ContestProblemStatement.objects.count() == 2

    existing_statement.refresh_from_db()
    assert existing_statement.linked_problem_id == linked_problem.pk
    assert existing_statement.problem_uuid == linked_problem.problem_uuid
    assert existing_statement.statement_latex == "Updated linked statement"

    new_statement = ContestProblemStatement.objects.get(
        contest_year=2025,
        contest_name="APMO",
        day_label="",
        problem_number=2,
    )
    assert new_statement.problem_code == "P2"
    assert new_statement.statement_latex == "Fresh standalone statement"
    assert any(
        "Imported 2 problem statement row(s) from CSV." in str(message)
        for message in response.context["messages"]
    )


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


def test_user_activity_dashboard_imports_completion_rows_for_current_user(client):
    user = UserFactory()
    client.force_login(user)
    record_with_date = ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=4,
        contest="ISRAEL TST",
        problem="P2",
        contest_year_problem="ISRAEL TST 2026 P2",
    )
    record_done = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=5,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2026 P1",
    )

    response = client.post(
        reverse("pages:user_activity_dashboard"),
        data={
            "action": "import_completions",
            "source_text": (
                "PROBLEM UUID Date\n"
                f"{record_with_date.problem_uuid}\t2025-08-28\n"
                f"{record_done.problem_uuid}\tDone"
            ),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert UserProblemCompletion.objects.filter(user=user).count() == EXPECTED_USER_ACTIVITY_IMPORTED_TOTAL
    assert UserProblemCompletion.objects.get(user=user, problem=record_with_date).completion_date == date(2025, 8, 28)
    assert UserProblemCompletion.objects.get(user=user, problem=record_done).completion_date is None
    response_html = response.content.decode("utf-8")
    assert "Completion import" in response_html
    assert "Import completions" in response_html
    assert any(
        "Updated 2 completion row(s). 1 marked Done without an exact date." in str(message)
        for message in response.context["messages"]
    )


def test_user_activity_dashboard_shows_completion_import_errors(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("pages:user_activity_dashboard"),
        data={"action": "import_completions", "source_text": "   "},
    )

    assert response.status_code == HTTPStatus.OK
    assert UserProblemCompletion.objects.filter(user=user).count() == 0
    response_html = response.content.decode("utf-8")
    assert "Please fix the completion import form and try again." in response_html
    assert "Paste at least one completion row." in response_html
    assert 'id="activity-import-submit"' in response_html


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
        "topics": ["Algebra", "Geometry", "Number Theory"],
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
    assert recent_cell["title"].endswith("1 completion")
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
    assert "Completion import" in response_html
    assert "Completion heatmaps" in response_html
    assert 'id="chart-user-completions-by-month"' in response_html
    assert 'id="user-activity-table"' in response_html
    assert 'id="completion-year-filter"' in response_html
    assert "estimated from" not in response_html
    assert "Zero-completion days stay visible" in response_html
    assert 'class="activity-heatmap-grid"' in response_html
    assert 'class="activity-heatmap-weekdays"' in response_html
    assert 'data-bs-toggle="tooltip"' in response_html
    assert 'data-bs-title="' in response_html
    assert "Current window" in response_html
    assert "excluded from these time-based visuals" in response_html
    assert response_html.index("Completion history") < response_html.index("Completion import")
    assert "--activity-heatmap-level-4: #216e39;" in response_html
    assert "--activity-heatmap-level-4: #39d353;" in response_html
    assert 'order: [[0, "desc"], [2, "asc"], [1, "asc"]]' in response_html
    assert "bootstrap.Tooltip.getOrCreateInstance" in response_html
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


def test_user_activity_dashboard_exposes_statement_completion_heatmap(client):
    user = UserFactory()
    client.force_login(user)
    today = timezone.localdate()

    imo_2025_problem = ProblemSolveRecord.objects.create(
        year=2025,
        topic="ALG",
        mohs=5,
        contest="IMO",
        problem="P1",
        contest_year_problem="IMO 2025 P1",
    )
    imo_2026_problem_a = ProblemSolveRecord.objects.create(
        year=2026,
        topic="NT",
        mohs=6,
        contest="IMO",
        problem="P2",
        contest_year_problem="IMO 2026 P2",
    )
    imo_2026_problem_b = ProblemSolveRecord.objects.create(
        year=2026,
        topic="GEO",
        mohs=7,
        contest="IMO",
        problem="P3",
        contest_year_problem="IMO 2026 P3",
    )
    bmo_2026_problem = ProblemSolveRecord.objects.create(
        year=2026,
        topic="ALG",
        mohs=4,
        contest="BMO",
        problem="P1",
        contest_year_problem="BMO 2026 P1",
    )
    no_statement_problem = ProblemSolveRecord.objects.create(
        year=2024,
        topic="COMB",
        mohs=3,
        contest="EGMO",
        problem="P2",
        contest_year_problem="EGMO 2024 P2",
    )

    for index, problem in enumerate(
        [
            imo_2025_problem,
            imo_2026_problem_a,
            imo_2026_problem_b,
            bmo_2026_problem,
            no_statement_problem,
        ],
        start=1,
    ):
        UserProblemCompletion.objects.create(
            user=user,
            problem=problem,
            completion_date=today - timedelta(days=index),
        )

    ContestProblemStatement.objects.create(
        linked_problem=imo_2025_problem,
        contest_year=2025,
        contest_name="IMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="IMO 2025 P1 statement",
    )
    ContestProblemStatement.objects.create(
        linked_problem=imo_2026_problem_a,
        contest_year=2026,
        contest_name="IMO",
        problem_number=2,
        problem_code="P2",
        day_label="Day 1",
        statement_latex="IMO 2026 P2 statement",
    )
    ContestProblemStatement.objects.create(
        linked_problem=imo_2026_problem_b,
        contest_year=2026,
        contest_name="IMO",
        problem_number=3,
        problem_code="P3",
        day_label="Day 2",
        statement_latex="IMO 2026 P3 statement",
    )
    ContestProblemStatement.objects.create(
        linked_problem=bmo_2026_problem,
        contest_year=2026,
        contest_name="BMO",
        problem_number=1,
        problem_code="P1",
        day_label="Day 1",
        statement_latex="BMO 2026 P1 statement",
    )

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK
    heatmap_payload = response.context["activity_statement_completion_heatmap"]
    assert heatmap_payload["years"] == ["2025", "2026"]
    assert heatmap_payload["max_value"] == 2
    assert heatmap_payload["series"][0]["name"] == "IMO"
    assert heatmap_payload["series"][0]["data"] == [
        {"x": "2025", "y": 1},
        {"x": "2026", "y": 2},
    ]
    assert heatmap_payload["series"][1]["name"] == "BMO"
    assert heatmap_payload["series"][1]["data"] == [
        {"x": "2025", "y": 0},
        {"x": "2026", "y": 1},
    ]
    assert response.context["activity_statement_completion_stats"] == {
        "contest_year_total": 3,
        "statement_backed_completion_total": 4,
    }
    response_html = response.content.decode("utf-8")
    assert "Contest-year statement completion heatmap" in response_html
    assert 'id="chart-user-statement-completion-heatmap"' in response_html
    assert "4 completed statement-backed problems across 3 contest-year sets." in response_html


def test_user_activity_dashboard_exposes_topic_mohs_completion_heatmap(client):
    user = UserFactory()
    client.force_login(user)
    today = timezone.localdate()
    expected_max_value = 2

    problems = [
        ProblemSolveRecord.objects.create(
            year=2025,
            topic="ALG",
            mohs=5,
            contest="IMO",
            problem="P1",
            contest_year_problem="IMO 2025 P1",
        ),
        ProblemSolveRecord.objects.create(
            year=2024,
            topic="ALG",
            mohs=5,
            contest="BMO",
            problem="P2",
            contest_year_problem="BMO 2024 P2",
        ),
        ProblemSolveRecord.objects.create(
            year=2023,
            topic="COMB",
            mohs=7,
            contest="APMO",
            problem="P3",
            contest_year_problem="APMO 2023 P3",
        ),
        ProblemSolveRecord.objects.create(
            year=2022,
            topic="GEO",
            mohs=3,
            contest="EGMO",
            problem="P4",
            contest_year_problem="EGMO 2022 P4",
        ),
        ProblemSolveRecord.objects.create(
            year=2021,
            topic="NT",
            mohs=9,
            contest="ISL",
            problem="P5",
            contest_year_problem="ISL 2021 P5",
        ),
    ]

    for index, problem in enumerate(problems, start=1):
        UserProblemCompletion.objects.create(
            user=user,
            problem=problem,
            completion_date=today - timedelta(days=index),
        )

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK
    heatmap_payload = response.context["activity_topic_mohs_completion_heatmap"]
    assert heatmap_payload["mohs_values"] == ["3", "5", "7", "9"]
    assert heatmap_payload["max_value"] == expected_max_value
    assert heatmap_payload["series"] == [
        {
            "name": "Algebra",
            "data": [
                {"x": "3", "y": 0},
                {"x": "5", "y": 2},
                {"x": "7", "y": 0},
                {"x": "9", "y": 0},
            ],
        },
        {
            "name": "Combinatorics",
            "data": [
                {"x": "3", "y": 0},
                {"x": "5", "y": 0},
                {"x": "7", "y": 1},
                {"x": "9", "y": 0},
            ],
        },
        {
            "name": "Geometry",
            "data": [
                {"x": "3", "y": 1},
                {"x": "5", "y": 0},
                {"x": "7", "y": 0},
                {"x": "9", "y": 0},
            ],
        },
        {
            "name": "Number Theory",
            "data": [
                {"x": "3", "y": 0},
                {"x": "5", "y": 0},
                {"x": "7", "y": 0},
                {"x": "9", "y": 1},
            ],
        },
    ]
    assert response.context["activity_topic_mohs_completion_stats"] == {
        "cell_total": 4,
        "completion_total": 5,
        "mohs_total": 4,
        "topic_total": 4,
    }
    response_html = response.content.decode("utf-8")
    assert "Main topic vs MOHS completion heatmap" in response_html
    assert 'id="chart-user-topic-mohs-completion-heatmap"' in response_html
    assert "charts.topicMohsCompletionHeatmap.reverse_yaxis = true;" in response_html
    assert (
        "5 completed problems across 4 topic-MOHS cells, covering 4 main topic "
        "buckets and 4 MOHS levels."
    ) in response_html


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


def test_user_activity_dashboard_empty_state_points_to_import_panel(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("pages:user_activity_dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert (
        "Paste your solved problems in the completion import panel below to start building this dashboard."
        in response.content.decode("utf-8")
    )


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
    assert 'textbullet: "\\\\bullet"' in content
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
    assert response.context["selected_topic"] == "Number Theory"
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


def test_dashboard_sidebar_groups_links_into_clear_sections_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    response = client.get(reverse("pages:latex_preview"))

    assert response.status_code == HTTPStatus.OK
    response_html = response.content.decode("utf-8")
    side_nav_html = response_html.split('<ul class="side-nav">', 1)[1].split("</ul>", 1)[0]
    assert "Home" in side_nav_html
    assert "Personal" in side_nav_html
    assert "Library" in side_nav_html
    assert "Analytics" in side_nav_html
    assert "Curation" in side_nav_html
    assert "Tools" in side_nav_html
    assert "Admin" in side_nav_html
    assert side_nav_html.index("Overview") < side_nav_html.index("My account")
    assert side_nav_html.index("My account") < side_nav_html.index("My activity")
    assert "Completion board" not in side_nav_html
    assert side_nav_html.index("My activity") < side_nav_html.index("My solutions")
    assert side_nav_html.index("My solutions") < side_nav_html.index("Problem statements")
    assert side_nav_html.index("Problem statements") < side_nav_html.index("Problem analytics")
    assert "Technique analytics" in side_nav_html
    assert "Completion records" in side_nav_html
    assert "Solution records" in side_nav_html
    assert side_nav_html.index("Problem analytics") < side_nav_html.index("Completion records")
    assert side_nav_html.index("Completion records") < side_nav_html.index("Solution records")
    assert side_nav_html.index("Solution records") < side_nav_html.index("Problem data")
    assert "Statement editor" in side_nav_html
    assert "Statement metadata" in side_nav_html
    assert side_nav_html.index("Problem data") < side_nav_html.index("Statement metadata")
    assert side_nav_html.index("Statement links") < side_nav_html.index("Statement editor")
    assert side_nav_html.index("Statement editor") < side_nav_html.index("Statement metadata")
    assert side_nav_html.index("Statement metadata") < side_nav_html.index("LaTeX preview")
    assert "Handle parser" in side_nav_html
    assert side_nav_html.index("LaTeX preview") < side_nav_html.index("Handle parser")
    assert side_nav_html.index("Handle parser") < side_nav_html.index("User roles")


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
