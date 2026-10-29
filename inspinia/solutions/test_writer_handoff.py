"""Public writing survives authentication and is saved privately only on request."""

import time
from http import HTTPStatus

import pytest
from allauth.mfa.models import Authenticator
from django.core import mail
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.writer_drafts import WRITER_DRAFT_SESSION_KEY
from inspinia.solutions.writer_drafts import WRITER_DRAFT_TTL
from inspinia.solutions.writer_drafts import writer_handoff_url
from inspinia.users.models import User
from inspinia.users.models import UserAccessSettings
from inspinia.users.tests.factories import UserFactory
from inspinia.users.tests.test_login_codes import request_code

pytestmark = pytest.mark.django_db
TEST_CREDENTIAL = "SyntheticWriterOnly!984"


@pytest.fixture(autouse=True)
def isolate_auth_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def problem():
    row = ProblemSolveRecord.objects.create(contest="WRITER TEST", year=2026, problem="P1", topic="ALG", mohs=5)
    ContestProblemStatement.objects.create(
        linked_problem=row, contest_name=row.contest, contest_year=2026, problem_code="P1",
        problem_number=1, topic="ALG", statement_latex="An official statement.",
    )
    return row


def source_data():
    return {
        "action": "continue_workspace", "title": "A preserved proof", "author_name": "Guest author",
        "problem_statement": r"Prove $a^2+b^2\geq2ab$.", "pdf_options_present": "1", "pdf_show_date": "on",
        "blocks-TOTAL_FORMS": "2", "blocks-INITIAL_FORMS": "0", "blocks-MAX_NUM_FORMS": "32",
        "blocks-0-block_type": str(SolutionBlockType.objects.get(slug="idea").pk),
        "blocks-0-title": "Key step", "blocks-0-body_format": "plain_text",
        "blocks-0-body_source": "Literal <script> and $x$ stay text.", "blocks-0-ORDER": "2",
        "blocks-1-block_type": str(SolutionBlockType.objects.get(slug="proof").pk),
        "blocks-1-title": "Proof", "blocks-1-body_format": "latex",
        "blocks-1-body_source": r"Use $(a-b)^2\geq0$.", "blocks-1-ORDER": "1",
    }


def stage(client, **changes):
    response = client.post(reverse("website:solution_preview"), {**source_data(), **changes})
    assert response.status_code == HTTPStatus.FOUND
    assert not ProblemSolution.objects.exists()
    assert not UserProblemCompletion.objects.exists()
    return response


def editor_data(response):
    form, formset = response.context["form"], response.context["formset"]
    data = {"action": "save", "writer_draft_token": response.context["writer_import"]["token"]}
    for name in form.fields:
        value = form[name].value()
        if value is not None and value is not False:
            data[form.add_prefix(name)] = "on" if value is True else str(value)
    data.update({"blocks-TOTAL_FORMS": str(len(formset.forms)), "blocks-INITIAL_FORMS": "0"})
    for block in formset:
        for name in block.fields:
            value = block[name].value()
            if value is not None and value is not False:
                data[block.add_prefix(name)] = str(value)
    return data


def test_password_sign_in_preserves_writing_until_explicit_private_save(client, problem):
    user = UserFactory(password=TEST_CREDENTIAL)
    assert stage(client).url.startswith(reverse("account_login") + "?next=")
    original_session = client.session.session_key
    response = client.post(reverse("account_login"), {
        "login": user.email, "password": TEST_CREDENTIAL, "next": "https://evil.invalid/",
    })
    assert response.url == writer_handoff_url()
    assert client.session.session_key != original_session
    picker = client.get(response.url)
    assert client.session[WRITER_DRAFT_SESSION_KEY]["owner"] == str(user.pk)
    row = next(row for row in picker.context["statement_problem_rows"] if "from_writer=" in row["editor_url"])
    editor = client.get(row["editor_url"])
    form = editor.context["form"]
    assert form["title"].value() == "A preserved proof"
    assert form["pdf_show_author"].value() is False
    assert form["pdf_show_date"].value() is True
    assert form["pdf_show_footer"].value() is False
    assert "Publish solution" not in editor.content.decode()
    assert "&lt;script&gt;" in editor.content.decode()
    assert "no-store" in editor["Cache-Control"]
    assert not ProblemSolution.objects.exists()
    saved = client.post(row["editor_url"], editor_data(editor))
    assert saved.status_code == HTTPStatus.FOUND
    solution = ProblemSolution.objects.get(author=user, problem=problem)
    assert solution.status == ProblemSolution.Status.DRAFT
    assert solution.published_at is None
    assert solution.submitted_at is None
    assert [b.body_source for b in solution.blocks.all()] == [
        source_data()["problem_statement"],
        source_data()["blocks-1-body_source"], source_data()["blocks-0-body_source"],
    ]
    assert solution.blocks.last().body_format == "plain_text"
    assert solution.pdf_show_author is False
    assert solution.pdf_show_footer is False
    assert WRITER_DRAFT_SESSION_KEY not in client.session
    assert not UserProblemCompletion.objects.exists()


def test_pending_signup_keeps_draft_and_resumes_after_approval(client, settings):
    settings.ACCOUNT_EMAIL_VERIFICATION = "none"
    access = UserAccessSettings.get_solo()
    access.auto_approve_new_users = False
    access.save()
    assert stage(client, action="continue_signup").url.startswith(reverse("account_signup"))
    response = client.post(reverse("account_signup"), {
        "email": "writer-signup@example.test", "password1": TEST_CREDENTIAL, "password2": TEST_CREDENTIAL,
        "next": writer_handoff_url(),
    }, follow=True)
    assert response.request["PATH_INFO"] == reverse("users:approval_pending")
    assert "Your Solution Writer draft is kept" in response.content.decode()
    resumed = client.get(reverse("website:solution_preview") + "?resume=1")
    assert resumed.context["form"]["title"].value() == "A preserved proof"
    assert resumed.context["formset"].forms[0]["body_source"].value() == source_data()["blocks-1-body_source"]
    assert not ProblemSolution.objects.exists()
    user = User.objects.get(email="writer-signup@example.test")
    user.is_approved = True
    user.save(update_fields=["is_approved"])
    assert client.get(reverse("users:approval_pending")).url == writer_handoff_url()


def test_email_code_sign_in_keeps_handoff_without_sending_writing_in_email(client):
    stage(client)
    code = request_code(client, UserFactory())
    assert "A preserved proof" not in mail.outbox[-1].body
    response = client.post(reverse("account_confirm_login_code"), {"code": code})
    assert response.url == writer_handoff_url()
    assert WRITER_DRAFT_SESSION_KEY in client.session


def test_staged_draft_does_not_bypass_admin_mfa(client):
    stage(client)
    user = UserFactory(role=User.Role.ADMIN)
    Authenticator.objects.create(user=user, type=Authenticator.Type.TOTP, data={"secret": "TESTONLY"})
    code = request_code(client, user)
    response = client.post(reverse("account_confirm_login_code"), {"code": code})
    assert response.url == reverse("mfa_authenticate")
    assert "_auth_user_id" not in client.session
    assert WRITER_DRAFT_SESSION_KEY in client.session


def test_existing_solution_is_never_replaced_by_handoff(client, problem):
    user = UserFactory()
    client.force_login(user)
    stage(client)
    token = client.session[WRITER_DRAFT_SESSION_KEY]["token"]
    url = reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]) + "?from_writer=" + token
    editor = client.get(url)
    solution = ProblemSolution.objects.create(author=user, problem=problem, title="Existing", status="published")
    block = ProblemSolutionBlock.objects.create(solution=solution, position=1, body_source="Existing proof")
    assert client.get(url).url == writer_handoff_url()
    response = client.post(url, editor_data(editor))
    assert response.context["form"].errors
    solution.refresh_from_db()
    block.refresh_from_db()
    assert solution.title == "Existing"
    assert solution.status == "published"
    assert block.body_source == "Existing proof"
    assert solution.blocks.count() == 1
    assert WRITER_DRAFT_SESSION_KEY in client.session


@pytest.mark.parametrize("failure", ["expired", "different_owner", "stale_token", "publish"])
def test_invalid_handoff_cannot_create_or_publish_a_solution(client, problem, failure):
    client.force_login(UserFactory())
    stage(client)
    token = client.session[WRITER_DRAFT_SESSION_KEY]["token"]
    url = reverse("solutions:problem_solution_edit", args=[problem.problem_uuid]) + "?from_writer=" + token
    data = editor_data(client.get(url))
    session = client.session
    if failure == "expired":
        session[WRITER_DRAFT_SESSION_KEY]["stored_at"] = time.time() - WRITER_DRAFT_TTL - 1
    elif failure == "different_owner":
        session[WRITER_DRAFT_SESSION_KEY]["owner"] = str(UserFactory().pk)
    elif failure == "stale_token":
        data["writer_draft_token"] = "0" * 32
    else:
        data["action"] = "publish"
    session.save()
    response = client.post(url, data)
    assert response.context["form"].errors
    assert not ProblemSolution.objects.exists()
    assert not UserProblemCompletion.objects.exists()


def test_handoff_requires_csrf():
    client = Client(enforce_csrf_checks=True)
    assert client.post(reverse("website:solution_preview"), source_data()).status_code == HTTPStatus.FORBIDDEN
    assert WRITER_DRAFT_SESSION_KEY not in client.session


def test_invalid_document_keeps_input_without_staging(client):
    response = client.post(reverse("website:solution_preview"), {**source_data(), "blocks-0-body_source": "x" * 12001})
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "A preserved proof" in response.content.decode()
    assert WRITER_DRAFT_SESSION_KEY not in client.session


def test_unfinished_blocks_can_cross_sign_in_without_becoming_saved_solutions(client):
    stage(client, **{"blocks-0-body_source": "", "blocks-1-body_source": ""})
    blocks = client.session[WRITER_DRAFT_SESSION_KEY]["document"]["blocks"]
    assert [block["title"] for block in blocks] == ["Proof", "Key step"]
    assert all(block["body_source"] == "" for block in blocks)


def test_homepage_does_not_render_session_draft_and_logout_clears_handoff(client):
    client.force_login(UserFactory())
    stage(client)
    assert "A preserved proof" not in client.get(reverse("pages:home") + "?resume=1").content.decode()
    response = client.get(reverse("solutions:my_solution_list"))
    assert "Your Solution Writer draft is waiting" in response.content.decode()
    client.post(reverse("account_logout"))
    assert WRITER_DRAFT_SESSION_KEY not in client.session
