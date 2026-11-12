# ruff: noqa: PLR2004 -- Fixture sizes and exact milestone counts are intentional assertions.
import uuid
from http import HTTPStatus

import pytest
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.urls import reverse

from inspinia.learning.drafts import checkpoint_draft
from inspinia.learning.drafts import create_draft
from inspinia.learning.models import ContentPublication
from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.training.models import Material
from inspinia.training.models import MaterialCompletion
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic
from inspinia.training.pathway_models import LearningPathItem
from inspinia.training.pathway_models import LearningPathRevision
from inspinia.training.pathway_models import PathReading
from inspinia.training.pathways import mark_read
from inspinia.training.pathways import path_context
from inspinia.training.pathways import pathway_edit_payload
from inspinia.training.pathways import pathway_preview
from inspinia.training.pathways import publication_impact
from inspinia.training.pathways import save_pathway
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def curriculum(settings):
    settings.LEARNING_MODULE_ENABLED = True
    settings.LEARNING_CONTRIBUTIONS_ENABLED = True
    settings.LEARNING_PUBLICATION_ENABLED = True
    publisher = UserFactory()
    learner = UserFactory()
    settings.LEARNING_PUBLISHER_USER_ID = publisher.pk
    area = CatalogueArea.objects.get(pk="Algebra:inequalities")
    draft = create_draft(
        user=publisher,
        area_id=area.pk,
        title="Synthetic AM-GM",
        source="For $a,b>0$, a nonnegative square proves $a+b\\geq 2\\sqrt{ab}$.",
    )
    revision = checkpoint_draft(draft=draft, user=publisher)
    publication = ContentPublication.objects.get(document=draft.document)
    # A fixture publication isolates curriculum behavior from the separately tested review workflow.
    publication.revision = revision
    publication.version = 1
    publication.training_visible = True
    publication.public_visible = True
    publication.save()
    return publisher, learner, publication


def path_data(publication, **overrides):
    values = {
        "slug": "synthetic-inequalities",
        "title": "Synthetic inequalities",
        "area_id": "Algebra:inequalities",
        "expected_version": 0,
        "items": [
            {"key": "amgm", "title": "Read AM-GM", "kind": "document", "document_id": str(publication.document_id)},
        ],
    }
    values.update(overrides)
    return values


def release(user, data):
    preview = pathway_preview(user=user, data=data)
    return save_pathway(user=user, context=preview["context"], **data)


def test_exact_review_context_and_idempotent_retry(curriculum):
    publisher, _learner, publication = curriculum
    data = path_data(publication)
    preview = pathway_preview(user=publisher, data=data)
    path = save_pathway(user=publisher, context=preview["context"], **data)
    repeated = save_pathway(user=publisher, context=preview["context"], **data)
    assert path.pk == repeated.pk
    assert path.version == 1
    assert LearningPathRevision.objects.count() == 1
    assert path.current_revision.snapshot["slug"] == data["slug"]
    assert publication_impact(publication.document)[0]["revision_id"] == str(path.current_revision_id)
    with pytest.raises(ValidationError):
        save_pathway(user=publisher, context=preview["context"], **{**data, "slug": "substituted-slug"})


def test_changed_linked_publication_or_catalogue_requires_fresh_review(curriculum):
    publisher, _learner, publication = curriculum
    data = path_data(publication)
    preview = pathway_preview(user=publisher, data=data)
    publication.version += 1
    publication.save(update_fields=["version"])
    with pytest.raises(ValidationError):
        save_pathway(user=publisher, context=preview["context"], **data)
    preview = pathway_preview(user=publisher, data=data)
    marker = CatalogueState.objects.get(pk=1)
    marker.source_revision += 1
    marker.save(update_fields=["source_revision"])
    with pytest.raises(ValidationError):
        save_pathway(user=publisher, context=preview["context"], **data)
    assert not LearningPathRevision.objects.exists()


def test_owner_gate_and_publication_switch_are_independent(curriculum, settings):
    publisher, learner, publication = curriculum
    data = path_data(publication)
    learner.is_superuser = True
    learner.role = "admin"
    learner.save()
    with pytest.raises(PermissionDenied):
        pathway_preview(user=learner, data=data)
    preview = pathway_preview(user=publisher, data=data)
    settings.LEARNING_PUBLICATION_ENABLED = False
    with pytest.raises(PermissionDenied):
        save_pathway(user=publisher, context=preview["context"], **data)
    assert not LearningPathRevision.objects.exists()


def test_current_channel_validation_prevents_partial_route_release(curriculum):
    publisher, _learner, publication = curriculum
    publication.public_visible = False
    publication.save(update_fields=["public_visible"])
    with pytest.raises(ValidationError):
        release(publisher, path_data(publication, public=True))
    data = path_data(publication)
    data["items"].append(
        {"key": "missing", "title": "Missing note", "kind": "document", "document_id": str(uuid.uuid4())},
    )
    with pytest.raises(ValidationError):
        release(publisher, data)
    assert not LearningPathRevision.objects.exists()


def test_revisions_and_items_reject_all_supported_overwrite_routes(curriculum):
    publisher, _learner, publication = curriculum
    path = release(publisher, path_data(publication))
    revision = path.current_revision
    with pytest.raises(ValidationError):
        revision.save()
    with pytest.raises(ValidationError):
        LearningPathRevision.objects.filter(pk=revision.pk).update(title="Overwrite")
    with pytest.raises(ValidationError):
        LearningPathRevision.objects.bulk_update([revision], ["title"])
    with pytest.raises(ValidationError):
        LearningPathItem.objects.filter(revision=revision).delete()
    with pytest.raises(ValidationError):
        LearningPathItem.objects.bulk_create([], update_conflicts=True)


def test_explicit_reading_tracks_exact_revision_without_points(curriculum):
    publisher, learner, publication = curriculum
    path = release(publisher, path_data(publication))
    assert not path_context(path, learner)["items"][0]["read"]
    assert not PathReading.objects.exists()
    reading = mark_read(user=learner, path=path, item_key="amgm", revision_id=publication.revision_id)
    assert mark_read(user=learner, path=path, item_key="amgm", revision_id=publication.revision_id).pk == reading.pk
    assert path_context(path, learner)["items"][0]["read"]
    assert not MaterialCompletion.objects.exists()
    publication.training_visible = False
    publication.public_visible = False
    publication.save(update_fields=["training_visible", "public_visible"])
    assert not path_context(path, learner)["items"][0]["available"]
    with pytest.raises(ValidationError):
        mark_read(user=learner, path=path, item_key="amgm", revision_id=publication.revision_id)


def test_canonical_problem_identity_and_old_material_completion_survive(curriculum):
    publisher, learner, publication = curriculum
    problem = ProblemSolveRecord.objects.create(year=2026, topic="Algebra", contest="Synthetic", problem="1")
    completion = UserProblemCompletion.objects.create(user=learner, problem=problem, status="attempted")
    topic = Topic.objects.create(title="Preserved Foundations", slug="preserved-foundations")
    subtopic = Subtopic.objects.create(topic=topic, title="Proof", slug="proof")
    material = Material.objects.create(
        subtopic=subtopic,
        title="Legacy proof",
        slug="legacy-proof",
        content_markdown="Private old body",
    )
    old = MaterialCompletion.objects.create(user=learner, material=material, points_awarded=13)
    data = path_data(publication)
    data["items"] += [
        {
            "key": "practice",
            "kind": "problem",
            "title": "Canonical practice",
            "problem_uuid": str(problem.problem_uuid),
        },
        {"key": "legacy", "kind": "legacy", "title": "Existing material", "material_id": material.pk},
    ]
    path = release(publisher, data)
    rows = path_context(path, learner)["items"]
    assert rows[1]["item"].problem_id == problem.problem_uuid
    assert rows[1]["practice_status"] == "attempted"
    assert not rows[1]["practice_completed"]
    assert rows[2]["read"]
    old.refresh_from_db()
    completion.refresh_from_db()
    assert old.points_awarded == 13
    assert completion.status == "attempted"
    assert MaterialCompletion.objects.count() == 1


def test_foundations_is_cross_topic_without_a_catalogue_subject(curriculum):
    publisher, _learner, publication = curriculum
    data = path_data(publication, slug="foundations", is_foundations=True, area_id=None)
    path = release(publisher, data)
    assert path.is_foundations
    assert path.subject_id is None
    assert path.area_id is None
    assert CatalogueArea.objects.filter(subject_id="foundations").count() == 0


def test_edit_payload_round_trips_every_activity_kind(curriculum):
    publisher, _learner, publication = curriculum
    problem = ProblemSolveRecord.objects.create(year=2026, topic="Algebra", contest="Round trip", problem="1")
    topic = Topic.objects.create(title="Round trip", slug="round-trip")
    subtopic = Subtopic.objects.create(topic=topic, title="Proof", slug="proof")
    material = Material.objects.create(
        subtopic=subtopic,
        title="Existing proof",
        slug="round-trip-proof",
        content_markdown="An existing proof.",
    )
    data = path_data(publication, audience="Synthetic learner", readiness=["Read the statement carefully."])
    data["items"] += [
        {
            "key": "practice",
            "title": "Canonical practice",
            "kind": "problem",
            "problem_uuid": str(problem.problem_uuid),
        },
        {"key": "old", "title": "Earlier material", "kind": "legacy", "material_id": material.pk},
        {
            "key": "original",
            "title": "Original exercise",
            "kind": "exercise",
            "exercise_source": "Prove $x^2+1>0$ for real $x$.",
            "hints": ["Use a nonnegative square."],
        },
    ]
    path = release(publisher, data)
    payload = pathway_edit_payload(path)
    assert payload["items"][0]["document_id"] == str(publication.document_id)
    assert payload["items"][1]["problem_uuid"] == str(problem.problem_uuid)
    assert payload["items"][2]["material_id"] == material.pk
    assert payload["items"][3]["hints"] == data["items"][3]["hints"]
    assert all("item_key" not in item and "position" not in item for item in payload["items"])
    previous_digest = path.current_revision.source_digest
    updated = release(publisher, payload)
    assert updated.version == 2
    assert updated.current_revision.source_digest == previous_digest
    assert list(updated.current_revision.items.values_list("kind", flat=True)) == LearningPathItem.Kind.values


def test_inline_pathway_completion_requires_the_current_revision(client, curriculum):
    publisher, learner, publication = curriculum
    path = release(publisher, path_data(publication))
    endpoint = reverse("learning:mark_read", args=[path.slug, "amgm"])
    client.force_login(learner)

    stale = client.post(endpoint, {"revision_id": uuid.uuid4()}, HTTP_ACCEPT="application/json")
    assert stale.status_code == HTTPStatus.CONFLICT
    assert "lecture changed" in stale.json()["message"]
    assert not PathReading.objects.exists()

    for _ in range(2):
        response = client.post(endpoint, {"revision_id": publication.revision_id}, HTTP_ACCEPT="application/json")
        assert response.status_code == HTTPStatus.OK
        assert "Read · current revision" in response.json()["html"]
    assert PathReading.objects.filter(user=learner).count() == 1
