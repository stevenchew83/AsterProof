"""Frozen, owner-reviewed 308-update Algebra concept normalization plan."""

import hashlib
import json
from pathlib import Path

from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_tag_cleanup import build_cleanup_report
from inspinia.pages.algebra_tag_cleanup import digest
from inspinia.pages.algebra_vocabulary import _benchmark_equivalences

DATA = Path(__file__).parent / "data"
PLAN_PATH = DATA / "algebra_concept_normalization_plan_v1.json"
POLICY_PATH = DATA / "algebra_concept_normalization_policy_v1.json"
PLAN_SHA256 = "cd59dbf69dd7deb13b4dfc794eb5e85ba4570486f23cb6d738e5b7dceb2cd302"
POLICY_SHA256 = "c8de34c731d9d23a845b7faafb70f03c9f266e86359f82530ffd1a09dbdb05f9"
TAG_ACTIONS_SHA256 = "bfebce6deaf2712cff380c66251b2a69b3e91228c60165620f126b64a3bdb17d"
ALIAS_ACTIONS_SHA256 = "d5aac93848f69b9a53e797be78fd23136b318400dbbc335f822c98618560466a"


def load_reviewed_operation():
    plan_bytes, policy_bytes = PLAN_PATH.read_bytes(), POLICY_PATH.read_bytes()
    if (hashlib.sha256(plan_bytes).hexdigest(), hashlib.sha256(policy_bytes).hexdigest()) != (
        PLAN_SHA256, POLICY_SHA256,
    ):
        message = "The packaged normalization differs from the owner-reviewed policy."
        raise AlgebraAliasError(message)
    return json.loads(plan_bytes), json.loads(policy_bytes), PLAN_SHA256


def build_concept_cleanup_report(snapshot, plan, *, policy, plan_sha256):
    conflicts = []
    equivalents, _details = _benchmark_equivalences(snapshot, policy, conflicts)
    report = build_cleanup_report(
        snapshot, plan, policy=policy, plan_sha256=plan_sha256, benchmark_equivalences=equivalents,
    )
    report["conflicts"].extend(conflicts)
    # A changed action set requires a new human review. Zero changes is a valid
    # verification result after the single approved application has completed.
    if report["tag_actions"] or report["alias_actions"]:
        if (digest(report["tag_actions"]), digest(report["alias_actions"])) != (
            TAG_ACTIONS_SHA256, ALIAS_ACTIONS_SHA256,
        ):
            report["conflicts"].append({"type": "OWNER_REVIEWED_ACTIONS_CHANGED"})
    return report
