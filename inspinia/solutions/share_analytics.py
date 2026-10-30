"""Anonymous aggregate readership, kept separate from the shared proof."""

import logging

from django.db import DatabaseError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from inspinia.solutions.models import SolutionPublicShare
from inspinia.solutions.models import SolutionShareDailyViews
from inspinia.users.roles import user_has_admin_role

logger = logging.getLogger(__name__)

# Best-effort filtering, not a claim that every remaining request is a person.
CRAWLER_MARKERS = (
    "bot", "crawler", "spider", "whatsapp", "facebookexternalhit", "facebot",
    "twitter", "slack", "discord", "telegram", "linkedin", "pinterest",
    "preview", "curl/", "wget/", "python-requests", "httpx/", "headless",
)


def record_public_view(request, share):
    """Count successful GET page opens; repeat visits count, previews do not."""
    agent = request.headers.get("User-Agent", "").lower()
    purpose = " ".join(request.headers.get(name, "") for name in ("Purpose", "Sec-Purpose", "X-Purpose")).lower()
    if request.method != "GET" or not agent or "prefetch" in purpose:
        return
    if any(marker in agent for marker in CRAWLER_MARKERS):
        return
    user = request.user
    if user.is_authenticated and (user_has_admin_role(user) or user.pk == share.owner_id):
        return
    try:
        # Lock the share so a concurrent revocation/deletion cannot leave a new
        # counter for a no-longer-active share. F() avoids lost concurrent opens.
        with transaction.atomic():
            active = SolutionPublicShare.objects.select_for_update().filter(pk=share.pk, is_active=True).exists()
            if not active:
                return
            counter, _ = SolutionShareDailyViews.objects.get_or_create(share_id=share.pk, day=timezone.localdate())
            SolutionShareDailyViews.objects.filter(pk=counter.pk).update(views=F("views") + 1)
    except DatabaseError:
        # Analytics must never make a readable solution unavailable. Do not log
        # tokens, request headers, proof text, or database exception parameters.
        logger.warning("Could not record an aggregate public solution view.")
