# ruff: noqa: PLR2004 -- Fixture sizes and exact milestone counts are intentional assertions.
import copy

import pytest
from django.core.exceptions import ValidationError

from inspinia.learning.models import ContentDocument
from inspinia.learning.models import ContentDraft
from inspinia.learning.models import ContentPublication
from inspinia.learning.models import ContributionProposal
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.training import test_pathway_fixtures
from inspinia.training.content_packs import apply_content_pack
from inspinia.training.content_packs import load_pathway_template
from inspinia.training.content_packs import load_teaching_pack
from inspinia.training.content_packs import preview_content_pack
from inspinia.training.pathway_models import ContentPackImport
from inspinia.training.pathway_models import LearningPath
from inspinia.users.tests.factories import UserFactory

private_content_packs = test_pathway_fixtures.private_content_packs

pytestmark = pytest.mark.django_db


@pytest.fixture
def author(settings, private_content_packs):
    settings.LEARNING_MODULE_ENABLED = True
    settings.LEARNING_CONTRIBUTIONS_ENABLED = True
    return UserFactory()


def test_pilot_import_is_private_only_and_exact_retry_is_idempotent(author):
    pack = load_teaching_pack("inequalities_pilot_v1")
    preview = preview_content_pack(pack=pack, user=author)
    assert preview["can_apply"]
    drafts = apply_content_pack(pack=pack, user=author, preview_token=preview["preview_token"])
    repeated = apply_content_pack(pack=pack, user=author, preview_token=preview["preview_token"])
    assert [draft.pk for draft in drafts] == [draft.pk for draft in repeated]
    assert ContentDraft.objects.count() == len(pack["notes"])
    assert ContentPackImport.objects.count() == 1
    assert not ContentPublication.objects.filter(training_visible=True).exists()
    assert not ContributionProposal.objects.exists()
    assert not LearningPath.objects.exists()
    assert all(draft.metadata["content_pack"]["rights_status"] == "unreviewed" for draft in drafts)
    assert all("concepts" in draft.metadata for draft in drafts)


def test_foundations_uses_existing_identity_and_can_prepare_all_nine_notes(author):
    pack = load_teaching_pack("foundations_v1")
    preview = preview_content_pack(pack=pack, user=author)
    drafts = apply_content_pack(pack=pack, user=author, preview_token=preview["preview_token"])
    assert len(drafts) == 9
    assert all(draft.document.canonical_concept_id for draft in drafts)
    assert all(draft.document.canonical_area_id is None for draft in drafts)


@pytest.mark.parametrize("location", ["pack", "note", "rights"])
def test_json_cannot_manufacture_publication_or_permission(author, location):
    pack = load_teaching_pack("inequalities_pilot_v1")
    target = pack if location == "pack" else pack["notes"][0]
    if location == "rights":
        target = target["rights"]
    target["approved_by"] = "forged publisher"
    with pytest.raises(ValidationError):
        preview_content_pack(pack=pack, user=author)
    assert not ContentDraft.objects.exists()


def test_mutated_content_or_catalogue_requires_fresh_preview(author):
    pack = load_teaching_pack("inequalities_pilot_v1")
    preview = preview_content_pack(pack=pack, user=author)
    altered = copy.deepcopy(pack)
    altered["notes"][0]["body_source"] += "\nAn additional statement."
    with pytest.raises(ValidationError):
        apply_content_pack(pack=altered, user=author, preview_token=preview["preview_token"])
    marker = CatalogueState.objects.get(pk=1)
    marker.source_revision += 1
    marker.save(update_fields=["source_revision"])
    with pytest.raises(ValidationError):
        apply_content_pack(pack=pack, user=author, preview_token=preview["preview_token"])
    assert not ContentDocument.objects.exists()


def test_bad_reference_blocks_the_batch_and_changed_import_identity_is_not_reused(author):
    pack = load_teaching_pack("inequalities_pilot_v1")
    pack["notes"][0]["concept_ids"] = ["no-such-concept"]
    preview = preview_content_pack(pack=pack, user=author)
    assert not preview["can_apply"]
    with pytest.raises(ValidationError):
        apply_content_pack(pack=pack, user=author, preview_token=preview["preview_token"])
    assert not ContentDraft.objects.exists()
    pack = load_teaching_pack("inequalities_pilot_v1")
    preview = preview_content_pack(pack=pack, user=author)
    apply_content_pack(
        pack=pack,
        user=author,
        preview_token=preview["preview_token"],
        selected_keys=[pack["notes"][0]["key"]],
    )
    pack["notes"][0]["body_source"] += "\nDifferent content."
    assert not preview_content_pack(pack=pack, user=author)["can_apply"]


def test_import_preview_is_bound_to_account_and_does_not_reset_existing_edits(author):
    pack = load_teaching_pack("inequalities_pilot_v1")
    preview = preview_content_pack(pack=pack, user=author)
    with pytest.raises(ValidationError):
        apply_content_pack(pack=pack, user=UserFactory(), preview_token=preview["preview_token"])
    keys = [pack["notes"][0]["key"]]
    draft = apply_content_pack(pack=pack, user=author, preview_token=preview["preview_token"], selected_keys=keys)[0]
    draft.body_source = "Author's later private improvement."
    draft.save(update_fields=["body_source"])
    replay = apply_content_pack(pack=pack, user=author, preview_token=preview["preview_token"], selected_keys=keys)[0]
    assert replay.body_source == draft.body_source


def test_template_refuses_partial_or_unpublished_note_sets(author, settings):
    settings.LEARNING_PUBLISHER_USER_ID = author.pk
    template = load_pathway_template("inequalities_pilot_v1", user=author)
    assert not template["can_preview"]
    assert len(template["missing"]) == 6
    assert all(item["document_id"] is None for item in template["payload"]["items"] if item["kind"] == "document")
    pack = load_teaching_pack("inequalities_pilot_v1")
    preview = preview_content_pack(pack=pack, user=author)
    drafts = apply_content_pack(pack=pack, user=author, preview_token=preview["preview_token"])
    assert not load_pathway_template("inequalities_pilot_v1", user=author)["can_preview"]
    from inspinia.learning.drafts import checkpoint_draft

    for draft in drafts:
        revision = checkpoint_draft(draft=draft, user=author)
        ContentPublication.objects.filter(document=draft.document).update(revision=revision, training_visible=True)
    resolved = load_pathway_template("inequalities_pilot_v1", user=author)
    assert resolved["can_preview"]
    assert not resolved["accepted"]
    assert not resolved["released"]
    assert not load_pathway_template("inequalities_pilot_v1", user=author, public=True)["can_preview"]
    assert all(item["document_id"] for item in resolved["payload"]["items"] if item["kind"] == "document")


def test_no_private_configuration_ships_or_loads_manuscripts(settings):
    from inspinia.training.content_packs import teaching_packs

    settings.LEARNING_CONTENT_PACK_ROOT = ""
    assert teaching_packs() == []
    with pytest.raises(ValidationError, match="not configured"):
        load_teaching_pack("inequalities_pilot_v1")


def test_missing_private_directory_is_an_empty_inventory_with_explicit_load_error(settings, tmp_path):
    from inspinia.training.content_packs import teaching_packs

    settings.MEDIA_ROOT = str(tmp_path / "public-media")
    settings.LEARNING_CONTENT_PACK_ROOT = str(tmp_path / "not-present")
    assert teaching_packs() == []
    with pytest.raises(ValidationError, match="unavailable"):
        load_teaching_pack("inequalities_pilot_v1")


@pytest.mark.parametrize("key", ["../outside", "/absolute", "a/b", "a.json", "", "x" * 161])
def test_private_pack_keys_cannot_escape_the_configured_root(private_content_packs, key):
    with pytest.raises(ValidationError):
        load_teaching_pack(key)


def test_private_json_is_bounded_and_structurally_validated(private_content_packs):
    from inspinia.training.content_packs import MAX_PACK_BYTES

    path = private_content_packs / "teaching_briefs/oversized.json"
    path.write_bytes(b" " * (MAX_PACK_BYTES + 1))
    with pytest.raises(ValidationError, match="2 MiB"):
        load_teaching_pack("oversized")
    path.write_text('{"version":1,"id":"other","notes":[]}')
    with pytest.raises(ValidationError, match="structure"):
        load_teaching_pack("oversized")
    path.write_text('{"version":1,"id":"oversized","notes":[NaN]}')
    with pytest.raises(ValidationError, match="JSON"):
        load_teaching_pack("oversized")


def test_private_file_or_directory_symlinks_are_rejected(private_content_packs, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('{"version":1,"id":"outside","notes":[{}]}')
    link = private_content_packs / "teaching_briefs/outside.json"
    link.symlink_to(outside)
    with pytest.raises(ValidationError, match="escape"):
        load_teaching_pack("outside")
    directory = private_content_packs / "pathways"
    saved = private_content_packs / "saved-pathways"
    directory.rename(saved)
    directory.symlink_to(saved, target_is_directory=True)
    from inspinia.training.content_packs import load_pathway_pack

    with pytest.raises(ValidationError, match="escape"):
        load_pathway_pack("inequalities_pilot_v1")


@pytest.mark.parametrize("field", ["MEDIA_ROOT", "STATIC_ROOT"])
def test_private_content_cannot_use_public_media_or_static_roots(settings, tmp_path, field):
    public = tmp_path / field.lower()
    root = public / "packs"
    root.mkdir(parents=True)
    setattr(settings, field, str(public))
    settings.LEARNING_CONTENT_PACK_ROOT = str(root)
    with pytest.raises(ValidationError, match="outside public"):
        load_teaching_pack("inequalities_pilot_v1")
