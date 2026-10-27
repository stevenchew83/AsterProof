# ruff: noqa: SLF001, S608
"""Invalidate only the derived revision, including bulk and direct source writes.

DDL identifiers are frozen model metadata passed through quote_name; no request
values or external text enter these statements.
"""

from django.db import migrations

SOURCE_MODELS = (
    ("pages", "ContestProblemStatement"),
    ("pages", "ProblemSolveRecord"),
    ("pages", "StatementTopicTechnique"),
    ("pages", "ProblemTopicTechnique"),
    ("pages", "ProblemConceptAssignment"),
    ("pages", "ConceptAssignmentState"),
    ("pages", "CatalogueSubject"),
    ("pages", "CatalogueArea"),
    ("pages", "CatalogueConcept"),
    ("pages", "CatalogueConceptArea"),
    ("pages", "CatalogueConceptRelation"),
    ("pages", "CatalogueConceptAlias"),
    ("solutions", "ProblemSolution"),
    ("solutions", "ProblemSolutionBlock"),
)
FUNCTION = "asterproof_catalogue_revision"


def install(apps, schema_editor):
    q = schema_editor.quote_name
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f"""
CREATE FUNCTION {q(FUNCTION)}() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE relevant_ids bigint[];
BEGIN
  IF TG_TABLE_NAME = 'solutions_problemsolution' THEN
    IF TG_OP = 'INSERT' THEN
      IF NEW.status <> 'published' THEN RETURN NULL; END IF;
    ELSIF TG_OP = 'DELETE' THEN
      IF OLD.status <> 'published' THEN RETURN NULL; END IF;
    ELSIF OLD.status <> 'published' AND NEW.status <> 'published' THEN RETURN NULL; END IF;
  ELSIF TG_TABLE_NAME = 'solutions_problemsolutionblock' THEN
    IF TG_OP = 'INSERT' THEN relevant_ids := ARRAY[NEW.solution_id];
    ELSIF TG_OP = 'DELETE' THEN relevant_ids := ARRAY[OLD.solution_id];
    ELSE relevant_ids := ARRAY[OLD.solution_id, NEW.solution_id]; END IF;
    IF NOT EXISTS (SELECT 1 FROM solutions_problemsolution WHERE id = ANY(relevant_ids) AND status = 'published')
      THEN RETURN NULL; END IF;
  END IF;
  UPDATE pages_cataloguestate SET source_revision = source_revision + 1 WHERE singleton_key = 1;
  RETURN NULL;
END;
$$;
""")
        for app, name in SOURCE_MODELS:
            table = apps.get_model(app, name)._meta.db_table
            schema_editor.execute(
                f"CREATE TRIGGER {q('ap_catalogue_' + table)} AFTER INSERT OR UPDATE OR DELETE ON {q(table)} "
                f"FOR EACH ROW EXECUTE FUNCTION {q(FUNCTION)}()",
            )
        return
    if schema_editor.connection.vendor != "sqlite":
        message = "Catalogue revision triggers require PostgreSQL or SQLite."
        raise NotImplementedError(message)
    for app, name in SOURCE_MODELS:
        model = apps.get_model(app, name)
        table = model._meta.db_table
        for event in ("INSERT", "UPDATE", "DELETE"):
            conditions = []
            if event == "UPDATE":
                conditions.append(
                    "("
                    + " OR ".join(f"OLD.{q(f.column)} IS NOT NEW.{q(f.column)}" for f in model._meta.local_fields)
                    + ")",
                )
            if name == "ProblemSolution":
                refs = ("OLD", "NEW") if event == "UPDATE" else ("OLD",) if event == "DELETE" else ("NEW",)
                conditions.append("(" + " OR ".join(f"{r}.status = 'published'" for r in refs) + ")")
            elif name == "ProblemSolutionBlock":
                refs = (
                    ("OLD.solution_id", "NEW.solution_id")
                    if event == "UPDATE"
                    else ("OLD.solution_id",)
                    if event == "DELETE"
                    else ("NEW.solution_id",)
                )
                conditions.append(
                    "EXISTS (SELECT 1 FROM solutions_problemsolution WHERE status = 'published' AND id IN ("
                    + ",".join(refs)
                    + "))",
                )
            when = " WHEN " + " AND ".join(conditions) if conditions else ""
            schema_editor.execute(
                f"CREATE TRIGGER {q('ap_catalogue_' + table + '_' + event.lower())} AFTER {event} ON {q(table)}{when} "
                "BEGIN UPDATE pages_cataloguestate SET source_revision = source_revision + 1 "
                "WHERE singleton_key = 1; END",
            )


def uninstall(apps, schema_editor):
    q = schema_editor.quote_name
    for app, name in SOURCE_MODELS:
        table = apps.get_model(app, name)._meta.db_table
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(f"DROP TRIGGER IF EXISTS {q('ap_catalogue_' + table)} ON {q(table)}")
        else:
            for event in ("insert", "update", "delete"):
                schema_editor.execute(f"DROP TRIGGER IF EXISTS {q('ap_catalogue_' + table + '_' + event)}")
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f"DROP FUNCTION IF EXISTS {q(FUNCTION)}()")


class Migration(migrations.Migration):
    dependencies = [("pages", "0038_seed_catalogue"), ("solutions", "0003_solution_body_image")]
    operations = [migrations.RunPython(install, uninstall)]
