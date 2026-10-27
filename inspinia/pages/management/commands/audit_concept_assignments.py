"""Read-only four-subject traces and immutable, bounded review bundles."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection
from django.db import transaction

from inspinia.pages.concept_assignment_registry import REGISTRY
from inspinia.pages.concept_assignment_registry import digest
from inspinia.pages.concept_assignment_service import MAX_BATCH
from inspinia.pages.concept_assignment_service import audit_sources
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.concept_assignment_trace import source_uuid_query
from inspinia.pages.concept_assignment_views import report_csv


class Command(BaseCommand):
    help = "Read-only provenance audit; optional new output directory contains reports of at most 250 problems."

    def add_arguments(self, parser):
        parser.add_argument("--subject", choices=("Algebra", "Number Theory", "Geometry", "Combinatorics"), default="")
        parser.add_argument("--problem-uuid", action="append", default=[])
        parser.add_argument("--output-directory", type=Path)

    def handle(self, *args, **options):
        reports = []
        directory = options["output_directory"]
        if directory:
            directory.mkdir(parents=True, exist_ok=False)
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = '15s'")
                    cursor.execute("SET LOCAL lock_timeout = '1s'")
            values = options["problem_uuid"] or list(source_uuid_query(subject=options["subject"]))
            for start in range(0, len(values), MAX_BATCH):
                report = audit_sources(load_sources(values[start : start + MAX_BATCH]))
                reports.append(
                    {
                        "batch": start // MAX_BATCH + 1,
                        "sha256": report["sha256"],
                        "problems": report["problems"],
                        "changes": len(report["changes"]),
                        "conflicts": len(report["conflicts"]),
                        "counts": report["counts"],
                    },
                )
                if directory:
                    name = f"batch-{start // MAX_BATCH + 1:05d}"
                    (directory / (name + ".json")).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
                    (directory / (name + ".csv")).write_text(report_csv(report))
        summary = {
            "version": 1,
            "mode": "dry-run",
            "registry_fingerprint": REGISTRY.fingerprint,
            "problems": sum(r["problems"] for r in reports),
            "changes": sum(r["changes"] for r in reports),
            "conflicts": sum(r["conflicts"] for r in reports),
            "batches": reports,
            "source_writes": 0,
        }
        summary["sha256"] = digest(summary)
        if directory:
            (directory / "audit-report.json").write_text(json.dumps(summary, indent=2) + "\n")
            (directory / "identity-proposals.json").write_text(
                json.dumps(REGISTRY.identity_proposals(), indent=2) + "\n",
            )
        self.stdout.write(json.dumps(summary))
