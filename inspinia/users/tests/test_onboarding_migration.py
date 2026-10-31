"""Existing accounts keep their landing page; new accounts receive the guide."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_solution_guide_migration_preserves_existing_accounts_and_enrols_new_ones():
    before = [("users", "0008_useraccesssettings")]
    after = [("users", "0009_user_solution_guide_status")]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    old_user = executor.loader.project_state(before).apps.get_model("users", "User")
    existing = old_user.objects.create(email="existing-guide@example.test", name="Existing Learner", is_approved=True)
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_user = executor.loader.project_state(after).apps.get_model("users", "User")
        preserved = new_user.objects.get(pk=existing.pk)
        assert preserved.solution_guide_status == "not_enrolled"
        assert preserved.name == "Existing Learner"
        assert preserved.is_approved
        assert new_user.objects.create(email="new-guide@example.test").solution_guide_status == "active"
        legacy_created = old_user.objects.create(email="legacy-code-guide@example.test")
        assert new_user.objects.get(pk=legacy_created.pk).solution_guide_status == "not_enrolled"
    finally:
        MigrationExecutor(connection).migrate(after)
