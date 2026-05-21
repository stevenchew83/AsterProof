from django.db import migrations
from django.utils.text import slugify


TRAINING_TOPIC_SEEDS = [
    {
        "slug": "algebra",
        "title": "Algebra",
        "description": "Equations, inequalities, polynomials, functions, and structural algebraic methods.",
        "order": 10,
        "subtopics": [
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
        ],
    },
    {
        "slug": "number-theory",
        "title": "Number Theory",
        "description": "Divisibility, congruences, primes, residues, valuations, and integer equations.",
        "order": 20,
        "subtopics": [
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
        ],
    },
    {
        "slug": "geometry",
        "title": "Geometry",
        "description": "Synthetic, metric, transformational, and coordinate methods for olympiad geometry.",
        "order": 30,
        "subtopics": [
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
        ],
    },
    {
        "slug": "combinatorics",
        "title": "Combinatorics",
        "description": "Counting, extremal arguments, invariants, graphs, games, and discrete structures.",
        "order": 40,
        "subtopics": [
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
        ],
    },
]


def normalize_seed_title(value: str) -> str:
    return " ".join((value or "").strip().split())


def seed_training_topics(apps, schema_editor) -> None:
    del schema_editor
    Topic = apps.get_model("training", "Topic")
    Subtopic = apps.get_model("training", "Subtopic")
    for topic_payload in TRAINING_TOPIC_SEEDS:
        topic_title = normalize_seed_title(topic_payload["title"])
        topic, _created = Topic.objects.update_or_create(
            slug=topic_payload["slug"],
            defaults={
                "description": topic_payload["description"],
                "is_published": True,
                "order": topic_payload["order"],
                "title": topic_title,
            },
        )
        for index, subtopic_title in enumerate(topic_payload["subtopics"], start=1):
            normalized_title = normalize_seed_title(subtopic_title)
            Subtopic.objects.update_or_create(
                topic=topic,
                slug=slugify(normalized_title),
                defaults={
                    "description": "",
                    "is_published": True,
                    "order": index * 10,
                    "title": normalized_title,
                },
            )


def noop_reverse(apps, schema_editor) -> None:
    del apps, schema_editor


class Migration(migrations.Migration):
    dependencies = [
        ("training", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_training_topics, noop_reverse),
    ]
