"""Validated curriculum manifests and preview-before-import of private teaching drafts."""

import hashlib
import json
from itertools import islice
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction

from inspinia.pages.catalogue_models import CatalogueArea
from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.training.pathway_models import ContentPackImport

DATA = Path(__file__).with_name("data")
PREVIEW_SALT = "training.private-content-pack.v1"
PREVIEW_TTL = 60 * 60
MAX_PACK_NOTES = 100
MAX_PACK_KEY = 160
MAX_NOTE_TITLE = 180
MAX_NOTE_SOURCE = 64000
MAX_NOTE_CONCEPTS = 30
MAX_IMPORT_BATCH = 25
MAX_PACK_BYTES = 2 * 1024 * 1024
MAX_PRIVATE_PACKS = 100
FORBIDDEN_FIELDS = {
    "approved",
    "is_approved",
    "is_published",
    "rights_grant",
    "approval",
    "approved_by",
    "approved_at",
    "consent",
    "grant",
    "permissions",
    "published_at",
    "publisher",
    "public_visible",
    "training_visible",
}


def _digest(value):
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        msg = "The content pack is not valid JSON data."
        raise ValidationError(msg) from exc
    if len(raw.encode()) > 2 * 1024 * 1024:
        msg = "The content pack is too large."
        raise ValidationError(msg)
    return hashlib.sha256(raw.encode()).hexdigest()


def rollout_manifest():
    return json.loads((DATA / "training_rollout_v1.json").read_text())


def _private_root(*, required=False):
    configured = getattr(settings, "LEARNING_CONTENT_PACK_ROOT", "")
    if not configured:
        if required:
            msg = "Private teaching packs are not configured. No manuscripts are shipped with the public application."
            raise ValidationError(msg)
        return None
    root = Path(configured).expanduser()
    if not root.is_absolute() or root.is_symlink():
        msg = "The private teaching-pack root must be an absolute directory without a symlink."
        raise ValidationError(msg)
    root = root.resolve()
    public_roots = [
        getattr(settings, "MEDIA_ROOT", ""),
        getattr(settings, "STATIC_ROOT", ""),
        settings.BASE_DIR / "inspinia/static",
        settings.BASE_DIR / "staticfiles",
        *getattr(settings, "STATICFILES_DIRS", []),
    ]
    for public_root in public_roots:
        location = public_root[-1] if isinstance(public_root, (tuple, list)) else public_root
        if location and root.is_relative_to(Path(location).resolve()):
            msg = "Teaching manuscripts must stay outside public media and static directories."
            raise ValidationError(msg)
    if not root.is_dir():
        if required:
            msg = "The private teaching-pack directory is unavailable."
            raise ValidationError(msg)
        return None
    return root


def _pack_key(key):
    if (
        not isinstance(key, str)
        or not 1 <= len(key) <= MAX_PACK_KEY
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in key)
    ):
        msg = "Unknown private teaching pack."
        raise ValidationError(msg)
    return key


def _read_private_json(section, key):
    root = _private_root(required=True)
    path = root / section / f"{_pack_key(key)}.json"
    if path.parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root):
        msg = "Private teaching-pack files cannot escape their configured directory."
        raise ValidationError(msg)
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_PACK_BYTES + 1)
        if len(raw) > MAX_PACK_BYTES:
            msg = "The private teaching pack exceeds the 2 MiB limit."
            raise ValidationError(msg)
        value = json.loads(raw)
        # Reject non-JSON NaN/Infinity constants as well as unbounded nested values.
        json.dumps(value, allow_nan=False)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        msg = "The private teaching pack is missing or is not valid bounded JSON."
        raise ValidationError(msg) from exc
    entries = "notes" if section == "teaching_briefs" else "items"
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != 1
        or value.get("id") != key
        or not isinstance(value.get(entries), list)
        or not 1 <= len(value[entries]) <= MAX_PACK_NOTES
        or any(not isinstance(item, dict) for item in value[entries])
    ):
        msg = "The private teaching pack has an unsupported identity or document structure."
        raise ValidationError(msg)
    return value


def teaching_packs():
    root = _private_root()
    if root is None:
        return []
    directory = root / "teaching_briefs"
    if directory.is_symlink():
        msg = "Private teaching-pack directories cannot be symlinks."
        raise ValidationError(msg)
    paths = sorted(islice(directory.glob("*.json"), MAX_PRIVATE_PACKS + 1))
    if len(paths) > MAX_PRIVATE_PACKS:
        msg = "The private teaching-pack directory exceeds its reviewed pack limit."
        raise ValidationError(msg)
    return [load_teaching_pack(path.stem) for path in paths]


def load_teaching_pack(key):
    return _read_private_json("teaching_briefs", _pack_key(key))


def load_pathway_pack(key):
    return _read_private_json("pathways", _pack_key(key))


def audit_private_starter_packs():
    """Local-only readiness inventory; never returns manuscript text or claims review."""
    packs = {pack["id"]: pack for pack in teaching_packs()}
    manifest = rollout_manifest()
    errors = []
    drafted_areas = 0
    for area in manifest["areas"]:
        pack = packs.get(area["pack"])
        if pack is None:
            errors.append(f"{area['id']}: private pack unavailable")
            continue
        notes = {note.get("key"): note for note in pack["notes"]}
        entry = notes.get(area["entry_note_key"])
        overview = any(note.get("kind") == "overview" and note.get("area_id") == area["id"] for note in notes.values())
        if not entry or not overview or not entry.get("body_source") or not entry.get("practice", {}).get("hints"):
            errors.append(f"{area['id']}: draft entry package incomplete")
            continue
        pathway = load_pathway_pack(area["pack"])
        if not any(item.get("pack_note_key") == area["entry_note_key"] for item in pathway["items"]):
            errors.append(f"{area['id']}: private pathway reference missing")
            continue
        drafted_areas += 1
    foundations = packs.get(manifest["foundations"]["pack"], {"notes": []})
    foundation_keys = {note.get("key") for note in foundations["notes"]}
    drafted_foundations = sum(item["note_key"] in foundation_keys for item in manifest["foundations"]["competencies"])
    return {
        "private_pack_count": len(packs),
        "private_note_count": sum(len(pack["notes"]) for pack in packs.values()),
        "draft_area_entries": drafted_areas,
        "draft_foundations_entries": drafted_foundations,
        "errors": errors,
        "editorial_review": "pending",
        "publication": "unpublished",
    }


def load_pathway_template(key, *, user, public=False):
    """Resolve a complete template only through this publisher's imported notes.

    Missing notes remain explicit null targets. A partial route is never silently
    returned as ready, and neither this read nor the JSON grants publication.
    """
    from inspinia.learning.models import ContentDraft
    from inspinia.learning.models import ContentPublication
    from inspinia.learning.permissions import require_publisher

    require_publisher(user)
    pack = load_teaching_pack(key)
    if type(public) is not bool:
        msg = "Unknown pathway template or publication channel."
        raise ValidationError(msg)
    template = load_pathway_pack(key)
    receipt = ContentPackImport.objects.filter(user=user, pack_key=pack["id"]).first()
    imported = receipt.draft_ids if receipt and receipt.source_digest == _digest(pack) else {}
    drafts = {str(draft.pk): draft for draft in ContentDraft.objects.filter(pk__in=imported.values(), author=user)}
    documents = {draft.document_id for draft in drafts.values()}
    publications = ContentPublication.objects.filter(
        document_id__in=documents,
        revision__isnull=False,
        training_visible=True,
    )
    if public:
        publications = publications.filter(public_visible=True)
    approved = {publication.document_id for publication in publications}
    items, missing = [], []
    for item in template["items"]:
        if item["kind"] == "document_reference":
            draft = drafts.get(imported.get(item["pack_note_key"]))
            ready = draft is not None and draft.document_id in approved
            items.append(
                {
                    "key": item["key"],
                    "title": item["title"],
                    "kind": "document",
                    "document_id": str(draft.document_id) if ready else None,
                },
            )
            if not ready:
                missing.append(
                    {
                        "key": item["key"],
                        "note_key": item["pack_note_key"],
                        "reason": "Import and publish the reviewed note in the selected channel first.",
                    },
                )
        else:
            items.append(dict(item))
    payload = {
        "slug": key,
        "title": template["title"],
        "subject_id": template.get("subject"),
        "is_foundations": template.get("is_foundations", False),
        "public": public,
        "expected_version": 0,
        "items": items,
    }
    from inspinia.training.pathway_models import LearningPath

    existing = LearningPath.objects.filter(slug=key).first()
    payload["expected_version"] = existing.version if existing else 0
    return {
        "payload": payload,
        "missing": missing,
        "can_preview": not missing,
        "status": "draft",
        "accepted": False,
        "released": False,
        "notice": (
            "A complete approved-document set permits review; area acceptance and publication remain separate actions."
        ),
    }


def _validate_pack(pack):  # noqa: C901, PLR0912, PLR0915 - Explicit untrusted pack validation boundary.
    if not isinstance(pack, dict) or pack.get("version") != 1:
        msg = "Unsupported content-pack version."
        raise ValidationError(msg)
    if FORBIDDEN_FIELDS.intersection(pack):
        msg = "Content packs cannot assert approval, permission or publication."
        raise ValidationError(msg)
    key = pack.get("id")
    if not isinstance(key, str) or not 1 <= len(key) <= MAX_PACK_KEY:
        msg = "The pack needs a stable identity."
        raise ValidationError(msg)
    if pack.get("status", "draft") != "draft":
        msg = "Imported material must remain an unreviewed draft."
        raise ValidationError(msg)
    notes = pack.get("notes")
    if not isinstance(notes, list) or not 1 <= len(notes) <= MAX_PACK_NOTES:
        msg = "A content pack needs between 1 and 100 notes."
        raise ValidationError(msg)
    errors, keys = [], set()
    for note in notes:
        if not isinstance(note, dict):
            msg = "Each teaching note must be an object."
            raise ValidationError(msg)
        if FORBIDDEN_FIELDS.intersection(note):
            msg = "A teaching note cannot manufacture approval or rights."
            raise ValidationError(msg)
        note_key = note.get("key")
        if not isinstance(note_key, str) or not note_key or len(note_key) > MAX_PACK_KEY or note_key in keys:
            msg = "Teaching notes need unique stable identities."
            raise ValidationError(msg)
        keys.add(note_key)
        if note.get("publication_status", "draft") != "draft":
            msg = "Imported notes cannot claim to be approved or published."
            raise ValidationError(msg)
        rights = note.get("rights", {})
        if (
            not isinstance(rights, dict)
            or rights.get("status", "unreviewed") != "unreviewed"
            or FORBIDDEN_FIELDS.intersection(rights)
        ):
            msg = "Source declarations are not a contributor publication grant."
            raise ValidationError(msg)
        if not isinstance(note.get("title"), str) or not 1 <= len(note["title"]) <= MAX_NOTE_TITLE:
            msg = "The note title is invalid."
            raise ValidationError(msg)
        if not isinstance(note.get("body_source"), str) or not 1 <= len(note["body_source"]) <= MAX_NOTE_SOURCE:
            msg = "The note source is invalid or too long."
            raise ValidationError(msg)
        if note.get("kind", "lecture") not in {"overview", "concept", "lecture", "technique", "standalone"}:
            msg = "The note kind is invalid."
            raise ValidationError(msg)
        area = note.get("area_id")
        if area is not None and not isinstance(area, str):
            message = "The canonical area identity is invalid."
            raise ValidationError(message)
        if area and not CatalogueArea.objects.filter(pk=area).exists():
            errors.append(f"{note_key}: canonical area is unavailable")
        concept_ids = note.get("concept_ids", [])
        if (
            not isinstance(concept_ids, list)
            or len(concept_ids) > MAX_NOTE_CONCEPTS
            or any(not isinstance(value, str) for value in concept_ids)
        ):
            msg = "Concept associations are invalid."
            raise ValidationError(msg)
        found = set(
            CatalogueConcept.objects.filter(pk__in=concept_ids, redirect__isnull=True).values_list("pk", flat=True),
        )
        if set(concept_ids) != found:
            errors.append(f"{note_key}: concept associations need canonical review")
        anchor = note.get("canonical_concept_id")
        if anchor and (
            not isinstance(anchor, str)
            or not CatalogueConcept.objects.filter(pk=anchor, redirect__isnull=True).exists()
        ):
            errors.append(f"{note_key}: canonical concept landing needs review")
        kind = note.get("kind", "lecture")
        if kind == "overview" and (not area or anchor):
            errors.append(f"{note_key}: an overview needs exactly one canonical area")
        if kind == "concept" and not anchor:
            errors.append(f"{note_key}: a concept explanation needs a canonical concept")
        if kind in {"lecture", "technique"} and not (area or anchor or concept_ids):
            errors.append(f"{note_key}: the teaching unit needs a canonical association")
        if kind == "standalone" and (area or anchor):
            errors.append(f"{note_key}: standalone resources cannot claim a canonical landing")
        practice = note.get("practice", {})
        if not isinstance(practice, dict):
            msg = "Practice metadata must be an object."
            raise ValidationError(msg)
        if practice.get("canonical_problem_uuid"):
            from inspinia.pages.models import ProblemSolveRecord

            if not ProblemSolveRecord.objects.filter(
                problem_uuid=practice["canonical_problem_uuid"],
                is_active=True,
            ).exists():
                errors.append(f"{note_key}: canonical practice problem is unavailable")
    return errors


def preview_content_pack(*, pack, user):
    from inspinia.learning.permissions import require_contributor

    require_contributor(user)
    digest = _digest(pack)
    errors = _validate_pack(pack)
    marker = CatalogueState.objects.filter(pk=1).values_list("source_revision", flat=True).first()
    previous = ContentPackImport.objects.filter(user=user, pack_key=pack["id"]).first()
    if previous and previous.source_digest != digest:
        errors.append("This pack identity was imported with different content; review a new version identity.")
    payload = {"user": str(user.pk), "pack": pack["id"], "digest": digest, "catalogue": marker}
    return {
        "id": pack["id"],
        "title": pack.get("title", pack["id"]),
        "digest": digest,
        "notes": [
            {
                "key": note["key"],
                "title": note["title"],
                "area_id": note.get("area_id"),
                "already_imported": bool(previous and note["key"] in previous.draft_ids),
            }
            for note in pack["notes"]
        ],
        "errors": errors,
        "can_apply": not errors,
        "preview_token": signing.dumps(payload, salt=PREVIEW_SALT),
        "publication_status": "draft",
        "rights_status": "unreviewed",
    }


@transaction.atomic
def apply_content_pack(*, pack, user, preview_token, selected_keys=None):  # noqa: C901 - Atomic import and replay.
    """Create private drafts only; all editorial actions remain separate."""
    from inspinia.learning.drafts import create_draft
    from inspinia.learning.models import ContentDraft
    from inspinia.learning.permissions import require_contributor

    require_contributor(user)
    try:
        payload = signing.loads(preview_token, salt=PREVIEW_SALT, max_age=PREVIEW_TTL)
    except (signing.BadSignature, TypeError, ValueError) as exc:
        msg = "The pack preview expired. Preview the current pack again."
        raise ValidationError(msg) from exc
    errors = _validate_pack(pack)
    if errors:
        raise ValidationError(errors)
    marker = CatalogueState.objects.select_for_update().filter(pk=1).values_list("source_revision", flat=True).first()
    digest = _digest(pack)
    if not isinstance(payload, dict) or payload != {
        "user": str(user.pk),
        "pack": pack.get("id"),
        "digest": digest,
        "catalogue": marker,
    }:
        msg = "The pack or catalogue changed. Preview it again before importing."
        raise ValidationError(msg)
    errors = _validate_pack(pack)
    if errors:
        raise ValidationError(errors)
    available = {note["key"] for note in pack["notes"]}
    if selected_keys is not None and (
        not isinstance(selected_keys, list) or any(not isinstance(key, str) for key in selected_keys)
    ):
        msg = "Choose a list of note identities from this pack."
        raise ValidationError(msg)
    selected = available if selected_keys is None else set(selected_keys)
    if not selected or not selected <= available or len(selected) > MAX_IMPORT_BATCH:
        msg = "Choose between 1 and 25 notes from this pack."
        raise ValidationError(msg)
    receipt, _ = ContentPackImport.objects.select_for_update().get_or_create(
        user=user,
        pack_key=pack["id"],
        defaults={"source_digest": digest},
    )
    if receipt.source_digest != digest:
        msg = "This import identity already belongs to different content."
        raise ValidationError(msg)
    result = []
    for note in pack["notes"]:
        if note["key"] not in selected:
            continue
        previous_id = receipt.draft_ids.get(note["key"])
        if previous_id:
            draft = ContentDraft.objects.filter(pk=previous_id, author=user).first()
            if draft is None:
                msg = "An imported draft was removed; reconcile the previous import before retrying."
                raise ValidationError(msg)
        else:
            metadata = {
                "pack_id": pack["id"],
                "concepts": [{"id": identifier, "role": "supporting"} for identifier in note.get("concept_ids", [])],
                "audience": note.get("audience", ""),
                "content_pack": {
                    "note_key": note["key"],
                    "readiness": note.get("readiness", []),
                    "practice": note.get("practice", {}),
                    "source_declaration": note.get("rights", {}),
                    "rights_status": "unreviewed",
                    "editorial_status": "draft",
                },
            }
            draft = create_draft(
                user=user,
                kind=note.get("kind", "lecture"),
                area_id=None if note.get("kind") == "concept" else note.get("area_id"),
                concept_id=note.get("canonical_concept_id")
                or ((note.get("concept_ids") or [None])[0] if not note.get("area_id") else None),
                title=note["title"],
                source=note["body_source"],
                summary=note.get("summary", ""),
                metadata=metadata,
            )
            receipt.draft_ids[note["key"]] = str(draft.pk)
        result.append(draft)
    receipt.save(update_fields=["draft_ids", "updated_at"])
    return result
