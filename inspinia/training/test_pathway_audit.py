# ruff: noqa: PLR2004 -- Fixture sizes and exact milestone counts are intentional assertions.
import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueConceptArea
from inspinia.training.curriculum_audit import audit_learning_scope
from inspinia.training.models import Material
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic

pytestmark = pytest.mark.django_db


def test_inventory_is_read_only_bounded_and_does_not_export_private_source():
    topic = Topic.objects.get(slug="algebra")
    subtopic = Subtopic.objects.create(topic=topic, slug="audit", title="Audit")
    source = Material.objects.create(
        subtopic=subtopic, slug="audit-secret", title="AM-GM", content_markdown="PRIVATE SOURCE MUST NEVER APPEAR",
    )
    with CaptureQueriesContext(connection) as queries:
        audit = audit_learning_scope(limit=500)
    assert all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)
    serialized = json.dumps(audit)
    assert "PRIVATE SOURCE" not in serialized
    row = next(item for item in audit["legacy"]["material"]["items"] if item["id"] == source.pk)
    assert row["id"] == source.pk
    assert row["candidate_state"] == "candidate_only"
    assert "am-gm" in row["candidate_ids"]
    assert len(row["fingerprint"]) == 64
    assert row["reviewed_document_id"] is None
    assert audit["catalogue"]["areas"] == 45
    assert len(audit["foundations"]) == 9
    assert all(area["rollout_owner"] == "Steven" for area in audit["areas"])


def test_duplicate_title_reports_ambiguity_without_creating_a_mapping():
    original = CatalogueConcept.objects.get(pk="am-gm")
    duplicate = CatalogueConcept.objects.create(id="synthetic-ambiguous-amgm", name=original.name)
    CatalogueConceptArea.objects.create(concept=duplicate, area_id="Algebra:inequalities")
    topic = Topic.objects.get(slug="algebra")
    subtopic = Subtopic.objects.create(topic=topic, slug="audit", title="Audit")
    Material.objects.create(
        subtopic=subtopic, slug="audit-ambiguous", title="AM-GM", content_markdown="Private source",
    )
    audit = audit_learning_scope(area_id="Algebra:inequalities")
    row = audit["legacy"]["material"]["items"][0]
    assert row["candidate_state"] == "ambiguous"
    assert len(row["candidate_ids"]) == 2
    assert row["reviewed_document_id"] is None
