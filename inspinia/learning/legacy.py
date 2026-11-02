"""Verified legacy transitions preserve old identities and never infer a public release."""

from django.conf import settings
from django.db import transaction

from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentPublication
from inspinia.learning.models import LegacyContentLink
from inspinia.learning.permissions import require_publisher
from inspinia.learning.revisions import LearningConflict
from inspinia.learning.revisions import LearningError
from inspinia.learning.revisions import digest


def source_fingerprint(source):
    # Private material is hashed for comparison, never exported as an audit payload.
    fields = ["pk", "title", "slug", "is_published"]
    if hasattr(source, "content_markdown"):
        fields += ["content_markdown", "subtopic_id"]
    else:
        fields += ["body_markdown", "summary", "order"]
        fields += [
            name
            for name in (
                "subject",
                "area_id",
                "concept_id",
                "attribution",
                "resource_url",
                "catalogue_area_id",
                "catalogue_concept_id",
            )
            if hasattr(source, name)
        ]
    return digest({key: getattr(source, key) for key in fields})


def _protect_lecture_announcements(source, source_field):
    """An ancestor transition has the same distribution boundary as a lecture."""
    from inspinia.website.models import NewsletterCampaign
    from inspinia.website.models import NewsletterLectureNotice

    filters = {
        "lecture": {"lecture": source},
        "concept": {"lecture__concept": source},
        "area": {"lecture__concept__area": source},
    }[source_field]
    query = NewsletterLectureNotice.objects.filter(**filters)
    campaign_ids = list(query.exclude(campaign_id=None).values_list("campaign_id", flat=True))
    campaigns = {
        campaign.pk: campaign
        for campaign in NewsletterCampaign.objects.select_for_update().filter(pk__in=campaign_ids).order_by("pk")
    }
    notices = list(query.select_for_update().order_by("pk"))
    # Unknown or in-flight states must be reconciled; mapping never cancels mail.
    if any(
        notice.campaign_id
        and (
            notice.campaign_id not in campaigns
            or campaigns[notice.campaign_id].status != NewsletterCampaign.Status.COMPLETED
        )
        for notice in notices
    ):
        message = "Reconcile this source's existing lecture campaigns before transition; no delivery was cancelled."
        raise LearningConflict(message)
    for notice in notices:
        if notice.status == NewsletterLectureNotice.Status.PENDING:
            notice.status = NewsletterLectureNotice.Status.EXCLUDED
            notice.save(update_fields=["status"])


@transaction.atomic
def link_legacy(*, user, document, source, expected_fingerprint, cutover=False):  # noqa: C901 - Explicit domain action and validation boundary.
    require_publisher(user)
    model = source._meta.label_lower  # noqa: SLF001 - Django model type metadata.
    source_field = {
        "training.material": "material",
        "website.libraryarea": "area",
        "website.libraryconcept": "concept",
        "website.librarylecture": "lecture",
    }.get(model)
    if source_field is None:
        message = "This legacy source type is not supported."
        raise LearningError(message)
    # Newsletter discovery holds this same policy lock. Acquire it before document locks.
    if source_field != "material":
        from inspinia.website.models import NewsletterAutomation

        policy, _created = NewsletterAutomation.objects.get_or_create(pk=1)
        NewsletterAutomation.objects.select_for_update().get(pk=policy.pk)
    document = ContentDocument.objects.select_for_update().get(pk=document.pk)
    source = source.__class__.objects.select_for_update().get(pk=source.pk)
    if source_fingerprint(source) != expected_fingerprint:
        message = "The legacy source changed after mapping review."
        raise LearningConflict(message)
    if cutover:
        if not getattr(settings, "LEARNING_PUBLICATION_ENABLED", False):
            message = "Legacy cutover is disabled until publication readiness is verified."
            raise LearningError(message)
        publication = ContentPublication.objects.get(document=document)
        if not publication.training_visible or not publication.revision_id:
            message = "Publish the reviewed shared revision before cutting over its legacy reader."
            raise LearningError(message)
        if getattr(source, "is_published", False) and source_field != "material" and not publication.public_visible:
            message = "A current public legacy page needs an explicitly public approved replacement."
            raise LearningError(message)
    if source_field != "material":
        _protect_lecture_announcements(source, source_field)
    link = LegacyContentLink.objects.select_for_update().filter(**{source_field: source}).first()
    if link:
        if link.document_id != document.pk:
            message = "This source already has a different reviewed shared identity."
            raise LearningConflict(message)
        if link.source_fingerprint != expected_fingerprint:
            message = "Review a new mapping before changing its source fingerprint."
            raise LearningConflict(message)
        if cutover and not link.is_cutover:
            link.is_cutover = True
            link.reviewed_by = user
            link.save(update_fields=["is_cutover", "reviewed_by"])
        return link
    return LegacyContentLink.objects.create(
        document=document,
        source_fingerprint=expected_fingerprint,
        is_cutover=cutover,
        reviewed_by=user,
        **{source_field: source},
    )


def legacy_publication(source):
    """Return (is_cutover, publication); callers must never fall back after cutover."""
    try:
        link = source.learning_link
    except LegacyContentLink.DoesNotExist:
        return False, None
    if not link.is_cutover:
        return False, None
    return True, ContentPublication.objects.select_related("revision", "document").get(document_id=link.document_id)
