from http import HTTPStatus

import pytest
from django.urls import reverse

from inspinia.training.models import LevelThreshold
from inspinia.training.models import Material
from inspinia.training.models import PointLedger
from inspinia.training.models import Problem
from inspinia.training.models import Submission
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic
from inspinia.training.services import complete_material
from inspinia.training.services import get_next_level
from inspinia.training.services import get_subtopic_progress
from inspinia.training.services import get_topic_progress
from inspinia.training.services import get_user_current_level
from inspinia.training.services import get_user_total_points
from inspinia.training.services import review_submission
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

FULL_COMPLETION_PERCENTAGE = 100
INITIAL_LEDGER_POINTS = 275
MATERIAL_COMPLETION_POINTS = 10
PARTIAL_ACCEPTANCE_POINTS = 15


def _thresholds() -> None:
    for level_number, name, minimum_points in [
        (1, "Euclid Initiate", 0),
        (2, "Hypatia Explorer", 100),
        (3, "Fibonacci Apprentice", 250),
        (4, "Euler Solver", 500),
    ]:
        LevelThreshold.objects.create(
            level_number=level_number,
            name=name,
            minimum_points=minimum_points,
        )


def _topic_tree(*, published: bool = True) -> tuple[Topic, Subtopic, Material, Problem]:
    trainer = UserFactory(role=User.Role.TRAINER)
    topic = Topic.objects.create(
        title="Algebra",
        slug="algebra",
        description="Core algebra training.",
        order=1,
        is_published=published,
    )
    subtopic = Subtopic.objects.create(
        topic=topic,
        title="Algebraic identities",
        slug="algebraic-identities",
        description="Factorization and transformations.",
        order=1,
        is_published=published,
    )
    material = Material.objects.create(
        subtopic=subtopic,
        title="Factoring patterns",
        slug="factoring-patterns",
        content_markdown="Use $a^2-b^2=(a-b)(a+b)$.",
        completion_points=10,
        order=1,
        is_published=published,
        created_by=trainer,
    )
    problem = Problem.objects.create(
        subtopic=subtopic,
        title="Identity challenge",
        slug="identity-challenge",
        statement_markdown="Prove that $a^3-b^3$ factors.",
        difficulty=Problem.Difficulty.INTRODUCTORY,
        tags=["IDENTITIES"],
        max_points=40,
        order=1,
        is_published=published,
        created_by=trainer,
    )
    return topic, subtopic, material, problem


def test_level_is_calculated_from_point_ledger():
    _thresholds()
    user = UserFactory()
    PointLedger.objects.create(
        user=user,
        source_type=PointLedger.SourceType.MANUAL_ADJUSTMENT,
        source_id="bootstrap",
        points=INITIAL_LEDGER_POINTS,
        reason="Starting balance",
    )

    assert get_user_total_points(user) == INITIAL_LEDGER_POINTS
    assert get_user_current_level(user).name == "Fibonacci Apprentice"
    assert get_next_level(user).name == "Euler Solver"


def test_material_completion_awards_points_only_once():
    _thresholds()
    user = UserFactory()
    _topic, _subtopic, material, _problem = _topic_tree()

    first = complete_material(user=user, material=material)
    second = complete_material(user=user, material=material)

    assert first.points_awarded == MATERIAL_COMPLETION_POINTS
    assert second.id == first.id
    assert (
        PointLedger.objects.filter(
            user=user,
            source_type=PointLedger.SourceType.MATERIAL_COMPLETION,
            source_id=str(first.id),
        ).count()
        == 1
    )
    assert get_user_total_points(user) == MATERIAL_COMPLETION_POINTS


def test_trainer_review_awards_submission_points_only_once():
    _thresholds()
    student = UserFactory()
    trainer = UserFactory(role=User.Role.TRAINER)
    _topic, _subtopic, _material, problem = _topic_tree()
    submission = Submission.objects.create(
        user=student,
        problem=problem,
        solution_markdown="A clean factorization proof.",
    )

    review_submission(
        submission=submission,
        reviewer=trainer,
        status=Submission.Status.ACCEPTED,
        awarded_points=problem.max_points,
        comment_body="Correct.",
    )
    review_submission(
        submission=submission,
        reviewer=trainer,
        status=Submission.Status.ACCEPTED,
        awarded_points=problem.max_points,
        comment_body="Still correct.",
    )

    submission.refresh_from_db()
    assert submission.status == Submission.Status.ACCEPTED
    assert submission.awarded_points == problem.max_points
    assert get_user_total_points(student) == problem.max_points
    assert (
        PointLedger.objects.filter(
            user=student,
            source_type=PointLedger.SourceType.PROBLEM_SUBMISSION,
            source_id=str(submission.id),
        ).count()
        == 1
    )


def test_student_cannot_access_trainer_or_admin_pages(client):
    student = UserFactory(role=User.Role.NORMAL)
    client.force_login(student)

    assert client.get(reverse("training:trainer_dashboard")).status_code == HTTPStatus.FORBIDDEN
    assert client.get(reverse("training:admin_levels")).status_code == HTTPStatus.FORBIDDEN


def test_student_cannot_award_submission_points(client):
    _thresholds()
    student = UserFactory(role=User.Role.NORMAL)
    other_student = UserFactory(role=User.Role.NORMAL)
    _topic, _subtopic, _material, problem = _topic_tree()
    submission = Submission.objects.create(
        user=other_student,
        problem=problem,
        solution_markdown="Attempt.",
    )
    client.force_login(student)

    response = client.post(
        reverse("training:submission_detail", args=[submission.id]),
        {
            "status": Submission.Status.ACCEPTED,
            "awarded_points": problem.max_points,
            "comment_body": "Looks good.",
        },
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert get_user_total_points(other_student) == 0


def test_unpublished_content_is_hidden_from_students_but_visible_to_trainers(client):
    student = UserFactory(role=User.Role.NORMAL)
    trainer = UserFactory(role=User.Role.TRAINER)
    _topic, _subtopic, material, problem = _topic_tree(published=False)

    client.force_login(student)
    assert client.get(reverse("training:material_detail", args=[material.slug])).status_code == HTTPStatus.NOT_FOUND
    assert client.get(reverse("training:problem_detail", args=[problem.slug])).status_code == HTTPStatus.NOT_FOUND

    client.force_login(trainer)
    assert client.get(reverse("training:material_detail", args=[material.slug])).status_code == HTTPStatus.OK
    assert client.get(reverse("training:problem_detail", args=[problem.slug])).status_code == HTTPStatus.OK


def test_progress_counts_completed_materials_and_accepted_problem_points():
    _thresholds()
    student = UserFactory()
    trainer = UserFactory(role=User.Role.TRAINER)
    topic, subtopic, material, problem = _topic_tree()
    complete_material(user=student, material=material)
    submission = Submission.objects.create(
        user=student,
        problem=problem,
        solution_markdown="Partial solution.",
    )
    review_submission(
        submission=submission,
        reviewer=trainer,
        status=Submission.Status.PARTIALLY_ACCEPTED,
        awarded_points=PARTIAL_ACCEPTANCE_POINTS,
        comment_body="Good start.",
    )

    subtopic_progress = get_subtopic_progress(student, subtopic)
    topic_progress = get_topic_progress(student, topic)
    earned_points = MATERIAL_COMPLETION_POINTS + PARTIAL_ACCEPTANCE_POINTS
    available_points = material.completion_points + problem.max_points

    assert subtopic_progress.completed_materials == 1
    assert subtopic_progress.accepted_problems == 1
    assert subtopic_progress.earned_points == earned_points
    assert subtopic_progress.available_points == available_points
    assert subtopic_progress.completion_percentage == FULL_COMPLETION_PERCENTAGE
    assert topic_progress.earned_points == earned_points
    assert topic_progress.available_points == available_points


def test_sidebar_shows_role_appropriate_training_links(client):
    _thresholds()
    _topic_tree()

    student = UserFactory(role=User.Role.NORMAL)
    client.force_login(student)
    student_html = client.get(reverse("training:dashboard")).content.decode("utf-8")
    assert "Training" in student_html
    assert "Roadmap" in student_html
    assert "Trainer queue" not in student_html
    assert "Level settings" not in student_html

    trainer = UserFactory(role=User.Role.TRAINER)
    client.force_login(trainer)
    trainer_html = client.get(reverse("training:dashboard")).content.decode("utf-8")
    assert "Trainer queue" in trainer_html
    assert "Training content" in trainer_html
    assert "Level settings" not in trainer_html

    admin = UserFactory(role=User.Role.ADMIN, is_approved=False)
    client.force_login(admin)
    admin_html = client.get(reverse("training:dashboard")).content.decode("utf-8")
    assert "Trainer queue" in admin_html
    assert "Level settings" in admin_html
