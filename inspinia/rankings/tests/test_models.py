import pytest
from django.db import IntegrityError

from inspinia.rankings.models import School
from inspinia.rankings.models import Student

pytestmark = pytest.mark.django_db


def test_school_normalizes_name_and_enforces_unique_normalized_name():
    school = School.objects.create(name="  SMK   Seri Indah  ")

    assert school.normalized_name == "smk seri indah"

    with pytest.raises(IntegrityError):
        School.objects.create(name="smk seri indah")


def test_student_external_code_is_unique_when_present():
    student = Student.objects.create(full_name="Alice Tan", external_code="  AST-001  ")

    assert student.external_code == "AST-001"

    with pytest.raises(IntegrityError):
        Student.objects.create(full_name="Bob Lim", external_code="AST-001")


def test_student_external_code_allows_multiple_blank_values():
    first_student = Student.objects.create(full_name="Alice Tan", external_code="")
    second_student = Student.objects.create(full_name="Bob Lim", external_code="   ")

    assert first_student.external_code == ""
    assert second_student.external_code == ""
