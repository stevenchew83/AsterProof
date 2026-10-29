from http import HTTPStatus

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.urls import reverse
from django.utils.http import urlencode

from inspinia.pages.models import CatalogueConcept
from inspinia.users.tests.factories import UserFactory
from inspinia.website.models import LibraryArea
from inspinia.website.models import LibraryConcept
from inspinia.website.models import LibraryLecture
from inspinia.website.models import NewsletterSubscriber
from inspinia.website.models import Subject

pytestmark = pytest.mark.django_db


@pytest.fixture
def library():
    area = LibraryArea.objects.create(title="Triangle geometry", subject=Subject.GEOMETRY, is_published=True)
    concept = LibraryConcept.objects.create(title="Similar triangles", area=area, is_published=True)
    lecture = LibraryLecture.objects.create(
        title="A first similarity proof",
        concept=concept,
        is_published=True,
        summary="Compare corresponding lengths.",
        body_markdown=r"## The idea" + "\n\n" + r"Use $AB/AC = BD/CE$ and \[x^2+y^2=z^2.\]",
    )
    return area, concept, lecture


@pytest.mark.parametrize(
    "name",
    ["pages:home", "website:problem_solving", "website:about", "website:contact", "website:privacy", "website:terms"],
)
def test_public_pages_have_shared_navigation_and_operator(client, name):
    response = client.get(reverse(name))

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert 'aria-label="Main navigation"' in html
    assert reverse("account_login") in html
    assert reverse("website:library") in html
    assert "Operated by Steven" in html
    if name != "website:problem_solving":
        assert 'name="consent"' in html
    assert 'rel="canonical" href="https://asterproof.com/' in html


@pytest.mark.parametrize(
    "path",
    [
        "/", "/problem-solving/", "/tools/solution-preview/", "/about/", "/contact/", "/privacy/", "/terms/",
        "/library/", "/library/geometry/", "/newsletter/subscribe/",
    ],
)
def test_pending_users_can_browse_public_site_without_opening_workspace_access(client, path):
    client.force_login(UserFactory(is_approved=False))

    assert client.get(path).status_code == HTTPStatus.OK
    assert client.get(reverse("pages:user_activity_dashboard")).url == reverse("users:approval_pending")


def test_subjects_and_empty_library_are_honest(client):
    response = client.get(reverse("website:library"))
    assert "A library taking shape" in response.content.decode()
    for subject in Subject.values:
        url = reverse("website:library_subject", kwargs={"subject": subject})
        assert url in response.content.decode()
        assert client.get(url).status_code == HTTPStatus.OK
    assert client.get("/library/not-a-subject/").status_code == HTTPStatus.NOT_FOUND


def test_problem_solving_walkthrough_is_public_and_uses_an_explicit_example(client):
    response = client.get(reverse("website:problem_solving"))

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert "A first inequality" in html
    assert "Live preview" in html
    assert "Personal progress" in html
    assert "Illustrative data" in html
    assert "Example edits reset when you reload" in html
    assert "Save your proof as a draft, then mark the problem solved" in html
    assert "Normal draft saves leave progress unchanged" in html
    assert f'href="{reverse("website:solution_preview")}">Solution Writer</a>' in html
    assert "New accounts require approval" in html
    assert 'href="https://asterproof.com/problem-solving/"' in html
    assert "Find olympiad problems by topic and MOHS difficulty" in html
    assert "mathjax" in html.lower()
    assert response.context["workspace_url"] == reverse("account_login") + "?" + urlencode(
        {"next": reverse("pages:problem_statement_list")},
    )
    assert client.post(reverse("website:problem_solving")).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert client.get(reverse("pages:problem_statement_list")).status_code == HTTPStatus.FOUND


def test_problem_solving_links_approved_users_to_the_problem_library(client):
    client.force_login(UserFactory(is_approved=True))

    response = client.get(reverse("website:problem_solving"))

    assert response.context["workspace_url"] == reverse("pages:problem_statement_list")


def test_homepage_invites_visitors_to_the_problem_solving_walkthrough(client):
    html = client.get(reverse("pages:home")).content.decode()

    assert f'href="{reverse("website:problem_solving")}">Explore the problem-solving workspace' in html


def test_published_hierarchy_links_and_math_render(client, library):
    area, concept, lecture = library
    for entry in library:
        response = client.get(entry.get_absolute_url())
        assert response.status_code == HTTPStatus.OK
        assert entry.title in response.content.decode()
    assert concept.get_absolute_url() in client.get(reverse("website:library")).content.decode()
    html = client.get(lecture.get_absolute_url()).content.decode()
    assert "<h2>The idea</h2>" in html
    assert r"\[x^2+y^2=z^2.\]" in html
    assert "mathjax" in html.lower()
    assert lecture.get_absolute_url() in client.get(concept.get_absolute_url()).content.decode()
    assert concept.get_absolute_url() in client.get(area.get_absolute_url()).content.decode()


@pytest.mark.parametrize("draft_level", [0, 1, 2])
def test_draft_ancestors_hide_descendants_and_search_results(client, library, draft_level):
    entry = library[draft_level]
    entry.is_published = False
    entry.save()

    for descendant in library[draft_level:]:
        assert client.get(descendant.get_absolute_url()).status_code == HTTPStatus.NOT_FOUND
        search = client.get(reverse("website:library"), {"q": descendant.title})
        assert not search.context["areas"]
        assert not search.context["concepts"]
        assert not search.context["lectures"]


def test_draft_prerequisites_and_catalogue_notes_are_never_published(client, library):
    area, concept, _lecture = library
    draft = LibraryConcept.objects.create(title="Secret prerequisite", area=area)
    concept.prerequisites.add(draft)
    catalogue_concept = CatalogueConcept.objects.create(
        id="website-test-private",
        name="Internal catalogue label",
        description="Private assessment notes",
    )
    concept.catalogue_concept = catalogue_concept
    concept.save()

    html = client.get(concept.get_absolute_url()).content.decode()
    assert draft.title not in html
    assert catalogue_concept.name not in html
    assert catalogue_concept.description not in html
    draft.is_published = True
    draft.save()
    assert draft.get_absolute_url() in client.get(concept.get_absolute_url()).content.decode()


def test_library_sanitizes_html_and_renders_safe_resource_link(client, library):
    lecture = library[2]
    lecture.body_markdown = (
        '<script>alert(1)</script><img src=x onerror="alert(2)">'
        '<a href="javascript:alert(3)" onclick="alert(4)">unsafe</a>\n\n**Valid proof**'
    )
    lecture.resource_url = "https://example.com/lecture.pdf"
    lecture.save()

    html = client.get(lecture.get_absolute_url()).content.decode()
    assert "<script>alert" not in html
    assert "onerror=" not in html
    assert "onclick=" not in html
    assert "javascript:alert" not in html
    assert "<strong>Valid proof</strong>" in html
    assert 'href="https://example.com/lecture.pdf" target="_blank" rel="noopener noreferrer"' in html
    lecture.resource_url = "javascript:alert(1)"
    with pytest.raises(ValidationError):
        lecture.full_clean()


def test_admin_supports_drafts_and_cannot_manually_enrol_newsletter_subscribers(library):
    request = RequestFactory().get("/admin/")
    request.user = UserFactory(is_staff=True, is_superuser=True)
    for entry in library:
        model_admin = admin.site._registry[type(entry)]  # noqa: SLF001
        assert model_admin.has_add_permission(request)
        assert "body_markdown" in model_admin.get_form(request).base_fields
        assert "is_published" in model_admin.list_filter or model_admin.list_filter[-1] == "is_published"
    newsletter_admin = admin.site._registry[NewsletterSubscriber]  # noqa: SLF001
    assert not newsletter_admin.has_add_permission(request)
    assert "status" in newsletter_admin.readonly_fields
