"""Integration and privacy boundaries for Community Proof Library Phase 1."""
# ruff: noqa: PLR2004

import base64
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.html import Element
from django.test.html import parse_html
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from inspinia.pages.community_models import CommunityProblem
from inspinia.pages.community_models import StatementAIReview
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.proof_models import CommunityAttempt
from inspinia.pages.proof_models import CommunityContentReport
from inspinia.pages.proof_models import CommunityProblemRevision
from inspinia.pages.proof_models import CommunitySolution
from inspinia.pages.proof_models import CommunitySolutionAsset
from inspinia.pages.proof_models import ModerationEvent
from inspinia.pages.proof_models import ProblemPublication
from inspinia.pages.statement_similarity import rebuild_similarity_index
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
PRIVATE_OUTLINE = "PRIVATE-OUTLINE-NEVER-PUBLISH"
PRIVATE_IDEA = "PRIVATE-IDEA-NEVER-PUBLISH"
PRIVATE_NOTES = "PRIVATE-REVIEW-NOTES-NEVER-PUBLISH"
PROOF_BODY = r"\begin{proof}Since $(a-b)^2\geq0$, the claim follows.\end{proof}"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC",
)


@pytest.fixture(autouse=True)
def isolated_library(settings):
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "proof-library-tests"},
    }
    cache.clear()
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = False
    settings.SOLUTION_AI_REVIEW_ENABLED = False
    rebuild_similarity_index()


@pytest.fixture
def owner():
    return UserFactory(name="Problem contributor")


@pytest.fixture
def reviewer():
    return UserFactory(role=User.Role.ADMIN, name="Publication reviewer")


def _url(name, *args):
    return reverse("pages:" + name, args=args)


def _hidden(response):
    assert response.status_code == 200
    return {
        field.html_name: field.value() if field.value() is not None else ""
        for field in response.context["form"] if field.is_hidden
    }


def _submit_problem(client, author, **updates):
    client.force_login(author)
    data = {
        "title": "A square inequality",
        "statement_latex": r"For $a,b>0$, prove $a^2+b^2\geq2ab$.",
        "topic": "ALG", "mohs": "", "topic_tags": "", "core_ideas": "", "rationale": "", "pitfalls": "",
        "source_kind": "original", "source_details": "An original practice example by the contributor.",
        "source_url": "", "contest_name": "", "contest_year": "", "problem_code": "",
        "solution_outline": PRIVATE_OUTLINE, "public_hint": "", "embargo_until": "",
        "sharing_confirmed": "on", "version": 1, **updates,
    }
    url = _url("community_problem_create")
    checked = client.post(url, {**data, "action": "check"})
    assert checked.context["similarity_token"], checked.context["form"].errors
    response = client.post(url, {
        **data, "action": "submit", "similarity_token": checked.context["similarity_token"],
        "matches_acknowledged": "1",
    })
    assert response.status_code == 302, response.content.decode()
    return CommunityProblem.objects.get(author=author, title=data["title"])


def _review(client, reviewer, problem, *, solution=None, **updates):
    client.force_login(reviewer)
    url = _url("proof_solution_moderation", solution.pk) if solution else _url("proof_moderation", problem.pk)
    return client.post(url, {
        **_hidden(client.get(url)), "action": "review", "decision": "approved", "notes": PRIVATE_NOTES,
        "check_content": "on", "check_rights": "on", "check_embargo": "on", **updates,
    })


def _share(client, author, problem, visibility="unlisted"):
    client.force_login(author)
    url = _url("proof_sharing", problem.pk)
    data = {
        **_hidden(client.get(url)), "visibility": visibility, "public_credit": "Problem contributor", "consent": "on",
    }
    preview = client.post(url, {**data, "action": "preview"})
    assert preview.status_code == 200
    assert preview.context["review_token"], preview.context["form"].errors
    response = client.post(url, {
        **data, **_hidden(preview), "action": "publish", "review_token": preview.context["review_token"],
    })
    assert response.status_code == 302, response.content.decode()
    publication = ProblemPublication.objects.get(problem=problem)
    assert publication.visibility == visibility
    return publication


def _published_problem(client, owner, reviewer, visibility="unlisted", **updates):
    problem = _submit_problem(client, owner, **updates)
    reviewed = _review(client, reviewer, problem)
    assert reviewed.status_code == 302, reviewed.content.decode()
    return problem, _share(client, owner, problem, visibility)


def _save_attempt(client, solver, publication, body=PROOF_BODY):
    client.force_login(solver)
    url = _url("proof_attempt", publication.token)
    before = CommunityAttempt.objects.count()
    opened = client.get(url)
    assert CommunityAttempt.objects.count() == before
    response = client.post(url, {
        **_hidden(opened), "title": "A direct proof", "body_source": body, "action": "save",
    })
    assert response.status_code == 302, response.content.decode()
    return CommunityAttempt.objects.get(owner=solver, problem=publication.problem)


def _submit_proof(client, solver, attempt, **updates):
    client.force_login(solver)
    url = _url("proof_solution_publish", attempt.pk)
    data = {
        **_hidden(client.get(url)), "title": "A direct proof", "summary": "A nonnegative square.",
        "public_credit": "Solution contributor", "consent": "on", **updates,
    }
    preview = client.post(url, {**data, "action": "preview"})
    assert preview.status_code == 200
    assert preview.context["review_token"], preview.context["form"].errors
    response = client.post(url, {
        **data, **_hidden(preview), "action": "submit", "review_token": preview.context["review_token"],
    })
    assert response.status_code == 302, response.content.decode()
    return CommunitySolution.objects.get(author=solver, problem=attempt.problem)


def _public_url(publication):
    return _url("proof_public_problem", publication.token)


def _nodes(element):
    yield element
    for child in element.children:
        if isinstance(child, Element):
            yield from _nodes(child)


def test_unknown_solution_submission_is_private_without_archive_or_ai_side_effects(client, owner):
    problem = _submit_problem(client, owner)
    assert problem.mohs is None
    assert problem.core_ideas == problem.rationale == problem.topic_tags == ""
    assert problem.solution_known is False
    assert problem.legacy_member_visible is False
    revision = CommunityProblemRevision.objects.get(problem=problem)
    assert revision.number == problem.version == 1
    assert revision.snapshot["statement_latex"] == problem.statement_latex
    assert "solution_outline" not in revision.snapshot
    assert "core_ideas" not in revision.snapshot
    assert PRIVATE_OUTLINE not in str(revision.snapshot)
    assert not ProblemPublication.objects.exclude(visibility="private").exists()
    assert not ContestProblemStatement.objects.exists()
    assert not ProblemSolveRecord.objects.exists()
    assert not UserProblemCompletion.objects.exists()
    assert not StatementAIReview.objects.exists()


def test_repeated_proof_submission_reuses_the_selected_public_copy(client, owner, reviewer):
    _problem, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    url = _url("proof_solution_publish", attempt.pk)
    data = {
        **_hidden(client.get(url)), "title": "A direct proof", "summary": "A nonnegative square.",
        "public_credit": "Solution contributor", "consent": "on",
    }
    preview = client.post(url, {**data, "action": "preview"})
    submitted = {
        **data, **_hidden(preview), "action": "submit", "review_token": preview.context["review_token"],
    }
    first = client.post(url, submitted)
    second = client.post(url, submitted)
    assert first.status_code == second.status_code == 302
    assert first.url == second.url
    solution = CommunitySolution.objects.get(author=solver, problem=attempt.problem)
    assert solution.status == CommunitySolution.Status.PENDING
    assert solution.revisions.count() == 1
    assert ModerationEvent.objects.filter(solution=solution, action="proof_submitted").count() == 1


def test_withdrawn_proof_requires_a_new_author_submission_before_admin_reapproval(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    solution = _submit_proof(client, solver, attempt)
    assert _review(client, reviewer, problem, solution=solution).status_code == 302
    client.force_login(solver)
    solution.refresh_from_db()
    withdrawn = client.post(_url("proof_solution_owner", solution.pk), {
        "action": "withdraw", "version": solution.version,
    })
    assert withdrawn.status_code == 302
    solution.refresh_from_db()
    withdrawn_version = solution.version
    withdrawn_revision = solution.current_revision_id
    before = ModerationEvent.objects.filter(solution=solution).count()
    rejected = _review(client, reviewer, problem, solution=solution)
    assert rejected.status_code == 200
    assert rejected.context["form"].non_field_errors()
    solution.refresh_from_db()
    assert solution.status == "withdrawn"
    assert solution.version == withdrawn_version
    assert solution.current_revision_id == withdrawn_revision
    assert ModerationEvent.objects.filter(solution=solution).count() == before
    client.logout()
    assert "A direct proof" not in client.get(_public_url(publication)).content.decode()
    submitted = _submit_proof(client, solver, attempt, solution_id=solution.pk)
    assert submitted.pk == solution.pk
    assert submitted.status == "pending"
    assert submitted.current_revision_id != withdrawn_revision
    assert submitted.current_revision.number == 2
    assert _review(client, reviewer, problem, solution=submitted).status_code == 302
    client.logout()
    assert "A direct proof" in client.get(_public_url(publication)).content.decode()


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("invalid_id", ["not-a-uuid", "123"])
def test_malformed_solution_selection_returns_404_without_creating_a_contribution(
    client, owner, reviewer, method, invalid_id,
):
    _, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    url = _url("proof_solution_publish", attempt.pk)
    if method == "get":
        response = client.get(url, {"solution": invalid_id})
    else:
        response = client.post(url, {
            **_hidden(client.get(url)), "solution_id": invalid_id, "action": "preview",
            "title": "Selected proof", "summary": "", "public_credit": "Contributor", "consent": "on",
        })
    assert response.status_code == 404
    assert not CommunitySolution.objects.exists()
    assert CommunityAttempt.objects.get(pk=attempt.pk).body_source == PROOF_BODY


@pytest.mark.parametrize("target", ["problem", "proof"])
def test_stale_moderation_release_cannot_clear_a_newer_hold(client, owner, reviewer, target):
    problem, publication = _published_problem(client, owner, reviewer)
    solution = None
    if target == "proof":
        solver = UserFactory()
        attempt = _save_attempt(client, solver, publication)
        solution = _submit_proof(client, solver, attempt)
        assert _review(client, reviewer, problem, solution=solution).status_code == 302
    client.force_login(reviewer)
    moderation = (
        _url("proof_solution_moderation", solution.pk) if solution else _url("proof_moderation", problem.pk)
    )
    before_hold = client.get(moderation)
    stale_version = before_hold.context["control_version"]
    held = client.post(moderation, {
        **_hidden(before_hold), "action": "hold", "reason": "Newly discovered publication concern",
        "control_version": stale_version,
    })
    assert held.status_code == 302
    held_target = CommunitySolution.objects.get(pk=solution.pk) if solution else ProblemPublication.objects.get(
        problem=problem,
    )
    assert held_target.is_held is True
    held_version = held_target.version
    assert held_version > stale_version
    events_after_hold = ModerationEvent.objects.filter(problem=problem).count()
    stale = client.post(moderation, {
        **_hidden(before_hold), "action": "release", "reason": "Outdated release decision",
        "control_version": stale_version,
    })
    assert stale.status_code == 200
    assert stale.context["form"].non_field_errors()
    held_target.refresh_from_db()
    assert held_target.is_held is True
    assert held_target.version == held_version
    assert ModerationEvent.objects.filter(problem=problem).count() == events_after_hold
    client.logout()
    public = client.get(_public_url(publication))
    if solution:
        assert public.status_code == 200
        assert "A direct proof" not in public.content.decode()
    else:
        assert public.status_code == 404
    client.force_login(reviewer)
    latest = client.get(moderation)
    assert latest.context["control_version"] == held_version
    released = client.post(moderation, {
        **_hidden(latest), "action": "release", "reason": "Concern resolved after current review",
        "control_version": latest.context["control_version"],
    })
    assert released.status_code == 302
    held_target.refresh_from_db()
    assert held_target.is_held is False
    client.logout()
    final = client.get(_public_url(publication))
    assert final.status_code == 200
    if solution:
        assert "A direct proof" in final.content.decode()


def test_public_problem_paginates_actual_proof_bodies_not_just_solution_cards(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    bodies = {}
    for number in range(11):
        # The shared factory reuses matching emails; this fixture needs distinct solvers.
        solver = UserFactory(email=f"pagination-solver-{number}@example.invalid")
        marker = f"BODY-PAGINATION-MARKER-{number:02d}"
        attempt = _save_attempt(client, solver, publication, body=PROOF_BODY + "\n" + marker)
        solution = _submit_proof(client, solver, attempt, title=f"Method {number}")
        assert _review(client, reviewer, problem, solution=solution).status_code == 302
        bodies[solution.pk] = marker
    client.logout()
    first = client.get(_public_url(publication))
    second = client.get(_public_url(publication), {"solutions_page": 2})
    assert first.status_code == second.status_code == 200
    assert first.context["solution_count"] == second.context["solution_count"] == 11
    first_ids = {solution.pk for solution in first.context["solutions"]}
    second_ids = {solution.pk for solution in second.context["solutions"]}
    assert len(first_ids) == 10
    assert len(second_ids) == 1
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == set(bodies)
    for solution_id, marker in bodies.items():
        assert (marker in first.content.decode()) is (solution_id in first_ids)
        assert (marker in second.content.decode()) is (solution_id in second_ids)



def test_legacy_member_review_does_not_grant_external_publication_approval(client, owner):
    problem = CommunityProblem.objects.create(
        author=owner, title="Previously member-reviewed problem", statement_latex="Find the positive integer.",
        topic="NT", mohs=5, source_kind="original", source_details="Legacy source",
        status="approved", legacy_member_visible=True,
    )
    client.force_login(owner)
    url = _url("proof_sharing", problem.pk)
    data = {
        **_hidden(client.get(url)), "visibility": "unlisted", "public_credit": "Contributor", "consent": "on",
    }
    preview = client.post(url, {**data, "action": "preview"})
    assert preview.status_code == 200
    assert preview.context["review_token"]
    response = client.post(url, {
        **data, **_hidden(preview), "action": "publish", "review_token": preview.context["review_token"],
    })
    assert response.status_code in {200, 400}
    assert not ProblemPublication.objects.exclude(visibility="private").exists()
    assert CommunityProblem.objects.get(pk=problem.pk).legacy_member_visible is True



def test_statement_edit_keeps_old_public_snapshot_until_fresh_review_and_explicit_update(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    original_revision = publication.statement_revision_id
    original_statement = problem.statement_latex
    client.force_login(owner)
    edit = _url("community_problem_edit", problem.pk)
    opened = client.get(edit)
    assert opened.status_code == 200
    data = {
        field.html_name: field.value() if field.value() is not None else ""
        for field in opened.context["form"]
    }
    data.update({
        "title": "Unreviewed changed title",
        "statement_latex": r"For $a,b\geq0$, prove $a^2+b^2\geq2ab$.",
        "sharing_confirmed": "on",
    })
    checked = client.post(edit, {**data, "action": "check"})
    assert checked.context["similarity_token"], checked.context["form"].errors
    saved = client.post(edit, {
        **data, "action": "submit", "similarity_token": checked.context["similarity_token"],
        "matches_acknowledged": "1",
    })
    assert saved.status_code == 302, saved.content.decode()
    problem.refresh_from_db()
    assert problem.version == 2
    assert problem.status == "pending"
    publication.refresh_from_db()
    assert publication.statement_revision_id == original_revision
    client.logout()
    pending_html = client.get(_public_url(publication)).content.decode()
    assert "Unreviewed changed title" not in pending_html
    assert escape(original_statement) in pending_html
    assert _review(client, reviewer, problem).status_code == 302
    publication.refresh_from_db()
    assert publication.statement_revision_id == original_revision
    updated = _share(client, owner, problem)
    assert updated.statement_revision_id != original_revision
    assert CommunityProblemRevision.objects.filter(problem=problem).count() == 2
    client.logout()
    assert "Unreviewed changed title" in client.get(_public_url(updated)).content.decode()


def test_a_saved_proof_preview_cannot_survive_problem_stop_and_reshare(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    publishing = _url("proof_solution_publish", attempt.pk)
    data = {
        **_hidden(client.get(publishing)), "title": "A direct proof", "summary": "",
        "public_credit": "Solution contributor", "consent": "on",
    }
    preview = client.post(publishing, {**data, "action": "preview"})
    assert preview.context["review_token"]
    client.force_login(owner)
    sharing = _url("proof_sharing", problem.pk)
    assert client.post(sharing, {**_hidden(client.get(sharing)), "action": "stop"}).status_code == 302
    renewed = _share(client, owner, problem)
    assert renewed.generation != publication.generation
    client.force_login(solver)
    response = client.post(publishing, {
        **data, **_hidden(preview), "action": "submit", "review_token": preview.context["review_token"],
    })
    assert response.status_code in {200, 400}
    assert not CommunitySolution.objects.filter(author=solver, problem=problem).exists()


def test_publication_requires_explicit_consent_after_reviewing_the_exact_preview(client, owner, reviewer):
    problem = _submit_problem(client, owner)
    assert _review(client, reviewer, problem).status_code == 302
    client.force_login(owner)
    url = _url("proof_sharing", problem.pk)
    data = {**_hidden(client.get(url)), "visibility": "public", "public_credit": "Contributor", "consent": "on"}
    preview = client.post(url, {**data, "action": "preview"})
    assert preview.context["review_token"]
    response = client.post(url, {
        **data, **_hidden(preview), "consent": "", "action": "publish",
        "review_token": preview.context["review_token"],
    })
    assert response.status_code in {200, 400}
    assert not ProblemPublication.objects.exclude(visibility="private").exists()



def test_new_private_problem_is_hidden_from_other_members_and_counts_but_legacy_access_survives(
    client, owner, reviewer,
):
    private = _submit_problem(client, owner, title="PRIVATE-PROBLEM-TITLE")
    legacy = CommunityProblem.objects.create(
        author=owner, title="LEGACY-MEMBER-TITLE", statement_latex="Legacy statement", topic="ALG",
        mohs=5, source_kind="original", source_details="Legacy author", legacy_member_visible=True,
    )
    client.force_login(UserFactory())
    assert client.get(_url("community_problem_detail", private.pk)).status_code == 404
    listing = client.get(_url("community_problem_list"), {"tab": "all"})
    assert listing.context["all_count"] == 1
    assert [row.pk for row in listing.context["problems"]] == [legacy.pk]
    assert "PRIVATE-PROBLEM-TITLE" not in listing.content.decode()
    assert client.get(_url("community_problem_detail", legacy.pk)).status_code == 200
    client.force_login(reviewer)
    assert client.get(_url("community_problem_detail", private.pk)).status_code == 200


def test_gets_and_moderation_approval_never_enable_public_sharing(client, owner, reviewer):
    problem = _submit_problem(client, owner)
    counts = (ProblemPublication.objects.count(), CommunityAttempt.objects.count(), CommunitySolution.objects.count())
    client.get(_url("proof_sharing", problem.pk))
    assert counts == (
        ProblemPublication.objects.count(), CommunityAttempt.objects.count(), CommunitySolution.objects.count(),
    )
    assert _review(client, reviewer, problem).status_code == 302
    publication = ProblemPublication.objects.filter(problem=problem).first()
    assert publication is None or publication.visibility == "private"
    assert CommunityAttempt.objects.count() == CommunitySolution.objects.count() == 0
    client.logout()
    assert problem.title not in client.get(_url("proof_public_list")).content.decode()
    if publication:
        assert client.get(_public_url(publication)).status_code == 404


@pytest.mark.parametrize("role", [User.Role.NORMAL, User.Role.TRAINER, User.Role.MODERATOR])
def test_only_admins_can_moderate_new_publications(client, owner, role):
    problem = _submit_problem(client, owner)
    client.force_login(UserFactory(role=role, is_staff=True))
    url = _url("proof_moderation", problem.pk)
    before = ModerationEvent.objects.count()
    assert client.get(url).status_code == 403
    assert client.post(url, {"action": "hold", "reason": "Unauthorized hold"}).status_code == 403
    assert ModerationEvent.objects.count() == before


def test_approval_requires_content_rights_and_embargo_checks(client, owner, reviewer):
    problem = _submit_problem(client, owner)
    response = _review(client, reviewer, problem, check_rights="", check_embargo="")
    assert response.status_code == 200
    assert response.context["form"].errors
    problem.refresh_from_db()
    assert problem.status == "pending"
    assert not ProblemPublication.objects.exclude(visibility="private").exists()


def test_unreviewed_problem_cannot_create_an_unlisted_publication(client, owner):
    problem = _submit_problem(client, owner)
    url = _url("proof_sharing", problem.pk)
    response = client.post(url, {
        **_hidden(client.get(url)), "visibility": "unlisted", "public_credit": "Contributor",
        "consent": "on", "action": "publish", "review_token": "forged",
    })
    assert response.status_code in {200, 400, 403}
    assert not ProblemPublication.objects.exclude(visibility="private").exists()


def test_unlisted_publication_is_guest_readable_but_not_discoverable_or_indexable(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    client.logout()
    response = client.get(_public_url(publication))
    assert response.status_code == 200
    html = response.content.decode()
    assert problem.title in html
    assert "noindex" in response.get("X-Robots-Tag", "") or 'name="robots" content="noindex' in html
    assert problem.title not in client.get(_url("proof_public_list")).content.decode()
    for private in (PRIVATE_OUTLINE, PRIVATE_IDEA, PRIVATE_NOTES, owner.email, reviewer.email):
        assert private not in html


def test_public_discovery_requires_explicit_public_visibility(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer, visibility="public")
    hidden = _submit_problem(client, owner, title="PRIVATE-DISCOVERY-EXCLUSION")
    client.logout()
    response = client.get(_url("proof_public_list"))
    assert response.status_code == 200
    assert problem.title in response.content.decode()
    assert hidden.title not in response.content.decode()
    assert client.get(_public_url(publication)).status_code == 200


def test_sharing_rejects_cross_user_and_changed_preview(client, owner, reviewer):
    problem = _submit_problem(client, owner)
    assert _review(client, reviewer, problem).status_code == 302
    client.force_login(owner)
    url = _url("proof_sharing", problem.pk)
    data = {**_hidden(client.get(url)), "visibility": "public", "public_credit": "Contributor", "consent": "on"}
    preview = client.post(url, {**data, "action": "preview"})
    assert preview.context["review_token"]
    publication = ProblemPublication.objects.get(problem=problem)
    token = preview.context["review_token"]
    client.force_login(UserFactory())
    assert client.post(url, {**data, "action": "publish", "review_token": token}).status_code == 404
    client.force_login(owner)
    changed = client.post(url, {
        **data, **_hidden(preview), "public_credit": "Changed public identity",
        "action": "publish", "review_token": token,
    })
    assert changed.status_code in {200, 400}
    publication.refresh_from_db()
    assert publication.visibility == "private"


def test_private_attempts_are_owner_only_and_stale_saves_cannot_overwrite(client, owner, reviewer):
    _, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    url = _url("proof_attempt_edit", attempt.pk)
    first = _hidden(client.get(url))
    good = client.post(url, {**first, "title": "Saved title", "body_source": "NEW-SAVED-PROOF", "action": "save"})
    assert good.status_code == 302
    stale = client.post(url, {**first, "title": "Stale title", "body_source": "STALE-PROOF", "action": "save"})
    assert stale.status_code in {200, 409}
    attempt.refresh_from_db()
    assert attempt.body_source == "NEW-SAVED-PROOF"
    for other in (owner, reviewer, UserFactory()):
        client.force_login(other)
        assert client.get(url).status_code == 404
        assert client.post(url, {"body_source": "Intrusion", "version": attempt.version}).status_code == 404


def test_attempt_publication_copies_saved_source_then_requires_content_moderation(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer, core_ideas=PRIVATE_IDEA)
    solver = UserFactory(name="Private learner name")
    attempt = _save_attempt(client, solver, publication)
    assert not CommunitySolution.objects.exists()
    solution = _submit_proof(client, solver, attempt, body_source="UNSAVED-POSTED-INJECTION")
    assert solution.status == "pending"
    assert solution.current_revision.body_source == PROOF_BODY
    assert solution.current_revision.statement_revision_id == attempt.statement_revision_id
    assert solution.current_revision.source_attempt_id == attempt.pk
    client.logout()
    assert "A direct proof" not in client.get(_public_url(publication)).content.decode()
    assert _review(client, reviewer, problem, solution=solution).status_code == 302
    client.logout()
    html = client.get(_public_url(publication)).content.decode()
    assert "A direct proof" in html
    assert "Solution contributor" in html
    assert "UNSAVED-POSTED-INJECTION" not in html
    for private in (PRIVATE_IDEA, PRIVATE_OUTLINE, PRIVATE_NOTES, solver.email, "Private learner name"):
        assert private not in html
    details = [
        node for node in _nodes(parse_html(html))
        if node.name == "details" and "Reveal community solutions" in str(node)
    ]
    assert details
    assert "open" not in dict(details[0].attributes)
    assert not StatementAIReview.objects.exists()
    assert not ProblemSolveRecord.objects.exists()
    assert not UserProblemCompletion.objects.exists()


def test_editing_private_attempt_does_not_modify_a_published_proof(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    solution = _submit_proof(client, solver, attempt)
    assert _review(client, reviewer, problem, solution=solution).status_code == 302
    client.force_login(solver)
    url = _url("proof_attempt_edit", attempt.pk)
    changed = client.post(url, {
        **_hidden(client.get(url)), "title": "My private revision",
        "body_source": "NEW-PRIVATE-ARGUMENT", "action": "save",
    })
    assert changed.status_code == 302
    solution.refresh_from_db()
    assert solution.current_revision.body_source == PROOF_BODY
    client.logout()
    assert "NEW-PRIVATE-ARGUMENT" not in client.get(_public_url(publication)).content.decode()


def test_stopping_sharing_preserves_private_work_and_rotates_the_link(client, owner, reviewer):
    _, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    old_url = _public_url(publication)
    client.force_login(owner)
    sharing = _url("proof_sharing", publication.problem_id)
    assert client.post(sharing, {**_hidden(client.get(sharing)), "action": "stop"}).status_code == 302
    client.logout()
    assert client.get(old_url).status_code == 404
    client.force_login(solver)
    assert client.get(_url("proof_attempt_edit", attempt.pk)).status_code == 200
    attempt.refresh_from_db()
    assert attempt.body_source == PROOF_BODY
    renewed = _share(client, owner, publication.problem)
    assert renewed.token != publication.token
    client.logout()
    assert client.get(old_url).status_code == 404
    assert client.get(_public_url(renewed)).status_code == 200


def test_embargo_and_admin_hold_revoke_public_access_and_discovery(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer, visibility="public")
    CommunityProblem.objects.filter(pk=problem.pk).update(embargo_until=timezone.now() + timedelta(days=1))
    client.logout()
    assert client.get(_public_url(publication)).status_code == 404
    assert problem.title not in client.get(_url("proof_public_list")).content.decode()
    CommunityProblem.objects.filter(pk=problem.pk).update(embargo_until=None)
    client.force_login(reviewer)
    moderation = _url("proof_moderation", problem.pk)
    opened = client.get(moderation)
    response = client.post(moderation, {
        **_hidden(opened), "control_version": opened.context["control_version"],
        "action": "hold", "reason": "Publication concern",
    })
    assert response.status_code == 302
    assert ModerationEvent.objects.filter(problem=problem, actor=reviewer).exists()
    publication.refresh_from_db()
    assert publication.is_held is True
    client.logout()
    assert client.get(_public_url(publication)).status_code == 404
    assert problem.title not in client.get(_url("proof_public_list")).content.decode()


def test_private_reports_reach_admins_without_becoming_public_content(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    reporter = UserFactory()
    client.force_login(reporter)
    url = _url("proof_report", publication.token)
    response = client.post(url, {"reason": "gap", "details": "REPORT-PRIVATE-DETAILS"})
    assert response.status_code == 302
    report = CommunityContentReport.objects.get(problem=problem, reporter=reporter)
    assert report.details == "REPORT-PRIVATE-DETAILS"
    client.logout()
    assert report.details not in client.get(_public_url(publication)).content.decode()
    assert client.get(url).status_code == 302
    client.force_login(reviewer)
    assert report.details in client.get(_url("proof_moderation", problem.pk)).content.decode()


@pytest.mark.parametrize(
    "image_syntax",
    [
        r"\includegraphics{{{path}}}",
        r"\includegraphics {{ {path} }}",
        "\\includegraphics\n[width=0.5\\linewidth]\n  {{ {path} }}",
    ],
    ids=["canonical", "spaces-around-command-and-path", "multiline-options-and-braces"],
)
def test_private_image_ownership_and_public_snapshot_bytes_follow_parent_visibility(
    client, owner, reviewer, image_syntax,
):
    problem, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    upload = _url("proof_attempt_upload", attempt.pk)
    uploaded = client.post(upload, {"image": SimpleUploadedFile("diagram.png", PNG, content_type="image/png")})
    assert uploaded.status_code == 200
    path = uploaded.json()["path"]
    private_url = _url("proof_attempt_asset", attempt.pk, path)
    own = client.get(private_url)
    assert own.status_code == 200
    stored_bytes = own.content
    assert stored_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    client.force_login(owner)
    assert client.get(private_url).status_code == 404
    assert client.post(upload, {"image": SimpleUploadedFile("other.png", PNG)}).status_code == 404
    client.force_login(solver)
    edit = _url("proof_attempt_edit", attempt.pk)
    saved = client.post(edit, {
        **_hidden(client.get(edit)), "title": "Proof with diagram", "action": "save",
        "body_source": PROOF_BODY + "\n" + image_syntax.format(path=path),
    })
    assert saved.status_code == 302
    attempt.refresh_from_db()
    solution = _submit_proof(client, solver, attempt)
    assert _review(client, reviewer, problem, solution=solution).status_code == 302
    asset = CommunitySolutionAsset.objects.get(revision=solution.current_revision, name=path)
    assert bytes(asset.data) == stored_bytes
    public_asset = _url("proof_public_asset", publication.token, solution.pk, path)
    client.logout()
    delivered = client.get(public_asset)
    assert delivered.status_code == 200
    assert delivered.content == stored_bytes
    assert delivered["X-Content-Type-Options"] == "nosniff"
    client.force_login(owner)
    sharing = _url("proof_sharing", problem.pk)
    assert client.post(sharing, {**_hidden(client.get(sharing)), "action": "stop"}).status_code == 302
    client.logout()
    assert client.get(public_asset).status_code == 404


def test_private_asset_from_another_attempt_cannot_be_copied_into_public_proof(client, owner, reviewer):
    _, publication = _published_problem(client, owner, reviewer)
    first = UserFactory()
    first_attempt = _save_attempt(client, first, publication)
    upload = client.post(_url("proof_attempt_upload", first_attempt.pk), {
        "image": SimpleUploadedFile("private.png", PNG, content_type="image/png"),
    })
    assert upload.status_code == 200
    path = upload.json()["path"]
    other = UserFactory()
    attempt = _save_attempt(client, other, publication, body=rf"\includegraphics{{{path}}}")
    url = _url("proof_solution_publish", attempt.pk)
    response = client.post(url, {
        **_hidden(client.get(url)), "action": "preview", "title": "Invalid borrowed diagram",
        "summary": "", "public_credit": "Other contributor", "consent": "on",
    })
    assert response.status_code in {200, 400}
    assert not response.context["review_token"]
    assert not CommunitySolution.objects.filter(author=other).exists()


def test_withdrawn_proof_disappears_without_deleting_private_work(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    attempt = _save_attempt(client, solver, publication)
    solution = _submit_proof(client, solver, attempt)
    assert _review(client, reviewer, problem, solution=solution).status_code == 302
    client.force_login(solver)
    solution.refresh_from_db()
    response = client.post(_url("proof_solution_owner", solution.pk), {
        "action": "withdraw", "version": solution.version,
    })
    assert response.status_code == 302
    solution.refresh_from_db()
    assert solution.status == "withdrawn"
    assert CommunityAttempt.objects.filter(pk=attempt.pk, body_source=PROOF_BODY).exists()
    client.logout()
    assert "A direct proof" not in client.get(_public_url(publication)).content.decode()


def test_script_source_is_escaped_in_public_proofs(client, owner, reviewer):
    problem, publication = _published_problem(client, owner, reviewer)
    solver = UserFactory()
    source = '<script>alert("proof")</script> ' + PROOF_BODY
    attempt = _save_attempt(client, solver, publication, body=source)
    solution = _submit_proof(client, solver, attempt)
    assert _review(client, reviewer, problem, solution=solution).status_code == 302
    client.logout()
    html = client.get(_public_url(publication)).content.decode()
    assert '<script>alert("proof")</script>' not in html
    assert "&lt;script&gt;" in html


def test_pending_accounts_can_read_publications_but_cannot_contribute(client, owner, reviewer):
    _, publication = _published_problem(client, owner, reviewer)
    client.force_login(UserFactory(is_approved=False))
    assert client.get(_public_url(publication)).status_code == 200
    response = client.get(_url("proof_attempt", publication.token))
    assert response.status_code == 302
    assert response.url == reverse("users:approval_pending")
    assert not CommunityAttempt.objects.exists()


def test_publication_mutations_retain_csrf_protection(client, owner, reviewer):
    problem, _ = _published_problem(client, owner, reviewer)
    protected = Client(enforce_csrf_checks=True)
    protected.force_login(owner)
    assert protected.post(_url("proof_sharing", problem.pk), {"action": "stop"}).status_code == 403


def test_ai_review_endpoint_stays_disabled_even_if_flag_is_accidentally_enabled(client, owner, reviewer, settings):
    problem = _submit_problem(client, owner)
    settings.PROBLEM_STATEMENT_AI_REVIEW_ENABLED = True
    client.force_login(reviewer)
    response = client.post(_url("community_problem_ai_review", problem.pk), {
        "version": problem.version, "acknowledged": "1",
    })
    assert response.status_code == 403
    assert not StatementAIReview.objects.exists()
