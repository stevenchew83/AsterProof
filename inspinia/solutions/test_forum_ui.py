"""Exercise the forum through authenticated HTML forms and bounded reader pages."""

import re
from http import HTTPStatus

import pytest
from django.core.cache import cache
from django.urls import reverse

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions import forum
from inspinia.solutions.forum_models import SolutionComment
from inspinia.solutions.forum_models import SolutionForumReport
from inspinia.solutions.forum_models import SolutionHumanAssessment
from inspinia.solutions.forum_models import SolutionUpvote
from inspinia.solutions.models import ProblemSolution
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def writing():
    cache.clear()
    author, member = UserFactory(), UserFactory()
    trainer, admin = UserFactory(role="trainer"), UserFactory(role="admin")
    problem = ProblemSolveRecord.objects.create(contest="FORUM UI", year=2026, problem="P1", topic="ALG")
    solution = ProblemSolution.objects.create(problem=problem, author=author, status="published", title="Member proof")
    solution.blocks.create(position=1, body_source="A saved proof with $x^2$.")
    return {"solution": solution, "author": author, "member": member, "trainer": trainer, "admin": admin}


def url(writing, action=None):
    return reverse(
        "solutions:forum_action" if action else "solutions:solution_detail",
        args=[writing["solution"].pk, action] if action else [writing["solution"].pk],
    )


def hidden_fields(response):
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', response.content.decode()))


def test_complete_html_review_vote_and_verification_flow(client, writing):
    client.force_login(writing["author"])
    response = client.get(url(writing))
    fields = hidden_fields(response)
    assert "Share publicly" in response.content.decode()
    response = client.post(url(writing, "request_review"), {"target_key": fields["target_key"]})
    assert response.status_code == HTTPStatus.FOUND

    client.force_login(writing["member"])
    assert client.post(url(writing, "upvote"), {"active": "1"}).status_code == HTTPStatus.FOUND
    assert SolutionUpvote.objects.filter(solution=writing["solution"]).count() == 1
    response = client.post(url(writing, "comment"), {"body": "Why does **this** hold for $x=0$?"})
    assert response.status_code == HTTPStatus.FOUND
    response = client.get(url(writing))
    assert b"<strong>this</strong>" in response.content
    assert b"Upvoted" in response.content

    client.force_login(writing["trainer"])
    response = client.get(url(writing))
    fields = hidden_fields(response)
    response = client.post(url(writing, "assess"), {
        "target_key": fields["target_key"], "assessment_head": fields.get("assessment_head", ""),
        "verdict": "correct", "feedback": "Every step is justified.",
    })
    assert response.status_code == HTTPStatus.FOUND
    assert SolutionHumanAssessment.objects.count() == 1

    client.force_login(writing["admin"])
    response = client.get(url(writing))
    fields = hidden_fields(response)
    response = client.post(url(writing, "verify"), {
        "target_key": fields["target_key"], "decision_head": fields.get("decision_head", ""),
        "assessment_basis": fields.get("assessment_basis", ""), "reason": "I checked the proof and boundary cases.",
    })
    assert response.status_code == HTTPStatus.FOUND
    response = client.get(url(writing))
    assert b"forum-verified" in response.content
    assert b"Verified by" in response.content
    assert b"Every step is justified." in response.content
    assert len(re.findall(rb"<h1(?: |>)", response.content)) == 1


def test_stale_assessment_keeps_entered_feedback(client, writing):
    client.force_login(writing["trainer"])
    fields = hidden_fields(client.get(url(writing)))
    writing["solution"].title = "Changed title"
    writing["solution"].save()
    response = client.post(url(writing, "assess"), {
        "target_key": fields["target_key"], "assessment_head": "", "verdict": "partial",
        "feedback": "Keep this carefully entered feedback.", "gaps": "The equality case is missing.",
    })
    assert response.status_code == HTTPStatus.CONFLICT
    assert b"Keep this carefully entered feedback." in response.content
    assert b"The equality case is missing." in response.content
    assert not SolutionHumanAssessment.objects.exists()


def test_comments_and_replies_paginate_without_loading_other_threads(client, writing):
    solution = writing["solution"]
    roots = [SolutionComment.objects.create(
        solution=solution, author=writing["member"], body=f"Root comment {index:02d}",
    ) for index in range(21)]
    for index in range(21):
        SolutionComment.objects.create(
            solution=solution, author=writing["trainer"], parent=roots[0], body=f"Reply comment {index:02d}",
        )
    client.force_login(writing["member"])
    response = client.get(url(writing))
    assert b"Root comment 19" in response.content
    assert b"Root comment 20" not in response.content
    assert b"Reply comment 00" not in response.content
    response = client.get(url(writing), {"comments_page": 2})
    assert b"Root comment 20" in response.content
    thread_url = reverse("solutions:forum_comment_replies", args=[solution.pk, roots[0].pk])
    response = client.get(thread_url)
    assert b"Reply comment 19" in response.content
    assert b"Reply comment 20" not in response.content
    assert b"Root comment 01" not in response.content
    assert b"Reply comment 20" in client.get(thread_url, {"page": 2}).content


def test_hidden_comment_source_and_reports_are_not_rendered_for_members(client, writing):
    comment = SolutionComment.objects.create(
        solution=writing["solution"], author=writing["member"], body="Secret hidden comment content.", state="hidden",
    )
    SolutionForumReport.objects.create(comment=comment, reporter=writing["trainer"], reason="Private report evidence.")
    client.force_login(writing["member"])
    response = client.get(url(writing))
    assert b"Secret hidden comment content." not in response.content
    assert b"Private report evidence." not in response.content
    assert b"hidden by an admin" in response.content
    assert client.get(reverse("solutions:forum_admin_queue"), {"state": "reports"}).status_code == HTTPStatus.FORBIDDEN

    client.force_login(writing["admin"])
    response = client.get(reverse("solutions:forum_admin_queue"), {"state": "reports"})
    assert b"Private report evidence." in response.content
    assert b"Secret hidden comment content." in response.content


def test_member_feedback_uses_safe_markdown(client, writing):
    client.force_login(writing["member"])
    response = client.post(url(writing, "comment"), {"body": '<script>alert("x")</script> **Readable**'})
    assert response.status_code == HTTPStatus.FOUND
    response = client.get(url(writing))
    assert b'<script>alert("x")</script>' not in response.content
    assert b"<strong>Readable</strong>" in response.content


def test_admin_history_is_bounded_and_rejects_malformed_target(client, writing):
    client.force_login(writing["admin"])
    history_url = reverse("solutions:forum_history", args=[writing["solution"].pk])
    response = client.get(history_url)
    assert response.status_code == HTTPStatus.OK
    assert b"No assessed versions yet." in response.content
    assert client.get(history_url, {"target": "invalid"}).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("name", ["forum_review_queue", "forum_admin_queue"])
def test_queue_login_and_role_boundaries(client, writing, name):
    queue_url = reverse(f"solutions:{name}")
    assert client.get(queue_url).status_code == HTTPStatus.FOUND
    client.force_login(writing["member"])
    assert client.get(queue_url).status_code == HTTPStatus.FORBIDDEN
    client.force_login(writing["trainer"])
    expected = HTTPStatus.OK if name == "forum_review_queue" else HTTPStatus.FORBIDDEN
    assert client.get(queue_url).status_code == expected


def test_empty_admin_report_queue_uses_report_empty_state(client, writing):
    client.force_login(writing["admin"])
    response = client.get(reverse("solutions:forum_admin_queue"), {"state": "reports"})
    assert response.status_code == HTTPStatus.OK
    assert b"No open reports." in response.content


def test_admin_can_inspect_published_review_snapshot(client, writing):
    target_key = forum.current_target_data(writing["solution"])["key"]
    forum.write(writing["trainer"], writing["solution"].pk, "assess", {
        "target_key": target_key, "assessment_head": "", "verdict": "partial", "feedback": "One step remains.",
    })
    target = writing["solution"].forum_targets.get()
    client.force_login(writing["admin"])
    response = client.get(reverse("solutions:forum_history", args=[writing["solution"].pk]), {"target": target.pk})
    assert response.status_code == HTTPStatus.OK
    assert b"A saved proof with $x^2$." in response.content
    assert b"One step remains." in response.content


@pytest.mark.parametrize("permission", ["approval", "admin"])
def test_write_error_does_not_rerender_after_authority_is_revoked(client, writing, monkeypatch, permission):
    user = writing["admin"] if permission == "admin" else writing["member"]
    if permission == "admin":
        writing["solution"].status = "draft"
        writing["solution"].save()
    client.force_login(user)
    original_write = forum.write

    def revoked_write(actor, *args):
        if permission == "approval":
            actor.is_approved = False
        else:
            actor.role = "normal"
        actor.save()
        return original_write(actor, *args)

    monkeypatch.setattr(forum, "write", revoked_write)
    response = client.post(url(writing, "upvote"), {"active": "1"})
    assert response.status_code in {HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND}
    assert b"A saved proof with" not in response.content
    assert b"Member proof" not in response.content
    assert response.content == b""


def test_resolved_report_history_stays_available_only_to_admins(client, writing):
    comment = SolutionComment.objects.create(
        solution=writing["solution"], author=writing["member"], body="Reported comment.",
    )
    SolutionForumReport.objects.create(
        comment=comment, reporter=writing["trainer"], reason="Original report evidence.",
        status="resolved", resolved_by=writing["admin"], resolution="Checked and resolved.",
    )
    client.force_login(writing["admin"])
    response = client.get(reverse("solutions:forum_admin_queue"), {"state": "reports", "report_status": "resolved"})
    assert response.status_code == HTTPStatus.OK
    assert b"Original report evidence." in response.content
    assert b"Checked and resolved." in response.content
    assert b">Resolve report</button>" not in response.content


def test_failed_off_page_comment_edit_preserves_unsaved_body_and_version(client, writing):
    comments = [SolutionComment.objects.create(
        solution=writing["solution"], author=writing["member"], body=f"Comment {index}",
    ) for index in range(21)]
    last = comments[-1]
    last.version = 2
    last.save(update_fields=["version"])
    client.force_login(writing["member"])
    response = client.post(url(writing, "edit_comment"), {
        "comment_id": last.pk, "version": 1, "body": "My carefully edited off-page comment.",
    })
    assert response.status_code == HTTPStatus.CONFLICT
    assert b"My carefully edited off-page comment." in response.content
    assert b'name="version" value="1"' in response.content
    last.refresh_from_db()
    assert last.body == "Comment 20"


def test_admin_can_moderate_discussion_after_solution_is_unpublished(client, writing):
    SolutionComment.objects.create(solution=writing["solution"], author=writing["member"], body="Member comment.")
    writing["solution"].status = "draft"
    writing["solution"].save()
    client.force_login(writing["admin"])
    response = client.get(url(writing))
    assert response.status_code == HTTPStatus.OK
    assert url(writing, "hide_comment").encode() in response.content
    assert b">Post comment</button>" not in response.content


def test_inline_upvote_returns_current_count_and_next_action(client, writing):
    endpoint = url(writing, "upvote")
    client.force_login(writing["member"])
    for _ in range(2):
        response = client.post(endpoint, {"active": "1"}, HTTP_ACCEPT="application/json")
        assert response.status_code == HTTPStatus.OK
        assert 'aria-pressed="true"' in response.json()["html"]
        assert "<span>1</span>" in response.json()["html"]
    response = client.post(endpoint, {"active": "0"}, HTTP_ACCEPT="application/json")
    assert response.status_code == HTTPStatus.OK
    assert 'aria-pressed="false"' in response.json()["html"]
    assert "<span>0</span>" in response.json()["html"]

    client.force_login(writing["author"])
    assert client.post(endpoint, {"active": "1"}, HTTP_ACCEPT="application/json").status_code == HTTPStatus.FORBIDDEN
    assert not SolutionUpvote.objects.filter(solution=writing["solution"]).exists()
