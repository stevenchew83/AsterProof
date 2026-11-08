"""Public discovery, legacy cutover and admin share one approved content boundary."""

from http import HTTPStatus

import pytest
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse

from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentPublication
from inspinia.learning.models import ContentRevision
from inspinia.learning.models import LegacyContentLink
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueConceptArea
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.training.models import LearningPath
from inspinia.training.models import LearningPathItem
from inspinia.training.models import LearningPathRevision
from inspinia.users.tests.factories import UserFactory
from inspinia.website.learning import note_url
from inspinia.website.models import LibraryArea
from inspinia.website.models import LibraryConcept
from inspinia.website.models import LibraryLecture
from inspinia.website.models import Subject

pytestmark = pytest.mark.django_db


@pytest.fixture
def shared_note(settings):
    settings.LEARNING_MODULE_ENABLED = True
    subject, _created = CatalogueSubject.objects.get_or_create(id="algebra", defaults={"name": "Algebra"})
    area = CatalogueArea.objects.create(
        id="algebra:learning-test-inequalities",
        subject=subject,
        slug="learning-test-inequalities",
        name="Inequalities",
    )
    document = ContentDocument.objects.create(kind="lecture", canonical_area=area, slug="am-gm")
    revision = ContentRevision.objects.create(
        document=document,
        sequence=1,
        title="Approved AM-GM note",
        summary="Recognition, proof and equality cases.",
        body_source="## Reviewed proof\n\nFor $a,b \\geq 0$.",
        source_digest="a" * 64,
    )
    return ContentPublication.objects.create(
        document=document, revision=revision, training_visible=True, public_visible=True,
    )


def legacy_hierarchy():
    area = LibraryArea.objects.create(
        title="Legacy area", subject=Subject.ALGEBRA, is_published=True, body_markdown="OLD AREA BODY",
    )
    concept = LibraryConcept.objects.create(
        title="Legacy concept", area=area, is_published=True, body_markdown="OLD CONCEPT BODY",
    )
    lecture = LibraryLecture.objects.create(
        title="Legacy lecture", concept=concept, is_published=True, body_markdown="OLD LECTURE BODY",
    )
    return area, concept, lecture


def test_home_library_search_and_subject_show_only_current_approved_note(client, shared_note):
    private = ContentDocument.objects.create(kind="standalone")
    ContentDraft.objects.create(
        document=private,
        author=UserFactory(),
        title="Private draft title",
        body_source="PRIVATE SOURCE SHOULD NEVER APPEAR",
    )
    for url in ("/", "/library/", "/library/algebra/", "/library/?q=recognition"):
        response = client.get(url)
        assert response.status_code == HTTPStatus.OK
        body = response.content.decode()
        assert shared_note.revision.title in body
        assert note_url(shared_note) in body
        assert "Private draft title" not in body
        assert "PRIVATE SOURCE SHOULD NEVER APPEAR" not in body
        assert "X-Robots-Tag" not in response or "?q=" in url
    shared_note.public_visible = False
    shared_note.save()
    for url in ("/", "/library/", "/library/algebra/"):
        assert shared_note.revision.title not in client.get(url).content.decode()
    assert client.get(note_url(shared_note)).status_code == HTTPStatus.NOT_FOUND


def test_concept_associated_note_is_discoverable_in_every_canonical_subject(client, shared_note):
    geometry, _created = CatalogueSubject.objects.get_or_create(id="geometry", defaults={"name": "Geometry"})
    area = CatalogueArea.objects.create(
        id="geometry:learning-test-metric", subject=geometry, slug="learning-test-metric", name="Metric",
    )
    concept = CatalogueConcept.objects.create(id="learning-integration-am-gm", name="AM-GM")
    CatalogueConceptArea.objects.create(concept=concept, area=shared_note.document.canonical_area)
    CatalogueConceptArea.objects.create(concept=concept, area=area)
    shared_note.document.canonical_area = None
    shared_note.document.canonical_concept = concept
    shared_note.document.save()
    for subject in ("algebra", "geometry"):
        response = client.get(f"/library/{subject}/")
        assert shared_note.revision.title in response.content.decode()
        assert "X-Robots-Tag" not in response


@pytest.mark.parametrize(("index", "field"), [(0, "area"), (1, "concept"), (2, "lecture")])
def test_legacy_identity_bridges_before_old_publication_flags_and_never_falls_back(
    client,
    shared_note,
    settings,
    index,
    field,
):
    entries = legacy_hierarchy()
    source = entries[index]
    LegacyContentLink.objects.create(
        document=shared_note.document, is_cutover=True, source_fingerprint="a" * 64, **{field: source},
    )
    for entry in entries:
        entry.is_published = False
        entry.save()
    response = client.get(source.get_absolute_url())
    assert response.status_code == HTTPStatus.OK
    assert "Reviewed proof" in response.content.decode()
    assert "OLD " not in response.content.decode()
    shared_note.public_visible = False
    shared_note.save()
    assert client.get(source.get_absolute_url()).status_code == HTTPStatus.NOT_FOUND
    settings.LEARNING_MODULE_ENABLED = False
    assert client.get(source.get_absolute_url()).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("module_enabled", [False, True])
def test_cutover_legacy_sources_stay_out_of_listing_search_and_sitemap(client, shared_note, settings, module_enabled):
    area, concept, lecture = legacy_hierarchy()
    for source, field in ((area, "area"), (concept, "concept"), (lecture, "lecture")):
        LegacyContentLink.objects.create(
            document=shared_note.document, is_cutover=True, source_fingerprint="a" * 64, **{field: source},
        )
    settings.LEARNING_MODULE_ENABLED = module_enabled
    for url in ("/library/", "/library/algebra/", "/library/?q=Legacy"):
        body = client.get(url).content.decode()
        assert "Legacy area" not in body
        assert "Legacy concept" not in body
        assert "Legacy lecture" not in body
    for section, source in (("areas", area), ("concepts", concept), ("lectures", lecture)):
        assert source.get_absolute_url() not in client.get(f"/sitemap-{section}.xml").content.decode()
    assert (note_url(shared_note) in client.get("/sitemap-notes.xml").content.decode()) is module_enabled


def test_foundations_and_subject_pathways_are_publicly_discoverable_only_when_released(client, shared_note, settings):
    path = LearningPath.objects.create(
        slug="foundations", is_foundations=True, training_visible=True, public_visible=True,
    )
    revision = LearningPathRevision.objects.create(
        path=path,
        sequence=1,
        title="Foundations of proof",
        summary="Cross-topic proof methods.",
        source_digest="b" * 64,
    )
    LearningPathItem.objects.create(
        revision=revision,
        item_key="first-proof",
        position=0,
        title="A first proof",
        kind="document",
        document=shared_note.document,
    )
    path.current_revision = revision
    path.save()
    url = reverse("website:learning_pathway", args=[path.slug])
    for location in ("/", "/library/", "/sitemap-pathways.xml"):
        assert url in client.get(location).content.decode()
    assert client.get(url).status_code == HTTPStatus.OK
    path.public_visible = False
    path.save()
    assert url not in client.get("/library/").content.decode()
    assert client.get(url).status_code == HTTPStatus.NOT_FOUND
    settings.LEARNING_MODULE_ENABLED = False
    assert url not in client.get("/sitemap-pathways.xml").content.decode()


def test_mathematical_legacy_admin_is_inspect_only_for_all_entries_when_module_enabled(shared_note, settings):
    request = RequestFactory().get("/admin/")
    request.user = UserFactory(is_staff=True, is_superuser=True)
    entries = legacy_hierarchy()
    for source in entries:
        model_admin = admin.site._registry[type(source)]  # noqa: SLF001 - Inspect the registered admin contract.
        assert model_admin.has_view_permission(request, source)
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request, source)
        assert not model_admin.has_delete_permission(request, source)
        assert not model_admin.get_form(request, source).base_fields
        with pytest.raises(PermissionDenied):
            model_admin.save_model(request, source, None, change=True)
        with pytest.raises(PermissionDenied):
            model_admin.delete_queryset(request, type(source).objects.filter(pk=source.pk))
    LegacyContentLink.objects.create(
        document=shared_note.document, area=entries[0], is_cutover=True, source_fingerprint="a" * 64,
    )
    settings.LEARNING_MODULE_ENABLED = False
    area_admin = admin.site._registry[LibraryArea]  # noqa: SLF001
    assert not area_admin.has_change_permission(request, entries[0])
    assert not area_admin.has_delete_permission(request, entries[0])
    assert admin.site._registry[LibraryLecture].has_change_permission(request, entries[2])  # noqa: SLF001
