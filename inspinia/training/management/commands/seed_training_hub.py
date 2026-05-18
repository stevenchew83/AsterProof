from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from inspinia.training.models import LevelThreshold
from inspinia.training.models import Material
from inspinia.training.models import Problem
from inspinia.training.models import Subtopic
from inspinia.training.models import Topic

LEVELS = [
    (1, "Euclid Initiate", 0),
    (2, "Hypatia Explorer", 100),
    (3, "Fibonacci Apprentice", 250),
    (4, "Euler Solver", 500),
    (5, "Gauss Strategist", 900),
    (6, "Noether Analyst", 1400),
    (7, "Galois Master", 2100),
    (8, "Ramanujan Sage", 3000),
    (9, "Riemann Visionary", 4200),
    (10, "Grothendieck Legend", 6000),
]

TOPICS = {
    "algebra": {
        "title": "Algebra",
        "description": "Identities, equations, inequalities, polynomials, and structural transformations.",
        "subtopics": [
            "Algebraic identities",
            "Equations and systems",
            "Inequalities",
            "Polynomials",
            "Functional equations",
            "Sequences and recurrences",
        ],
    },
    "number-theory": {
        "title": "Number Theory",
        "description": "Divisibility, modular arithmetic, factorization, Diophantine reasoning, and valuations.",
        "subtopics": [
            "Divisibility",
            "Modular arithmetic",
            "Primes and factorization",
            "Diophantine equations",
            "Orders, residues, and primitive roots",
            "Valuations and LTE-style methods",
        ],
    },
    "geometry": {
        "title": "Geometry",
        "description": "Synthetic and analytic geometry methods for olympiad proof problems.",
        "subtopics": [
            "Angle chasing",
            "Cyclic quadrilaterals",
            "Similarity and homothety",
            "Power of a point",
            "Inversion",
            "Coordinate, barycentric, and complex geometry",
        ],
    },
    "combinatorics": {
        "title": "Combinatorics",
        "description": "Counting, invariants, graph methods, extremal ideas, and game strategies.",
        "subtopics": [
            "Counting techniques",
            "Pigeonhole principle",
            "Invariants and monovariants",
            "Graph theory",
            "Extremal combinatorics",
            "Games and strategies",
        ],
    },
}

OFFICIAL_SOLUTION_PLACEHOLDER = "A complete solution should identify the key invariant or transformation."
SEED_PASSWORDS = {
    "admin": "training-admin",
    "trainer": "training-trainer",
    "student": "training-student",
}


class Command(BaseCommand):
    help = "Seed the Math Olympiad training hub with development data."

    def handle(self, *args, **options) -> None:
        user_model = get_user_model()
        admin = self._user(
            user_model,
            email="training-admin@example.com",
            password=SEED_PASSWORDS["admin"],
            role=user_model.Role.ADMIN,
            name="Training Admin",
            is_staff=True,
            is_superuser=True,
        )
        trainer = self._user(
            user_model,
            email="training-trainer@example.com",
            password=SEED_PASSWORDS["trainer"],
            role=user_model.Role.TRAINER,
            name="Training Trainer",
        )
        self._user(
            user_model,
            email="training-student@example.com",
            password=SEED_PASSWORDS["student"],
            role=user_model.Role.NORMAL,
            name="Training Student",
        )
        for level_number, name, minimum_points in LEVELS:
            LevelThreshold.objects.update_or_create(
                level_number=level_number,
                defaults={"name": name, "minimum_points": minimum_points},
            )

        for topic_order, (topic_slug, topic_data) in enumerate(TOPICS.items(), start=1):
            topic, _created = Topic.objects.update_or_create(
                slug=topic_slug,
                defaults={
                    "description": topic_data["description"],
                    "is_published": True,
                    "order": topic_order,
                    "title": topic_data["title"],
                },
            )
            first_subtopic = None
            for subtopic_order, title in enumerate(topic_data["subtopics"], start=1):
                slug = title.lower().replace(",", "").replace(" ", "-")
                subtopic, _created = Subtopic.objects.update_or_create(
                    topic=topic,
                    slug=slug,
                    defaults={
                        "description": f"Core methods for {title.lower()}.",
                        "is_published": True,
                        "order": subtopic_order,
                        "title": title,
                    },
                )
                first_subtopic = first_subtopic or subtopic
            if first_subtopic is None:
                continue
            Material.objects.update_or_create(
                slug=f"{topic_slug}-starter-notes",
                defaults={
                    "completion_points": 10,
                    "content_markdown": self._material_body(topic.title),
                    "created_by": trainer,
                    "estimated_minutes": 20,
                    "is_published": True,
                    "order": 1,
                    "subtopic": first_subtopic,
                    "title": f"{topic.title} starter notes",
                },
            )
            for problem_order in range(1, 3):
                Problem.objects.update_or_create(
                    slug=f"{topic_slug}-practice-{problem_order}",
                    defaults={
                        "created_by": trainer,
                        "difficulty": Problem.Difficulty.INTRODUCTORY
                        if problem_order == 1
                        else Problem.Difficulty.INTERMEDIATE,
                        "expected_method": first_subtopic.title,
                        "is_published": True,
                        "max_points": 30 + (problem_order * 10),
                        "order": problem_order,
                        "official_solution_markdown": OFFICIAL_SOLUTION_PLACEHOLDER,
                        "source": "AsterProof seed",
                        "statement_markdown": self._problem_body(topic.title, problem_order),
                        "subtopic": first_subtopic,
                        "tags": [topic.title.upper(), first_subtopic.title.upper()],
                        "title": f"{topic.title} practice {problem_order}",
                    },
                )

        self.stdout.write(self.style.SUCCESS("Seeded training hub data."))
        self.stdout.write(f"Admin: {admin.email} / {SEED_PASSWORDS['admin']}")
        self.stdout.write(f"Trainer: {trainer.email} / {SEED_PASSWORDS['trainer']}")
        self.stdout.write(f"Student: training-student@example.com / {SEED_PASSWORDS['student']}")

    def _user(self, user_model, *, email: str, password: str, role: str, name: str, **flags):
        user, created = user_model.objects.get_or_create(
            email=email,
            defaults={
                "is_approved": True,
                "name": name,
                "role": role,
                **flags,
            },
        )
        if not created:
            user.name = name
            user.role = role
            user.is_approved = True
            for key, value in flags.items():
                setattr(user, key, value)
        user.set_password(password)
        user.save()
        return user

    def _material_body(self, topic: str) -> str:
        return (
            f"## {topic} overview\n\n"
            "Read the main examples carefully and rewrite each proof in your own words.\n\n"
            "- Identify the central object.\n"
            "- Track the invariant or transformation.\n"
            "- Finish with a complete proof, not only an answer.\n\n"
            "Use MathJax notation such as $a^2-b^2=(a-b)(a+b)$ when writing notes."
        )

    def _problem_body(self, topic: str, problem_order: int) -> str:
        return (
            f"Let this be a curated {topic.lower()} training problem {problem_order}.\n\n"
            "Prove the stated claim using a clear olympiad-style argument and explain why each step is valid."
        )
