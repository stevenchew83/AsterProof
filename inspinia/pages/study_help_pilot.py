"""Bounded authorization and credential access for the private BMO draft pilot."""

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from inspinia.pages.study_help_models import StudyHelpAdminEvent

PILOT_STATEMENT = UUID("e6a15951-47f5-4d74-bd0a-7ada530acff2")
PILOT_REVISION = "05cfccf20d7ec35240ca3235bcc0d9a82f6a483f2086fef5caef86baa728bd9b"
PILOT_PROMPT = UUID("cec50917-33d7-4243-80be-842738b825d2")
PILOT_MODEL = "gpt-6.1-sol"
PILOT_DIGEST = "7eeaf3166cace666c6b091bd8326490d6c23e0be8af248f65cb44f16634012b8"
PILOT_ARM = "arm_draft_pilot"
PILOT_FUNDING = "bmo_draft_pilot"
PILOT_INPUT_PRICE = 5_000_000
PILOT_OUTPUT_PRICE = 10_000_000
PILOT_REQUEST_CAP = 70_000
PILOT_TOTAL_CAP = 2 * PILOT_REQUEST_CAP


def pilot_authorization():
    """Return the one-time pilot authorization, even after generation access expires."""
    if (
        not settings.STUDY_HELP_DRAFT_HINT_PILOT_ENABLED
        or settings.STUDY_HELP_ENABLED
        or settings.STUDY_HELP_EVALUATION_ENABLED
    ):
        return None
    return StudyHelpAdminEvent.objects.filter(
        action=PILOT_ARM,
        prompt_id=PILOT_PROMPT,
        actor__isnull=False,
    ).first()


def pilot_lease():
    authorization = pilot_authorization()
    if authorization and authorization.created_at >= timezone.now() - timedelta(minutes=30):
        return authorization
    return None


def pilot_review_configuration():
    from inspinia.solutions.admin_review_models import AdminSolutionReviewSettings

    return AdminSolutionReviewSettings.objects.filter(pk=1, models_enabled=[PILOT_MODEL]).exclude(encrypted_key=b"")


def pilot_review_key():
    from inspinia.solutions.admin_reviews import read_credential

    lease = pilot_lease()
    if lease is None:
        return ""
    try:
        key_version = UUID(lease.reference.rsplit("|", 1)[-1])
    except ValueError:
        return ""
    return read_credential(pilot_review_configuration().filter(key_version=key_version).first())
