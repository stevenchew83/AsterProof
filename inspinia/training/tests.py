from http import HTTPStatus

import pytest
from django.conf import settings
from django.db import IntegrityError
from django.db import transaction
from django.urls import reverse

from inspinia.pages.models import ProblemSolveRecord
from inspinia.training.forms import TrainingMaterialForm
from inspinia.training.models import TrainingMaterial
from inspinia.training.models import TrainingMaterialProblem
from inspinia.training.models import TrainingSubtopic
from inspinia.training.models import TrainingTopic
from inspinia.training.rendering import render_training_markdown
from inspinia.training.services import TrainingMaterialServiceError
from inspinia.training.services import replace_training_material_problems
from inspinia.training.services import save_material_subtopics
from inspinia.training.services import set_training_material_status
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_MAIN_TOPIC_TOTAL = 4
EXPECTED_SUBTOPIC_TOTAL = 56

EXPECTED_SEED_SUBTOPICS = {
    "ALGEBRA": {
        "Algebraic identities",
        "Equations and systems",
        "Inequalities",
        "Polynomials",
        "Functional equations",
        "Sequences and recurrences",
        "Symmetric and cyclic expressions",
        "Vieta relations and root methods",
        "Algebraic substitutions and transformations",
        "Absolute value and piecewise algebra",
        "Exponential and logarithmic expressions",
        "Optimization and extrema",
        "Complex numbers and roots of unity",
        "Matrices and linear transformations",
    },
    "NUMBER THEORY": {
        "Divisibility",
        "Modular arithmetic",
        "Primes and factorization",
        "Diophantine equations",
        "Orders, residues, and primitive roots",
        "Valuations and LTE-style methods",
        "GCD, LCM, and Euclidean algorithm",
        "Chinese remainder theorem",
        "Fermat, Euler, and Wilson theorems",
        "Quadratic residues and reciprocity",
        "Arithmetic functions",
        "Pell equations and continued fractions",
        "Base representation and digit problems",
        "Infinite descent",
    },
    "GEOMETRY": {
        "Angle chasing",
        "Cyclic quadrilaterals",
        "Similarity and homothety",
        "Power of a point",
        "Inversion",
        "Coordinate, barycentric, and complex geometry",
        "Triangle centers and classical lines",
        "Ceva, Menelaus, and mass points",
        "Tangency and radical axis",
        "Spiral similarity",
        "Area methods",
        "Trigonometric geometry",
        "Projective geometry",
        "Loci and constructions",
    },
    "COMBINATORICS": {
        "Counting techniques",
        "Pigeonhole principle",
        "Invariants and monovariants",
        "Graph theory",
        "Extremal combinatorics",
        "Games and strategies",
        "Double counting",
        "Inclusion-exclusion",
        "Recursion and generating functions",
        "Coloring arguments",
        "Tiling and packing",
        "Ramsey theory",
        "Probabilistic method",
        "Posets and ordering",
    },
}


def _problem(**overrides) -> ProblemSolveRecord:
    values = {
        "contest": "IMO",
        "is_active": True,
        "mohs": 5,
        "problem": "P1",
        "topic": "ALG",
        "topic_tags": "ALG - inequalities",
        "year": 2026,
    } | overrides
    return ProblemSolveRecord.objects.create(
        year=values["year"],
        topic=values["topic"],
        mohs=values["mohs"],
        contest=values["contest"],
        problem=values["problem"],
        contest_year_problem=f"{values['contest']} {values['year']} {values['problem']}",
        is_active=values["is_active"],
        topic_tags=values["topic_tags"],
    )


def _topic(**overrides) -> TrainingTopic:
    values = {
        "code": "LALG",
        "title": "Local Algebra",
        "description": "Algebra training.",
        "sort_order": 10,
    } | overrides
    return TrainingTopic.objects.create(**values)


def _subtopic(topic: TrainingTopic | None = None, **overrides) -> TrainingSubtopic:
    values = {
        "topic": topic or _topic(),
        "title": "Inequalities",
        "description": "Inequality methods.",
        "sort_order": 10,
    } | overrides
    return TrainingSubtopic.objects.create(**values)


def _material(*, author=None, status=TrainingMaterial.Status.DRAFT, **overrides) -> TrainingMaterial:
    values = {
        "title": "Inequality warmup",
        "summary": "A first training module.",
        "body_source": "## Lesson\n\nUse AM-GM.",
        "estimated_minutes": 30,
        "status": status,
        "created_by": author or UserFactory(),
        "updated_by": author or UserFactory(),
    } | overrides
    return TrainingMaterial.objects.create(**values)


def test_training_seed_topics_and_subtopics_exist_once():
    assert TrainingTopic.objects.count() == EXPECTED_MAIN_TOPIC_TOTAL
    assert TrainingSubtopic.objects.filter(is_seeded=True).count() == EXPECTED_SUBTOPIC_TOTAL

    for topic_title, expected_subtopics in EXPECTED_SEED_SUBTOPICS.items():
        expected_topic_title = topic_title.title() if topic_title != "NUMBER THEORY" else "Number Theory"
        topic = TrainingTopic.objects.get(title=expected_topic_title)
        titles = set(topic.subtopics.values_list("title", flat=True))
        assert expected_subtopics <= titles
        assert len(titles) == len(set(titles))


def test_training_topic_and_subtopic_normalize_code_slugs_and_titles():
    topic = TrainingTopic.objects.create(code=" xalg ", title=" Algebra Practice ", sort_order=99)
    subtopic = TrainingSubtopic.objects.create(topic=topic, title="  Vieta Relations  ", sort_order=1)

    assert topic.code == "XALG"
    assert topic.title == "Algebra Practice"
    assert topic.slug == "algebra-practice"
    assert subtopic.title == "Vieta Relations"
    assert subtopic.slug == "vieta-relations"
    assert subtopic.normalized_title == "vieta relations"


def test_training_subtopic_rejects_duplicate_slug_and_normalized_title_within_topic():
    topic = _topic(title="Local Algebra", code="LALG")
    TrainingSubtopic.objects.create(topic=topic, title="Angle Chase", sort_order=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        TrainingSubtopic.objects.create(topic=topic, title=" angle   chase ", sort_order=2)


def test_training_material_status_service_sets_publish_timestamp_once():
    trainer = UserFactory(role=User.Role.TRAINER)
    material = _material(author=trainer)

    set_training_material_status(material, TrainingMaterial.Status.PUBLISHED, actor=trainer)
    material.refresh_from_db()
    first_published_at = material.published_at

    assert material.status == TrainingMaterial.Status.PUBLISHED
    assert first_published_at is not None
    assert material.updated_by == trainer

    set_training_material_status(material, TrainingMaterial.Status.ARCHIVED, actor=trainer)
    material.refresh_from_db()
    assert material.status == TrainingMaterial.Status.ARCHIVED
    assert material.published_at == first_published_at


def test_training_material_problem_sequence_replaces_order_notes_and_rejects_duplicates():
    material = _material()
    first_problem = _problem(problem="P1")
    second_problem = _problem(problem="P2", contest="USAMO", year=2025)

    rows = replace_training_material_problems(
        material,
        [str(second_problem.problem_uuid), str(first_problem.problem_uuid)],
        notes=["Try after reading the proof sketch.", ""],
    )

    assert [row.problem_id for row in rows] == [second_problem.id, first_problem.id]
    assert list(material.practice_problems.order_by("position").values_list("problem_id", "position", "note")) == [
        (second_problem.id, 1, "Try after reading the proof sketch."),
        (first_problem.id, 2, ""),
    ]

    with pytest.raises(TrainingMaterialServiceError, match="more than once"):
        replace_training_material_problems(
            material,
            [str(first_problem.problem_uuid), str(first_problem.problem_uuid)],
        )


def test_training_material_problem_unique_constraints():
    material = _material()
    first_problem = _problem(problem="P1")
    second_problem = _problem(problem="P2", contest="USAMO", year=2025)
    TrainingMaterialProblem.objects.create(material=material, problem=first_problem, position=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        TrainingMaterialProblem.objects.create(material=material, problem=first_problem, position=2)

    with pytest.raises(IntegrityError), transaction.atomic():
        TrainingMaterialProblem.objects.create(material=material, problem=second_problem, position=1)


def test_save_material_subtopics_rejects_inactive_or_missing_subtopics():
    material = _material()
    active_subtopic = _subtopic(title="Power of a point")
    inactive_subtopic = _subtopic(topic=active_subtopic.topic, title="Inactive topic", is_active=False)

    save_material_subtopics(material, [str(active_subtopic.subtopic_uuid)])

    assert list(material.material_subtopics.values_list("subtopic_id", flat=True)) == [active_subtopic.id]

    with pytest.raises(TrainingMaterialServiceError, match="active subtopics"):
        save_material_subtopics(material, [str(inactive_subtopic.subtopic_uuid)])

    with pytest.raises(TrainingMaterialServiceError, match="active subtopics"):
        save_material_subtopics(material, ["00000000-0000-0000-0000-000000000000"])


def test_training_markdown_renderer_sanitizes_html_and_preserves_math():
    html = render_training_markdown(
        "# Inequalities\n\n"
        "Use $a^2+b^2 \\ge 2ab$.\n\n"
        "<script>alert('x')</script>"
        '<a href="javascript:alert(1)" onclick="alert(2)">bad</a>\n\n'
        "[good](https://example.com)",
    )

    assert "<h1>Inequalities</h1>" in html
    assert "$a^2+b^2 \\ge 2ab$" in html
    assert "<script" not in html
    assert "onclick" not in html
    assert "javascript:" not in html
    assert '<a href="https://example.com"' in html


def test_training_material_form_groups_subtopic_choices_by_topic():
    algebra = _topic(title="Local Algebra", code="LALG", sort_order=1)
    geometry = _topic(title="Local Geometry", code="LGEO", sort_order=2)
    algebra_subtopic = _subtopic(algebra, title="Polynomials")
    geometry_subtopic = _subtopic(geometry, title="Inversion")

    form = TrainingMaterialForm()
    grouped_choices = list(form.fields["subtopics"].choices)

    assert ("Local Algebra", [(algebra_subtopic.subtopic_uuid, "Polynomials")]) in grouped_choices
    assert ("Local Geometry", [(geometry_subtopic.subtopic_uuid, "Inversion")]) in grouped_choices


@pytest.mark.parametrize(
    ("url_name", "args"),
    [
        ("training:index", []),
        ("training:manage", []),
    ],
)
def test_training_routes_require_login(client, url_name, args):
    url = reverse(url_name, args=args)

    response = client.get(url)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next={url}"


def test_training_library_requires_app_approval(client):
    user = UserFactory(is_approved=False)
    client.force_login(user)

    response = client.get(reverse("training:index"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("users:approval_pending")


def test_training_library_shows_only_published_materials_to_approved_users(client):
    user = UserFactory()
    topic = _topic(title="Local Algebra", code="LALG")
    subtopic = _subtopic(topic, title="Inequalities")
    published = _material(title="Published module", status=TrainingMaterial.Status.PUBLISHED)
    draft = _material(title="Draft module", status=TrainingMaterial.Status.DRAFT)
    save_material_subtopics(published, [str(subtopic.subtopic_uuid)])
    save_material_subtopics(draft, [str(subtopic.subtopic_uuid)])
    client.force_login(user)

    index_response = client.get(reverse("training:index"))
    topic_response = client.get(reverse("training:topic_detail", args=[topic.slug]))
    subtopic_response = client.get(reverse("training:subtopic_detail", args=[topic.slug, subtopic.slug]))
    detail_response = client.get(reverse("training:material_detail", args=[published.material_uuid, published.slug]))
    draft_response = client.get(reverse("training:material_detail", args=[draft.material_uuid, draft.slug]))

    assert index_response.status_code == HTTPStatus.OK
    index_content = index_response.content.decode()
    assert "Published module" in index_content
    assert "Draft module" not in index_content
    assert topic_response.status_code == HTTPStatus.OK
    assert subtopic_response.status_code == HTTPStatus.OK
    assert detail_response.status_code == HTTPStatus.OK
    assert "Use AM-GM" in detail_response.content.decode()
    assert draft_response.status_code == HTTPStatus.NOT_FOUND


def test_training_curator_pages_allow_trainers_and_reject_normal_users(client):
    trainer = UserFactory(role=User.Role.TRAINER)
    normal_user = UserFactory()
    material = _material(title="Trainer draft", status=TrainingMaterial.Status.DRAFT, author=trainer)

    client.force_login(normal_user)
    denied_response = client.get(reverse("training:manage"))
    denied_publish = client.post(reverse("training:publish", args=[material.material_uuid]))

    assert denied_response.status_code == HTTPStatus.FORBIDDEN
    assert denied_publish.status_code == HTTPStatus.FORBIDDEN

    client.force_login(trainer)
    manage_response = client.get(reverse("training:manage"))
    publish_response = client.post(reverse("training:publish", args=[material.material_uuid]), follow=True)
    material.refresh_from_db()

    assert manage_response.status_code == HTTPStatus.OK
    assert "Trainer draft" in manage_response.content.decode()
    assert publish_response.status_code == HTTPStatus.OK
    assert material.status == TrainingMaterial.Status.PUBLISHED


def test_training_material_create_update_and_problem_sequence_workflow(client):
    trainer = UserFactory(role=User.Role.TRAINER)
    subtopic = _subtopic(title="Graph theory")
    first_problem = _problem(problem="P1")
    second_problem = _problem(problem="P2", contest="USAMO", year=2025)
    client.force_login(trainer)

    create_response = client.post(
        reverse("training:create"),
        {
            "title": "Graph warmup",
            "summary": "Intro graph practice.",
            "body_source": "## Graphs\n\nCount degrees.",
            "estimated_minutes": "25",
            "subtopics": [str(subtopic.subtopic_uuid)],
        },
        follow=True,
    )
    material = TrainingMaterial.objects.get(title="Graph warmup")

    save_response = client.post(
        reverse("training:save_problems", args=[material.material_uuid]),
        {
            "problem_uuid_order": [str(first_problem.problem_uuid), str(second_problem.problem_uuid)],
            "problem_note": ["Warmup", "Challenge"],
        },
        follow=True,
    )

    assert create_response.status_code == HTTPStatus.OK
    assert material.created_by == trainer
    assert list(material.subtopics.values_list("id", flat=True)) == [subtopic.id]
    assert save_response.status_code == HTTPStatus.OK
    assert list(material.practice_problems.order_by("position").values_list("problem_id", "note")) == [
        (first_problem.id, "Warmup"),
        (second_problem.id, "Challenge"),
    ]


def test_training_subtopic_management_allows_custom_subtopics_but_not_seeded_toggle(client):
    trainer = UserFactory(role=User.Role.TRAINER)
    seed_subtopic = TrainingSubtopic.objects.filter(is_seeded=True).first()
    assert seed_subtopic is not None
    client.force_login(trainer)

    create_response = client.post(
        reverse("training:subtopic_create"),
        {
            "topic": seed_subtopic.topic_id,
            "title": "Custom olympiad drill",
            "description": "Trainer-created.",
            "is_active": "on",
        },
        follow=True,
    )
    custom_subtopic = TrainingSubtopic.objects.get(title="Custom olympiad drill")
    toggle_seed_response = client.post(reverse("training:subtopic_toggle", args=[seed_subtopic.subtopic_uuid]))
    toggle_custom_response = client.post(
        reverse("training:subtopic_toggle", args=[custom_subtopic.subtopic_uuid]),
        follow=True,
    )
    custom_subtopic.refresh_from_db()

    assert create_response.status_code == HTTPStatus.OK
    assert custom_subtopic.is_seeded is False
    assert toggle_seed_response.status_code == HTTPStatus.FORBIDDEN
    assert toggle_custom_response.status_code == HTTPStatus.OK
    assert custom_subtopic.is_active is False
