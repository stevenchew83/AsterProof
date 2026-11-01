# ruff: noqa: PLR2004 - HTTP status codes and explicit version numbers are regression assertions.
"""Synthetic package records never confer provider or release authorization."""

import copy
import json
import uuid

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from inspinia.pages.models import ProblemSolveRecord
from inspinia.solutions.problem_evaluation_models import EvaluationPackageApproval
from inspinia.solutions.problem_evaluation_models import ProblemEvaluationPackage
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def curator():
    return UserFactory(role="admin", is_staff=True, is_superuser=True)


@pytest.fixture
def package_content():
    return {
        "schema_version": 1,
        "statement": "For real x, prove x^2 >= 0.",
        "assumptions": ["x is real"],
        "domain": "ALG",
        "level": "Synthetic",
        "images": [],
        "known_pitfalls": [],
        "references": [
            {
                "id": "square",
                "method": "direct",
                "proof": "A real square is nonnegative.",
                "source": "Synthetic test reference; not a human approval",
            },
        ],
        "rubric": None,
    }


@pytest.fixture
def package(curator, package_content):
    problem = ProblemSolveRecord.objects.create(contest="SYNTHETIC", year=2026, problem="P1", topic="ALG")
    return ProblemEvaluationPackage.objects.create(
        problem=problem,
        version=1,
        content=package_content,
        created_by=curator,
    )


def decision(package, curator, value="approved"):
    return EvaluationPackageApproval.objects.create(
        package=package,
        reviewer=curator,
        decision=value,
        notes="Synthetic test action, not real mathematical approval.",
    )


def test_creation_is_pending_and_digest_binds_problem_version_and_content(package, curator):
    assert package.approval_status == "pending"
    assert not EvaluationPackageApproval.objects.exists()
    package.check_integrity()
    next_version = ProblemEvaluationPackage.objects.create(
        problem=package.problem,
        version=2,
        content=copy.deepcopy(package.content),
        created_by=curator,
    )
    assert package.content_digest != next_version.content_digest
    assert next_version.approval_status == "pending"


def test_approval_and_revocation_are_distinct_digest_bound_human_records(package, curator):
    approval = decision(package, curator)
    assert approval.package_digest == package.content_digest
    assert package.approval_status == "approved"
    revocation = decision(package, curator, "revoked")
    assert package.approval_status == "revoked"
    assert list(package.approvals.values_list("pk", flat=True)) == [approval.pk, revocation.pk]
    assert approval.reviewer_id == curator.pk
    assert approval.created_at is not None


@pytest.mark.parametrize("kind", ["package", "approval"])
@pytest.mark.parametrize(
    "operation",
    ["save", "delete", "update", "query_delete", "bulk_update", "bulk_create", "base_update"],
)
def test_standard_orm_cannot_overwrite_or_remove_history(package, curator, kind, operation):
    record = package if kind == "package" else decision(package, curator)
    model = type(record)
    query = model.objects.filter(pk=record.pk)
    operations = {
        "save": record.save,
        "delete": record.delete,
        "update": lambda: query.update(created_at=record.created_at),
        "query_delete": query.delete,
        "bulk_update": lambda: model.objects.bulk_update([record], ["created_at"]),
        "base_update": lambda: model._base_manager.filter(pk=record.pk).update(  # noqa: SLF001
            created_at=record.created_at,
        ),
        "bulk_create": lambda: model.objects.bulk_create([record]),
    }
    with pytest.raises(ValidationError, match="append-only|cannot be deleted|individually"):
        operations[operation]()


def test_package_and_human_identity_relationships_are_protected(package, curator):
    decision(package, curator)
    with pytest.raises(ProtectedError):
        package.problem.delete()
    with pytest.raises(ProtectedError):
        curator.delete()


def test_later_package_version_does_not_inherit_approval(package, curator):
    decision(package, curator)
    new = ProblemEvaluationPackage.objects.create(
        problem=package.problem,
        version=2,
        content=package.content,
        created_by=curator,
    )
    assert new.approval_status == "pending"


def test_package_digest_uses_persisted_problem_identity(package, curator):
    problem = package.problem
    problem.problem_uuid = uuid.uuid4()
    new = ProblemEvaluationPackage.objects.create(
        problem=problem,
        version=2,
        content=package.content,
        created_by=curator,
    )
    new.refresh_from_db()
    new.check_integrity()


def test_database_enforces_unique_problem_version_even_without_model_validation(package, curator):
    duplicate = ProblemEvaluationPackage(
        problem=package.problem,
        version=1,
        content=package.content,
        content_digest=package.content_digest,
        created_by=curator,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        duplicate.save_base(force_insert=True)


def test_duplicate_versions_and_forged_approval_fields_are_rejected(package, curator):
    with pytest.raises(ValidationError):
        ProblemEvaluationPackage.objects.create(
            problem=package.problem,
            version=1,
            content=package.content,
            created_by=curator,
        )
    content = {**package.content, "approval_status": "human_approved"}
    with pytest.raises(ValidationError, match="approval is recorded separately"):
        ProblemEvaluationPackage.objects.create(
            problem=package.problem,
            version=2,
            content=content,
            created_by=curator,
        )


def test_in_memory_mutation_cannot_receive_approval_or_pass_integrity(package, curator):
    package.content["statement"] = "A different statement."
    with pytest.raises(ValidationError, match="digest"):
        package.check_integrity()
    approval = decision(package, curator)
    package.refresh_from_db()
    assert approval.package_digest == package.content_digest
    assert package.approval_status == "approved"


def test_approval_needs_reference_and_nonempty_human_notes(package, curator):
    with pytest.raises(ValidationError):
        EvaluationPackageApproval.objects.create(package=package, reviewer=curator, decision="approved", notes=" ")
    content = copy.deepcopy(package.content)
    content["references"] = []
    empty = ProblemEvaluationPackage.objects.create(
        problem=package.problem,
        version=2,
        content=content,
        created_by=curator,
    )
    with pytest.raises(ValidationError, match="reference solution"):
        decision(empty, curator)
    decision(empty, curator, "rejected")
    assert empty.approval_status == "rejected"


@pytest.mark.parametrize("role", ["learner", "trainer", "moderator"])
def test_model_permissions_alone_do_not_grant_curator_role(package, role):
    user = UserFactory(role=role, is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="solutions"))
    with pytest.raises(PermissionDenied):
        decision(package, user)


def test_curator_needs_explicit_model_permission_and_current_active_role(package):
    user = UserFactory(role="admin", is_staff=True)
    with pytest.raises(PermissionDenied):
        decision(package, user)
    user.user_permissions.add(Permission.objects.get(codename="add_evaluationpackageapproval"))
    decision(package, user)
    type(user).objects.filter(pk=user.pk).update(is_active=False)
    with pytest.raises(PermissionDenied):
        decision(package, user, "revoked")


def test_non_admin_cannot_use_curation_admin_even_with_django_permissions(package, client):
    user = UserFactory(role="trainer", is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="solutions"))
    client.force_login(user)
    for model in ("problemevaluationpackage", "evaluationpackageapproval"):
        assert client.get(reverse(f"admin:solutions_{model}_add")).status_code == 403
    with pytest.raises(PermissionDenied):
        ProblemEvaluationPackage.objects.create(
            problem=package.problem,
            version=2,
            content=package.content,
            created_by=user,
        )


def test_admin_attributes_decision_to_requester_and_requires_confirmation(package, curator, client):
    client.force_login(curator)
    url = reverse("admin:solutions_evaluationpackageapproval_add")
    data = {"package": str(package.pk), "decision": "approved", "notes": "Synthetic HTTP test only."}
    response = client.post(url, data)
    assert response.status_code == 200
    assert not EvaluationPackageApproval.objects.exists()
    response = client.post(url, {**data, "confirm_human_review": "on", "reviewer": "999999"})
    assert response.status_code == 302
    assert EvaluationPackageApproval.objects.get().reviewer_id == curator.pk
    record = EvaluationPackageApproval.objects.get()
    change = reverse("admin:solutions_evaluationpackageapproval_change", args=[record.pk])
    assert client.post(change, {**data, "decision": "revoked"}).status_code == 403
    assert package.approval_status == "approved"


def test_admin_can_create_new_package_without_approving_it(package, curator, client):
    client.force_login(curator)
    url = reverse("admin:solutions_problemevaluationpackage_add")
    assert client.get(url).status_code == 200
    response = client.post(url, {"problem": package.problem_id, "version": 2, "content": json.dumps(package.content)})
    assert response.status_code == 302
    assert ProblemEvaluationPackage.objects.get(version=2).approval_status == "pending"


@pytest.mark.parametrize("kind", ["package", "approval"])
def test_admin_read_only_view_preserves_original_attribution(package, curator, client, kind):
    record = package if kind == "package" else decision(package, curator)
    model_name = "problemevaluationpackage" if kind == "package" else "evaluationpackageapproval"
    actor_field = "created_by_id" if kind == "package" else "reviewer_id"
    viewer = UserFactory(role="admin", is_staff=True, is_superuser=True)
    client.force_login(viewer)
    response = client.get(reverse(f"admin:solutions_{model_name}_change", args=[record.pk]))
    assert response.status_code == 200
    assert getattr(response.context["adminform"].form.instance, actor_field) == curator.pk
    record.refresh_from_db()
    assert getattr(record, actor_field) == curator.pk
