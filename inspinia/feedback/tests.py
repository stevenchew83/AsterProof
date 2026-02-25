import pytest
from django.urls import reverse

from inspinia.backoffice.models import ProblemSubmission
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_create_problem_submission_saves_format_and_plaintext(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("feedback:create_problem_submission"),
        data={
            "title": "Sample",
            "statement": r"Show that $a+b=c$.",
            "statement_format": "latex",
            "proposed_difficulty": "3",
        },
    )
    assert response.status_code == 302

    row = ProblemSubmission.objects.latest("id")
    assert row.statement_format == ProblemSubmission.StatementFormat.LATEX
    assert row.statement_plaintext


def test_create_problem_submission_blocks_disallowed_latex(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("feedback:create_problem_submission"),
        data={
            "title": "Unsafe",
            "statement": r"\include{secrets}",
            "statement_format": "latex",
            "proposed_difficulty": "3",
        },
    )
    assert response.status_code == 302
    assert not ProblemSubmission.objects.filter(title="Unsafe").exists()
