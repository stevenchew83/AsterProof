from __future__ import annotations

from django.db import connection
from django.db.utils import DatabaseError

from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import TechniqueBenchmarkExportBatch
from inspinia.pages.models import TechniqueBenchmarkImportBatch


def technique_benchmark_schema_status() -> dict[str, object]:
    missing: list[str] = []
    try:
        table_names = set(connection.introspection.table_names())
        benchmark_table = _db_table(TechniqueBenchmark)
        import_batch_table = _db_table(TechniqueBenchmarkImportBatch)
        export_batch_table = _db_table(TechniqueBenchmarkExportBatch)

        if benchmark_table not in table_names:
            missing.append(benchmark_table)
        elif "quality_flags" not in _table_columns(benchmark_table):
            missing.append(f"{benchmark_table}.quality_flags")

        if import_batch_table not in table_names:
            missing.append(import_batch_table)
        elif "export_batch_id" not in _table_columns(import_batch_table):
            missing.append(f"{import_batch_table}.export_batch_id")

        if export_batch_table not in table_names:
            missing.append(export_batch_table)
    except DatabaseError as exc:
        missing.append(str(exc))

    return {
        "ready": not missing,
        "missing": missing,
    }


def _table_columns(table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        return {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }


def _db_table(model_class) -> str:
    return str(model_class._meta.db_table)  # noqa: SLF001
