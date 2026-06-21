from __future__ import annotations

from django.core.management.base import BaseCommand

from inspinia.pages.models import TOPIC_TAG_LAYER_FIELDS
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.subtopic_cleanup import SUBTOPIC_CLEANUP_BATCH_SIZE
from inspinia.pages.subtopic_cleanup import classified_topic_tag_entries


class Command(BaseCommand):
    help = "Populate structured topic-tag layer fields for existing parsed tag rows."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--batch-size",
            dest="batch_size",
            default=SUBTOPIC_CLEANUP_BATCH_SIZE,
            type=int,
        )

    def handle(self, *args, **options) -> None:
        batch_size = max(int(options["batch_size"]), 1)
        updated_count = 0
        updated_count += self._backfill_model(ProblemTopicTechnique, batch_size=batch_size)
        updated_count += self._backfill_model(StatementTopicTechnique, batch_size=batch_size)
        self.stdout.write(f"Updated {updated_count} parsed tag row(s).")

    def _backfill_model(self, model, *, batch_size: int) -> int:
        pending_rows = []
        updated_count = 0
        rows = (
            model.objects.only("id", "technique", "domains", "raw_tag", *TOPIC_TAG_LAYER_FIELDS)
            .order_by("id")
            .iterator(chunk_size=batch_size)
        )
        for row in rows:
            fields = classified_topic_tag_entries(
                technique=row.technique,
                domains=list(row.domains or []),
                raw_tag=row.raw_tag or row.technique,
            )[0]
            changed = False
            for field_name in TOPIC_TAG_LAYER_FIELDS:
                value = list(fields.get(field_name) or [])
                if getattr(row, field_name, []) != value:
                    setattr(row, field_name, value)
                    changed = True
            if not changed:
                continue
            pending_rows.append(row)
            if len(pending_rows) >= batch_size:
                updated_count += self._flush(model, pending_rows, batch_size=batch_size)
                pending_rows = []

        updated_count += self._flush(model, pending_rows, batch_size=batch_size)
        return updated_count

    def _flush(self, model, rows: list, *, batch_size: int) -> int:
        if not rows:
            return 0
        model.objects.bulk_update(rows, TOPIC_TAG_LAYER_FIELDS, batch_size=batch_size)
        return len(rows)
