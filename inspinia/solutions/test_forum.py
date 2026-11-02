"""Forum decisions bind real saved versions without changing progress or public copies."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http import HTTPStatus
from threading import Event
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection
from django.db import connections
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions import forum
from inspinia.solutions.forum_access import visible_solutions
from inspinia.solutions.forum_models import SolutionComment
from inspinia.solutions.forum_models import SolutionForumReport
from inspinia.solutions.forum_models import SolutionForumTarget
from inspinia.solutions.forum_models import SolutionHumanAssessment
from inspinia.solutions.forum_models import SolutionUpvote
from inspinia.solutions.forum_models import SolutionVerificationDecision
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.revisions import editor_context
from inspinia.solutions.revisions import save_document
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def proof():
    cache.clear()
    author, member = UserFactory(), UserFactory()
    trainer = UserFactory(role="trainer")
    second = UserFactory(role="trainer")
    admin = UserFactory(role="admin")
    problem = ProblemSolveRecord.objects.create(contest="FORUM", year=2026, problem="P1", topic="ALG")
    statement = ContestProblemStatement.objects.create(
        linked_problem=problem,
        contest_name="FORUM",
        contest_year=2026,
        problem_code="P1",
        problem_number=1,
        topic="ALG",
        statement_latex=r"Prove $x^2\geq 0$.",
    )
    solution = ProblemSolution.objects.create(problem=problem, author=author, status="published", title="A proof")
    solution.blocks.create(position=1, body_source="A square is nonnegative.")
    return {
        "author": author,
        "member": member,
        "trainer": trainer,
        "second": second,
        "admin": admin,
        "solution": solution,
        "statement": statement,
        "problem": problem,
    }


def submit(state, who, action, **data):
    solution = state["solution"]
    solution.refresh_from_db()
    target = forum.current_target_data(solution)
    state_summary = forum.summary(solution)
    own = next((row for row in state_summary["assessments"] if row.reviewer_id == state[who].pk), None)
    return forum.write(
        state[who],
        solution.pk,
        action,
        {
            "target_key": target["key"],
            "assessment_head": str(own.pk) if own else "",
            "decision_head": str(state_summary["decision"].pk) if state_summary["decision"] else "",
            "assessment_basis": ",".join(
                str(row.pk) for row in sorted(state_summary["assessments"], key=lambda row: row.pk)
            ),
            **data,
        },
    )


def test_reader_does_not_create_review_snapshots_and_legacy_links_redirect(client, proof):
    solution = proof["solution"]
    client.force_login(proof["member"])
    detail = reverse("solutions:solution_detail", args=[solution.pk])
    response = client.get(detail)
    assert response.status_code == HTTPStatus.OK
    assert b"A square is nonnegative" in response.content
    assert "no-store" in response["Cache-Control"]
    assert not SolutionForumTarget.objects.exists()
    old = reverse("solutions:problem_solution_list", args=[solution.problem.problem_uuid])
    assert client.get(f"{old}?solution={solution.pk}")["Location"] == detail
    assert client.get(f"{old}?solution=invalid").status_code == HTTPStatus.NOT_FOUND
    for invalid in ["²", "9" * 5000, "9999999999999999999"]:
        assert client.get(old, {"solution": invalid}).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("role", ["normal", "trainer", "moderator"])
def test_drafts_and_histories_remain_private_to_author_and_admin(client, proof, role):
    submit(proof, "trainer", "assess", verdict="correct", feedback="Complete proof.")
    solution = proof["solution"]
    solution.status = "draft"
    solution.save()
    member = UserFactory(role=role)
    client.force_login(member)
    url = reverse("solutions:solution_detail", args=[solution.pk])
    assert client.get(url).status_code == HTTPStatus.NOT_FOUND
    assert not visible_solutions(member).filter(pk=solution.pk).exists()
    assert client.get(reverse("solutions:forum_history", args=[solution.pk])).status_code == HTTPStatus.NOT_FOUND
    for who in ["author", "admin"]:
        client.force_login(proof[who])
        assert client.get(url).status_code == HTTPStatus.OK


def test_votes_are_idempotent_private_counts_without_self_votes(proof):
    submit(proof, "member", "upvote", active="1")
    submit(proof, "member", "upvote", active="1")
    assert SolutionUpvote.objects.count() == 1
    with pytest.raises(forum.ForumError, match="own"):
        submit(proof, "author", "upvote", active="1")
    submit(proof, "member", "upvote", active="0")
    submit(proof, "member", "upvote", active="0")
    assert SolutionUpvote.objects.count() == 0


def test_member_ranking_and_pagination_are_independent_of_verification(client, proof):
    solution = proof["solution"]
    solution.published_at = timezone.now() - timedelta(days=2)
    solution.save()
    newest = ProblemSolution.objects.create(
        problem=proof["problem"], author=proof["trainer"], title="Newest solution", status="published",
        published_at=timezone.now(),
    )
    for index in range(20):
        ProblemSolution.objects.create(
            problem=proof["problem"], author=UserFactory(), title=f"Other solution {index}", status="published",
        )
    SolutionUpvote.objects.create(solution=solution, user=proof["member"])
    SolutionUpvote.objects.create(solution=solution, user=proof["trainer"])
    SolutionUpvote.objects.create(solution=newest, user=proof["member"])
    submit(proof, "admin", "verify", reason="A verified proof is still ranked by actual votes.")
    client.force_login(proof["member"])
    url = reverse("solutions:problem_solution_list", args=[proof["problem"].problem_uuid])
    response = client.get(url)
    assert response.context["visible_solution_rows"][0]["id"] == solution.pk
    assert len(response.context["visible_solution_rows"]) == 20  # noqa: PLR2004 - Fixed server page size.
    assert response.context["solution_page"].has_next()
    assert client.get(url, {"sort": "newest"}).context["visible_solution_rows"][0]["id"] == newest.pk


def test_unknown_actions_do_not_allocate_attacker_controlled_cache_keys(proof):
    with (
        patch.object(cache, "add", wraps=cache.add) as allocate,
        pytest.raises(forum.ForumError) as rejected,
    ):
        forum.write(proof["member"], proof["solution"].pk, "attacker-chosen-action", {})
    assert rejected.value.status == HTTPStatus.NOT_FOUND
    allocate.assert_not_called()


def test_independent_disagreement_admin_adjudication_and_new_conflict(proof):
    submit(proof, "author", "request_review")
    submit(proof, "author", "request_review")
    assert proof["solution"].forum_targets.count() == 1
    one = submit(proof, "trainer", "assess", verdict="correct", feedback="Complete proof.")
    assert not forum.summary(proof["solution"])["verified"]
    submit(proof, "second", "assess", verdict="partial", feedback="Missing a case.")
    state = forum.summary(proof["solution"])
    assert state["disputed"]
    assert state["request"].status == "answered"
    assert proof["solution"].pk in forum.queue_solutions("disputed").values_list("pk", flat=True)
    decision = submit(proof, "admin", "verify", reason="The allegedly missing case is covered by the first sentence.")
    state = forum.summary(proof["solution"])
    assert state["verified"]
    assert state["disagreement_resolved"]
    assert set(decision.assessment_basis) == {row.pk for row in state["assessments"]}
    submit(proof, "trainer", "assess", verdict="incorrect", feedback="I found a counterexample.")
    state = forum.summary(proof["solution"])
    assert not state["verified"]
    assert state["verification_label"] == "Verification needs review"
    assert SolutionHumanAssessment.objects.filter(reviewer=proof["trainer"]).count() == 2  # noqa: PLR2004 - Two immutable assessment revisions.
    one.feedback = "Rewrite history"
    with pytest.raises(ValidationError):
        one.save()


def test_abstention_does_not_create_disagreement_and_admin_can_verify_directly(proof):
    submit(proof, "admin", "verify", reason="Checked the argument directly.")
    submit(proof, "trainer", "assess", verdict="undetermined", feedback="I cannot assess this method.")
    state = forum.summary(proof["solution"])
    assert state["verified"]
    assert not state["disputed"]
    submit(proof, "admin", "revoke", reason="Rechecking the statement assumptions.")
    assert not forum.summary(proof["solution"])["verified"]


def test_admin_cannot_verify_a_selected_noncorrect_verdict(proof):
    with pytest.raises(forum.ForumError, match="Choose Correct"):
        submit(proof, "admin", "verify", verdict="partial", reason="Incomplete argument.")
    assert not SolutionVerificationDecision.objects.exists()


@pytest.mark.parametrize(
    ("action", "who"),
    [("assess", "member"), ("assess", "author"), ("verify", "trainer"), ("request_review", "member")],
)
def test_unauthorized_decisions_leave_no_target_or_record(proof, action, who):
    with pytest.raises(forum.ForumError):
        submit(proof, who, action, verdict="correct", feedback="A claim.", reason="A claim.")
    assert not SolutionForumTarget.objects.exists()


def test_saved_revisions_and_statement_changes_invalidate_verification(proof, settings):
    submit(proof, "admin", "verify", reason="Checked legacy proof.")
    solution = proof["solution"]
    settings.SOLUTION_DOCUMENT_WRITES_ENABLED = True
    result = save_document(
        solution=solution,
        user=proof["author"],
        source="A changed proof.",
        title="A proof",
        summary="",
        pdf_options={"pdf_show_author": True, "pdf_show_date": True, "pdf_show_footer": True},
        base_version=solution.edit_version,
        context=editor_context(proof["author"], solution.problem.problem_uuid),
    )
    proof["solution"] = result.solution
    assert forum.summary(result.solution)["verification_label"] == "Updated since verification"
    submit(proof, "admin", "verify", reason="Checked changed proof.")
    statement = proof["statement"]
    statement.statement_latex = "Prove a different claim."
    statement.save()
    assert not forum.summary(result.solution)["verified"]
    assert not SolutionPublicShare.objects.exists()
    assert not result.solution.problem.user_completions.exists()


def test_stale_target_and_assessment_basis_rejected(proof):
    key = forum.current_target_data(proof["solution"])["key"]
    submit(proof, "trainer", "assess", verdict="partial", feedback="A gap.")
    with pytest.raises(forum.ForumError, match="Trainer assessments changed"):
        forum.write(
            proof["admin"],
            proof["solution"].pk,
            "verify",
            {
                "target_key": key,
                "decision_head": "",
                "assessment_basis": "",
                "reason": "Old form.",
            },
        )
    proof["statement"].statement_latex = "New claim."
    proof["statement"].save()
    with pytest.raises(forum.ForumError, match="statement changed"):
        forum.write(proof["trainer"], proof["solution"].pk, "assess", {"target_key": key})
    assert not SolutionVerificationDecision.objects.exists()


def test_comments_reply_scope_edit_history_moderation_and_reports(proof):
    comment = submit(proof, "member", "comment", body="Why is $x=0$ allowed?")
    reply = submit(proof, "author", "comment", body="The inequality is non-strict.", parent_id=comment.pk)
    with pytest.raises(forum.ForumError):
        submit(proof, "trainer", "comment", body="Too deep.", parent_id=reply.pk)
    submit(proof, "member", "edit_comment", comment_id=comment.pk, version=1, body="Why is equality allowed?")
    assert list(comment.events.values_list("body", flat=True)) == ["Why is $x=0$ allowed?", "Why is equality allowed?"]
    with pytest.raises(forum.ForumError, match="changed"):
        submit(proof, "member", "remove_comment", comment_id=comment.pk, version=1)
    report = submit(proof, "trainer", "report", comment_id=comment.pk, reason="Please inspect.")
    submit(proof, "trainer", "report", comment_id=comment.pk, reason="Repeated report.")
    assert SolutionForumReport.objects.count() == 1
    submit(proof, "admin", "hide_comment", comment_id=comment.pk, version=2, reason="Pending moderation.")
    comment.refresh_from_db()
    assert comment.state == "hidden"
    assert comment.replies.count() == 1
    submit(proof, "admin", "restore_comment", comment_id=comment.pk, version=3, reason="Safe question.")
    submit(proof, "admin", "resolve_report", report_id=report.pk, resolution="No issue found.")
    report.refresh_from_db()
    assert report.status == "resolved"
    submit(proof, "member", "remove_comment", comment_id=comment.pk, version=4)
    assert SolutionComment.objects.filter(parent=comment).exists()


def test_access_revoked_and_unpublished_mutations_are_rejected(proof):
    proof["trainer"].is_approved = False
    proof["trainer"].save()
    with pytest.raises(forum.ForumError, match="approval"):
        submit(proof, "trainer", "comment", body="Not allowed.")
    proof["solution"].status = "draft"
    proof["solution"].save()
    with pytest.raises(forum.ForumError):
        submit(proof, "member", "upvote", active="1")
    assert not SolutionUpvote.objects.exists()


def test_admin_can_resolve_reports_after_author_unpublishes(proof):
    comment = submit(proof, "member", "comment", body="Inspect this comment.")
    report = submit(proof, "trainer", "report", comment_id=comment.pk, reason="Please moderate.")
    proof["solution"].status = "draft"
    proof["solution"].save()
    submit(proof, "admin", "hide_comment", comment_id=comment.pk, version=1, reason="Moderation continues privately.")
    submit(proof, "admin", "resolve_report", report_id=report.pk, resolution="Resolved after withdrawal.")
    report.refresh_from_db()
    assert report.status == "resolved"


def test_queue_filters_current_version_before_pagination(proof):
    solution = proof["solution"]
    submit(proof, "author", "request_review")
    assert list(forum.queue_solutions("requested")) == [solution]
    submit(proof, "trainer", "assess", verdict="correct", feedback="Complete.")
    assert not forum.queue_solutions("requested").exists()
    assert list(forum.queue_solutions("assessed")) == [solution]
    solution.edit_version += 1
    solution.save()
    assert not forum.queue_solutions("assessed").exists()
    assert list(forum.queue_solutions("unassessed")) == [solution]


def test_new_empty_statement_does_not_match_a_missing_statement_review(proof):
    proof["statement"].delete()
    submit(proof, "author", "request_review")
    ContestProblemStatement.objects.create(
        linked_problem=proof["problem"], contest_name="FORUM", contest_year=2026,
        problem_code="P1", problem_number=1, topic="ALG", statement_latex="",
    )
    assert not forum.queue_solutions("requested").exists()


def test_deleted_reviewer_does_not_resurrect_superseded_assessments(proof):
    submit(proof, "trainer", "assess", verdict="incorrect", feedback="Initially thought this failed.")
    submit(proof, "trainer", "assess", verdict="correct", feedback="The boundary case is covered.")
    submit(proof, "admin", "verify", reason="Checked the corrected assessment.")
    proof["trainer"].delete()
    state = forum.summary(proof["solution"])
    assert state["verified"]
    assert not state["disputed"]
    assert len(state["assessments"]) == 1
    assert not forum.queue_solutions("disputed").exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires real PostgreSQL row locks")
@pytest.mark.parametrize("operation", ["verify", "upvote"])
def test_author_edit_or_unpublish_wins_against_waiting_forum_write(proof, operation, settings):
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    attempted = Event()
    key = forum.current_target_data(proof["solution"])["key"]
    actor = proof["admin"] if operation == "verify" else proof["member"]

    def observe(execute, sql, params, many, context):
        if "FOR UPDATE" in sql and '"pages_problemsolverecord"' in sql:
            attempted.set()
        return execute(sql, params, many, context)

    def waiting_write():
        try:
            with connections["default"].execute_wrapper(observe):
                forum.write(actor, proof["solution"].pk, operation, {
                    "target_key": key, "decision_head": "", "assessment_basis": "",
                    "reason": "Checked the version shown.", "active": "1",
                })
        except forum.ForumError as error:
            return error.status
        else:
            return "saved"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            ProblemSolveRecord.objects.select_for_update().get(pk=proof["problem"].pk)
            future = pool.submit(waiting_write)
            assert attempted.wait(5), "Forum action never reached the shared source lock"
            if operation == "verify":
                settings.SOLUTION_DOCUMENT_WRITES_ENABLED = True
                solution = proof["solution"]
                save_document(
                    solution=solution, user=proof["author"], source="A later version.", title="New proof", summary="",
                    pdf_options={"pdf_show_author": True, "pdf_show_date": True, "pdf_show_footer": True},
                    base_version=solution.edit_version,
                    context=editor_context(proof["author"], solution.problem.problem_uuid),
                )
            else:
                proof["solution"].status = "draft"
                proof["solution"].save()
        expected = HTTPStatus.CONFLICT if operation == "verify" else HTTPStatus.NOT_FOUND
        assert future.result(timeout=10) == expected
    assert not SolutionVerificationDecision.objects.exists()
    assert not SolutionUpvote.objects.exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires real PostgreSQL row locks")
def test_concurrent_votes_are_unique_and_review_edit_head_is_checked(proof):
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    assert connection.settings_dict["HOST"] in {"127.0.0.1", "localhost"} or connection.settings_dict[
        "HOST"
    ].startswith(("/tmp/", "/private/tmp/"))  # noqa: S108 - Disposable local PostgreSQL socket.

    def vote(_index):
        try:
            forum.write(proof["member"], proof["solution"].pk, "upvote", {"active": "1"})
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(vote, range(2)))
    assert SolutionUpvote.objects.count() == 1
    key = forum.current_target_data(proof["solution"])["key"]

    def assess(_index):
        try:
            forum.write(
                proof["trainer"],
                proof["solution"].pk,
                "assess",
                {
                    "target_key": key,
                    "assessment_head": "",
                    "verdict": "correct",
                    "feedback": "Complete.",
                },
            )
        except forum.ForumError as error:
            return error.status
        else:
            return "saved"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(assess, range(2)))
    assert sorted(map(str, results)) == ["409", "saved"]
    assert SolutionHumanAssessment.objects.count() == 1
