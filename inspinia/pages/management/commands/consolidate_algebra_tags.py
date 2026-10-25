"""Audited consolidation of reviewed Algebra subtopic and method synonyms."""

import hashlib
import json

from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_vocabulary import VOCABULARY_PATH
from inspinia.pages.algebra_vocabulary import build_vocabulary_report
from inspinia.pages.algebra_vocabulary import load_vocabulary_plan
from inspinia.pages.algebra_vocabulary import vocabulary_operation_plan
from inspinia.pages.algebra_vocabulary import vocabulary_sha256
from inspinia.pages.management.commands.cleanup_algebra_tags import Command as ReviewedCleanupCommand


class Command(ReviewedCleanupCommand):
    help = "Dry-run the reviewed Algebra vocabulary consolidation; apply requires the exact reviewed report hash."
    report_builder = staticmethod(build_vocabulary_report)

    def add_arguments(self, parser) -> None:
        super().add_arguments(parser)
        parser.set_defaults(plan=VOCABULARY_PATH)

    def load_operation(self, options: dict) -> tuple:
        plan_bytes = options["plan"].read_bytes()
        plan_sha = hashlib.sha256(plan_bytes).hexdigest()
        if plan_sha != vocabulary_sha256():
            message = "The plan hash does not match the packaged vocabulary policy."
            raise AlgebraAliasError(message)
        policy = json.loads(plan_bytes)
        if policy != load_vocabulary_plan():
            message = "The vocabulary policy changed during this operation."
            raise AlgebraAliasError(message)
        return vocabulary_operation_plan(policy), policy, plan_sha

    def report_summary(self, report: dict) -> dict:
        return {
            **super().report_summary(report),
            "vocabulary_before": report["vocabulary_before"],
            "vocabulary_after": report["vocabulary_after"],
            "affected_problem_uuids": report["affected_problem_uuids"],
        }
