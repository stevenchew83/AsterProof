"""Configure a reviewed rollout, import qualification evidence, or reconcile a receipt."""

# ruff: noqa: EM101, EM102, PLR2004, TRY003

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from inspinia.pages.study_help import generation_ready
from inspinia.pages.study_help import pricing_ready
from inspinia.pages.study_help_access import lock_study_help
from inspinia.pages.study_help_models import StudyHelpAdminEvent
from inspinia.pages.study_help_models import StudyHelpEnrollment
from inspinia.pages.study_help_models import StudyHelpPolicy
from inspinia.pages.study_help_models import StudyHelpPrompt
from inspinia.pages.study_help_models import StudyHelpQualification
from inspinia.pages.study_help_models import StudyHelpSpend
from inspinia.pages.study_help_provider import profile_digest
from inspinia.pages.study_help_qualification import load_fixtures
from inspinia.pages.study_help_qualification import summarize_reviews
from inspinia.pages.study_help_worker import reconcile
from inspinia.users.roles import user_can_access_app_features
from inspinia.users.roles import user_has_admin_role
from inspinia.users.roles import user_has_trainer_or_admin_role

MAX_MICROS = 1_000_000_000_000
MONEY_FIELDS = ("input_price", "output_price", "request_cap", "day_cap", "month_cap")


class Command(BaseCommand):
    help = "Control the funded Study Help policy and record approved launch evidence."

    def add_arguments(self, parser):
        subcommands = parser.add_subparsers(dest="operation", required=True)
        readiness = subcommands.add_parser("readiness")
        readiness.add_argument("--prompt")
        receipt = subcommands.add_parser("receipt")
        receipt.add_argument("--receipt", required=True)
        for operation in ("configure", "qualify", "enroll", "revoke", "enable", "pause", "reconcile"):
            sub = subcommands.add_parser(operation)
            sub.add_argument("--operator-id", type=int, required=True)
            sub.add_argument("--approval-ref", required=True)
            if operation == "configure":
                sub.add_argument("--model", required=True)
                for name in MONEY_FIELDS:
                    sub.add_argument("--" + name.replace("_", "-"), type=int, required=True)
            if operation == "qualify":
                sub.add_argument("--prompt", required=True)
                sub.add_argument("--evidence", type=Path, required=True)
            if operation in {"enroll", "revoke"}:
                sub.add_argument("--user-id", required=True, type=int)
            if operation == "enable":
                sub.add_argument("--audience", choices=StudyHelpPolicy.Audience.values, required=True)
            if operation == "reconcile":
                sub.add_argument("--receipt", required=True)
                sub.add_argument("--actual-micros", type=int, required=True)

    def handle(self, *args, **options):
        operation = options["operation"]
        if operation == "readiness":
            self._readiness(options["prompt"])
            return
        if operation == "receipt":
            self._receipt(options["receipt"])
            return
        actor = get_user_model().objects.filter(pk=options["operator_id"], is_active=True).first()
        reference = options["approval_ref"].strip()
        if not user_has_admin_role(actor) or not 0 < len(reference) <= 160:
            raise CommandError("Use an active AsterProof administrator and a bounded approval reference.")
        try:
            with transaction.atomic():
                lock_study_help()
                policy, _ = StudyHelpPolicy.objects.get_or_create(pk=1)
                prompt = getattr(self, "_" + operation)(policy, actor, reference, options)
                StudyHelpAdminEvent.objects.create(actor=actor, action=operation, reference=reference, prompt=prompt)
        except (ValidationError, ValueError, TypeError, KeyError, AttributeError, OSError) as error:
            raise CommandError(f"Invalid Study Help operation or evidence: {error}") from error
        self.stdout.write(self.style.SUCCESS(f"Study Help {operation} recorded."))

    def _readiness(self, prompt_id=None):
        policy = StudyHelpPolicy.objects.select_related("active_prompt").filter(pk=1).first()
        receipts = StudyHelpSpend.objects
        try:
            prompt = StudyHelpPrompt.objects.filter(pk=prompt_id).first() if prompt_id else None
        except ValidationError as error:
            raise CommandError("Provide a valid prompt UUID.") from error
        if prompt_id and prompt is None:
            raise CommandError("No prompt with that UUID exists.")
        self.stdout.write(
            json.dumps(
                {
                    "generation_ready": generation_ready(policy),
                    "model": policy.model if policy else "",
                    "audience": policy.audience if policy else "",
                    "worker_checked_at": (
                        policy.worker_checked_at.isoformat() if policy and policy.worker_checked_at else None
                    ),
                    "pending_receipts": receipts.filter(
                        state__in=[StudyHelpSpend.State.RESERVED, StudyHelpSpend.State.DISPATCHED],
                    ).count(),
                    "unreconciled_receipts": receipts.filter(state=StudyHelpSpend.State.UNKNOWN).count(),
                "unreconciled_ids": [
                    str(pk) for pk in receipts.filter(state=StudyHelpSpend.State.UNKNOWN)
                    .order_by("dispatched_at").values_list("pk", flat=True)[:20]
                ],
                "candidate_profile_digest": (
                    profile_digest(prompt, policy.model) if prompt and policy and policy.model else None
                ),
                },
            ),
        )

    def _receipt(self, receipt_id):
        try:
            receipt = StudyHelpSpend.objects.get(pk=receipt_id)
        except (StudyHelpSpend.DoesNotExist, ValidationError) as error:
            raise CommandError("No receipt with that UUID exists.") from error
        self.stdout.write(json.dumps({
            "state": receipt.state,
            "reserved_micros": receipt.reserved_micros,
            "actual_micros": receipt.actual_micros,
            "provider_request_id": receipt.provider_request_id,
            "provider_response_id": receipt.provider_response_id,
            "dispatched_at": receipt.dispatched_at.isoformat() if receipt.dispatched_at else None,
        }))

    def _configure(self, policy, _actor, _reference, options):
        model = options["model"].strip()
        if not 0 < len(model) <= 100 or any(not 0 < options[name] <= MAX_MICROS for name in MONEY_FIELDS):
            raise CommandError("Supply an exact model and positive prices and spending caps in USD micros.")
        for name in MONEY_FIELDS:
            setattr(policy, name, options[name])
        policy.model = model
        policy.pricing_verified_at = timezone.now()
        policy.generation_enabled = False
        if not pricing_ready(policy):
            raise CommandError("The request, daily, and monthly caps must be in ascending order.")
        policy.save()

    def _qualify(self, policy, _actor, reference, options):
        prompt = StudyHelpPrompt.objects.filter(pk=options["prompt"]).first()
        path = options["evidence"]
        if prompt is None or not policy.model or path.stat().st_size > 256_000:
            raise CommandError("Provide a saved prompt, configured model, and a bounded evidence file.")
        evidence = json.loads(path.read_text())
        digest = profile_digest(prompt, policy.model)
        if evidence["profile_digest"] != digest:
            raise CommandError("Evidence must bind the exact current prompt, model, and output settings.")
        fixtures = load_fixtures(evidence["fixtures"])
        usable = summarize_reviews(evidence, fixtures)
        reviewers = []
        for review in evidence["reviews"]:
            reviewer = get_user_model().objects.filter(pk=review["reviewer_id"], is_active=True).first()
            if not user_can_access_app_features(reviewer) or not user_has_trainer_or_admin_role(reviewer):
                raise CommandError("The reviewers must be approved trainers or administrators.")
            reviewers.append(reviewer.pk)
        if len(set(reviewers)) != 2:
            raise CommandError("Two distinct reviewers are required.")
        StudyHelpQualification.objects.get_or_create(
            prompt=prompt,
            profile_digest=digest,
            defaults={"evidence": {"reference": reference, "usable": usable, "fixture_count": len(fixtures)}},
        )
        return prompt

    def _enroll(self, _policy, _actor, _reference, options):
        user = get_user_model().objects.filter(pk=options["user_id"], is_active=True).first()
        if not user_can_access_app_features(user):
            raise CommandError("The account must be active and approved.")
        StudyHelpEnrollment.objects.get_or_create(user=user)

    def _revoke(self, _policy, _actor, _reference, options):
        StudyHelpEnrollment.objects.filter(user_id=options["user_id"]).delete()

    def _enable(self, policy, _actor, _reference, options):
        policy.audience = options["audience"]
        policy.generation_enabled = True
        if not generation_ready(policy):
            raise CommandError(
                "A qualified published prompt, funded pricing, enabled provider, and fresh worker are required.",
            )
        policy.save(update_fields=["audience", "generation_enabled"])
        return policy.active_prompt

    def _pause(self, policy, _actor, _reference, _options):
        policy.generation_enabled = False
        policy.save(update_fields=["generation_enabled"])

    def _reconcile(self, _policy, actor, reference, options):
        if not 0 <= options["actual_micros"] <= MAX_MICROS:
            raise CommandError("Provide a non-negative reconciled amount in USD micros.")
        try:
            reconcile(options["receipt"], options["actual_micros"], reference, actor)
        except StudyHelpSpend.DoesNotExist as error:
            raise CommandError("There is no unresolved receipt with that ID.") from error
