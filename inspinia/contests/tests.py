import pytest
from django.utils import timezone

from inspinia.contests.models import ContestEvent
from inspinia.contests.models import ScoreEntry
from inspinia.contests.services import apply_simple_elo
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_simple_elo_changes_ratings():
    user_a = UserFactory(rating=1200)
    user_b = UserFactory(rating=1200)
    contest = ContestEvent.objects.create(
        title="Mock Contest",
        slug="mock-contest",
        start_time=timezone.now(),
        end_time=timezone.now(),
        is_rated=True,
    )
    ScoreEntry.objects.create(contest=contest, user=user_a, score=7, rank=1)
    ScoreEntry.objects.create(contest=contest, user=user_b, score=3, rank=2)

    apply_simple_elo(contest.id, k_factor=20)

    user_a.refresh_from_db()
    user_b.refresh_from_db()
    assert user_a.rating > 1200
    assert user_b.rating < 1200
