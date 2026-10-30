import re
from html import escape
from http import HTTPStatus
from xml.etree import ElementTree as ET

import pytest
from django.urls import reverse

from inspinia.users.tests.factories import UserFactory
from inspinia.website.models import LibraryArea
from inspinia.website.models import LibraryConcept
from inspinia.website.models import LibraryLecture
from inspinia.website.models import Subject
from inspinia.website.seo import PublicSitemap

pytestmark = pytest.mark.django_db
ORIGIN = "https://asterproof.com"


def locations(response):
    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "application/xml"
    # Application-generated XML contains no untrusted entities.
    root = ET.fromstring(response.content)  # noqa: S314
    return {node.text for node in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")}


def test_public_pages_have_unique_descriptions_and_complete_social_metadata(client):
    paths = [
        "/",
        "/library/",
        "/about/",
        "/contact/",
        "/privacy/",
        "/terms/",
        "/problem-solving/",
        "/tools/solution-preview/",
    ]
    paths.extend(reverse("website:library_subject", kwargs={"subject": subject}) for subject in Subject.values)
    descriptions = set()
    for path in paths:
        response = client.get(path)
        html = response.content.decode()
        description = response.context["page_description"]
        assert description not in descriptions
        descriptions.add(description)
        assert f'name="description" content="{escape(description, quote=True)}"' in html
        assert f'property="og:description" content="{escape(description, quote=True)}"' in html
        assert 'name="twitter:card" content="summary_large_image"' in html
        assert f'property="og:image" content="{ORIGIN}/static/images/asterproof-social.png"' in html
    assert "Olympiad Mathematics &amp; Solution Writer | AsterProof" in client.get("/").content.decode()


def test_public_pages_load_only_the_public_asset_bundle(client):
    for path in ("/", "/library/", "/tools/solution-preview/", "/problem-solving/"):
        html = client.get(path).content.decode()
        assert "css/public-site.min.css" in html
        for asset in ("css/app.min.css", "css/vendors.min.css", "js/vendors.min.js", "js/app.js", "js/config.js"):
            assert asset not in html
    homepage = client.get("/").content.decode()
    assert 'data-geometry-src="/static/js/website-geometry.bundle.js"' in homepage
    scripts = re.findall(r'<script\b[^>]*\ssrc="([^"]+)"', homepage)
    assert "/static/js/website-geometry.bundle.js" not in scripts
    assert "data-lazy-math" in homepage
    assert not any("cdn.jsdelivr.net/npm/mathjax" in src for src in scripts)
    assert "data-lazy-math" not in client.get("/tools/solution-preview/").content.decode()


def test_empty_subjects_and_search_results_stay_accessible_without_indexing(client):
    path = reverse("website:library_subject", kwargs={"subject": Subject.ALGEBRA})
    response = client.get(path)
    assert response.status_code == HTTPStatus.OK
    assert response["X-Robots-Tag"] == "noindex,follow"
    assert 'name="robots" content="noindex,follow"' in response.content.decode()
    LibraryArea.objects.create(title="Inequalities", subject=Subject.ALGEBRA, is_published=True)
    assert "X-Robots-Tag" not in client.get(path)
    assert client.get("/library/", {"q": "inequalities"})["X-Robots-Tag"] == "noindex,follow"
    assert "X-Robots-Tag" not in client.get("/library/")


def test_editorial_metadata_uses_each_summary_and_safe_fallbacks(client):
    area = LibraryArea.objects.create(title="Triangle geometry", subject=Subject.GEOMETRY, is_published=True)
    concept = LibraryConcept.objects.create(
        title="Similarity", area=area, is_published=True, summary='Ratios & "angles".',
    )
    lecture = LibraryLecture.objects.create(
        title="First proof", concept=concept, is_published=True, summary="Compare lengths.",
    )
    for entry in (area, concept, lecture):
        response = client.get(entry.get_absolute_url())
        description = response.context["page_description"]
        assert entry.summary in description if entry.summary else entry.title in description
        assert f'name="description" content="{escape(description, quote=True)}"' in response.content.decode()


def test_robots_and_sitemaps_use_configured_origin_instead_of_request_host(client, settings):
    settings.PUBLIC_SITE_ORIGIN = "https://canonical.example"
    robots = client.get(reverse("website:robots"))
    assert robots["Content-Type"].startswith("text/plain")
    assert "Sitemap: https://canonical.example/sitemap.xml" in robots.content.decode()
    index = locations(client.get(reverse("website:sitemap")))
    assert index == {
        f"https://canonical.example/sitemap-{section}.xml" for section in ("pages", "areas", "concepts", "lectures")
    }
    pages = locations(client.get(reverse("website:sitemap_section", kwargs={"section": "pages"})))
    assert "https://canonical.example/" in pages
    assert all(url.startswith("https://canonical.example/") for url in pages)
    assert not any(
        "accounts/" in url or "newsletter/" in url or "?" in url or "/library/algebra/" in url for url in pages
    )


@pytest.mark.parametrize("draft_level", [None, 0, 1, 2])
def test_sitemap_never_discloses_drafts_or_descendants_of_drafts(client, draft_level):
    area = LibraryArea.objects.create(title="Geometry", subject=Subject.GEOMETRY, is_published=True)
    concept = LibraryConcept.objects.create(title="Similarity", area=area, is_published=True)
    lecture = LibraryLecture.objects.create(title="First proof", concept=concept, is_published=True)
    entries = [area, concept, lecture]
    if draft_level is not None:
        entries[draft_level].is_published = False
        entries[draft_level].save()
    for index, (section, entry) in enumerate(zip(("areas", "concepts", "lectures"), entries, strict=True)):
        urls = locations(client.get(reverse("website:sitemap_section", kwargs={"section": section})))
        assert (ORIGIN + entry.get_absolute_url() in urls) == (draft_level is None or index < draft_level)
    pages = locations(client.get("/sitemap-pages.xml"))
    assert (ORIGIN + "/library/geometry/" in pages) == (draft_level != 0)


def test_sitemap_index_includes_paginated_sections(client, monkeypatch):
    monkeypatch.setattr(PublicSitemap, "limit", 2)
    index = locations(client.get("/sitemap.xml"))
    assert ORIGIN + "/sitemap-pages.xml?p=2" in index
    first = locations(client.get("/sitemap-pages.xml"))
    second = locations(client.get("/sitemap-pages.xml", {"p": 2}))
    assert len(first) == len(second) == PublicSitemap.limit
    assert first.isdisjoint(second)
    assert client.get("/sitemap-pages.xml", {"p": 999}).status_code == HTTPStatus.NOT_FOUND
    assert client.get("/sitemap-private.xml").status_code == HTTPStatus.NOT_FOUND


def test_pending_accounts_can_read_discovery_files_without_opening_workspace_access(client):
    client.force_login(UserFactory(is_approved=False))
    for path in (
        "/robots.txt",
        "/sitemap.xml",
        "/sitemap-pages.xml",
        "/sitemap-areas.xml",
        "/sitemap-concepts.xml",
        "/sitemap-lectures.xml",
    ):
        assert client.get(path).status_code == HTTPStatus.OK
        assert client.head(path).status_code == HTTPStatus.OK
        assert client.post(path).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert client.get(reverse("pages:user_activity_dashboard")).url == reverse("users:approval_pending")
