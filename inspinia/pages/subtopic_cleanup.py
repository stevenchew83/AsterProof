# The raw SQL in this module is limited to internal PostgreSQL bulk updates with
# quoted model table names and parameterized row values.
# ruff: noqa: S608

from __future__ import annotations

import json
import re
import unicodedata
from collections import OrderedDict
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import connection
from django.db import transaction
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.subtopic_taxonomy import CANONICAL_SUBTOPIC_TAXONOMY
from inspinia.pages.topic_tags_parse import domains_dedup_preserve_order
from inspinia.pages.topic_tags_parse import normalize_topic_tag
from inspinia.pages.topic_tags_parse import repair_topic_tag_text

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class SubtopicTaxonomyEntry:
    main_topic: str
    canonical_subtopic: str
    technique: str
    stored_technique: str
    normalization_status: str = "alias"
    normalization_confidence: str = "high"


@dataclass(frozen=True)
class TaxonomyPatternRule:
    main_topic: str
    canonical_subtopic: str
    tokens: tuple[str, ...] = ()
    words: tuple[str, ...] = ()
    padded_tokens: tuple[str, ...] = ()
    stored_technique: str | None = None


@dataclass(frozen=True)
class SubtopicCleanupApplyResult:
    deleted_count: int
    raw_update_count: int
    updated_count: int


def _parent_aliases(
    main_topic: str,
    canonical_subtopic: str,
    aliases: tuple[str, ...],
) -> tuple[tuple[str, str, str], ...]:
    return tuple((main_topic, canonical_subtopic, alias) for alias in aliases)


def _stored_aliases(
    main_topic: str,
    canonical_subtopic: str,
    stored_technique: str,
    aliases: tuple[str, ...],
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple((main_topic, canonical_subtopic, alias, stored_technique) for alias in aliases)


NORMALIZATION_STATUS_CANONICAL = "canonical"
NORMALIZATION_STATUS_ALIAS = "alias"
NORMALIZATION_STATUS_METHOD = "method"
NORMALIZATION_STATUS_METADATA = "metadata"
NORMALIZATION_STATUS_CORRUPT = "corrupt"
NORMALIZATION_STATUS_INVALID = "invalid"
NORMALIZATION_STATUS_NEEDS_REVIEW = "needs_review"
NORMALIZATION_CONFIDENCE_HIGH = "high"
NORMALIZATION_CONFIDENCE_LOW = "low"
SUBTOPIC_CLEANUP_BATCH_SIZE = 1000

TAG_NORMALIZATION_UPDATE_FIELDS = [
    "technique",
    "main_topic",
    "canonical_subtopic",
    "domains",
    "raw_tag",
    "normalization_status",
    "normalization_confidence",
]


FIRST_PASS_CANONICAL_SUBTOPICS: tuple[str, ...] = (
    "Inequalities and optimization",
    "Sequences, recurrences, and series",
    "Polynomials and algebraic manipulation",
    "Functional equations",
    "Algebraic structures and linear algebra",
    "Equations, substitutions, and transformations",
    "Discrete functions, floors, rounding, and base representation",
    "Extremal methods, monotonicity, and invariants",
    "Number-theoretic algebra",
    "Combinatorial algebra and counting",
    "Geometry-flavored algebra",
    "Analytic estimates and asymptotics",
    "Complex, trigonometric, and Fourier methods",
    "Congruences and modular arithmetic",
    "Chinese remainder theorem and local-to-global methods",
    "Orders, primitive roots, and unit groups",
    "Divisibility, gcd, lcm, and factorization",
    "Prime numbers and prime divisors",
    "p-adic and valuation methods",
    "LTE and exponent lifting",
    "Diophantine equations and descent",
    "Pell-type equations and Vieta jumping",
    "Quadratic residues, squares, and squarefree methods",
    "Quadratic forms and sums of squares",
    "Arithmetic functions and divisor structure",
    "M\u00f6bius inversion and inclusion-exclusion",
    "Base, digit, and carry methods",
    "Binary and dyadic methods",
    "Sequences, recurrences, and finite dynamics",
    "Fibonacci, Lucas, Chebyshev, and special recurrences",
    "Polynomial methods over integers and residues",
    "Finite fields, characters, and advanced modular tools",
    "Algebraic number theory flavor",
    "Additive number theory and zero-sum methods",
    "Multiplicative structure and semigroups",
    "Floor, rounding, Beatty, Farey, and approximation methods",
    "Lattice and integer geometry methods",
    "Sieve, density, and asymptotic estimates",
    "Primitive divisors and Zsigmondy-type ideas",
    "Data-quality / invalid tag",
)


FIRST_PASS_CANONICAL_MAIN_TOPICS: dict[str, str] = {
    "Inequalities and optimization": "ALG",
    "Sequences, recurrences, and series": "ALG",
    "Polynomials and algebraic manipulation": "ALG",
    "Functional equations": "ALG",
    "Algebraic structures and linear algebra": "ALG",
    "Equations, substitutions, and transformations": "ALG",
    "Discrete functions, floors, rounding, and base representation": "ALG",
    "Extremal methods, monotonicity, and invariants": "ALG",
    "Number-theoretic algebra": "NT",
    "Combinatorial algebra and counting": "COMB",
    "Geometry-flavored algebra": "GEO",
    "Analytic estimates and asymptotics": "ALG",
    "Complex, trigonometric, and Fourier methods": "ALG",
    "Congruences and modular arithmetic": "NT",
    "Chinese remainder theorem and local-to-global methods": "NT",
    "Orders, primitive roots, and unit groups": "NT",
    "Divisibility, gcd, lcm, and factorization": "NT",
    "Prime numbers and prime divisors": "NT",
    "p-adic and valuation methods": "NT",
    "LTE and exponent lifting": "NT",
    "Diophantine equations and descent": "NT",
    "Pell-type equations and Vieta jumping": "NT",
    "Quadratic residues, squares, and squarefree methods": "NT",
    "Quadratic forms and sums of squares": "NT",
    "Arithmetic functions and divisor structure": "NT",
    "M\u00f6bius inversion and inclusion-exclusion": "NT",
    "Base, digit, and carry methods": "NT",
    "Binary and dyadic methods": "NT",
    "Sequences, recurrences, and finite dynamics": "NT",
    "Fibonacci, Lucas, Chebyshev, and special recurrences": "NT",
    "Polynomial methods over integers and residues": "NT",
    "Finite fields, characters, and advanced modular tools": "NT",
    "Algebraic number theory flavor": "NT",
    "Additive number theory and zero-sum methods": "NT",
    "Multiplicative structure and semigroups": "NT",
    "Floor, rounding, Beatty, Farey, and approximation methods": "NT",
    "Lattice and integer geometry methods": "NT",
    "Sieve, density, and asymptotic estimates": "NT",
    "Primitive divisors and Zsigmondy-type ideas": "NT",
    "Data-quality / invalid tag": "",
}


FIRST_PASS_PARENT_ALIASES: tuple[tuple[str, str, str], ...] = (
    *_parent_aliases(
        "ALG",
        "Inequalities and optimization",
        (
            "inequality",
            "inequalities",
            "cyclic inequality",
            "cyclic inequalities",
            "symmetric inequality",
            "symmetric inequalities",
            "trigonometric inequality",
            "variational inequality",
            "absolute value inequality",
            "product inequalities",
            "rank inequalities",
            "coefficient inequalities",
            "power means",
            "tangent-line bound",
            "lagrange multipliers",
            "kkt",
            "lp duality",
            "linear programming",
            "one-variable optimization",
            "quadratic optimization",
            "constrained minimization",
            "maximization",
            "minimization",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        (
            "sequences",
            "sequence classification",
            "sequences/inequalities",
            "recurrence",
            "recurrences",
            "linear recurrence",
            "binary recursion",
            "binary recursions",
            "cyclic recurrence",
            "cyclic recurrences",
            "max-plus recurrence",
            "chebyshev recurrence",
            "recurrence dynamics",
            "recurrence estimates",
            "recurrence structure",
            "recursive structure",
            "fibonacci",
            "fibonacci identities",
            "fibonacci weights",
            "fibonacci exponents",
            "lucas numbers",
            "geometric series",
            "geometric sums",
            "infinite series",
            "convergent series",
            "divergent sums",
            "subsequences",
            "telescoping",
            "telescoping sum",
            "telescoping estimate",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        (
            "polynomial",
            "polynomials",
            "polynomial values",
            "polynomial images",
            "polynomial composition",
            "polynomial recurrence",
            "polynomial construction",
            "polynomial dynamics",
            "polynomial inequality",
            "polynomial irreducibility",
            "polynomial roots",
            "polynomials mod p",
            "permutation polynomials",
            "real polynomials",
            "complex polynomials",
            "factorisation",
            "factorization",
            "factor arguments",
            "factor comparison",
            "factorial basis",
            "factoring tricks",
            "interpolation",
            "hermite interpolation",
            "vandermonde",
            "discriminant",
            "resultant",
            "roots",
            "roots of polynomial",
            "root dynamics",
            "coefficients",
            "coefficient bounds",
            "binomial identities",
            "binomial sums",
            "binomial expansion",
            "cubic",
            "cubics",
            "cubic identity",
            "cubic factorization",
            "quadratic",
            "quadratics",
            "quadratic polynomials",
            "chebyshev",
            "chebyshev polynomials",
            "finite difference",
            "finite differences",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Functional equations",
        (
            "functional equation",
            "functional equations",
            "functional equations on n",
            "functional equation on sequences",
            "quadratic fe",
            "arithmetic functional equations",
            "discrete functional equation",
            "differential-functional equation",
            "functional rigidity",
            "functional iteration",
            "functional graph",
            "functional inequalities",
            "cauchy equation",
            "cauchy equation stability",
            "cauchy over q",
            "additive functions",
            "multiplicative cauchy",
            "exponential cauchy",
            "real functions",
            "integer functions",
            "wild functions",
            "recursive functions",
            "injectivity",
            "surjectivity",
            "forced linearity",
            "functions; inequalities; casework",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Algebraic structures and linear algebra",
        (
            "algebraic structures",
            "linear algebra",
            "modular linear algebra",
            "constructive linear algebra",
            "matrix",
            "matrices",
            "nilpotent matrices",
            "skew-symmetric matrices",
            "determinant",
            "determinants",
            "eigenvalue",
            "eigenvalues",
            "rank",
            "trace",
            "adjugate",
            "cofactors",
            "groups",
            "cyclic groups",
            "abelian groups",
            "additive groups",
            "multiplicative group",
            "p-groups",
            "group action",
            "group structure",
            "cosets",
            "generators",
            "rings",
            "boolean rings",
            "division rings",
            "reduced rings",
            "field theory",
            "cubic fields",
            "ufd",
            "ideals",
            "polynomial ideals",
            "commutators",
            "centralizers",
            "nilpotent",
            "nilpotence",
            "nilradical",
            "units",
            "unit group",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Equations, substitutions, and transformations",
        (
            "equations",
            "systems",
            "linear equations",
            "cyclic equations",
            "coupled equations",
            "substitutions",
            "substitution",
            "special substitutions",
            "strategic substitutions",
            "symmetric substitutions",
            "ratio substitution",
            "rational substitution",
            "trig substitution",
            "trigonometric substitution",
            "ravi-type substitution",
            "log substitution",
            "z substitution",
            "homogenization",
            "homogeneous reduction",
            "normalization",
            "scaling",
            "affine normalization",
            "affine transformation",
            "transformations",
            "translation",
            "translations",
            "rotations/translations",
            "mobius transformation",
            "m\u00f6bius transformation",
            "parametrization",
            "rational parametrization",
            "reparametrization",
            "variable reduction",
            "variable separation",
            "linearization",
            "rationalization",
            "clearing denominators",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Discrete functions, floors, rounding, and base representation",
        (
            "floor function",
            "floor functions",
            "floors",
            "floor sums",
            "floor/fractional part",
            "floors/fractional parts",
            "floor stabilization",
            "rounding",
            "rounding identities",
            "modulo 1 rounding",
            "integer part structure",
            "discrete intermediate value",
            "discrete ivt",
            "discrete functions",
            "discrete structure",
            "discrete differences",
            "base representation",
            "base-10 constructions",
            "base-2/base-3 expansions",
            "binary expansion",
            "binary structure",
            "binary decomposition",
            "dyadic decomposition",
            "dyadic blocks",
            "dyadic intervals",
            "digit counting",
            "digit bounds",
            "digit extraction",
            "decimal structure",
            "decimal carries",
            "automata",
            "automatic sequence",
            "beatty sequence",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Extremal methods, monotonicity, and invariants",
        (
            "extremal",
            "extremal argument",
            "extremal thinking",
            "extremal ordering",
            "extremal configurations",
            "extremal sets",
            "extremal subsets",
            "extremal structure",
            "extremal process",
            "extremal contradiction",
            "extremal examples",
            "extremal values",
            "minimax",
            "min-max",
            "max/min",
            "bounding",
            "bounding by extrema",
            "monotonicity",
            "monotone functions",
            "monotone maps",
            "monotone arrays",
            "monotonicity forcing",
            "ordering",
            "ordered variables",
            "order relations",
            "growth",
            "growth control",
            "growth/monotonicity",
            "invariant",
            "invariants",
            "invariant polynomials",
            "monovariants",
            "descent",
            "finite descent",
            "infinite descent",
            "stability",
            "rigidity",
            "uniqueness",
            "classification",
        ),
    ),
    *_parent_aliases(
        "NT",
        "Number-theoretic algebra",
        (
            "divisibility",
            "divisibility sequences",
            "divisibility descent",
            "gcd",
            "gcd design",
            "valuations",
            "rational valuations",
            "p-adic",
            "p-adic integrality",
            "modular",
            "modular rigidity",
            "congruence",
            "residues",
            "division algorithm",
            "vieta",
            "vieta jumping",
            "pell",
            "pell-type",
            "zsigmondy",
            "lucas-sequence",
            "factorials",
            "squares",
            "squarefree",
            "square classes",
            "sums of two squares",
            "powers of two",
            "prime structure",
            "distinct prime factors",
            "algebraic integers",
            "algebraic conjugates",
            "rationality",
            "rationals",
            "rational numbers",
            "irrationality",
            "integrality",
            "integer values",
            "integer functions",
            "integer polynomials",
            "norm form",
            "eisenstein norm form",
        ),
    ),
    *_parent_aliases(
        "COMB",
        "Combinatorial algebra and counting",
        (
            "counting",
            "countability",
            "counting roots",
            "counting preimages",
            "pairing",
            "reciprocal pairing",
            "symmetry/pairing",
            "charging",
            "double counting",
            "inclusion-exclusion",
            "permutation",
            "permutations",
            "permutation inequality",
            "permutation swaps",
            "graph",
            "graph independence",
            "graph components",
            "graph ordering",
            "weighted graph",
            "matching",
            "set operations",
            "set coloring",
            "subset choice",
            "finite chains",
            "ordered sets",
            "game strategy",
            "strategy pairing",
            "dp",
            "dynamic programming",
            "random walk",
            "probability method",
            "lattice walks",
            "dyck path bijection",
        ),
    ),
    *_parent_aliases(
        "GEO",
        "Geometry-flavored algebra",
        (
            "coordinates",
            "coordinate geometry",
            "geometry on r^2",
            "lattice points",
            "integer lattice",
            "regular polygon",
            "equilateral triangle",
            "triangle condition",
            "triangle constraints",
            "triangle inequality",
            "area formulas",
            "area computation",
            "heron formula",
            "tangent lengths",
            "tangential quads",
            "unit circle",
            "unit disk",
            "rotation",
            "rotation symmetry",
            "vector geometry",
            "unit vectors",
            "convex geometry",
            "discrete geometry",
            "constructibility",
            "affine geometry",
            "complex plane",
            "complex numbers; vector geometry",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Analytic estimates and asymptotics",
        (
            "asymptotics",
            "asymptotic",
            "asymptotic dominance",
            "asymptotic inequalities",
            "approximation",
            "limit",
            "limsup",
            "convergence",
            "dominated convergence",
            "calculus",
            "derivative",
            "mean value",
            "mvt",
            "integral",
            "integration by parts",
            "improper integrals",
            "topology",
            "topology of r",
            "compactness",
            "baire",
            "density",
            "density of q",
            "density of rationals",
            "continuity",
            "discontinuity",
            "lipschitz",
            "differential equation",
            "ode",
            "darboux property",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Complex, trigonometric, and Fourier methods",
        (
            "complex",
            "complex numbers",
            "complex rotations",
            "complex conjugation",
            "roots on a circle",
            "argument principle",
            "rouche",
            "rouch\u00e9",
            "fourier",
            "discrete fourier transform",
            "parseval",
            "trigonometric",
            "trig",
            "trig identities",
            "trigonometric identities",
            "trigonometric sums",
            "trigonometric form",
            "trigonometric parameterization",
            "product-to-sine",
            "sine identities",
            "chebyshev/sine",
            "hyperbolic",
            "hyperbolic cosine identity",
        ),
    ),
)


FIRST_PASS_STORED_ALIASES: tuple[tuple[str, str, str, str], ...] = (
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Functional equations",
        ("functional equation", "functional equations"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Inequalities and optimization",
        ("inequality", "inequalities"),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Sequences, recurrences, and series",
        ("sequence", "sequences", "recurrence", "recurrences"),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Polynomials and algebraic manipulation",
        ("polynomial", "polynomials"),
    ),
    *_stored_aliases(
        "GEO",
        "Geometry-flavored algebra",
        "Coordinate geometry",
        ("coordinate", "coordinates", "coordinate geometry"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Cauchy-Schwarz / Engel form",
        (
            "am-gm/cauchy",
            "cauchy/am-gm",
            "am-gm / cauchy",
            "cauchy / am-gm",
            "cauchy-schwarz",
            "cauchy",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "H\u00f6lder",
        ("h\u00f6lder", "holder", "h\u221a\xf1lder"),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Polynomial functional equation",
        ("polynomial functional equation", "polynomial fe"),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Factorization",
        (
            "factorisation",
            "alg factorisation",
            "alg - factorisation",
        ),
    ),
)


METHOD_ONLY_TAGS: tuple[str, ...] = (
    "contradiction",
    "contraposition",
    "impossibility",
    "existence/uniqueness",
    "statement check",
    "statement flaw",
    "red herring",
    "degeneracy check",
)


INVALID_TAGS: tuple[str, ...] = (
    "1",
    "11",
    "13",
    "1)",
    "1]",
    "p",
    "q",
    "r",
    "y",
    "y]",
    "zx",
    "yz",
)


NUMBER_THEORY_STORED_ALIASES: tuple[tuple[str, str, str, str], ...] = (
    *_stored_aliases(
        "NT",
        "Congruences and modular arithmetic",
        "Modular arithmetic / residues",
        (
            "congruences",
            "congrences",
            "modular arithmetic",
            "modular congruences",
            "modular algebra",
            "modular strategy",
            "modular contradiction",
            "modular bounding",
            "modular restrictions",
            "modular solvability",
            "modular parity",
            "modular systems",
            "modulo 9",
            "mod 8",
            "mod 24",
            "residues",
            "residues mod",
            "complete residues",
            "residue obstruction",
            "fermat's theorem",
            "fermat theorem",
            "fermat little theorem",
            "fermat's little theorem",
            "flt",
            "wilson theorem",
            "wilson-type arguments",
            "euler theorem",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Chinese remainder theorem and local-to-global methods",
        "Chinese remainder theorem / local-global",
        (
            "crt",
            "crt construction",
            "crt constructions",
            "constructive crt",
            "crt/local analysis",
            "crt/local obstructions",
            "simultaneous congruences",
            "local-to-global",
            "local-global",
            "local/global obstructions",
            "local-global/crt",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Orders, primitive roots, and unit groups",
        "Orders / primitive roots / unit groups",
        (
            "orders modulo primes",
            "orders mod primes",
            "orders mod p",
            "orders modulo p",
            "orders mod prime",
            "orders modulo prime powers",
            "orders modulo n",
            "modular order",
            "order modulo p",
            "primitive roots",
            "primitive roots/order",
            "reduced residues",
            "units",
            "unit groups",
            "units mod",
            "cyclic groups",
            "subgroups",
            "multiplicative subgroups",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Divisibility, gcd, lcm, and factorization",
        "Divisibility / GCD / factorization",
        (
            "divisibility",
            "divisibility / diophantine",
            "divisibility/congruences",
            "divisibility structure",
            "divisibility condition",
            "divisibility tricks",
            "gcd",
            "gcd structure",
            "gcd trick",
            "gcd/lcm",
            "lcm/gcd",
            "lcm structure",
            "lcm growth",
            "factoring",
            "factorization",
            "factor structure",
            "factorial divisibility",
            "factorials/divisibility",
            "coprimality",
            "pairwise coprime",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Divisibility, gcd, lcm, and factorization",
        "B\u00e9zout / Euclidean algorithm",
        (
            "bezout",
            "b\u00e9zout",
            "bezout/linear combinations",
            "b\u00e9zout/linear combinations",
            "euclidean algorithm",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Prime numbers and prime divisors",
        "Primes / prime divisors",
        (
            "primes",
            "prime factors",
            "prime divisibility",
            "prime divisors",
            "prime factor structure",
            "prime-factor cases",
            "prime-power cases",
            "prime powers",
            "prime avoidance",
            "prime construction",
            "infinite primes",
            "euclid new-prime trick",
            "largest prime factor",
            "smallest prime factor",
            "primes in ap",
            "primes in residue classes",
        ),
    ),
    *_stored_aliases(
        "NT",
        "p-adic and valuation methods",
        "Valuations / p-adic methods",
        (
            "p-adic valuations",
            "p-adic",
            "p-adics",
            "p-adic control",
            "p-adic flavor",
            "p-adic units",
            "p-adic congruences",
            "2-adic",
            "2-adic valuations",
            "2-adic order",
            "2-adic structure",
            "2-adic descent",
            "2-adic lifting",
            "v2",
            "v_2",
            "valuation",
            "valuations",
            "valuation structure",
            "valuations/divisibility",
            "p-adic divisibility",
            "p-adic methods",
            "p-adic structure",
            "p-adic/newton polygon ideas",
        ),
    ),
    *_stored_aliases(
        "NT",
        "LTE and exponent lifting",
        "LTE / exponent lifting",
        (
            "lifting exponent",
            "lifting exponents",
            "lifting exponent (lte)",
            "lte-style lifting",
            "orders/lte",
            "lte/valuations",
            "lte/orders",
            "lte/congruences",
            "lte/zsigmondy",
            "p-adic valuations/lte",
            "valuation control/lte",
        ),
    ),
    *_stored_aliases("NT", "LTE and exponent lifting", "LTE", ("lte",)),
    *_stored_aliases(
        "NT",
        "Diophantine equations and descent",
        "Diophantine equations",
        (
            "diophantine",
            "diophantine equation",
            "diophantine equations",
            "diophantine descent",
            "diophantine factorization",
            "diophantine bounding",
            "diophantine constraints",
            "diophantine obstruction",
            "diophantine systems",
            "linear diophantine",
            "quadratic diophantine",
            "cubic diophantine",
            "exponential diophantine",
            "descent/vieta jumping",
            "finite descent",
            "infinite descent",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Pell-type equations and Vieta jumping",
        "Pell / Vieta jumping",
        (
            "pell",
            "pell equation",
            "pell-type",
            "pell-type equations",
            "pell-type diophantine",
            "pell-type identities",
            "pell-type construction",
            "pell-type recurrence",
            "pell-type recurrences",
            "vieta",
            "vieta jumping",
            "vieta jumping flavor",
            "vieta-style jumping",
            "vieta/descent",
            "vieta/discriminant",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Quadratic residues, squares, and squarefree methods",
        "Quadratic residues / squarefree",
        (
            "quadratic residue",
            "quadratic residues",
            "legendre symbols",
            "legendre",
            "squares mod 8",
            "square residues",
            "square classes",
            "square values",
            "square condition",
            "square divisibility",
            "squarefree",
            "square-free",
            "squarefree parts",
            "squarefree kernels",
            "squarefree obstruction",
            "bounding between squares",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Quadratic forms and sums of squares",
        "Quadratic forms / sums of squares",
        (
            "quadratic form",
            "quadratic forms",
            "sums of two squares",
            "sums-of-two-squares",
            "two-square theorem",
            "three-square theorem",
            "pythagorean triple",
            "pythagorean triples",
            "pythagorean parametrization",
            "rational squares",
            "rational sums of squares",
            "integer triangles",
            "heronian/pythagorean families",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Arithmetic functions and divisor structure",
        "Arithmetic functions / divisor structure",
        (
            "arithmetic functions",
            "divisor function",
            "divisor functions",
            "divisor count",
            "divisor counting",
            "divisor sum",
            "divisor-sum function",
            "sigma functions",
            "tau",
            "multiplicative functions",
            "multiplicativity",
            "highly composite",
            "perfect numbers",
            "abundant divisors",
            "odd perfect numbers",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Arithmetic functions and divisor structure",
        "Euler phi / totient",
        ("phi(n)", "phi function", "euler phi", "totient"),
    ),
    *_stored_aliases(
        "NT",
        "Arithmetic functions and divisor structure",
        "Prime-factor counting functions",
        ("omega", "parity of omega"),
    ),
    *_stored_aliases(
        "NT",
        "M\u00f6bius inversion and inclusion-exclusion",
        "M\u00f6bius inversion",
        (
            "mobius",
            "m\u00f6bius",
            "mobius inversion",
            "m\u00f6bius inversion",
            "mobius/dirichlet convolution",
            "m\u00f6bius/dirichlet convolution",
            "inclusion-exclusion/mobius",
            "dirichlet convolution",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Base, digit, and carry methods",
        "Base / digit / carry methods",
        (
            "base representation",
            "base expansion",
            "base-p digits",
            "base-10",
            "base-10 digit constraints",
            "base-b digits",
            "decimal digits",
            "decimal expansion",
            "decimal expansions",
            "decimal structure",
            "decimal construction",
            "decimal concatenation",
            "digits",
            "digit sum",
            "digit sums",
            "digital sums",
            "carrying",
            "carry control",
            "carries/borrows",
            "decimal carries",
            "repdigits",
            "repunits",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Binary and dyadic methods",
        "Binary / dyadic methods",
        (
            "binary",
            "binary digits",
            "binary expansion",
            "binary expansions",
            "binary representation",
            "binary representations",
            "binary structure",
            "binary blocks",
            "binary odometer",
            "powers of two",
            "powers of 2",
            "powers of 2 and 5",
            "dyadic decomposition",
            "dyadic grouping",
            "dyadic halving",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Sequences, recurrences, and finite dynamics",
        "Recurrences / finite dynamics",
        (
            "recurrence",
            "recurrences",
            "linear recurrence",
            "linear recurrences",
            "modular recurrence",
            "recurrence mod p",
            "recurrence modulo p",
            "recurrence construction",
            "recurrence dynamics",
            "recursive sequence",
            "recursive structure",
            "finite dynamics",
            "finite-state recurrence",
            "periodicity",
            "pisano period",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Fibonacci, Lucas, Chebyshev, and special recurrences",
        "Fibonacci / Lucas / Chebyshev",
        (
            "fibonacci",
            "fibonacci identities",
            "fibonacci modulo m",
            "fibonacci/lucas",
            "lucas",
            "lucas/kummer",
            "lucas-type congruence",
            "chebyshev recurrence",
            "chebyshev-type units",
            "pell sequence",
            "stern sequence",
            "ducci sequence",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Polynomial methods over integers and residues",
        "Polynomials over integers / residues",
        (
            "polynomial values",
            "polynomial values mod n",
            "polynomial functions mod n",
            "polynomials modulo n",
            "polynomials modulo p",
            "polynomial images",
            "polynomial maps",
            "polynomial construction",
            "polynomial recurrence",
            "polynomial composition",
            "polynomial remainders",
            "permutation polynomials",
            "hermite criterion",
            "hermite interpolation",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Finite fields, characters, and advanced modular tools",
        "Finite fields / characters",
        (
            "finite field",
            "finite-field counting",
            "finite-field polynomials",
            "finite-field structure",
            "character sums",
            "gauss sums",
            "gauss lemma",
            "chevalley-warning",
            "root-of-unity filter",
            "finite fourier",
            "cyclotomy",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Algebraic number theory flavor",
        "Algebraic number theory",
        (
            "algebraic number theory",
            "algebraic nt flavor",
            "algebraic integers",
            "algebraic conjugates",
            "algebraic norm",
            "norms",
            "norm form",
            "gaussian integers",
            "z[sqrt(2)]",
            "cubic fields",
            "cyclotomic fields",
            "cyclotomic structure",
            "ufd flavor",
            "unique factorization",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Additive number theory and zero-sum methods",
        "Additive number theory / zero-sum",
        (
            "additive number theory",
            "additive structure",
            "additive sets",
            "additive functions",
            "additive representation",
            "additive partitions",
            "sumsets",
            "zero-sum",
            "zero-sum subsets",
            "zero-sum-free sets",
            "egz",
            "olson",
            "cauchy-davenport",
            "restricted sumset",
            "ap/gp",
            "arithmetic progression",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Multiplicative structure and semigroups",
        "Multiplicative structure / semigroups",
        (
            "multiplicative structure",
            "multiplicative",
            "multiplicative dynamics",
            "multiplicative relations",
            "multiplicative coloring",
            "semigroup",
            "numerical semigroups",
            "numerical semigroup",
            "s-unit flavor",
            "product set",
            "products",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Floor, rounding, Beatty, Farey, and approximation methods",
        "Floor / rounding / approximation",
        (
            "floor functions",
            "floor function",
            "floors",
            "floor sums",
            "floor maps",
            "ceiling function",
            "rounding",
            "rounding functions",
            "beatty",
            "sturmian",
            "continued fractions",
            "farey",
            "stern-brocot",
            "rational approximation",
            "diophantine approximation",
            "density mod 1",
            "rotations mod 1",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Lattice and integer geometry methods",
        "Lattice / integer geometry",
        (
            "lattice",
            "lattices",
            "lattice points",
            "lattice counting",
            "lattice geometry",
            "lattice polygons",
            "lattice transformation",
            "visibility",
            "integer triangle",
            "rational lattices",
            "gauss area formula",
            "pick-style geometry",
            "pick style geometry",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Sieve, density, and asymptotic estimates",
        "Sieve / density / asymptotics",
        (
            "sieve",
            "elementary sieve",
            "density",
            "density estimates",
            "asymptotics",
            "asymptotic counting",
            "asymptotic comparison",
            "asymptotic contradiction",
            "sparsity",
            "smoothness",
            "smooth numbers",
            "bertrand-type bounds",
            "chebyshev bound",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Primitive divisors and Zsigmondy-type ideas",
        "Primitive divisors / Zsigmondy",
        (
            "zsigmondy",
            "zsigmondy flavor",
            "zsigmondy-type ideas",
            "zsigmondy/orders",
            "zsigmondy/lte",
            "zsigmondy/primitive prime divisors",
            "primitive divisors",
            "primitive divisors/zsigmondy",
            "schur-type prime divisors",
            "sylvester/schur flavor",
        ),
    ),
)


NUMBER_THEORY_METHOD_ALIASES: tuple[tuple[str, str], ...] = (
    ("extremal argument", "Extremal method"),
    ("extremal process", "Extremal method"),
    ("extremal structure", "Extremal method"),
    ("extremal set", "Extremal method"),
    ("extremal sets", "Extremal method"),
    ("extremal subset", "Extremal method"),
    ("extremal subsets", "Extremal method"),
    ("extremal ordering", "Extremal method"),
    ("extremal sequences", "Extremal method"),
    ("extremal product", "Extremal method"),
    ("extremal divisors", "Extremal method"),
    ("extremal minimality", "Extremal method"),
    ("extremal/minimal counterexample", "Extremal method"),
    ("constructive", "Construction"),
    ("constructive number theory", "Construction"),
    ("constructive divisibility", "Construction"),
    ("constructive congruences", "Construction"),
    ("constructive crt", "Construction"),
    ("constructive sequence", "Construction"),
    ("constructive search", "Construction"),
    ("construction of examples", "Construction"),
    ("contradiction", "Contradiction / obstruction"),
    ("modular contradiction", "Contradiction / obstruction"),
    ("obstruction", "Contradiction / obstruction"),
    ("local obstructions", "Contradiction / obstruction"),
    ("bounding", "Bounding and estimates"),
    ("bounds", "Bounding and estimates"),
    ("growth control", "Bounding and estimates"),
    ("estimates", "Bounding and estimates"),
    ("induction", "Induction and descent"),
    ("finite descent", "Induction and descent"),
    ("infinite descent", "Induction and descent"),
    ("invariance", "Invariants, closure, and rigidity"),
    ("invariants", "Invariants, closure, and rigidity"),
    ("closure", "Invariants, closure, and rigidity"),
    ("rigidity", "Invariants, closure, and rigidity"),
    ("classification", "Invariants, closure, and rigidity"),
    ("pigeonhole", "Pigeonhole, pairing, injection"),
    ("pairing", "Pigeonhole, pairing, injection"),
    ("injection", "Pigeonhole, pairing, injection"),
    ("bijection", "Pigeonhole, pairing, injection"),
    ("double counting", "Pigeonhole, pairing, injection"),
    ("cases", "Casework and finite checking"),
    ("casework", "Casework and finite checking"),
    ("finite casework", "Casework and finite checking"),
    ("finite check", "Casework and finite checking"),
    ("greedy", "Greedy / optimization / adversarial strategy"),
    ("game strategy", "Greedy / optimization / adversarial strategy"),
    ("strategy game", "Greedy / optimization / adversarial strategy"),
    ("graph connectivity", "Graph / matching / ordering model"),
    ("graph modeling", "Graph / matching / ordering model"),
    ("gcd graph", "Graph / matching / ordering model"),
    ("coprimality graph", "Graph / matching / ordering model"),
    ("divisibility graph", "Graph / matching / ordering model"),
    ("matching", "Graph / matching / ordering model"),
    ("ordering", "Graph / matching / ordering model"),
    ("parametrization", "Transformations and parametrization"),
    ("parameterization", "Transformations and parametrization"),
    ("rational parametrization", "Transformations and parametrization"),
    ("substitution", "Transformations and parametrization"),
    ("scaling", "Transformations and parametrization"),
    ("reduction", "Transformations and parametrization"),
    ("transformation", "Transformations and parametrization"),
)


METADATA_TAGS: tuple[str, ...] = (
    "imo 2007 p5",
    "advanced theorem risk",
    "caveat",
    "information ambiguity",
    "ambiguity",
    "ambiguity/counterexample",
)


CORRUPT_TAGS: tuple[str, ...] = (
    "bbb",
    "nnn",
    "rrr",
    "\\alpha",
    "\\alpha^21",
    "\u0152\u00eb",
    "\u0152\u00eb2",
    "\u0152\u00eb21",
    "d^2",
    "z) flavor",
)


ADDITIONAL_SUBTOPIC_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("ALG", "Inequalities and optimization", "inequalities"),
    ("ALG", "Inequalities and optimization", "extremal inequalities"),
    ("ALG", "Inequalities and optimization", "optimization"),
    ("ALG", "Inequalities and optimization", "concavity"),
    ("ALG", "Polynomials and algebraic manipulation", "polynomial structure"),
    ("ALG", "Polynomials and algebraic manipulation", "exponential polynomials"),
    ("ALG", "Polynomials and algebraic manipulation", "integer coefficients"),
    ("ALG", "Sequences, recurrences, and series", "recurrences"),
    ("ALG", "Sequences, recurrences, and series", "telescoping"),
    ("ALG", "Sequences, recurrences, and series", "sums of powers"),
    ("ALG", "Functional equations", "functional equations disguised"),
    ("ALG", "Functional equations", "functional equations on Q"),
    ("ALG", "Functional equations", "differentiability"),
    ("ALG", "Functional equations", "iteration"),
    ("ALG", "Algebraic structures and linear algebra", "linear algebra mod 2"),
    ("NT", "Diophantine equations and descent", "diophantine approximation"),
    ("NT", "Diophantine equations and descent", "geometry of numbers"),
    ("NT", "Additive and multiplicative number theory", "additive representations"),
    ("GEO", "Core Euclidean geometry", "geometry"),
    ("GEO", "Core Euclidean geometry", "trig"),
    ("GEO", "Core Euclidean geometry", "complex numbers"),
    ("GEO", "Core Euclidean geometry", "complex vectors"),
    ("COMB", "Counting and enumerative combinatorics", "growth and counting"),
    ("COMB", "Graph theory", "hamiltonian paths"),
    ("COMB", "Graph theory", "geometric graphs"),
    ("COMB", "Set systems, posets, and extremal set theory", "sequences of sets"),
    ("COMB", "Coloring, tiling, grids, and invariants", "invariants"),
    ("COMB", "Coloring, tiling, grids, and invariants", "invariants on permutations"),
    ("COMB", "Coloring, tiling, grids, and invariants", "colorings"),
    ("COMB", "Coloring, tiling, grids, and invariants", "grids"),
    ("COMB", "Coloring, tiling, grids, and invariants", "3D grids"),
    ("COMB", "Coloring, tiling, grids, and invariants", "paths on grids"),
    ("COMB", "Coloring, tiling, grids, and invariants", "dissections"),
    ("COMB", "Coloring, tiling, grids, and invariants", "local patterns"),
    ("COMB", "Games, strategies, and processes", "game"),
    ("COMB", "Games, strategies, and processes", "strategy"),
    ("COMB", "Games, strategies, and processes", "worst-case search"),
    ("COMB", "Games, strategies, and processes", "adversarial"),
    ("COMB", "Games, strategies, and processes", "pursuit games"),
    ("COMB", "Games, strategies, and processes", "multiset process"),
    ("COMB", "Pigeonhole, extremal principle, and averaging", "extremal"),
    ("COMB", "Probability, entropy, coding, and information methods", "coding"),
    ("COMB", "Algorithms, automata, words, and constructive combinatorics", "word problem"),
    ("COMB", "Algorithms, automata, words, and constructive combinatorics", "strings"),
    ("COMB", "Algorithms, automata, words, and constructive combinatorics", "constructive / obstructions"),
)


PARENT_COLLAPSE_SUBTOPIC_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("ALG", "Functional equations", "functional equation"),
    ("ALG", "Functional equations", "functional equations"),
    ("GEO", "Core Euclidean geometry", "coordinate"),
    ("GEO", "Core Euclidean geometry", "coordinates"),
    ("GEO", "Core Euclidean geometry", "coordinate geometry"),
    ("ALG", "Inequalities and optimization", "inequality"),
    ("ALG", "Inequalities and optimization", "inequalities"),
    ("ALG", "Inequalities and optimization", "cauchy"),
    ("ALG", "Inequalities and optimization", "convexity"),
    ("ALG", "Sequences, recurrences, and series", "recurrence"),
    ("ALG", "Sequences, recurrences, and series", "recurrences"),
    *_parent_aliases(
        "ALG",
        "Functional equations",
        (
            "fe",
            "functional condition",
            "functional conditions",
            "functional values",
            "functional families",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Inequalities and optimization",
        (
            "inequalities/optimization",
            "inequalities / optimization",
            "inequalities and optimization",
            "inequality lemma",
            "inequality forcing",
            "nonlinear inequality",
            "sequence inequality",
            "single-variable inequality",
            "constrained inequality",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        (
            "polynomial",
            "polynomials",
            "polynomial actions",
            "polynomial constraints",
            "algebraic manipulation",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        (
            "sequence",
            "sequences",
            "recursion",
            "recursive sequences",
            "recurrence sequences",
            "sequences/recurrences",
            "integer sequence",
            "integer sequences",
            "sequencing real numbers",
        ),
    ),
    *_parent_aliases(
        "GEO",
        "Core Euclidean geometry",
        (
            "angle chasing/coordinates",
            "angle chasing coordinates",
        ),
    ),
    *_parent_aliases(
        "ALG",
        "Algebraic structures and linear algebra",
        (
            "algebraic structure",
            "algebraic structures",
        ),
    ),
)


STORED_TECHNIQUE_SUBTOPIC_ALIASES: tuple[tuple[str, str, str, str], ...] = (
    ("ALG", "Functional equations", "integer functional equation", "Integer Functional Equations"),
    ("ALG", "Functional equations", "integer functional equations", "Integer Functional Equations"),
    ("ALG", "Functional equations", "divisibility fe", "Divisibility FE"),
    ("GEO", "Core Euclidean geometry", "affine/coordinate methods", "Affine/coordinate methods"),
    ("GEO", "Core Euclidean geometry", "cevian coordinates", "Cevian coordinates"),
    ("GEO", "Core Euclidean geometry", "coordinates/trig ceva", "Coordinates/trig Ceva"),
    ("GEO", "Core Euclidean geometry", "parallelogram coordinates", "Parallelogram coordinates"),
    ("GEO", "Core Euclidean geometry", "midpoint vectors", "Midpoint vectors"),
    ("ALG", "Inequalities and optimization", "cauchy-schwarz/engel", "Cauchy-Schwarz/Engel"),
    ("ALG", "Inequalities and optimization", "engel form", "Engel form"),
    ("ALG", "Inequalities and optimization", "schur/am-gm", "Schur/AM-GM"),
    ("ALG", "Inequalities and optimization", "bernoulli inequality", "Bernoulli inequality"),
    ("ALG", "Inequalities and optimization", "jensen convexity", "Jensen / Convexity"),
    ("ALG", "Inequalities and optimization", "jensen convexity/concavity", "Jensen / Convexity"),
    ("ALG", "Inequalities and optimization", "smoothing", "Smoothing"),
    ("ALG", "Inequalities and optimization", "uvw", "UVW"),
    ("ALG", "Inequalities and optimization", "polynomial inequalities", "Polynomial inequalities"),
    ("ALG", "Inequalities and optimization", "symmetric bounds", "Symmetric bounds"),
    ("ALG", "Inequalities and optimization", "product comparison", "Product comparison"),
    ("ALG", "Inequalities and optimization", "parameter inequality", "Parameter inequality"),
    ("ALG", "Inequalities and optimization", "extremal value", "Extremal value"),
    ("ALG", "Sequences, recurrences, and series", "floor recurrence", "Floor recurrence"),
    ("ALG", "Sequences, recurrences, and series", "integer sequences", "Integer sequences"),
    ("NT", "Diophantine equations and descent", "pell-type recurrence", "Pell-type recurrences"),
    ("ALG", "Sequences, recurrences, and series", "block sums", "Block sums"),
    ("ALG", "Sequences, recurrences, and series", "harmonic sum", "Harmonic sums"),
    ("ALG", "Polynomials and algebraic manipulation", "factorisation", "Factorization"),
    ("ALG", "Polynomials and algebraic manipulation", "factorization", "Factorization"),
    ("ALG", "Polynomials and algebraic manipulation", "interpolation", "Interpolation"),
    ("ALG", "Polynomials and algebraic manipulation", "coefficient chase", "Coefficient chase"),
    ("ALG", "Polynomials and algebraic manipulation", "cubic curves", "Cubic curves"),
    ("ALG", "Polynomials and algebraic manipulation", "exponential substitution", "Exponential substitution"),
    ("NT", "Divisibility, gcd, lcm, and primes", "divisibility obstruction", "Divisibility obstruction"),
    ("NT", "Divisibility, gcd, lcm, and primes", "divisibility/congruences", "Divisibility/congruences"),
    ("NT", "Divisibility, gcd, lcm, and primes", "divisor check", "Divisor check"),
    ("NT", "Divisibility, gcd, lcm, and primes", "denominator control", "Denominator control"),
    ("NT", "Divisibility, gcd, lcm, and primes", "gcd over primes", "GCD over primes"),
    ("NT", "Divisibility, gcd, lcm, and primes", "gcd dynamics", "GCD dynamics"),
    ("NT", "Divisibility, gcd, lcm, and primes", "coprime factorization", "Coprime factorization"),
    ("NT", "Congruences and modular arithmetic", "congruence", "Congruence"),
    ("NT", "Congruences and modular arithmetic", "modular classes", "Modular classes"),
    ("NT", "Congruences and modular arithmetic", "fermat little theorem", "Fermat little theorem"),
    ("NT", "Congruences and modular arithmetic", "order constraints", "Order constraints"),
    ("NT", "p-adic and valuation methods", "orders/lte", "Orders/LTE"),
    ("NT", "p-adic and valuation methods", "p-adic arguments", "p-adic / Valuation Methods"),
    ("NT", "p-adic and valuation methods", "p-adic structure", "p-adic / Valuation Methods"),
    ("NT", "p-adic and valuation methods", "valuations", "Valuations"),
    ("NT", "Diophantine equations and descent", "diophantine classification", "Diophantine classification"),
    ("NT", "Diophantine equations and descent", "diophantine factorization", "Diophantine factorization"),
    ("NT", "Diophantine equations and descent", "diophantine manipulation", "Diophantine manipulation"),
    ("NT", "Diophantine equations and descent", "exponential diophantine", "Exponential Diophantine"),
    ("NT", "Diophantine equations and descent", "digit equations", "Digit equations"),
    ("NT", "Diophantine equations and descent", "extremal triples", "Extremal triples"),
    (
        "COMB",
        "Algorithms, automata, words, and constructive combinatorics",
        "constructive families",
        "Constructive families",
    ),
    (
        "COMB",
        "Algorithms, automata, words, and constructive combinatorics",
        "constructive arrangement",
        "Constructive arrangement",
    ),
    (
        "COMB",
        "Algorithms, automata, words, and constructive combinatorics",
        "constructive examples",
        "Constructive examples",
    ),
    (
        "COMB",
        "Algorithms, automata, words, and constructive combinatorics",
        "constructive scheduling",
        "Constructive scheduling",
    ),
    (
        "COMB",
        "Algorithms, automata, words, and constructive combinatorics",
        "constructive tilings",
        "Constructive tilings",
    ),
    ("COMB", "Pigeonhole, extremal principle, and averaging", "greedy", "Greedy"),
    ("COMB", "Graph theory", "greedy/matching", "Greedy/matching"),
    ("COMB", "Graph theory", "matchings/permutations", "Matchings/permutations"),
    ("COMB", "Graph theory", "graph interpretation", "Graph interpretation"),
    ("COMB", "Graph theory", "graph modeling", "Graph modeling"),
    ("COMB", "Graph theory", "graph scheduling", "Graph scheduling"),
    ("COMB", "Graph theory", "petersen graph", "Petersen graph"),
    ("COMB", "Graph theory", "permutation matrices", "Permutation matrices"),
    ("COMB", "Pigeonhole, extremal principle, and averaging", "invariant/monotonicity", "Invariant/monotonicity"),
    (
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "invariants/double counting",
        "Invariants/double counting",
    ),
    ("COMB", "Pigeonhole, extremal principle, and averaging", "invariants/pairing", "Invariants/pairing"),
    ("COMB", "Pigeonhole, extremal principle, and averaging", "finite process", "Finite process"),
    ("COMB", "Pigeonhole, extremal principle, and averaging", "finite games", "Finite games"),
    ("COMB", "Pigeonhole, extremal principle, and averaging", "finite maps", "Finite maps"),
    ("GEO", "Circle geometry", "cyclic", "Cyclic"),
    ("GEO", "Circle geometry", "cyclic ratios", "Cyclic ratios"),
    ("GEO", "Circle geometry", "coaxal/cyclic geometry", "Coaxality / Radical Axis"),
    ("GEO", "Circle geometry", "auxiliary circles", "Auxiliary circles"),
    ("GEO", "Circle geometry", "circle power", "Circle power"),
    ("GEO", "Circle geometry", "angle/power of a point", "Angle/power of a point"),
    ("GEO", "Circle geometry", "parallel chords", "Parallel chords"),
    ("GEO", "Circle geometry", "perpendicular chords", "Perpendicular chords"),
    ("GEO", "Circle geometry", "tangency", "Tangency"),
    ("GEO", "Circle geometry", "equal tangents", "Equal tangents"),
    ("GEO", "Circle geometry", "circumcircle tangency", "Circumcircle tangency"),
    ("GEO", "Circle geometry", "incircle/tangent lengths", "Incircle/tangent lengths"),
    ("GEO", "Circle geometry", "coaxal/tangent circles", "Coaxal/tangent circles"),
    ("GEO", "Circle geometry", "coaxal systems", "Coaxality / Radical Axis"),
    ("GEO", "Circle geometry", "inversion/coaxality", "Inversion/coaxality"),
    ("GEO", "Circle geometry", "miquel/reim", "Miquel / Reim"),
    ("GEO", "Circle geometry", "miquel-type point", "Miquel Geometry"),
    ("GEO", "Circle geometry", "miquel/complete quadrilateral", "Miquel/complete quadrilateral"),
    ("GEO", "Circle geometry", "miquel/projective flavor", "Miquel/projective flavor"),
    ("GEO", "Circle geometry", "isogonal/spiral similarity", "Isogonal/spiral similarity"),
    ("GEO", "Triangle centers and triangle configurations", "orthocenter geometry", "Orthocenter geometry"),
    ("GEO", "Triangle centers and triangle configurations", "orthic geometry", "Orthic geometry"),
    ("GEO", "Triangle centers and triangle configurations", "cyclic/orthocenter", "Cyclic/orthocenter"),
    ("GEO", "Triangle centers and triangle configurations", "orthogonal projections", "Orthogonal projections"),
    ("GEO", "Triangle centers and triangle configurations", "euler line geometry", "Euler line geometry"),
    ("GEO", "Triangle centers and triangle configurations", "incenter lemma", "Incenter lemma"),
    ("GEO", "Triangle centers and triangle configurations", "angle bisectors/excenters", "Angle bisectors/excenters"),
    (
        "GEO",
        "Triangle centers and triangle configurations",
        "excenters/excentral triangle",
        "Excenters/excentral triangle",
    ),
    ("GEO", "Triangle centers and triangle configurations", "isosceles triangles", "Isosceles triangles"),
    ("GEO", "Triangle centers and triangle configurations", "isosceles configuration", "Isosceles configuration"),
    ("GEO", "Triangle centers and triangle configurations", "isosceles constraints", "Isosceles constraints"),
    ("GEO", "Triangle centers and triangle configurations", "acute triangles", "Acute triangles"),
    ("GEO", "Triangle centers and triangle configurations", "isogonal", "Isogonal Geometry"),
    ("GEO", "Triangle centers and triangle configurations", "isogonal structure", "Isogonal Geometry"),
    ("GEO", "Projective and advanced geometry", "projective/synthetic geometry", "Projective/synthetic geometry"),
    ("GEO", "Projective and advanced geometry", "synthetic geometry", "Synthetic geometry"),
    ("GEO", "Projective and advanced geometry", "inversion at aaa", "Inversion at AAA"),
    ("GEO", "Projective and advanced geometry", "isogonal/polar", "Isogonal / Polar"),
    ("GEO", "Projective and advanced geometry", "menelaus-style ratios", "Menelaus-style ratios"),
    ("GEO", "Core Euclidean geometry", "lattice polygon", "Lattice polygon"),
    ("GEO", "Core Euclidean geometry", "pick/shoelace", "Pick/shoelace"),
    ("COMB", "Coloring, tiling, grids, and invariants", "grid counting", "Grid counting"),
    ("COMB", "Coloring, tiling, grids, and invariants", "grid operations", "Grid operations"),
    ("COMB", "Pigeonhole, extremal principle, and averaging", "area pigeonhole", "Area pigeonhole"),
    ("GEO", "Core Euclidean geometry", "parallelogram law", "Parallelogram law"),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Integer domain",
        (
            "integer functional equation",
            "integer functional equations",
            "functional equation on integers",
            "functional equations on integers",
            "functions on integers",
            "functional equation on n",
            "functional equation on z",
            "functional equations on z",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Real domain",
        ("real functional equation", "real functional equations", "functional equations over r"),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Rational domain",
        (
            "functional equations rational domain",
            "functional equations (rational domain)",
            "rational-domain functional equations",
            "rational domain",
            "rational-domain rigidity",
            "rational-domain linearity",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Polynomial / coefficient FE",
        (
            "functional equation on coefficients",
            "functional equations on coefficients",
            "coefficient functional equation",
            "functional equations (polynomials)",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Polynomial-type behavior",
        (
            "polynomial-type rigidity",
            "polynomial-type / quadratic behavior",
            "quadratic-type functional equation",
            "quadratic-type functional equations",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Iteration / dynamics",
        (
            "functional equations / iteration",
            "functional equation / iteration",
            "functional recursion",
            "functional dynamics",
            "functional dynamics / mobius transform",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Symmetry / affine structure",
        (
            "functional equations / symmetry",
            "functional equation / symmetry",
            "functional equations (2 variables) / counting / affine structure",
            "two-variable functional equations",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Functional inequalities",
        (
            "functional inequalities",
            "functional inequality",
            "functional inequality / monotone arithmetic structure",
            "functional equation / monotone arithmetic structure",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Continuity / regularity",
        (
            "fe-style continuity",
            "functional equations; real analysis; continuity; isometries",
            "continuity in functional equations",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Set-valued functions",
        ("set-valued functional equation", "set-valued functional equations"),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Geometric FE",
        ("geometric functional equations", "geometric functional equation"),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Injectivity / surjectivity",
        (
            "injectivity/surjectivity tactics",
            "injectivity/surjectivity",
            "injective/surjective functions",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Image / value set",
        ("image/range", "image/range analysis", "range/value set", "value set"),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Linearity forcing",
        ("linearity forcing", "additivity/linearity forcing", "affine forcing"),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "IVT / Darboux",
        ("ivp/darboux", "ivt/darboux", "intermediate value/darboux"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Cauchy-Schwarz / Engel form",
        (
            "cauchy",
            "cauchy/engel",
            "cauchy engel",
            "cauchy engel form",
            "cauchy-schwarz/engel",
            "cauchy-schwarz engel",
            "cauchy-schwarz/engel form",
            "cauchy/titu",
            "titu/cauchy",
            "titu lemma",
            "titu's lemma",
            "engel form",
            "qm/cauchy",
            "rms/cauchy",
            "triangle/cauchy",
            "dyadic decomposition; cauchy-schwarz",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "H\u00f6lder",
        (
            "holder",
            "holder-type",
            "holder type",
            "holder inequality",
            "holder estimates",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Jensen / convexity",
        (
            "jensen",
            "jensen/log concavity",
            "jensen convexity",
            "jensen convexity/concavity",
            "jensen / convexity",
            "jensen-style smoothing",
            "weighted jensen",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Majorization / Karamata",
        (
            "majorization/karamata",
            "majorization",
            "karamata",
            "karamata inequality",
            "majorization smoothing",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Schur / Maclaurin / Muirhead",
        (
            "schur",
            "maclaurin",
            "muirhead",
            "schur/maclaurin",
            "schur/muirhead",
            "schur/am-gm",
            "newton/maclaurin",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "UVW / pqr method",
        ("uvw", "uvw method", "uvw/symmetric reduction", "pqr method", "pqr/uvw"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Smoothing",
        ("smoothing", "smoothing/equalization", "equalization", "smoothing method"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Sum of squares",
        (
            "sos",
            "sos/positivity",
            "sum of squares",
            "sums of squares",
            "sum-of-squares",
            "sos decomposition",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Classical mean inequalities",
        ("am-gm variants", "mean inequalities", "classical mean inequalities"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Harmonic estimates",
        ("harmonic estimates", "harmonic bounds", "harmonic inequality"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Tangent line method",
        ("tangent-line estimate", "tangent line estimate", "tangent-line method", "tangent-line bounding"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Convexity",
        ("convexity", "convexity method", "convexity/concavity", "log-convexity", "log concavity"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Homogeneity / homogenization",
        ("homogeneity", "homogenization", "homogeneous inequality", "homogeneous inequalities"),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Best constant / equality case",
        (
            "best constant search",
            "best constant",
            "equality case",
            "equality cases",
            "equality forcing",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Triangle substitutions",
        (
            "ravi substitution",
            "ravi/triangle substitutions",
            "triangle substitution",
            "triangle substitutions",
            "triangle-substitution inequalities",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Polynomial identities",
        (
            "polynomial identification",
            "polynomial identity",
            "polynomial identities",
            "identity theorem",
            "polynomial zero identity",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Coefficient comparison",
        (
            "coefficient comparison",
            "coefficient chase",
            "coefficient extraction",
            "coefficient method",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Factorization",
        (
            "factorisation",
            "factorization",
            "factor theorem",
            "factorization tricks",
            "polynomial factorization",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Irreducibility",
        ("irreducibility", "eisenstein", "eisenstein criterion", "gauss lemma"),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Interpolation",
        (
            "interpolation",
            "lagrange interpolation",
            "newton interpolation",
            "polynomial interpolation",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Finite differences",
        (
            "finite-difference identity",
            "finite differences",
            "finite-difference method",
            "divided differences",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Root location / relations",
        ("root location", "root relations", "polynomial roots", "root bounds"),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Real-rootedness / interlacing",
        (
            "real-rooted polynomials/interlacing/perturbation",
            "real-rootedness",
            "real-rooted polynomials",
            "root interlacing",
            "interlacing",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Roots of unity / cyclotomic",
        (
            "roots of unity averaging",
            "roots of unity",
            "roots of unity filter",
            "cyclotomic",
            "cyclotomic polynomials",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Symmetric polynomials / Vieta-Newton",
        (
            "symmetric polynomials",
            "vieta-newton",
            "vieta/newton",
            "vieta relations",
            "newton sums",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Homogeneous polynomials",
        ("homogeneous polynomials", "homogeneous polynomial"),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Special polynomial families",
        (
            "chebyshev polynomials",
            "reciprocal polynomials",
            "self-reciprocal polynomials",
            "trigonometric polynomials",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Zero-set method",
        ("zero-set rigidity", "zero-set method", "zero-set analysis"),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Fejer-Riesz",
        (
            "fejer-riesz",
            "fejer/riesz",
            "fejer/riesz-type extremals",
            "fejer-riesz-type extremals",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Recurrence growth / asymptotics",
        (
            "recurrence asymptotics",
            "growth/asymptotics",
            "recurrence growth",
            "linear recurrence asymptotics",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Linearization / telescoping",
        ("linearization/telescoping", "recurrence linearization", "telescoping recurrence"),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Fibonacci / Lucas / Chebyshev",
        (
            "fibonacci/chebyshev",
            "fibonacci/lucas",
            "fibonacci",
            "lucas sequences",
            "chebyshev recurrences",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Zeckendorf",
        ("zeckendorf", "zeckendorf representation", "zeckendorf decomposition"),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Generating functions",
        (
            "generating functions",
            "generating function",
            "formal power series",
            "series/generating functions",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Summation techniques",
        ("summation techniques", "summation by parts", "abel summation", "sums of powers"),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Telescoping",
        (
            "telescoping",
            "telescoping sums",
            "telescoping products",
            "telescoping product bounds",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Periodicity",
        ("periodicity", "periodic sequences", "eventual periodicity", "recurrence modulo m"),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Floor / ceiling / fractional part",
        (
            "floor/ceiling inequalities",
            "floor ceiling inequalities",
            "floor/ceiling",
            "floor and ceiling",
            "fractional parts",
            "fractional part",
            "floor sequences",
            "beatty sequences",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Iteration / fixed points",
        ("iteration", "iterative processes", "dynamical sequences", "fixed-point iteration"),
    ),
    *_stored_aliases(
        "ALG",
        "Algebraic structures and linear algebra",
        "Mobius / fractional-linear transformation",
        (
            "mobius transformation",
            "mobius transformations",
            "mobius transform",
            "linear fractional transformation",
            "fractional-linear transformation",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Algebraic structures and linear algebra",
        "Rank / kernel / image",
        ("rank/kernel/image", "rank kernel image", "kernel/image", "rank-nullity"),
    ),
    *_stored_aliases(
        "ALG",
        "Algebraic structures and linear algebra",
        "Finite algebraic structures",
        (
            "finite semigroups",
            "semigroups",
            "monoids",
            "finite groups",
            "finite rings",
            "finite fields",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Algebraic structures and linear algebra",
        "Grobner bases",
        ("grobner", "grobner basis", "grobner bases"),
    ),
    *_stored_aliases(
        "NT",
        "p-adic and valuation methods",
        "p-adic methods",
        (
            "p-adic/newton polygon ideas",
            "p-adic methods",
            "p-adic arguments",
            "p-adic structure",
            "p-adic valuation",
            "newton polygon",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Congruences and modular arithmetic",
        "Modular methods",
        (
            "modular methods",
            "modular arithmetic",
            "modular constraints",
            "modular obstruction",
            "modular obstructions",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Divisibility, gcd, lcm, and primes",
        "GCD / divisibility",
        ("gcd/divisibility", "divisibility/gcd", "gcd dynamics", "divisibility obstruction"),
    ),
    *_stored_aliases(
        "ALG",
        "Equations, substitutions, and transformations",
        "Product normalization",
        ("substitution xyz=1", "xyz=1", "product normalization", "normalization xyz"),
    ),
    *_stored_aliases(
        "ALG",
        "Equations, substitutions, and transformations",
        "Symmetric / cyclic expressions",
        (
            "symmetric/cyclic expressions",
            "symmetric cyclic expressions",
            "symmetric and cyclic expressions",
            "cyclic expressions",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Equations, substitutions, and transformations",
        "Substitution / transformation",
        ("substitution/transformation", "substitution tactics", "change of variables"),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Energy / potential method",
        ("lyapunov energy", "energy method", "potential method", "potential function"),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Invariants / monovariants",
        ("monovariant", "invariant/monovariant", "ordering invariant", "descent invariant"),
    ),
    *_stored_aliases(
        "COMB",
        "Set systems, posets, and extremal set theory",
        "Folner-type sets",
        ("folner", "folner sets", "folner-type sets"),
    ),
    *_stored_aliases(
        "GEO",
        "Core Euclidean geometry",
        "Projections",
        ("projection", "projections", "projection methods"),
    ),
    *_stored_aliases(
        "GEO",
        "Core Euclidean geometry",
        "Coordinate geometry",
        (
            "vectors",
            "complex plane",
            "barycentric distances",
            "rational slopes",
            "coordinate dynamics",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Cauchy-Schwarz / Engel form",
        (
            "inequalities cauchy engel",
            "inequalities (cauchy/engel",
            "cauchy-shwarz/titu",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Convexity / Jensen methods",
        (
            "concavity/convexity",
            "convexity/smoothing",
            "jensen/convexity",
            "discrete convexity",
            "convex sequences",
            "convexity/karamata",
            "convexity/tangent line",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Smoothing",
        (
            "pairwise smoothing",
            "cyclic smoothing",
            "symmetric smoothing",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "UVW / pqr method",
        (
            "uvw/smoothing",
            "uvw/pqr",
            "uvw/sos",
            "uvw-style reduction",
            "schur/uvw",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Rearrangement / majorization",
        (
            "rearrangement",
            "rearrangement/majorization",
            "chebyshev/rearrangement",
            "convexity/majorization",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Best constant / equality case",
        (
            "equality analysis",
            "equality characterization",
            "equality condition",
            "equality hunting",
            "equality search",
            "sharp constant",
            "sharp constants",
            "sharpness",
            "sharp inequality",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Bounding / estimates",
        (
            "bounding",
            "bounds",
            "boundedness",
            "bounding tricks",
            "estimates",
            "estimation",
            "asymptotic bounds",
            "crude estimates",
            "growth estimates",
            "product bounds",
            "error bounds",
            "floor estimates",
            "integral bounds",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Polynomial identities",
        (
            "algebraic identities",
            "identities",
            "symmetric identities",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Polynomial method",
        ("polynomial method", "integer polynomials"),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Rational / integer roots",
        (
            "rational root theorem",
            "rational roots",
            "integer roots",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Discriminant methods",
        (
            "discriminant",
            "discriminants",
            "quadratic discriminant",
            "discriminant bounds",
            "discriminant tricks",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Polynomial roots",
        (
            "roots",
            "real roots",
            "complex roots",
            "root counting",
            "root localization",
            "root multiplicity",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Roots of unity / cyclotomic",
        (
            "unit circle",
            "cyclotomic factors",
            "cyclotomic factor",
            "cyclotomic division",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Integer-valued polynomials / functions",
        (
            "integer polynomials",
            "integer-valued",
            "integer-valued functions",
            "integer-valued maps",
            "integer-valued constraints",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Coefficient methods",
        (
            "coefficient analysis",
            "coefficient constraints",
            "coefficient estimates",
            "coefficient matching",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Polynomials and algebraic manipulation",
        "Degree arguments",
        (
            "degree argument",
            "degree bounds",
            "degree comparison",
            "degree control",
            "degree descent",
            "degree/leading coefficient",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Sums / prefixes / summation",
        (
            "partial sums",
            "prefix sums",
            "prefix products",
            "summation",
            "finite sums",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Summation by parts / Abel summation",
        ("abel summation", "summation by parts"),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Telescoping",
        (
            "telescoping bounds",
            "telescoping potential",
            "telescoping product",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Dynamics / iteration / fixed points",
        (
            "dynamics",
            "dynamical systems",
            "discrete dynamics",
            "continuous dynamics",
            "iterates",
            "orbits",
            "orbit analysis",
            "fixed point",
            "fixed points",
            "periodic orbits",
            "real dynamics",
            "logarithmic dynamics",
            "stabilization",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Sequences, recurrences, and series",
        "Periodicity",
        ("periodic functions", "periodic orbits"),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Injectivity / surjectivity / bijectivity",
        (
            "injectivity",
            "surjectivity/injectivity",
            "injectivity/surjectivity forcing",
            "injective maps",
            "surjectivity",
            "bijectivity",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Functional equations",
        "Real analysis tools",
        (
            "analysis",
            "calculus",
            "continuity",
            "continuous functions",
            "derivative",
            "derivatives",
            "integration",
            "integrals",
            "ivt",
            "mvt",
            "rolle",
            "darboux property",
            "one-sided derivatives",
            "one-sided limits",
            "riemann sums",
            "integral comparison",
            "taylor estimate",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Algorithms, automata, words, and constructive combinatorics",
        "Constructive methods",
        (
            "construction",
            "constructions",
            "constructive",
            "constructive classification",
            "constructive characterization",
            "exact construction",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Algorithms, automata, words, and constructive combinatorics",
        "Counterexample construction",
        (
            "counterexample",
            "construction/counterexample",
            "counterexample construction",
            "adversarial construction",
            "greedy construction",
            "block construction",
            "constructive partition",
            "congruence construction",
            "divisibility construction",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Extremal methods",
        (
            "extremal methods",
            "extremal choice",
            "extremal counting",
            "extremal averaging",
            "extremal construction",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Extremal sequence",
        ("extremal sequence",),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Extremal graph",
        ("extremal graph",),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Extremal configuration",
        ("extremal configuration",),
    ),
    *_stored_aliases(
        "ALG",
        "Inequalities and optimization",
        "Extremal inequality",
        ("extremal inequality",),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Invariants / monovariants",
        (
            "invariant",
            "invariants/monovariants",
            "modular invariant",
            "recurrence invariant",
            "carry/greedy invariant",
            "discrepancy invariant",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Energy / potential method",
        (
            "potential functions",
            "potential method",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Coloring, tiling, grids, and invariants",
        "Parity methods",
        (
            "parity",
            "parity obstruction",
            "parity split",
            "parity splitting",
            "parity cases",
            "parity structure",
            "mod 2",
            "degree parity",
            "digital sums/parity",
            "cyclic indexing/parity",
            "construction/parity",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Casework / finite checking",
        (
            "casework",
            "case analysis",
            "case split",
            "case splits",
            "finite checking",
            "elementary cases",
            "edge cases",
            "sign cases",
            "boundary cases",
            "degeneracy cases",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Counting and enumerative combinatorics",
        "Permutations / swaps",
        (
            "permutation",
            "permutations",
            "permutation structure",
            "transpositions",
            "adjacent swaps",
            "involution",
            "involutions",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Pigeonhole, extremal principle, and averaging",
        "Discrete / combinatorial structure",
        (
            "pigeonhole",
            "density",
            "covering",
            "coverings",
            "finite sets",
            "partitioning",
            "infinite pigeonhole",
            "interval covering",
            "layer-cake",
            "double counting",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Counting and enumerative combinatorics",
        "Counting / enumeration",
        (
            "enumeration",
            "counting pairs",
        ),
    ),
    *_stored_aliases(
        "COMB",
        "Graph theory",
        "Graph representation",
        (
            "graph representation",
            "graph constraints",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Congruences and modular arithmetic",
        "Modular arithmetic / residues",
        (
            "modular residues",
            "residues",
            "coprime residues",
            "modular reduction",
            "modular cases",
            "mod p",
            "mod 2",
            "modular intervals",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Congruences and modular arithmetic",
        "Chinese remainder theorem",
        (
            "crt",
            "chinese remainder theorem",
            "crt-style construction",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Congruences and modular arithmetic",
        "Multiplicative orders / LTE",
        (
            "orders",
            "congruences/orders",
            "zsigmondy/lte",
            "multiplicative orders",
        ),
    ),
    *_stored_aliases(
        "NT",
        "p-adic and valuation methods",
        "Valuations / p-adic methods",
        (
            "prime valuations",
            "p-adic divisibility",
            "2-adic periodicity",
        ),
    ),
    *_stored_aliases(
        "NT",
        "p-adic and valuation methods",
        "Multiplicative orders / LTE",
        ("zsigmondy/lte",),
    ),
    *_stored_aliases(
        "NT",
        "Divisibility, gcd, lcm, and primes",
        "GCD / LCM",
        (
            "gcd/lcm",
            "gcd normalization",
            "elementary divisibility",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Divisibility, gcd, lcm, and primes",
        "Square gaps",
        (
            "squares gap",
            "square gaps",
        ),
    ),
    *_stored_aliases(
        "NT",
        "Diophantine equations and descent",
        "Linear Diophantine equations",
        ("linear diophantine equations",),
    ),
    *_stored_aliases(
        "NT",
        "Diophantine equations and descent",
        "Integer constraints / descent",
        (
            "integer constraints",
            "integer descent",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Equations, substitutions, and transformations",
        "Cyclic sums",
        (
            "cyclic sum",
            "cyclic sums",
            "cyclic sums)",
            "cyclic symmetric sums",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Equations, substitutions, and transformations",
        "Symmetric sums / identities",
        (
            "symmetric sums",
            "symmetric identities",
            "symmetric expressions",
            "symmetric forms",
            "symmetric sums and identities",
        ),
    ),
    *_stored_aliases(
        "ALG",
        "Equations, substitutions, and transformations",
        "Symmetric / cyclic expressions",
        (
            "symmetric",
            "symmetry tricks",
            "cyclic symmetry",
            "symmetrization",
            "symmetric reduction",
            "cyclic substitution",
            "symmetric substitution",
        ),
    ),
    *_stored_aliases(
        "GEO",
        "Core Euclidean geometry",
        "Geometry: Euclidean / metric",
        (
            "euclidean geometry",
            "metric geometry",
            "trigonometric geometry",
            "triangle inequalities",
            "similarity",
            "reflections",
            "rotations",
            "collinearity",
            "orthogonality",
            "medians",
            "centers",
            "heron",
            "fermat point",
            "area method",
        ),
    ),
)


TAXONOMY_TEXT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\u221a\xf1", "o"),
    ("\u221a\xd1", "O"),
    ("\u221a\xe2", "e"),
    ("\u221a\xf2", "o"),
    ("\u201a\xc4\xec", "-"),
    ("\u201a\xc4\xee", "-"),
    ("\u201a\xc4\xfa", '"'),
    ("\u201a\xc4\xf9", '"'),
)


TAXONOMY_AREA_PREFIX_RE = re.compile(
    r"^\s*(?:ALG|NT|GEO|COMB)(?:\s*/\s*(?:ALG|NT|GEO|COMB))*\s*[-:\u2013\u2014]\s*",
    flags=re.IGNORECASE,
)


def _taxonomy_key(value: str) -> str:
    value = repair_topic_tag_text(value)
    for old, new in TAXONOMY_TEXT_REPLACEMENTS:
        value = value.replace(old, new)
    value = TAXONOMY_AREA_PREFIX_RE.sub("", value or "")
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = normalized.casefold()
    normalized = normalized.replace("\\", "")
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _taxonomy_entry(
    main_topic: str,
    canonical_subtopic: str,
    technique: str,
    *,
    stored_technique: str | None = None,
    normalization: tuple[str, str] = (NORMALIZATION_STATUS_ALIAS, NORMALIZATION_CONFIDENCE_HIGH),
) -> SubtopicTaxonomyEntry:
    return SubtopicTaxonomyEntry(
        main_topic=main_topic,
        canonical_subtopic=canonical_subtopic,
        technique=technique,
        stored_technique=normalize_topic_tag(stored_technique or technique),
        normalization_status=normalization[0],
        normalization_confidence=normalization[1],
    )


def _add_first_pass_canonical_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    for canonical_subtopic in FIRST_PASS_CANONICAL_SUBTOPICS:
        lookup[_taxonomy_key(canonical_subtopic)] = _taxonomy_entry(
            FIRST_PASS_CANONICAL_MAIN_TOPICS[canonical_subtopic],
            canonical_subtopic,
            canonical_subtopic,
            normalization=(NORMALIZATION_STATUS_CANONICAL, NORMALIZATION_CONFIDENCE_HIGH),
        )


def _add_existing_taxonomy_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    canonical_pairs: set[tuple[str, str]] = set()
    for main_topic, canonical_subtopic, technique in CANONICAL_SUBTOPIC_TAXONOMY:
        pair = (main_topic, canonical_subtopic)
        if pair not in canonical_pairs:
            canonical_pairs.add(pair)
            canonical_entry = _taxonomy_entry(main_topic, canonical_subtopic, canonical_subtopic)
            lookup.setdefault(_taxonomy_key(canonical_subtopic), canonical_entry)
        lookup.setdefault(
            _taxonomy_key(technique),
            _taxonomy_entry(main_topic, canonical_subtopic, technique),
        )


def _add_parent_collapse_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    for main_topic, canonical_subtopic, alias in PARENT_COLLAPSE_SUBTOPIC_ALIASES:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            main_topic,
            canonical_subtopic,
            alias,
            stored_technique=canonical_subtopic,
        )


def _add_stored_technique_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    for main_topic, canonical_subtopic, alias, stored_technique in STORED_TECHNIQUE_SUBTOPIC_ALIASES:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            main_topic,
            canonical_subtopic,
            alias,
            stored_technique=stored_technique,
        )


def _add_additional_alias_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    for main_topic, canonical_subtopic, alias in ADDITIONAL_SUBTOPIC_ALIASES:
        lookup.setdefault(
            _taxonomy_key(alias),
            _taxonomy_entry(main_topic, canonical_subtopic, alias),
        )


def _add_first_pass_parent_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    for main_topic, canonical_subtopic, alias in FIRST_PASS_PARENT_ALIASES:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            main_topic,
            canonical_subtopic,
            alias,
        )


def _add_first_pass_stored_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    for main_topic, canonical_subtopic, alias, stored_technique in FIRST_PASS_STORED_ALIASES:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            main_topic,
            canonical_subtopic,
            alias,
            stored_technique=stored_technique,
        )


def _add_status_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    for alias in METHOD_ONLY_TAGS:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            "",
            "",
            alias,
            normalization=(NORMALIZATION_STATUS_METHOD, NORMALIZATION_CONFIDENCE_HIGH),
        )
    for alias in INVALID_TAGS:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            "",
            "Data-quality / invalid tag",
            alias,
            normalization=(NORMALIZATION_STATUS_INVALID, NORMALIZATION_CONFIDENCE_HIGH),
        )


def _add_number_theory_entries(lookup: dict[str, SubtopicTaxonomyEntry]) -> None:
    for main_topic, canonical_subtopic, alias, stored_technique in NUMBER_THEORY_STORED_ALIASES:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            main_topic,
            canonical_subtopic,
            alias,
            stored_technique=stored_technique,
        )
    for alias, stored_technique in NUMBER_THEORY_METHOD_ALIASES:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            "",
            "",
            alias,
            stored_technique=stored_technique,
            normalization=(NORMALIZATION_STATUS_METHOD, NORMALIZATION_CONFIDENCE_HIGH),
        )
    for alias in METADATA_TAGS:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            "",
            "",
            alias,
            normalization=(NORMALIZATION_STATUS_METADATA, NORMALIZATION_CONFIDENCE_HIGH),
        )
    for alias in CORRUPT_TAGS:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            "",
            "Data-quality / invalid tag",
            alias,
            normalization=(NORMALIZATION_STATUS_CORRUPT, NORMALIZATION_CONFIDENCE_HIGH),
        )


def _build_taxonomy_lookup() -> dict[str, SubtopicTaxonomyEntry]:
    lookup: dict[str, SubtopicTaxonomyEntry] = {}
    _add_first_pass_canonical_entries(lookup)
    _add_existing_taxonomy_entries(lookup)
    _add_parent_collapse_entries(lookup)
    _add_stored_technique_entries(lookup)
    _add_additional_alias_entries(lookup)
    _add_first_pass_parent_entries(lookup)
    _add_first_pass_stored_entries(lookup)
    _add_status_entries(lookup)
    return lookup


def _build_number_theory_lookup() -> dict[str, SubtopicTaxonomyEntry]:
    lookup: dict[str, SubtopicTaxonomyEntry] = {}
    _add_number_theory_entries(lookup)
    return lookup


TAXONOMY_LOOKUP = _build_taxonomy_lookup()
NUMBER_THEORY_LOOKUP = _build_number_theory_lookup()

NUMBER_THEORY_DOMAIN_ALIASES = {"NT", "NUMBER THEORY", "NUMBER_THEORY"}
NUMBER_THEORY_AMBIGUOUS_KEYS = frozenset(
    _taxonomy_key(alias)
    for alias in (
        "cyclic groups",
        "lattice",
        "lattices",
        "lattice points",
        "extremal argument",
        "extremal process",
        "extremal structure",
        "graph modeling",
        "ordering",
        "parametrization",
        "rational parametrization",
        "substitution",
        "scaling",
        "transformation",
    )
)
NUMBER_THEORY_STRONG_TOKENS = (
    "CRT",
    "P-ADIC",
    "2-ADIC",
    "LTE",
    "ZSIGMONDY",
    "DIOPHANTINE",
    "PELL",
    "VIETA",
    "LEGENDRE",
    "BEZOUT",
    "B\u00c9ZOUT",
    "FERMAT",
    "WILSON",
    "EULER",
    "TOTIENT",
    "PHI",
    "PRIME",
    "GCD",
    "LCM",
    "CONGRUENCE",
    "CONGRUENCES",
    "MODULAR",
    "MODULO",
    "RESIDUE",
    "RESIDUES",
    "DIVISIBILITY",
    "VALUATION",
    "M\u00d6BIUS",
    "MOBIUS",
    "DIRICHLET",
    "SIEVE",
    "SQUAREFREE",
    "PYTHAGOREAN",
    "GAUSSIAN INTEGER",
    "FINITE FIELD",
    "CHARACTER SUM",
    "PISANO",
)


GARBAGE_FRAGMENT_MAX_LENGTH = 2

EXCEPTION_PATTERN_RULES: tuple[TaxonomyPatternRule, ...] = (
    TaxonomyPatternRule("ALG", "Functional equations", tokens=("CAUCHY EQUATION",)),
    TaxonomyPatternRule(
        "ALG",
        "Functional equations",
        tokens=("POLYNOMIAL FE", "POLYNOMIAL FUNCTIONAL EQUATION"),
        stored_technique="Polynomial functional equation",
    ),
    TaxonomyPatternRule("ALG", "Functional equations", tokens=("FUNCTIONAL GRAPH",)),
    TaxonomyPatternRule(
        "ALG",
        "Equations, substitutions, and transformations",
        tokens=("RATIONAL PARAMETRIZATION",),
    ),
    TaxonomyPatternRule("GEO", "Geometry-flavored algebra", tokens=("TANGENT LENGTH",)),
    TaxonomyPatternRule("ALG", "Inequalities and optimization", tokens=("TRIGONOMETRIC INEQUALITY",)),
    TaxonomyPatternRule(
        "ALG",
        "Complex, trigonometric, and Fourier methods",
        tokens=("TRIGONOMETRIC IDENTIT", "TRIG IDENTIT"),
    ),
)

GENERIC_PATTERN_RULES: tuple[TaxonomyPatternRule, ...] = (
    TaxonomyPatternRule(
        "ALG",
        "Inequalities and optimization",
        tokens=("INEQUAL",),
        words=("KARAMATA", "SCHUR", "MUIRHEAD", "SMOOTHING", "UVW", "SOS"),
    ),
    TaxonomyPatternRule(
        "ALG",
        "Sequences, recurrences, and series",
        tokens=("RECURREN", "RECURS", "FIBONACCI", "LUCAS", "TELESCOP", "SEQUENCE"),
    ),
    TaxonomyPatternRule(
        "ALG",
        "Polynomials and algebraic manipulation",
        tokens=("POLYNOMIAL", "FACTOR", "INTERPOL", "ROOT", "COEFFICIENT", "DISCRIMINANT"),
    ),
    TaxonomyPatternRule(
        "ALG",
        "Discrete functions, floors, rounding, and base representation",
        tokens=("FLOOR", "ROUND", "BASE", "BINARY", "DYADIC", "DIGIT", "DECIMAL", "AUTOMATA"),
    ),
    TaxonomyPatternRule(
        "ALG",
        "Extremal methods, monotonicity, and invariants",
        tokens=("EXTREMAL", "MONOTON", "RIGID", "INVARIANT", "MONOVARIANT"),
        words=("ORDERING", "GROWTH", "DESCENT", "MINIMAX", "STABILITY", "UNIQUENESS"),
    ),
    TaxonomyPatternRule(
        "NT",
        "Number-theoretic algebra",
        tokens=("VIETA", "DIVIS", "VALUATION", "P-ADIC", "MODULAR", "CONGRUENCE", "GCD"),
        words=("PELL", "SQUARES", "FACTORIALS", "INTEGRALITY"),
    ),
    TaxonomyPatternRule(
        "COMB",
        "Combinatorial algebra and counting",
        tokens=("COUNT", "PAIRING", "PERMUT", "GRAPH", "MATCHING", "GAME", "DYNAMIC PROGRAMMING"),
    ),
    TaxonomyPatternRule(
        "GEO",
        "Geometry-flavored algebra",
        tokens=("COORDINATE", "LATTICE", "POLYGON", "TRIANGLE", "TANGENT", "ROTATION", "VECTOR"),
    ),
    TaxonomyPatternRule(
        "ALG",
        "Analytic estimates and asymptotics",
        tokens=("ASYMPTOT", "APPROX", "LIMIT", "CONVERGEN", "CALCULUS", "DERIVATIVE", "INTEGRAL"),
    ),
    TaxonomyPatternRule(
        "ALG",
        "Complex, trigonometric, and Fourier methods",
        tokens=("TRIG", "FOURIER", "PARSEVAL", "HYPERBOLIC"),
        padded_tokens=(" COMPLEX ",),
    ),
)


NUMBER_THEORY_PATTERN_RULES: tuple[TaxonomyPatternRule, ...] = (
    TaxonomyPatternRule(
        "NT",
        "Primitive divisors and Zsigmondy-type ideas",
        tokens=("ZSIGMONDY", "PRIMITIVE DIVISOR", "PRIMITIVE PRIME"),
        stored_technique="Primitive divisors / Zsigmondy",
    ),
    TaxonomyPatternRule(
        "NT",
        "LTE and exponent lifting",
        tokens=("LTE", "LIFTING EXPONENT", "EXPONENT LIFT"),
        stored_technique="LTE / exponent lifting",
    ),
    TaxonomyPatternRule(
        "NT",
        "Chinese remainder theorem and local-to-global methods",
        tokens=("CRT", "CHINESE REMAINDER", "LOCAL-GLOBAL", "LOCAL TO GLOBAL"),
        stored_technique="Chinese remainder theorem / local-global",
    ),
    TaxonomyPatternRule(
        "NT",
        "p-adic and valuation methods",
        tokens=("P-ADIC", "2-ADIC", "VALUATION", "V_2", "V2"),
        stored_technique="Valuations / p-adic methods",
    ),
    TaxonomyPatternRule(
        "NT",
        "Orders, primitive roots, and unit groups",
        tokens=("PRIMITIVE ROOT", "UNIT GROUP", "UNITS MOD", "ORDER MOD", "ORDERS MOD"),
        words=("ORDER", "ORDERS"),
        stored_technique="Orders / primitive roots / unit groups",
    ),
    TaxonomyPatternRule(
        "NT",
        "Congruences and modular arithmetic",
        tokens=("CONGRU", "MODULAR", "MODULO", "RESIDUE", "FERMAT", "WILSON", "EULER THEOREM"),
        padded_tokens=(" MOD ",),
        stored_technique="Modular arithmetic / residues",
    ),
    TaxonomyPatternRule(
        "NT",
        "Divisibility, gcd, lcm, and factorization",
        tokens=("DIVIS", "GCD", "LCM", "COPRIME", "COPRIMAL", "BEZOUT", "B\u00c9ZOUT", "EUCLIDEAN"),
        stored_technique="Divisibility / GCD / factorization",
    ),
    TaxonomyPatternRule(
        "NT",
        "Prime numbers and prime divisors",
        tokens=("PRIME", "FACTOR STRUCTURE", "FACTORIAL DIVISIBILITY"),
        stored_technique="Primes / prime divisors",
    ),
    TaxonomyPatternRule(
        "NT",
        "Pell-type equations and Vieta jumping",
        tokens=("PELL", "VIETA"),
        stored_technique="Pell / Vieta jumping",
    ),
    TaxonomyPatternRule(
        "NT",
        "Diophantine equations and descent",
        tokens=("DIOPHANTINE",),
        stored_technique="Diophantine equations",
    ),
    TaxonomyPatternRule(
        "NT",
        "Quadratic residues, squares, and squarefree methods",
        tokens=("QUADRATIC RESIDUE", "LEGENDRE", "SQUAREFREE", "SQUARE-FREE", "SQUARE CLASS"),
        stored_technique="Quadratic residues / squarefree",
    ),
    TaxonomyPatternRule(
        "NT",
        "Quadratic forms and sums of squares",
        tokens=("SUMS OF SQUARES", "SUMS OF TWO SQUARES", "PYTHAGOREAN", "QUADRATIC FORM"),
        stored_technique="Quadratic forms / sums of squares",
    ),
    TaxonomyPatternRule(
        "NT",
        "Arithmetic functions and divisor structure",
        tokens=("PHI", "TOTIENT", "TAU", "OMEGA", "DIVISOR FUNCTION", "SIGMA FUNCTION"),
        stored_technique="Arithmetic functions / divisor structure",
    ),
    TaxonomyPatternRule(
        "NT",
        "M\u00f6bius inversion and inclusion-exclusion",
        tokens=("M\u00d6BIUS", "MOBIUS", "DIRICHLET CONVOLUTION"),
        stored_technique="M\u00f6bius inversion",
    ),
    TaxonomyPatternRule(
        "NT",
        "Base, digit, and carry methods",
        tokens=("BASE", "DIGIT", "DECIMAL", "CARRY", "CARRIES", "REPUNIT", "REPDIGIT"),
        stored_technique="Base / digit / carry methods",
    ),
    TaxonomyPatternRule(
        "NT",
        "Binary and dyadic methods",
        tokens=("BINARY", "DYADIC", "POWERS OF TWO", "POWERS OF 2"),
        stored_technique="Binary / dyadic methods",
    ),
    TaxonomyPatternRule(
        "NT",
        "Fibonacci, Lucas, Chebyshev, and special recurrences",
        tokens=("FIBONACCI", "LUCAS", "CHEBYSHEV", "PELL SEQUENCE"),
        stored_technique="Fibonacci / Lucas / Chebyshev",
    ),
    TaxonomyPatternRule(
        "NT",
        "Sequences, recurrences, and finite dynamics",
        tokens=("RECURREN", "PERIODIC", "PISANO", "FINITE DYNAMIC", "FINITE-STATE"),
        stored_technique="Recurrences / finite dynamics",
    ),
    TaxonomyPatternRule(
        "NT",
        "Polynomial methods over integers and residues",
        tokens=("POLYNOMIAL",),
        stored_technique="Polynomials over integers / residues",
    ),
    TaxonomyPatternRule(
        "NT",
        "Finite fields, characters, and advanced modular tools",
        tokens=("FINITE FIELD", "CHARACTER SUM", "GAUSS SUM", "CHEVALLEY", "ROOT-OF-UNITY"),
        stored_technique="Finite fields / characters",
    ),
    TaxonomyPatternRule(
        "NT",
        "Algebraic number theory flavor",
        tokens=("ALGEBRAIC INTEGER", "ALGEBRAIC NUMBER", "GAUSSIAN INTEGER", "NORM FORM", "CYCLOTOMIC FIELD"),
        stored_technique="Algebraic number theory",
    ),
    TaxonomyPatternRule(
        "NT",
        "Additive number theory and zero-sum methods",
        tokens=("ZERO-SUM", "SUMSET", "ADDITIVE", "CAUCHY-DAVENPORT"),
        stored_technique="Additive number theory / zero-sum",
    ),
    TaxonomyPatternRule(
        "NT",
        "Multiplicative structure and semigroups",
        tokens=("MULTIPLICATIVE", "SEMIGROUP", "PRODUCT SET"),
        stored_technique="Multiplicative structure / semigroups",
    ),
    TaxonomyPatternRule(
        "NT",
        "Floor, rounding, Beatty, Farey, and approximation methods",
        tokens=("FLOOR", "ROUND", "BEATTY", "FAREY", "APPROXIMATION", "CONTINUED FRACTION"),
        stored_technique="Floor / rounding / approximation",
    ),
    TaxonomyPatternRule(
        "NT",
        "Lattice and integer geometry methods",
        tokens=("LATTICE", "PICK-STYLE", "PICK STYLE", "INTEGER GEOMETRY"),
        stored_technique="Lattice / integer geometry",
    ),
    TaxonomyPatternRule(
        "NT",
        "Sieve, density, and asymptotic estimates",
        tokens=("SIEVE", "DENSITY", "ASYMPTOT", "SPARSITY", "SMOOTH NUMBER", "SMOOTHNESS"),
        stored_technique="Sieve / density / asymptotics",
    ),
)


NUMBER_THEORY_METHOD_PATTERN_RULES: tuple[TaxonomyPatternRule, ...] = (
    TaxonomyPatternRule("", "", tokens=("EXTREMAL",), stored_technique="Extremal method"),
    TaxonomyPatternRule("", "", tokens=("CONSTRUCTIVE", "CONSTRUCTION"), stored_technique="Construction"),
    TaxonomyPatternRule(
        "",
        "",
        tokens=("CONTRADICTION", "OBSTRUCTION"),
        stored_technique="Contradiction / obstruction",
    ),
    TaxonomyPatternRule("", "", tokens=("BOUNDING", "BOUNDS", "ESTIMATE"), stored_technique="Bounding and estimates"),
    TaxonomyPatternRule(
        "",
        "",
        tokens=("INVARIANT", "RIGID", "CLOSURE"),
        stored_technique="Invariants, closure, and rigidity",
    ),
    TaxonomyPatternRule(
        "",
        "",
        tokens=("PIGEONHOLE", "PAIRING", "INJECTION", "BIJECTION"),
        stored_technique="Pigeonhole, pairing, injection",
    ),
    TaxonomyPatternRule(
        "",
        "",
        tokens=("CASEWORK", "FINITE CHECK", "CASES"),
        stored_technique="Casework and finite checking",
    ),
    TaxonomyPatternRule(
        "",
        "",
        tokens=("GREEDY", "GAME STRATEGY"),
        stored_technique="Greedy / optimization / adversarial strategy",
    ),
    TaxonomyPatternRule(
        "",
        "",
        tokens=("GRAPH", "MATCHING", "ORDERING"),
        stored_technique="Graph / matching / ordering model",
    ),
    TaxonomyPatternRule(
        "",
        "",
        tokens=("PARAMETRIZATION", "SUBSTITUTION", "SCALING"),
        stored_technique="Transformations and parametrization",
    ),
)


def _invalid_pattern_entry(repaired: str, normalized: str, key: str) -> SubtopicTaxonomyEntry | None:
    if len(key) <= GARBAGE_FRAGMENT_MAX_LENGTH and not key.isdigit():
        return _taxonomy_entry(
            "",
            "Data-quality / invalid tag",
            normalized,
            normalization=(NORMALIZATION_STATUS_INVALID, NORMALIZATION_CONFIDENCE_HIGH),
        )
    if key.isdigit() or re.fullmatch(r"\d+\)?", repaired.strip()):
        return _taxonomy_entry(
            "",
            "Data-quality / invalid tag",
            normalized,
            normalization=(NORMALIZATION_STATUS_INVALID, NORMALIZATION_CONFIDENCE_HIGH),
        )
    return None


def _corrupt_pattern_entry(repaired: str, normalized: str) -> SubtopicTaxonomyEntry | None:
    stripped = normalized.strip()
    if re.fullmatch(r"\\[A-Z]+(?:\^\d+)?", stripped):
        return _taxonomy_entry(
            "",
            "Data-quality / invalid tag",
            repaired,
            normalization=(NORMALIZATION_STATUS_CORRUPT, NORMALIZATION_CONFIDENCE_HIGH),
        )
    return None


def _pattern_rule_matches(
    rule: TaxonomyPatternRule,
    *,
    normalized: str,
    words: set[str],
    padded_text: str,
) -> bool:
    return (
        any(token in normalized for token in rule.tokens)
        or any(word in words for word in rule.words)
        or any(token in padded_text for token in rule.padded_tokens)
    )


def _entry_from_pattern_rules(
    normalized: str,
    words: set[str],
    rules: tuple[TaxonomyPatternRule, ...],
    *,
    normalization: tuple[str, str] = (NORMALIZATION_STATUS_ALIAS, NORMALIZATION_CONFIDENCE_HIGH),
) -> SubtopicTaxonomyEntry | None:
    padded_text = f" {normalized} "
    for rule in rules:
        if not _pattern_rule_matches(rule, normalized=normalized, words=words, padded_text=padded_text):
            continue
        return _taxonomy_entry(
            rule.main_topic,
            rule.canonical_subtopic,
            normalized,
            stored_technique=rule.stored_technique,
            normalization=normalization,
        )
    return None


def _pattern_taxonomy_entry(technique: str) -> SubtopicTaxonomyEntry | None:
    repaired = repair_topic_tag_text(technique)
    normalized = normalize_topic_tag(repaired)
    key = _taxonomy_key(repaired)
    if not key:
        return None

    corrupt_entry = _corrupt_pattern_entry(repaired, normalized)
    if corrupt_entry is not None:
        return corrupt_entry

    invalid_entry = _invalid_pattern_entry(repaired, normalized, key)
    if invalid_entry is not None:
        return invalid_entry

    words = set(re.findall(r"[A-Z0-9]+", normalized))
    return _entry_from_pattern_rules(
        normalized,
        words,
        EXCEPTION_PATTERN_RULES,
    ) or _entry_from_pattern_rules(normalized, words, GENERIC_PATTERN_RULES)


def _normalized_domain_set(domains: list[str] | tuple[str, ...] | None) -> set[str]:
    return {normalize_topic_tag(domain) for domain in (domains or []) if normalize_topic_tag(domain)}


def _domains_include_number_theory(domains: list[str] | tuple[str, ...] | None) -> bool:
    return bool(_normalized_domain_set(domains) & NUMBER_THEORY_DOMAIN_ALIASES)


def _is_strong_number_theory_technique(technique: str) -> bool:
    repaired = repair_topic_tag_text(technique)
    normalized = normalize_topic_tag(repaired)
    if _taxonomy_key(repaired) in NUMBER_THEORY_AMBIGUOUS_KEYS:
        return False
    return any(token in normalized for token in NUMBER_THEORY_STRONG_TOKENS)


def _number_theory_pattern_taxonomy_entry(technique: str) -> SubtopicTaxonomyEntry | None:
    repaired = repair_topic_tag_text(technique)
    normalized = normalize_topic_tag(repaired)
    if not _taxonomy_key(repaired):
        return None
    words = set(re.findall(r"[A-Z0-9]+", normalized))
    return _entry_from_pattern_rules(
        normalized,
        words,
        NUMBER_THEORY_METHOD_PATTERN_RULES,
        normalization=(NORMALIZATION_STATUS_METHOD, NORMALIZATION_CONFIDENCE_HIGH),
    ) or _entry_from_pattern_rules(normalized, words, NUMBER_THEORY_PATTERN_RULES)


def taxonomy_entry_for_technique(
    technique: str,
    domains: list[str] | tuple[str, ...] | None = None,
) -> SubtopicTaxonomyEntry | None:
    key = _taxonomy_key(technique)
    domains_include_nt = _domains_include_number_theory(domains)
    nt_entry = NUMBER_THEORY_LOOKUP.get(key)
    strong_number_theory_without_domains = not domains and _is_strong_number_theory_technique(technique)
    selected_entry: SubtopicTaxonomyEntry | None = None

    if nt_entry is not None and (
        domains_include_nt
        or strong_number_theory_without_domains
        or nt_entry.normalization_status in {
        NORMALIZATION_STATUS_METADATA,
        NORMALIZATION_STATUS_CORRUPT,
        }
    ):
        selected_entry = nt_entry

    if selected_entry is None and domains_include_nt:
        nt_pattern_entry = _number_theory_pattern_taxonomy_entry(technique)
        if nt_pattern_entry is not None:
            selected_entry = nt_pattern_entry

    if selected_entry is None:
        selected_entry = TAXONOMY_LOOKUP.get(key) or _pattern_taxonomy_entry(technique)

    if selected_entry is None:
        nt_pattern_entry = _number_theory_pattern_taxonomy_entry(technique)
        if nt_pattern_entry is not None and (domains_include_nt or strong_number_theory_without_domains):
            selected_entry = nt_pattern_entry

    return selected_entry or nt_entry


def classified_topic_tag_fields(
    *,
    technique: str,
    domains: list[str] | None,
    raw_tag: str | None = None,
) -> dict[str, object]:
    repaired_technique = repair_topic_tag_text(technique)
    normalized_technique = normalize_topic_tag(repaired_technique)
    source_raw_tag = raw_tag or technique
    domain_list = domains_dedup_preserve_order(domains or [])
    entry = taxonomy_entry_for_technique(repaired_technique, domains=domain_list)

    if entry is None:
        return {
            "canonical_subtopic": "",
            "domains": domain_list,
            "main_topic": "",
            "normalization_confidence": NORMALIZATION_CONFIDENCE_LOW,
            "normalization_status": NORMALIZATION_STATUS_NEEDS_REVIEW,
            "raw_tag": source_raw_tag,
            "technique": normalized_technique,
        }

    if entry.main_topic:
        domain_list = domains_dedup_preserve_order([entry.main_topic, *domain_list])
    return {
        "canonical_subtopic": entry.canonical_subtopic,
        "domains": domain_list,
        "main_topic": entry.main_topic,
        "normalization_confidence": entry.normalization_confidence,
        "normalization_status": entry.normalization_status,
        "raw_tag": source_raw_tag,
        "technique": entry.stored_technique,
    }


def _tag_domains_with_main_topic(domains: list[str], main_topic: str) -> list[str]:
    return domains_dedup_preserve_order([main_topic, *(domains or [])])


def _problem_parent_label(tag: ProblemTopicTechnique) -> str:
    record = tag.record
    return record.contest_year_problem or f"{record.contest} {record.year} {record.problem}"


def _statement_parent_label(tag: StatementTopicTechnique) -> str:
    statement = tag.statement
    return statement.contest_year_problem or (
        f"{statement.contest_name} {statement.contest_year} {statement.problem_code}"
    )


def _problem_tag_rows() -> Iterable[ProblemTopicTechnique]:
    return (
        ProblemTopicTechnique.objects.select_related("record")
        .only(
            "id",
            "record_id",
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
            "raw_tag",
            "normalization_status",
            "normalization_confidence",
            "record__contest_year_problem",
            "record__contest",
            "record__year",
            "record__problem",
        )
        .order_by("record_id", "id")
        .iterator(chunk_size=1000)
    )


def _statement_tag_rows() -> Iterable[StatementTopicTechnique]:
    return (
        StatementTopicTechnique.objects.select_related("statement")
        .only(
            "id",
            "statement_id",
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
            "raw_tag",
            "normalization_status",
            "normalization_confidence",
            "statement__contest_year_problem",
            "statement__contest_name",
            "statement__contest_year",
            "statement__problem_code",
        )
        .order_by("statement_id", "id")
        .iterator(chunk_size=1000)
    )


def _problem_cleanup_tag_rows() -> Iterable[ProblemTopicTechnique]:
    return (
        ProblemTopicTechnique.objects.only(
            "id",
            "record_id",
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
            "raw_tag",
            "normalization_status",
            "normalization_confidence",
        )
        .order_by("record_id", "id")
        .iterator(chunk_size=SUBTOPIC_CLEANUP_BATCH_SIZE)
    )


def _statement_cleanup_tag_rows() -> Iterable[StatementTopicTechnique]:
    return (
        StatementTopicTechnique.objects.only(
            "id",
            "statement_id",
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
            "raw_tag",
            "normalization_status",
            "normalization_confidence",
        )
        .order_by("statement_id", "id")
        .iterator(chunk_size=SUBTOPIC_CLEANUP_BATCH_SIZE)
    )


def _tag_needs_update(tag, entry: SubtopicTaxonomyEntry) -> bool:
    return (
        tag.technique != entry.stored_technique
        or tag.main_topic != entry.main_topic
        or tag.canonical_subtopic != entry.canonical_subtopic
        or tag.domains != _tag_domains_with_main_topic(tag.domains or [], entry.main_topic)
        or not tag.raw_tag
        or tag.normalization_status != entry.normalization_status
        or tag.normalization_confidence != entry.normalization_confidence
    )


def _preview_change(kind: str, tag, entry: SubtopicTaxonomyEntry, parent_label: str) -> dict[str, str]:
    return {
        "canonical_subtopic": entry.canonical_subtopic,
        "current_main_topic": tag.main_topic,
        "current_subtopic": tag.canonical_subtopic,
        "current_technique": tag.technique,
        "kind": kind,
        "main_topic": entry.main_topic,
        "normalization_confidence": entry.normalization_confidence,
        "normalization_status": entry.normalization_status,
        "parent_label": parent_label,
        "raw_tag": tag.raw_tag or tag.technique,
        "technique": entry.stored_technique,
    }


def _record_unmatched_subtopic(
    unmatched_by_key: OrderedDict[str, dict[str, object]],
    *,
    parent_label: str,
    source: str,
    tag,
) -> None:
    key = _taxonomy_key(tag.technique)
    if not key:
        return

    row = unmatched_by_key.setdefault(
        key,
        {
            "_domains": [],
            "example_problem": parent_label,
            "occurrences": 0,
            "problem_rows": 0,
            "statement_rows": 0,
            "subtopic": normalize_topic_tag(tag.technique),
        },
    )
    row["occurrences"] = int(row["occurrences"]) + 1
    if source == "problem":
        row["problem_rows"] = int(row["problem_rows"]) + 1
    else:
        row["statement_rows"] = int(row["statement_rows"]) + 1
    row["_domains"] = domains_dedup_preserve_order([
        *list(row["_domains"]),
        *(tag.domains or []),
    ])


def _format_unmatched_subtopic_rows(
    unmatched_by_key: OrderedDict[str, dict[str, object]],
) -> list[dict[str, object]]:
    rows = [
        {
            "example_problem": row["example_problem"],
            "existing_domains": ", ".join(row["_domains"]),
            "occurrences": row["occurrences"],
            "problem_rows": row["problem_rows"],
            "statement_rows": row["statement_rows"],
            "subtopic": row["subtopic"],
        }
        for row in unmatched_by_key.values()
    ]
    return sorted(rows, key=lambda row: (-int(row["occurrences"]), str(row["subtopic"]).casefold()))


def build_unmatched_subtopic_review(*, limit: int | None = None) -> dict[str, object]:
    unmatched_by_key: OrderedDict[str, dict[str, object]] = OrderedDict()

    for tag in _problem_tag_rows():
        if taxonomy_entry_for_technique(tag.technique, domains=tag.domains) is None:
            _record_unmatched_subtopic(
                unmatched_by_key,
                parent_label=_problem_parent_label(tag),
                source="problem",
                tag=tag,
            )

    for tag in _statement_tag_rows():
        if taxonomy_entry_for_technique(tag.technique, domains=tag.domains) is None:
            _record_unmatched_subtopic(
                unmatched_by_key,
                parent_label=_statement_parent_label(tag),
                source="statement",
                tag=tag,
            )

    rows = _format_unmatched_subtopic_rows(unmatched_by_key)
    return {
        "row_count": len(rows),
        "rows": rows[:limit] if limit is not None else rows,
        "truncated": limit is not None and len(rows) > limit,
    }


def build_subtopic_cleanup_preview(*, limit: int = 50) -> dict[str, object]:
    changes: list[dict[str, str]] = []
    change_count = 0
    unmatched_by_key: OrderedDict[str, dict[str, object]] = OrderedDict()
    raw_parent_keys: set[tuple[str, int]] = set()
    duplicate_count = 0
    duplicate_groups: defaultdict[tuple[str, int, str], int] = defaultdict(int)
    invalid_count = 0

    tag_sources = (
        ("Problem row", _problem_tag_rows(), lambda tag: tag.record_id, _problem_parent_label),
        ("Statement row", _statement_tag_rows(), lambda tag: tag.statement_id, _statement_parent_label),
    )
    for kind, tag_rows, parent_id_getter, parent_label_getter in tag_sources:
        parent_key_kind = "problem" if kind == "Problem row" else "statement"
        for tag in tag_rows:
            entry = taxonomy_entry_for_technique(tag.technique, domains=tag.domains)
            if entry is None:
                _record_unmatched_subtopic(
                    unmatched_by_key,
                    parent_label=parent_label_getter(tag),
                    source=parent_key_kind,
                    tag=tag,
                )
                continue
            parent_id = parent_id_getter(tag)
            raw_parent_keys.add((parent_key_kind, parent_id))
            duplicate_groups[(parent_key_kind, parent_id, entry.stored_technique)] += 1
            if entry.normalization_status in {
                NORMALIZATION_STATUS_CORRUPT,
                NORMALIZATION_STATUS_INVALID,
            }:
                invalid_count += 1
            if _tag_needs_update(tag, entry):
                change_count += 1
                if len(changes) < limit:
                    changes.append(_preview_change(kind, tag, entry, parent_label_getter(tag)))

    for group_size in duplicate_groups.values():
        if group_size > 1:
            duplicate_count += group_size - 1

    unmatched_review = _format_unmatched_subtopic_rows(unmatched_by_key)
    unmatched = [
        {"technique": str(row["subtopic"])}
        for row in unmatched_review
    ]
    return {
        "change_count": change_count,
        "changes": changes,
        "changes_truncated": change_count > limit,
        "duplicate_count": duplicate_count,
        "has_changes": bool(change_count or duplicate_count or raw_parent_keys),
        "invalid_count": invalid_count,
        "raw_update_count": len(raw_parent_keys),
        "unmatched": unmatched[:limit],
        "unmatched_count": len(unmatched),
        "unmatched_review": unmatched_review[:limit],
        "unmatched_review_count": len(unmatched_review),
        "unmatched_review_truncated": len(unmatched_review) > limit,
        "unmatched_truncated": len(unmatched) > limit,
    }


def _select_keeper(rows: list, target_technique: str):
    for row in rows:
        if row.technique == target_technique:
            return row
    return rows[0]


def _merge_tag_raw_values(rows: list) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for row in rows:
        raw_value = (row.raw_tag or row.technique or "").strip()
        key = raw_value.casefold()
        if raw_value and key not in seen:
            seen.add(key)
            merged.append(raw_value)
    return "; ".join(merged)[:512]


def _prepare_parent_group_update(rows: list, entry: SubtopicTaxonomyEntry) -> tuple[object | None, list[int]]:
    keeper = _select_keeper(rows, entry.stored_technique)
    merged_domains = [entry.main_topic]
    for row in rows:
        merged_domains.extend(row.domains or [])
    merged_domains = domains_dedup_preserve_order(merged_domains)
    merged_raw_tag = _merge_tag_raw_values(rows)

    changed = (
        keeper.technique != entry.stored_technique
        or keeper.main_topic != entry.main_topic
        or keeper.canonical_subtopic != entry.canonical_subtopic
        or keeper.domains != merged_domains
        or keeper.raw_tag != merged_raw_tag
        or keeper.normalization_status != entry.normalization_status
        or keeper.normalization_confidence != entry.normalization_confidence
    )
    if changed:
        keeper.technique = entry.stored_technique
        keeper.main_topic = entry.main_topic
        keeper.canonical_subtopic = entry.canonical_subtopic
        keeper.domains = merged_domains
        keeper.raw_tag = merged_raw_tag
        keeper.normalization_status = entry.normalization_status
        keeper.normalization_confidence = entry.normalization_confidence

    duplicate_ids = [row.id for row in rows if row.id != keeper.id]
    return (keeper if changed else None), duplicate_ids


def _apply_parent_group(rows: list, entry: SubtopicTaxonomyEntry) -> tuple[int, int]:
    updated_row, duplicate_ids = _prepare_parent_group_update(rows, entry)
    if duplicate_ids:
        rows[0].__class__.objects.filter(id__in=duplicate_ids).delete()
    if updated_row is not None:
        updated_row.__class__.objects.bulk_update(
            [updated_row],
            TAG_NORMALIZATION_UPDATE_FIELDS,
            batch_size=SUBTOPIC_CLEANUP_BATCH_SIZE,
        )
    return (1 if updated_row is not None else 0), len(duplicate_ids)


def _include_existing_target_row(existing_target, target_technique: str, rows: list) -> list:
    if any(row.technique == target_technique for row in rows):
        return rows
    if existing_target is None:
        return rows
    return [existing_target, *rows]


def _chunked_ids(ids: Iterable[int]) -> Iterable[list[int]]:
    sorted_ids = sorted(ids)
    for index in range(0, len(sorted_ids), SUBTOPIC_CLEANUP_BATCH_SIZE):
        yield sorted_ids[index:index + SUBTOPIC_CLEANUP_BATCH_SIZE]


def _chunked_rows(rows: list) -> Iterable[list]:
    for index in range(0, len(rows), SUBTOPIC_CLEANUP_BATCH_SIZE):
        yield rows[index:index + SUBTOPIC_CLEANUP_BATCH_SIZE]


def _quoted_table_name(model) -> str:
    return connection.ops.quote_name(model._meta.db_table)  # noqa: SLF001


def _bulk_update_tag_rows_with_postgres_values(model, rows: list) -> None:
    table_name = _quoted_table_name(model)
    with connection.cursor() as cursor:
        for row_batch in _chunked_rows(rows):
            placeholders = []
            params = []
            for row in row_batch:
                placeholders.append("(%s, %s, %s, %s, %s::jsonb, %s, %s, %s)")
                params.extend([
                    row.id,
                    row.technique,
                    row.main_topic,
                    row.canonical_subtopic,
                    json.dumps(row.domains or []),
                    row.raw_tag,
                    row.normalization_status,
                    row.normalization_confidence,
                ])
            query = f"""
            UPDATE {table_name} AS target
            SET
                technique = data.technique,
                main_topic = data.main_topic,
                canonical_subtopic = data.canonical_subtopic,
                domains = data.domains,
                raw_tag = data.raw_tag,
                normalization_status = data.normalization_status,
                normalization_confidence = data.normalization_confidence
            FROM (VALUES {", ".join(placeholders)}) AS data(
                id,
                technique,
                main_topic,
                canonical_subtopic,
                domains,
                raw_tag,
                normalization_status,
                normalization_confidence
            )
            WHERE target.id = data.id
            """
            cursor.execute(query, params)


def _bulk_update_tag_rows(model, rows: list) -> None:
    if not rows:
        return
    if connection.vendor == "postgresql":
        _bulk_update_tag_rows_with_postgres_values(model, rows)
        return
    model.objects.bulk_update(
        rows,
        TAG_NORMALIZATION_UPDATE_FIELDS,
        batch_size=SUBTOPIC_CLEANUP_BATCH_SIZE,
    )


def _bulk_delete_tag_ids(model, ids: list[int]) -> None:
    if not ids:
        return
    for id_batch in _chunked_ids(ids):
        model.objects.filter(id__in=id_batch).delete()


def _format_tag_value(tag, field_name: str):
    if isinstance(tag, dict):
        return tag.get(field_name)
    return getattr(tag, field_name)


def _format_raw_topic_tags(tag_rows: Iterable) -> str:
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for tag in tag_rows:
        main_topic = _format_tag_value(tag, "main_topic")
        canonical_subtopic = _format_tag_value(tag, "canonical_subtopic")
        domains = _format_tag_value(tag, "domains") or []
        technique = _format_tag_value(tag, "technique")
        prefix = f"{main_topic} / {canonical_subtopic}" if main_topic and canonical_subtopic else "/".join(domains)
        grouped.setdefault(prefix, []).append(technique)

    segments = []
    for prefix, techniques in grouped.items():
        technique_label = ", ".join(techniques)
        if prefix:
            segments.append(f"{prefix} - {technique_label}")
        else:
            segments.append(technique_label)
    return f"Topic tags: {'; '.join(segments)}" if segments else ""


def _formatted_topic_tags_by_parent_batch(
    *,
    parent_field_name: str,
    parent_ids: list[int],
    tag_model,
) -> dict[int, str]:
    parent_id_field = f"{parent_field_name}_id"
    grouped_rows: dict[int, list[dict[str, object]]] = {
        parent_id: []
        for parent_id in parent_ids
    }
    tag_rows = (
        tag_model.objects.filter(**{f"{parent_id_field}__in": parent_ids})
        .values(
            parent_id_field,
            "technique",
            "domains",
            "main_topic",
            "canonical_subtopic",
        )
        .order_by(parent_id_field, "id")
        .iterator(chunk_size=SUBTOPIC_CLEANUP_BATCH_SIZE)
    )
    for tag in tag_rows:
        grouped_rows.setdefault(tag[parent_id_field], []).append(tag)
    return {
        parent_id: _format_raw_topic_tags(grouped_rows.get(parent_id, []))
        for parent_id in parent_ids
    }


def _bulk_update_topic_tag_parent_rows_with_postgres_values(
    parent_model,
    rows: list,
    *,
    timestamp_field_name: str | None = None,
) -> None:
    table_name = _quoted_table_name(parent_model)
    timestamp_column = connection.ops.quote_name(timestamp_field_name) if timestamp_field_name else ""
    with connection.cursor() as cursor:
        for row_batch in _chunked_rows(rows):
            placeholders = []
            params = []
            for row in row_batch:
                if timestamp_field_name:
                    placeholders.append("(%s, %s, %s)")
                    params.extend([row.id, row.topic_tags, getattr(row, timestamp_field_name)])
                else:
                    placeholders.append("(%s, %s)")
                    params.extend([row.id, row.topic_tags])

            if timestamp_field_name:
                query = f"""
                UPDATE {table_name} AS target
                SET
                    topic_tags = data.topic_tags,
                    {timestamp_column} = data.updated_at
                FROM (VALUES {", ".join(placeholders)}) AS data(id, topic_tags, updated_at)
                WHERE target.id = data.id
                """
                cursor.execute(query, params)
            else:
                query = f"""
                UPDATE {table_name} AS target
                SET topic_tags = data.topic_tags
                FROM (VALUES {", ".join(placeholders)}) AS data(id, topic_tags)
                WHERE target.id = data.id
                """
                cursor.execute(query, params)


def _bulk_update_topic_tag_parent_rows(
    parent_model,
    rows: list,
    *,
    timestamp_field_name: str | None = None,
) -> None:
    if not rows:
        return
    if connection.vendor == "postgresql":
        _bulk_update_topic_tag_parent_rows_with_postgres_values(
            parent_model,
            rows,
            timestamp_field_name=timestamp_field_name,
        )
        return

    update_fields = ["topic_tags"]
    if timestamp_field_name:
        update_fields.append(timestamp_field_name)
    parent_model.objects.bulk_update(
        rows,
        update_fields,
        batch_size=SUBTOPIC_CLEANUP_BATCH_SIZE,
    )


def _bulk_rewrite_topic_tags(
    *,
    parent_ids: set[int],
    parent_model,
    tag_model,
    parent_field_name: str,
    timestamp_field_name: str | None = None,
) -> int:
    updated_count = 0
    pending_updates = []

    for parent_id_batch in _chunked_ids(parent_ids):
        current_values = {
            row["id"]: row["topic_tags"]
            for row in parent_model.objects.filter(id__in=parent_id_batch).values("id", "topic_tags")
        }
        next_values = _formatted_topic_tags_by_parent_batch(
            parent_field_name=parent_field_name,
            parent_ids=parent_id_batch,
            tag_model=tag_model,
        )
        updated_at = timezone.now()
        for parent_id in parent_id_batch:
            next_value = next_values.get(parent_id, "")
            if current_values.get(parent_id) == next_value:
                continue
            parent = parent_model(id=parent_id, topic_tags=next_value)
            if timestamp_field_name:
                setattr(parent, timestamp_field_name, updated_at)
            pending_updates.append(parent)
            updated_count += 1

        if len(pending_updates) >= SUBTOPIC_CLEANUP_BATCH_SIZE:
            _bulk_update_topic_tag_parent_rows(
                parent_model,
                pending_updates,
                timestamp_field_name=timestamp_field_name,
            )
            pending_updates = []

    if pending_updates:
        _bulk_update_topic_tag_parent_rows(
            parent_model,
            pending_updates,
            timestamp_field_name=timestamp_field_name,
        )
    return updated_count


def _rewrite_problem_topic_tags(record_id: int) -> bool:
    record = ProblemSolveRecord.objects.values("topic_tags").get(id=record_id)
    tag_rows = (
        ProblemTopicTechnique.objects.filter(record_id=record_id)
        .values("technique", "domains", "main_topic", "canonical_subtopic")
        .order_by("id")
    )
    next_value = _format_raw_topic_tags(tag_rows)
    if record["topic_tags"] == next_value:
        return False
    ProblemSolveRecord.objects.filter(id=record_id).update(topic_tags=next_value)
    return True


def _rewrite_statement_topic_tags(statement_id: int) -> bool:
    statement = ContestProblemStatement.objects.values("topic_tags").get(id=statement_id)
    tag_rows = (
        StatementTopicTechnique.objects.filter(statement_id=statement_id)
        .values("technique", "domains", "main_topic", "canonical_subtopic")
        .order_by("id")
    )
    next_value = _format_raw_topic_tags(tag_rows)
    if statement["topic_tags"] == next_value:
        return False
    ContestProblemStatement.objects.filter(id=statement_id).update(
        topic_tags=next_value,
        updated_at=timezone.now(),
    )
    return True


def _apply_problem_tag_cleanup() -> SubtopicCleanupApplyResult:
    updated_rows: list[ProblemTopicTechnique] = []
    duplicate_ids: list[int] = []
    touched_record_ids: set[int] = set()
    grouped_rows: dict[tuple[int, str], tuple[SubtopicTaxonomyEntry, list[ProblemTopicTechnique]]] = {}
    rows_by_technique: dict[tuple[int, str], ProblemTopicTechnique] = {}

    for tag in _problem_cleanup_tag_rows():
        rows_by_technique[(tag.record_id, tag.technique)] = tag
        entry = taxonomy_entry_for_technique(tag.technique, domains=tag.domains)
        if entry is None:
            continue
        key = (tag.record_id, entry.stored_technique)
        rows = grouped_rows.setdefault(key, (entry, []))[1]
        rows.append(tag)
        touched_record_ids.add(tag.record_id)

    for (record_id, target_technique), (entry, rows) in grouped_rows.items():
        merged_rows = _include_existing_target_row(
            rows_by_technique.get((record_id, target_technique)),
            target_technique,
            rows,
        )
        updated_row, row_duplicate_ids = _prepare_parent_group_update(merged_rows, entry)
        if updated_row is not None:
            updated_rows.append(updated_row)
        duplicate_ids.extend(row_duplicate_ids)

    _bulk_delete_tag_ids(ProblemTopicTechnique, duplicate_ids)
    _bulk_update_tag_rows(ProblemTopicTechnique, updated_rows)
    raw_update_count = _bulk_rewrite_topic_tags(
        parent_ids=touched_record_ids,
        parent_model=ProblemSolveRecord,
        tag_model=ProblemTopicTechnique,
        parent_field_name="record",
    )
    return SubtopicCleanupApplyResult(
        deleted_count=len(duplicate_ids),
        raw_update_count=raw_update_count,
        updated_count=len(updated_rows),
    )


def _apply_statement_tag_cleanup() -> SubtopicCleanupApplyResult:
    updated_rows: list[StatementTopicTechnique] = []
    duplicate_ids: list[int] = []
    touched_statement_ids: set[int] = set()
    grouped_rows: dict[tuple[int, str], tuple[SubtopicTaxonomyEntry, list[StatementTopicTechnique]]] = {}
    rows_by_technique: dict[tuple[int, str], StatementTopicTechnique] = {}

    for tag in _statement_cleanup_tag_rows():
        rows_by_technique[(tag.statement_id, tag.technique)] = tag
        entry = taxonomy_entry_for_technique(tag.technique, domains=tag.domains)
        if entry is None:
            continue
        key = (tag.statement_id, entry.stored_technique)
        rows = grouped_rows.setdefault(key, (entry, []))[1]
        rows.append(tag)
        touched_statement_ids.add(tag.statement_id)

    for (statement_id, target_technique), (entry, rows) in grouped_rows.items():
        merged_rows = _include_existing_target_row(
            rows_by_technique.get((statement_id, target_technique)),
            target_technique,
            rows,
        )
        updated_row, row_duplicate_ids = _prepare_parent_group_update(merged_rows, entry)
        if updated_row is not None:
            updated_rows.append(updated_row)
        duplicate_ids.extend(row_duplicate_ids)

    _bulk_delete_tag_ids(StatementTopicTechnique, duplicate_ids)
    _bulk_update_tag_rows(StatementTopicTechnique, updated_rows)
    raw_update_count = _bulk_rewrite_topic_tags(
        parent_ids=touched_statement_ids,
        parent_model=ContestProblemStatement,
        tag_model=StatementTopicTechnique,
        parent_field_name="statement",
        timestamp_field_name="updated_at",
    )
    return SubtopicCleanupApplyResult(
        deleted_count=len(duplicate_ids),
        raw_update_count=raw_update_count,
        updated_count=len(updated_rows),
    )


@transaction.atomic
def apply_subtopic_cleanup() -> SubtopicCleanupApplyResult:
    problem_result = _apply_problem_tag_cleanup()
    statement_result = _apply_statement_tag_cleanup()
    return SubtopicCleanupApplyResult(
        deleted_count=problem_result.deleted_count + statement_result.deleted_count,
        raw_update_count=problem_result.raw_update_count + statement_result.raw_update_count,
        updated_count=problem_result.updated_count + statement_result.updated_count,
    )
