from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.subtopic_taxonomy import CANONICAL_SUBTOPIC_TAXONOMY
from inspinia.pages.topic_tags_parse import domains_dedup_preserve_order
from inspinia.pages.topic_tags_parse import normalize_topic_tag

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class SubtopicTaxonomyEntry:
    main_topic: str
    canonical_subtopic: str
    technique: str
    stored_technique: str


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
        "Holder",
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
) -> SubtopicTaxonomyEntry:
    return SubtopicTaxonomyEntry(
        main_topic=main_topic,
        canonical_subtopic=canonical_subtopic,
        technique=technique,
        stored_technique=normalize_topic_tag(stored_technique or technique),
    )


def _build_taxonomy_lookup() -> dict[str, SubtopicTaxonomyEntry]:
    lookup: dict[str, SubtopicTaxonomyEntry] = {}
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
    for main_topic, canonical_subtopic, alias in PARENT_COLLAPSE_SUBTOPIC_ALIASES:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            main_topic,
            canonical_subtopic,
            alias,
            stored_technique=canonical_subtopic,
        )
    for main_topic, canonical_subtopic, alias, stored_technique in STORED_TECHNIQUE_SUBTOPIC_ALIASES:
        lookup[_taxonomy_key(alias)] = _taxonomy_entry(
            main_topic,
            canonical_subtopic,
            alias,
            stored_technique=stored_technique,
        )
    for main_topic, canonical_subtopic, alias in ADDITIONAL_SUBTOPIC_ALIASES:
        lookup.setdefault(
            _taxonomy_key(alias),
            _taxonomy_entry(main_topic, canonical_subtopic, alias),
        )
    return lookup


TAXONOMY_LOOKUP = _build_taxonomy_lookup()


def taxonomy_entry_for_technique(technique: str) -> SubtopicTaxonomyEntry | None:
    return TAXONOMY_LOOKUP.get(_taxonomy_key(technique))


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
            "statement__contest_year_problem",
            "statement__contest_name",
            "statement__contest_year",
            "statement__problem_code",
        )
        .order_by("statement_id", "id")
        .iterator(chunk_size=1000)
    )


def _tag_needs_update(tag, entry: SubtopicTaxonomyEntry) -> bool:
    return (
        tag.technique != entry.stored_technique
        or tag.main_topic != entry.main_topic
        or tag.canonical_subtopic != entry.canonical_subtopic
        or tag.domains != _tag_domains_with_main_topic(tag.domains or [], entry.main_topic)
    )


def _preview_change(kind: str, tag, entry: SubtopicTaxonomyEntry, parent_label: str) -> dict[str, str]:
    return {
        "canonical_subtopic": entry.canonical_subtopic,
        "current_main_topic": tag.main_topic,
        "current_subtopic": tag.canonical_subtopic,
        "current_technique": tag.technique,
        "kind": kind,
        "main_topic": entry.main_topic,
        "parent_label": parent_label,
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
        if taxonomy_entry_for_technique(tag.technique) is None:
            _record_unmatched_subtopic(
                unmatched_by_key,
                parent_label=_problem_parent_label(tag),
                source="problem",
                tag=tag,
            )

    for tag in _statement_tag_rows():
        if taxonomy_entry_for_technique(tag.technique) is None:
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

    tag_sources = (
        ("Problem row", _problem_tag_rows(), lambda tag: tag.record_id, _problem_parent_label),
        ("Statement row", _statement_tag_rows(), lambda tag: tag.statement_id, _statement_parent_label),
    )
    for kind, tag_rows, parent_id_getter, parent_label_getter in tag_sources:
        parent_key_kind = "problem" if kind == "Problem row" else "statement"
        for tag in tag_rows:
            entry = taxonomy_entry_for_technique(tag.technique)
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


def _apply_parent_group(rows: list, entry: SubtopicTaxonomyEntry) -> tuple[int, int]:
    keeper = _select_keeper(rows, entry.stored_technique)
    merged_domains = [entry.main_topic]
    for row in rows:
        merged_domains.extend(row.domains or [])
    merged_domains = domains_dedup_preserve_order(merged_domains)

    changed = (
        keeper.technique != entry.stored_technique
        or keeper.main_topic != entry.main_topic
        or keeper.canonical_subtopic != entry.canonical_subtopic
        or keeper.domains != merged_domains
    )
    if changed:
        keeper.technique = entry.stored_technique
        keeper.main_topic = entry.main_topic
        keeper.canonical_subtopic = entry.canonical_subtopic
        keeper.domains = merged_domains
        keeper.save(update_fields=["technique", "main_topic", "canonical_subtopic", "domains"])

    duplicate_ids = [row.id for row in rows if row.id != keeper.id]
    if duplicate_ids:
        rows[0].__class__.objects.filter(id__in=duplicate_ids).delete()

    return (1 if changed else 0), len(duplicate_ids)


def _include_existing_target_row(existing_target, target_technique: str, rows: list) -> list:
    if any(row.technique == target_technique for row in rows):
        return rows
    if existing_target is None:
        return rows
    return [existing_target, *rows]


def _format_raw_topic_tags(tag_rows: Iterable) -> str:
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for tag in tag_rows:
        if tag.main_topic and tag.canonical_subtopic:
            prefix = f"{tag.main_topic} / {tag.canonical_subtopic}"
        else:
            prefix = "/".join(tag.domains or [])
        grouped.setdefault(prefix, []).append(tag.technique)

    segments = []
    for prefix, techniques in grouped.items():
        technique_label = ", ".join(techniques)
        if prefix:
            segments.append(f"{prefix} - {technique_label}")
        else:
            segments.append(technique_label)
    return f"Topic tags: {'; '.join(segments)}" if segments else ""


def _rewrite_problem_topic_tags(record_id: int) -> bool:
    record = ProblemSolveRecord.objects.values("topic_tags").get(id=record_id)
    tag_rows = (
        ProblemTopicTechnique.objects.filter(record_id=record_id)
        .only("id", "technique", "domains", "main_topic", "canonical_subtopic")
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
        .only("id", "technique", "domains", "main_topic", "canonical_subtopic")
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
    updated_count = 0
    deleted_count = 0
    touched_record_ids: set[int] = set()
    grouped_rows: dict[tuple[int, str], tuple[SubtopicTaxonomyEntry, list[ProblemTopicTechnique]]] = {}
    rows_by_technique: dict[tuple[int, str], ProblemTopicTechnique] = {}

    for tag in _problem_tag_rows():
        rows_by_technique[(tag.record_id, tag.technique)] = tag
        entry = taxonomy_entry_for_technique(tag.technique)
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
        updated, deleted = _apply_parent_group(merged_rows, entry)
        updated_count += updated
        deleted_count += deleted

    raw_update_count = sum(
        1
        for record_id in touched_record_ids
        if _rewrite_problem_topic_tags(record_id)
    )
    return SubtopicCleanupApplyResult(
        deleted_count=deleted_count,
        raw_update_count=raw_update_count,
        updated_count=updated_count,
    )


def _apply_statement_tag_cleanup() -> SubtopicCleanupApplyResult:
    updated_count = 0
    deleted_count = 0
    touched_statement_ids: set[int] = set()
    grouped_rows: dict[tuple[int, str], tuple[SubtopicTaxonomyEntry, list[StatementTopicTechnique]]] = {}
    rows_by_technique: dict[tuple[int, str], StatementTopicTechnique] = {}

    for tag in _statement_tag_rows():
        rows_by_technique[(tag.statement_id, tag.technique)] = tag
        entry = taxonomy_entry_for_technique(tag.technique)
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
        updated, deleted = _apply_parent_group(merged_rows, entry)
        updated_count += updated
        deleted_count += deleted

    raw_update_count = sum(
        1
        for statement_id in touched_statement_ids
        if _rewrite_statement_topic_tags(statement_id)
    )
    return SubtopicCleanupApplyResult(
        deleted_count=deleted_count,
        raw_update_count=raw_update_count,
        updated_count=updated_count,
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
