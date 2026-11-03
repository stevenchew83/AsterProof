"""The profile migration preserves every pre-existing row and schema object."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from inspinia.rankings.models import ResultClaim
from inspinia.rankings.models import ResultProfile
from inspinia.users.tests.factories import UserFactory
from scripts.deployment.ranking_analysis_schema_rehearsal import preserved_state

PREVIOUS = ("rankings", "0005_ranking_analysis_review")
TARGET = ("rankings", "0006_student_achievement_profiles")
NEW_TABLES = {"rankings_resultprofile", "rankings_resultclaim"}


@pytest.mark.django_db(transaction=True)
def test_profile_migration_preserves_records_provenance_and_prior_schema():
    executor = MigrationExecutor(connection)
    executor.migrate([PREVIOUS])
    try:
        old = executor.loader.project_state([PREVIOUS]).apps
        actor = UserFactory(role="admin")
        assessment = old.get_model("rankings", "Assessment").objects.create(
            code="PROFILE_MIGRATION_SYNTHETIC", display_name="Synthetic preserved contest", season_year=2026,
        )
        for year, score in [(2012, 0), (2013, 17)]:
            student = old.get_model("rankings", "Student").objects.create(
                full_name="Synthetic Same Name", normalized_name="synthetic same name", birth_year=year,
            )
            result = old.get_model("rankings", "StudentResult").objects.create(
                student_id=student.pk, assessment_id=assessment.pk, raw_score=score, medal="Silver",
                remarks="Family report; national placing not established.",
                source_url="https://example.invalid/synthetic-result", source_file_name="synthetic-source.csv",
            )
        correction = old.get_model("rankings", "RankingCorrection").objects.create(
            created_by_id=actor.pk, reason="Preserved synthetic correction", evidence="Synthetic source",
        )
        old.get_model("rankings", "RankingCorrectionItem").objects.create(
            correction_id=correction.pk, kind="result", target_id=result.pk,
            before={"exists": False}, changes={"medal": "Silver"},
        )
        tables = set(connection.introspection.table_names())
        before = preserved_state(connection, tables)
        executor = MigrationExecutor(connection)
        assert [(migration.app_label, migration.name, backwards) for migration, backwards in
                executor.migration_plan([TARGET])] == [(*TARGET, False)]
        executor.migrate([TARGET])
        assert set(connection.introspection.table_names()) == tables | NEW_TABLES
        after = preserved_state(connection, tables)
        for name in ("rows", "columns", "constraints", "triggers"):
            assert after[name] == before[name], name
        key_width = 2 if connection.vendor == "postgresql" else 1
        keys = {tuple(row[:key_width]) for row in before["sequences"]}
        assert [row for row in after["sequences"] if tuple(row[:key_width]) in keys] == before["sequences"]
        assert after["migrations"][:-1] == before["migrations"]
        assert tuple(after["migrations"][-1][1:3]) == TARGET
        assert not ResultProfile.objects.exists()
        assert not ResultClaim.objects.exists()
    finally:
        MigrationExecutor(connection).migrate([TARGET])
