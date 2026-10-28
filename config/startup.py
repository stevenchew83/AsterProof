"""Prepare fixed rendering dependencies before a production WSGI worker is ready."""

import logging
from time import perf_counter

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.template.loader import get_template
from django.urls import reverse
from django.utils.translation import get_supported_language_variant
from django.utils.translation import override

logger = logging.getLogger(__name__)

# Include the inherited shell and literal includes: compiling a child alone
# leaves its parents/includes to the first render. Never render user context.
FIRST_REQUEST_TEMPLATES = (
    "base.html",
    "layouts/vertical.html",
    "partials/sidenav.html",
    "partials/sidenav-link.html",
    "partials/topbar.html",
    "partials/footer.html",
    "partials/page-title.html",
    "partials/page-header-intro.html",
    "partials/page-header-stat.html",
    "pages/topic-tag-analytics.html",
    "pages/technique-progress.html",
    "pages/technique-progress-topic.html",
    "pages/partials/concept-progress-bar.html",
)
# One route per shell namespace prepares its reverse resolver without invoking
# a view. Role-specific navigation can then use the same initialized resolver.
FIRST_REQUEST_ROUTES = (
    "pages:topic_tag_dashboard",
    "training:dashboard",
    "users:update",
    "solutions:my_solution_list",
    "problemsets:my_lists",
    "rankings:ranking_table",
)


def prepare_first_request():
    if not getattr(settings, "PREPARE_FIRST_REQUEST", False):
        return
    started = perf_counter()
    # Match LocaleMiddleware's fallback language, including en-us -> en.
    # The override restores the caller's active language when startup finishes.
    with override(get_supported_language_variant(settings.LANGUAGE_CODE)):
        for route in FIRST_REQUEST_ROUTES:
            reverse(route)
        for template in FIRST_REQUEST_TEMPLATES:
            get_template(template)
        # Initialize the configured local manifest storage, without reading
        # user media or fetching asset contents. Later static tags reuse it.
        staticfiles_storage.url("css/app.min.css")
    logger.info(
        "startup_prepared templates=%s routes=%s duration_ms=%.2f",
        len(FIRST_REQUEST_TEMPLATES),
        len(FIRST_REQUEST_ROUTES),
        (perf_counter() - started) * 1000,
    )
