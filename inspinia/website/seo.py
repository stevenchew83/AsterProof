"""Discovery URLs include only intentionally published public content."""

from types import SimpleNamespace
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from .learning import exclude_cutovers
from .learning import note_url
from .learning import public_notes
from .learning import schema_ready
from .models import LibraryArea
from .models import LibraryConcept
from .models import LibraryLecture
from .models import Subject


def public_url(path):
    return settings.PUBLIC_SITE_ORIGIN.rstrip("/") + path


class PublicSitemap(Sitemap):
    def get_urls(self, page=1, site=None, protocol=None):
        origin = urlsplit(settings.PUBLIC_SITE_ORIGIN)
        return super().get_urls(page=page, site=SimpleNamespace(domain=origin.netloc), protocol=origin.scheme)


class StaticSitemap(PublicSitemap):
    def items(self):
        pages = [
            "pages:home",
            "website:library",
            "website:problem_solving",
            "website:solution_preview",
            "website:about",
            "website:contact",
            "website:privacy",
            "website:terms",
        ]
        paths = [reverse(name) for name in pages]
        subjects = set(
            exclude_cutovers(LibraryArea.objects.filter(is_published=True)).values_list("subject", flat=True),
        )
        from inspinia.learning.permissions import module_enabled

        if module_enabled() and schema_ready():
            from inspinia.training.pathways import published_pathways

            subjects.update(public_notes().values_list("document__canonical_area__subject_id", flat=True))
            subjects.update(
                public_notes().values_list(
                    "document__canonical_concept__memberships__area__subject_id",
                    flat=True,
                ),
            )
            subjects.update(
                public_notes().values_list(
                    "revision__concept_links__concept__memberships__area__subject_id",
                    flat=True,
                ),
            )
            subjects.update(published_pathways(public=True).values_list("subject_id", flat=True))
        subjects.intersection_update(Subject.values)
        paths.extend(reverse("website:library_subject", kwargs={"subject": subject}) for subject in sorted(subjects))
        return paths

    def location(self, item):
        return item


class AreaSitemap(PublicSitemap):
    def items(self):
        return exclude_cutovers(LibraryArea.objects.filter(is_published=True)).order_by("pk")

    def lastmod(self, item):
        return item.updated_at


class ConceptSitemap(AreaSitemap):
    def items(self):
        return exclude_cutovers(
            LibraryConcept.objects.filter(is_published=True, area__is_published=True)
            .select_related("area")
            .order_by("pk"),
        )


class LectureSitemap(AreaSitemap):
    def items(self):
        return exclude_cutovers(
            LibraryLecture.objects.filter(
                is_published=True,
                concept__is_published=True,
                concept__area__is_published=True,
            )
            .select_related("concept__area")
            .order_by("pk"),
        )


class LearningNoteSitemap(PublicSitemap):
    def items(self):
        return public_notes().order_by("document_id")

    def location(self, item):
        return note_url(item)

    def lastmod(self, item):
        return item.published_at


class LearningPathwaySitemap(PublicSitemap):
    def items(self):
        from inspinia.learning.permissions import module_enabled
        from inspinia.training.models import LearningPath

        if not module_enabled() or not schema_ready():
            return LearningPath.objects.none()
        from inspinia.training.pathways import published_pathways

        return published_pathways(public=True).order_by("slug")

    def location(self, item):
        return reverse("website:learning_pathway", args=[item.slug])

    def lastmod(self, item):
        return item.current_revision.created_at


SITEMAPS = {
    "pages": StaticSitemap,
    "areas": AreaSitemap,
    "concepts": ConceptSitemap,
    "lectures": LectureSitemap,
    "notes": LearningNoteSitemap,
    "pathways": LearningPathwaySitemap,
}


@require_safe
def robots_view(request):
    return HttpResponse(
        "User-agent: *\nAllow: /\n\nSitemap: " + public_url(reverse("website:sitemap")) + "\n",
        content_type="text/plain; charset=utf-8",
    )


@require_safe
def sitemap_index_view(request):
    locations = []
    for section, sitemap_class in SITEMAPS.items():
        location = public_url(reverse("website:sitemap_section", kwargs={"section": section}))
        locations.append(location)
        locations.extend(f"{location}?p={page}" for page in range(2, sitemap_class().paginator.num_pages + 1))
    return render(request, "website/sitemap_index.xml", {"locations": locations}, content_type="application/xml")


@require_safe
def sitemap_section_view(request, section):
    return sitemap(request, sitemaps=SITEMAPS, section=section, template_name="website/sitemap.xml")
