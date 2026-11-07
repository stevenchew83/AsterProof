"""Execute an explicitly authorized, frozen Study Help sample under the site budget."""

# ruff: noqa: EM101, EM102, PLR2004, TRY003, TRY301

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.study_help import budget_available
from inspinia.pages.study_help import locked_account
from inspinia.pages.study_help import pricing_ready
from inspinia.pages.study_help_access import assistance_restricted
from inspinia.pages.study_help_access import lock_study_help
from inspinia.pages.study_help_access import source_problem
from inspinia.pages.study_help_access import statement_revision
from inspinia.pages.study_help_models import StudyHelpAction
from inspinia.pages.study_help_models import StudyHelpPolicy
from inspinia.pages.study_help_models import StudyHelpPrompt
from inspinia.pages.study_help_models import StudyHelpSpend
from inspinia.pages.study_help_provider import ProviderResult
from inspinia.pages.study_help_provider import call_provider
from inspinia.pages.study_help_provider import cost_micros
from inspinia.pages.study_help_provider import input_messages
from inspinia.pages.study_help_provider import maximum_tokens
from inspinia.pages.study_help_provider import profile_digest
from inspinia.pages.study_help_provider import validate_result
from inspinia.pages.study_help_qualification import load_fixtures
from inspinia.pages.study_help_worker import finish
from inspinia.users.roles import user_has_admin_role


@transaction.atomic
def _claim(prompt, fixture, action, prior, manifest):
    lock_study_help()
    policy = StudyHelpPolicy.objects.filter(pk=1).first()
    now = timezone.now()
    statement = ContestProblemStatement.objects.select_for_update().filter(pk=fixture.pk).first()
    actor = locked_account(manifest["actor"].pk)
    if (
        not settings.STUDY_HELP_EVALUATION_ENABLED
        or not settings.STUDY_HELP_OPENAI_API_KEY
        or not pricing_ready(policy)
        or actor is None
        or not actor.is_active
        or not user_has_admin_role(actor)
        or policy.generation_enabled
        or profile_digest(prompt, policy.model) != manifest["profile_digest"]
        or now >= manifest["expires"]
        or statement is None
        or source_problem(statement)
        or statement_revision(statement) != statement_revision(fixture)
        or assistance_restricted(actor, (statement.problem_uuid,), statement_uuid=statement.statement_uuid)
    ):
        raise CommandError("The approved evaluation scope, configuration, or archive source changed.")
    if StudyHelpSpend.objects.filter(state=StudyHelpSpend.State.DISPATCHED).exists():
        raise CommandError("A provider request is already in flight.")
    identity = ":".join((manifest["batch"], str(statement.statement_uuid), action))
    key = sha256(identity.encode()).hexdigest()
    if StudyHelpSpend.objects.filter(evaluation_key=key).exists():
        raise CommandError("This approved sample attempt already exists. Reconcile it before requesting further work.")
    payload = input_messages(action, statement.statement_latex, prompt, prior)
    pricing = {"input_price": policy.input_price, "output_price": policy.output_price}
    reserve = cost_micros(*maximum_tokens(action, payload), pricing)
    used = StudyHelpSpend.objects.filter(evaluation_batch=manifest["batch"])
    if used.exclude(evaluation_manifest=manifest["digest"]).exists() or pricing != manifest["pricing"]:
        raise CommandError("The approved manifest or pricing changed.")
    committed = sum(item.actual_micros if item.actual_micros is not None else item.reserved_micros for item in used)
    if (
        reserve > policy.request_cap
        or committed + reserve > manifest["budget_micros"]
        or not budget_available(policy, reserve)
    ):
        raise CommandError("The next attempt exceeds the approved evaluation budget.")
    receipt = StudyHelpSpend.objects.create(
        **pricing,
        reserved_micros=reserve,
        state=StudyHelpSpend.State.DISPATCHED,
        dispatched_at=now,
        evaluation_key=key,
        evaluation_batch=manifest["batch"],
        evaluation_manifest=manifest["digest"],
    )
    return receipt, policy.model, payload


class Command(BaseCommand):
    help = "Run a reviewed archive-only sample. Redirect output to an approved private evidence file."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--approval-ref", required=True)
        parser.add_argument("--operator-id", type=int, required=True)

    def handle(self, *args, **options):
        if not settings.STUDY_HELP_EVALUATION_ENABLED or not settings.STUDY_HELP_OPENAI_API_KEY:
            raise CommandError("Paid Study Help evaluation is disabled.")
        path = options["manifest"]
        approval = options["approval_ref"].strip()
        if not 0 < len(approval) <= 120 or path.stat().st_size > 64_000:
            raise CommandError("Provide a bounded approval reference and manifest.")
        actor = get_user_model().objects.filter(pk=options["operator_id"], is_active=True).first()
        if not user_has_admin_role(actor):
            raise CommandError("Use an active AsterProof administrator.")
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        if digest != options["manifest_sha256"]:
            raise CommandError("The manifest does not match the approved digest.")
        try:
            manifest = json.loads(raw)
            expires = parse_datetime(manifest["expires"])
            if (
                expires is None
                or timezone.is_naive(expires)
                or expires <= timezone.now()
                or type(manifest["budget_micros"]) is not int
                or not 0 < manifest["budget_micros"] <= 1_000_000_000_000
            ):
                raise ValueError
            manifest.update(expires=expires, actor=actor, digest=digest, batch=sha256(approval.encode()).hexdigest())
            prompt = StudyHelpPrompt.objects.get(pk=UUID(manifest["prompt"]))
            fixtures = load_fixtures(manifest["fixtures"])
        except (ValidationError, ValueError, TypeError, KeyError, StudyHelpPrompt.DoesNotExist) as error:
            raise CommandError("Invalid or expired approved sample manifest.") from error

        for statement, row in fixtures:
            hint = self._attempt(prompt, statement, StudyHelpAction.HINT, None, manifest)
            if hint:
                self._attempt(prompt, statement, StudyHelpAction.STRONGER_HINT, hint, manifest)
            proof = self._attempt(prompt, statement, StudyHelpAction.SOLUTION, None, manifest)
            if proof and row["alternative"]:
                self._attempt(prompt, statement, StudyHelpAction.ALTERNATIVE, proof, manifest)

    def _attempt(self, prompt, statement, action, prior, manifest):
        receipt, model, payload = _claim(prompt, statement, action, prior, manifest)
        try:
            result = call_provider(model, action, payload, evaluation=True)
        except Exception:  # noqa: BLE001 - never print provider exceptions or redispatch.
            result = ProviderResult(error="provider_uncertain")
        disposition = finish(receipt.pk, result)
        if disposition != "evaluation":
            raise CommandError(f"Evaluation receipt {receipt.pk} requires reconciliation.")
        receipt.refresh_from_db()
        if receipt.actual_micros > receipt.reserved_micros:
            raise CommandError(f"Evaluation receipt {receipt.pk} exceeded its reservation.")
        body, method, error = validate_result(action, result, prior)
        self.stdout.write(
            json.dumps(
                {
                    "receipt": str(receipt.pk),
                    "statement_uuid": str(statement.statement_uuid),
                    "revision": statement_revision(statement),
                    "profile_digest": manifest["profile_digest"],
                    "action": action,
                    "body": body,
                    "method": method,
                    "error": error,
                },
                ensure_ascii=False,
            ),
        )
        return SimpleNamespace(body=body, method=method) if body else None
