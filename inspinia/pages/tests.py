from http import HTTPStatus
from io import BytesIO

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.problem_import import ProblemImportValidationError
from inspinia.pages.problem_import import dataframe_from_excel
from inspinia.pages.problem_import import import_problem_dataframe
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_RECORD_COUNT = 1
EXPECTED_ONE_TECHNIQUE = 1
EXPECTED_TWO_TECHNIQUES = 2
UPDATED_MOHS = 5
WORKBOOK_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    ) == ["LTE", "parity"]


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

    invariants = ProblemTopicTechnique.objects.get(record=record, technique="invariants")
    assert invariants.domains == ["ALG", "COMB"]
    assert ProblemTopicTechnique.objects.get(record=record, technique="LTE").domains == ["NT"]


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
    assert techniques == [("angle chasing", ["GEO"])]


@override_settings(DEBUG=True)
def test_dashboard_allows_anonymous_access_in_debug(client):
    response = client.get(reverse("pages:dashboard"))

    assert response.status_code == HTTPStatus.OK


def test_dashboard_forbids_non_admin_access_when_debug_is_off(client):
    response = client.get(reverse("pages:dashboard"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_dashboard_allows_admin_access_when_debug_is_off(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    response = client.get(reverse("pages:dashboard"))

    assert response.status_code == HTTPStatus.OK


def test_problem_import_forbids_non_admin_access_when_debug_is_off(client):
    response = client.get(reverse("pages:problem_import"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_problem_import_allows_admin_access_when_debug_is_off(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    response = client.get(reverse("pages:problem_import"))

    assert response.status_code == HTTPStatus.OK


def test_problem_import_preview_parses_workbook_without_writing_rows(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    response = client.post(
        reverse("pages:problem_import"),
        {
            "action": "preview",
            "file": _xlsx_upload(
                {
                    "YEAR": 2026,
                    "TOPIC": "NT",
                    "MOHS": 4,
                    "CONTEST": "ISRAEL TST",
                    "PROBLEM": "P2",
                    "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
                    "Topic tags": "Topic tags: NT - LTE, parity",
                },
            ),
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert ProblemSolveRecord.objects.count() == 0
    assert ProblemTopicTechnique.objects.count() == 0
    assert response.context["preview_payload"]["total_prepared_problems"] == EXPECTED_RECORD_COUNT
    assert response.context["preview_payload"]["total_parsed_techniques"] == EXPECTED_TWO_TECHNIQUES
    assert any("Parsed preview" in str(message) for message in response.context["messages"])


def test_problem_import_import_writes_records_for_admin(client):
    admin_user = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin_user)

    response = client.post(
        reverse("pages:problem_import"),
        {
            "action": "import",
            "file": _xlsx_upload(
                {
                    "YEAR": 2026,
                    "TOPIC": "NT",
                    "MOHS": 4,
                    "CONTEST": "ISRAEL TST",
                    "PROBLEM": "P2",
                    "CONTEST PROBLEM": "ISRAEL TST 2026 P2",
                    "Topic tags": "Topic tags: NT - LTE, parity",
                },
            ),
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert ProblemSolveRecord.objects.count() == EXPECTED_RECORD_COUNT
    assert ProblemTopicTechnique.objects.count() == EXPECTED_TWO_TECHNIQUES
    assert any("Import finished." in str(message) for message in response.context["messages"])
