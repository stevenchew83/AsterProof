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

from .models import LibraryArea
from .models import LibraryConcept
from .models import LibraryLecture


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
        subjects = LibraryArea.objects.filter(is_published=True).order_by("subject").values_list("subject", flat=True)
        paths.extend(
            reverse("website:library_subject", kwargs={"subject": subject}) for subject in subjects.distinct()
        )
        return paths

    def location(self, item):
        return item


class AreaSitemap(PublicSitemap):
    def items(self):
        return LibraryArea.objects.filter(is_published=True).order_by("pk")

    def lastmod(self, item):
        return item.updated_at


class ConceptSitemap(AreaSitemap):
    def items(self):
        return (
            LibraryConcept.objects.filter(is_published=True, area__is_published=True)
            .select_related("area")
            .order_by("pk")
        )


class LectureSitemap(AreaSitemap):
    def items(self):
        return (
            LibraryLecture.objects.filter(
                is_published=True,
                concept__is_published=True,
                concept__area__is_published=True,
            )
            .select_related("concept__area")
            .order_by("pk")
        )


SITEMAPS = {"pages": StaticSitemap, "areas": AreaSitemap, "concepts": ConceptSitemap, "lectures": LectureSitemap}


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
