from math import pow

from django.db import transaction

from inspinia.contests.models import RatingDelta
from inspinia.contests.models import ScoreEntry


def _expected_score(player_rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + pow(10, (opponent_rating - player_rating) / 400.0))


@transaction.atomic
def apply_simple_elo(contest_id: int, k_factor: int | None = None, config=None):  # noqa: ANN001
    score_entries = list(
        ScoreEntry.objects.select_related("user")
        .filter(contest_id=contest_id)
        .order_by("rank", "-score"),
    )
    if len(score_entries) < 2:
        return []

    base_rating = float(getattr(config, "base_rating", 1200))
    effective_k = float(k_factor or getattr(config, "k_factor", 24))
    small_contest_threshold = int(getattr(config, "small_contest_threshold", 0) or 0)
    small_contest_k_multiplier = float(getattr(config, "small_contest_k_multiplier", 1.0))
    if small_contest_threshold and len(score_entries) < small_contest_threshold:
        effective_k *= small_contest_k_multiplier
    rating_floor = getattr(config, "rating_floor", None)
    rating_cap = getattr(config, "rating_cap", None)

    avg_rating = sum(entry.user.rating for entry in score_entries) / len(score_entries)
    snapshots = []
    for entry in score_entries:
        current = float(entry.user.rating or base_rating)
        expected = _expected_score(current, avg_rating)
        # Normalize rank into [0,1] where better rank means higher score.
        actual = max(0.0, (len(score_entries) - entry.rank) / max(1, len(score_entries) - 1))
        delta = effective_k * (actual - expected)
        new_rating = max(0.0, current + delta)
        if rating_floor is not None:
            new_rating = max(float(rating_floor), new_rating)
        if rating_cap is not None:
            new_rating = min(float(rating_cap), new_rating)
        entry.rating_delta = delta
        entry.save(update_fields=["rating_delta"])
        entry.user.rating = new_rating
        entry.user.save(update_fields=["rating"])
        RatingDelta.objects.create(
            user=entry.user,
            contest_id=contest_id,
            previous_rating=current,
            new_rating=new_rating,
            delta=delta,
        )
        snapshots.append(
            {
                "user": entry.user,
                "previous_rating": current,
                "new_rating": new_rating,
                "delta": delta,
            },
        )
    return snapshots
