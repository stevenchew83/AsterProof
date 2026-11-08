"""Real request-chain checks for the shared authoring and reading interfaces."""

import json
import uuid
from http import HTTPStatus

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import Client
from django.urls import reverse

from inspinia.learning.drafts import create_draft
from inspinia.learning.drafts import editor_context
from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentIssue
from inspinia.learning.models import ContentPublication
from inspinia.learning.models import ContentRevision
from inspinia.learning.publication import publish_proposal
from inspinia.learning.publication import review_context
from inspinia.learning.publication import review_proposal
from inspinia.learning.publication import submit_draft
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueConceptArea
from inspinia.pages.catalogue_models import CatalogueSubject
from inspinia.training import test_pathway_fixtures
from inspinia.users.tests.factories import UserFactory

private_content_packs = test_pathway_fixtures.private_content_packs

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace(settings):
    settings.LEARNING_MODULE_ENABLED = True
    settings.LEARNING_CONTRIBUTIONS_ENABLED = True
    settings.LEARNING_PUBLICATION_ENABLED = True
    settings.LEARNING_AGREEMENT_VERSION = "synthetic-web-v1"
    settings.LEARNING_AGREEMENT_APPROVED = True
    author, publisher = UserFactory(), UserFactory()
    settings.LEARNING_PUBLISHER_USER_ID = publisher.pk
    subject, _ = CatalogueSubject.objects.get_or_create(id="algebra", defaults={"name": "Algebra"})
    area, _ = CatalogueArea.objects.get_or_create(
        id="Algebra:inequalities",
        defaults={"name": "Inequalities", "slug": "inequalities", "subject": subject},
    )
    concept, _ = CatalogueConcept.objects.get_or_create(id="web-amgm", defaults={"name": "Web AM-GM"})
    CatalogueConceptArea.objects.get_or_create(area=area, concept=concept)
    return author, publisher, area, concept


def draft(workspace):
    author, _publisher, area, concept = workspace
    return create_draft(
        user=author,
        title="A square proves AM-GM",
        area_id=area.pk,
        source="## Statement\nFor $a,b>0$, $a+b \\geq 2\\sqrt{ab}$.\n\nEquality holds exactly when $a=b$.",
        metadata={"concepts": [{"id": concept.pk, "role": "primary"}]},
    )


def publish(workspace, item=None, *, public=True):
    author, publisher, *_ = workspace
    proposal = submit_draft(
        draft=item or draft(workspace),
        user=author,
        agreement_version="synthetic-web-v1",
        rights_confirmed=True,
        public_credit="Opt-in author",
        declaration={"editorial_changes_allowed": True},
    )
    proposal = review_proposal(proposal=proposal, user=publisher, action="approve", context=review_context(proposal))
    return publish_proposal(
        proposal=proposal,
        user=publisher,
        context=review_context(proposal),
        expected_version=0,
        public=public,
    )


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def test_all_workspace_pages_render_and_gets_do_not_create_learning_rows(workspace):
    author, publisher, area, concept = workspace
    item = draft(workspace)
    publication = publish(workspace, item)
    before = [model.objects.count() for model in (ContentDocument, ContentDraft, ContentRevision, ContentPublication)]
    client = client_for(author)
    urls = [
        reverse("learning:learn"),
        reverse("learning:explore"),
        reverse("learning:area", args=[area.pk]),
        reverse("learning:concept", args=[concept.pk]),
        reverse("learning:my_drafts"),
        reverse("learning:edit", args=[item.pk]),
        reverse("learning:read", args=[publication.document_id]),
        reverse("learning:report", args=[publication.document_id]),
        reverse("learning:target_report", args=["classification", concept.pk]),
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == HTTPStatus.OK, (url, response.status_code)
    assert [
        model.objects.count() for model in (ContentDocument, ContentDraft, ContentRevision, ContentPublication)
    ] == before
    owner = client_for(publisher)
    for url in (
        reverse("learning:review_queue"),
        reverse("learning:pathway_editor"),
        reverse("learning:packs"),
        reverse("learning:issues"),
        reverse("learning:prerequisites"),
    ):
        assert owner.get(url).status_code == HTTPStatus.OK, url


def test_editor_save_is_private_versioned_and_csrf_protected(workspace):
    author = workspace[0]
    item = draft(workspace)
    url = reverse("learning:draft_save", args=[item.pk])
    data = {
        "title": item.title,
        "summary": "",
        "body_source": "Private improved proof",
        "metadata": item.metadata,
        "edit_version": item.edit_version,
        "editor_context": editor_context(item, author),
        "operation_id": str(uuid.uuid4()),
    }
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(author)
    assert (
        csrf_client.post(url, data=json.dumps(data), content_type="application/json").status_code
        == HTTPStatus.FORBIDDEN
    )
    client = client_for(author)
    response = client.post(url, data=json.dumps(data), content_type="application/json")
    assert response.status_code == HTTPStatus.OK, response.content
    item.refresh_from_db()
    assert item.body_source == data["body_source"]
    assert ContentRevision.objects.count() == 0
    assert (
        client.post(
            url,
            data=json.dumps({**data, "operation_id": str(uuid.uuid4())}),
            content_type="application/json",
        ).status_code
        == HTTPStatus.CONFLICT
    )
    stranger = client_for(UserFactory(role="admin", is_superuser=True))
    assert stranger.get(reverse("learning:edit", args=[item.pk])).status_code == HTTPStatus.NOT_FOUND
    assert (
        stranger.post(url, data=json.dumps(data), content_type="application/json").status_code == HTTPStatus.NOT_FOUND
    )


def test_public_and_training_read_the_same_approved_revision(workspace):
    publication = publish(workspace)
    private = draft(workspace)
    client = Client()
    url = reverse("website:learning_note", args=[publication.document_id, publication.document.slug])
    response = client.get(url)
    assert response.status_code == HTTPStatus.OK
    assert "Equality holds exactly" in response.content.decode()
    assert "Opt-in author" in response.content.decode()
    assert "no-store" in response["Cache-Control"]
    assert (
        client.get(reverse("website:learning_note", args=[private.document_id, "private"])).status_code
        == HTTPStatus.NOT_FOUND
    )
    training = client_for(workspace[0]).get(reverse("learning:read", args=[publication.document_id]))
    assert training.context["revision"].pk == response.context["revision"].pk
    assert training.context["rendered_content"] == response.context["rendered_content"]
    assert "website-math.js" not in response.content.decode()


def test_proposal_and_publisher_routes_do_not_expand_admin_authority(workspace):
    item = draft(workspace)
    author = workspace[0]
    proposal = submit_draft(draft=item, user=author, agreement_version="synthetic-web-v1", rights_confirmed=True)
    admin = client_for(UserFactory(role="admin", is_superuser=True))
    assert admin.get(reverse("learning:review_queue")).status_code == HTTPStatus.FORBIDDEN
    assert admin.get(reverse("learning:proposal", args=[proposal.pk])).status_code == HTTPStatus.NOT_FOUND
    response = client_for(workspace[1]).get(reverse("learning:proposal", args=[proposal.pk]))
    assert response.status_code == HTTPStatus.OK
    assert "Source changes" in response.content.decode()


def test_canonical_filter_preserves_area_and_no_duplicate_concepts(workspace):
    publish(workspace)
    client = client_for(workspace[0])
    response = client.get(
        reverse("learning:explore"),
        {"area": workspace[2].pk, "availability": "available", "q": "Web"},
    )
    assert response.status_code == HTTPStatus.OK
    assert [row.pk for row in response.context["page"]] == [workspace[3].pk]
    assert "area=Algebra%3Ainequalities" in response.context["filter_query"]


def test_classification_reports_wait_for_review(workspace):
    author, publisher, _area, concept = workspace
    client = client_for(author)
    url = reverse("learning:target_report", args=["classification", concept.pk])
    response = client.get(url)
    token = response.context["form"].initial["token"]
    response = client.post(
        url,
        {"token": token, "description": "This theorem also supports optimization.", "website": ""},
    )
    assert response.status_code == HTTPStatus.FOUND
    assert ContentIssue.objects.filter(kind="classification", status="open").count() == 1
    assert client_for(author).get(reverse("learning:issues")).status_code == HTTPStatus.FORBIDDEN
    assert client_for(publisher).get(reverse("learning:issues")).status_code == HTTPStatus.OK


def test_old_material_admin_and_direct_post_cannot_publish(workspace):
    from inspinia.training.admin import MaterialAdmin
    from inspinia.training.models import Material

    admin = UserFactory(role="admin", is_staff=True, is_superuser=True)
    request = type("Request", (), {"user": admin})()
    model_admin = MaterialAdmin(Material, AdminSite())
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    client = client_for(admin)
    response = client.post(reverse("training:trainer_materials"), {"title": "bypass"})
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not Material.objects.filter(title="bypass").exists()


def test_failed_submission_keeps_saved_text_and_allows_corrected_form_retry(workspace):
    author = workspace[0]
    item = draft(workspace)
    client = client_for(author)
    url = reverse("learning:edit", args=[item.pk])
    values = {
        "title": item.title,
        "summary": "",
        "body_source": "An improved, original proof.",
        "metadata": json.dumps(item.metadata),
        "edit_version": item.edit_version,
        "editor_context": editor_context(item, author),
        "operation_id": str(uuid.uuid4()),
        "action": "submit",
    }
    failed = client.post(url, values)
    assert failed.status_code == HTTPStatus.OK
    item.refresh_from_db()
    assert item.body_source == values["body_source"]
    form = failed.context["form"]
    assert form["edit_version"].value() == item.edit_version
    corrected = dict(
        values,
        rights_confirmed="on",
        edit_version=form["edit_version"].value(),
        editor_context=form["editor_context"].value(),
        operation_id=form["operation_id"].value(),
    )
    response = client.post(url, corrected)
    assert response.status_code == HTTPStatus.FOUND
    assert "/proposals/" in response.url


def test_publisher_can_load_pathway_pack_and_submitted_history(workspace, private_content_packs):
    publication = publish(workspace)
    owner = client_for(workspace[1])
    response = owner.get(reverse("learning:pathway_editor"), {"pack": "inequalities_pilot_v1"})
    assert response.status_code == HTTPStatus.OK
    assert response.context["template_status"]["missing"]
    assert "None" not in response.context["form"]["slug"].value()
    history = owner.get(reverse("learning:history", args=[publication.document_id]))
    assert history.status_code == HTTPStatus.OK
    assert publication.revision in history.context["revisions"]


def test_prerequisite_filter_never_uses_stale_graph(workspace):
    from inspinia.pages.catalogue_models import CatalogueState
    from inspinia.pages.prerequisite_models import PrerequisiteGraphState

    marker, _ = CatalogueState.objects.get_or_create(pk=1)
    PrerequisiteGraphState.objects.update_or_create(
        pk=1,
        defaults={
            "is_valid": True,
            "validated_catalogue_revision": marker.source_revision,
            "snapshot": [["am-gm", workspace[3].pk]],
        },
    )
    client = client_for(workspace[0])
    response = client.get(reverse("learning:explore"), {"q": "Web", "prerequisites": "has"})
    assert response.context["page"].paginator.count == 1
    marker.source_revision += 1
    marker.save(update_fields=["source_revision"])
    for mode in ("has", "none"):
        response = client.get(reverse("learning:explore"), {"q": "Web", "prerequisites": mode})
        assert not response.context["prerequisite_available"]
        assert response.context["page"].paginator.count == 0


def test_reading_omits_only_duplicate_document_heading(workspace):
    item = draft(workspace)
    item.body_source = f"# {item.title}\n\n## Proof\n\nThe retained mathematical body."
    item.save(update_fields=["body_source"])
    publication = publish(workspace, item)
    response = Client().get(
        reverse("website:learning_note", args=[publication.document_id, publication.document.slug]),
    )
    assert response.status_code == HTTPStatus.OK
    assert "<h1>" not in response.context["rendered_content"]
    assert "<h2>Proof</h2>" in response.context["rendered_content"]
    publication.revision.refresh_from_db()
    assert publication.revision.body_source.startswith(f"# {item.title}")


def test_public_report_intake_can_close_without_breaking_reader(workspace, settings):
    publication = publish(workspace)
    settings.LEARNING_CONTRIBUTIONS_ENABLED = False
    response = Client().get(reverse("website:learning_report", args=[publication.document_id]))
    assert response.status_code == HTTPStatus.OK
    assert "Report intake is currently closed" in response.content.decode()
    assert "csrfmiddlewaretoken" not in response.content.decode()
    assert (
        Client()
        .get(reverse("website:learning_note", args=[publication.document_id, publication.document.slug]))
        .status_code
        == HTTPStatus.OK
    )


def test_archiving_from_my_notes_retains_source_and_publication(workspace):
    item = draft(workspace)
    publication = publish(workspace, item)
    client = client_for(workspace[0])
    listing = client.get(reverse("learning:my_drafts"))
    assert f"Archive {item.title}" in listing.content.decode()
    response = client.post(
        reverse("learning:archive", args=[item.pk]),
        {"edit_version": item.edit_version, "action": "archive"},
    )
    assert response.status_code == HTTPStatus.FOUND
    item.refresh_from_db()
    assert item.is_archived
    assert item.body_source
    assert client.get(reverse("learning:read", args=[publication.document_id])).status_code == HTTPStatus.OK
    response = client.get(reverse("learning:my_drafts"))
    assert item in response.context["archived_drafts"]
    client.post(reverse("learning:archive", args=[item.pk]), {"edit_version": item.edit_version, "action": "reopen"})
    item.refresh_from_db()
    assert not item.is_archived
