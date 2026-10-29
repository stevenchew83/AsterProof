"""Reviewable Gmail DSN imports; no mailbox access or inferred inbox delivery."""

from __future__ import annotations

import hashlib
import re
from email import policy
from email.errors import MessageError
from email.parser import BytesParser
from email.parser import Parser

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from .models import NewsletterBounceReport
from .models import NewsletterDelivery
from .models import NewsletterSendingHold

MAX_BYTES = 1024 * 1024
MAX_PARTS = 100
PREVIEW_SALT = "asterproof.newsletter.bounce-review.v1"
MESSAGE_ID = re.compile(
    r"^<newsletter-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})@asterproof\.com>$",
)
STATUS_CODE = re.compile(r"^[45]\.\d{1,3}\.\d{1,3}$")
# Address failures only. Policy/authentication failures (e.g. 5.7.1) do not prove
# that a recipient address is invalid and must not suppress that address.
ADDRESS_FAILURES = {"5.1.1", "5.1.2", "5.1.3", "5.1.6", "5.2.1"}
MAX_CLEAR_REASON_LENGTH = 180


def _address(block, name):
    values = block.get_all(name, [])
    if len(values) != 1:
        return ""
    kind, separator, address = str(values[0]).partition(";")
    if not separator or kind.strip().casefold() != "rfc822":
        return ""
    address = address.strip().casefold()
    try:
        validate_email(address)
    except ValidationError:
        return ""
    return address


def _recipient(block):
    final = _address(block, "Final-Recipient")
    if not final or len(block.get_all("Original-Recipient", [])) > 1:
        return ""
    if block.get("Original-Recipient") is not None:
        return _address(block, "Original-Recipient")
    return final


def _original_id(parts):
    ids = set()
    for part in parts:
        if part.get_content_type() == "message/rfc822":
            headers = part.get_payload()[0] if isinstance(part.get_payload(), list) and part.get_payload() else None
        elif part.get_content_type() == "text/rfc822-headers":
            headers = Parser(policy=policy.default).parsestr(part.get_content())
        else:
            continue
        if headers:
            for value in headers.get_all("Message-ID", []):
                match = MESSAGE_ID.fullmatch(str(value).strip())
                if match:
                    ids.add(match[1])
    if len(ids) != 1:
        msg = "The report must include exactly one original AsterProof newsletter Message-ID."
        raise ValidationError(msg)
    return ids.pop()


def _candidate(content):
    message = BytesParser(policy=policy.default).parsebytes(content)
    if message.get_content_type() != "multipart/report" or message.get_param("report-type") != "delivery-status":
        msg = "Upload the original delivery-status notification, not an ordinary or forwarded email."
        raise ValidationError(msg)
    parts = []
    for part in message.walk():
        parts.append(part)
        if len(parts) > MAX_PARTS:
            msg = "The report has too many MIME parts."
            raise ValidationError(msg)
    reports = [part for part in parts if part.get_content_type() == "message/delivery-status"]
    if len(reports) != 1 or not isinstance(reports[0].get_payload(), list):
        msg = "Upload a delivery-status notification with its original message headers."
        raise ValidationError(msg)
    delivery = NewsletterDelivery.objects.select_related("campaign").filter(pk=_original_id(parts)).first()
    if not delivery or delivery.status not in {NewsletterDelivery.Status.ACCEPTED, NewsletterDelivery.Status.UNKNOWN}:
        msg = "No completed or uncertain newsletter attempt matches this report."
        raise ValidationError(msg)
    address = delivery.recipient_email.casefold()
    matches = [block for block in reports[0].get_payload() if _recipient(block) == address]
    if len(matches) != 1:
        msg = "The reported recipient does not uniquely match the recorded newsletter attempt."
        raise ValidationError(msg)
    block = matches[0]
    action = str(block.get("Action", "")).strip().casefold()
    code = str(block.get("Status", "")).strip()
    if (
        len(block.get_all("Action", [])) != 1
        or len(block.get_all("Status", [])) != 1
        or not STATUS_CODE.fullmatch(code)
    ):
        msg = "The report has an invalid action or enhanced status code."
        raise ValidationError(msg)
    if action not in {"failed", "delayed"} or (action == "delayed" and not code.startswith("4.")):
        msg = "Only failure and delay notifications can be imported. Delivery success is not inferred."
        raise ValidationError(msg)
    source_hash = hashlib.sha256(content).hexdigest()
    identity = str(message.get("Message-ID", ""))[:1000] or source_hash
    fingerprint = hashlib.sha256(f"{delivery.pk}\0{address}\0{action}\0{code}\0{identity}".encode()).hexdigest()
    payload = {
        "delivery_id": str(delivery.pk),
        "recipient": address,
        "action": action,
        "status_code": code,
        "source_sha256": source_hash,
        "fingerprint": fingerprint,
    }
    return payload, delivery


def preview_report(content):
    if not content or len(content) > MAX_BYTES:
        msg = "Use a saved .eml delivery-failure email no larger than 1 MB."
        raise ValidationError(msg)
    try:
        payload, delivery = _candidate(content)
    except (MessageError, RecursionError, ValueError, TypeError, LookupError) as error:
        msg = "This delivery report could not be read safely."
        raise ValidationError(msg) from error
    return {
        "token": signing.dumps(payload, salt=PREVIEW_SALT),
        "delivery": delivery,
        "action": payload["action"],
        "status_code": payload["status_code"],
        "will_hold": payload["action"] == "failed" and payload["status_code"] in ADDRESS_FAILURES,
        "duplicate": NewsletterBounceReport.objects.filter(fingerprint=payload["fingerprint"]).exists(),
    }


def apply_report(token, actor):
    try:
        value = signing.loads(token, salt=PREVIEW_SALT, max_age=900)
    except signing.BadSignature as error:
        msg = "This review expired or changed. Upload the report again."
        raise ValidationError(msg) from error
    with transaction.atomic():
        delivery = NewsletterDelivery.objects.select_for_update().get(pk=value["delivery_id"])
        if delivery.recipient_email.casefold() != value["recipient"] or delivery.status not in {
            NewsletterDelivery.Status.ACCEPTED,
            NewsletterDelivery.Status.UNKNOWN,
        }:
            msg = "The recorded attempt changed. Review the report again."
            raise ValidationError(msg)
        report, created = NewsletterBounceReport.objects.get_or_create(
            fingerprint=value["fingerprint"],
            defaults={
                "delivery": delivery,
                "action": value["action"],
                "status_code": value["status_code"],
                "source_sha256": value["source_sha256"],
                "imported_by": actor,
            },
        )
        if created:
            result = (
                NewsletterDelivery.Result.BOUNCED if report.action == "failed" else NewsletterDelivery.Result.DELAYED
            )
            if delivery.delivery_result != NewsletterDelivery.Result.BOUNCED:
                delivery.delivery_result = result
                delivery.save(update_fields=["delivery_result"])
            if report.action == "failed" and report.status_code in ADDRESS_FAILURES:
                NewsletterSendingHold.objects.get_or_create(
                    email=value["recipient"],
                    cleared_at=None,
                    defaults={"report": report},
                )
    return report, created


def clear_hold(pk, actor, reason):
    reason = reason.strip()
    if not reason or len(reason) > MAX_CLEAR_REASON_LENGTH:
        msg = "Record a reason of up to 180 characters for restoring newsletter sending."
        raise ValidationError(msg)
    with transaction.atomic():
        hold = NewsletterSendingHold.objects.select_for_update().get(pk=pk)
        if hold.cleared_at is None:
            hold.cleared_at, hold.cleared_by, hold.clear_reason = timezone.now(), actor, reason
            hold.save(update_fields=["cleared_at", "cleared_by", "clear_reason"])
    return hold
