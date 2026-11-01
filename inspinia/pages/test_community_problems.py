"""Community publication, review permissions, and mandatory similarity preflight."""
# ruff: noqa: PLR2004

import pytest
from django.urls import reverse

from inspinia.pages.community_forms import CommunityProblemForm
from inspinia.pages.community_models import CommunityProblem
from inspinia.pages.community_models import CommunityProblemReview
from inspinia.pages.community_models import StatementAIReview
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.statement_similarity import rebuild_similarity_index
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def payload(**updates):
    data = {
        "title": "A square inequality",
        "statement_latex": r"For $a,b>0$, prove $a^2+b^2\geq 2ab$.",
        "topic": "ALG",
        "mohs": 5,
        "topic_tags": "squares, inequality",
        "core_ideas": "Expand a square.",
        "rationale": "One direct observation.",
        "pitfalls": "",
        "source_kind": "original",
        "source_details": "An original practice example by the submitter.",
        "source_url": "",
        "contest_name": "",
        "contest_year": "",
        "problem_code": "",
        "solution_outline": "PRIVATE-OUTLINE: expand the difference.",
        "sharing_confirmed": "on",
        "version": 1,
    }
    return {**data, **updates}


def post(author, **updates):
    fields = {key: value for key, value in payload(**updates).items() if key not in {"sharing_confirmed", "version"}}
    fields["contest_year"] = fields["contest_year"] or None
    return CommunityProblem.objects.create(author=author, **fields)


@pytest.fixture
def learner(client):
    user = UserFactory()
    client.force_login(user)
    return user


def test_login_and_pending_account_boundaries(client):
    url = reverse("pages:community_problem_list")
    assert client.get(url).status_code == 302
    client.force_login(UserFactory(is_approved=False))
    assert client.get(url).url == reverse("users:approval_pending")


def test_default_approved_and_all_tab_includes_every_status_and_paginates(client, learner):
    for status in CommunityProblem.Status.values:
        post(learner, status=status, title=status)
    default = client.get(reverse("pages:community_problem_list"))
    assert [row.status for row in default.context["problems"]] == ["approved"]
    assert default.context["reviewed_count"] == 1
    all_posts = client.get(reverse("pages:community_problem_list"), {"tab": "all"})
    assert all_posts.context["problems"].paginator.count == 4
    assert {row.status for row in all_posts.context["problems"]} == set(CommunityProblem.Status.values)
    assert "PRIVATE-OUTLINE" not in all_posts.content.decode()
    for number in range(22):
        post(learner, title=f"Problem {number}")
    first = client.get(reverse("pages:community_problem_list"), {"tab": "all"}).context["problems"]
    second = client.get(reverse("pages:community_problem_list"), {"tab": "all", "page": 2}).context["problems"]
    assert len(first) == 20
    assert len(second) == 6
    assert not {row.pk for row in first} & {row.pk for row in second}


def test_submission_requires_current_check_and_does_not_change_library(client, learner):
    rebuild_similarity_index()
    url = reverse("pages:community_problem_create")
    bypass = client.post(url, {**payload(), "action": "submit"})
    assert "Check for similar problems again" in bypass.content.decode()
    assert not CommunityProblem.objects.exists()
    checked = client.post(url, {**payload(), "action": "check"})
    assert checked.context["similarity"]["available"]
    token = checked.context["similarity_token"]
    changed = client.post(url, {**payload(title="Changed title"), "action": "submit", "similarity_token": token})
    assert not CommunityProblem.objects.exists()
    assert changed.status_code == 200
    saved = client.post(
        url,
        {**payload(), "action": "submit", "similarity_token": token, "status": "approved", "author": UserFactory().pk},
    )
    assert saved.status_code == 302
    problem = CommunityProblem.objects.get()
    assert problem.status == CommunityProblem.Status.PENDING
    assert problem.author_id == learner.pk
    assert problem.topic_tags == "SQUARES, INEQUALITY"
    assert not ContestProblemStatement.objects.exists()
    assert not ProblemSolveRecord.objects.exists()
    client.post(url, {**payload(), "action": "submit", "similarity_token": token})
    assert CommunityProblem.objects.count() == 1


def test_check_token_bound_to_user_and_library(client, learner):
    rebuild_similarity_index()
    url = reverse("pages:community_problem_create")
    checked = client.post(url, {**payload(), "action": "check"})
    token = checked.context["similarity_token"]
    client.force_login(UserFactory())
    client.post(url, {**payload(), "action": "submit", "similarity_token": token})
    assert not CommunityProblem.objects.exists()
    client.force_login(learner)
    ContestProblemStatement.objects.create(
        contest_name="CHECK",
        contest_year=2026,
        problem_number=1,
        problem_code="P1",
        statement_latex="New statement.",
    )
    rebuild_similarity_index()
    client.post(url, {**payload(), "action": "submit", "similarity_token": token})
    assert not CommunityProblem.objects.exists()


def test_matches_need_acknowledgement_and_missing_index_cannot_pass(client, learner):
    url = reverse("pages:community_problem_create")
    missing = client.post(url, {**payload(), "action": "check"})
    assert not missing.context["similarity"]["available"]
    assert not missing.context["similarity_token"]
    ContestProblemStatement.objects.create(
        contest_name="MATCH",
        contest_year=2026,
        problem_number=1,
        problem_code="P1",
        statement_latex=payload()["statement_latex"],
    )
    rebuild_similarity_index()
    checked = client.post(url, {**payload(), "action": "check"})
    assert checked.context["similarity"]["matches"]
    data = {**payload(), "action": "submit", "similarity_token": checked.context["similarity_token"]}
    client.post(url, data)
    assert not CommunityProblem.objects.exists()
    assert client.post(url, {**data, "matches_acknowledged": "1"}).status_code == 302


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mohs", -1),
        ("mohs", 61),
        ("topic", "invalid"),
        ("core_ideas", " "),
        ("topic_tags", ", ,"),
        ("source_details", ""),
        ("statement_latex", "x" * 12001),
        ("solution_outline", "x" * 6001),
        ("source_url", "javascript:alert(1)"),
        ("contest_name", "Incomplete contest"),
    ],
)
def test_required_details_and_bounds(field, value):
    assert not CommunityProblemForm(payload(**{field: value})).is_valid()


def test_detail_private_outline_escaping_and_owner_edit_gate(client, learner):
    problem = post(learner, statement_latex='<script>alert("x")</script>')
    url = reverse("pages:community_problem_detail", args=[problem.pk])
    assert "PRIVATE-OUTLINE" in client.get(url).content.decode()
    client.force_login(UserFactory())
    html = client.get(url).content.decode()
    assert "PRIVATE-OUTLINE" not in html
    assert '<script>alert("x")</script>' not in html
    assert "&lt;script&gt;" in html
    assert client.get(reverse("pages:community_problem_edit", args=[problem.pk])).status_code == 404
    assert client.post(url, {"version": 1, "decision": "approved"}).status_code == 403


def test_admin_decision_and_author_resubmission_preserve_review_evidence(client, learner):
    problem = post(learner)
    url = reverse("pages:community_problem_detail", args=[problem.pk])
    admin = UserFactory(role=User.Role.ADMIN)
    client.force_login(admin)
    assert (
        client.post(url, {"version": 1, "decision": "changes_requested", "notes": "Clarify the domain."}).status_code
        == 302
    )
    assert CommunityProblemReview.objects.get().content_snapshot["title"] == problem.title
    client.force_login(learner)
    rebuild_similarity_index()
    edit = reverse("pages:community_problem_edit", args=[problem.pk])
    checked = client.post(edit, {**payload(title="Revised statement"), "action": "check"})
    saved = client.post(
        edit,
        {
            **payload(title="Revised statement"),
            "action": "submit",
            "similarity_token": checked.context["similarity_token"],
        },
    )
    assert saved.status_code == 302
    problem.refresh_from_db()
    assert problem.version == 2
    assert problem.status == "pending"
    assert problem.reviewed_by is None
    client.force_login(admin)
    stale = client.post(url, {"version": 1, "decision": "approved"})
    assert "already reviewed" in stale.content.decode()
    assert client.post(url, {"version": 2, "decision": "approved"}).status_code == 302
    assert not ContestProblemStatement.objects.exists()
    assert not ProblemSolveRecord.objects.exists()
    client.force_login(learner)
    assert client.get(edit).status_code == 403


def test_non_admin_cannot_request_ai_even_in_debug_mode(client, learner, settings):
    settings.DEBUG = True
    problem = post(learner)
    url = reverse("pages:community_problem_ai_review", args=[problem.pk])
    assert client.post(url, {"version": 1, "acknowledged": "1"}).status_code == 403
    assert not StatementAIReview.objects.exists()
