from __future__ import annotations

from collections import defaultdict

from django.db import migrations
from django.db import models
from django.utils.text import slugify


IMO_SYLLABUS_SUBTOPICS = [
    ("algebra", "Functional Equations", "What it means to solve (structure, fixed points, verification)", "CORE"),
    (
        "algebra",
        "Functional Equations",
        "Cauchy equation linearity under regularity (monotone/bounded/continuous)",
        "CORE",
    ),
    ("algebra", "Functional Equations", "Monotonicity & one-sided limits for FE checks", "CORE"),
    ("algebra", "Polynomials", "Division algorithm; factor/roots/remainder theorems", "CORE"),
    ("algebra", "Polynomials", "Quadratics; Vieta relations; rational/integer root tests", "CORE"),
    ("algebra", "Polynomials", "Classic factorizations (Sophie Germain, x³+y³+z³−3xyz, etc.)", "CORE"),
    ("algebra", "Polynomials", "Multiple roots & derivative zeros", "CORE"),
    ("algebra", "Polynomials", "P(a)−P(b) divisible by a−b", "CORE"),
    ("algebra", "Polynomials", "Euclidean algorithm over ℚ/ℝ", "CORE"),
    ("algebra", "Polynomials", "Elementary symmetric polynomials", "CORE"),
    ("algebra", "Polynomials", "Root counts (≤ degree; odd degree ⇒ real root)", "CORE"),
    ("algebra", "Polynomials", "Real factorization into linear/quadratic factors", "CORE"),
    ("algebra", "Polynomials", "Homogeneity & degree bookkeeping", "CORE"),
    ("algebra", "Polynomials", "Eisenstein criterion", "CORE"),
    ("algebra", "Polynomials", "Lagrange interpolation", "CORE"),
    (
        "algebra",
        "Sequences & Recurrences",
        "Arithmetic/geometric sequences; periodic/bounded/monotone/eventual behavior",
        "CORE",
    ),
    (
        "algebra",
        "Sequences & Recurrences",
        "Invariants; telescoping; finite differences/difference operator",
        "CORE",
    ),
    ("algebra", "Inequalities", "Triangle inequality; sums of squares ≥ 0", "CORE"),
    ("algebra", "Inequalities", "(De)homogenization; normalization tricks", "CORE"),
    ("algebra", "Inequalities", "Rearrangement inequality", "CORE"),
    ("algebra", "Inequalities", "RMS–AM–GM–HM chain; Bernoulli; Cauchy–Schwarz", "CORE"),
    ("algebra", "Inequalities", "Maclaurin & Newton inequalities", "CORE"),
    (
        "algebra",
        "Algebraic Manipulation",
        "Radicals/fractions; simultaneous equations; exponent laws",
        "CORE",
    ),
    ("algebra", "Permutations & Symmetry", "Parity, transpositions, cycle form", "CORE"),
    ("algebra", "Vectors", "Dot/cross products; scalar triple product", "CORE"),
    ("combinatorics", "Counting & Identities", "Basic counting; double counting; Venn & PIE", "CORE"),
    (
        "combinatorics",
        "Counting & Identities",
        "Stars and bars; binomial/trinomial/multinomial coefficients & identities",
        "CORE",
    ),
    (
        "combinatorics",
        "Pigeonhole & Invariants",
        "Parity arguments; pigeonhole; extremal/mean value principles",
        "CORE",
    ),
    (
        "combinatorics",
        "Pigeonhole & Invariants",
        "Invariants & semi-invariants (construction/proof)",
        "CORE",
    ),
    (
        "combinatorics",
        "Graph Theory",
        "Handshake lemma; degrees; connectedness; trees/forests; planarity basics",
        "CORE",
    ),
    (
        "combinatorics",
        "Graph Theory",
        "Eulerian/Hamiltonian notions (definitions & simple criteria)",
        "CORE",
    ),
    ("combinatorics", "Graph Theory", "Small Ramsey cases", "CORE"),
    (
        "combinatorics",
        "Coloring & Tilings",
        "Vertex/edge/face colorings; tilings; classic logic puzzles",
        "CORE",
    ),
    ("combinatorics", "Geometry-Flavored Tools", "Euler characteristic; Platonic solids", "CORE"),
    (
        "geometry",
        "Triangles & Basics",
        "Triangle taxonomy; similarity & congruence; symmetry/reflective ideas",
        "CORE",
    ),
    ("geometry", "Angle Chasing", "Core angle-chasing techniques", "CORE"),
    (
        "geometry",
        "Transformations (Elementary)",
        "Translations, reflections, rotations, homothety",
        "CORE",
    ),
    (
        "geometry",
        "Circles (Core)",
        "Equal subtended angles; center vs circumference; tangents; chord bisectors; alternate segment; Thales; cyclic quadrilaterals",
        "CORE",
    ),
    ("geometry", "Circles (Power)", "Power of a Point; radical axis & radical center", "CORE"),
    (
        "geometry",
        "Triangle Centers & Lines",
        "O, G, H, I, excenters, N; nine-point circle; Euler line",
        "CORE",
    ),
    (
        "geometry",
        "Triangle Centers & Lines",
        "OI²=R²−2Rr; OH²=9R²−(a²+b²+c²) identities",
        "CORE",
    ),
    ("geometry", "Triangle Centers & Lines", "Reflection properties of H", "CORE"),
    (
        "geometry",
        "Bisectors & Ratios",
        "Internal/external angle bisectors; incenter–excenter lemma",
        "CORE",
    ),
    ("geometry", "Lines & Cevians", "Menelaus; Ceva; van Aubel (ratio tools)", "CORE"),
    ("geometry", "Triangle Geometry", "Excircles; Heron’s formula", "CORE"),
    ("geometry", "Triangle Geometry", "Symmedians; isogonal/isotomic conjugates", "CORE"),
    ("geometry", "Triangle Geometry", "Apollonius & Stewart theorems", "CORE"),
    ("geometry", "Vector Geometry", "Vector methods in the plane", "CORE"),
    (
        "geometry",
        "Tangency & Quadrilaterals",
        "Tangents to two circles; quadrilateral taxonomy; Simson line",
        "CORE",
    ),
    (
        "number-theory",
        "Divisibility & Primes",
        "Divisibility; gcd/lcm; Euclid’s algorithm; Bézout; infinite primes; unique factorization",
        "CORE",
    ),
    ("number-theory", "Congruences", "Solving congruences; choosing moduli; congruence classes", "CORE"),
    ("number-theory", "Modular Arithmetic", "Multiplicative group mod prime", "CORE"),
    ("number-theory", "Classic Theorems", "Fermat’s little theorem; Euler’s theorem", "CORE"),
    ("number-theory", "Arithmetic Functions", "Euler φ(n); τ(n) behavior; σ_k basics", "CORE"),
    ("number-theory", "Tests & Identities", "Wilson’s theorem; digit-sum congruences", "CORE"),
    ("number-theory", "CRT & Applications", "Chinese Remainder Theorem", "CORE"),
    ("number-theory", "Valuations", "p-adic valuation v_p (basics & parity tricks)", "CORE"),
    (
        "number-theory",
        "Multiplicative Functions",
        "μ(n) and σ_k(n) (properties & convolution)",
        "CORE",
    ),
    (
        "number-theory",
        "Proof Techniques",
        "Induction (complete), minimal counterexample, infinite descent",
        "CORE",
    ),
    (
        "number-theory",
        "Diophantine Classics",
        "Pythagorean triples; irrationality of √n; (awareness of e, π)",
        "CORE",
    ),
    ("algebra", "Polynomials", "Descartes’ rule of signs", "ADVANCED"),
    ("algebra", "Sequences & Recurrences", "Linear recurrences (theory and solving)", "ADVANCED"),
    (
        "algebra",
        "Sequences & Recurrences",
        "Generating functions (ordinary/exponential, basic uses)",
        "ADVANCED",
    ),
    ("algebra", "Inequalities", "Power means; Chebyshev", "ADVANCED"),
    ("algebra", "Inequalities", "Jensen; weighted Jensen", "ADVANCED"),
    ("algebra", "Inequalities", "Muirhead & majorization (HLP)", "ADVANCED"),
    ("algebra", "Inequalities", "Schur; Hölder; Minkowski", "ADVANCED"),
    (
        "algebra",
        "Inequalities",
        "Popoviciu; “convex ⇒ maxima at endpoints” heuristics",
        "ADVANCED",
    ),
    (
        "algebra",
        "Complex Numbers (Extension)",
        "z=x+iy, re^{iθ}; geometric meaning of + and ×; De Moivre",
        "ADVANCED",
    ),
    (
        "algebra",
        "Complex Numbers (Extension)",
        "Triangle inequality; conjugation & norm N(z)=z\\bar z",
        "ADVANCED",
    ),
    (
        "algebra",
        "Complex Numbers (Extension)",
        "Locating polynomial roots; FTA assumed",
        "ADVANCED",
    ),
    ("combinatorics", "Graph Theory", "Dirac’s Hamiltonicity criterion", "ADVANCED"),
    ("combinatorics", "Algebraic/Group Methods", "Burnside’s lemma & Pólya enumeration", "ADVANCED"),
    (
        "combinatorics",
        "Algebraic/Polynomial Methods",
        "Combinatorial Nullstellensatz",
        "ADVANCED",
    ),
    ("combinatorics", "Lattice & Planar", "Pick’s theorem", "ADVANCED"),
    ("combinatorics", "Matchings & Flows", "Hall’s marriage theorem; Kőnig’s theorem", "ADVANCED"),
    (
        "combinatorics",
        "Games & Strategies",
        "Nim and nim-sum; impartial games; strategy invariants",
        "ADVANCED",
    ),
    (
        "combinatorics",
        "Classics & Constructions",
        "Erdős–Szekeres variants; knight tours; Conway’s soldiers",
        "ADVANCED",
    ),
    ("geometry", "Circles (Advanced)", "Ptolemy (incl. inequality)", "ADVANCED"),
    ("geometry", "Circles (Advanced)", "“Eyeball” theorem; arc–angle refinements", "ADVANCED"),
    ("geometry", "Triangle Centers & Lines", "Humpty/Dumpty/Queue lemmas", "ADVANCED"),
    ("geometry", "Bisectors & Ratios", "Apollonius circle; orthogonal circles", "ADVANCED"),
    ("geometry", "Special Quadrilaterals", "Tangential & bicentric quadrilaterals", "ADVANCED"),
    (
        "geometry",
        "Centers/Configurations (Advanced)",
        "Miquel point; Descartes’ four circles",
        "ADVANCED",
    ),
    ("geometry", "Classical Theorems (Advanced)", "Butterfly; Monge", "ADVANCED"),
    (
        "geometry",
        "Mechanics Link (Advanced)",
        "Huygens–Steiner/parallel-axis theorem (geometric use)",
        "ADVANCED",
    ),
    ("geometry", "Transformations (Advanced)", "Inversion (theory & applications)", "ADVANCED"),
    (
        "geometry",
        "Transformations (Advanced)",
        "Affine transformations (area/ratio invariants)",
        "ADVANCED",
    ),
    (
        "geometry",
        "Transformations (Projective)",
        "Desargues/Pascal/Brianchon; cross-ratio; pole–polar",
        "ADVANCED",
    ),
    (
        "geometry",
        "Complex Methods (Extension)",
        "Complex plane geometry; Möbius transformations (incl. unit-disk maps)",
        "ADVANCED",
    ),
    ("number-theory", "Proof Techniques", "Vieta jumping", "ADVANCED"),
    ("number-theory", "Pell & Quadratic Forms", "Pell equations", "ADVANCED"),
    (
        "number-theory",
        "Lifting & Primes",
        "Lifting-the-Exponent (LTE); Hensel-type lifting",
        "ADVANCED",
    ),
    (
        "number-theory",
        "Primitive Roots & Orders",
        "Structure of (ℤ/nℤ)^×; primitive roots",
        "ADVANCED",
    ),
    (
        "number-theory",
        "Quadratic Reciprocity",
        "Legendre/Jacobi symbols; quadratic reciprocity",
        "ADVANCED",
    ),
    ("number-theory", "Sum of Squares", "Fermat two-squares; Lagrange four-squares", "ADVANCED"),
    ("number-theory", "Sequences & Farey", "Farey sequences & neighbors", "ADVANCED"),
    ("number-theory", "Zsigmondy & Primitive Divisors", "Zsigmondy’s theorem", "ADVANCED"),
    ("number-theory", "Analytic Glimpses", "Prime Number Theorem (statement/uses)", "ADVANCED"),
    (
        "number-theory",
        "Analytic Glimpses",
        "Dirichlet’s theorem on primes in AP (statement/uses)",
        "ADVANCED",
    ),
    (
        "number-theory",
        "Quadratic Integer Rings (Extension)",
        "Gaussian integers ℤ[i]; UFD & Gaussian primes",
        "ADVANCED",
    ),
    (
        "number-theory",
        "Quadratic Integer Rings (Extension)",
        "Fermat two-squares via ℤ[i]",
        "ADVANCED",
    ),
    ("number-theory", "Exponential Sums (Extension)", "Gauss sums (awareness)", "ADVANCED"),
    ("algebra", "Polynomials", "Sturm sequences", "EXCEPTIONAL"),
    ("algebra", "Polynomials", "Gauss’s content theorem", "EXCEPTIONAL"),
    ("algebra", "Polynomials", "Multivariate factorization methods", "EXCEPTIONAL"),
    ("algebra", "Inequalities", "Taylor-expansion based estimates", "EXCEPTIONAL"),
    ("algebra", "Fields & Structures", "Finite fields (basic facts)", "EXCEPTIONAL"),
    (
        "algebra",
        "Fields & Structures",
        "Bézout/EUCLID in general fields (abstract setting)",
        "EXCEPTIONAL",
    ),
    (
        "combinatorics",
        "Graph Theory",
        "Euler trail/path algorithms (algorithmic focus)",
        "EXCEPTIONAL",
    ),
    ("combinatorics", "Order/Posets", "Dilworth’s theorem", "EXCEPTIONAL"),
    ("combinatorics", "Optimization Problems", "Traveling Salesman Problem (TSP)", "EXCEPTIONAL"),
    (
        "geometry",
        "Transformations (Exceptional)",
        "Projective transformations (general theory)",
        "EXCEPTIONAL",
    ),
    ("geometry", "Complex/Coordinates (Exceptional)", "Barycentric coordinates", "EXCEPTIONAL"),
    (
        "geometry",
        "Complex/Coordinates (Exceptional)",
        "Complex numbers in geometry; quaternions (awareness)",
        "EXCEPTIONAL",
    ),
    ("geometry", "Special Porisms (Exceptional)", "Poncelet & Steiner porisms", "EXCEPTIONAL"),
    (
        "geometry",
        "Notable Points (Exceptional)",
        "Brocard, Napoleon, Morley, Gergonne/Nagel, symmedian point (deep properties)",
        "EXCEPTIONAL",
    ),
    (
        "number-theory",
        "Partitions & Additive NT",
        "Integer partitions (Hardy–Ramanujan flavor awareness)",
        "EXCEPTIONAL",
    ),
]


def normalize_title(value: str) -> str:
    return " ".join((value or "").strip().split()).casefold()


def unique_slug(title: str, used_slugs: set[str]) -> str:
    base = slugify(title)[:180].strip("-") or "imo-subtopic"
    candidate = base
    suffix = 2
    while candidate in used_slugs:
        label = f"-{suffix}"
        candidate = f"{base[: 180 - len(label)].rstrip('-')}{label}"
        suffix += 1
    used_slugs.add(candidate)
    return candidate


def seed_imo_syllabus_subtopics(apps, schema_editor) -> None:
    del schema_editor
    Topic = apps.get_model("training", "Topic")
    Subtopic = apps.get_model("training", "Subtopic")

    topic_by_slug = {topic.slug: topic for topic in Topic.objects.filter(slug__in={row[0] for row in IMO_SYLLABUS_SUBTOPICS})}
    seen_titles_by_topic = defaultdict(set)
    used_slugs_by_topic = defaultdict(set)
    max_order_by_topic = defaultdict(int)
    next_index_by_topic = defaultdict(int)

    for subtopic in Subtopic.objects.filter(topic__slug__in=topic_by_slug).select_related("topic"):
        topic_slug = subtopic.topic.slug
        seen_titles_by_topic[topic_slug].add(normalize_title(subtopic.title))
        used_slugs_by_topic[topic_slug].add(subtopic.slug)
        max_order_by_topic[topic_slug] = max(max_order_by_topic[topic_slug], subtopic.order)

    for topic_slug, category, title, level in IMO_SYLLABUS_SUBTOPICS:
        topic = topic_by_slug.get(topic_slug)
        if topic is None:
            continue
        normalized_title = normalize_title(title)
        if normalized_title in seen_titles_by_topic[topic_slug]:
            continue
        next_index_by_topic[topic_slug] += 1
        seen_titles_by_topic[topic_slug].add(normalized_title)
        Subtopic.objects.create(
            topic=topic,
            title=title,
            slug=unique_slug(title, used_slugs_by_topic[topic_slug]),
            category=category,
            level=level,
            is_imo_syllabus=True,
            is_published=True,
            order=max_order_by_topic[topic_slug] + (next_index_by_topic[topic_slug] * 10),
            description="",
        )


def noop_reverse(apps, schema_editor) -> None:
    del apps, schema_editor


class Migration(migrations.Migration):
    dependencies = [
        ("training", "0002_seed_training_topics"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subtopic",
            name="slug",
            field=models.SlugField(max_length=180),
        ),
        migrations.AddField(
            model_name="subtopic",
            name="category",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="subtopic",
            name="level",
            field=models.CharField(
                blank=True,
                choices=[
                    ("CORE", "Core"),
                    ("ADVANCED", "Advanced"),
                    ("EXCEPTIONAL", "Exceptional"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="subtopic",
            name="is_imo_syllabus",
            field=models.BooleanField("IMO syllabus", db_index=True, default=False),
        ),
        migrations.RunPython(seed_imo_syllabus_subtopics, noop_reverse),
    ]
