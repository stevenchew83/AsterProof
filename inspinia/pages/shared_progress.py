"""Read-only progress sharing for the explicitly configured Alex/Ben pair."""

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.urls import reverse

from inspinia.users.models import User
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role

LEARNER_LABELS = {"alex": "Alex", "ben": "Ben"}
PROGRESS_SECTIONS = {
    "completions": "Problem completions",
    "techniques": "Technique coverage",
    "training": "Training roadmap",
}
COMPARISON_SECTION_LABELS = {"completions": "Completions", "techniques": "Techniques", "training": "Training"}


def shared_progress_learners(viewer) -> list[dict]:
    if not getattr(viewer, "is_active", False) or not user_can_access_app_features(viewer):
        return []
    emails = {
        slug: str(settings.SHARED_PROGRESS_LEARNERS.get(slug, "")).strip().casefold()
        for slug in LEARNER_LABELS
    }
    if not all(emails.values()) or len(set(emails.values())) != len(LEARNER_LABELS):
        return []
    # Admins may inspect this fixed pair; other viewers must be one of the learners.
    admin = user_has_admin_role(viewer)
    if not admin and viewer.email.casefold() not in emails.values():
        return []
    matches = list(
        User.objects.filter(is_active=True).filter(Q(email__iexact=emails["alex"]) | Q(email__iexact=emails["ben"])),
    )
    users = {user.email.casefold(): user for user in matches}
    if len(users) != len(matches) or (not admin and viewer.pk not in {user.pk for user in matches}):
        return []
    return [
        {
            "slug": slug,
            "label": label,
            "user": users[emails[slug]],
            "url": reverse("pages:shared_progress", kwargs={"learner": slug}),
        }
        for slug, label in LEARNER_LABELS.items()
        if emails[slug] in users and user_can_access_app_features(users[emails[slug]])
    ]


def shared_progress_context(viewer, *, learner: str, section: str) -> dict:
    if learner not in LEARNER_LABELS or section not in PROGRESS_SECTIONS:
        raise Http404
    learners = shared_progress_learners(viewer)
    if not learners:
        raise PermissionDenied
    selected = next((entry for entry in learners if entry["slug"] == learner), None)
    if selected is None:
        raise Http404
    return {
        "shared_progress_subject": selected["user"],
        "shared_progress_label": selected["label"],
        "shared_progress_learner": learner,
        "shared_progress_section": section,
        "shared_progress_compare_url": (
            shared_progress_comparison_url(section) if len(learners) == len(LEARNER_LABELS) else ""
        ),
        "shared_progress_learners": [
            {**entry, "url": shared_progress_section_url(entry["slug"], section)} for entry in learners
        ],
        "shared_progress_tabs": [
            {"key": key, "label": label, "url": shared_progress_section_url(learner, key)}
            for key, label in PROGRESS_SECTIONS.items()
        ],
    }


def shared_progress_section_url(learner: str, section: str) -> str:
    return reverse("pages:shared_progress_section", kwargs={"learner": learner, "section": section})


def shared_progress_comparison_url(section: str) -> str:
    return reverse("pages:shared_progress_comparison_section", kwargs={"section": section})


def shared_progress_comparison_context(viewer, *, section: str) -> dict:
    if section not in PROGRESS_SECTIONS:
        raise Http404
    learners = shared_progress_learners(viewer)
    if not learners:
        raise PermissionDenied
    if len(learners) != len(LEARNER_LABELS):
        raise Http404
    return {
        "shared_progress_is_comparison": True,
        "shared_progress_section": section,
        "shared_progress_compare_url": shared_progress_comparison_url(section),
        "shared_progress_learners": [
            {**entry, "url": shared_progress_section_url(entry["slug"], section)} for entry in learners
        ],
        "shared_progress_tabs": [
            {"key": key, "label": label, "url": shared_progress_comparison_url(key)}
            for key, label in COMPARISON_SECTION_LABELS.items()
        ],
    }
