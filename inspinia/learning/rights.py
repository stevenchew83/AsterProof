"""Revision-bound publication permission; public availability is not an open licence."""

from django.conf import settings

from inspinia.learning.models import ContributorPermission
from inspinia.learning.revisions import LearningError
from inspinia.learning.revisions import LearningUnavailable

CREDIT_LIMIT = 180
SOURCE_CREDIT_LIMIT = 4000


def validate_agreement(version):
    current = getattr(settings, "LEARNING_AGREEMENT_VERSION", "")
    if not current or not getattr(settings, "LEARNING_AGREEMENT_APPROVED", False):
        message = "Contribution submission is closed until the publication agreement is reviewed."
        raise LearningUnavailable(message)
    if not isinstance(version, str) or version != current:
        message = "Review and accept the current contributor agreement before submitting."
        raise LearningError(message)


def grant_permission(*, revision, user, agreement_version, rights_confirmed, public_credit="", declaration=None):  # noqa: PLR0913 - Explicit domain action and validation boundary.
    validate_agreement(agreement_version)
    if rights_confirmed is not True:
        message = "Confirm that you have permission to submit this writing and its illustrations."
        raise LearningError(message)
    if not isinstance(public_credit, str) or len(public_credit) > CREDIT_LIMIT:
        message = "Keep the optional public credit within 180 characters."
        raise LearningError(message)
    from inspinia.learning.rendering import validate_learning_source

    validate_learning_source(public_credit)
    if revision.author_id != user.pk:
        message = "Only the revision's author can grant permission for it."
        raise LearningError(message)
    declaration = declaration or {}
    if not isinstance(declaration, dict) or set(declaration) - {
        "original_or_authorised",
        "editorial_changes_allowed",
        "sources",
    }:
        message = "Invalid contributor permission declaration."
        raise LearningError(message)
    sources = declaration.get("sources", "")
    if not isinstance(sources, str) or len(sources) > SOURCE_CREDIT_LIMIT:
        message = "Keep source-permission information within 4,000 characters."
        raise LearningError(message)
    validate_learning_source(sources)
    declaration = {
        "original_or_authorised": True,
        "sources": sources,
        "editorial_changes_allowed": declaration.get("editorial_changes_allowed") is True,
    }
    existing = ContributorPermission.objects.filter(revision=revision).first()
    if existing:
        if (
            existing.contributor_id != user.pk
            or existing.source_digest != revision.source_digest
            or existing.agreement_version != agreement_version
            or existing.public_credit != public_credit.strip()
            or existing.rights_declaration != declaration
        ):
            message = "This checkpoint already has different permission evidence. Save a new checkpoint."
            raise LearningError(message)
        return existing
    return ContributorPermission.objects.create(
        revision=revision,
        contributor=user,
        agreement_version=agreement_version,
        source_digest=revision.source_digest,
        public_credit=public_credit.strip(),
        rights_declaration=declaration,
    )


def permission_evidence(revision):
    permission = ContributorPermission.objects.filter(revision=revision).first()
    if permission is None or permission.source_digest != revision.source_digest:
        message = "This revision needs its author's exact publication permission."
        raise LearningError(message)
    evidence = {
        "id": permission.pk,
        "digest": permission.source_digest,
        "agreement": permission.agreement_version,
        "credit": permission.public_credit,
        "declaration": permission.rights_declaration,
        "contributor": permission.contributor_id,
    }
    base = revision.base_revision
    if base and base.author_id != revision.author_id and base.source_digest != revision.source_digest:
        original = ContributorPermission.objects.filter(revision=base).first()
        if original is None or original.rights_declaration.get("editorial_changes_allowed") is not True:
            message = (
                "The original author's permission does not yet cover editorial changes. "
                "Return this proposal for permission."
            )
            raise LearningError(message)
        evidence["base_permission"] = {
            "id": original.pk,
            "digest": original.source_digest,
            "declaration": original.rights_declaration,
        }
    return evidence
