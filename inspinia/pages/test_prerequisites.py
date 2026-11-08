# ruff: noqa: PLR2004 -- Fixture sizes and exact milestone counts are intentional assertions.
import pytest
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError

from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.prerequisite_models import CataloguePrerequisite
from inspinia.pages.prerequisite_models import PrerequisiteGraphState
from inspinia.pages.prerequisites import prerequisite_context
from inspinia.pages.prerequisites import replace_prerequisites
from inspinia.pages.prerequisites import revalidate_graph
from inspinia.pages.prerequisites import set_prerequisite
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def curator(settings):
    settings.LEARNING_MODULE_ENABLED = True
    settings.LEARNING_PUBLICATION_ENABLED = True
    user = UserFactory()
    settings.LEARNING_PUBLISHER_USER_ID = user.pk
    for key in ("prereq-a", "prereq-b", "prereq-c"):
        CatalogueConcept.objects.create(id=key, name=key)
    return user


def test_prerequisites_are_curator_approved_and_not_taxonomy_edges(curator):
    state = replace_prerequisites(user=curator, edges=[("prereq-a", "prereq-b")], expected_version=0)
    assert state.version == 1
    assert prerequisite_context("prereq-b")["prerequisites"] == [{"id": "prereq-a", "name": "prereq-a"}]
    assert CataloguePrerequisite.objects.get().approved_by_id == curator.pk
    with pytest.raises(PermissionDenied):
        set_prerequisite(
            user=UserFactory(is_superuser=True),
            prerequisite_id="prereq-b",
            dependent_id="prereq-c",
            expected_version=1,
        )
    with pytest.raises(ValidationError):
        set_prerequisite(user=curator, prerequisite_id="prereq-b", dependent_id="prereq-c", expected_version=0)
    assert CataloguePrerequisite.objects.count() == 1


def test_cycle_and_redirect_self_edges_leave_existing_graph_intact(curator):
    replace_prerequisites(user=curator, edges=[("prereq-a", "prereq-b"), ("prereq-b", "prereq-c")], expected_version=0)
    with pytest.raises(ValidationError):
        set_prerequisite(user=curator, prerequisite_id="prereq-c", dependent_id="prereq-a", expected_version=1)
    CatalogueConcept.objects.filter(pk="prereq-c").update(redirect_id="prereq-b")
    with pytest.raises(ValidationError):
        replace_prerequisites(user=curator, edges=[("prereq-b", "prereq-c")], expected_version=1)
    assert CataloguePrerequisite.objects.count() == 2
    assert PrerequisiteGraphState.objects.get().version == 1


def test_catalogue_changes_fail_closed_until_explicit_maintenance(curator, django_assert_num_queries):
    replace_prerequisites(user=curator, edges=[("prereq-a", "prereq-b")], expected_version=0)
    marker = CatalogueState.objects.get(pk=1)
    marker.source_revision += 1
    marker.save(update_fields=["source_revision"])
    with django_assert_num_queries(2):
        assert not prerequisite_context("prereq-b")["available"]
    assert PrerequisiteGraphState.objects.get().validated_catalogue_revision != marker.source_revision
    state = revalidate_graph()
    assert state.is_valid
    assert prerequisite_context("prereq-b")["available"]
    CatalogueConcept.objects.filter(pk="prereq-b").update(redirect_id="prereq-a")
    marker.source_revision += 1
    marker.save(update_fields=["source_revision"])
    assert not revalidate_graph().is_valid
    assert not prerequisite_context("prereq-b")["available"]


def test_redirects_resolve_before_dag_validation(curator):
    CatalogueConcept.objects.filter(pk="prereq-c").update(redirect_id="prereq-a")
    replace_prerequisites(user=curator, edges=[("prereq-c", "prereq-b")], expected_version=0)
    assert CataloguePrerequisite.objects.get().prerequisite_id == "prereq-a"
