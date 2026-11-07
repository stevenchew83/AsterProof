from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deployment.newsletter_schedule import render_units


def contract(**changes):
    return SimpleNamespace(**{
        "service": "asterproof.service", "app_user": "asterproof",
        "release_root": Path("/srv/asterproof-managed"), "environment_file": Path("/var/lib/asterproof/environment"),
        **changes,
    })


def test_newsletter_units_use_current_external_environment_and_stop_with_app():
    units = render_units(contract())
    service = units["asterproof-newsletter.service"]
    assert "WorkingDirectory=/srv/asterproof-managed/current\n" in service
    assert "EnvironmentFile=/var/lib/asterproof/environment\n" in service
    assert "Requisite=asterproof.service\n" in service
    assert "PartOf=asterproof.service\n" in service
    assert "Requires=" not in service  # Never start the drained app during maintenance.
    assert "process_newsletters --max-messages=20 --seconds=50\n" in service
    assert "NoNewPrivileges=true\n" in service
    assert "OnUnitInactiveSec=60s\n" in units["asterproof-newsletter.timer"]
    assert all("@" not in text for text in units.values())


@pytest.mark.parametrize("user", ["root\nUser=other", "user name", "user%U"])
def test_unit_substitution_cannot_inject_directives(user):
    with pytest.raises(ValueError, match="substitutions"):
        render_units(contract(app_user=user))


def test_admin_review_worker_uses_the_same_runtime_and_bounded_non_overlapping_schedule():
    units = render_units(contract(), admin_reviews=True)
    service = units["asterproof-admin-solution-reviews.service"]
    timer = units["asterproof-admin-solution-reviews.timer"]
    assert "Requisite=asterproof.service\n" in service
    assert "PartOf=asterproof.service\n" in service
    assert "User=asterproof\n" in service
    assert "EnvironmentFile=/var/lib/asterproof/environment\n" in service
    assert "WorkingDirectory=/srv/asterproof-managed/current\n" in service
    assert "manage.py process_admin_solution_reviews\n" in service
    assert "TimeoutStartSec=320s\n" in service
    assert "Unit=asterproof-admin-solution-reviews.service\n" in timer
    assert "OnUnitInactiveSec=60s\n" in timer
    assert all("@" not in text for text in units.values())
