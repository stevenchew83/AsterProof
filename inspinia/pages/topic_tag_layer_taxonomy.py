"""Explicit layer mappings for normalized olympiad topic tags."""

# The attached import maps are embedded as raw TSV data; long mojibake rows are expected.
# ruff: noqa: E501, RUF001

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from inspinia.pages.topic_tags_parse import repair_topic_tag_text


@dataclass(frozen=True)
class LayeredTopicTagMapping:
    domains: tuple[str, ...]
    canonical_subtopic: str
    stored_technique: str
    aliases: tuple[str, ...]
    object_tags: tuple[str, ...] = ()
    technique_tags: tuple[str, ...] = ()
    lemma_theorem_tags: tuple[str, ...] = ()
    proof_roles: tuple[str, ...] = ()
    normalization_status: str = "alias"
    normalization_confidence: str = "high"
    main_topic: str = ""
    preserve_source_domains: bool = True


def _mapping(  # noqa: PLR0913
    domains: tuple[str, ...],
    canonical_subtopic: str,
    stored_technique: str,
    aliases: tuple[str, ...],
    *,
    object_tags: tuple[str, ...] = (),
    technique_tags: tuple[str, ...] = (),
    lemma_theorem_tags: tuple[str, ...] = (),
    proof_roles: tuple[str, ...] = (),
    status: str = "alias",
    main_topic: str = "",
    preserve_source_domains: bool = True,
) -> LayeredTopicTagMapping:
    return LayeredTopicTagMapping(
        aliases=aliases,
        canonical_subtopic=canonical_subtopic,
        domains=domains,
        lemma_theorem_tags=lemma_theorem_tags,
        main_topic=main_topic,
        normalization_status=status,
        object_tags=object_tags,
        preserve_source_domains=preserve_source_domains,
        proof_roles=proof_roles,
        stored_technique=stored_technique,
        technique_tags=technique_tags,
    )


DOMAIN_CODE_BY_TABLE_LABEL = {
    "Algebra": "ALG",
    "Combinatorics": "COMB",
    "Geometry": "GEO",
    "Number Theory": "NT",
}
TABLE_FIELD_COUNT = 7

CANONICAL_SUBTOPIC_REPLACEMENTS = {
    "Additive and multiplicative number theory": "Additive number theory and zero-sum methods",
    "Algorithms, automata, words, and constructive combinatorics": (
        "Algorithms, automata, words, and constructive methods"
    ),
    "Design theory, Latin squares, and finite structures": "Design theory and finite configurations",
    "Divisibility, gcd, lcm, and primes": "Divisibility, gcd, lcm, and factorization",
    "Games, strategies, and processes": "Games, strategies, and adversarial methods",
    "Loci and constructions": "Locus and continuity geometry",
    "Projective and advanced geometry": "Projective and affine geometry",
    "Set systems, posets, and extremal set theory": "Set systems, posets, and order theory",
    "Special configurations and special angles": "Core Euclidean geometry",
    "Triangle centers and triangle configurations": "Triangle centers and configurations",
}

PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS = {
    **CANONICAL_SUBTOPIC_REPLACEMENTS,
    "Additive and arithmetic structures": "Additive and arithmetic combinatorics",
    "Additive combinatorics": "Additive and arithmetic combinatorics",
    "Additive/combinatorial algebra": "Combinatorial algebra and counting",
    "Additive/combinatorial number theory": "Additive number theory and zero-sum methods",
    "Algebraic combinatorics and linear algebra": "Algebraic and linear methods in combinatorics",
    "Algebraic geometry/flavored algebra": "Geometry-flavored algebra",
    "Algebraic graph/degree methods": "Graph theory",
    "Algebraic manipulation": "Polynomials and algebraic manipulation",
    "Algebraic number theory and modular structures": "Algebraic number theory flavor",
    "Algebraic/combinatorial dynamics": "Processes, dynamics, potential, and reconfiguration",
    "Algebraic/combinatorial structure": "Combinatorial algebra and counting",
    "Algorithms and optimization": "Algorithms, automata, words, and constructive methods",
    "Arrangements and incidence geometry": "Combinatorial and discrete geometry",
    "Arrangements and order methods": "Set systems, posets, and order theory",
    "Averaging and subset methods": "Extremal combinatorics and Ramsey theory",
    "Base, digit, and automata number theory": "Base, digit, and carry methods",
    "Calculus and real-variable methods": "Analytic estimates and asymptotics",
    "Casework and construction": "Extremal methods, monotonicity, and invariants",
    "Casework and modular arithmetic": "Congruences and modular arithmetic",
    "Casework and piecewise methods": "Equations, substitutions, and transformations",
    "Coding and metric geometry": "Probability, entropy, coding, and information methods",
    "Combinatorial games and strategies": "Games, strategies, and adversarial methods",
    "Combinatorial structures and constructive methods": "Algorithms, automata, words, and constructive methods",
    "Convexity, Helly, and intersection methods": "Set systems, posets, and order theory",
    "Corrupted import / needs review": "Data-quality / invalid tag",
    "Covering and hitting": "Discrete optimization, matching, covering, packing, and flows",
    "Cyclic order and partial sums": "Set systems, posets, and order theory",
    "Density and approximation": "Analytic estimates and asymptotics",
    "Diophantine equations": "Diophantine equations and descent",
    "Divisibility and exponential structure": "Divisibility, gcd, lcm, and factorization",
    "Divisibility and factorization": "Divisibility, gcd, lcm, and factorization",
    "Dynamical number theory": "Sequences, recurrences, and finite dynamics",
    "Equations and inequalities": "Equations, substitutions, and transformations",
    "Equations and specialization": "Equations, substitutions, and transformations",
    "Equations and systems": "Equations, substitutions, and transformations",
    "Equations and transformations": "Equations, substitutions, and transformations",
    "Extremal and avoidance methods": "Extremal combinatorics and Ramsey theory",
    "Extremal and geometric combinatorics": "Combinatorial and discrete geometry",
    "Extremal and infinitude methods": "Extremal methods, monotonicity, and invariants",
    "Extremal and saturation methods": "Extremal combinatorics and Ramsey theory",
    "Figurate numbers": "Quadratic forms and sums of squares",
    "Fractions and Diophantine approximation": "Floor, rounding, Beatty, Farey, and approximation methods",
    "Fractions and Diophantine methods": "Diophantine equations and descent",
    "Functions and inequalities": "Inequalities and optimization",
    "Functions and maps": "Functional equations",
    "Games, strategies, and information": "Games, strategies, and adversarial methods",
    "Geometric combinatorics": "Combinatorial and discrete geometry",
    "Graph theory and walks": "Graph theory",
    "Greedy algorithms and constructive combinatorics": "Algorithms, automata, words, and constructive methods",
    "Identities and quadratic methods": "Polynomials and algebraic manipulation",
    "Incidence combinatorics": "Combinatorial and discrete geometry",
    "Induction, recursion, and compression": "Extremal methods, monotonicity, and invariants",
    "Inequalities and convexity": "Inequalities and optimization",
    "Inequalities and estimates": "Inequalities and optimization",
    "Inequalities and estimates in number theory": "Sieve, density, and asymptotic estimates",
    "Infinite sets and density": "Set systems, posets, and order theory",
    "Integer optimization and lattice methods": "Lattice and integer geometry methods",
    "Intervals and order methods": "Discrete functions, floors, rounding, and base representation",
    "Inversive geometry": "Transformational geometry",
    "Linear algebra": "Algebraic structures and linear algebra",
    "Linear methods": "Algebraic structures and linear algebra",
    "Local-to-global methods": "Processes, dynamics, potential, and reconfiguration",
    "Logical conditions in geometry": "Core Euclidean geometry",
    "Matching, transversals, and covering": "Discrete optimization, matching, covering, packing, and flows",
    "Matrix and array methods": "Algebraic and linear methods in combinatorics",
    "Metric and difference methods": "Geometric inequalities and optimization",
    "Metric and distance methods": "Geometric inequalities and optimization",
    "Metric and geometric combinatorics": "Combinatorial and discrete geometry",
    "Metric geometry": "Core Euclidean geometry",
    "Modular and parity methods": "Congruences and modular arithmetic",
    "Modular arithmetic and congruences": "Congruences and modular arithmetic",
    "Modular arithmetic and residues": "Congruences and modular arithmetic",
    "Modular arithmetic and sequences": "Congruences and modular arithmetic",
    "Multiplicative functions and factorization": "Arithmetic functions and divisor structure",
    "Multiplicative identities and counting": "Multiplicative structure and semigroups",
    "Multiplicative number theory": "Multiplicative structure and semigroups",
    "Noncrossing and planar combinatorics": "Planar and topological combinatorics",
    "Number theory structures and methods": "Number-theoretic algebra",
    "Number-theoretic sequences and sums": "Sequences, recurrences, and finite dynamics",
    "Online algorithms and strategies": "Games, strategies, and adversarial methods",
    "Optimization and extremal methods": "Discrete optimization, matching, covering, packing, and flows",
    "Optimization and median methods": "Geometric inequalities and optimization",
    "Order and lattice methods": "Set systems, posets, and order theory",
    "Order and ranking methods": "Set systems, posets, and order theory",
    "Pigeonhole, extremal principle, and averaging": "Extremal combinatorics and Ramsey theory",
    "Planar and geometric combinatorics": "Planar and topological combinatorics",
    "Planar graph theory": "Planar and topological combinatorics",
    "Processes and constructive combinatorics": "Processes, dynamics, potential, and reconfiguration",
    "Processes and invariants": "Processes, dynamics, potential, and reconfiguration",
    "Projective, affine, and transformational geometry": "Projective and affine geometry",
    "Quadratic methods": "Polynomials and algebraic manipulation",
    "Ramsey and coloring methods": "Extremal combinatorics and Ramsey theory",
    "Rationality and obstruction methods": "Number-theoretic algebra",
    "Self-similarity and dynamics": "Sequences, recurrences, and series",
    "Separating systems and coding": "Probability, entropy, coding, and information methods",
    "Sign and parity methods": "Extremal methods, monotonicity, and invariants",
    "Square and parity methods": "Quadratic residues, squares, and squarefree methods",
    "Square and quadratic methods": "Quadratic forms and sums of squares",
    "Statement validation": "Data-quality / invalid tag",
    "Structural decomposition": "Extremal methods, monotonicity, and invariants",
    "Structure and regularity methods": "Extremal methods, monotonicity, and invariants",
    "Structure theorems": "Algebraic structures and linear algebra",
    "Switching and transformation methods": "Equations, substitutions, and transformations",
    "Symmetry methods": "Transformational geometry",
    "Topological/combinatorial methods": "Planar and topological combinatorics",
    "Topological/combinatorial parity": "Planar and topological combinatorics",
    "Transformations and geometric motion": "Transformational geometry",
    "Triangle coordinates and complex methods": "Analytic and coordinate geometry",
    "Tropical/min-plus methods": "Algebraic and linear methods in combinatorics",
    "Width and covering methods": "Discrete optimization, matching, covering, packing, and flows",
}

PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS = {
    "INVERSION AT AAA": "Transformational geometry",
}

PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS = {
    "INVERSION AT AAA": "INVERSION",
}

SECOND_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS = {
    **PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
    "Combinatorial geometry and topology": "Combinatorial and discrete geometry",
    "Diophantine equations": "Diophantine equations and descent",
    "Exponential and Diophantine methods": "Diophantine equations and descent",
    "Extremal combinatorics": "Extremal combinatorics and Ramsey theory",
    "Linear algebraic combinatorics": "Algebraic and linear methods in combinatorics",
}

SECOND_PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS = {
    **PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS,
    "TRIG CEVA/MENELAUS": "Geometry-flavored algebra",
}

SECOND_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS = {
    **PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
    "F2 LINEAR ALGEBRA": "F_2 LINEAR ALGEBRA",
    "F_2 LINEAR ALGEBRA": "F_2 LINEAR ALGEBRA",
    "GF(2) LINEAR ALGEBRA": "F_2 LINEAR ALGEBRA",
}

SECOND_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES = {
    "DEGENERATE PASCAL",
    "F2 LINEAR ALGEBRA",
    "F_2 LINEAR ALGEBRA",
    "GF(2) LINEAR ALGEBRA",
    "GRAPH MATCHING",
    "GRAPH MATCHINGS",
    "FLOORS",
    "FLOOR SUMS",
    "GRID TOPOLOGY",
    "INVARIANT ANGLE",
    "NONCROSSING MATCHING",
    "ORDER THEORY",
    "PASCAL",
    "PASCAL THEOREM",
    "TRIG CEVA/MENELAUS",
}

FOURTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS = {
    **SECOND_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
    "Additive/combinatorial number theory": "Additive number theory and zero-sum methods",
    "Algebraic and analytic number theory": "Algebraic number theory flavor",
    "Combinatorial games and processes": "Games, strategies, and adversarial methods",
    "Conics and projective geometry": "Projective and affine geometry",
    "Continuity and topology methods": "Locus and continuity geometry",
    "Convex geometry": "Geometric inequalities and optimization",
    "Counting and divisibility": "Combinatorial algebra and counting",
    "Extremal combinatorics and probabilistic method": "Extremal combinatorics and Ramsey theory",
    "Games and strategies": "Games, strategies, and adversarial methods",
    "General combinatorial structures": "Combinatorial algebra and counting",
    "General combinatorics": "Combinatorial algebra and counting",
    "Linear algebra and convexity": "Algebraic structures and linear algebra",
    "Metric, convex, and incidence geometry": "Geometric inequalities and optimization",
    "Number theory constructions and pigeonhole": "Divisibility, gcd, lcm, and factorization",
    "Projective geometry": "Projective and affine geometry",
    "Sequences and recurrences": "Sequences, recurrences, and finite dynamics",
    "Spatial geometry": "3D and solid geometry",
}

FIFTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS = {
    **FOURTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
    "Algebraic manipulation and equations": "Equations, substitutions, and transformations",
    "Combinatorial structures and processes": "Processes, dynamics, potential, and reconfiguration",
    "Diophantine equations and integer constraints": "Diophantine equations and descent",
    "Euclidean geometry": "Core Euclidean geometry",
}

SIXTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS = {
    **FIFTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
    "Algebraic number structure": "Algebraic number theory flavor",
    "Congruences and residues": "Congruences and modular arithmetic",
    "Convex and discrete geometry": "Discrete and combinatorial geometry",
    "Data quality / statement checking": "Data-quality / invalid tag",
    "Flow and transport methods": "Discrete optimization, matching, covering, packing, and flows",
    "Group actions and symmetry": "Algebraic and linear methods in combinatorics",
    "Rationality, integrality, and algebraic number structure": "Number-theoretic algebra",
    "Solid geometry": "3D and solid geometry",
    "Symmetric algebra and identities": "Polynomials and algebraic manipulation",
    "Synthetic and metric geometry": "Core Euclidean geometry",
}

SEVENTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS = {
    **SIXTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
    "Algebraic structures and dynamics": "Algebraic structures and linear algebra",
    "Analytic/approximation number theory": "Sieve, density, and asymptotic estimates",
    "Complex-plane geometry": "Analytic and coordinate geometry",
    "Congruences, residues, and modular arithmetic": "Congruences and modular arithmetic",
    "Convexity and metric geometry": "Geometric inequalities and optimization",
    "Dynamic and locus geometry": "Locus and continuity geometry",
    "Game strategy and invariants": "Games, strategies, and adversarial methods",
    "Process/greedy methods": "Processes, dynamics, potential, and reconfiguration",
    "Triangle centers and advanced configurations": "Triangle centers and configurations",
    "Triangle centers and orthic/pedal geometry": "Triangle centers and configurations",
    "Triangle centers and orthocentric geometry": "Triangle centers and configurations",
    "Triangle cevians and medians": "Triangle centers and configurations",
    "Simson and pedal geometry": "Triangle centers and configurations",
    "Solid geometry": "3D and solid geometry",
    "Divisibility and prime structure": "Divisibility, gcd, lcm, and factorization",
}

FOURTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS = {
    **SECOND_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
    "BIPARTITE COVERINGS": "BIPARTITE COVERING",
}

SIXTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS = {
    **FOURTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
    "TRIG IDENTITIES": "TRIG IDENTITIES",
    "TUR\u221a\u00c5N/MANTEL": "TUR\u00c1N/MANTEL",
    "VARIGNON PARALLELOGRAM": "MIDPOINTS AND MIDLINES",
}

SEVENTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS = {
    **SIXTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
    "MIQUEL/POWER": "MIQUEL/POWER",
    "ORTHOCENTER/SIMSON FLAVOR": "ORTHOCENTER/SIMSON FLAVOR",
    "PLANAR TRIANGULATIONS": "PLANAR TRIANGULATIONS",
    "QUADRATIC RESIDUES": "QUADRATIC RESIDUES",
}

METHOD_ONLY_TABLE_SUBTOPICS = {"General strategy and proof architecture"}
TABLE_EMPTY_VALUES = {"", "-", "\u2014", "NULL", "NONE", "N/A"}


def _read_layered_topic_tag_table_file(filename: str) -> str:
    path = Path(__file__).with_name(filename)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _table_values(value: str) -> tuple[str, ...]:
    values: list[str] = []
    for part in (value or "").split(";"):
        cleaned = part.strip()
        if cleaned.upper() in TABLE_EMPTY_VALUES:
            continue
        values.append(cleaned)
    return tuple(values)


def _table_layer_values(value: str) -> tuple[str, ...]:
    values: list[str] = []
    for chunk in _table_values(value):
        for part in re.split(r"\s*,\s*", chunk):
            cleaned = part.strip()
            if cleaned.upper() in TABLE_EMPTY_VALUES:
                continue
            values.append(cleaned)
    return tuple(values)


def _table_domains(area: str) -> tuple[str, ...]:
    domains: list[str] = []
    for raw_area in _table_values(area):
        for raw_domain in re.split(r"\s*(?:/|,)\s*", raw_area):
            domain = DOMAIN_CODE_BY_TABLE_LABEL.get(raw_domain)
            if domain and domain not in domains:
                domains.append(domain)
    return tuple(domains)


def _table_canonical_subtopic(
    subtopic: str,
    domains: tuple[str, ...],
    replacements: dict[str, str],
    raw_tag: str,
    raw_replacements: dict[str, str],
) -> str:
    raw_replacement = raw_replacements.get(raw_tag.strip().upper())
    if raw_replacement:
        return raw_replacement
    if subtopic in METHOD_ONLY_TABLE_SUBTOPICS:
        return ""
    if subtopic in {"Discrete geometry and incidence", "Finite configurations and incidence geometry"}:
        return "Discrete and combinatorial geometry" if domains[:1] == ("GEO",) else "Combinatorial and discrete geometry"
    if subtopic == "Combinatorial geometry":
        return "Discrete and combinatorial geometry" if domains[:1] == ("GEO",) else "Combinatorial and discrete geometry"
    if subtopic == "Modular arithmetic and coloring":
        return "Coloring, tiling, grids, and invariants" if domains[:1] == ("COMB",) else "Congruences and modular arithmetic"
    return replacements.get(subtopic, subtopic)


def _table_raw_alias_keys(table: str, *, split_raw_aliases: bool) -> set[str]:
    alias_keys: set[str] = set()
    for line in table.splitlines():
        fields = line.strip().split("\t")
        if len(fields) != TABLE_FIELD_COUNT or fields[0] == "Area":
            continue
        raw_tag = fields[-1]
        for raw_alias in _table_raw_tag_aliases(raw_tag, split_raw_aliases=split_raw_aliases):
            raw_key = raw_alias.strip().upper()
            if raw_key:
                alias_keys.add(raw_key)
    return alias_keys


def _table_aliases(raw_tag: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for alias in (raw_tag, repair_topic_tag_text(raw_tag)):
        if alias and alias not in aliases:
            aliases.append(alias)
    return tuple(aliases)


def _table_raw_tag_aliases(raw_tag: str, *, split_raw_aliases: bool) -> tuple[str, ...]:
    if split_raw_aliases:
        aliases = _table_values(raw_tag)
        if aliases:
            return aliases
    raw_tag = raw_tag.strip()
    return (raw_tag,) if raw_tag else ()


def _table_mappings(  # noqa: PLR0913
    line: str,
    *,
    replacements: dict[str, str],
    raw_replacements: dict[str, str],
    raw_stored_technique_replacements: dict[str, str],
    drop_source_domain_aliases: set[str],
    split_raw_aliases: bool,
) -> tuple[LayeredTopicTagMapping, ...]:
    fields = line.split("\t")
    if len(fields) != TABLE_FIELD_COUNT or fields[0] == "Area":
        return ()
    area, subtopic, object_tag, technique_tag, lemma_tag, proof_role, raw_tag = fields
    domains = _table_domains(area)
    if not domains or not raw_tag.strip():
        return ()
    status = "method" if subtopic in METHOD_ONLY_TABLE_SUBTOPICS else "alias"
    raw_aliases = _table_raw_tag_aliases(raw_tag, split_raw_aliases=split_raw_aliases)
    if not raw_aliases:
        return ()
    default_stored_technique = repair_topic_tag_text(raw_aliases[0] if split_raw_aliases else raw_tag)
    mappings: list[LayeredTopicTagMapping] = []
    for raw_alias in raw_aliases:
        raw_key = raw_alias.strip().upper()
        canonical_subtopic = _table_canonical_subtopic(subtopic, domains, replacements, raw_alias, raw_replacements)
        stored_technique = raw_stored_technique_replacements.get(raw_key, default_stored_technique)
        mappings.append(
            _mapping(
                domains,
                canonical_subtopic,
                stored_technique,
                _table_aliases(raw_alias),
                object_tags=_table_layer_values(object_tag),
                technique_tags=_table_layer_values(technique_tag),
                lemma_theorem_tags=_table_layer_values(lemma_tag),
                proof_roles=_table_layer_values(proof_role),
                status=status,
                main_topic="" if status == "method" else domains[0],
                preserve_source_domains=raw_key not in drop_source_domain_aliases,
            ),
        )
    return tuple(mappings)


def _build_layered_topic_tag_mappings(  # noqa: PLR0913
    table: str,
    *,
    replacements: dict[str, str],
    drop_source_domain_aliases: set[str] | None = None,
    raw_replacements: dict[str, str] | None = None,
    raw_stored_technique_replacements: dict[str, str] | None = None,
    split_raw_aliases: bool = False,
) -> tuple[LayeredTopicTagMapping, ...]:
    mappings: list[LayeredTopicTagMapping] = []
    drop_source_domain_aliases = drop_source_domain_aliases or set()
    raw_replacements = raw_replacements or {}
    raw_stored_technique_replacements = raw_stored_technique_replacements or {}
    for line in table.splitlines():
        line_mappings = _table_mappings(
            line.strip(),
            replacements=replacements,
            drop_source_domain_aliases=drop_source_domain_aliases,
            raw_replacements=raw_replacements,
            raw_stored_technique_replacements=raw_stored_technique_replacements,
            split_raw_aliases=split_raw_aliases,
        )
        mappings.extend(line_mappings)
    return tuple(mappings)


def _auxiliary_layer_mapping(  # noqa: PLR0913
    *,
    area: str = "",
    canonical_subtopic: str = "",
    raw_tag: str,
    object_tag: str = "",
    technique_tag: str = "",
    lemma_tag: str = "",
    proof_role: str = "",
    status: str = "alias",
    stored_technique: str | None = None,
    preserve_source_domains: bool = True,
) -> LayeredTopicTagMapping:
    domains = _table_domains(area)
    normalized_canonical_subtopic = ""
    if canonical_subtopic:
        normalized_canonical_subtopic = _table_canonical_subtopic(
            canonical_subtopic,
            domains,
            SECOND_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
            raw_tag,
            SECOND_PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS,
        )
    if status == "method":
        normalized_canonical_subtopic = ""
    return _mapping(
        domains,
        normalized_canonical_subtopic,
        stored_technique or repair_topic_tag_text(raw_tag),
        _table_aliases(raw_tag),
        object_tags=_table_values(object_tag),
        technique_tags=_table_values(technique_tag),
        lemma_theorem_tags=_table_values(lemma_tag),
        proof_roles=_table_values(proof_role),
        status=status,
        main_topic="" if status == "method" or not domains else domains[0],
        preserve_source_domains=preserve_source_domains,
    )


BASE_LAYERED_TOPIC_TAG_MAPPINGS: tuple[LayeredTopicTagMapping, ...] = (
    _mapping(
        ("NT",),
        "Congruences and modular arithmetic",
        "Modular arithmetic / residues",
        ("MODULAR ARITHMETIC / RESIDUES",),
        object_tags=("residues",),
        technique_tags=("modular arithmetic",),
    ),
    _mapping(
        ("NT",),
        "Divisibility, gcd, lcm, and factorization",
        "Divisibility / GCD / factorization",
        ("DIVISIBILITY / GCD / FACTORIZATION",),
        object_tags=("gcd", "lcm", "divisibility relation"),
        technique_tags=("divisibility", "factorization"),
        lemma_theorem_tags=("Euclidean algorithm", "Bézout"),
    ),
    _mapping(
        ("NT",),
        "Divisibility, gcd, lcm, and factorization",
        "Bézout / Euclidean algorithm",
        ("BÉZOUT / EUCLIDEAN ALGORITHM", "BÉZOUT/LINEAR COMBINATIONS", "BEZOUT/LINEAR COMBINATIONS"),
        object_tags=("gcd", "lcm", "divisibility relation"),
        technique_tags=("divisibility", "factorization"),
        lemma_theorem_tags=("Euclidean algorithm", "Bézout"),
    ),
    _mapping(
        ("NT",),
        "p-adic and valuation methods",
        "Valuations / p-adic methods",
        ("VALUATIONS / P-ADIC METHODS",),
        object_tags=("p-adic valuation",),
        technique_tags=("valuation method",),
    ),
    _mapping(
        ("NT",),
        "Prime numbers and prime divisors",
        "Primes / prime divisors",
        ("PRIMES / PRIME DIVISORS",),
        object_tags=("prime", "prime divisor"),
        technique_tags=("prime divisor analysis",),
    ),
    _mapping(
        ("NT",),
        "Base, digit, and carry methods",
        "Base / digit / carry methods",
        ("BASE / DIGIT / CARRY METHODS",),
        object_tags=("digit", "carry"),
        technique_tags=("base representation",),
    ),
    _mapping(
        ("NT",),
        "Floor, rounding, Beatty, Farey, and approximation methods",
        "Floor / rounding / approximation",
        ("FLOOR / ROUNDING / APPROXIMATION",),
        object_tags=("floor function", "Farey fraction", "Beatty sequence"),
        technique_tags=("rounding", "approximation"),
    ),
    _mapping(
        ("NT",),
        "Chinese remainder theorem and local-to-global methods",
        "Chinese remainder theorem / local-global",
        ("CHINESE REMAINDER THEOREM / LOCAL-GLOBAL", "CRT"),
        object_tags=("residue system",),
        technique_tags=("local-to-global",),
        lemma_theorem_tags=("Chinese remainder theorem",),
    ),
    _mapping(
        ("NT",),
        "Diophantine equations and descent",
        "Diophantine equations",
        ("DIOPHANTINE EQUATIONS",),
        object_tags=("Diophantine equation",),
        technique_tags=("descent", "integer solution analysis"),
        proof_roles=("descent",),
    ),
    _mapping(
        ("NT",),
        "Pell-type equations and Vieta jumping",
        "Pell / Vieta jumping",
        ("PELL / VIETA JUMPING", "VIETA JUMPING"),
        object_tags=("Pell equation",),
        technique_tags=("Vieta jumping",),
        lemma_theorem_tags=("Vieta jumping",),
        proof_roles=("descent",),
    ),
    _mapping(
        ("NT",),
        "Quadratic residues, squares, and squarefree methods",
        "Quadratic residues / squarefree",
        ("QUADRATIC RESIDUES / SQUAREFREE", "SQUARES"),
        object_tags=("quadratic residue", "squarefree integer", "square"),
        technique_tags=("quadratic residue method",),
    ),
    _mapping(
        ("NT",),
        "LTE and exponent lifting",
        "LTE",
        ("LTE", "LTE / EXPONENT LIFTING"),
        object_tags=("exponent of prime",),
        technique_tags=("exponent lifting",),
        lemma_theorem_tags=("LTE",),
    ),
    _mapping(
        ("NT",),
        "Primitive divisors and Zsigmondy-type ideas",
        "Primitive divisors / Zsigmondy",
        ("PRIMITIVE DIVISORS / ZSIGMONDY",),
        object_tags=("primitive prime divisor",),
        technique_tags=("primitive divisor method",),
        lemma_theorem_tags=("Zsigmondy",),
    ),
    _mapping(
        ("NT",),
        "Möbius inversion and inclusion-exclusion",
        "Möbius inversion",
        ("MÖBIUS INVERSION",),
        object_tags=("divisor poset",),
        technique_tags=("inversion method",),
        lemma_theorem_tags=("Möbius inversion", "inclusion-exclusion"),
    ),
    _mapping(
        ("NT", "COMB"),
        "Discrepancy methods",
        "Discrepancy",
        ("DISCREPANCY",),
        object_tags=("coloring discrepancy",),
        technique_tags=("discrepancy method",),
        proof_roles=("lower bound",),
        main_topic="NT",
    ),
    _mapping(
        ("NT", "ALG"),
        "Radical and rationality methods",
        "Radicals",
        ("RADICALS",),
        object_tags=("radical expression",),
        technique_tags=("rationality / irrationality obstruction",),
        proof_roles=("obstruction",),
        main_topic="NT",
    ),
    _mapping(
        ("NT", "ALG", "GEO"),
        "Ratio methods",
        "Ratios",
        ("RATIOS",),
        object_tags=("ratio",),
        technique_tags=("ratio chasing",),
        main_topic="NT",
    ),
    _mapping(
        ("ALG",),
        "Inequalities and optimization",
        "Cauchy-Schwarz / Engel form",
        ("CAUCHY-SCHWARZ / ENGEL FORM", "CAUCHY-SCHWARZ", "CAUCHY", "CAUCHY/AM-GM"),
        object_tags=("quadratic expression",),
        technique_tags=("Cauchy-Schwarz", "Engel form"),
        lemma_theorem_tags=("Cauchy-Schwarz", "Engel"),
    ),
    _mapping(
        ("ALG",),
        "Inequalities and optimization",
        "Smoothing",
        ("SMOOTHING",),
        object_tags=("symmetric inequality",),
        technique_tags=("smoothing",),
        proof_roles=("extremal reduction",),
    ),
    _mapping(
        ("ALG",),
        "Inequalities and optimization",
        "UVW / PQR method",
        ("UVW / PQR METHOD", "UVW", "PQR"),
        object_tags=("symmetric polynomial inequality",),
        technique_tags=("uvw method", "pqr method"),
        lemma_theorem_tags=("UVW", "PQR"),
        proof_roles=("extremal reduction",),
    ),
    _mapping(
        ("ALG",),
        "Inequalities and optimization",
        "Convexity / Jensen methods",
        ("CONVEXITY", "CONVEXITY / JENSEN METHODS"),
        object_tags=("convex function",),
        technique_tags=("convexity",),
        lemma_theorem_tags=("Jensen", "Karamata"),
    ),
    _mapping(
        ("ALG",),
        "Equations, substitutions, and transformations",
        "Substitution",
        ("SUBSTITUTION", "SUBSTITUTIONS"),
        object_tags=("substitution",),
        technique_tags=("substitution", "transformation"),
        proof_roles=("simplification",),
    ),
    _mapping(
        ("ALG",),
        "Functional equations",
        "Functional equations",
        ("FUNCTIONAL EQUATIONS",),
        object_tags=("function",),
        technique_tags=("functional equation method",),
    ),
    _mapping(
        (),
        "General problem-solving method",
        "Construction",
        ("CONSTRUCTION", "CONSTRUCTIVE", "CONSTRUCTIVE METHOD"),
        proof_roles=("construction",),
        status="method",
        main_topic="",
    ),
    _mapping(
        (),
        "General problem-solving method",
        "Contradiction",
        ("CONTRADICTION", "CONTRADICTION / OBSTRUCTION"),
        proof_roles=("contradiction / obstruction",),
        status="method",
        main_topic="",
    ),
    _mapping(
        (),
        "General problem-solving method",
        "Casework and finite checking",
        ("CASEWORK", "CASEWORK AND FINITE CHECKING", "FINITE CHECKING"),
        proof_roles=("casework / finite check",),
        status="method",
        main_topic="",
    ),
    _mapping(
        (),
        "General problem-solving method",
        "Bounding and estimates",
        ("BOUNDING AND ESTIMATES", "BOUNDING / ESTIMATES", "LOWER BOUND", "UPPER BOUND"),
        proof_roles=("upper bound / lower bound",),
        status="method",
        main_topic="",
    ),
    _mapping(
        ("GEO",),
        "Core Euclidean geometry",
        "Angle chasing",
        ("ANGLE CHASING", "ANGLE CHASE"),
        object_tags=("angle",),
        technique_tags=("angle chasing",),
        proof_roles=("deduction",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Core Euclidean geometry",
        "Angle bisectors",
        ("ANGLE BISECTORS", "ANGLE BISECTOR"),
        object_tags=("angle bisector",),
        technique_tags=("angle bisector chasing",),
        lemma_theorem_tags=("Angle bisector theorem",),
        proof_roles=("deduction",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Circle geometry",
        "Cyclic quadrilateral",
        ("CYCLIC QUADRILATERAL", "CYCLIC QUADRILATERALS"),
        object_tags=("cyclic quadrilateral",),
        technique_tags=("cyclicity", "cyclic quadrilateral chasing"),
        proof_roles=("angle chase",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Circle geometry",
        "Cyclicity",
        ("CYCLIC ANGLES", "CYCLICITY", "CYCLIC GEOMETRY"),
        object_tags=("cyclic angle",),
        technique_tags=("cyclic angle chasing",),
        proof_roles=("angle chase",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Circle geometry",
        "Tangency",
        ("TANGENCY", "CIRCLE TANGENCY"),
        object_tags=("tangent line",),
        technique_tags=("tangency", "tangent chasing"),
        proof_roles=("angle/length deduction",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Circle geometry",
        "Tangents",
        ("TANGENTS",),
        object_tags=("tangent line",),
        technique_tags=("tangency", "tangent chasing"),
        proof_roles=("angle/length deduction",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Circle geometry",
        "Tangent-chord",
        ("TANGENT-CHORD",),
        object_tags=("tangent line",),
        technique_tags=("tangency", "tangent chasing"),
        lemma_theorem_tags=("Tangent-chord theorem",),
        proof_roles=("angle/length deduction",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Circle geometry",
        "Tangent circles",
        ("TANGENT CIRCLES",),
        object_tags=("tangent circles",),
        technique_tags=("tangent circle method",),
        proof_roles=("configuration recognition",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Circle geometry",
        "Power of a point",
        ("POWER OF A POINT", "POWER OF POINT"),
        object_tags=("power of a point",),
        technique_tags=("power of a point",),
        lemma_theorem_tags=("Power of a point",),
        proof_roles=("length product proof",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Circle geometry",
        "Circle intersections",
        ("CIRCLE INTERSECTIONS",),
        object_tags=("circle intersection",),
        technique_tags=("circle intersection geometry",),
        proof_roles=("configuration recognition",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Triangle centers and configurations",
        "Circumcenter",
        ("CIRCUMCENTER", "CIRCUMCENTERS"),
        object_tags=("circumcenter",),
        technique_tags=("circumcenter geometry",),
        proof_roles=("center chasing",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Triangle centers and configurations",
        "Incenter and incircle",
        ("INCENTER", "INCENTERS", "INCIRCLE"),
        object_tags=("incenter", "incircle"),
        technique_tags=("incenter geometry", "incircle geometry"),
        proof_roles=("center chasing",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("GEO",),
        "Transformational geometry",
        "Inversion",
        ("INVERSION",),
        object_tags=("inverse point/circle",),
        technique_tags=("inversion",),
        lemma_theorem_tags=("Inversion",),
        proof_roles=("transformation",),
        preserve_source_domains=False,
    ),
    _mapping(
        ("COMB",),
        "Coloring, tiling, grids, and invariants",
        "Grid coloring",
        ("GRID COLORING", "GRID COLOURING"),
        object_tags=("grid",),
        technique_tags=("grid coloring",),
        proof_roles=("obstruction",),
    ),
    _mapping(
        ("COMB",),
        "Graph theory",
        "Hamiltonian paths and cycles",
        ("HAMILTONIAN CYCLE", "HAMILTONIAN CYCLES", "HAMILTONIAN PATH", "HAMILTONIAN PATHS"),
        object_tags=("Hamiltonian cycle",),
    ),
    _mapping(
        ("COMB",),
        "Extremal combinatorics and Ramsey theory",
        "Turan / Mantel",
        ("TURAN", "MANTEL/TURAN", "TURAN/MANTEL"),
        lemma_theorem_tags=("Turan", "Mantel"),
    ),
    _mapping(
        ("COMB",),
        "Discrete optimization, matching, covering, packing, and flows",
        "Hall / Konig / matching",
        ("HALL", "HALL/KONIG", "KONIG THEOREM"),
        object_tags=("matching",),
        technique_tags=("matching method",),
        lemma_theorem_tags=("Hall", "Konig"),
    ),
    _mapping(
        ("COMB", "GEO"),
        "Packing and covering methods",
        "Packing",
        ("PACKING",),
        object_tags=("packing configuration",),
        technique_tags=("packing argument",),
        proof_roles=("upper/lower bound",),
        main_topic="COMB",
    ),
    _mapping(
        ("COMB", "GEO"),
        "Area and dissection methods",
        "Area",
        ("AREA",),
        object_tags=("area region",),
        technique_tags=("area method",),
        proof_roles=("invariant / bound",),
        main_topic="COMB",
    ),
)


ATTACHED_LAYERED_TOPIC_TAG_TABLE = r"""
Area	Canonical Subtopic	Object tag	Technique tag	Lemma/Theorem tag	Proof role	Raw imported tag
Combinatorics	Pigeonhole, extremal principle, and averaging	configuration	extremal argument		construction / lower bound	EXTREMAL CONFIGURATION
Combinatorics	Set systems, posets, and extremal set theory	set family	extremal set method	Sperner; LYM	upper bound / extremal example	EXTREMAL SET THEORY
Algebra	Polynomials and algebraic manipulation	polynomial	irreducibility		obstruction	IRREDUCIBILITY
Combinatorics	Counting and enumerative combinatorics	partition	partition counting		counting / construction	PARTITIONS
Combinatorics	Set systems, posets, and extremal set theory	poset	chain-antichain method	Dilworth; Sperner	upper bound / structure	POSETS
Geometry	Triangle centers and triangle configurations	excenter				EXCENTERS
Combinatorics	Games, strategies, and processes	impartial game	strategy / Grundy analysis	Sprague-Grundy	winning strategy	IMPARTIAL GAMES
Geometry	Triangle centers and triangle configurations	incenter	angle bisector geometry			INCENTER GEOMETRY
Geometry	Projective and advanced geometry	projective configuration	projective transformation			PROJECTIVE FLAVOR
Combinatorics; Geometry	Coloring, tiling, grids, and invariants	tiling	coloring / invariant		construction / impossibility	TILINGS
Geometry	Geometry-flavored algebra	vectors	vector geometry			VECTOR GEOMETRY
Geometry	Circle geometry	circle	angle chase			CIRCLES
Geometry	Circle geometry	coaxal circles	radical axis / coaxality		concurrency / collinearity	COAXALITY
Combinatorics	Coloring, tiling, grids, and invariants	coloring	coloring invariant		invariant / impossibility	COLORING INVARIANT
Geometry	Special configurations and special angles	isosceles triangle	symmetry			ISOSCELES SYMMETRY
Geometry	Core Euclidean geometry	triangle with transversal		Menelaus	collinearity	MENELAUS
Geometry	Core Euclidean geometry	midpoints	midpoint chase			MIDPOINTS
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants	ordered quantity	minimax		optimization / extremal choice	MINIMAX
Geometry	Geometry-flavored algebra	regular polygon	rotation / roots of unity			REGULAR POLYGONS
Geometry	Geometry-flavored algebra	rotation	rotation transformation			ROTATION
Combinatorics	Graph theory	cycle graph	cycle argument			CYCLES
Geometry	Core Euclidean geometry	directed lengths	signed length chase			DIRECTED LENGTHS
Number Theory	Arithmetic functions and divisor structure	Euler phi / totient function	arithmetic function analysis	Euler theorem		EULER PHI / TOTIENT
Geometry	Triangle centers and triangle configurations	excircle	excenter geometry			EXCIRCLES
Algebra; Combinatorics	Pigeonhole, extremal principle, and averaging	configuration	extremal argument		extremal choice / structure	EXTREMAL CONFIGURATIONS
Algebra	Polynomials and algebraic manipulation	integer-valued polynomial/function	finite differences			INTEGER-VALUED POLYNOMIALS / FUNCTIONS
Algebra; Number Theory	Equations, substitutions, and transformations	logarithm	log transform			LOGARITHMS
Combinatorics	Graph theory	matching	matching argument	Hall; König	existence / construction	MATCHINGS
Algebra	Polynomials and algebraic manipulation	polynomial identity	identity comparison			POLYNOMIAL IDENTITIES
Geometry	Special configurations and special angles	right triangle	metric angle chase	Pythagoras; Thales		RIGHT TRIANGLE
Algebra	Extremal methods, monotonicity, and invariants	solution/configuration	uniqueness argument		uniqueness	UNIQUENESS
Algebra	Analytic estimates and asymptotics	sequence/function growth	asymptotic estimate		limit / bound	ASYMPTOTICS
Geometry	Circle geometry	circle with diameter	right-angle detection	Thales		CIRCLE WITH DIAMETER
Algebra	Extremal methods, monotonicity, and invariants	solution family	case classification		classification	CLASSIFICATION
Combinatorics	Probability, entropy, coding, and information methods	code	coding bound	Hamming bound; Singleton bound	upper/lower bound	CODING THEORY
Geometry	Geometric inequalities and optimization	convex polygon	convexity / area argument			CONVEX POLYGONS
Algebra	Polynomials and algebraic manipulation	polynomial	degree argument		contradiction / bound	DEGREE ARGUMENTS
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL ARGUMENT
Number Theory	Finite fields, characters, and advanced modular tools	finite field	character sums			FINITE FIELDS / CHARACTERS
Geometry	Triangle centers and triangle configurations	orthocenter; circumcenter	triangle-center chase			ORTHOCENTER/CIRCUMCENTER
Combinatorics	Graph theory	tree	tree induction			TREES
Geometry	3D and solid geometry	solid configuration	3D geometry			3D GEOMETRY
Combinatorics	Probability, entropy, coding, and information methods	code	coding method		encoding / decoding	CODING
Geometry	Circle geometry	equal chords	circle chord chase			EQUAL CHORDS
Combinatorics	Graph theory	grid graph	graph model			GRID GRAPH
Geometry	Projective and advanced geometry	harmonic bundle	projective chase	cross-ratio		HARMONIC BUNDLES
Algebra	Sequences, recurrences, and series	harmonic sum	summation / estimates			HARMONIC SUMS
Geometry	Triangle centers and triangle configurations	incircle	tangency chase			INCIRCLES
Combinatorics	Combinatorial algebra and counting	finite sets	inclusion-exclusion	PIE	counting	INCLUSION-EXCLUSION
Algebra; Combinatorics; Number Theory	Discrete functions, floors, rounding, and base representation	intervals	interval covering/order			INTERVALS
Combinatorics	Combinatorial algebra and counting	paired objects	pairing		involution / cancellation	PAIRING
Combinatorics	Games, strategies, and processes	game positions	pairing strategy		winning strategy	PAIRING STRATEGY
Combinatorics; Number Theory	Algorithms, automata, words, and constructive combinatorics	state graph	reachability / invariant		existence / impossibility	REACHABILITY
Geometry	Geometry-flavored algebra	regular polygon	rotation / roots of unity			REGULAR POLYGON
Algebra	Sequences, recurrences, and series	sequence sum	summation by parts	Abel summation	estimate	SUMMATION BY PARTS / ABEL SUMMATION
Geometry	Geometry-flavored algebra	triangle coordinates	trilinear / barycentric coordinates			TRILINEARS/BARYCENTRICS
Geometry	Core Euclidean geometry	angle bisector		Angle bisector theorem	ratio chase	ANGLE BISECTOR THEOREM
Geometry	Triangle centers and triangle configurations	centroid	median/centroid chase			CENTROID
Algebra; Geometry	Analytic estimates and asymptotics	sequence/set	compactness argument		existence / limit	COMPACTNESS
Algebra	Inequalities and optimization	concave function	concavity		inequality	CONCAVITY
Geometry	Circle geometry	cyclic hexagon	circle angle chase			CYCLIC HEXAGON
Combinatorics	Coloring, tiling, grids, and invariants	coloring	extremal coloring		lower bound / contradiction	EXTREMAL COLORING
Number Theory	Number-theoretic algebra	factorial	valuation / divisibility	Legendre formula		FACTORIALS
Combinatorics	Coloring, tiling, grids, and invariants	grid	grid coloring / invariant		construction / impossibility	GRIDS
Combinatorics; Geometry	Coloring, tiling, grids, and invariants	local constraints	local-to-global		structure / contradiction	LOCAL CONSTRAINTS
Geometry	Core Euclidean geometry	parallel lines	angle chase			PARALLELS
Combinatorics	Graph theory	planar graph	planarity	Euler formula	counting / bound	PLANAR GRAPHS
Geometry	Projective and advanced geometry	poles and polars	projective polarity			POLES/POLARS
Algebra; Combinatorics	Inequalities and optimization	positive quantity	positivity		sign / inequality	POSITIVITY
Geometry	Special configurations and special angles	tangential quadrilateral	tangent lengths	Pitot		TANGENTIAL QUADRILATERAL
Combinatorics; Geometry	Coloring, tiling, grids, and invariants	triangulation	triangulation / Euler counting	Euler formula	decomposition	TRIANGULATIONS
Algebra	Complex, trigonometric, and Fourier methods	trigonometric expression	trigonometric method			TRIG
Algebra	Complex, trigonometric, and Fourier methods	cevians	trigonometric Ceva	Trig Ceva	concurrency	TRIG CEVA
Algebra	Polynomials and algebraic manipulation	polynomial/series	coefficient comparison			COEFFICIENT COMPARISON
Geometry	Triangle centers and triangle configurations	contact triangle	incircle tangency chase			CONTACT TRIANGLE
Algebra	Algebraic structures and linear algebra	cyclic group	group structure			CYCLIC GROUPS
Combinatorics	Set systems, posets, and extremal set theory	block design	design counting	BIBD equations	construction / counting	DESIGN THEORY
Geometry; Combinatorics	Discrete geometry and incidence	finite point/line configuration	discrete geometry			DISCRETE GEOMETRY
Algebra; Combinatorics; Number Theory	Extremal methods, monotonicity, and invariants	discrete objective	discrete optimization		optimization	DISCRETE OPTIMIZATION
Combinatorics	Coloring, tiling, grids, and invariants	domino tiling	checkerboard coloring		tiling obstruction / construction	DOMINO TILINGS
Combinatorics	Graph theory	edge coloring	graph coloring	Vizing	coloring	EDGE COLORING
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants	ordered objects	extremal ordering		choose largest/smallest	EXTREMAL ORDERING
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants	process	monotonic process		termination / invariant	EXTREMAL PROCESS
Combinatorics	Set systems, posets, and extremal set theory	set family	extremal set method	Sperner; LYM	upper bound / extremal example	EXTREMAL SETS
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants	sequence/function	growth estimate		monotonicity / bound	GROWTH
Geometry	Core Euclidean geometry	homothety center	homothety			HOMOTHETY CENTERS
Geometry; Number Theory	Discrete geometry and incidence	lattice points	lattice geometry			LATTICE GEOMETRY
Geometry	Core Euclidean geometry	lengths	length chase			LENGTH CHASE
Algebra	Equations, substitutions, and transformations	equation/system	linearization		simplification	LINEARIZATION
Algebra	Algebraic structures and linear algebra	matrix	linear algebra			MATRICES
Geometry	Core Euclidean geometry	midpoint	midpoint chase			MIDPOINT
Geometry	Core Euclidean geometry	parallelogram	parallel/vector chase			PARALLELOGRAM
Combinatorics	Games, strategies, and processes	positional game	strategy	strategy stealing	winning strategy	POSITIONAL GAMES
Algebra	Algebraic structures and linear algebra	rational function	partial fractions / poles			RATIONAL FUNCTIONS
Algebra	Polynomials and algebraic manipulation	real-rooted polynomial	interlacing		root control	REAL-ROOTEDNESS / INTERLACING
Algebra	Algebraic structures and linear algebra	ring	ring algebra			RINGS
Number Theory	Divisibility, gcd, lcm, and primes	square numbers	gap/modular argument		contradiction	SQUARE GAPS
Geometry	Circle geometry	tangent circles	tangency chase			TANGENT CIRCLE
Geometry	Circle geometry	tangent line/circle	tangent criterion		tangency test	TANGENT CRITERION
Geometry	Circle geometry	tangents	tangent geometry			TANGENT GEOMETRY
Geometry	3D and solid geometry	3D coordinates	coordinate geometry			3D COORDINATES
Algebra	Equations, substitutions, and transformations	absolute value	case split / sign analysis			ABSOLUTE VALUES
Geometry	Projective and advanced geometry	advanced configuration	configuration chase			ADVANCED CONFIGURATION
Geometry	Triangle centers and triangle configurations	altitudes	orthic geometry			ALTITUDES
Geometry	Core Euclidean geometry	triangle coordinates	barycentric coordinates			BARYCENTRIC COORDINATES
Geometry	Circle geometry	circle centers	center chase			CIRCLE CENTERS
Combinatorics	Set systems, posets, and extremal set theory	set family	compression / shifting		normalization / extremal reduction	COMPRESSION
Geometry	Projective and advanced geometry	conic	projective geometry	Pascal; Brianchon		CONICS
Algebra	Algebraic structures and linear algebra	algebraic conjugates	conjugate pairing			CONJUGATES
Combinatorics	Algorithms, automata, words, and constructive combinatorics	constructed object	constructive induction		construction	CONSTRUCTIVE INDUCTION
Number Theory	Additive and multiplicative number theory	difference set	additive combinatorics			DIFFERENCE SETS
Algebra	Discrete functions, floors, rounding, and base representation	discrete function	discrete intermediate value		existence	DISCRETE INTERMEDIATE VALUE
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants	structure	extremal argument		structural characterization	EXTREMAL STRUCTURE
Combinatorics	Combinatorial algebra and counting	incidences	incidence counting		double counting	INCIDENCE COUNTING
Combinatorics	Probability, entropy, coding, and information methods	information/entropy	entropy method		upper/lower bound	INFORMATION THEORY
Algebra	Functional equations	integer-valued function	functional equation over integers			INTEGER DOMAIN
Combinatorics; Number Theory	Algebraic structures and linear algebra	F2 vector space	linear algebra over F2		parity / rank	LINEAR ALGEBRA OVER F2
Geometry	Circle geometry	Miquel point; spiral similarity	spiral similarity	Miquel	concurrency / cyclicity	MIQUEL/SPIRAL SIMILARITY
Combinatorics	Coloring, tiling, grids, and invariants	coloring	modular coloring		invariant / impossibility	MODULAR COLORING
Algebra	Extremal methods, monotonicity, and invariants	monotone function	monotonicity			MONOTONE FUNCTIONS
Geometry	Triangle centers and triangle configurations	orthocenter	orthic geometry			ORTHOCENTERS
Geometry	Core Euclidean geometry	parallel lines	angle chase			PARALLEL LINES
Algebra	Polynomials and algebraic manipulation	polynomial	polynomial method		existence / bound	POLYNOMIAL METHOD
Algebra	Inequalities and optimization	positive real variables	normalization / positivity		inequality	POSITIVE REALS
Combinatorics	Games, strategies, and processes	game	strategy stealing		existence / winning strategy	STRATEGY STEALING
Algebra; Combinatorics	Sequences, recurrences, and series	subadditive sequence/function	subadditivity	Fekete lemma	bound / limit	SUBADDITIVITY
Geometry	Triangle centers and triangle configurations	symmedian	symmedian chase	Symmedian lemma		SYMMEDIAN
Algebra	Inequalities and optimization	area expression	area inequality		inequality	AREA INEQUALITY
Combinatorics	Set systems, posets, and extremal set theory	block design	design counting	BIBD equations	construction / counting	BLOCK DESIGNS
Geometry	Circle geometry	circumcircle	circle angle chase			CIRCUMCIRCLES
Combinatorics	Graph theory	complement graph	complement argument		translation	COMPLEMENT GRAPH
Geometry	Geometry-flavored algebra	coordinates/vectors	coordinate-vector method			COORDINATES/VECTORS
Algebra	Algebraic structures and linear algebra	determinant	determinant method			DETERMINANTS
Combinatorics; Geometry	Coloring, tiling, grids, and invariants	dissection	cut-and-paste		construction / invariant	DISSECTION
Geometry	Special configurations and special angles	equilateral triangle/configuration	rotation by 60 degrees			EQUILATERAL GEOMETRY
Geometry	Triangle centers and triangle configurations	excircle	excenter geometry			EXCIRCLE
Combinatorics	Coloring, tiling, grids, and invariants	grid	extremal grid argument		lower bound / construction	EXTREMAL GRID
Combinatorics	Set systems, posets, and extremal set theory	subset family	extremal subset method	Sperner; LYM	upper bound	EXTREMAL SUBSETS
Combinatorics	Counting and enumerative combinatorics	grid path	lattice path counting		counting	GRID PATHS
Geometry	Geometry-flavored algebra	incircle	incircle coordinates			INCIRCLE COORDINATES
Geometry	Triangle centers and triangle configurations	incircle; contact triangle	tangency chase			INCIRCLE/CONTACT TRIANGLE
Geometry	Triangle centers and triangle configurations	isogonal conjugates	isogonal geometry			ISOGONAL CONJUGATES
Combinatorics	Design theory, Latin squares, and finite structures	Latin square	Latin square construction		construction	LATIN SQUARES
Combinatorics; Geometry	Discrete geometry and incidence	line arrangement	incidence / arrangement counting		counting / bound	LINE ARRANGEMENTS
Algebra	Inequalities and optimization	linear constraints	linear programming		optimization	LINEAR PROGRAMMING
Algebra	Sequences, recurrences, and series	linear recurrence	characteristic polynomial			LINEAR RECURRENCES
Algebra	Inequalities and optimization	metric distances	metric inequality	Triangle inequality	inequality	METRIC INEQUALITY
Geometry	Circle geometry	Miquel point/circles	Miquel configuration	Miquel	cyclicity / concurrency	MIQUEL
Geometry	Core Euclidean geometry	moving point	continuity / locus		existence	MOVING POINT
Geometry	Core Euclidean geometry	perpendicular lines	angle chase			PERPENDICULARITY
Algebra	Functional equations	polynomial functional equation	polynomial method			POLYNOMIAL FUNCTIONAL EQUATION
Algebra	Algebraic structures and linear algebra	rank	rank argument		upper/lower bound	RANK
Geometry	Core Euclidean geometry	triangle		Sine rule	ratio chase	SINE RULE
Combinatorics	Algorithms, automata, words, and constructive combinatorics	word/sequence window	sliding window		local-to-global	SLIDING WINDOWS
Geometry	Circle geometry	tangent lengths	equal tangent lengths	Tangent lengths theorem	length chase	TANGENT LENGTHS
Geometry	Circle geometry	tangent and chord		Tangent-chord theorem	angle chase	TANGENT-CHORD THEOREM
Geometry	Circle geometry	tangential quadrilateral	tangent lengths	Pitot		TANGENTIAL QUADRILATERALS
Geometry	Geometry-flavored algebra	trigonometric/coordinate setup	trig-coordinate method			TRIG/COORDINATES
Geometry	Geometry-flavored algebra	triangle coordinates	trilinear coordinates			TRILINEARS
Algebra	Inequalities and optimization	weighted positive terms	weighted AM-GM	Weighted AM-GM	inequality	WEIGHTED AM-GM
Combinatorics	Algorithms, automata, words, and constructive combinatorics	words/strings	word combinatorics		construction / counting	WORDS
Geometry; Combinatorics	Geometric inequalities and optimization	area	area bound		lower/upper bound	AREA BOUNDS
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants	balanced quantities	balancing		construction / optimization	BALANCING
Geometry	Geometry-flavored algebra	triangle coordinates	barycentric/trilinear coordinates			BARYCENTRICS/TRILINEARS
Geometry	Circle geometry	circle tangents	tangent chase			CIRCLE TANGENTS
Combinatorics; Geometry	Counting and enumerative combinatorics	circular order	cyclic ordering		ordering	CIRCULAR ORDER
Geometry	Geometry-flavored algebra	complex/vectors	complex-vector geometry			COMPLEX/VECTOR GEOMETRY
Algebra; Geometry; Number Theory	Equations, substitutions, and transformations	composed functions/transformations	composition		iteration / transformation	COMPOSITION
Combinatorics	Graph theory	graph connectivity	connectivity argument		existence / obstruction	CONNECTIVITY
Geometry	Geometric inequalities and optimization	convex hull	convex hull argument		extremal boundary	CONVEX HULL
Combinatorics	Combinatorial algebra and counting	countable set/family	countability argument		counting / existence	COUNTABILITY
Algebra	Inequalities and optimization	cyclic inequality	cyclic summation		inequality	CYCLIC INEQUALITIES
Algebra	Inequalities and optimization	cyclic inequality	cyclic summation		inequality	CYCLIC INEQUALITY
Combinatorics; Geometry	Counting and enumerative combinatorics	cyclic order	cyclic ordering		ordering	CYCLIC ORDER
Geometry	Geometry-flavored algebra	cyclic polygon	circle angle chase			CYCLIC POLYGONS
Geometry	3D and solid geometry	polyhedron/complex	Euler characteristic	Euler formula	counting invariant	EULER CHARACTERISTIC
Geometry	Triangle centers and triangle configurations	excenter	excenter geometry			EXCENTER
Algebra; Combinatorics; Geometry	Pigeonhole, extremal principle, and averaging	arrangement	extremal arrangement		extremal choice / lower bound	EXTREMAL ARRANGEMENT
Combinatorics; Number Theory	Algebraic structures and linear algebra	F2 vector space	linear algebra over F2		parity / rank	F2 LINEAR ALGEBRA
Algebra	Discrete functions, floors, rounding, and base representation	floor function	floor/rounding analysis			FLOOR FUNCTIONS
Combinatorics	Graph theory	functional digraph	functional graph model			FUNCTIONAL DIGRAPHS
Combinatorics	Games, strategies, and processes	game	strategy		winning strategy	GAME THEORY
Number Theory; Geometry	Diophantine equations and descent	lattice points	geometry of numbers	Minkowski	existence / bound	GEOMETRY OF NUMBERS
Combinatorics	Set systems, posets, and extremal set theory	intersecting family	extremal set method	Erdos-Ko-Rado	upper bound	INTERSECTING FAMILIES
Geometry	Geometry-flavored algebra	circle/coordinate setup	inversion + coordinates			INVERSION/COORDINATES
Combinatorics	Counting and enumerative combinatorics	inversions	inversion counting		counting / parity	INVERSIONS
Number Theory	Number-theoretic algebra	irrational number	irrationality argument		contradiction	IRRATIONALITY
Geometry	Triangle centers and triangle configurations	isogonal conjugacy	isogonal geometry			ISOGONAL CONJUGACY
Algebra	Sequences, recurrences, and series	limit	limit argument			LIMITS
Geometry	Projective and advanced geometry	projective configuration	projective geometry			PROJECTIVE
Combinatorics	Graph theory	Ramsey coloring	Ramsey argument	Ramsey theorem	existence / bound	RAMSEY THEORY
Geometry	Geometry-flavored algebra	right triangle	metric angle chase	Pythagoras; Thales		RIGHT TRIANGLES
Algebra	Discrete functions, floors, rounding, and base representation	rounded/floor quantity	rounding		estimation	ROUNDING
Combinatorics; Number Theory	Algorithms, automata, words, and constructive combinatorics	schedule/order	greedy / exchange		optimization	SCHEDULING
Geometry	Circle geometry	Simson line	Simson line	Simson theorem	collinearity	SIMSON LINE
Geometry	3D and solid geometry	solid configuration	solid geometry			SOLID GEOMETRY
Combinatorics	Games, strategies, and processes	game	strategy		winning strategy	STRATEGY GAMES
Number Theory	Diophantine equations and descent	sum of two squares	descent / modular arithmetic	Fermat two-square theorem	classification	SUM OF TWO SQUARES
Algebra	Equations, substitutions, and transformations	system of equations	system transformation		solving / simplification	SYSTEMS
Algebra; Geometry	Analytic estimates and asymptotics	topological/continuity setup	topological argument		existence	TOPOLOGY

Area	Canonical Subtopic	Object tag	Technique tag	Lemma/Theorem tag	Proof role	Raw imported tag
Algebra	Equations, substitutions, and transformations	translation-invariant expression	translation invariance		invariant	TRANSLATION INVARIANCE
Geometry	Complex, trigonometric, and Fourier methods	trigonometric geometry	trigonometric method			TRIG GEOMETRY
Geometry	Geometry-flavored algebra	vector/complex configuration	vector method; complex method			VECTORS/COMPLEX
Geometry	Geometry-flavored algebra	3D vector configuration	vector method			3D VECTORS
Geometry	Transformational geometry	60-degree configuration	60-degree rotation			60-DEGREE ROTATION
Combinatorics; Geometry	Finite configurations and incidence geometry	arrangement of lines/objects	arrangement analysis			ARRANGEMENTS
Algebra	Polynomials and algebraic manipulation	binomial identity	algebraic identity	binomial theorem		BINOMIAL IDENTITIES
Algebra	Polynomials and algebraic manipulation	binomial sum	summation; coefficient extraction			BINOMIAL SUMS
Combinatorics	Graph theory	bipartite graph				BIPARTITE GRAPHS
Algebra	Polynomials and algebraic manipulation	Chebyshev polynomial		Chebyshev recurrence; Chebyshev trigonometric identity		CHEBYSHEV
Geometry	Circle geometry	circle configuration	circle chasing			CIRCLE CHASING
Geometry	Circle geometry	circle intersection				CIRCLE INTERSECTION
Geometry	Triangle centers and triangle configurations	circumcenter locus	locus method			CIRCUMCENTER LOCUS
Algebra	Algebraic structures and linear algebra	commutator				COMMUTATORS
Geometry	Geometry-flavored algebra	complex coordinate model	complex coordinates			COMPLEX COORDINATES
Algebra	Inequalities and optimization	constrained extremum	constrained optimization		optimization	CONSTRAINED OPTIMIZATION
Algebra	Sequences, recurrences, and series	cyclic sequence				CYCLIC SEQUENCES
Number Theory	Algebraic number theory flavor	cyclotomic factor	cyclotomic factorization	cyclotomic polynomial factorization		CYCLOTOMIC FACTORIZATION
Algebra	Discrete functions, floors, rounding, and base representation	binary/dyadic scale	dyadic decomposition			DYADIC DECOMPOSITION
Algebra	Algebraic structures and linear algebra	eigenvalue	spectral method			EIGENVALUES
Combinatorics	Pigeonhole, extremal principle, and averaging	exchangeable object	exchange argument		local improvement	EXCHANGE ARGUMENT
Algebra; Combinatorics	Functional equations	function				FUNCTIONS
Number Theory	Congruences and modular arithmetic	p-adic root	lifting	Hensel's lemma	lifting	HENSEL LIFTING
Combinatorics	Set systems, posets, and extremal set theory	hypergraph				HYPERGRAPHS
Geometry	Triangle centers and triangle configurations	incircle; excircle				INCIRCLE/EXCIRCLE
Geometry	Triangle centers and triangle configurations	isogonal conjugate	isogonal conjugation			ISOGONAL CONJUGATION
Geometry	Core Euclidean geometry	isosceles triangle	symmetry; angle chasing			ISOSCELES GEOMETRY
Geometry	Triangle centers and triangle configurations	nine-point center				NINE-POINT CENTER
Geometry	Triangle centers and triangle configurations	pedal triangle				PEDAL TRIANGLE
Number Theory	Divisibility, gcd, lcm, and primes	perfect square	square obstruction			PERFECT SQUARES
Geometry	Geometry-flavored algebra	projective coordinate model	projective coordinates			PROJECTIVE COORDINATES
Geometry	Geometry-flavored algebra	projective/coordinate model	projective coordinates; coordinate geometry			PROJECTIVE/COORDINATE GEOMETRY
Number Theory	Number-theoretic algebra	rationality condition	rationality criterion			RATIONALITY
Number Theory	Number-theoretic algebra	rational number				RATIONALS
Combinatorics	Graph theory	regular graph				REGULAR GRAPHS
Algebra	Polynomials and algebraic manipulation	resultant	resultant method			RESULTANTS
Algebra	Inequalities and optimization	sign pattern	sign analysis		case analysis	SIGN ANALYSIS
Geometry	Core Euclidean geometry	similar triangles	similarity	AA similarity; SAS similarity		SIMILAR TRIANGLES
Algebra; Combinatorics; Number Theory	General strategy and proof architecture	structural form	structural classification		classification	STRUCTURAL CLASSIFICATION
Geometry	Circle geometry	tangent lengths	equal tangents	equal tangent lengths		TANGENCY LENGTHS
Algebra	Inequalities and optimization	triangle variables	triangle substitution			TRIANGLE SUBSTITUTIONS
Combinatorics	Probability, entropy, coding, and information methods	variance	variance method; second moment			VARIANCE
Geometry	Transformational geometry	60-degree/equilateral configuration	rotation; angle chasing			60-DEGREE GEOMETRY
Algebra	Algebraic structures and linear algebra	additive subgroup				ADDITIVE SUBGROUPS
Combinatorics	Algorithms, automata, words, and constructive combinatorics	algorithm	algorithmic construction		construction	ALGORITHMS
Geometry	Triangle centers and triangle configurations	altitude foot				ALTITUDE FEET
Geometry	Core Euclidean geometry	angle condition	angle chasing			ANGLE CONDITION
Combinatorics; Geometry	Core Euclidean geometry	area	area bound		upper/lower bound	AREA BOUND
Geometry	Core Euclidean geometry	area	area chasing			AREA CHASING
Combinatorics	Set systems, posets, and extremal set theory	Boolean lattice				BOOLEAN LATTICE
Combinatorics	Coloring, tiling, grids, and invariants	cellular automaton	local transition analysis		invariant	CELLULAR AUTOMATA
Combinatorics	Combinatorial algebra and counting	charged object	charging; discharging		counting	CHARGING
Geometry	Circle geometry	circle-line intersection				CIRCLE-LINE INTERSECTIONS
Algebra; Combinatorics	Combinatorial algebra and counting	convolution	convolution method			CONVOLUTION
Geometry	Circle geometry	cyclic quadrilateral				CYCLIC QUADS
Combinatorics	Graph theory	graph diameter				DIAMETER
Combinatorics	Graph theory	directed cycle				DIRECTED CYCLES
Combinatorics; Geometry	Geometry-flavored algebra	dot product	vector method			DOT PRODUCTS
Combinatorics; Geometry	Projective and advanced geometry	dual object	duality			DUALITY
Combinatorics	Algorithms, automata, words, and constructive combinatorics	state/value table	dynamic programming		optimization	DYNAMIC PROGRAMMING
Geometry	Core Euclidean geometry	equal lengths	length chasing			EQUAL LENGTHS
Combinatorics	Graph theory	planar graph/polyhedron		Euler formula		EULER FORMULA
Geometry	Triangle centers and triangle configurations	excentral triangle; excenter				EXCENTRAL GEOMETRY
Algebra	Extremal methods, monotonicity, and invariants	distance	extremal distance		extremal choice	EXTREMAL DISTANCES
Algebra	Extremal methods, monotonicity, and invariants	extremal example	extremal construction		sharpness example	EXTREMAL EXAMPLES
Combinatorics	Graph theory	extremal graph	extremal graph argument		extremal choice	EXTREMAL GRAPH
Combinatorics	Pigeonhole, extremal principle, and averaging	sequence	extremal sequence		extremal choice	EXTREMAL SEQUENCE
Combinatorics; Geometry	Finite configurations and incidence geometry	finite configuration				FINITE CONFIGURATIONS
Number Theory	Diophantine equations and descent	numerical semigroup; coin representation		Frobenius coin theorem		FROBENIUS COIN PROBLEM
Algebra	Functional equations	iterated function	functional iteration			FUNCTIONAL ITERATION
Combinatorics	Graph theory	graph connectivity				GRAPH CONNECTIVITY
Combinatorics	Graph theory	graph model	graph modeling		modeling	GRAPH MODEL
Combinatorics	Graph theory	graph process	process analysis		invariant	GRAPH PROCESS
Combinatorics	Graph theory	graph representation	graph representation		modeling	GRAPH REPRESENTATION
Algebra	Algebraic structures and linear algebra	group action	group action			GROUP ACTION
Combinatorics	Graph theory	Hamiltonian path				HAMILTON PATHS
Combinatorics	Graph theory	Hamiltonian path				HAMILTONIAN PATHS
Geometry	Transformational geometry	homothety; inversion	homothety; inversion			HOMOTHETY/INVERSION
Algebra	Inequalities and optimization		Hölder inequality	Hölder inequality		H√ñLDER
Combinatorics; Geometry	Finite configurations and incidence geometry	incidence configuration	incidence counting			INCIDENCE
Geometry	Triangle centers and triangle configurations	incircle tangency point	equal tangents			INCIRCLE TANGENCY
Algebra; Number Theory	Diophantine equations and descent	integer constraint	descent		infinite descent	INTEGER CONSTRAINTS / DESCENT
Geometry	Transformational geometry	inversion; homothety	inversion; homothety			INVERSION/HOMOTHETY
Geometry	Transformational geometry	inversion; spiral similarity	inversion; spiral similarity			INVERSION/SPIRAL SIMILARITY
Geometry	Triangle centers and triangle configurations	isogonal lines	isogonal transformation			ISOGONAL LINES
Algebra	Algebraic structures and linear algebra	vector space over F2	linear algebra mod 2			LINEAR ALGEBRA MOD 2
Algebra	Functional equations	linear function	linearity forcing		rigidity	LINEARITY FORCING
Geometry	Core Euclidean geometry	midline; midsegment		midline theorem		MIDLINE
Geometry	Core Euclidean geometry	midpoint; midsegment		midpoint theorem		MIDPOINT THEOREM
Geometry	Triangle centers and triangle configurations	orthocenter configuration				ORTHOCENTER CONFIGURATION
Algebra	Equations, substitutions, and transformations	parameter	parametrization			PARAMETRIZATION
Combinatorics	Coloring, tiling, grids, and invariants	parity coloring	parity coloring		invariant	PARITY COLORING
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants	parity	parity invariant		invariant	PARITY INVARIANT
Geometry	Core Euclidean geometry	perpendicular lines	right-angle chasing			PERPENDICULARS
Geometry	Projective and advanced geometry	pole/polar	polar method	pole-polar theorem; La Hire theorem		POLARS
Algebra; Geometry; Number Theory	Number-theoretic algebra	power; exponent	exponentiation			POWERS
Geometry	Projective and advanced geometry	projective ratio; cross ratio	projective ratio chasing			PROJECTIVE RATIOS
Geometry	Geometry-flavored algebra	analytic/projective model	projective method; analytic coordinates			PROJECTIVE/ANALYTIC GEOMETRY
Geometry	Circle geometry	cyclic quadrilateral		Ptolemy theorem		PTOLEMY
Algebra	Functional equations	real function				REAL FUNCTIONS
Combinatorics	Algorithms, automata, words, and constructive combinatorics	reconstructible object	reconstruction		reconstruction	RECONSTRUCTION
Combinatorics; Number Theory	Pigeonhole, extremal principle, and averaging	record value	record argument		extremal choice	RECORDS
Geometry	Core Euclidean geometry	right angle	right-angle chasing			RIGHT ANGLES
Algebra; Combinatorics	Inequalities and optimization	sign pattern	sign analysis		case analysis	SIGN PATTERNS
Algebra	Equations, substitutions, and transformations	expression/equation	substitution; transformation			SUBSTITUTION / TRANSFORMATION
Algebra	Equations, substitutions, and transformations	expression/equation	transformation			TRANSFORMATIONS
Combinatorics; Geometry	Finite configurations and incidence geometry	triangulation	triangulation		decomposition	TRIANGULATION
Algebra	Inequalities and optimization	trigonometric inequality	trigonometric substitution; inequality method			TRIGONOMETRIC INEQUALITY
Algebra	Polynomials and algebraic manipulation	Vandermonde determinant; binomial sum		Vandermonde identity; Vandermonde determinant		VANDERMONDE
Geometry	Geometry-flavored algebra	vector/complex-number model	vector method; complex method			VECTORS/COMPLEX NUMBERS
Algebra; Combinatorics	Functional equations	additive relation	additivity			ADDITIVITY
Algebra	Algebraic structures and linear algebra	adjugate matrix		adjugate identity		ADJUGATE
Algebra; Geometry	Extremal methods, monotonicity, and invariants	affine structure	affine rigidity		rigidity	AFFINE RIGIDITY
Geometry	Geometry-flavored algebra	affine/vector model	affine coordinates; vector method			AFFINE/VECTOR GEOMETRY
Geometry	Circle geometry	Apollonius circle		Apollonius circle theorem		APOLLONIUS CIRCLE
Geometry	Core Euclidean geometry	area	area comparison			AREA COMPARISON
Combinatorics	Algorithms, automata, words, and constructive combinatorics	balance scale	weighing strategy		construction; information lower bound	BALANCE SCALE
Geometry	Geometry-flavored algebra	barycentric/coordinate model	barycentric coordinates; coordinate geometry			BARYCENTRIC/COORDINATE GEOMETRY
Combinatorics	Graph theory	BFS layer	BFS layering			BFS LAYERS
Algebra	Polynomials and algebraic manipulation	binomial expression	binomial expansion	binomial theorem		BINOMIAL EXPANSION
Algebra	Inequalities and optimization	boundary case	boundary analysis		equality/boundary case	BOUNDARY ANALYSIS
Algebra	Functional equations	Cauchy equation		Cauchy functional equation		CAUCHY EQUATION
Geometry	Core Euclidean geometry	cevian configuration	ratio chasing	Ceva theorem; Menelaus theorem		CEVA/MENELAUS
Geometry	Core Euclidean geometry	cevian				CEVIANS
Geometry	Circle geometry	chord length	chord-length chasing			CHORD LENGTHS
Geometry	Circle geometry	circle equation	coordinate circle equation			CIRCLE EQUATIONS
Algebra	Sequences, recurrences, and series	cyclic/circular sequence				CIRCULAR SEQUENCES
Geometry	Triangle centers and triangle configurations	circumcenter				CIRCUMCENTER GEOMETRY
Number Theory	Divisibility, gcd, lcm, and primes	consecutive product	factorization; divisibility			CONSECUTIVE PRODUCTS
Combinatorics	Pigeonhole, extremal principle, and averaging	extremal example	constructive lower bound		construction; lower bound	CONSTRUCTIVE LOWER BOUND
Geometry	Geometry-flavored algebra	convex configuration	convexity			CONVEX GEOMETRY
Combinatorics; Geometry	Finite configurations and incidence geometry	points in convex position	convex-position argument			CONVEX POSITION
Geometry	Geometry-flavored algebra	coordinate model	coordinate bash			COORDINATE BASH
Geometry	Geometry-flavored algebra	coordinate/complex model	coordinates; complex numbers			COORDINATES/COMPLEX
Geometry	Geometry-flavored algebra	coordinate/projective model	coordinates; projective coordinates			COORDINATES/PROJECTIVE
Algebra	Polynomials and algebraic manipulation	cubic identity	algebraic identity			CUBIC IDENTITY
Geometry	Circle geometry	cyclicity condition	cyclicity criterion; angle chasing			CYCLIC CONDITION
Geometry	Circle geometry	cyclic configuration				CYCLIC CONFIGURATIONS
Combinatorics	Combinatorial algebra and counting	cyclic order	cyclic counting			CYCLIC COUNTING
Combinatorics; Geometry	Circle geometry	cyclicity criterion	cyclicity criterion			CYCLIC CRITERION
Algebra	Inequalities and optimization	cyclic sum	cyclic estimates			CYCLIC ESTIMATES
Geometry	Circle geometry	diameter circle		Thales theorem		DIAMETER CIRCLES
Algebra	Functional equations	differentiable function	differentiability argument			DIFFERENTIABILITY
Combinatorics; Number Theory	Algorithms, automata, words, and constructive combinatorics	encoding scheme	encoding		encoding	ENCODING
Geometry	Circle geometry	equal circles	symmetry; metric comparison			EQUAL CIRCLES
Geometry	Transformational geometry	equilateral configuration	60-degree rotation			EQUILATERAL ROTATION
Geometry	Transformational geometry	equilateral triangle	rotation; complex numbers			EQUILATERAL TRIANGLE
Geometry	Transformational geometry	equilateral triangles	rotation; complex numbers			EQUILATERAL TRIANGLES
Algebra; Number Theory	Divisibility, gcd, lcm, and primes	exponent vector	prime-exponent vectorization			EXPONENT VECTORS
Algebra	Extremal methods, monotonicity, and invariants	extremal construction	extremal construction		construction; sharpness	EXTREMAL CONSTRUCTIONS
Algebra	Extremal methods, monotonicity, and invariants	extremal object	extremal choice		contradiction	EXTREMAL CONTRADICTION
Algebra; Geometry	Extremal methods, monotonicity, and invariants	distance	extremal distance		extremal choice	EXTREMAL DISTANCE
Algebra	Inequalities and optimization	inequality	extremal inequality		upper/lower bound	EXTREMAL INEQUALITIES
Algebra	Inequalities and optimization	inequality	extremal inequality		upper/lower bound	EXTREMAL INEQUALITY
Algebra	Extremal methods, monotonicity, and invariants	extremal object	extremal strategy		extremal choice	EXTREMAL STRATEGY
Algebra	Extremal methods, monotonicity, and invariants	sum	extremal sum argument		extremal bound	EXTREMAL SUMS
Algebra; Combinatorics	Pigeonhole, extremal principle, and averaging	extremal object	extremal pigeonhole		contradiction	EXTREMAL/PIGEONHOLE
Combinatorics; Geometry	Coloring, tiling, grids, and invariants	finite coloring	coloring		invariant	FINITE COLORING
Algebra	Algebraic structures and linear algebra	generator				GENERATORS
Combinatorics	Graph theory	graph	graph construction		construction	GRAPH CONSTRUCTION
Combinatorics	Graph theory	graph cut	cut argument			GRAPH CUTS
Combinatorics	Graph theory	graph decomposition	graph decomposition		decomposition	GRAPH DECOMPOSITION
Combinatorics	Graph theory	independent set	independence argument			GRAPH INDEPENDENCE
Combinatorics	Graph theory	grid graph				GRID GRAPHS
Combinatorics	Coloring, tiling, grids, and invariants	grid packing	packing argument		lower/upper bound	GRID PACKING
Algebra	Algebraic structures and linear algebra	group action	group action			GROUP ACTIONS
Combinatorics	Graph theory	matching	matching argument	Hall's theorem	existence criterion	HALL
Combinatorics	Graph theory	Hamiltonian cycle				HAMILTON CYCLES
Geometry	Geometry-flavored algebra	triangle area		Heron's formula		HERON FORMULA
Geometry	Transformational geometry	homothety; spiral similarity	homothety; spiral similarity			HOMOTHETY/SPIRAL SIMILARITY
Combinatorics	Graph theory	hypercube				HYPERCUBE
Algebra	Algebraic structures and linear algebra	idempotent				IDEMPOTENTS
Geometry	Triangle centers and triangle configurations	incircle contact triangle				INCIRCLE CONTACT TRIANGLE
Geometry; Number Theory	Triangle centers and triangle configurations	inradius				INRADIUS
Geometry	Triangle centers and triangle configurations	intouch triangle				INTOUCH TRIANGLE
Geometry	Triangle centers and triangle configurations	isogonal configuration	isogonal conjugation			ISOGONAL GEOMETRY
Geometry	Triangle centers and triangle configurations	symmedian; isogonal line	isogonal method; symmedian method			ISOGONAL/SYMMEDIAN
Geometry	Core Euclidean geometry	length	length chasing			LENGTH CHASING
Number Theory	Congruences and modular arithmetic	congruence solution	lifting		lifting	LIFTING
Algebra	Equations, substitutions, and transformations	linear equation				LINEAR EQUATIONS
Algebra	Sequences, recurrences, and series	linear recurrence				LINEAR RECURRENCE
Geometry	Loci and constructions	locus	locus method			LOCI
Combinatorics	Pigeonhole, extremal principle, and averaging		lower-bound argument		lower bound	LOWER BOUND
Combinatorics; Geometry	Triangle centers and triangle configurations	median				MEDIAN
Geometry	Core Euclidean geometry	metric identity	length chasing; metric comparison			METRIC IDENTITY
Algebra; Number Theory	Inequalities and optimization	moment	moment method			MOMENTS
Algebra	Sequences, recurrences, and series	monotone sequence	monotonicity			MONOTONE SEQUENCES
Algebra	Algebraic structures and linear algebra	nilpotent				NILPOTENTS
Algebra; Combinatorics	Pigeonhole, extremal principle, and averaging	order statistic	ordering; ranking			ORDER STATISTICS
Geometry	Triangle centers and triangle configurations	orthocenter				ORTHOCENTRE
Geometry	Core Euclidean geometry	parallel lines	parallel chasing			PARALLELISM
Geometry	Core Euclidean geometry	perpendicular bisector				PERPENDICULAR BISECTOR
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants	perturbed object	perturbation		local adjustment	PERTURBATION
Geometry	Projective and advanced geometry	polarity	pole-polar transformation	La Hire theorem		POLARITY
Algebra	Polynomials and algebraic manipulation	polynomial divisibility	factor/divisibility argument			POLYNOMIAL DIVISIBILITY
Algebra; Number Theory	Equations, substitutions, and transformations	product expression	product trick		transformation	PRODUCT TRICK
Geometry	Projective and advanced geometry	pole/polar	projective-polar method	pole-polar theorem		PROJECTIVE/POLAR FLAVOR
Combinatorics	Counting and enumerative combinatorics	q-binomial coefficient	q-analog counting	Gaussian binomial identity		Q-BINOMIAL COEFFICIENTS
Number Theory	Congruences and modular arithmetic	quadratic residue		quadratic reciprocity		QUADRATIC RECIPROCITY
Algebra	Polynomials and algebraic manipulation	quadratic polynomial; quadratic equation				QUADRATICS
"""


PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE = r"""
Area	Canonical Subtopic	Object tag	Technique tag	Lemma/Theorem tag	Proof role	Raw imported tag
Algebra	Extremal methods, monotonicity, and invariants	sequence/process	greedy descent		descent	GREEDY DESCENT
Combinatorics	Greedy algorithms and constructive combinatorics	packing configuration	greedy packing		construction	GREEDY PACKING
Algebra	Sequences, recurrences, and series	sequence	greedy construction		construction	GREEDY SEQUENCES
Combinatorics	Algorithms, automata, words, and constructive combinatorics	state/process	greedy; dynamic programming		optimization	GREEDY/DP
Algebra	Extremal methods, monotonicity, and invariants	process	greedy; invariant		invariant	GREEDY/INVARIANT
Combinatorics	Coloring, tiling, grids, and invariants	grid				GRID
Combinatorics	Graph theory	grid graph	domination		covering	GRID DOMINATION
Combinatorics	Coloring, tiling, grids, and invariants	grid process	dynamics		process invariant	GRID DYNAMICS
Combinatorics	Combinatorial games and strategies	grid game	strategy		game strategy	GRID GAME
Combinatorics	Geometric combinatorics	grid geometry	coordinate/grid method			GRID GEOMETRY
Combinatorics	Coloring, tiling, grids, and invariants	grid tiling	coloring invariant		construction/obstruction	GRID TILING
Algebra	Algebraic structures and linear algebra	group	structural analysis		classification	GROUP STRUCTURE
Number Theory	Algebraic number theory and modular structures	group	group theory		structure	GROUP THEORY
Algebra	Extremal methods, monotonicity, and invariants	growth sequence/function	growth comparison		estimate	GROWTH COMPARISON
Algebra	Extremal methods, monotonicity, and invariants	monotone growth	monotonicity		estimate	GROWTH/MONOTONICITY
Geometry	Trigonometric geometry	triangle angle	half-angle substitution	half-angle identities	computation	HALF-ANGLE
Geometry	Trigonometric geometry	triangle angle	half-angle identities	half-angle identities	computation	HALF-ANGLE IDENTITIES
Algebra	Complex, trigonometric, and Fourier methods	trigonometric expression	half-angle trig		transformation	HALF-ANGLE TRIG
Combinatorics; Number Theory	Matching, transversals, and covering	matching/transversal	Hall-type argument	Hall	existence proof	HALL-TYPE ARGUMENT
Combinatorics	Matching, transversals, and covering	matching/transversal	Hall-type condition	Hall	existence condition	HALL-TYPE CONDITION
Combinatorics	Combinatorial algebra and counting	bipartite matching	matching method	Hall	existence proof	HALL/MATCHING
Combinatorics	Graph theory	Hamiltonian cycle	graph traversal		construction/existence	HAMILTONIAN CYCLES
Combinatorics	Probability, entropy, coding, and information methods	Hamming ball	coding bound		bound	HAMMING BALLS
Combinatorics	Probability, entropy, coding, and information methods	Hamming cube	coding/Boolean cube method		structure	HAMMING CUBE
Algebra; Combinatorics	Inequalities and estimates	harmonic sum	harmonic bound		upper/lower bound	HARMONIC BOUND
Combinatorics	Convexity, Helly, and intersection methods	set family	intersection method	Helly	existence/obstruction	HELLY PROPERTY
Number Theory	Divisibility, gcd, lcm, and primes	highly composite number	divisor-count structure		classification	HIGHLY COMPOSITE NUMBERS
Number Theory	Divisibility, gcd, lcm, and primes	highly composite number	structural decomposition		classification	HIGHLY COMPOSITE STRUCTURE
Algebra	Inequalities and estimates	homogeneous expression	homogenization/estimate		estimate	HOMOGENEOUS ESTIMATES
Geometry	Projective and advanced geometry	projective map	homography		transformation	HOMOGRAPHY
Geometry	Transformational geometry	homothety center	homothety		transformation	HOMOTHETY CENTER
Geometry	Transformational geometry	homothety configuration	homothety		transformation	HOMOTHETY ABOUT GGG
Geometry	Transformational geometry	homothety configuration	homothety		transformation	HOMOTHETY AT HHH
Geometry	Geometry-flavored algebra	homothety configuration	homothety; coordinates		computation	HOMOTHETY/COORDINATES
Geometry	Transformational geometry	symmetric homothety configuration	homothety; symmetry		transformation	HOMOTHETY/SYMMETRY
Geometry	Circle geometry	tangent homothety configuration	homothety; tangency		transformation	HOMOTHETY/TANGENCY
Algebra	Algebraic structures and linear algebra	ideal	ideal method		structure	IDEALS
Geometry	Logical conditions in geometry	equivalence condition	iff reformulation		condition	IFF
Geometry	Logical conditions in geometry	equivalence condition	iff reformulation		condition	IFF CONDITION
Geometry	Triangle centers and triangle configurations	incenter	formula use	incenter formulas	computation	INCENTER FORMULAS
Geometry	Triangle centers and triangle configurations	incenter/incircle	angle/tangent chasing		configuration	INCENTER/INCIRCLE
Geometry	Triangle centers and triangle configurations	incenter/excenter	angle/tangent chasing		configuration	INCENTERS/EXCENTERS
Combinatorics	Incidence combinatorics	incidence structure	incidence bound		bound	INCIDENCE BOUNDS
Combinatorics	Combinatorial algebra and counting	incidence graph	graph encoding		model	INCIDENCE GRAPH
Geometry	Circle geometry	incircle touchpoint	tangent lengths		configuration	INCIRCLE TOUCHPOINT
Geometry	Circle geometry	incircle tangent lengths	tangent-length method		computation	INCIRCLE/TANGENT LENGTHS
Algebra	Induction, recursion, and compression	algebraic structure	induction; compression		reduction	INDUCTION/COMPRESSION
Combinatorics	Coloring, tiling, grids, and invariants	infinite coloring	coloring argument		construction/obstruction	INFINITE COLORING
Algebra	Extremal methods, monotonicity, and invariants	generated sequence/process	infinite descent/generation		descent	INFINITE DESCENT/GENERATION
Combinatorics	Graph theory	infinite graph	graph method		existence/structure	INFINITE GRAPH
Combinatorics	Graph theory	infinite path	path construction		existence	INFINITE PATHS
Combinatorics; Number Theory	Infinite sets and density	infinite set	infinite set method		existence	INFINITE SETS
Combinatorics	Games, strategies, and information	information state	information strategy		strategy	INFORMATION STRATEGY
Algebra	Functions and maps	map/function	injectivity; specialization		proof by injectivity	INJECTIVITY/SPECIALIZATION
Algebra	Functions and maps	map/function	injectivity/surjectivity check		trap/obstruction	INJECTIVITY/SURJECTIVITY TRAPS
Geometry	Metric geometry	triangle incircle	inradius formula	inradius formula	computation	INRADIUS FORMULA
Algebra	Polynomials and algebraic manipulation	integer-coefficient polynomial	coefficient comparison		structure	INTEGER COEFFICIENTS
Algebra	Polynomials and algebraic manipulation	integer polynomial/factorization	factorization		reduction	INTEGER FACTORIZATION
Geometry	Geometry-flavored algebra	integer lattice	lattice method		model	INTEGER LATTICE
Geometry; Number Theory	Integer optimization and lattice methods	integer point/configuration	optimization		extremal	INTEGER OPTIMIZATION
Algebra	Extremal methods, monotonicity, and invariants	integer-valued structure	rigidity		rigidity	INTEGER RIGIDITY
Algebra; Combinatorics	Additive/combinatorial algebra	integer set	set method		structure	INTEGER SETS
Number Theory	Number-theoretic algebra	integer-valued expression	integrality		obstruction	INTEGER VALUES
Algebra	Polynomials and algebraic manipulation	integer-valued polynomial	finite differences/interpolation		structure	INTEGER-VALUED POLYNOMIALS
Algebra	Number-theoretic algebra	integers	integrality		structure	INTEGERS
Algebra	Inequalities and optimization	integral expression	integral inequality		estimate	INTEGRAL INEQUALITIES
Combinatorics	Covering and hitting	intervals	hitting set		covering	INTERVAL HITTING
Algebra	Functions and maps	interval image	interval mapping		range control	INTERVAL IMAGES
Algebra; Number Theory	Intervals and order methods	intervals	interval intersection		existence	INTERVAL INTERSECTION
Algebra	Extremal methods, monotonicity, and invariants	invariant polynomial	polynomial invariant		invariant	INVARIANT POLYNOMIALS
Algebra	Extremal methods, monotonicity, and invariants	rewrite system	invariant		invariant/termination	INVARIANTS/REWRITE SYSTEMS
Geometry	Projective and advanced geometry	inversion centered at A	inversion		transformation	INVERSION AT AAA
Geometry	Projective and advanced geometry	inversive/projective configuration	inversion; projective method		transformation	INVERSION/PROJECTIVE
Geometry	Projective and advanced geometry	inversive/projective configuration	inversion; projective geometry		transformation	INVERSION/PROJECTIVE GEOMETRY
Geometry	Transformational geometry	similarity configuration	inversion; similarity		transformation	INVERSION/SIMILARITY
Geometry	Transformational geometry	inversive configuration	inversion		transformation	INVERSIVE GEOMETRY
Geometry	Geometry-flavored algebra	irrational rotation orbit	rotation/density	Kronecker-type density	existence/density	IRRATIONAL ROTATIONS
Geometry	Transformational geometry	isogonal reflection	isogonal reflection		transformation	ISOGONAL REFLECTION
Geometry	Triangle centers and triangle configurations	isogonal lines	isogonal relations		configuration	ISOGONAL RELATIONS
Geometry	Projective and advanced geometry	isogonal/projective configuration	isogonal; projective method		transformation	ISOGONAL/PROJECTIVE
Geometry	Triangle centers and triangle configurations	isogonals	isogonal conjugation/reflection		configuration	ISOGONALS
Geometry	Special configurations and special angles	isosceles triangle	angle chase		computation	ISOSCELES ANGLE CHASE
Geometry	Triangle centers and triangle configurations	isosceles triangle	symmetry		configuration	ISOSCELES TRIANGLES
Algebra	Extremal methods, monotonicity, and invariants	convex/concave expression	Jensen-type rigidity	Jensen	equality/rigidity	JENSEN-TYPE RIGIDITY
Algebra; Geometry	Inequalities and convexity	concave function/configuration	Jensen; concavity	Jensen	estimate	JENSEN/CONCAVITY
Combinatorics	Combinatorial algebra and counting	Johnson graph	graph encoding		structure	JOHNSON GRAPH
Algebra	Density and approximation	orbit/sequence	Kronecker density	Kronecker	density	KRONECKER/DENSITY
Geometry	Geometry-flavored algebra	lattice polygon/region	area method	Pick-type theorem	computation	LATTICE AREA
Combinatorics	Coloring, tiling, grids, and invariants	lattice coloring	coloring invariant		invariant	LATTICE COLORING
Geometry	Geometry-flavored algebra	lattice set	compression		reduction	LATTICE COMPRESSION
Geometry	Geometry-flavored algebra	lattice points	distance analysis		metric constraint	LATTICE DISTANCES
Geometry	Geometry-flavored algebra	lattice points	parity		invariant	LATTICE PARITY
Geometry	Geometry-flavored algebra	lattice path	path counting/geometry		construction/counting	LATTICE PATH
Geometry	Geometry-flavored algebra	lattice points	lattice method		counting/structure	LATTICE POINTS
Combinatorics	Combinatorial algebra and counting	lattice walk	walk counting		counting	LATTICE WALKS
Geometry	Core Euclidean geometry	triangle sides/angles	sine rule	Law of Sines	computation	LAW OF SINES
Combinatorics	Covering and hitting	line cover	covering argument		covering	LINE COVERS
Geometry	Core Euclidean geometry	line intersection	incidence/angle chase		configuration	LINE INTERSECTION
Combinatorics	Algebraic combinatorics and linear algebra	vector space over F_2	linear algebra over F_2		invariant/model	LINEAR ALGEBRA OVER F2\MATHBB F_2F2‚Äã
Combinatorics	Algebraic combinatorics and linear algebra	integer lattice/module	linear algebra over integers		invariant/model	LINEAR ALGEBRA OVER INTEGERS
Algebra	Linear methods	linear relation	forcing		forcing	LINEAR FORCING
Combinatorics	Optimization and extremal methods	feasible polytope	linear programming flavor		optimization/bound	LINEAR PROGRAMMING FLAVOR
Algebra	Equations and systems	linear solution	solving linear system		computation	LINEAR SOLUTIONS
Algebra	Algebraic structures and linear algebra	linear map	linear transformation		transformation	LINEAR TRANSFORMATIONS
Algebra	Sequences, recurrences, and series	recurrence/sum	linearization; telescoping		reduction	LINEARIZATION / TELESCOPING
Combinatorics	Local-to-global methods	forbidden pattern	local obstruction		obstruction	LOCAL FORBIDDEN PATTERNS
Combinatorics	Processes and invariants	local move	local transformation		invariant/termination	LOCAL MOVES
Combinatorics	Local-to-global methods	constraint system	propagation		local-to-global	LOCAL-TO-GLOBAL CONSTRAINTS
Algebra	Equations, substitutions, and transformations	logarithmic expression	logarithmic substitution		transformation	LOGARITHMIC SUBSTITUTION
Combinatorics	Games, strategies, and processes	maker-breaker game	strategy		game strategy	MAKER-BREAKER
Algebra; Number Theory	Diophantine equations	Markov-type equation	Vieta jumping/descent	Markov-type equation	descent	MARKOV-TYPE EQUATION
Combinatorics	Combinatorial algebra and counting	matching/packing	matching/packing	Hall	construction/existence	MATCHING/PACKING
Combinatorics	Graph theory	flow network/cut	max-flow min-cut	Max-flow/min-cut	optimization	MAX-FLOW/MIN-CUT
Algebra; Combinatorics	Tropical/min-plus methods	max-plus expression	max-plus algebra		optimization	MAX-PLUS ALGEBRA
Geometry	Metric geometry	median length	median formula	Apollonius median formula	computation	MEDIAN FORMULA
Number Theory	Divisibility, gcd, lcm, and primes	Mersenne number	divisibility/order method		structure	MERSENNE NUMBERS
Geometry	Metric geometry	angle/length configuration	metric angle chasing		computation	METRIC ANGLE CHASING
Algebra	Extremal methods, monotonicity, and invariants	metric configuration	extremal metric method		extremal	METRIC EXTREMAL
Algebra	Inequalities and optimization	metric expression	metric inequality		bound	METRIC INEQUALITIES
Algebra; Combinatorics	Metric and distance methods	metric space/graph	metric structure		structure	METRIC STRUCTURE
Geometry	Core Euclidean geometry	midpoint relation	midpoint method		configuration	MIDPOINT RELATION
Geometry	Transformational geometry	midpoint/reflection	reflection		transformation	MIDPOINT/REFLECTION
Combinatorics	Algorithms and optimization	sequence/array	min-plus convolution		optimization	MIN-PLUS CONVOLUTION
Combinatorics	Covering and hitting	transversal	minimal transversal		minimality	MINIMAL TRANSVERSALS
Algebra	Extremal methods, monotonicity, and invariants	extremal structure	minimax		extremal	MINIMAX STRUCTURE
Geometry	Circle geometry	Miquel/Reim configuration	cyclic angle chase	Miquel; Reim	configuration	MIQUEL / REIM
Geometry	Circle geometry	Miquel circle	Miquel configuration	Miquel	configuration	MIQUEL CIRCLES
Geometry	Circle geometry	Miquel configuration	Miquel method	Miquel	configuration	MIQUEL CONFIGURATION
Geometry	Circle geometry	Miquel point/circle	Miquel geometry	Miquel	configuration	MIQUEL GEOMETRY
Geometry	Circle geometry	Miquel point	cyclic angle chase	Miquel	configuration	MIQUEL POINTS
Geometry	Circle geometry	Miquel-style configuration	Miquel method	Miquel	configuration	MIQUEL-STYLE CONFIGURATION
Geometry	Circle geometry	cyclic Miquel configuration	Miquel; cyclicity	Miquel	configuration	MIQUEL/CYCLIC
Algebra	Algebraic structures and linear algebra	module/vector space mod n	modular linear algebra		invariant/model	MODULAR LINEAR ALGEBRA
Algebra	Extremal methods, monotonicity, and invariants	monotone array	monotonicity		invariant	MONOTONE ARRAYS
Combinatorics	Processes and constructive combinatorics	motion plan	constructive strategy		construction	MOTION PLANNING
Geometry	Locus and moving-point geometry	moving point locus	locus method		locus	MOVING POINT LOCUS
Geometry	Locus and moving-point geometry	moving point	continuity/locus		configuration	MOVING POINTS
Combinatorics	Combinatorial algebra and counting	multipartite graph	graph decomposition		structure	MULTIPARTITE GRAPHS
Combinatorics	Graph theory	nearest-neighbor relation	extremal graph method		structure	NEAREST NEIGHBORS
Combinatorics	Combinatorial algebra and counting	nearest-neighbor graph	graph encoding		structure	NEAREST-NEIGHBOR GRAPHS
Combinatorics	Counting and enumerative combinatorics	necklace	Burnside/cyclic counting	Burnside, if used	counting	NECKLACES
Algebra; Number Theory	Intervals and order methods	nested intervals	nested interval method		existence	NESTED INTERVALS
Geometry	Triangle centers and triangle configurations	nine-point center	center geometry	Nine-point circle	configuration	NINE-POINT CENTERS
Combinatorics	Noncrossing and planar combinatorics	noncrossing chords	planar order		structure	NONCROSSING CHORDS
Combinatorics	Noncrossing and planar combinatorics	noncrossing diagonals	planar order		structure	NONCROSSING DIAGONALS
Combinatorics	Combinatorial algebra and counting	noncrossing matching	Catalan/noncrossing method		counting/construction	NONCROSSING MATCHINGS
Geometry	Geometry-flavored algebra	oblique coordinate system	coordinate method		computation	OBLIQUE COORDINATES
Combinatorics	Graph theory	graph with odd girth	extremal graph method		obstruction/bound	ODD GIRTH
Algebra	Analytic estimates and asymptotics	one-sided derivative	derivative estimate		estimate	ONE-SIDED DERIVATIVE
Algebra	Inequalities and optimization	one-variable expression	one-variable reduction		optimization	ONE-VARIABLE INEQUALITY
Combinatorics	Online algorithms and strategies	covering process	online covering		strategy	ONLINE COVERING
Combinatorics	Online algorithms and strategies	online process	online strategy		strategy	ONLINE STRATEGY
Algebra	Extremal methods, monotonicity, and invariants	orbit	orbit rigidity		rigidity	ORBIT RIGIDITY
Algebra	Extremal methods, monotonicity, and invariants	ordered structure	order relation		monotonicity	ORDER RELATIONS
Algebra	Order and lattice methods	ordered structure	order method		structure	ORDER STRUCTURE
Geometry	Triangle centers and triangle configurations	orthic feet	orthic triangle method		configuration	ORTHIC FEET
Geometry	Triangle centers and triangle configurations	orthocenter circle	orthocenter/circle method		configuration	ORTHOCENTER CIRCLE
Geometry	Triangle centers and triangle configurations	orthocenter/circumcenter	center geometry		configuration	ORTHOCENTER/CIRCUMCENTER GEOMETRY
Geometry	Core Euclidean geometry	orthogonal diagonals	perpendicularity method		configuration	ORTHOGONAL DIAGONALS
Geometry	Geometry-flavored algebra	orthogonal polygon	coordinate/area method		structure	ORTHOGONAL POLYGONS
Geometry	Triangle centers and triangle configurations	orthogonal projection	projection method		transformation	ORTHOGONAL PROJECTIONS
Algebra	Algebraic structures and linear algebra	p-group	group structure		classification	P-GROUPS
Combinatorics	Combinatorial algebra and counting	pair	double counting		counting	PAIR COUNTING
Combinatorics	Combinatorial algebra and counting	paired objects	pairing argument		involution/pairing	PAIRING ARGUMENT
Number Theory	Base, digit, and automata number theory	palindrome	digit/base method		construction/obstruction	PALINDROMES
Combinatorics	Graph theory	pancyclic graph	cycle method		existence	PANCYCLICITY
Geometry	Circle geometry	parallel chord	angle/cyclic method	parallel chord theorem	configuration	PARALLEL CHORD
Geometry	Circle geometry	parallel chords	angle/cyclic method	parallel chord theorem	configuration	PARALLEL CHORDS
Algebra; Combinatorics	Algebraic/combinatorial structure	parallel class	partition into classes		structure	PARALLEL CLASSES
Geometry	Core Euclidean geometry	parallel lines	parallel condition		condition	PARALLEL CONDITION
Geometry	Projective and affine geometry	parallel projection	affine/projective projection		transformation	PARALLEL PROJECTION
Geometry	Core Euclidean geometry	parallelogram	vector/parallel method		configuration	PARALLELOGRAMS
Combinatorics	Coloring, tiling, grids, and invariants	parity constraint	parity		invariant/obstruction	PARITY CONSTRAINTS
Number Theory	Multiplicative functions and factorization	omega function/parity	parity of omega		invariant	PARITY OF Œ©
Combinatorics	Coloring, tiling, grids, and invariants	parity state	parity strategy		strategy	PARITY STRATEGY
Combinatorics; Geometry	Coloring, tiling, grids, and invariants	parity construction	parity		construction	PARITY/CONSTRUCTION
Algebra	Extremal methods, monotonicity, and invariants	parity state	parity invariant		invariant	PARITY/INVARIANT
Combinatorics	Combinatorial algebra and counting	involution pair	parity; involution		involution	PARITY/INVOLUTION
Number Theory	Number-theoretic algebra	square/parity	parity of squares		obstruction	PARITY/SQUARES
Combinatorics	Topological/combinatorial parity	parity/topology object	parity; topology		obstruction	PARITY/TOPOLOGY
Combinatorics	Graph theory	path cover	covering argument		covering	PATH COVERS
Combinatorics	Combinatorial algebra and counting	path graph	graph encoding		structure	PATH GRAPH
Combinatorics	Algorithms, automata, words, and constructive combinatorics	forbidden pattern	pattern avoidance		construction/obstruction	PATTERN AVOIDANCE
Geometry	Circle geometry	pedal circle	pedal geometry	Simson, if used	configuration	PEDAL CIRCLE
Geometry	Circle geometry	pedal circles	pedal geometry	Simson, if used	configuration	PEDAL CIRCLES
Geometry	Triangle centers and triangle configurations	pedal configuration	pedal geometry		configuration	PEDAL GEOMETRY
Geometry	Triangle centers and triangle configurations	pedal/Simson configuration	pedal method	Simson line	configuration	PEDAL/SIMSON FLAVOR
Geometry	Geometric inequalities and optimization	perimeter	perimeter inequality		bound	PERIMETER INEQUALITIES
Algebra	Inequalities and optimization	perimeter expression	inequality		bound	PERIMETER INEQUALITY
Combinatorics	Coloring, tiling, grids, and invariants	periodic coloring	coloring invariant		construction	PERIODIC COLORINGS
Algebra; Geometry	Core Euclidean geometry	perpendicular diagonals	perpendicularity; algebraic method		configuration	PERPENDICULAR DIAGONALS
Algebra; Number Theory	Casework and piecewise methods	piecewise expression	piecewise analysis		casework	PIECEWISE ANALYSIS
Geometry	Circle geometry	tangential quadrilateral	tangent-length method	Pitot theorem	computation	PITOT THEOREM
Combinatorics; Geometry	Arrangements and incidence geometry	planar arrangement	planar decomposition		structure/counting	PLANAR ARRANGEMENTS
Combinatorics	Combinatorial algebra and counting	planar matching	noncrossing/planar matching		construction	PLANAR MATCHING
Combinatorics	Planar and geometric combinatorics	planar order	cyclic/linear order		structure	PLANAR ORDER
Combinatorics; Geometry	Planar and geometric combinatorics	planar structure	planar graph/geometry method		structure	PLANAR STRUCTURE
Combinatorics; Geometry	Planar graph theory	planar triangulation	triangulation	Euler formula, if used	structure	PLANAR TRIANGULATION
Geometry	Core Euclidean geometry	plane angle	angle chase		computation	PLANE ANGLE
Geometry	3D and solid geometry	plane section	section method		construction	PLANE SECTIONS
Combinatorics	Probability, entropy, coding, and information methods	code	coding bound	Plotkin bound	bound	PLOTKIN BOUND
Combinatorics	Extremal and geometric combinatorics	point set	extremal/incidence method		structure	POINT SETS
Geometry	Projective and advanced geometry	pole-polar configuration	polar method	pole-polar theorem	transformation	POLAR GEOMETRY
Geometry	Projective and advanced geometry	pole-polar configuration	projective method	pole-polar theorem	transformation	POLE-POLAR/PROJECTIVE
Geometry	Geometry-flavored algebra	polygon	classification		classification	POLYGON CLASSIFICATION
Geometry	Geometry-flavored algebra	polygonal chain	closure condition		existence	POLYGON CLOSURE
Geometry	Geometry-flavored algebra	polygonal path	path/coordinate method		construction	POLYGONAL PATHS
Algebra	Polynomials and algebraic manipulation	polynomial coefficient FE	coefficient comparison		functional equation	POLYNOMIAL / COEFFICIENT FE
Algebra	Polynomials and algebraic manipulation	polynomial composition	composition method		structure	POLYNOMIAL COMPOSITION
Algebra	Algebraic structures and linear algebra	polynomial ideal	ideal method		structure	POLYNOMIAL IDEALS
Algebra	Inequalities and optimization	polynomial expression	polynomial inequality		bound	POLYNOMIAL INEQUALITIES
Algebra	Polynomials and algebraic manipulation	polynomial inequality	polynomial method		bound	POLYNOMIAL INEQUALITY
Algebra	Polynomials and algebraic manipulation	polynomial invariant	invariant polynomial method		invariant	POLYNOMIAL INVARIANTS
Algebra	Polynomials and algebraic manipulation	polynomial recurrence	recurrence method		recurrence	POLYNOMIAL RECURRENCE
Algebra	Polynomials and algebraic manipulation	polynomial	rigidity		rigidity	POLYNOMIAL RIGIDITY
Algebra	Polynomials and algebraic manipulation	polynomial-like behavior	polynomial method		structure	POLYNOMIAL-TYPE BEHAVIOR
Combinatorics	Coloring, tiling, grids, and invariants	polyomino	tiling method		construction/obstruction	POLYOMINOES
Combinatorics	Set systems, posets, and extremal set theory	poset	chain/antichain decomposition	Dilworth; Mirsky	decomposition	POSETS/DILWORTH‚ÄìMIRSKY
Algebra	Algebraic structures and linear algebra	positive definite matrix	quadratic form/matrix method		positivity	POSITIVE DEFINITE MATRICES
Geometry	Circle geometry	power of a point	power method	Power of a Point	computation	POWER
Algebra	Inequalities and optimization	mean	power means	Power Mean inequality	estimate	POWER MEANS
Combinatorics; Number Theory	Divisibility and exponential structure	powers of 3	modular/order method		structure	POWERS OF 3
Number Theory	Divisibility, gcd, lcm, and primes	practical number	divisor-sum structure		classification	PRACTICAL NUMBERS
Combinatorics	Probability, entropy, coding, and information methods	prefix code	coding/entropy method	Kraft inequality, if used	construction/bound	PREFIX CODES
Algebra; Number Theory	Number-theoretic algebra	primitive element/value	primitive divisor/primitive root method		structure	PRIMITIVES
Geometry	3D and solid geometry	prism	solid geometry		configuration	PRISM GEOMETRY
Combinatorics	Processes and invariants	process	process analysis		process	PROCESS
Algebra	Extremal methods, monotonicity, and invariants	process	invariant		invariant	PROCESS INVARIANT
Algebra	Extremal methods, monotonicity, and invariants	process	invariant		invariant	PROCESS/INVARIANT
Algebra	Inequalities and estimates	product expression	product estimate		estimate	PRODUCT ESTIMATE
Combinatorics; Number Theory	Multiplicative identities and counting	product identity	algebraic/product identity		identity	PRODUCT IDENTITIES
Combinatorics	Set systems, posets, and extremal set theory	product of chains	poset method		structure	PRODUCT OF CHAINS
Geometry	Geometry-flavored algebra	projected coordinate system	projection; coordinates		transformation/computation	PROJECTION/COORDINATES
Geometry	Transformational geometry	reflected projection	projection; reflection		transformation	PROJECTION/REFLECTION
Geometry	Projective and advanced geometry	projective configuration	projective method		configuration	PROJECTIVE CONFIGURATION
Geometry	Projective and advanced geometry	projective involution	involution	Projective involution	transformation	PROJECTIVE INVOLUTION
Geometry	Projective and advanced geometry	projective parametrization	parametrization		computation	PROJECTIVE PARAMETRIZATION
Geometry	Projective and advanced geometry	projective-flavored configuration	projective method		configuration	PROJECTIVE-FLAVORED CONFIGURATION
Geometry	Projective and affine geometry	affine/projective configuration	projective/affine method		transformation	PROJECTIVE/AFFINE
Geometry	Projective and advanced geometry	concurrency configuration	projective method	Desargues/Ceva, if used	concurrency	PROJECTIVE/CONCURRENCY
Geometry	Geometry-flavored algebra	coordinate model	projective coordinates		computation	PROJECTIVE/COORDINATE METHODS
Geometry	Geometry-flavored algebra	coordinate model	projective coordinates		computation	PROJECTIVE/COORDINATES
Geometry	Projective and advanced geometry	cyclic/projective configuration	projective; cyclic method		configuration	PROJECTIVE/CYCLIC
Geometry	Projective and advanced geometry	metric/projective configuration	projective metric method		transformation	PROJECTIVE/METRIC GEOMETRY
Geometry	Projective and advanced geometry	spiral similarity configuration	projective; spiral similarity		transformation	PROJECTIVE/SPIRAL SIMILARITY
Geometry	Projective and advanced geometry	synthetic projective configuration	synthetic projective method	Pascal/Desargues/Pappus, if used	configuration	PROJECTIVE/SYNTHETIC
Combinatorics	Processes and invariants	propagated constraint	propagation		local-to-global	PROPAGATION
Algebra	Quadratic methods	quadratic constraint	quadratic analysis		condition	QUADRATIC CONSTRAINTS
Algebra	Quadratic methods	quadratic function	quadratic method		optimization	QUADRATIC FUNCTIONS
Algebra; Number Theory	Quadratic methods	quadratic equation/form	quadratic reduction		reduction	QUADRATIC REDUCTION
Algebra	Polynomials and algebraic manipulation	quadratic roots	root analysis	Vieta, if used	computation	QUADRATIC ROOTS
Algebra; Number Theory	Quadratic methods	quadratic structure	quadratic form/discriminant		structure	QUADRATIC STRUCTURE
Geometry	Core Euclidean geometry	quadrilateral angles	angle chase		computation	QUADRILATERAL ANGLES
Combinatorics	Metric and geometric combinatorics	radius/diameter graph	distance bound		bound	RADIUS/DIAMETER
Geometry	Geometry-flavored algebra	rainbow triangle	coloring geometry		construction/obstruction	RAINBOW TRIANGLES
Combinatorics; Number Theory	Ramsey and coloring methods	coloring structure	Ramsey/coloring	Ramsey	existence/bound	RAMSEY/COLORING
Combinatorics	Combinatorial algebra and counting	random walk	probabilistic method		counting/expectation	RANDOM WALK
Combinatorics	Cyclic order and partial sums	cyclic sequence	gas-station lemma	Raney lemma; gas-station lemma	existence	RANEY/GAS-STATION LEMMA
Algebra	Functions and maps	range	range analysis		range control	RANGE
Algebra	Inequalities and optimization	matrix/rank object	rank inequality		bound	RANK INEQUALITIES
Algebra	Linear algebra	matrix/rank object	rank normal form		normal form	RANK NORMAL FORM
Combinatorics	Order and ranking methods	ranking/permutation	ranking argument		structure	RANKINGS
Algebra	Equations, substitutions, and transformations	ratio expression	ratio substitution		transformation	RATIO SUBSTITUTION
Combinatorics	Counting and enumerative combinatorics	rational Catalan object	Catalan enumeration	Rational Catalan	counting	RATIONAL CATALAN
Algebra	Polynomials and algebraic manipulation	rational-coefficient polynomial	coefficient analysis		structure	RATIONAL COEFFICIENTS
Geometry	Metric geometry	rational distance set	rationality method		obstruction	RATIONAL DISTANCES
Number Theory	Dynamical number theory	rational map/orbit	rational dynamics		dynamics	RATIONAL DYNAMICS
Algebra	Inequalities and optimization	rational expression	rational inequality		bound	RATIONAL INEQUALITIES
Algebra	Rationality and obstruction methods	rational expression	rational obstruction		obstruction	RATIONAL OBSTRUCTION
Number Theory	Number-theoretic algebra	rational ratio	rationality/divisibility method		structure	RATIONAL RATIOS
Algebra; Number Theory	Equations, substitutions, and transformations	rational expression/map	rational transformation		transformation	RATIONAL TRANSFORMATION
Algebra	Equations, substitutions, and transformations	rational expression/map	rational transformation		transformation	RATIONAL TRANSFORMATIONS
Geometry; Number Theory	Rationality and obstruction methods	rational geometric quantity	rationality obstruction		obstruction	RATIONALITY OBSTRUCTION
Algebra	Equations, substitutions, and transformations	radical/rational expression	rationalization		transformation	RATIONALIZATION
Algebra	Functions and inequalities	real variable	real-variable method		computation/estimate	REAL VARIABLES
Algebra	Polynomials and algebraic manipulation	real-rooted polynomial	real-root constraint		obstruction	REAL-ROOT CONSTRAINTS
Algebra	Polynomials and algebraic manipulation	real-rooted polynomial	real-root construction		construction	REAL-ROOT CONSTRUCTION
Algebra	Symmetry methods	reciprocal expression	reciprocal symmetry		symmetry	RECIPROCAL SYMMETRY
Algebra	Sequences, recurrences, and series	recurrence	recurrence dynamics		dynamics	RECURRENCE DYNAMICS
Algebra	Sequences, recurrences, and series	recurrence	recurrence estimate		estimate	RECURRENCE ESTIMATES
Algebra	Inequalities and optimization	recurrence inequality	recursive inequality		estimate	RECURRENCE INEQUALITIES
Algebra	Sequences, recurrences, and series	recurrence	recurrence invariant		invariant	RECURRENCE INVARIANTS
Algebra	Sequences, recurrences, and series	recursive structure	recursive counting		counting	RECURSIVE COUNTING
Algebra	Inequalities and optimization	recursive inequality	recursive inequality		estimate	RECURSIVE INEQUALITIES
Number Theory	Divisibility, gcd, lcm, and primes	reduced fraction	gcd/coprimality		normalization	REDUCED FRACTIONS
Algebra	Polynomials and algebraic manipulation	reducible expression	reducibility		reduction	REDUCIBILITY
Geometry	Transformational geometry	reflected configuration	reflection symmetry		symmetry/transformation	REFLECTION SYMMETRY
Combinatorics; Geometry	Special configurations and special angles	regular hexagon	symmetry		configuration	REGULAR HEXAGONS
Geometry	Special configurations and special angles	regular polygon	regular polygon geometry		configuration	REGULAR POLYGON GEOMETRY
Geometry	Geometry-flavored algebra	regular polygon	symmetry		symmetry	REGULAR POLYGON SYMMETRY
Algebra; Combinatorics; Geometry	Structure and regularity methods	regular structure	regularity argument		structure	REGULARITY
Geometry	Projective and advanced geometry	Reim/Pascal configuration	projective/cyclic method	Reim; Pascal	collinearity/cyclicity	REIM/PASCAL
Combinatorics; Number Theory	Modular arithmetic and residues	remainder class	modular residues		casework	REMAINDERS
Combinatorics	Combinatorial algebra and counting	representation count	representation counting		counting	REPRESENTATION COUNTING
Combinatorics	Modular arithmetic and coloring	residue mod 3	mod 3 argument		casework	RESIDUES MOD 3
Geometry	Geometry-flavored algebra	right triangle coordinates	coordinate method		computation	RIGHT-TRIANGLE COORDINATES
Geometry	Geometry-flavored algebra	right triangle	right-triangle geometry	Pythagorean theorem, if used	computation	RIGHT-TRIANGLE GEOMETRY
Algebra	Calculus and real-variable methods	differentiable function	Rolle's theorem	Rolle's theorem	existence	ROLLE‚ÄôS THEOREM
Algebra	Polynomials and algebraic manipulation	polynomial root	root dynamics		dynamics	ROOT DYNAMICS
Algebra	Polynomials and algebraic manipulation	polynomial root	root analysis		computation	ROOTS OF POLYNOMIAL
Geometry	Transformational geometry	rotated rectangle	rotation method		transformation	ROTATED RECTANGLE
Combinatorics	Matrix and array methods	row/column sums	double counting/linear algebra		counting	ROW/COLUMN SUMS
Algebra	Inequalities and optimization	additive set/difference set	Ruzsa triangle inequality	Ruzsa triangle inequality	bound	RUZSA TRIANGLE INEQUALITY
Combinatorics	Extremal and saturation methods	saturated structure	saturation		extremal	SATURATION
Algebra	Inequalities and optimization	symmetric polynomial expression	Schur-type inequality	Schur	bound	SCHUR-TYPE
Algebra	Inequalities and optimization	symmetric expression	Schur-type argument	Schur	bound	SCHUR-TYPE ARGUMENTS
Algebra	Sequences, recurrences, and series	score sequence	sequence analysis		structure	SCORE SEQUENCES
Geometry	Circle geometry	secant configuration	power of a point	Secant theorem	computation	SECANTS
Combinatorics	Probability, entropy, coding, and information methods	random variable/count	second moment method		existence/bound	SECOND MOMENT
Algebra	Sequences, recurrences, and series	self-descriptive sequence	recurrence/self-reference		structure	SELF-DESCRIPTIVE SEQUENCES
Number Theory	Self-similarity and dynamics	self-similar structure	self-similarity		structure	SELF-SIMILARITY
Geometry	Metric geometry	semiperimeter lengths	semiperimeter substitution	Heron, if used	computation	SEMIPERIMETER LENGTHS
Combinatorics	Separating systems and coding	separating family	separating system		construction	SEPARATING FAMILIES
Combinatorics	Graph theory	separator	separator argument		decomposition	SEPARATORS
Combinatorics	Set systems, posets, and extremal set theory	set operator	set operation method		transformation	SET OPERATORS
Geometry	Core Euclidean geometry	side ratio	ratio chase	Menelaus/Ceva, if used	computation	SIDE RATIOS
Algebra; Combinatorics	Sign and parity methods	signed expression	sign argument		obstruction	SIGN ARGUMENT
Algebra; Combinatorics	Sign and parity methods	signed expression	sign forcing		forcing	SIGN FORCING
Geometry	Geometry-flavored algebra	signed area	area method		computation	SIGNED AREA
Algebra	Algebraic manipulation	signed expansion	expansion/sign analysis		computation	SIGNED EXPANSIONS
Algebra	Sign and parity methods	signs	sign analysis		casework	SIGNS
Geometry	Core Euclidean geometry	triangle sides/angles	sine rule	Law of Sines	computation	SINE LAW
Algebra	Inequalities and optimization	single-variable expression	one-variable optimization		optimization	SINGLE-VARIABLE OPTIMIZATION
Number Theory	Modular arithmetic and sequences	sliding window sequence	sliding-window method		local-to-global	SLIDING WINDOW
Combinatorics; Geometry	Geometry-flavored algebra	slope set	slope method		structure	SLOPES
Combinatorics	Casework and construction	small cases	small-case analysis		casework	SMALL CASES
Number Theory	Casework and modular arithmetic	small cases	small-case check		verification	SMALL-CASE CHECK
Combinatorics	Extremal and avoidance methods	sparse set	sparse avoidance		construction/obstruction	SPARSE AVOIDANCE
Algebra; Number Theory	Equations and specialization	specialized value	specialization		reduction	SPECIALIZATION
Algebra	Algebraic structures and linear algebra	spectrum/eigenvalue set	spectral method		structure	SPECTRA
Combinatorics	Set systems, posets, and extremal set theory	antichain	Sperner/antichain method	Sperner	bound	SPERNER/ANTICHAIN
Geometry	Coding and metric geometry	spherical code	coding/metric method		bound	SPHERICAL CODES
Geometry	Transformational geometry	spiral similarity	spiral geometry		transformation	SPIRAL GEOMETRY
Geometry	Transformational geometry	spiral similarity/homothety	spiral similarity; homothety		transformation	SPIRAL SIMILARITY/HOMOTHETY
Geometry	Circle geometry	spiral/Miquel configuration	spiral similarity; Miquel	Miquel	configuration	SPIRAL/MIQUEL
Geometry	Circle geometry	spiral/Miquel configuration	spiral similarity; Miquel	Miquel	configuration	SPIRAL/MIQUEL FLAVOR
Combinatorics; Number Theory	Square and parity methods	square difference	modular/square method		obstruction	SQUARE DIFFERENCES
Algebra	Polynomials and algebraic manipulation	square factor	factorization		obstruction	SQUARE FACTORS
Algebra; Combinatorics; Number Theory	Square and quadratic methods	square sum	square-sum method		representation	SQUARE SUMS
Algebra; Geometry	Statement validation	problem statement	statement check		verification	STATEMENT CHECK
Number Theory	Fractions and Diophantine approximation	Stern-Brocot tree	Stern-Brocot structure	Stern-Brocot	structure	STERN-BROCOT STRUCTURE
Combinatorics; Number Theory	Games, strategies, and processes	strategy game/process	strategy		strategy	STRATEGIES
Combinatorics	Combinatorial algebra and counting	strategy game	strategy		game strategy	STRATEGY GAME
Combinatorics	Combinatorial algebra and counting	paired strategy	pairing strategy		strategy	STRATEGY PAIRING
Combinatorics	Combinatorial algebra and counting	strategy-stealing game	strategy stealing; pairing		strategy	STRATEGY STEALING/PAIRING
Combinatorics	Geometric combinatorics	strip	strip decomposition		covering/structure	STRIPS
Combinatorics	Graph theory	strongly connected graph/digraph	connectivity		structure	STRONG CONNECTIVITY
Combinatorics	Pigeonhole, extremal principle, and averaging	inductive structure	strong induction		induction	STRONG INDUCTION
Combinatorics	Structural decomposition	combinatorial structure	structural decomposition		decomposition	STRUCTURAL DECOMPOSITION
Geometry; Number Theory	Structure theorems	structure	structure theorem		classification	STRUCTURE THEOREM
Combinatorics	Averaging and subset methods	subset averages	averaging		estimate	SUBSET AVERAGES
Combinatorics	Combinatorial algebra and counting	subset family	subset counting		counting	SUBSET COUNTING
Algebra	Equations, substitutions, and transformations	substitution chain	substitution		transformation	SUBSTITUTION CHAINS
Algebra	Polynomials and algebraic manipulation	factorized expression	substitution; factorization		reduction	SUBSTITUTION/FACTORIZATION
Algebra	Equations and systems	equations	subtracting equations		elimination	SUBTRACTING EQUATIONS
Combinatorics	Switching and transformation methods	switched configuration	switching argument		transformation	SWITCHING ARGUMENT
Geometry	Triangle centers and triangle configurations	symmedian	symmedian method	Symmedian	configuration	SYMMEDIAN FLAVOR
Geometry	Triangle centers and triangle configurations	symmedian/Apollonius configuration	symmedian; Apollonius	Apollonius; Symmedian	computation	SYMMEDIAN/APOLLONIUS
Combinatorics	Set systems, posets, and extremal set theory	symmetric chain decomposition	symmetric chains		decomposition	SYMMETRIC CHAINS
Algebra	Symmetry methods	symmetric expression	symmetric manipulation		transformation	SYMMETRIC MANIPULATION
Algebra	Inequalities and optimization	symmetric expression	symmetric optimization		optimization	SYMMETRIC OPTIMIZATION
Algebra	Inequalities and optimization	symmetric rational expression	rational inequality; symmetry		bound	SYMMETRIC RATIONAL INEQUALITY
Algebra	Equations, substitutions, and transformations	symmetric variables	symmetric substitution		transformation	SYMMETRIC SUBSTITUTIONS
Algebra	Symmetry methods	symmetric triple	symmetry		structure	SYMMETRIC TRIPLES
Algebra	Symmetry methods	symmetric variables	symmetry		structure	SYMMETRIC VARIABLES
Algebra	Functional equations	function with symmetry	affine/symmetry method		functional equation	SYMMETRY / AFFINE STRUCTURE
Combinatorics	Combinatorial algebra and counting	paired symmetric objects	symmetry; pairing		pairing	SYMMETRY/PAIRING
Geometry	Geometry-flavored algebra	tangency coordinates	coordinate method		computation	TANGENCY COORDINATES
Geometry	Geometry-flavored algebra	tangent condition	tangency method		condition	TANGENT CONDITION
Geometry	Geometry-flavored algebra	tangent construction	tangent construction		construction	TANGENT CONSTRUCTION
Geometry	Geometry-flavored algebra	tangent configuration	tangent lemma	tangent lemma	computation	TANGENT LEMMA
Algebra	Inequalities and optimization	convex function/expression	tangent line method		estimate	TANGENT LINE METHOD
Geometry	Geometry-flavored algebra	tangent lines	tangent method		configuration	TANGENT LINES
Geometry	Geometry-flavored algebra	tangent-symmedian configuration	tangent-symmedian method	Symmedian tangent lemma	configuration	TANGENT-SYMMEDIAN
Geometry	Geometry-flavored algebra	tangential polygon	tangent lengths	Pitot, if used	configuration	TANGENTIAL POLYGON
Geometry	Geometry-flavored algebra	tangential polygons	tangent lengths	Pitot, if used	configuration	TANGENTIAL POLYGONS
Geometry	Geometry-flavored algebra	tangential quadrilateral	tangent lengths	Pitot	configuration	TANGENTIAL QUADS
Combinatorics	Processes and invariants	finite process	termination argument		termination	TERMINATION
Geometry	3D and solid geometry	tetrahedron	solid geometry		configuration	TETRAHEDRA
Combinatorics	Games, strategies, and processes	threat	threat strategy		strategy	THREATS
Combinatorics	Combinatorial algebra and counting	threshold game	threshold strategy		strategy	THRESHOLD GAMES
Combinatorics	Combinatorial algebra and counting	threshold graph	graph structure		structure	THRESHOLD GRAPH
Combinatorics	Coloring, tiling, grids, and invariants	tiling	parity invariant		obstruction	TILINGS/PARITY
Algebra	Algebraic structures and linear algebra	trace	trace method		invariant	TRACES
Algebra	Equations and transformations	translated expression	translation identity		identity	TRANSLATION IDENTITY
Algebra	Extremal methods, monotonicity, and invariants	translated structure	translation rigidity		rigidity	TRANSLATION RIGIDITY
Algebra	Equations, substitutions, and transformations	translated variable/function	translation		transformation	TRANSLATIONS
Combinatorics	Set systems, posets, and extremal set theory	transversal	transversal number	Hall, if used	covering	TRANSVERSAL NUMBER
Geometry	Special configurations and special angles	trapezoid	trapezoid geometry		configuration	TRAPEZOID GEOMETRY
Geometry	Core Euclidean geometry	trapezoid ratios	ratio chase		computation	TRAPEZOID RATIOS
Geometry	Geometry-flavored algebra	triangle constraints	coordinate/algebraic geometry		condition	TRIANGLE CONSTRAINTS
Combinatorics	Coloring, tiling, grids, and invariants	triangular grid	grid method		structure	TRIANGULAR GRID
Combinatorics; Number Theory	Figurate numbers	triangular number	arithmetic/combinatorial method		structure	TRIANGULAR NUMBERS
Geometry	Geometry-flavored algebra	trigonometric coordinates	trig coordinates		computation	TRIG COORDINATES
Algebra	Inequalities and optimization	trigonometric expression	trig inequality		bound	TRIG INEQUALITY
Algebra	Complex, trigonometric, and Fourier methods	trigonometric length expression	trig length computation		computation	TRIG LENGTHS
Algebra	Complex, trigonometric, and Fourier methods	angle configuration	trigonometric angle chase		computation	TRIG/ANGLE CHASE
Algebra	Complex, trigonometric, and Fourier methods	complex/trig model	trig/complex bash		computation	TRIG/COMPLEX BASH
Algebra	Complex, trigonometric, and Fourier methods	trigonometric expression	trigonometry		computation	TRIGONOMETRIC
Algebra	Complex, trigonometric, and Fourier methods	trigonometric identity	identity manipulation	trigonometric identities	computation	TRIGONOMETRIC IDENTITIES
Algebra	Complex, trigonometric, and Fourier methods	trigonometric parametrization	parametrization		transformation	TRIGONOMETRIC PARAMETRIZATION
Algebra	Complex, trigonometric, and Fourier methods	trigonometric ratio	ratio computation		computation	TRIGONOMETRIC RATIOS
Geometry	Geometry-flavored algebra	coordinate geometry model	trigonometry; coordinates		computation	TRIGONOMETRY/COORDINATES
Geometry	Triangle coordinates and complex methods	trilinear/complex model	trilinears; complex numbers		computation	TRILINEARS/COMPLEX
Combinatorics	Graph theory	extremal graph	extremal graph method	Turán theorem	bound	TUR√ÅN
Combinatorics	Graph theory	extremal graph	extremal graph method	Turán theorem	bound	TUR√ÅN THEOREM
Algebra; Number Theory	Extremal and infinitude methods	unbounded set/function	unboundedness		existence/contradiction	UNBOUNDEDNESS
Geometry	Geometry-flavored algebra	unit disk	metric/coordinate method		bound	UNIT DISK
Combinatorics; Number Theory	Fractions and Diophantine methods	unit fraction	Egyptian fraction method		representation	UNIT FRACTIONS
Geometry	Geometry-flavored algebra	unit vector	vector method		computation	UNIT VECTORS
Geometry	Circle geometry	variable circle	moving-circle method		locus/configuration	VARIABLE CIRCLE
Geometry	Locus and moving-point geometry	variable point	moving-point method		locus	VARIABLE POINT
Algebra; Geometry	Identities and quadratic methods	variance expression	variance identity		identity	VARIANCE IDENTITY
Geometry	Geometry-flavored algebra	vector/barycentric model	vectors; barycentrics		computation	VECTOR/BARYCENTRIC
Geometry	Geometry-flavored algebra	vector/complex model	vectors; complex numbers		computation	VECTOR/COMPLEX
Geometry	Geometry-flavored algebra	coordinate vector model	vectors; coordinates		computation	VECTORS/COORDINATES
Geometry	Geometry-flavored algebra	vector/trig model	vectors; trigonometry		computation	VECTORS/TRIG
Combinatorics	Graph theory and walks	walk	walk method		counting/existence	WALKS
Algebra	Algebraic graph/degree methods	weighted degree	degree counting		counting	WEIGHTED DEGREE
Combinatorics	Combinatorial algebra and counting	weighted graph	weighting argument		structure/bound	WEIGHTED GRAPH
Combinatorics	Graph theory	weighted tree	tree weighting		structure	WEIGHTED TREES
Combinatorics; Geometry	Width and covering methods	width	width argument		bound	WIDTH
Algebra	Functional equations	wild function	pathological construction		construction/obstruction	WILD FUNCTIONS
Combinatorics	Topological/combinatorial methods	winding number	winding argument		invariant	WINDING NUMBER
Geometry	Geometry-flavored algebra	Witt vector	Witt vector method	Witt vectors	structure	WITT VECTORS
Algebra	Algebraic geometry/flavored algebra	zero set	zero-set method		structure/obstruction	ZERO SET
Combinatorics	Set systems, posets, and extremal set theory	fractional Helly/EKR family	intersection method	Helly; Erdős–Ko–Rado	bound/existence	(FRACTIONAL) HELLY/EKR-STYLE
Geometry	Inversive geometry	inversion centered at L	inversion		transformation	(POINT) INVERSION AT LLL
Combinatorics	Matrix and array methods	0-1 matrix	matrix structure		structure	0-1 MATRIX STRUCTURE
Geometry	Special configurations and special angles	120-degree angle configuration	angle chase/rotation		configuration	120¬∞ ANGLES
Geometry	Special configurations and special angles	120-degree geometry	angle chase/rotation		configuration	120¬∞ GEOMETRY
Geometry	Special configurations and special angles	15-degree angle configuration	angle chase		configuration	15-DEGREE GEOMETRY
Combinatorics	Arrangements and order methods	one-dimensional arrangement	order method		structure	1D ARRANGEMENTS
Algebra	Optimization and median methods	one-dimensional k-median	median method		optimization	1D KKK-MEDIAN
Algebra	Coloring, tiling, grids, and invariants	2 by 2 by 2 cube/parity state	parity invariant		invariant	2 BY 2 BY 2 PARITY
Combinatorics	Modular and parity methods	2-adic cases	2-adic casework		casework	2-ADIC CASES
Combinatorics	Modular and parity methods	2-adic classes	2-adic classification		classification	2-ADIC CLASSES
Algebra	Sequences, recurrences, and series	2-automatic sequence	automata method		structure	2-AUTOMATIC SEQUENCES
Combinatorics	Graph theory	2-colorable graph/set	coloring		condition	2-COLORABILITY
Combinatorics	Coloring, tiling, grids, and invariants	two-coloring	coloring invariant		construction/obstruction	2-COLORING
Combinatorics	Graph theory	2-connected graph	connectivity		structure	2-CONNECTIVITY
Algebra	Polynomials and algebraic manipulation	factorization by 2	2-factorization		reduction	2-FACTORIZATION
Combinatorics	Combinatorial algebra and counting	2-free graph	forbidden subgraph method		obstruction	2-FREE GRAPH
Algebra	Sequences, recurrences, and series	2-periodic structure	period reduction		reduction	2-PERIOD REDUCTION
Combinatorics	Modular and parity methods	2-adic/3-adic valuation	p-adic tracking		invariant	2/3-ADIC TRACKING
Combinatorics	Coloring, tiling, grids, and invariants	2D grid	grid method		structure	2D GRIDS
Algebra	Extremal methods, monotonicity, and invariants	2D state/grid	invariant		invariant	2D INVARIANTS
Combinatorics	Set systems, posets, and extremal set theory	2D poset	poset method	Dilworth/Sperner, if used	structure	2D POSETS
Combinatorics	Matrix and array methods	2D prefix sums	prefix-sum method		computation	2D PREFIX SUMS
Combinatorics	Switching and transformation methods	2x2 switch graph	switching connectivity		connectivity	2√ó2 SWITCH CONNECTIVITY
Combinatorics	Graph theory	3-cycle	cycle method		structure/counting	3-CYCLES
Combinatorics	Coloring, tiling, grids, and invariants	3D grid	grid method		structure	3-DIMENSIONAL GRID
Combinatorics	Combinatorial algebra and counting	3-free permutation	pattern avoidance		construction/obstruction	3-FREE PERMUTATION
Number Theory	Additive and multiplicative number theory	3-term arithmetic progression	additive method		structure	3-TERM AP
Combinatorics	Additive combinatorics	3-term AP	avoidance		construction/obstruction	3-TERM AP AVOIDANCE
Combinatorics	Additive combinatorics	3-term AP chain	chain method		structure	3-TERM AP CHAINS
Combinatorics	Combinatorial algebra and counting	3-term AP	counting		counting	3-TERM AP COUNTING
Combinatorics	Additive/combinatorial number theory	3-term AP-free set	additive combinatorics	Roth-type, if used	bound/construction	3-TERM AP-FREE SETS
Combinatorics	Additive combinatorics	3-term arithmetic progression	additive method		structure	3-TERM ARITHMETIC PROGRESSIONS
Number Theory	Multiplicative number theory	3-term geometric progression	avoidance		construction/obstruction	3-TERM GP AVOIDANCE
Combinatorics	Additive combinatorics	3-term progression	additive method		structure	3-TERM PROGRESSIONS
Combinatorics	Combinatorial algebra and counting	3-uniform hypergraph	hypergraph method		structure/counting	3-UNIFORM HYPERGRAPHS
Geometry	Special configurations and special angles	30-60-90 triangle	special triangle method		computation	30-60-90 GEOMETRY
Geometry	3D and solid geometry	3D coordinate model	analytic geometry		computation	3D ANALYTIC
Combinatorics	Matrix and array methods	3D array	array method		structure	3D ARRAYS
Geometry	3D and solid geometry	3D barycentric model	barycentrics		computation	3D BARYCENTRICS
Combinatorics	Coloring, tiling, grids, and invariants	3D coloring	coloring invariant		construction/obstruction	3D COLORING
Geometry	3D and solid geometry	3D convex set	convexity		structure	3D CONVEX GEOMETRY
Geometry	3D and solid geometry	3D convex set	convexity		estimate	3D CONVEXITY
Algebra	Extremal methods, monotonicity, and invariants	3D coloring configuration	extremal coloring		extremal	3D EXTREMAL COLORING
Combinatorics	Geometric combinatorics	3D grid geometry	grid/coordinate method		structure	3D GRID GEOMETRY
Combinatorics	Combinatorial algebra and counting	3D grid graph	graph encoding		structure	3D GRID GRAPH
Combinatorics	Incidence combinatorics	3D incidence structure	incidence method		bound	3D INCIDENCE
Geometry	3D and solid geometry	3D metric configuration	metric geometry		computation	3D METRIC GEOMETRY
Geometry	3D and solid geometry	polyhedron	polyhedral method	Euler, if used	structure	3D POLYHEDRA
Geometry	3D and solid geometry	sphere/power configuration	power of point in 3D	Power of a Point	computation	3D POWER OF POINT
Geometry	3D and solid geometry	3D projection	projection		transformation	3D PROJECTION
Geometry	3D and solid geometry	3D projective configuration	projective method		transformation	3D PROJECTIVE GEOMETRY
Geometry	3D and solid geometry	3D search configuration	constructive search		construction	3D SEARCH
Geometry	3D and solid geometry	3D similarity configuration	similarity		transformation	3D SIMILARITY
Geometry	3D and solid geometry	sphere configuration	sphere geometry		configuration	3D SPHERES
Geometry	3D and solid geometry	3D tangency configuration	tangency		configuration	3D TANGENCY
Geometry	3D and solid geometry	volume	volume method		computation	3D VOLUME
Geometry	Core Euclidean geometry	four-point configuration	constraint analysis		condition	4-POINT CONSTRAINTS
Algebra	Number-theoretic algebra	5-12-13 triple/structure	Pythagorean-style structure		structure	5-12-13 STRUCTURE
Geometry	Geometry-flavored algebra	60-degree rotation configuration	rotation trick		transformation	60-DEGREE ROTATION TRICK
Geometry	Special configurations and special angles	60-degree structure	angle chase/rotation		configuration	60-DEGREE STRUCTURE
Geometry	Special configurations and special angles	60-degree lemma configuration	angle chase/rotation		lemma use	60¬∞ LEMMAS
Algebra	Extremal methods, monotonicity, and invariants	7-adic valuation/growth	p-adic growth		valuation/invariant	7-ADIC GROWTH
Geometry	Transformational geometry	90-degree rotation configuration	rotation		transformation	90-DEGREE ROTATION
Combinatorics	Corrupted import / needs review	corrupted tag			needs manual review	\CDOT)(R>0‚Äã
Algebra	Corrupted import / needs review	corrupted interval/infinity tag			needs manual review	\INFTY)[0
Geometry	Circle geometry	A-mixtilinear circle	circle geometry	mixtilinear circle	configuration	A-MIXTILINEAR CIRCLE
Combinatorics	Coloring, tiling, grids, and invariants	abelian group coloring	group coloring		invariant/construction	ABELIAN GROUP COLORING
Algebra	Algebraic structures and linear algebra	abelian group	group structure		structure	ABELIAN GROUPS
Combinatorics	Additive/combinatorial algebra	abelian pattern	pattern avoidance		obstruction	ABELIAN PATTERN AVOIDANCE
Combinatorics	Algebraic/combinatorial dynamics	abelian-style dynamics	dynamics		process	ABELIAN-STYLE DYNAMICS
Combinatorics	Metric and difference methods	absolute differences	difference method		invariant/bound	ABSOLUTE DIFFERENCES
Combinatorics	Sign and parity methods	absolute sums/alternation	alternating sum method		invariant	ABSOLUTE SUMS/ALTERNATION
Algebra	Equations and inequalities	absolute value expression	absolute value method		casework/bound	ABSOLUTE VALUE
Area	Canonical Subtopic	Object tag	Technique tag	Lemma/Theorem tag	Proof role	Raw imported tag
Algebra	Inequalities and optimization	absolute value expression	absolute value analysis			ABSOLUTE VALUE INEQUALITY
Algebra	Equations, substitutions, and transformations	absolute value expression	absolute value analysis			ABSOLUTE VALUE KINK
Combinatorics	Combinatorial structures and constructive methods	absolute-value minimization			optimization	ABSOLUTE-VALUE MINIMIZATION
Algebra	Extremal methods, monotonicity, and invariants	abstract extremal	extremal method			ABSTRACT EXTREMAL
Geometry	Geometry-flavored algebra	acute triangle; angle configuration				ACUTE TRIANGLE
Geometry	Geometry-flavored algebra	acute triangle; angle configuration; triangle configuration				ACUTE TRIANGLE GEOMETRY
Geometry	Triangle centers and triangle configurations	acute triangle; angle configuration; triangles				ACUTE TRIANGLES
Combinatorics	Graph theory	acyclic orientation	acyclic orientation			ACYCLIC ORIENTATION
Combinatorics	Graph theory	acyclic orientation	acyclic orientation			ACYCLIC ORIENTATIONS
Combinatorics	Graph theory	acyclic graph	acyclic orientation			ACYCLICITY
Combinatorics	Graph theory	acyclic graph	topological ordering; acyclic orientation			ACYCLICITY/TOPOLOGICAL ORDER
Combinatorics	Games, strategies, and processes	decision tree	decision tree			ADAPTIVE DECISION TREE
Combinatorics	Games, strategies, and processes		adaptive search		search	ADAPTIVE SEARCH
Combinatorics	Combinatorial algebra and counting		adaptive search; matching		search; strategy	ADAPTIVE STRATEGY/SEARCH/MATCHING
Combinatorics	Algorithms, automata, words, and constructive combinatorics	addition-multiplication chain				ADDITION-MULTIPLICATION CHAINS
Combinatorics	Combinatorial algebra and counting	zero-sum set	additive combinatorics			ADDITIVE / ZERO-SUM
Combinatorics	Coloring, tiling, grids, and invariants	coloring	coloring; additive combinatorics			ADDITIVE COLORING
Combinatorics	Combinatorial algebra and counting	additive combinatorics, cauchy-schwarz, log-concavity	additive combinatorics	Cauchy-Schwarz; log-concavity		ADDITIVE COMBINATORICS; CAUCHY-SCHWARZ; LOG-CONCAVITY
Combinatorics	Combinatorial algebra and counting	set sum	construction; additive combinatorics		construction	ADDITIVE COMBINATORICS; CONSTRUCTION; SET SUMS
Combinatorics	Combinatorial algebra and counting	cyclic group; restricted sumset; sumset	additive combinatorics			ADDITIVE COMBINATORICS; CYCLIC GROUPS; RESTRICTED SUMSETS
Combinatorics	Combinatorial algebra and counting	difference set	counting; energy counting; additive combinatorics		counting	ADDITIVE COMBINATORICS; DIFFERENCE SETS; COUNTING/ENERGY
Algebra	Discrete functions, floors, rounding, and base representation	Sidon-type set	construction; base representation; additive combinatorics		construction	ADDITIVE COMBINATORICS; SIDON-TYPE SETS; BASE CONSTRUCTION
Combinatorics	Combinatorial algebra and counting	additive configurations	additive combinatorics			ADDITIVE CONFIGURATIONS
Combinatorics	Combinatorial algebra and counting	additive constraints	additive combinatorics			ADDITIVE CONSTRAINTS
Combinatorics	Combinatorial algebra and counting		matching; construction; additive combinatorics		construction	ADDITIVE CONSTRUCTIONS/MATCHING
Combinatorics	Combinatorial algebra and counting	additive counting	counting; additive combinatorics		counting	ADDITIVE COUNTING
Combinatorics	Combinatorial algebra and counting	cyclic group	additive combinatorics			ADDITIVE CYCLIC GROUPS
Algebra	Equations, substitutions, and transformations	additive defect sets	additive combinatorics		defect	ADDITIVE DEFECT SETS
Algebra	Equations, substitutions, and transformations	additive drift	additive combinatorics			ADDITIVE DRIFT
Algebra	Equations, substitutions, and transformations	additive interval; intervals	additive combinatorics			ADDITIVE INTERVALS
Combinatorics	Combinatorial algebra and counting	additive labeling	additive combinatorics			ADDITIVE LABELINGS
Combinatorics	Combinatorial algebra and counting	additive metric	additive combinatorics			ADDITIVE METRIC
Combinatorics	Combinatorial algebra and counting	additive ordering	additive combinatorics		ordering	ADDITIVE ORDERINGS
Combinatorics	Combinatorial algebra and counting	additive pairing	additive combinatorics		pairing	ADDITIVE PAIRING
Combinatorics	Combinatorial algebra and counting	additive partition	additive combinatorics		partition	ADDITIVE PARTITIONING
Algebra	Extremal methods, monotonicity, and invariants		stability argument; additive combinatorics		stability	ADDITIVE STABILITY
Algebra	Extremal methods, monotonicity, and invariants	additive structure  /  extremal  /  local-to-global	extremal method; local-to-global; additive combinatorics		local-to-global	ADDITIVE STRUCTURE / EXTREMAL / LOCAL-TO-GLOBAL
Combinatorics	Combinatorial algebra and counting	additive triple	additive combinatorics			ADDITIVE TRIPLES
Combinatorics	Combinatorial algebra and counting	additive-multiplicative structure	additive combinatorics			ADDITIVE-MULTIPLICATIVE STRUCTURE
Algebra	Extremal methods, monotonicity, and invariants		rigidity argument; additive combinatorics		rigidity	ADDITIVE/MULTIPLICATIVE RIGIDITY
Combinatorics	Combinatorial algebra and counting	product set	additive combinatorics			ADDITIVE/PRODUCT SET
Geometry	Geometry-flavored algebra	angle configuration	additive combinatorics		obstruction	ADDITIVE/TRIANGLE OBSTRUCTION
Algebra	Extremal methods, monotonicity, and invariants		forcing		forcing	ADDITIVITY FORCING
Number Theory	Number theory structures and methods	adjacency relation				ADJACENCY
Combinatorics	Graph theory	adjacency matrix; adjacency relation				ADJACENCY MATRICES
Combinatorics	Graph theory	adjacency matrix; adjacency relation				ADJACENCY MATRIX
Combinatorics	Combinatorial structures and constructive methods	adjacency relation				ADJACENCY STATISTICS
Combinatorics	Combinatorial structures and constructive methods	adjacent products				ADJACENT PRODUCTS
Combinatorics	Combinatorial structures and constructive methods	adjacent-swap distance				ADJACENT-SWAP DISTANCE
Geometry	Special configurations and special angles	angle configuration	angle chasing			ADVANCED ANGLE CHASE
Geometry	Circle geometry	circle configuration				ADVANCED CIRCLE CONFIGURATION
Geometry	Geometry-flavored algebra	advanced coordinates	coordinate method			ADVANCED COORDINATES
Geometry	Projective, affine, and transformational geometry	cyclic configuration; projective configuration	projective method			ADVANCED CYCLIC/PROJECTIVE STRUCTURE
Geometry	Core Euclidean geometry	advanced euclidean geometry				ADVANCED EUCLIDEAN GEOMETRY
Geometry	Projective, affine, and transformational geometry	projective configuration	projective method; synthetic geometry			ADVANCED SYNTHETIC/PROJECTIVE
Algebra	Complex, trigonometric, and Fourier methods	projective configuration	trigonometric method; projective method; synthetic geometry			ADVANCED SYNTHETIC/PROJECTIVE/TRIG
Geometry	Geometry-flavored algebra	angle configuration; triangle configuration				ADVANCED TRIANGLE GEOMETRY
Geometry	Special configurations and special angles	angle configuration				ADVENTITIOUS ANGLES
Combinatorics	Games, strategies, and processes		adversary argument		bound	ADVERSARIAL BOUND
Combinatorics	Games, strategies, and processes	adversarial cases	adversary argument			ADVERSARIAL CASES
Combinatorics	Games, strategies, and processes	adversarial deletion	adversary argument		deletion	ADVERSARIAL DELETION
Combinatorics	Games, strategies, and processes	adversarial examples	adversary argument		counterexample / extremal example	ADVERSARIAL EXAMPLES
Combinatorics	Combinatorial algebra and counting	hitting set; game	adversary argument			ADVERSARIAL GAME ‚Äö√ú√≠ HITTING SET
Combinatorics	Games, strategies, and processes	game	adversary argument			ADVERSARIAL GAMES
Algebra	Extremal methods, monotonicity, and invariants	game	invariant; adversary argument		invariant	ADVERSARIAL GAMES/INVARIANTS
Combinatorics	Games, strategies, and processes	adversarial information	adversary argument			ADVERSARIAL INFORMATION
Combinatorics	Games, strategies, and processes	intervals	adversary argument			ADVERSARIAL INTERVALS
Combinatorics	Games, strategies, and processes		adversary argument		lower bound; bound	ADVERSARIAL LOWER BOUND
Combinatorics	Games, strategies, and processes	adversarial merging	adversary argument		merging	ADVERSARIAL MERGING
Algebra	Extremal methods, monotonicity, and invariants	adversarial ordering	adversary argument		ordering	ADVERSARIAL ORDERING
Combinatorics	Games, strategies, and processes		adversary argument			ADVERSARIAL REASONING
Combinatorics	Games, strategies, and processes	tiling	adversary argument; tiling			ADVERSARIAL TILINGS
Combinatorics	Games, strategies, and processes	adversarial / strategy	adversary argument		strategy	ADVERSARIAL/STRATEGY
Combinatorics	Games, strategies, and processes	adversary	adversary argument			ADVERSARY
Combinatorics	Pigeonhole, extremal principle, and averaging		adversary argument			ADVERSARY ARGUMENT
Combinatorics	Games, strategies, and processes		adversary argument			ADVERSARY ARGUMENTS
Combinatorics	Games, strategies, and processes	query model	adversary argument		strategy	ADVERSARY/QUERY STRATEGY
Geometry	Projective, affine, and transformational geometry	affine	affine method			AFFINE
Algebra	Algebraic structures and linear algebra	affine actions	affine method			AFFINE ACTIONS
Algebra	Algebraic structures and linear algebra	affine ansatz	affine method			AFFINE ANSATZ
Geometry	Projective, affine, and transformational geometry	area	affine method; area method			AFFINE AREA IDENTITIES
Algebra	Algebraic structures and linear algebra		affine method		bound	AFFINE BOUNDS
Algebra	Algebraic structures and linear algebra	affine candidates	affine method		candidate analysis	AFFINE CANDIDATES
Algebra	Algebraic structures and linear algebra	affine classification	affine method		classification	AFFINE CLASSIFICATION
Geometry	Projective, affine, and transformational geometry	affine collinearity	affine method			AFFINE COLLINEARITY
Algebra	Algebraic structures and linear algebra	affine conjugation	affine method			AFFINE CONJUGATION
Combinatorics	Combinatorial structures and constructive methods	affine constraint	affine method			AFFINE CONSTRAINTS
Algebra	Algebraic structures and linear algebra	affine correction	affine method		correction	AFFINE CORRECTION
Combinatorics	Combinatorial structures and constructive methods	affine cube	construction; affine method		construction	AFFINE CUBE CONSTRUCTION
Algebra	Algebraic structures and linear algebra	affine decomposition	affine method		decomposition	AFFINE DECOMPOSITION
Geometry	Projective, affine, and transformational geometry	distance function	affine method			AFFINE DISTANCE FUNCTIONS
Number Theory	Number-theoretic sequences and sums	affine dynamics	affine method		process invariant	AFFINE DYNAMICS
Combinatorics	Combinatorial structures and constructive methods		construction; affine method		construction	AFFINE F_5 CONSTRUCTION
Algebra	Algebraic structures and linear algebra	affine form	affine method			AFFINE FORMS
Algebra	Inequalities and optimization	area	affine method; area method			AFFINE GEOMETRY/AREA INEQUALITIES
Combinatorics	Coloring, tiling, grids, and invariants	affine grid	affine method			AFFINE GRID
Geometry	Projective, affine, and transformational geometry	affine lift	affine method		lifting	AFFINE LIFT
Geometry	Projective, affine, and transformational geometry	locus	affine method			AFFINE LOCUS
Geometry	Projective, affine, and transformational geometry	midpoint	affine method			AFFINE MIDPOINT
Geometry	Projective, affine, and transformational geometry	affine parameterization	affine method; parametrization		parametrization	AFFINE PARAMETERIZATION
Geometry	Projective, affine, and transformational geometry	affine parametrization	affine method; parametrization		parametrization	AFFINE PARAMETRIZATION
Geometry	Projective, affine, and transformational geometry	affine projection	affine method			AFFINE PROJECTION
Geometry	Projective, affine, and transformational geometry		affine method; ratio chasing			AFFINE RATIO CHASE
Algebra	Sequences, recurrences, and series	affine recurrence	affine method			AFFINE RECURRENCE
Algebra	Algebraic structures and linear algebra	affine reflection moves	affine method; reflection			AFFINE REFLECTION MOVES
Geometry	Projective, affine, and transformational geometry	affine reflections	affine method; reflection			AFFINE REFLECTIONS
Algebra	Algebraic structures and linear algebra	affine self-similarity	affine method			AFFINE SELF-SIMILARITY
Combinatorics	Combinatorial structures and constructive methods	affine span	affine method			AFFINE SPANS
Combinatorics	Combinatorial structures and constructive methods	affine structure	affine method			AFFINE STRUCTURE
Algebra	Equations, substitutions, and transformations	affine transformation	affine method			AFFINE TRANSFORMATION
Geometry	Projective, affine, and transformational geometry	affine transforms	affine method			AFFINE TRANSFORMS
Geometry	Geometry-flavored algebra	affine vectors; vectors	affine method; vector method			AFFINE VECTORS
Geometry	Projective, affine, and transformational geometry	affine volume	affine method			AFFINE VOLUME
Combinatorics	Combinatorial algebra and counting	affine-coset counting	counting; affine method		counting	AFFINE-COSET COUNTING
Geometry	Projective, affine, and transformational geometry	affine-flavored euclidean geometry	affine method			AFFINE-FLAVORED EUCLIDEAN GEOMETRY
Geometry	Projective, affine, and transformational geometry	affine-looking configuration	affine method			AFFINE-LOOKING CONFIGURATION
Geometry	Projective, affine, and transformational geometry		construction; affine method		construction	AFFINE-PARALLEL CONSTRUCTION
Combinatorics	Combinatorial structures and constructive methods		construction; affine method		construction	AFFINE-PLANE CONSTRUCTION
Geometry	Projective, affine, and transformational geometry		affine method			AFFINE-STYLE GEOMETRY
Number Theory	Number theory structures and methods	affine-to-homogeneous shift	homogenization; affine method		homogenization; shift	AFFINE-TO-HOMOGENEOUS SHIFT
Geometry	Geometry-flavored algebra	area	affine method; coordinate method; area method			AFFINE/AREA COORDINATES
Geometry	Projective, affine, and transformational geometry	barycentric coordinates	affine method; barycentric coordinates			AFFINE/BARYCENTRIC ON EQUILATERAL
Geometry	Projective, affine, and transformational geometry	affine / complex	affine method; complex numbers			AFFINE/COMPLEX
Geometry	Geometry-flavored algebra	vectors	affine method; complex numbers; vector method			AFFINE/COMPLEX VECTORS
Geometry	Projective, affine, and transformational geometry	affine / continuity	affine method			AFFINE/CONTINUITY
Geometry	Geometry-flavored algebra	affine / coordinate	affine method; coordinate method			AFFINE/COORDINATE
Geometry	Core Euclidean geometry		affine method; coordinate method			AFFINE/COORDINATE METHODS
Geometry	Projective, affine, and transformational geometry	affine / euler geometry	affine method			AFFINE/EULER GEOMETRY
Combinatorics	Combinatorial structures and constructive methods	affine / harmonicity	affine method			AFFINE/HARMONICITY
Geometry	Projective, affine, and transformational geometry	affine / linear algebra	affine method			AFFINE/LINEAR ALGEBRA
Geometry	Projective, affine, and transformational geometry	affine / linear relations	affine method			AFFINE/LINEAR RELATIONS
Geometry	Projective, affine, and transformational geometry		affine method		comparison	AFFINE/METRIC COMPARISON
Geometry	Geometry-flavored algebra	affine / oblique coordinates	affine method; coordinate method			AFFINE/OBLIQUE COORDINATES
Geometry	Projective, affine, and transformational geometry	affine / projection ideas	affine method			AFFINE/PROJECTION IDEAS
Geometry	Projective, affine, and transformational geometry	projective configuration	affine method; projective method			AFFINE/PROJECTIVE
Geometry	Projective, affine, and transformational geometry	projective configuration	affine method; projective method			AFFINE/PROJECTIVE METHODS
Geometry	Projective, affine, and transformational geometry	projective configuration	affine method; projective method			AFFINE/PROJECTIVE RATIOS
Geometry	Projective, affine, and transformational geometry	projective configuration	affine method; projective method			AFFINE/PROJECTIVE TRANSFORMATIONS
Geometry	Projective, affine, and transformational geometry	affine / quadratic forms	affine method			AFFINE/QUADRATIC FORMS
Geometry	Projective, affine, and transformational geometry	affine / reflection geometry	affine method; reflection			AFFINE/REFLECTION GEOMETRY
Geometry	Projective, affine, and transformational geometry	affine / trapezoid lemma	affine method			AFFINE/TRAPEZOID LEMMA
Geometry	Geometry-flavored algebra	affine / vector	affine method; vector method			AFFINE/VECTOR
Geometry	Geometry-flavored algebra	affine / vector bash	affine method; vector method			AFFINE/VECTOR BASH
Geometry	Geometry-flavored algebra	affine / vector coordinates	affine method; coordinate method; vector method			AFFINE/VECTOR COORDINATES
Algebra	Inequalities and optimization	nonnegative variables			equality case	ALG - INEQUALITIES; NONNEGATIVE VARIABLES; EQUALITY CASES
Algebra	Inequalities and optimization		monotonicity; substitution			ALG - SUBSTITUTIONS; CYCLIC INEQUALITIES; MONOTONICITY
Algebra	Inequalities and optimization	summation by parts, majorization-lite, inequalities	summation by parts; majorization			ALG - SUMMATION BY PARTS; MAJORIZATION-LITE; INEQUALITIES
Algebra	Inequalities and optimization	inequalities, telescoping, summation by parts	summation by parts; telescoping		telescoping	ALG-INEQUALITIES; TELESCOPING; SUMMATION BY PARTS
Algebra	Polynomials and algebraic manipulation	polynomial sums	expansion; polynomial method			ALG-POLYNOMIAL SUMS; SYMMETRY; EXPANSION
Algebra	Polynomials and algebraic manipulation	polynomial	polynomial method	Factor theorem		ALG-POLYNOMIALS; DIVISIBILITY; FACTOR THEOREM
Combinatorics	Combinatorial algebra and counting	permutation graph; finite chain				ALG/COMB - PERMUTATION GRAPH; FINITE CHAINS
Algebra	Polynomials and algebraic manipulation	support set	inclusion-exclusion			ALG/COMB; COEFFICIENTS; INCLUSION-EXCLUSION; SUPPORT SETS
Algebra	Sequences, recurrences, and series		telescoping; integral estimate		telescoping; comparison	ALG/ESTIMATION; TELESCOPING; INTEGRAL COMPARISON
Algebra	Analytic estimates and asymptotics	generating function	generating functions; integral estimate			ALGEBRA; GENERATING FUNCTIONS; POSITIVITY; INTEGRAL REPRESENTATION
Algebra	Inequalities and optimization		factorization; homogenization		optimization; homogenization	ALGEBRA; HOMOGENEOUS OPTIMIZATION; FACTORIZATION; INEQUALITIES
Algebra	Polynomials and algebraic manipulation	complex roots	irreducibility; complex numbers			ALGEBRA; IRREDUCIBILITY; COMPLEX ROOTS
Algebra	Polynomials and algebraic manipulation	polynomial	coefficient comparison; polynomial modulo p; polynomial method		comparison	ALGEBRA; POLYNOMIALS MOD P; COEFFICIENT COMPARISON
Algebra	Sequences, recurrences, and series	sequence	induction		induction	ALGEBRA; SEQUENCES; INDUCTION
Geometry	Core Euclidean geometry					ALGEBRAIC CHASE
Geometry	Core Euclidean geometry		construction		construction	ALGEBRAIC CONSTRUCTION
Algebra	Equations, substitutions, and transformations	ebraic degree				ALGEBRAIC DEGREE
Algebra	Polynomials and algebraic manipulation	discriminant				ALGEBRAIC DISCRIMINANTS
Algebra	Equations, substitutions, and transformations	ebraic equivalence			equivalence	ALGEBRAIC EQUIVALENCE
Combinatorics	Combinatorial structures and constructive methods	ebraic generation				ALGEBRAIC GENERATION
Geometry	Core Euclidean geometry	ebraic geometry flavor				ALGEBRAIC GEOMETRY FLAVOR
Algebra	Equations, substitutions, and transformations	ebraic irrationality				ALGEBRAIC IRRATIONALITY
Combinatorics	Combinatorial structures and constructive methods		determinant/Vandermonde method; determinant method	Vandermonde		ALGEBRAIC METHOD (DETERMINANT/VANDERMONDE-TYPE)
Number Theory	Algebraic number theory flavor	ebraic norms				ALGEBRAIC NORMS
Combinatorics	Combinatorial structures and constructive methods	ebraic potential				ALGEBRAIC POTENTIAL
Algebra	Equations, substitutions, and transformations	ebraic syntax				ALGEBRAIC SYNTAX
Algebra	Extremal methods, monotonicity, and invariants		rigidity argument		rigidity	ALGEBRAIC/RATIONALITY RIGIDITY
Algebra	Inequalities and optimization				optimization	ALGORITHMIC OPTIMIZATION
Combinatorics	Games, strategies, and processes	orithmic strategy			strategy	ALGORITHMIC STRATEGY
Algebra	Algebraic structures and linear algebra	‚Äìfunctional equations, substitution, linearity	substitution; functional equation			ALG‚Äö√Ñ√¨FUNCTIONAL EQUATIONS; SUBSTITUTION; LINEARITY
Combinatorics	Combinatorial algebra and counting	all-pairs counting	counting		counting	ALL-PAIRS COUNTING
Algebra	Equations, substitutions, and transformations	almost additive functions	additive combinatorics			ALMOST ADDITIVE FUNCTIONS
Combinatorics	Graph theory	Hamilton cycle				ALTERNATING HAMILTON CYCLES
Algebra	Equations, substitutions, and transformations	alternating pattern				ALTERNATING PATTERN
Combinatorics	Combinatorial algebra and counting	permutation				ALTERNATING PERMUTATIONS
Algebra	Polynomials and algebraic manipulation	polynomial	polynomial method			ALTERNATING POLYNOMIALS
Algebra	Equations, substitutions, and transformations	alternating sum				ALTERNATING SUM
Geometry	Triangle centers and triangle configurations	altitude			bound	ALTITUDE BOUND
Geometry	Triangle centers and triangle configurations	altitude				ALTITUDE-FOOT RATIOS
Number Theory	Inequalities and estimates in number theory	AM-GM equality case	AM-GM	AM-GM	equality case	AM-GM EQUALITY CASE
Number Theory	Inequalities and estimates in number theory	AM-GM equality defect	AM-GM	AM-GM	defect/equality case; defect	AM-GM EQUALITY DEFECT
Combinatorics	Combinatorial structures and constructive methods		AM-GM	AM-GM		AM-GM INTUITION
Algebra	Inequalities and optimization		AM-GM	AM-GM		AM-GM STYLE
Combinatorics	Combinatorial structures and constructive methods		AM-GM	AM-GM	estimate	AM-GM STYLE ESTIMATE
Algebra	Inequalities and optimization	AM-GM / H√∂lder	AM-GM; H√∂lder inequality	H√∂lder; AM-GM		AM-GM/H‚àö√±LDER
Algebra	Inequalities and optimization	AM-GM / inequalities	AM-GM	AM-GM		AM-GM/INEQUALITIES
Algebra	Analytic estimates and asymptotics		AM-GM; integral estimate	AM-GM	bound	AM-GM/INTEGRAL BOUNDS
Algebra	Inequalities and optimization		AM-GM; Jensen-style convexity	Jensen; AM-GM		AM-GM/JENSEN-STYLE
Algebra	Inequalities and optimization	AM-GM / normalization	AM-GM	AM-GM	normalization	AM-GM/NORMALIZATION
Algebra	Inequalities and optimization	AM-GM / schur	AM-GM; Schur inequality	Schur; AM-GM		AM-GM/SCHUR
Algebra	Inequalities and optimization	AM-HM		AM-HM		AM-HM
Algebra	Inequalities and optimization	AM-QM		AM-QM		AM-QM
Combinatorics	Pigeonhole, extremal principle, and averaging		amortization		bound	AMORTIZED BOUNDS
Combinatorics	Combinatorial algebra and counting	amortized counting	counting; amortization		counting	AMORTIZED COUNTING
Combinatorics	Pigeonhole, extremal principle, and averaging		amortization		lower bound; bound	AMORTIZED LOWER BOUND
Algebra	Inequalities and optimization	convex polytope	AM-GM	AM-GM		AM‚Äö√Ñ√¨GM ON CONVEX POLYTOPES
Algebra	Extremal methods, monotonicity, and invariants	monotone function; one-sided derivative	monotonicity; integral estimate		characterization	ANALYSIS - MONOTONE FUNCTIONS; ONE-SIDED DERIVATIVES; INTEGRAL CHARACTERIZATION
Algebra	Sequences, recurrences, and series	sequence				ANALYSIS ON SEQUENCES
Algebra	Extremal methods, monotonicity, and invariants	monotone function	monotonicity; integral estimate			ANALYSIS; MONOTONE FUNCTIONS; ONE-SIDED LIMITS; DERIVATIVES OF INTEGRALS
Algebra	Analytic estimates and asymptotics	improper series	Taylor estimate; asymptotic estimate		estimate	ANALYSIS; TAYLOR ESTIMATE AT 0; IMPROPER SERIES; ASYMPTOTICS
Combinatorics	Combinatorial algebra and counting	analytic counting	counting		counting	ANALYTIC COUNTING
Algebra	Analytic estimates and asymptotics				estimate	ANALYTIC ESTIMATE (NO HEAVY CALCULUS REQUIRED)
Algebra	Analytic estimates and asymptotics	analytic flavor (exp)				ANALYTIC FLAVOR (EXP)
Geometry	Triangle centers and triangle configurations	ellipse; locus; incenter	analytic geometry; parametrization		parametrization	ANALYTIC GEOMETRY; ELLIPSE PARAMETRIZATION; INCENTER FORMULA; LOCUS
Geometry	Geometry-flavored algebra	parabola	analytic geometry; parametrization		parametrization	ANALYTIC GEOMETRY; PARABOLA PARAMETRIZATION; PERPENDICULARITY
Geometry	Geometry-flavored algebra	parabola	analytic geometry		optimization	ANALYTIC GEOMETRY; PARABOLA; OPTIMIZATION
Geometry	Geometry-flavored algebra	vectors	vector method; analytic geometry			ANALYTIC GEOMETRY; VECTORS
Algebra	Inequalities and optimization	analytic inequalities				ANALYTIC INEQUALITIES
Geometry	Geometry-flavored algebra	locus				ANALYTIC LOCUS
Number Theory	Number theory structures and methods	analytic / algebraic NT				ANALYTIC/ALGEBRAIC NT
Geometry	Projective, affine, and transformational geometry	projective configuration	projective method			ANALYTIC/PROJECTIVE GEOMETRY
Geometry	Geometry-flavored algebra	analytic / synthetic characterization	synthetic geometry		characterization	ANALYTIC/SYNTHETIC CHARACTERIZATION
Geometry	Geometry-flavored algebra	analytic / synthetic hybrid	synthetic geometry			ANALYTIC/SYNTHETIC HYBRID
Geometry	Geometry-flavored algebra	analytic / trilinear	trilinear coordinates			ANALYTIC/TRILINEAR
Geometry	Geometry-flavored algebra	analytic / vector geometry	vector method			ANALYTIC/VECTOR GEOMETRY
Geometry	Special configurations and special angles	angle configuration; angle bisector				ANGLE BISECTOR LENGTH
Geometry	Special configurations and special angles	angle configuration; angle bisector	reflection			ANGLE BISECTOR REFLECTION
Geometry	Special configurations and special angles	angle configuration; angle bisector				ANGLE BISECTOR TYPE CONCLUSION
Geometry	Triangle centers and triangle configurations	angle configuration; angle bisector; circumcenter				ANGLE BISECTOR/CIRCUMCENTER
Algebra	Complex, trigonometric, and Fourier methods	angle configuration; angle bisector; angle bisectors				ANGLE BISECTORS/CENTER III
Geometry	Triangle centers and triangle configurations	angle configuration; angle bisector; angle bisectors				ANGLE BISECTORS/CENTERS
Geometry	Triangle centers and triangle configurations	angle configuration; angle bisector; angle bisectors				ANGLE BISECTORS/EXCENTERS
Geometry	Special configurations and special angles	angle configuration			characterization	ANGLE CHARACTERIZATION
Algebra	Complex, trigonometric, and Fourier methods	angle configuration; circumcenter	trigonometric method; angle chasing			ANGLE CHASE / TRIG / CIRCUMCENTER
Geometry	Geometry-flavored algebra	angle configuration	coordinate method; angle chasing			ANGLE CHASE/COORDINATES
Geometry	Special configurations and special angles	angle configuration; IO-line	angle chasing			ANGLE CHASE/IO-LINE
Geometry	Special configurations and special angles	angle configuration; isogonal lines	angle chasing			ANGLE CHASE/ISOGONALS
Geometry	Triangle centers and triangle configurations	angle configuration; incenter	angle chasing			ANGLE CHASING + INCENTER GEOMETRY
Algebra	Complex, trigonometric, and Fourier methods	angle configuration	trigonometric method; angle chasing			ANGLE CHASING/TRIG
Combinatorics	Combinatorial algebra and counting	angle configuration	counting		counting	ANGLE COUNTING
Geometry	Special configurations and special angles	angle configuration				ANGLE DOUBLING
Algebra	Inequalities and optimization	angle configuration				ANGLE INEQUALITIES
Geometry	Special configurations and special angles	angle configuration			optimization	ANGLE OPTIMIZATION
Geometry	Special configurations and special angles	angle configuration	packing		packing	ANGLE PACKING
Geometry	Special configurations and special angles	angle configuration				ANGLE PRESERVATION
Algebra	Sequences, recurrences, and series	angle configuration				ANGLE RECURRENCE
Number Theory	Modular arithmetic and congruences	angle configuration				ANGLE RELATIONS MOD ≈í‚Ä†
Algebra	Complex, trigonometric, and Fourier methods	angle configuration				ANGLE SUMS
Geometry	Special configurations and special angles	angle configuration				ANGLE WITH PLANE
Geometry	Special configurations and special angles	angle configuration				ANGLE-BISECTOR AXES
Geometry	Special configurations and special angles	angle configuration				ANGLE-BISECTOR AXIS
Geometry	Geometry-flavored algebra	angle configuration; cevian triangle				ANGLE-BISECTOR CEVIAN TRIANGLE
Geometry	Geometry-flavored algebra	angle configuration	coordinate method			ANGLE-BISECTOR COORDINATES
Geometry	Special configurations and special angles	angle configuration				ANGLE-CHASING WITH PARALLELS THROUGH OOO
Number Theory	Number theory structures and methods	angle configuration				ANGLE-DOUBLING STRUCTURE
Geometry	Special configurations and special angles	angle configuration				ANGLE-SUM IDENTITY
Geometry	Geometry-flavored algebra	angle configuration; barycentric coordinates	barycentric coordinates			ANGLE/BARYCENTRIC CHASE
Algebra	Inequalities and optimization	angle configuration				ANGLE/INEQUALITY
Geometry	Circle geometry	angle configuration; power of a point				ANGLE/POWER OF A POINT
Geometry	Special configurations and special angles	angle configuration				ANGLE/RATIO LEMMAS
Geometry	Special configurations and special angles	angle configuration				ANGLES
Geometry	Core Euclidean geometry	angular sectors				ANGULAR SECTORS
Algebra	Analytic estimates and asymptotics	angular sweep / integral geometry	integral estimate			ANGULAR SWEEP/INTEGRAL GEOMETRY
Algebra	Equations, substitutions, and transformations	annihilator				ANNIHILATORS
Number Theory	Additive and arithmetic structures	anti-bunyakovsky traps		Bunyakovsky		ANTI-BUNYAKOVSKY TRAPS
Combinatorics	Pigeonhole, extremal principle, and averaging	anti-concentration				ANTI-CONCENTRATION
Combinatorics	Coloring, tiling, grids, and invariants	coloring; anti-Ramsey coloring	coloring			ANTI-RAMSEY COLORING
Combinatorics	Combinatorial structures and constructive methods	anti-steiner / isogonal				ANTI-STEINER/ISOGONAL
Combinatorics	Set systems, posets, and extremal set theory	antichain / chain				ANTICHAINS/CHAINS
Geometry	Special configurations and special angles	antiparallel lines				ANTIPARALLEL LINES
Number Theory	Additive and arithmetic structures	AP/GP intersection				AP/GP INTERSECTION
Geometry	Circle geometry	Apollonian circle				APOLLONIAN CIRCLE
Algebra	Equations, substitutions, and transformations	apollonius		Apollonius		APOLLONIUS
Geometry	Core Euclidean geometry	Apollonius ratio		Apollonius		APOLLONIUS RATIO
Algebra	Analytic estimates and asymptotics	approximate additivity	approximation			APPROXIMATE ADDITIVITY
Algebra	Analytic estimates and asymptotics	arithmetic progression	approximation			APPROXIMATE ARITHMETIC PROGRESSIONS
Algebra	Analytic estimates and asymptotics	approximate homomorphisms	approximation			APPROXIMATE HOMOMORPHISMS
Geometry	Geometry-flavored algebra	approximation by polygons				APPROXIMATION BY POLYGONS
Number Theory	Additive and arithmetic structures	aps				APS
Combinatorics	Pigeonhole, extremal principle, and averaging			van der Waerden	bound	APS/VAN DER WAERDEN (ELEMENTARY BOUND)
Geometry	Core Euclidean geometry	arbelos				ARBELOS-STYLE GEOMETRY
Algebra	Equations, substitutions, and transformations	arbitrary functions				ARBITRARY FUNCTIONS
Geometry	Circle geometry	arc				ARC CHASING
Geometry	Circle geometry	arc	construction		construction	ARC CONSTRUCTION
Combinatorics	Combinatorial algebra and counting	arc	counting		counting	ARC COUNTING
Geometry	Circle geometry	arc				ARC LENGTHS
Algebra	Equations, substitutions, and transformations	arc				ARC METHODS
Geometry	Circle geometry	arc				ARC MIDPOINT LEMMA
Geometry	Circle geometry	arc				ARC MIDPOINT/SYMMEDIAN
Geometry	Circle geometry	arc				ARC PARAMETER
Geometry	Circle geometry	arc	parametrization		parametrization	ARC PARAMETRIZATION
Geometry	Circle geometry	arc				ARC-CHASING
Geometry	Circle geometry	arc				ARC-MIDPOINT GEOMETRY
Geometry	Circle geometry	arc				ARC-MIDPOINT LEMMA
Geometry	Circle geometry	arc				ARC-MIDPOINT MACHINERY
Geometry	Circle geometry	Archimedean/Catalan solid				ARCHIMEDEAN/CATALAN SOLIDS
Geometry	Circle geometry	arc				ARCS/CENTERS
Geometry	Circle geometry	arc				ARCS/CONTACT POINTS
Geometry	Geometry-flavored algebra					ARCTANGENT SUM
Combinatorics	Combinatorial structures and constructive methods	area	area method			AREA ADDITIVITY
Geometry	Geometry-flavored algebra	area	area method			AREA ALGEBRA
Geometry	Geometry-flavored algebra	area	area method			AREA AS DISTANCE
Combinatorics	Pigeonhole, extremal principle, and averaging	area	averaging; area method			AREA AVERAGING
Combinatorics	Combinatorial structures and constructive methods	area	area method		cancellation	AREA CANCELLATION
Geometry	Geometry-flavored algebra	area	area method		computation	AREA COMPUTATION
Geometry	Geometry-flavored algebra	area	area method			AREA CONDITION
Geometry	Geometry-flavored algebra	area	coordinate method; area method			AREA COORDINATES
Combinatorics	Combinatorial algebra and counting	area	counting; area method		counting	AREA COUNTING
Combinatorics	Coloring, tiling, grids, and invariants	area	area method; covering		covering	AREA COVERING
Geometry	Geometry-flavored algebra	area	determinant method; area method			AREA DETERMINANT
Geometry	Geometry-flavored algebra	area	determinant method; area method			AREA DETERMINANTS
Combinatorics	Combinatorial structures and constructive methods	area	area method			AREA EQUALITY
Algebra	Extremal methods, monotonicity, and invariants	area	extremal method; area method			AREA EXTREMAL
Algebra	Extremal methods, monotonicity, and invariants	area	extremal method; area method			AREA EXTREMALS
Geometry	Geometry-flavored algebra	area; diagonals	area method			AREA FROM DIAGONALS
Algebra	Extremal methods, monotonicity, and invariants	area	invariant; area method		invariant	AREA INVARIANT
Geometry	Geometry-flavored algebra	area	area method		optimization	AREA OPTIMIZATION
Combinatorics	Combinatorial algebra and counting	area	area method		pairing	AREA PAIRING
Geometry	Geometry-flavored algebra	area	area method		partition	AREA PARTITION
Combinatorics	Pigeonhole, extremal principle, and averaging	area	area method; pigeonhole principle		pigeonhole	AREA PIGEONHOLE
Geometry	Geometry-flavored algebra	area	area method			AREA POTENTIAL
Geometry	Geometry-flavored algebra	area	area method			AREA RATIO
Number Theory	Inequalities and estimates in number theory	area	area method			AREA SANDWICH
Geometry	Geometry-flavored algebra	area	area method			AREA SCALING
Geometry	Geometry-flavored algebra	area	area method			AREA TRIANGULATIONS
Geometry	Geometry-flavored algebra	vectors; area	vector method; area method			AREA VECTORS
Geometry	Geometry-flavored algebra	area	area method			AREA VIA SINES
Geometry	Geometry-flavored algebra	area	area method			AREA-DENSITY
Geometry	Geometry-flavored algebra	area	area method		comparison	AREA-LENGTH COMPARISON
Geometry	Geometry-flavored algebra	area	area method			AREA-PERIMETER CONSTRAINTS
Geometry	Geometric inequalities and optimization	area	area method			AREA-PERIMETER RELATIONS
Geometry	Geometry-flavored algebra	area	area method		estimate	AREA-WIDTH ESTIMATES
Geometry	Triangle centers and triangle configurations	altitude; area	area method			AREA/ALTITUDES
Geometry	Geometry-flavored algebra	area	area method			AREA/AVERAGES
Geometry	Geometry-flavored algebra	area	area method			AREA/DIAMETER
Geometry	Geometry-flavored algebra	area	area method			AREA/HEIGHTS
Algebra	Equations, substitutions, and transformations	area	area method			AREA/LENGTH IDENTITIES
Geometry	Geometry-flavored algebra	area; semiperimeter	area method			AREA/SEMIPERIMETER
Geometry	Geometry-flavored algebra	area	area method			AREAS
Algebra	Equations, substitutions, and transformations					ARGUMENT CHASING
Algebra	Analytic estimates and asymptotics			Rouch√©	comparison	ARGUMENT/ROUCH‚àö√¢-TYPE COMPARISON
Algebra	Equations, substitutions, and transformations					ARGUMENTS/SECTOR LEMMA
Number Theory	Additive and arithmetic structures	arithmetic computation			computation	ARITHMETIC COMPUTATION
Number Theory	Additive and arithmetic structures	arithmetic dynamics			process invariant	ARITHMETIC DYNAMICS
Geometry	Core Euclidean geometry	arithmetic progression of solutions				ARITHMETIC PROGRESSION OF SOLUTIONS
Combinatorics	Combinatorial structures and constructive methods	arithmetic progression				ARITHMETIC PROGRESSIONS/THRESHOLDS
Algebra	Extremal methods, monotonicity, and invariants		rigidity argument		rigidity	ARITHMETIC RIGIDITY
Combinatorics	Combinatorial algebra and counting	planar graph; arrangement				ARRANGEMENTS/PLANAR GRAPHS
Combinatorics	Counting and enumerative combinatorics	arrangement				ARRANGEMENTS/REGIONS
Combinatorics	Counting and enumerative combinatorics	array				ARRAYS
Combinatorics	Counting and enumerative combinatorics	array			bound	ARRAYS WITH RHOMBUS BOUNDS
Combinatorics	Counting and enumerative combinatorics	array; rook placement				ARRAYS/ROOK PLACEMENTS
Algebra	Inequalities and optimization				optimization	ASSIGNMENT OPTIMIZATION
Combinatorics	Combinatorial structures and constructive methods	assignment				ASSIGNMENTS
Combinatorics	Combinatorial structures and constructive methods	semigroup normal form				ASSOCIATIVE BANDS/SEMIGROUP NORMAL FORMS
Algebra	Analytic estimates and asymptotics	asymptotic binomial trick	asymptotic estimate			ASYMPTOTIC BINOMIAL TRICK
Algebra	Polynomials and algebraic manipulation		coefficient comparison; asymptotic estimate		comparison	ASYMPTOTIC COEFFICIENT COMPARISON
Algebra	Analytic estimates and asymptotics		asymptotic estimate		comparison	ASYMPTOTIC COMPARISON
Algebra	Analytic estimates and asymptotics		construction; asymptotic estimate		construction	ASYMPTOTIC CONSTRUCTION
Algebra	Analytic estimates and asymptotics	asymptotic directions	asymptotic estimate			ASYMPTOTIC DIRECTIONS
Algebra	Analytic estimates and asymptotics	asymptotic dominance	asymptotic estimate			ASYMPTOTIC DOMINANCE
Algebra	Sequences, recurrences, and series		asymptotic estimate		estimate	ASYMPTOTIC ESTIMATES
Algebra	Extremal methods, monotonicity, and invariants	asymptotic growth	asymptotic estimate			ASYMPTOTIC GROWTH
Algebra	Analytic estimates and asymptotics	asymptotic inequalities	asymptotic estimate			ASYMPTOTIC INEQUALITIES
Algebra	Analytic estimates and asymptotics	asymptotic integral	integral estimate; asymptotic estimate			ASYMPTOTIC INTEGRAL
Algebra	Extremal methods, monotonicity, and invariants		asymptotic estimate; rigidity argument		rigidity	ASYMPTOTIC RIGIDITY
Algebra	Analytic estimates and asymptotics	asymptotic squeeze	asymptotic estimate; squeeze argument		squeeze	ASYMPTOTIC SQUEEZE
Algebra	Extremal methods, monotonicity, and invariants		asymptotic estimate; stability argument		stability	ASYMPTOTIC STABILITY
Algebra	Analytic estimates and asymptotics	asymptotic subadditivity	asymptotic estimate			ASYMPTOTIC SUBADDITIVITY
Algebra	Analytic estimates and asymptotics	asymptotics at infinity	asymptotic estimate			ASYMPTOTICS AT INFINITY
Combinatorics	Combinatorial structures and constructive methods	augmentation				AUGMENTATION
Combinatorics	Combinatorial algebra and counting	augmenting paths / matching flavor	matching; augmenting path		augmentation	AUGMENTING PATHS/MATCHING FLAVOR
Number Theory	Divisibility and factorization					AURIFEUILLEAN-STYLE IDENTITY
Algebra	Discrete functions, floors, rounding, and base representation	automaton	automata method			AUTOMATA FLAVOR
Algebra	Discrete functions, floors, rounding, and base representation	automaton	automata method			AUTOMATA/BLOCKS
Algebra	Discrete functions, floors, rounding, and base representation	automaton	automata method		equivalence	AUTOMATA/EQUIVALENCE/DISTINGUISHING WORDS
Algebra	Sequences, recurrences, and series	automaton	automata method			AUTOMATA/RECURRENCES
Algebra	Discrete functions, floors, rounding, and base representation	automatic sequence				AUTOMATIC SEQUENCE
Combinatorics	Games, strategies, and processes	automaton / state compression	automaton/state method; state compression			AUTOMATON/STATE COMPRESSION
Algebra	Equations, substitutions, and transformations	automaton / transfer behavior	automaton/state method; transfer method			AUTOMATON/TRANSFER BEHAVIOR
Geometry	Circle geometry	circle	auxiliary construction			AUXILIARY CIRCLES
Geometry	Circle geometry	circumcircle	auxiliary construction			AUXILIARY CIRCUMCIRCLE
Geometry	Core Euclidean geometry		construction; auxiliary construction		construction	AUXILIARY CONSTRUCTION
Geometry	Core Euclidean geometry	intersection	auxiliary construction			AUXILIARY INTERSECTIONS
Geometry	Core Euclidean geometry	auxiliary point	construction; auxiliary construction		construction	AUXILIARY POINT CONSTRUCTION
Number Theory	Divisibility and factorization	quotient	auxiliary construction			AUXILIARY QUOTIENT
Geometry	Geometry-flavored algebra	angle configuration	auxiliary construction			AUXILIARY TRIANGLE
Combinatorics	Graph theory	average degree				AVERAGE DEGREE
Number Theory	Inequalities and estimates in number theory		averaging		bound	AVERAGING BOUND
Combinatorics	Games, strategies, and processes	averaging dynamics	averaging		process invariant	AVERAGING DYNAMICS
Combinatorics	Combinatorial algebra and counting	permutation	averaging			AVERAGING OVER PERMUTATIONS
Combinatorics	Pigeonhole, extremal principle, and averaging	averaging over states	averaging			AVERAGING OVER STATES
Combinatorics	Pigeonhole, extremal principle, and averaging	averaging over translations	averaging			AVERAGING OVER TRANSLATIONS
Combinatorics	Games, strategies, and processes	averaging processes	averaging		process invariant	AVERAGING PROCESSES
Algebra	Extremal methods, monotonicity, and invariants		averaging; rigidity argument		rigidity	AVERAGING RIGIDITY
Combinatorics	Pigeonhole, extremal principle, and averaging	tree	averaging			AVERAGING TREES
Algebra	Extremal methods, monotonicity, and invariants	arrangement	extremal method; averaging			AVERAGING/EXTREMAL ARRANGEMENTS
Algebra	Extremal methods, monotonicity, and invariants	averaging / extremal subset	extremal method; averaging			AVERAGING/EXTREMAL SUBSET
Algebra	Extremal methods, monotonicity, and invariants	averaging / invariants	invariant; averaging		invariant	AVERAGING/INVARIANTS
Combinatorics	Pigeonhole, extremal principle, and averaging	averaging / LP	averaging; linear programming relaxation			AVERAGING/LP
Algebra	Extremal methods, monotonicity, and invariants	averaging / minimax	averaging; minimax			AVERAGING/MINIMAX
Combinatorics	Combinatorial structures and constructive methods	avoidance	avoidance		avoidance	AVOIDANCE
Combinatorics	Set systems, posets, and extremal set theory	opposite pair	avoidance		avoidance	AVOIDANCE OF OPPOSITE PAIRS
Combinatorics	Combinatorial structures and constructive methods	avoidance patterns	avoidance		avoidance	AVOIDANCE PATTERNS
Geometry	Special configurations and special angles	angle configuration; axis-aligned rectangle				AXIS-ALIGNED RECTANGLES
Combinatorics	Coloring, tiling, grids, and invariants	axis-parallel line/covering	covering		covering	AXIS-PARALLEL COVERINGS
Combinatorics	Coloring, tiling, grids, and invariants	axis-parallel line/covering				AXIS-PARALLEL ‚Äö√Ñ√∫INTERVAL ON LINES‚Äö√Ñ√π
Algebra	Equations, substitutions, and transformations	B3 set				B3 SETS
Combinatorics	Combinatorial structures and constructive methods	back-and-forth				BACK-AND-FORTH
Algebra	Extremal methods, monotonicity, and invariants	backward descent	descent		descent	BACKWARD DESCENT
Algebra	Equations, substitutions, and transformations	Baire category obstruction			obstruction	BAIRE-STYLE OBSTRUCTION
Algebra	Equations, substitutions, and transformations	Baire category obstruction			uniformization	BAIRE-TYPE UNIFORMIZATION
Combinatorics	Games, strategies, and processes	balance strategy			strategy	BALANCE STRATEGY
Combinatorics	Games, strategies, and processes	balance scale				BALANCE-SCALE CODING
Combinatorics	Games, strategies, and processes	balance scale				BALANCE-SCALE LOGIC
Combinatorics	Games, strategies, and processes	balance-weighing				BALANCE-WEIGHING
Algebra	Sequences, recurrences, and series	sequence				BALANCED SEQUENCES
Combinatorics	Games, strategies, and processes	balancing processes			process invariant	BALANCING PROCESSES
Combinatorics	Combinatorial structures and constructive methods	balancing signs				BALANCING SIGNS
Algebra	Extremal methods, monotonicity, and invariants	balancing / invariants	invariant		invariant	BALANCING/INVARIANTS
Combinatorics	Counting and enumerative combinatorics	ballot path				BALLOT PATHS
Combinatorics	Combinatorial structures and constructive methods	barycenter				BARYCENTER
Geometry	Geometry-flavored algebra	area; barycentric coordinates	barycentric coordinates; area method			BARYCENTRIC AREAS
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates			BARYCENTRIC INTUITION
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates			BARYCENTRIC REASONING
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates			BARYCENTRIC-LIKE WEIGHTS
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates			BARYCENTRIC-STYLE RATIOS
Geometry	Geometry-flavored algebra	barycentric coordinates	affine method; barycentric coordinates; coordinate method			BARYCENTRIC/AFFINE COORDINATES
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates; analytic geometry			BARYCENTRIC/ANALYTIC GEOMETRY
Geometry	Geometry-flavored algebra	angle configuration; barycentric coordinates	barycentric coordinates; angle chasing			BARYCENTRIC/ANGLE CHASE
Geometry	Geometry-flavored algebra	angle configuration; barycentric coordinates	barycentric coordinates; angle chasing			BARYCENTRIC/ANGLE CHASING
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates; coordinate method; complex numbers			BARYCENTRIC/COMPLEX COORDINATES
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates; complex numbers			BARYCENTRIC/COMPLEX POSSIBLE
Algebra	Complex, trigonometric, and Fourier methods	barycentric coordinates	barycentric coordinates; trigonometric method			BARYCENTRIC/TRIG
Algebra	Complex, trigonometric, and Fourier methods	barycentric coordinates	barycentric coordinates; trigonometric method			BARYCENTRIC/TRIG RATIOS
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates; trilinear coordinates		computation	BARYCENTRIC/TRILINEAR COMPUTATION
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates; trilinear coordinates			BARYCENTRIC/TRILINEAR SIGNS
Geometry	Geometry-flavored algebra	barycentric coordinates	barycentric coordinates; vector method			BARYCENTRIC/VECTOR METHODS
Geometry	Geometry-flavored algebra	barycentric coordinates	affine method; barycentric coordinates; coordinate method			BARYCENTRICS/AFFINE COORDINATES
Algebra	Complex, trigonometric, and Fourier methods	barycentric coordinates	barycentric coordinates; trigonometric method			BARYCENTRICS/TRIG
Algebra	Discrete functions, floors, rounding, and base representation	base-3 representation	construction; base representation		construction	BASE 3 CONSTRUCTION
Algebra	Discrete functions, floors, rounding, and base representation	base powers	base representation			BASE POWERS
Algebra	Discrete functions, floors, rounding, and base representation	base-n representation	construction; base representation		construction	BASE-N CONSTRUCTION
Algebra	Discrete functions, floors, rounding, and base representation	base / carry tricks	base representation; carry analysis			BASE/CARRY TRICKS
Combinatorics	Combinatorial structures and constructive methods	batching				BATCHING
Combinatorics	Combinatorial structures and constructive methods	Beatty/Sturmian sequence				BEATTY/STURMIAN PATTERNS
Algebra	Inequalities and optimization	Bernoulli inequality expression	Bernoulli inequality	Bernoulli		BERNOULLI INEQUALITY
Combinatorics	Combinatorial structures and constructive methods	Bernoulli parity	parity argument			BERNOULLI PARITY
Number Theory	Number-theoretic sequences and sums	Bernoulli/Stickelberger sums	finite-sum congruence	Stickelberger		BERNOULLI/STICKELBERGER-TYPE SUMS
Algebra	Inequalities and optimization	bernstein / P√≥lya smoothing		P√≥lya		BERNSTEIN/P‚àö√¨LYA SMOOTHING
Algebra	Inequalities and optimization	Bessel-type expression	Bessel inequality	Bessel		BESSEL
Algebra	Inequalities and optimization	Bessel inequality expression	Bessel inequality	Bessel		BESSEL INEQUALITY
Algebra	Analytic estimates and asymptotics	beta-expansion	expansion			BETA-EXPANSION
Combinatorics	Combinatorial algebra and counting	beta-expansion	expansion			BETA-EXPANSIONS
Combinatorics	Combinatorial structures and constructive methods	betweenness relation				BETWEENNESS
Geometry	Triangle centers and triangle configurations	Bevan point				BEVAN POINT
Combinatorics	Graph theory	BFS ball	BFS layering			BFS BALLS
Combinatorics	Graph theory	BFS layering	BFS layering			BFS LAYERING
Combinatorics	Set systems, posets, and extremal set theory	block design				BIBD
Geometry	Special configurations and special angles	bicentric quadrilateral				BICENTRIC QUADRILATERAL
Combinatorics	Combinatorial algebra and counting	bijection / double counting	counting; double counting; bijection		counting	BIJECTION/DOUBLE COUNTING
Algebra	Extremal methods, monotonicity, and invariants	bijection / invariants	invariant; bijection		invariant	BIJECTION/INVARIANTS
Algebra	Sequences, recurrences, and series	bijection / recurrence	bijection			BIJECTION/RECURRENCE
Combinatorics	Combinatorial algebra and counting	bijective counting	counting		counting	BIJECTIVE COUNTING
Algebra	Algebraic structures and linear algebra				reduction	BILINEAR REDUCTION
Geometry	Transformations and geometric motion	billiard unfolding	unfolding			BILLIARD UNFOLDING
Geometry	Transformations and geometric motion	billiards path				BILLIARDS
Geometry	Geometry-flavored algebra	billiards path				BILLIARDS/ROTATION
Geometry	Triangle centers and triangle configurations	bimedians				BIMEDIANS
Combinatorics	Combinatorial structures and constructive methods	bin packing / greedy	greedy method; packing		packing	BIN PACKING/GREEDY
Algebra	Discrete functions, floors, rounding, and base representation	array; binary array	binary/base representation			BINARY ARRAYS
Algebra	Discrete functions, floors, rounding, and base representation	binary carrying	binary/base representation; carry analysis			BINARY CARRYING
Algebra	Discrete functions, floors, rounding, and base representation	binary code	binary/base representation			BINARY CODES
Algebra	Discrete functions, floors, rounding, and base representation		construction; binary/base representation		construction	BINARY CONSTRUCTION
Algebra	Discrete functions, floors, rounding, and base representation	binary decomposition	binary/base representation		decomposition	BINARY DECOMPOSITION
Algebra	Discrete functions, floors, rounding, and base representation	binary digit sum	binary/base representation			BINARY DIGIT SUM
Algebra	Discrete functions, floors, rounding, and base representation	binary encoding	binary/base representation			BINARY ENCODING
Algebra	Discrete functions, floors, rounding, and base representation	binary form	binary/base representation			BINARY FORMS
Algebra	Discrete functions, floors, rounding, and base representation	vectors; binary incidence vector	vector method; binary/base representation			BINARY INCIDENCE VECTORS
Algebra	Discrete functions, floors, rounding, and base representation	binary increments	binary/base representation			BINARY INCREMENTS
Algebra	Discrete functions, floors, rounding, and base representation	binary merging	binary/base representation		merging	BINARY MERGING
Algebra	Sequences, recurrences, and series	binary recursions	binary/base representation			BINARY RECURSIONS
Algebra	Discrete functions, floors, rounding, and base representation	binary selection	binary/base representation			BINARY SELECTION
Algebra	Discrete functions, floors, rounding, and base representation	binary shift graph	binary/base representation		shift	BINARY SHIFT GRAPH
Algebra	Discrete functions, floors, rounding, and base representation	binary sums	binary/base representation			BINARY SUMS
Algebra	Discrete functions, floors, rounding, and base representation	binary tree	binary/base representation			BINARY TREE ANCESTORS
Algebra	Discrete functions, floors, rounding, and base representation	binary tree	binary/base representation			BINARY TREE PROCESS
Algebra	Discrete functions, floors, rounding, and base representation	binary tree	binary/base representation			BINARY TREE VIEW
Algebra	Discrete functions, floors, rounding, and base representation	vectors; binary vector	vector method; binary/base representation			BINARY VECTORS
Algebra	Discrete functions, floors, rounding, and base representation	binary-tree strategy	binary/base representation		strategy	BINARY-TREE STRATEGY
Algebra	Discrete functions, floors, rounding, and base representation	binary / base-2 encoding	binary/base representation; base representation			BINARY/BASE-2 ENCODING
Algebra	Discrete functions, floors, rounding, and base representation	binary / base-4 pattern	binary/base representation; base representation			BINARY/BASE-4 PATTERN
Algebra	Discrete functions, floors, rounding, and base representation	Gray code	binary/base representation			BINARY/GRAY CODE
Algebra	Discrete functions, floors, rounding, and base representation	binary / gray-code structure	binary/base representation			BINARY/GRAY-CODE STRUCTURE
Algebra	Sequences, recurrences, and series	binet-type expressions		Binet		BINET-TYPE EXPRESSIONS
Number Theory	Number-theoretic sequences and sums	binomial conjugates				BINOMIAL CONJUGATES
Number Theory	Number-theoretic sequences and sums	binomial convolution				BINOMIAL CONVOLUTION
Combinatorics	Combinatorial algebra and counting	binomial counting	counting		counting	BINOMIAL COUNTING
Algebra	Polynomials and algebraic manipulation	binomial identity				BINOMIAL IDENTITY
Combinatorics	Counting and enumerative combinatorics	binomial layer				BINOMIAL LAYERS
Combinatorics	Counting and enumerative combinatorics	binomial parity				BINOMIAL PARITY
Algebra	Polynomials and algebraic manipulation	binomial polynomial	polynomial method			BINOMIAL POLYNOMIAL
Combinatorics	Counting and enumerative combinatorics	binomial symmetry				BINOMIAL SYMMETRY
Algebra	Polynomials and algebraic manipulation	binomial transform				BINOMIAL TRANSFORM
Algebra	Polynomials and algebraic manipulation	binomial transform				BINOMIAL TRANSFORMS
Number Theory	Number-theoretic sequences and sums	binomial truncation				BINOMIAL TRUNCATION
"""


SECOND_PASTED_TECHNIQUE_ROWS: tuple[LayeredTopicTagMapping, ...] = (
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Algorithms, automata, words, and constructive combinatorics",
        raw_tag="GREEDY",
        technique_tag="greedy argument",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Algorithms, automata, words, and constructive combinatorics",
        raw_tag="GREEDY ALGORITHMS",
        technique_tag="greedy algorithm",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Combinatorial geometry and topology",
        raw_tag="UNCROSSING",
        technique_tag="uncrossing",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Counting and enumerative combinatorics",
        raw_tag="DOUBLE COUNTING/AVERAGING",
        technique_tag="double counting / averaging",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Probability, entropy, coding, and information methods",
        raw_tag="LINEARITY OF EXPECTATION",
        technique_tag="expectation linearity",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Linear algebraic combinatorics",
        raw_tag="F_2 LINEAR ALGEBRA",
        technique_tag="F_2 linear algebra",
        preserve_source_domains=False,
        stored_technique="F_2 LINEAR ALGEBRA",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Linear algebraic combinatorics",
        raw_tag="INCIDENCE MATRICES",
        technique_tag="incidence matrix / rank method",
    ),
    _auxiliary_layer_mapping(
        area="Number Theory / Algebra",
        canonical_subtopic="p-adic and valuation methods",
        raw_tag="PARITY DESCENT",
        technique_tag="parity descent",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Coloring, tiling, grids, and invariants",
        raw_tag="PARITY INVARIANTS",
        technique_tag="parity invariant",
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Inequalities and optimization",
        raw_tag="TANGENT-LINE BOUND",
        technique_tag="tangent-line bound",
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Inequalities and optimization",
        raw_tag="LAGRANGE MULTIPLIERS",
        technique_tag="constrained optimization",
    ),
    _auxiliary_layer_mapping(
        area="Algebra / Combinatorics",
        canonical_subtopic="Inequalities and optimization",
        raw_tag="LP DUALITY",
        technique_tag="linear-programming duality",
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Equations, substitutions, and transformations",
        raw_tag="TRIG SUBSTITUTION",
        technique_tag="trigonometric substitution",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Geometry-flavored algebra",
        raw_tag="BARYCENTRICS/COORDINATES",
        technique_tag="barycentric coordinates",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Geometry-flavored algebra",
        raw_tag="COMPLEX/COORDINATES",
        technique_tag="complex coordinates",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Core Euclidean geometry",
        raw_tag="MASS POINTS",
        technique_tag="mass points",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Circle geometry",
        raw_tag="RADICAL AXIS/COAXALITY",
        technique_tag="radical-axis method",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="CROSS RATIO",
        technique_tag="cross-ratio method",
    ),
)

SECOND_PASTED_LEMMA_ROWS: tuple[LayeredTopicTagMapping, ...] = (
    _auxiliary_layer_mapping(
        area="Number Theory",
        canonical_subtopic="p-adic and valuation methods",
        raw_tag="KUMMER THEOREM",
        lemma_tag="Kummer theorem",
    ),
    _auxiliary_layer_mapping(
        area="Number Theory",
        canonical_subtopic="Congruences and modular arithmetic",
        raw_tag="EULER CRITERION",
        lemma_tag="Euler criterion",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="PASCAL THEOREM",
        lemma_tag="Pascal theorem",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="PASCAL",
        lemma_tag="Pascal theorem",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="MENELAUS/CEVA",
        lemma_tag="Menelaus / Ceva",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Geometry-flavored algebra",
        raw_tag="TRIG CEVA/MENELAUS",
        lemma_tag="Trig Ceva / Trig Menelaus",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Core Euclidean geometry",
        raw_tag="THALES THEOREM",
        lemma_tag="Thales theorem",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Core Euclidean geometry",
        raw_tag="LAW OF COSINES",
        lemma_tag="Law of cosines",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Set systems, posets, and extremal set theory",
        raw_tag="SPERNER",
        lemma_tag="Sperner theorem",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Circle geometry",
        raw_tag="PITOT",
        lemma_tag="Pitot theorem",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="NEWTON LINE",
        lemma_tag="Newton line",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="SIMSON-LINE FLAVOR",
        lemma_tag="Simson line",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="REIM/SPIRAL SIMILARITY",
        lemma_tag="Reim theorem / spiral similarity",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Circle geometry",
        raw_tag="MIQUEL/COAXALITY",
        lemma_tag="Miquel theorem",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Circle geometry",
        raw_tag="MIQUEL/RADICAL AXIS",
        lemma_tag="Miquel theorem / radical axis",
    ),
)

SECOND_PASTED_RAW_CORRECTION_ROWS: tuple[LayeredTopicTagMapping, ...] = (
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="EXTREMAL GRAPHS",
        technique_tag="extremal graph argument",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Linear algebraic combinatorics",
        raw_tag="GF(2) LINEAR ALGEBRA",
        object_tag="F_2 vector space",
        technique_tag="F_2 linear algebra",
        proof_role="invariant / contradiction",
        preserve_source_domains=False,
        stored_technique="F_2 LINEAR ALGEBRA",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Linear algebraic combinatorics",
        raw_tag="F_2 LINEAR ALGEBRA",
        object_tag="F_2 vector space",
        technique_tag="F_2 linear algebra",
        proof_role="invariant / contradiction",
        preserve_source_domains=False,
        stored_technique="F_2 LINEAR ALGEBRA",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Linear algebraic combinatorics",
        raw_tag="F2 LINEAR ALGEBRA",
        object_tag="F_2 vector space",
        technique_tag="F_2 linear algebra",
        proof_role="invariant / contradiction",
        preserve_source_domains=False,
        stored_technique="F_2 LINEAR ALGEBRA",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Triangle centers and triangle configurations",
        raw_tag="CIRCUMCENTERS",
        object_tag="circumcenter",
        technique_tag="circumcenter geometry",
        proof_role="center chasing",
        preserve_source_domains=False,
        stored_technique="CIRCUMCENTER",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Triangle centers and triangle configurations",
        raw_tag="CIRCUMCENTRES",
        object_tag="circumcenter",
        technique_tag="circumcenter geometry",
        proof_role="center chasing",
        preserve_source_domains=False,
        stored_technique="CIRCUMCENTER",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Core Euclidean geometry",
        raw_tag="INVARIANT ANGLE",
        technique_tag="angle invariant",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Geometry-flavored algebra",
        raw_tag="TRIG CEVA/MENELAUS",
        technique_tag="Trig Ceva / Trig Menelaus",
        lemma_tag="Trig Ceva / Trig Menelaus",
        preserve_source_domains=False,
    ),
)

SECOND_PASTED_PROOF_ROLE_ROWS: tuple[LayeredTopicTagMapping, ...] = (
    _auxiliary_layer_mapping(raw_tag="CONSTRUCTION/IMPOSSIBILITY", proof_role="construction / impossibility", status="method"),
    _auxiliary_layer_mapping(raw_tag="CONSTRUCTION/LOWER BOUND", proof_role="construction / lower bound", status="method"),
    _auxiliary_layer_mapping(
        raw_tag="CONSTRUCTION + LOWER BOUND",
        proof_role="construction / lower bound",
        status="method",
        stored_technique="CONSTRUCTION/LOWER BOUND",
    ),
    _auxiliary_layer_mapping(raw_tag="IMPOSSIBILITY", proof_role="impossibility", status="method"),
    _auxiliary_layer_mapping(raw_tag="COUNTEREXAMPLE SEARCH", proof_role="counterexample search", status="method"),
    _auxiliary_layer_mapping(raw_tag="COUNTEREXAMPLES", proof_role="counterexample", status="method"),
    _auxiliary_layer_mapping(raw_tag="EXISTENCE/UNIQUENESS", proof_role="existence / uniqueness", status="method"),
    _auxiliary_layer_mapping(raw_tag="CASE REDUCTION", proof_role="case reduction", status="method"),
    _auxiliary_layer_mapping(raw_tag="SEARCH STRATEGY", proof_role="search", status="method"),
    _auxiliary_layer_mapping(
        raw_tag="THRESHOLD ARGUMENT",
        technique_tag="threshold argument",
        proof_role="lower bound",
        status="method",
    ),
    _auxiliary_layer_mapping(
        raw_tag="EXTREMAL LOWER BOUND",
        technique_tag="extremal argument",
        proof_role="lower bound",
        status="method",
    ),
    _auxiliary_layer_mapping(
        raw_tag="RIGIDITY/CLASSIFICATION",
        technique_tag="rigidity",
        proof_role="classification",
        status="method",
    ),
    _auxiliary_layer_mapping(raw_tag="PROCESS TERMINATION", proof_role="termination", status="method"),
    _auxiliary_layer_mapping(raw_tag="CONSTRUCTIVE DESIGN", proof_role="construction", status="method"),
    _auxiliary_layer_mapping(raw_tag="CONSTRUCTIVE PROCESS", proof_role="construction", status="method"),
    _auxiliary_layer_mapping(raw_tag="CONSTRUCTIVE RECURSION", proof_role="recursive construction", status="method"),
)

THIRD_PASTED_LAYERED_TOPIC_TAG_MAPPINGS: tuple[LayeredTopicTagMapping, ...] = (
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HALL-TYPE THEOREM",
        object_tag="matching; transversal",
        technique_tag="Hall condition",
        lemma_tag="Hall",
        proof_role="existence",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HALL/CLOSURE",
        object_tag="matching; closure",
        technique_tag="Hall condition; closure",
        lemma_tag="Hall",
        proof_role="contradiction",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HALL/K√ñNIG FLAVOR",
        object_tag="bipartite matching",
        technique_tag="min-max duality",
        lemma_tag="Hall; Konig",
        proof_role="upper bound",
        preserve_source_domains=False,
        stored_technique="HALL/KONIG FLAVOR",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HALL/LP FLAVOR",
        object_tag="matching",
        technique_tag="LP duality",
        lemma_tag="Hall",
        proof_role="dual certificate",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Pigeonhole, extremal principle, and averaging",
        raw_tag="HALL/PIGEONHOLE",
        object_tag="matching",
        technique_tag="pigeonhole; Hall condition",
        lemma_tag="Hall",
        proof_role="contradiction",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HALL’S THEOREM / MATCHINGS",
        object_tag="matching; SDR",
        technique_tag="Hall condition",
        lemma_tag="Hall",
        proof_role="existence",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HALL‚ÄôS THEOREM / MATCHINGS",
        object_tag="matching; SDR",
        technique_tag="Hall condition",
        lemma_tag="Hall",
        proof_role="existence",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HAMILTONIAN CYCLE (CAMION)",
        object_tag="tournament; Hamiltonian cycle",
        technique_tag="strong connectivity",
        lemma_tag="Camion",
        proof_role="existence",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Probability, entropy, coding, and information methods",
        raw_tag="HAMMING BOUND",
        object_tag="code; Hamming ball",
        technique_tag="sphere packing",
        lemma_tag="Hamming bound",
        proof_role="upper bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HAMMING GRAPH",
        object_tag="Hamming graph",
        technique_tag="graph model",
        proof_role="classification",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Graph theory",
        raw_tag="HAMMING GRAPHS",
        object_tag="Hamming graph",
        technique_tag="graph model",
        proof_role="classification",
        preserve_source_domains=False,
        stored_technique="HAMMING GRAPH",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Probability, entropy, coding, and information methods",
        raw_tag="HAMMING METRIC",
        object_tag="Hamming metric",
        technique_tag="distance argument",
        proof_role="lower bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Probability, entropy, coding, and information methods",
        raw_tag="HAMMING WEIGHT",
        object_tag="Hamming weight",
        technique_tag="weight counting",
        proof_role="lower bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Inequalities and optimization",
        raw_tag="HARDY INEQUALITY",
        object_tag="inequality",
        technique_tag="sum/integral inequality",
        lemma_tag="Hardy",
        proof_role="upper bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Inequalities and optimization",
        raw_tag="HARDY-TYPE INEQUALITY",
        object_tag="inequality",
        technique_tag="Hardy-type estimate",
        lemma_tag="Hardy",
        proof_role="upper bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Number Theory",
        canonical_subtopic="p-adic and valuation methods",
        raw_tag="HENSEL-STYLE ARGUMENT",
        object_tag="p-adic root",
        technique_tag="lifting",
        lemma_tag="Hensel",
        proof_role="existence",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Number Theory",
        canonical_subtopic="p-adic and valuation methods",
        raw_tag="HENSEL-STYLE ARGUMENTS",
        object_tag="p-adic root",
        technique_tag="lifting",
        lemma_tag="Hensel",
        proof_role="existence",
        preserve_source_domains=False,
        stored_technique="HENSEL-STYLE ARGUMENT",
    ),
    _auxiliary_layer_mapping(
        area="Number Theory",
        canonical_subtopic="p-adic and valuation methods",
        raw_tag="HENSEL-STYLE LIFTING",
        object_tag="p-adic root",
        technique_tag="lifting",
        lemma_tag="Hensel",
        proof_role="existence",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="HARMONIC/POLAR",
        object_tag="polar; harmonic relation",
        technique_tag="pole-polar method",
        proof_role="classification",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Projective and advanced geometry",
        raw_tag="HARMONIC BUNDLES/COAXALITY",
        object_tag="harmonic bundle; coaxal circles",
        technique_tag="projective ratio; coaxality",
        proof_role="classification",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Set systems, posets, and extremal set theory",
        raw_tag="HELLY-TYPE LEMMA",
        object_tag="intersection family",
        technique_tag="local-to-global intersection",
        lemma_tag="Helly",
        proof_role="existence",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Transformational geometry",
        raw_tag="HOMOTHETY AT DDD",
        object_tag="homothety center",
        technique_tag="homothety",
        proof_role="construction",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Transformational geometry",
        raw_tag="HOMOTHETY / ANGLE CHASE",
        object_tag="figures",
        technique_tag="homothety; angle chase",
        proof_role="construction",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Set systems, posets, and extremal set theory",
        raw_tag="HYPERGRAPH MATCHING",
        object_tag="hypergraph",
        technique_tag="matching",
        proof_role="existence",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Set systems, posets, and extremal set theory",
        raw_tag="HYPERGRAPH COVERING",
        object_tag="hypergraph",
        technique_tag="covering",
        proof_role="upper bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Set systems, posets, and extremal set theory",
        raw_tag="HYPERGRAPH INDEPENDENCE",
        object_tag="hypergraph",
        technique_tag="independence",
        proof_role="lower bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Inequalities and optimization",
        raw_tag="H√ñLDER-TYPE INEQUALITY",
        object_tag="inequality",
        technique_tag="Hölder",
        lemma_tag="Hölder",
        proof_role="upper bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Inequalities and optimization",
        raw_tag="HOLDER-TYPE BOUNDS",
        object_tag="norm; sum",
        technique_tag="Hölder-type bound",
        lemma_tag="Hölder",
        proof_role="upper bound",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Core Euclidean geometry",
        raw_tag="HIDDEN SIMILARITY",
        object_tag="similar triangles",
        technique_tag="hidden similarity",
        proof_role="classification",
        preserve_source_domains=False,
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Triangle centers and triangle configurations",
        raw_tag="INCENTER / INCIRCLE",
        object_tag="incenter; incircle",
        technique_tag="angle/length chase",
        proof_role="classification",
        preserve_source_domains=False,
        stored_technique="INCENTER/INCIRCLE",
    ),
)


SECOND_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE = r"""Area	Canonical Subtopic	Object tag	Technique tag	Lemma/Theorem tag	Proof role	Raw imported tag
Geometry	Core Euclidean geometry		ratio chase			RATIO CHASE
Combinatorics	Coloring, tiling, grids, and invariants	rectangles				RECTANGLES
Number Theory; Combinatorics	Games, strategies, and processes		reverse process			REVERSE PROCESS
Algebra	Inequalities and optimization		majorization / smoothing	Schur; Maclaurin; Muirhead		SCHUR / MACLAURIN / MUIRHEAD
Number Theory; Combinatorics	Games, strategies, and processes		self-reference			SELF-REFERENCE
Algebra	Equations, substitutions, and transformations		sign-change analysis			SIGN CHANGES
Geometry; Combinatorics	Core Euclidean geometry		signed distances			SIGNED DISTANCES
Geometry	Circle geometry	Simson lines				SIMSON LINES
Algebra; Combinatorics	Combinatorial algebra and counting		sorting argument			SORTING
Geometry	Special configurations and special angles	special angles				SPECIAL ANGLES
Combinatorics	Counting and enumerative combinatorics		stars and bars		counting	STARS AND BARS
Algebra	Equations, substitutions, and transformations		symmetry reduction			SYMMETRIC CONSTRAINT
Algebra	Inequalities and optimization		symmetric inequality method			SYMMETRIC INEQUALITIES
Algebra	Inequalities and optimization		symmetric inequality method			SYMMETRIC INEQUALITY
Algebra	Equations, substitutions, and transformations		symmetric system reduction			SYMMETRIC SYSTEMS
Geometry	Circle geometry	tangency configuration	tangency criterion		criterion	TANGENCY CRITERION
Geometry	Circle geometry		tangent method			TANGENT
Geometry	Circle geometry		tangent line method			TANGENT LINE
Combinatorics	Coloring, tiling, grids, and invariants		tiling invariant		invariant	TILING INVARIANT
Combinatorics	Coloring, tiling, grids, and invariants		tiling invariant		invariant	TILINGS/INVARIANTS
Combinatorics	Coloring, tiling, grids, and invariants	tilings / packings				TILINGS/PACKINGS
Geometry	Core Euclidean geometry		trigonometric ratio chase	Trigonometric Ceva		TRIGONOMETRIC CEVA
Algebra	Polynomials and algebraic manipulation		zero-set method			ZERO-SET METHOD
Geometry	Circle geometry	circle configurations				ADVANCED CIRCLE GEOMETRY
Combinatorics	Combinatorial algebra and counting	adversarial game			strategy	ADVERSARIAL GAME
Number Theory; Combinatorics	Games, strategies, and processes		adversarial strategy		strategy	ADVERSARIAL STRATEGY
Algebra	Equations, substitutions, and transformations		affine normalization			AFFINE NORMALIZATION
Algebra	Algebraic structures and linear algebra		affine transformations			AFFINE TRANSFORMATIONS
Geometry	Geometry-flavored algebra		affine / coordinate method			AFFINE/COORDINATE GEOMETRY
Geometry	Core Euclidean geometry		algebraic geometry method			ALGEBRAIC GEOMETRY
Algebra	Algebraic structures and linear algebra	algebraic structures / linear algebra				ALGEBRAIC STRUCTURES AND LINEAR ALGEBRA
Geometry	Triangle centers and triangle configurations	altitude configuration				ALTITUDE GEOMETRY
Geometry	Special configurations and special angles	antipodes				ANTIPODES
Geometry	Circle geometry	Apollonius circles	ratio locus			APOLLONIUS CIRCLES
Geometry	Circle geometry	circle arcs				ARCS
Geometry	Core Euclidean geometry		area decomposition		decomposition	AREA DECOMPOSITION
Geometry	Core Euclidean geometry		area estimates		upper/lower bound	AREA ESTIMATES
Algebra	Discrete functions, floors, rounding, and base representation	automata				AUTOMATA
Algebra	Inequalities and optimization		averaging			AVERAGES
Number Theory; Combinatorics	Games, strategies, and processes		backward induction		induction	BACKWARD INDUCTION
Geometry	Geometry-flavored algebra		barycentric / trilinear coordinates			BARYCENTRIC/TRILINEAR COORDINATES
Algebra	Sequences, recurrences, and series		binary recursion			BINARY RECURSION
Algebra	Discrete functions, floors, rounding, and base representation	binary structure				BINARY STRUCTURE
Combinatorics	Combinatorial algebra and counting	bipartite matching				BIPARTITE MATCHING
Algebra	Algebraic structures and linear algebra		matrix polynomial reduction	Cayley-Hamilton theorem		CAYLEY-HAMILTON
Geometry	Triangle centers and triangle configurations	cevian configuration				CEVIAN GEOMETRY
Geometry	Circle geometry	circle				CIRCLE
Geometry	Circle geometry	circle chords				CIRCLE CHORDS
Geometry	Circle geometry	circle / tangent				CIRCLE/TANGENT
Combinatorics	Algorithms, automata, words, and constructive combinatorics	circular words				CIRCULAR WORDS
Geometry	Triangle centers and triangle configurations	circumcentres				CIRCUMCENTRES
Algebra; Number Theory	Equations, substitutions, and transformations		clearing denominators			CLEARING DENOMINATORS
Algebra	Polynomials and algebraic manipulation		coefficient method			COEFFICIENT METHODS
Combinatorics	Coloring, tiling, grids, and invariants		coloring invariant		invariant	COLORING INVARIANTS
Geometry	Geometry-flavored algebra		complex-number geometry			COMPLEX GEOMETRY
Combinatorics	Algorithms, automata, words, and constructive combinatorics		constructive algorithm		construction	CONSTRUCTIVE ALGORITHMS
Algebra; Combinatorics	Combinatorial algebra and counting	continuants				CONTINUANTS
Algebra	Analytic estimates and asymptotics		convergence argument			CONVERGENCE
Geometry	Special configurations and special angles	convex polygon				CONVEX POLYGON
Geometry	Geometry-flavored algebra		coordinates + angle chase			COORDINATES/ANGLE CHASE
Geometry	Geometry-flavored algebra		coordinate / projective method			COORDINATES/PROJECTIVE GEOMETRY
Geometry	Geometry-flavored algebra		coordinate / trilinear method			COORDINATES/TRILINEARS
Geometry	Core Euclidean geometry		metric computation	Cosine law		COSINE LAW
Combinatorics	Combinatorial algebra and counting	critical graphs				CRITICAL GRAPHS
Combinatorics	Graph theory		cycle decomposition		decomposition	CYCLE DECOMPOSITION
Number Theory; Combinatorics	Combinatorial algebra and counting	cyclic action	cyclic action / group action			CYCLIC ACTION
Algebra	Equations, substitutions, and transformations	cyclic equations	cyclic equation reduction			CYCLIC EQUATIONS
Algebra	Equations, substitutions, and transformations	cyclic products	cyclic product manipulation			CYCLIC PRODUCTS
Algebra	Polynomials and algebraic manipulation	cyclotomic roots				CYCLOTOMIC ROOTS
Combinatorics	Combinatorial algebra and counting	De Bruijn graph				DE BRUIJN GRAPH
Combinatorics	Probability, entropy, coding, and information methods		decision tree method			DECISION TREES
Number Theory	Number-theoretic algebra	denominators	denominator control			DENOMINATORS
Algebra	Discrete functions, floors, rounding, and base representation		digit counting		counting	DIGIT COUNTING
Combinatorics	Combinatorial algebra and counting	directed graphs				DIRECTED GRAPHS
Combinatorics	Graph theory	domination				DOMINATION
Combinatorics	Games, strategies, and processes		process invariant / dynamics			DYNAMICAL PROCESS
Number Theory	Additive and multiplicative number theory		Egyptian-fraction decomposition			EGYPTIAN-FRACTION FLAVOR
Algebra	Equations, substitutions, and transformations		equation solving			EQUATIONS
Geometry	Geometry-flavored algebra		rotation by 60 degrees			EQUILATERAL ROTATIONS
Combinatorics	Set systems, posets, and extremal set theory		monotone subsequence / convex-position argument	Erd≈ës‚ÄìSzekeres theorem		ERD‚âà√™S‚Äö√Ñ√¨SZEKERES
Algebra; Number Theory; Combinatorics	Additive and multiplicative number theory		expansion			EXPANSION
Combinatorics	Probability, entropy, coding, and information methods		expectation method			EXPECTATION
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL AREA
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL ARRAYS
Combinatorics	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL DEGREE
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL DENSITY
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		sharpness example	EXTREMAL EXAMPLE
Combinatorics	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL GRIDS
Algebra	Extremal methods, monotonicity, and invariants	extremal matrix	extremal argument		extremal choice	EXTREMAL MATRIX
Combinatorics	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL PATH
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL PERMUTATIONS
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL SELECTION
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL VALUES
Algebra; Number Theory	Number-theoretic algebra	fibers	fiber counting			FIBERS
Geometry; Combinatorics	Set systems, posets, and extremal set theory	finite geometry				FINITE GEOMETRY
Number Theory; Combinatorics	Additive and multiplicative number theory		finite optimization		optimization	FINITE OPTIMIZATION
Number Theory; Combinatorics	Games, strategies, and processes	finite search	finite search		case analysis	FINITE SEARCH
Algebra; Number Theory	Additive and multiplicative number theory		Frobenius method	Frobenius coin theorem		FROBENIUS
Algebra; Combinatorics	Functional equations	functional graph	functional-equation method			FUNCTIONAL GRAPH
Algebra	Algebraic structures and linear algebra	Gram matrices				GRAM MATRICES
Combinatorics	Combinatorial algebra and counting	graph cycles				GRAPH CYCLES
Combinatorics	Combinatorial algebra and counting	graph labeling				GRAPH LABELING
Combinatorics	Combinatorial algebra and counting	graph parity	graph parity		parity	GRAPH PARITY
Combinatorics	Combinatorial algebra and counting	graph reachability	reachability argument			GRAPH REACHABILITY
Combinatorics	Graph theory	graph walks				GRAPH WALKS
Algebra; Combinatorics	Extremal methods, monotonicity, and invariants		grid extremal argument		extremal choice	GRID EXTREMAL
Combinatorics	Coloring, tiling, grids, and invariants		grid process			GRID PROCESSES
Combinatorics	Graph theory		matching argument	Hall's theorem		HALL‚Äö√Ñ√¥S THEOREM
Number Theory; Combinatorics	Graph theory	Hamiltonian cycle				HAMILTONIAN CYCLE
Combinatorics	Probability, entropy, coding, and information methods	Hamming distance				HAMMING DISTANCE
Geometry	Core Euclidean geometry	heavy configuration				HEAVY CONFIGURATION
Combinatorics	Set systems, posets, and extremal set theory	hypergraph coloring				HYPERGRAPH COLORING
Combinatorics	Combinatorial algebra and counting	impartial game			strategy	IMPARTIAL GAME
Geometry	Triangle centers and triangle configurations	incenter / circumcenter				INCENTER/CIRCUMCENTER
Combinatorics	Graph theory	independence number				INDEPENDENCE NUMBER
Combinatorics	Graph theory	independent sets				INDEPENDENT SETS
Combinatorics	Graph theory	induced cycles				INDUCED CYCLES
Number Theory	Additive and multiplicative number theory	infinite families	parametric construction		construction	INFINITE FAMILIES
Number Theory	Number-theoretic algebra	integer functions				INTEGER FUNCTIONS
Number Theory; Combinatorics	Counting and enumerative combinatorics	integer partitions				INTEGER PARTITIONS
Number Theory	Number-theoretic algebra		integrality argument			INTEGRALITY
Algebra	Analytic estimates and asymptotics		integration by parts			INTEGRATION BY PARTS
Combinatorics	Combinatorial algebra and counting	interval graphs				INTERVAL GRAPHS
Algebra	Extremal methods, monotonicity, and invariants		parity invariant		invariant	INVARIANTS/PARITY
Algebra	Extremal methods, monotonicity, and invariants		potential invariant		invariant	INVARIANTS/POTENTIAL
Geometry	Geometry-flavored algebra		inversion			INVERSION AT III
Geometry	Geometry-flavored algebra		inversion / projective method			INVERSION/PROJECTIVE FLAVOR
Algebra	Inequalities and optimization		linear inequalities			LINEAR INEQUALITIES
Algebra	Extremal methods, monotonicity, and invariants		linear invariant		invariant	LINEAR INVARIANTS
Combinatorics	Graph theory	longest path				LONGEST PATH
Algebra	Sequences, recurrences, and series		max-plus recurrence			MAX-PLUS RECURRENCE
Algebra	Analytic estimates and asymptotics		maximum modulus principle			MAXIMUM MODULUS
Geometry	Core Euclidean geometry		metric condition			METRIC CONDITION
Geometry	Core Euclidean geometry		metric relation			METRIC RELATION
Geometry	Core Euclidean geometry	midpoint line	midpoint line			MIDPOINT LINE
Combinatorics	Pigeonhole, extremal principle, and averaging		minimal counterexample		contradiction / minimal counterexample	MINIMAL COUNTEREXAMPLE
Geometry	Triangle centers and triangle configurations	mixtilinear circle				MIXTILINEAR CIRCLE
Algebra	Extremal methods, monotonicity, and invariants		monovariant		invariant	MONOVARIANTS
Algebra	Algebraic structures and linear algebra	nilpotent matrices				NILPOTENT MATRICES
Number Theory	Number-theoretic algebra	number theory				NUMBER THEORY
Combinatorics	Graph theory	odd cycles				ODD CYCLES
Algebra	Inequalities and optimization		one-variable reduction			ONE-VARIABLE REDUCTION
Combinatorics	Combinatorial algebra and counting	ordered sets				ORDERED SETS
Geometry	Triangle centers and triangle configurations	orthic projections				ORTHIC PROJECTIONS
Geometry	Triangle centers and triangle configurations	orthocenter configuration				ORTHOCENTER GEOMETRY
Geometry	Circle geometry	orthogonal circles				ORTHOGONAL CIRCLES
Geometry	Special configurations and special angles	parallelogram				PARALLELOGRAM GEOMETRY
Geometry; Combinatorics	Core Euclidean geometry		parity construction		parity	PARITY CONSTRUCTION
Number Theory; Combinatorics	Counting and enumerative combinatorics	partitions				PARTITION
Combinatorics	Graph theory	paths				PATHS
Combinatorics	Combinatorial algebra and counting		periodic construction		construction	PERIODIC CONSTRUCTION
Combinatorics	Combinatorial algebra and counting	permutation groups				PERMUTATION GROUPS
Geometry	Core Euclidean geometry		perpendicular projection			PERPENDICULAR PROJECTIONS
Combinatorics	Coloring, tiling, grids, and invariants		planar duality			PLANAR DUALITY
Combinatorics	Combinatorial algebra and counting	planar graph				PLANAR GRAPH
Combinatorics	Combinatorial algebra and counting	planar graph counting	planar graph counting		counting	PLANAR GRAPH COUNTING
Geometry	Geometry-flavored algebra		polar coordinates			POLAR COORDINATES
Geometry	Geometry-flavored algebra		pole-polar method			POLE-POLAR FLAVOR
Algebra	Polynomials and algebraic manipulation		irreducibility argument			POLYNOMIAL IRREDUCIBILITY
Algebra	Polynomials and algebraic manipulation		polynomial map method			POLYNOMIAL MAPS
Algebra	Extremal methods, monotonicity, and invariants		potential invariant		invariant	POTENTIAL/INVARIANT
Geometry	Geometry-flavored algebra		projective / affine method			PROJECTIVE/AFFINE GEOMETRY
Geometry	Geometry-flavored algebra		projective / inversion method			PROJECTIVE/INVERSION
Algebra; Number Theory	Algebraic number theory flavor	quadratic irrationals				QUADRATIC IRRATIONALS
Algebra; Geometry	Inequalities and optimization		quadratic minimization		optimization	QUADRATIC MINIMIZATION
Geometry	Special configurations and special angles	quadrilateral				QUADRILATERAL
Geometry	Special configurations and special angles	quadrilateral geometry				QUADRILATERAL GEOMETRY
Combinatorics	Set systems, posets, and extremal set theory		Ramsey-type argument			RAMSEY FLAVOR
Algebra	Functional equations		rational-domain reduction			RATIONAL DOMAIN
Algebra; Number Theory	Number-theoretic algebra	rational points				RATIONAL POINTS
Algebra	Sequences, recurrences, and series		recursive construction		construction	RECURSIVE CONSTRUCTION
Geometry	Special configurations and special angles	rhombus				RHOMBUS GEOMETRY
Algebra	Polynomials and algebraic manipulation	rooted trees				ROOTED TREES
Combinatorics	Games, strategies, and processes		rotating line method			ROTATING LINE
Algebra	Sequences, recurrences, and series		sequence inequality method			SEQUENCES/INEQUALITIES
Algebra; Combinatorics	Graph theory		shortest path method			SHORTEST PATHS
Number Theory	Additive and multiplicative number theory	Sidon sets				SIDON SETS
Combinatorics	Combinatorial algebra and counting		sign-reversing involution		cancellation	SIGN-REVERSING INVOLUTION
Geometry	3D and solid geometry	spherical geometry				SPHERICAL GEOMETRY
Geometry	Core Euclidean geometry	spiral similarities				SPIRAL SIMILARITIES
Geometry	Core Euclidean geometry	spiral similarity / Miquel configuration				SPIRAL SIMILARITY/MIQUEL
Geometry; Combinatorics	Core Euclidean geometry		squared-distance method			SQUARED DISTANCES
Algebra	Extremal methods, monotonicity, and invariants		stability argument		stability	STABILITY
Combinatorics	Counting and enumerative combinatorics	Stirling numbers				STIRLING NUMBERS
Geometry	Triangle centers and triangle configurations	symmedian / isogonal configuration				SYMMEDIAN/ISOGONAL
Geometry	Triangle centers and triangle configurations	symmedians				SYMMEDIANS
Algebra	Equations, substitutions, and transformations		symmetry reduction			SYMMETRIC CONSTRAINTS
Combinatorics	Set systems, posets, and extremal set theory	symmetric difference				SYMMETRIC DIFFERENCE
Combinatorics	Set systems, posets, and extremal set theory	transversals				TRANSVERSALS
Geometry	Geometry-flavored algebra	triangle configuration				TRIANGLE GEOMETRY
Combinatorics	Coloring, tiling, grids, and invariants	triangular lattice				TRIANGULAR LATTICE
Algebra	Complex, trigonometric, and Fourier methods		trigonometric chase			TRIG CHASE
Algebra	Complex, trigonometric, and Fourier methods		trigonometric ratios			TRIG RATIOS
Geometry	Circle geometry	two-circle configuration				TWO CIRCLES
Algebra	Algebraic structures and linear algebra	units				UNITS
Algebra	Inequalities and optimization		variational inequality method			VARIATIONAL INEQUALITY
Number Theory; Combinatorics	Graph theory	vertex cover				VERTEX COVER
Algebra	Inequalities and optimization		weighted averaging			WEIGHTED AVERAGES
Algebra; Combinatorics	Inequalities and optimization		weighted sum method			WEIGHTED SUMS
Geometry	3D and solid geometry	3D analytic geometry	coordinate method			3D ANALYTIC GEOMETRY
Algebra	Functional equations	additive functions				ADDITIVE FUNCTIONS
Combinatorics	Combinatorial algebra and counting		adjacent transpositions			ADJACENT TRANSPOSITIONS
Geometry	Core Euclidean geometry		synthetic geometry			ADVANCED SYNTHETIC GEOMETRY
Combinatorics	Games, strategies, and processes		adversarial process		strategy	ADVERSARIAL PROCESS
Algebra	Algebraic structures and linear algebra		affine maps			AFFINE MAPS
Geometry	Geometry-flavored algebra	affine setup	affine setup			AFFINE SETUP
Geometry	Geometry-flavored algebra		affine / projective method			AFFINE/PROJECTIVE FLAVOR
Geometry	Geometry-flavored algebra		affine / projective method			AFFINE/PROJECTIVE GEOMETRY
Combinatorics	Graph theory	alternating cycles				ALTERNATING CYCLES
Algebra; Combinatorics	Combinatorial algebra and counting		alternating sums			ALTERNATING SUMS
Geometry	Special configurations and special angles		angle-bisector symmetry			ANGLE BISECTOR SYMMETRY
Geometry	Special configurations and special angles		angle constraints			ANGLE CONSTRAINTS
Combinatorics	Set systems, posets, and extremal set theory	antichains				ANTICHAINS
Geometry	Special configurations and special angles	antipode				ANTIPODE
Algebra	Analytic estimates and asymptotics		approximation			APPROXIMATION
Geometry	Core Euclidean geometry		area formula			AREA FORMULA
Geometry	Geometry-flavored algebra		area formulas			AREA FORMULAS
Geometry	Core Euclidean geometry		area maximization		optimization	AREA MAXIMIZATION
Algebra	Functional equations	arithmetic functional equations	arithmetic functional equation method			ARITHMETIC FUNCTIONAL EQUATIONS
Algebra; Combinatorics	Combinatorial algebra and counting		associativity argument			ASSOCIATIVITY
Algebra	Extremal methods, monotonicity, and invariants		asymptotic extremal argument		extremal choice	ASYMPTOTIC EXTREMAL
Number Theory; Combinatorics	Coloring, tiling, grids, and invariants	bin packing				BIN PACKING
Combinatorics	Algorithms, automata, words, and constructive combinatorics	binary strings				BINARY STRINGS
Algebra; Number Theory	Algebraic number theory flavor		binomial-basis expansion			BINOMIAL BASIS
Algebra	Sequences, recurrences, and series	bounded sequences	boundedness argument		upper/lower bound	BOUNDED SEQUENCES
Number Theory; Combinatorics	Counting and enumerative combinatorics		orbit counting	Burnside lemma	counting	BURNSIDE
Combinatorics	Combinatorial algebra and counting	cactus graphs				CACTUS GRAPHS
Algebra; Number Theory; Combinatorics	Additive and multiplicative number theory		cancellation		cancellation	CANCELLATION
Algebra	Inequalities and optimization		norm / inequality comparison	Cauchy-Schwarz; Minkowski inequality		CAUCHY/MINKOWSKI
Algebra	Algebraic structures and linear algebra	field characteristic				CHARACTERISTIC
Algebra	Algebraic structures and linear algebra	characteristic 2				CHARACTERISTIC 2
Algebra	Algebraic structures and linear algebra	characteristic polynomials				CHARACTERISTIC POLYNOMIALS
Combinatorics	Pigeonhole, extremal principle, and averaging		charging argument		counting / lower bound	CHARGING ARGUMENT
Combinatorics	Coloring, tiling, grids, and invariants	checkerboard coloring	coloring invariant		invariant	CHECKERBOARD COLORING
Geometry	Circle geometry	chord length				CHORD LENGTH
Geometry	Circle geometry	circle angles				CIRCLE ANGLES
Geometry	Circle geometry	circle arcs				CIRCLE ARCS
Geometry	Circle geometry	circle center				CIRCLE CENTER
Algebra; Geometry	Circle geometry	circle equation				CIRCLE EQUATION
Geometry	Circle geometry	circle pencils				CIRCLE PENCILS
Geometry	Triangle centers and triangle configurations	circumcenter loci				CIRCUMCENTER LOCI
Geometry	Circle geometry	circumcircle arcs				CIRCUMCIRCLE ARCS
Geometry	Circle geometry	circumcircle	cyclicity criterion		criterion	CIRCUMCIRCLE CRITERION
Geometry	Circle geometry	circumradius				CIRCUMRADIUS
Geometry	Circle geometry	circumradius	metric formula			CIRCUMRADIUS FORMULA
Number Theory; Combinatorics	Additive and multiplicative number theory	combinatorial number theory				COMBINATORIAL NUMBER THEORY
Combinatorics	Graph theory	common neighborhoods				COMMON NEIGHBORHOODS
Combinatorics	Combinatorial algebra and counting		complementation			COMPLEMENTS
Algebra	Sequences, recurrences, and series	complete sequence				COMPLETE SEQUENCE
Geometry	Geometry-flavored algebra		complex numbers / vectors			COMPLEX NUMBERS/VECTORS
Algebra	Polynomials and algebraic manipulation	complex polynomials				COMPLEX POLYNOMIALS
Geometry	Geometry-flavored algebra		complex / coordinate geometry			COMPLEX/COORDINATE GEOMETRY
Number Theory	Number-theoretic algebra	consecutive integers				CONSECUTIVE INTEGERS
Algebra	Equations, substitutions, and transformations		constant analysis			CONSTANTS
Combinatorics	Games, strategies, and processes		constructive strategy		strategy	CONSTRUCTIVE STRATEGY
Algebra; Geometry; Number Theory	Equations, substitutions, and transformations		contraction			CONTRACTION
Algebra; Geometry	Geometry-flavored algebra		coordinate / trigonometric method			COORDINATE/TRIG
Algebra; Geometry	Geometry-flavored algebra		coordinate / trigonometric geometry			COORDINATE/TRIG GEOMETRY
Geometry	Geometry-flavored algebra		coordinates / synthetic method			COORDINATES/SYNTHETIC GEOMETRY
Combinatorics	Combinatorial algebra and counting		crossing argument			CROSSINGS
Algebra; Number Theory	Number-theoretic algebra	cubes				CUBES
Algebra	Polynomials and algebraic manipulation	cubic roots				CUBIC ROOTS
Combinatorics	Graph theory	cycle space				CYCLE SPACE
Geometry	Circle geometry	cyclic	cyclic symmetry			CYCLIC
Geometry; Combinatorics	Circle geometry	cyclic arcs	cyclic symmetry			CYCLIC ARCS
Combinatorics	Algorithms, automata, words, and constructive combinatorics	cyclic construction	cyclic construction		construction	CYCLIC CONSTRUCTION
Algebra	Extremal methods, monotonicity, and invariants	cyclic descent	cyclic descent			CYCLIC DESCENT
Algebra; Number Theory	Number-theoretic algebra	cyclic fractions	cyclic fractions			CYCLIC FRACTIONS
Combinatorics	Combinatorial algebra and counting	cyclic permutations	cyclic symmetry			CYCLIC PERMUTATIONS
Algebra	Sequences, recurrences, and series	cyclic recurrence	cyclic recurrence			CYCLIC RECURRENCE
Number Theory; Combinatorics	Algorithms, automata, words, and constructive combinatorics	cyclic shifts	cyclic shifts			CYCLIC SHIFTS
Algebra	Equations, substitutions, and transformations	cyclic systems	cyclic system reduction			CYCLIC SYSTEMS
Geometry	Circle geometry	cyclic trapezoid	cyclic symmetry			CYCLIC TRAPEZOID
Combinatorics	Combinatorial algebra and counting		degree counting		counting	DEGREE COUNTING
Combinatorics	Graph theory	degree sequences				DEGREE SEQUENCES
Combinatorics	Counting and enumerative combinatorics	derangements				DERANGEMENTS
Number Theory	Number-theoretic algebra		diagonalization			DIAGONALIZATION
Geometry; Combinatorics	Core Euclidean geometry	diagonals				DIAGONALS
Geometry; Combinatorics	Core Euclidean geometry		diameter bound		upper/lower bound	DIAMETER BOUND
Geometry	Core Euclidean geometry		directed ratios			DIRECTED RATIOS
Combinatorics	Pigeonhole, extremal principle, and averaging		discharging			DISCHARGING
Algebra	Complex, trigonometric, and Fourier methods		discrete Fourier transform			DISCRETE FOURIER TRANSFORM
Algebra; Combinatorics	Combinatorial algebra and counting	discrete harmonic functions	discrete harmonic functions			DISCRETE HARMONIC FUNCTIONS
Geometry; Combinatorics	Core Euclidean geometry	disks				DISKS
Geometry	3D and solid geometry	disphenoid				DISPHENOID
Combinatorics	Combinatorial algebra and counting	distance graphs				DISTANCE GRAPHS
Geometry	Core Euclidean geometry		distance minimization		optimization	DISTANCE MINIMIZATION
Algebra	Algebraic structures and linear algebra	division rings				DIVISION RINGS
Algebra	Discrete functions, floors, rounding, and base representation		dyadic blocking			DYADIC BLOCKS
Number Theory	Algebraic number theory flavor	Eisenstein integers				EISENSTEIN INTEGERS
Geometry	Special configurations and special angles		equal-angle chase			EQUAL ANGLES
Geometry	Circle geometry		power of a point			EQUAL POWER
Geometry	Special configurations and special angles	equilateral configuration	construction		construction	EQUILATERAL CONSTRUCTION
Geometry	Circle geometry	Euler circle				EULER CIRCLE
Geometry	Triangle centers and triangle configurations	Euler configuration	center relation	Euler relation		EULER RELATION
Geometry	Circle geometry	excircles / incircles				EXCIRCLES/INCIRCLES
Number Theory	Additive and multiplicative number theory		explicit formula			EXPLICIT FORMULA
Algebra	Equations, substitutions, and transformations	exponentials				EXPONENTIALS
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL BOUND
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL CASES
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL CHAINS
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL COMBINATORICS
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL DESIGN
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL INDUCTION
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL INTERVALS
Combinatorics	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL PACKING
Combinatorics	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL PARTITION
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL RATIOS
Algebra	Extremal methods, monotonicity, and invariants	extremal subset	extremal argument		extremal choice	EXTREMAL SUBSET
Algebra	Extremal methods, monotonicity, and invariants		extremal argument		extremal choice	EXTREMAL SUBSTITUTION
Algebra	Extremal methods, monotonicity, and invariants		extremal / minimal counterexample		contradiction / minimal counterexample	EXTREMAL/MINIMAL COUNTEREXAMPLE
Algebra	Polynomials and algebraic manipulation		sum-of-squares factorization	Fej√©r-Riesz theorem		FEJER-RIESZ
Combinatorics	Counting and enumerative combinatorics	Ferrers diagrams				FERRERS DIAGRAMS
Algebra	Discrete functions, floors, rounding, and base representation	finite automata				FINITE AUTOMATA
Combinatorics	Algorithms, automata, words, and constructive combinatorics	finite states	finite-state method			FINITE STATES
Algebra; Number Theory	Number-theoretic algebra		finiteness argument			FINITENESS
Geometry	Core Euclidean geometry	fixed locus	fixed-locus method			FIXED LOCUS

Recommended database rule

Use this logic:

Raw tag type	Put into
Mathematical object	Object tag
Method / move / proof idea	Technique tag
Named theorem / named lemma	Lemma/Theorem tag
Purpose in solution	Proof role
Broad training family	Canonical Subtopic
Main olympiad branch	Area

Use NULL / blank when the field is not naturally present. Do not force every row to have all tags.

Normalized mapping for this batch

In the table below, I group obvious aliases together. In your actual database, you can expand each alias into one row while pointing to the same normalized fields.

Area	Canonical Subtopic	Object tag	Technique tag	Lemma/Theorem tag	Proof role	Raw imported tag
Algebra	Discrete functions, floors, rounding, and base representation	floor function	floor manipulation		computation / bounding	FLOOR FUNCTION; FLOORS; FLOOR SUMS; FLOOR / CEILING / FRACTIONAL PART; FLOOR/FRACTIONAL PART
Algebra	Discrete functions, floors, rounding, and base representation	base representation	digit argument		construction / classification	BASE REPRESENTATION; BINARY EXPANSION; DIGIT CONSTRUCTION
Algebra	Discrete functions, floors, rounding, and base representation	binary structure	binary splitting		construction	BINARY SPLITTING; BINARY TREES; BINARY WORDS; DYADIC INTERVALS; DYADIC WEIGHTS
Algebra	Sequences, recurrences, and series	geometric series	summation		computation	GEOMETRIC SUMS; GEOMETRIC SERIES
Algebra	Sequences, recurrences, and series	recurrence	asymptotic growth		classification / bounding	RECURRENCE GROWTH / ASYMPTOTICS; CHARACTERISTIC ROOTS; CYCLIC RECURRENCES
Algebra	Sequences, recurrences, and series	Fibonacci sequence	recurrence identity		computation	FIBONACCI IDENTITIES; FIBONACCI RECURRENCE; FIBONACCI WEIGHTS
Algebra	Sequences, recurrences, and series	automatic sequence	finite-state recursion		classification	AUTOMATIC SEQUENCES; BINARY SEQUENCES
Algebra	Functional equations	function on integers	iteration / recursion		classification	FUNCTIONAL EQUATIONS ON N; RECURSIVE FUNCTIONS; FUNCTIONAL GRAPHS
Algebra	Functional equations	real function	regularity condition		classification	REAL DOMAIN; CONTINUITY / REGULARITY
Algebra	Functional equations	multiplicative function	Cauchy-type equation	multiplicative Cauchy	classification	MULTIPLICATIVE CAUCHY
Algebra	Functional equations	affine function	affine ansatz		classification	AFFINE FUNCTIONS; AFFINE SOLUTIONS; EVENTUAL LINEARITY
Algebra	Functional equations	inverse function	injectivity / inversion		classification	INVERSE FUNCTION
Algebra	Polynomials and algebraic manipulation	polynomial	construction		construction	POLYNOMIAL CONSTRUCTION
Algebra	Polynomials and algebraic manipulation	polynomial	growth comparison		bounding	POLYNOMIAL GROWTH
Algebra	Polynomials and algebraic manipulation	real polynomial	root/sign analysis		classification	REAL POLYNOMIALS
Algebra	Polynomials and algebraic manipulation	self-inversive polynomial	reciprocal symmetry		classification	SELF-INVERSIVE POLYNOMIALS
Algebra	Polynomials and algebraic manipulation	special polynomial family	structural recognition		classification	SPECIAL POLYNOMIAL FAMILIES
Algebra	Polynomials and algebraic manipulation	factorization	algebraic factorization		transformation	1-FACTORIZATION; ALGEBRAIC FACTORIZATION; FACTORIZATION TRICK; CUBIC FACTORIZATION
Algebra	Polynomials and algebraic manipulation	coefficient	coefficient comparison		bounding	COEFFICIENT BOUNDS; COEFFICIENT POSITIVITY
Algebra	Polynomials and algebraic manipulation	finite difference	difference operator		transformation	FINITE DIFFERENCE
Algebra	Polynomials and algebraic manipulation	characteristic polynomial	eigenvalue / recurrence method		computation	CHARACTERISTIC POLYNOMIAL; DETERMINANT POLYNOMIAL
Algebra	Algebraic structures and linear algebra	group	group structure		classification	ADDITIVE GROUPS; MULTIPLICATIVE GROUP; FINITE ABELIAN GROUPS
Algebra	Algebraic structures and linear algebra	automorphism	symmetry of structure		classification	AUTOMORPHISMS
Algebra	Algebraic structures and linear algebra	bilinear form	linear algebra		computation	BILINEAR FORMS
Algebra	Algebraic structures and linear algebra	determinant	determinant method		computation	DETERMINANT; GRAM DETERMINANT
Algebra	Algebraic structures and linear algebra	Möbius transformation	fractional-linear transformation		transformation	MOBIUS / FRACTIONAL-LINEAR TRANSFORMATION
Algebra	Algebraic structures and linear algebra	coset	quotient / residue class structure		classification	COSETS
Algebra	Inequalities and optimization	constrained expression	Lagrange multiplier method		optimization	LAGRANGE MULTIPLIERS
Algebra	Inequalities and optimization	convex function	Cauchy / Jensen / convexity	Cauchy; Jensen	bounding / optimization	CAUCHY/CONVEXITY; CAUCHY/JENSEN
Algebra	Inequalities and optimization	mean inequality	power mean comparison	Power mean	bounding	POWER MEAN
Algebra	Inequalities and optimization	norm / vector inequality	Minkowski inequality	Minkowski	bounding	MINKOWSKI
Algebra	Inequalities and optimization	product constraint	product normalization		optimization	PRODUCT CONSTRAINT; PRODUCT INEQUALITIES; PRODUCT NORMALIZATION
Algebra	Inequalities and optimization	quadratic expression	quadratic optimization		optimization	QUADRATIC OPTIMIZATION; QUADRATIC ANSATZ
Algebra	Inequalities and optimization	one-variable function	reduction to one variable		optimization	ONE-VARIABLE OPTIMIZATION; MINIMIZATION
Algebra	Inequalities and optimization	tangent line	tangent-line bound		bounding	TANGENT-LINE BOUND; TANGENT ESTIMATES
Algebra	Equations, substitutions, and transformations	expression	scaling / homogenization		transformation	SCALING; COMMON DENOMINATOR
Algebra	Equations, substitutions, and transformations	trigonometric expression	trig substitution		transformation	TRIG SUBSTITUTION; TRIGONOMETRIC SUBSTITUTION
Algebra	Extremal methods, monotonicity, and invariants	ordered variables	ordering / monotonicity		extremal choice	ORDERED VARIABLES; MONOTONE MAPS
Algebra	Extremal methods, monotonicity, and invariants	extremal object	extremal argument		extremal choice	EXTREMA; EXTREMAL CLASSIFICATION; EXTREMAL COVERING; EXTREMAL CUTS; EXTREMAL DISTRIBUTIONS; EXTREMAL EDGES; EXTREMAL ENDPOINTS; EXTREMAL GAPS; EXTREMAL GROWTH; EXTREMAL LENGTH; EXTREMAL LOWER BOUND; EXTREMAL OPTIMIZATION; EXTREMAL PAIR; EXTREMAL SET
Algebra	Extremal methods, monotonicity, and invariants	invariant	invariant argument		contradiction / classification	COUNTING INVARIANTS; QUADRATIC RIGIDITY; RIGIDITY/CLASSIFICATION; COMPOSITION RIGIDITY
Number Theory	Additive and multiplicative number theory	geometric progression	multiplicative structure		construction / classification	GEOMETRIC PROGRESSIONS
Number Theory	Additive and multiplicative number theory	consecutive sums	additive decomposition		classification	CONSECUTIVE SUMS; COMPLEMENTARY SUMS
Number Theory	Additive and multiplicative number theory	square product	squarefree / parity analysis		classification	SQUARE PRODUCTS
Number Theory	Additive and multiplicative number theory	sums of cubes	algebraic number theory flavor		transformation	SUMS OF CUBES
Number Theory	Congruences and modular arithmetic	modulo class	modular arithmetic		contradiction	MODULO 3; EULER CRITERION
Number Theory	p-adic and valuation methods	valuation	p-adic carry analysis	Kummer theorem	valuation argument	KUMMER THEOREM
Number Theory	Algebraic number theory flavor	Eisenstein integer	norm method		factorization	EISENSTEIN NORM
Number Theory	Exponential and Diophantine methods	exponent	exponent comparison		bounding	EXPONENT BALANCING; EXPONENT COMPARISON; EXPONENT ENGINEERING
Number Theory	Diophantine equations	rational power	infinite descent / divisibility		contradiction	RATIONAL POWERS
Number Theory	Additive and multiplicative number theory	Frobenius problem	coin problem reasoning	Frobenius problem	existence / construction	FROBENIUS PROBLEM; FROBENIUS-TYPE REASONING
Number Theory	Congruences and modular arithmetic	bitwise XOR	parity / binary argument		invariant	BITWISE XOR
Number Theory	Congruences and modular arithmetic	Liouville parity	parity obstruction		contradiction	LIOUVILLE PARITY
Combinatorics	Graph theory	graph	graph modeling		translation	GRAPHS; GRAPH TRANSLATION; GRAPH STRUCTURE; GRAPH ENCODING
Combinatorics	Graph theory	forest / tree	acyclic graph argument		construction / contradiction	FORESTS; INDUCED FOREST; SPANNING TREES
Combinatorics	Graph theory	path	path argument		construction / existence	GRAPH PATHS; HAMILTONIAN PATH; NONCROSSING PATHS
Combinatorics	Graph theory	matching	matching argument	Hall	existence	GRAPH MATCHING; GRAPH MATCHINGS; NONCROSSING MATCHING
Combinatorics	Graph theory	graph complement	complement graph argument		transformation	GRAPH COMPLEMENT
Combinatorics	Graph theory	diameter / metric	distance in graph		bounding	GRAPH DIAMETER; GRAPH METRIC; L1 METRIC
Combinatorics	Graph theory	graph cut / separation	separator argument		lower bound	GRAPH SEPARATION; EDGE-DISJOINT PATHS
Combinatorics	Graph theory	directed graph	orientation argument		construction	DIRECTED GRAPH; GRAPH ORIENTATION; FUNCTIONAL DIGRAPH
Combinatorics	Graph theory	Eulerian graph	parity degree argument	Euler trail criterion	existence	EULERIAN GRAPHS; EULER TRAILS
Combinatorics	Graph theory	tournament	score sequence	Landau-type theorem	classification	TOURNAMENT SCORES
Combinatorics	Graph theory	clique	clique forcing	Turán	extremal bound	CLIQUES; CLIQUE FORCING; CLIQUE PARTITIONS
Combinatorics	Graph theory	circulant graph	cyclic symmetry		construction	CIRCULANT GRAPHS
Combinatorics	Graph theory	graph Laplacian	spectral / matrix method		computation	GRAPH LAPLACIAN
Combinatorics	Set systems, posets, and extremal set theory	subset family	antichain / chain argument	Sperner theorem	extremal bound	SUBSETS; SPERNER; CHAINS; CHAIN DECOMPOSITION; CHAIN DECOMPOSITIONS
Combinatorics	Set systems, posets, and extremal set theory	poset	order-theoretic argument		classification	ORDER THEORY; ORDERED VARIABLES
Combinatorics	Set systems, posets, and extremal set theory	blocker / filter	dual family argument		contradiction	BLOCKERS; FILTERS
Combinatorics	Counting and enumerative combinatorics	injection	injective counting		upper/lower bound	INJECTIONS
Combinatorics	Counting and enumerative combinatorics	Catalan object	recursive counting	Catalan numbers	enumeration	CATALAN NUMBERS
Combinatorics	Counting and enumerative combinatorics	composition	stars-and-bars / decomposition		enumeration	COMPOSITIONS
Combinatorics	Counting and enumerative combinatorics	Eulerian number	descent counting	Eulerian numbers	enumeration	EULERIAN NUMBERS
Combinatorics	Counting and enumerative combinatorics	orbit	group action counting	Burnside / orbit-counting	enumeration	ORBIT COUNTING
Combinatorics	Counting and enumerative combinatorics	lattice point	lattice counting		enumeration	LATTICE COUNTING
Combinatorics	Counting and enumerative combinatorics	interval	interval counting		enumeration	INTERVAL COUNTING; INTERVAL OVERLAP
Combinatorics	Counting and enumerative combinatorics	boundary / component	double counting		enumeration / bound	BOUNDARY COUNTING; COMPONENT COUNTING; CONNECTED COMPONENTS
Combinatorics	Counting and enumerative combinatorics	collision	collision counting		contradiction / bound	COLLISION COUNTING; COLLISION AVOIDANCE
Combinatorics	Counting and enumerative combinatorics	cut	cut counting		lower bound	CUT COUNTING
Combinatorics	Counting and enumerative combinatorics	pairing	complement / reciprocal pairing		counting simplification	COMPLEMENT PAIRING; RECIPROCAL PAIRING
Combinatorics	Algorithms, automata, words, and constructive combinatorics	greedy choice	greedy algorithm		construction	GREEDY; GREEDY ALGORITHMS; GREEDY COVERING
Combinatorics	Algorithms, automata, words, and constructive combinatorics	process	termination invariant		termination	PROCESS TERMINATION; CONSTRUCTIVE PROCESS
Combinatorics	Algorithms, automata, words, and constructive combinatorics	finite-state process	DP / transfer matrix		computation	DP; FINITE-STATE DP; TRANSFER MATRIX
Combinatorics	Algorithms, automata, words, and constructive combinatorics	Gray code	constructive ordering	Gray code	construction	GRAY CODE; GRAY CODES
Combinatorics	Algorithms, automata, words, and constructive combinatorics	rewriting system	normal form / termination		classification	REWRITING SYSTEMS
Combinatorics	Algorithms, automata, words, and constructive combinatorics	token configuration	token swapping		construction / lower bound	TOKEN SWAPPING
Combinatorics	Games, strategies, and processes	finite game	strategy stealing / invariant		winning strategy	FINITE GAME; GAME PROCESS; GAME INVARIANT; GAMES ON GRAPHS
Combinatorics	Coloring, tiling, grids, and invariants	parity coloring	parity invariant		contradiction	PARITY INVARIANTS; AREA INVARIANTS
Combinatorics	Coloring, tiling, grids, and invariants	domino tiling	coloring invariant		impossibility	DOMINO TILING
Combinatorics	Coloring, tiling, grids, and invariants	rook placement	board counting		construction / bound	ROOK PLACEMENTS
Combinatorics	Coloring, tiling, grids, and invariants	grid	grid construction		construction	GRID CONSTRUCTION; GRID CYCLES; GRID PARTITIONS; GRID TOPOLOGY
Combinatorics	Linear algebraic combinatorics	F_2 vector space	linear algebra over F_2		invariant / contradiction	GF(2) LINEAR ALGEBRA; F_2 LINEAR ALGEBRA; F2 LINEAR ALGEBRA; F_2 LINEAR ALGEBRA corrupted tag
Combinatorics	Linear algebraic combinatorics	incidence matrix	rank / parity method		contradiction	INCIDENCE MATRICES; INCIDENCE VECTORS; INDICATOR VARIABLES
Combinatorics	Probability, entropy, coding, and information methods	random variable	linearity of expectation	Linearity of expectation	expectation computation	LINEARITY OF EXPECTATION; PROBABILITY
Combinatorics	Probability, entropy, coding, and information methods	code / information	entropy or information bound		lower bound	INFORMATION; COVERING CODES
Combinatorics	Extremal combinatorics	forbidden configuration	extremal argument	Turán-type theorem	upper bound / contradiction	FORBIDDEN CONFIGURATIONS; THRESHOLD ARGUMENT
Combinatorics	Extremal combinatorics	local density	density increment / averaging		extremal bound	LOCAL DENSITY; DENSE SETS
Combinatorics	Extremal combinatorics	averaging process	double counting / averaging		existence	AVERAGING PROCESS; DOUBLE COUNTING/AVERAGING
Combinatorics	Combinatorial geometry and topology	planar separation	topological separation	Jordan curve flavor	lower bound	PLANAR SEPARATION; PLANAR TOPOLOGY
Combinatorics	Combinatorial geometry and topology	line arrangement	arrangement counting		enumeration	ARRANGEMENTS OF LINES
Combinatorics	Combinatorial geometry and topology	finite point set	extremal geometry		construction / contradiction	FINITE POINT SETS; UNIT DISTANCES; EMPTY POLYGONS
Combinatorics	Combinatorial geometry and topology	convex hull	hull reduction		case reduction	CONVEX HULLS; CONVEX HULL CASES
Combinatorics	Combinatorial geometry and topology	noncrossing object	uncrossing		simplification	UNCROSSING; CROSSING ARGUMENT; CROSSING GRAPH
Combinatorics	Combinatorial geometry and topology	billiard path	unfolding		transformation	BILLIARDS UNFOLDING; UNFOLDING
Geometry	Core Euclidean geometry	triangle / angle	angle chasing		proof setup	GEOMETRY; ADVANCED ANGLE CHASING; ANGLE COMPUTATION; ANGLE EQUALITY; ANGLE SUM
Geometry	Core Euclidean geometry	line	parallel / perpendicular argument		construction	LINE GEOMETRY; PERPENDICULAR LINES; PARALLEL CONSTRUCTION
Geometry	Core Euclidean geometry	distance	metric relation		computation	DISTANCES; DISTANCE EQUATIONS; DISTANCE SUMS; DISTANCE PRODUCTS; EQUAL DISTANCES
Geometry	Core Euclidean geometry	triangle side lengths	law of cosines	Law of cosines	computation	LAW OF COSINES
Geometry	Core Euclidean geometry	right angle / semicircle	angle in semicircle	Thales theorem	angle chase	THALES THEOREM; SEMICIRCLE; SEMICIRCLE GEOMETRY
Geometry	Core Euclidean geometry	cevian ratios	mass points	Mass points	ratio chase	MASS POINTS
Geometry	Core Euclidean geometry	quadrilateral	angle / side relation		proof setup	QUADRILATERALS; CONVEX QUADRILATERAL
Geometry	Circle geometry	circle	cyclic angle chase		proof setup	CIRCLE GEOMETRY; CIRCLE CONFIGURATIONS; CIRCLE CONDITION; CYCLICS
Geometry	Circle geometry	concyclic points	cyclic quadrilateral criterion		proving concyclicity	CONCYCLICITY; CYCLIC CONFIGURATION; CYCLIC/QUADRILATERAL ANGLES
Geometry	Circle geometry	radical axis	radical-axis method	Radical axis theorem	concurrence / collinearity	RADICAL AXIS/COAXALITY; COAXALITY / RADICAL AXIS; COAXALITY/RADICAL AXIS; MIQUEL/RADICAL AXIS
Geometry	Circle geometry	coaxal circles	coaxality		classification	COAXALITY; CIRCLE PENCIL; COAXAL/CIRCLE TANGENCY
Geometry	Circle geometry	tangent	equal tangents / tangent-secant	Tangent-secant theorem	ratio chase	CIRCLE TANGENT; CIRCLE TANGENCIES; COMMON TANGENTS; EQUAL TANGENTS; TANGENT-SECANT
Geometry	Circle geometry	arc midpoint	arc midpoint lemma		construction	CIRCUMCIRCLE/ARC MIDPOINT
Geometry	Triangle centers and triangle configurations	incenter / incircle	incenter geometry		proof setup	INCENTER COORDINATES; INCIRCLE GEOMETRY; INCIRCLE TANGENTS; MIXTILINEAR INCIRCLES
Geometry	Triangle centers and triangle configurations	orthocenter / orthic triangle	altitude / orthic configuration		proof setup	ORTHIC CONFIGURATION; ORTHIC GEOMETRY; ORTHOCENTER COORDINATES; ORTHOCENTER FORMULA; ORTHOCENTER/INCENTER
Geometry	Triangle centers and triangle configurations	median	median geometry		ratio chase	MEDIAN GEOMETRY
Geometry	Triangle centers and triangle configurations	centroid / circumcenter	center relation		computation	CENTROID/CIRCUMCENTER; CENTROIDS
Geometry	Triangle centers and triangle configurations	cevian triangle	Ceva-style relation	Ceva theorem	concurrence	CEVIAN TRIANGLE; CEVA-STYLE ALGEBRA; CEVA-TYPE CONCURRENCY
Geometry	Special configurations and special angles	isosceles triangle	symmetry / equal angles		simplification	ISOSCELES TRIANGLE; ISOSCELES SETUP; ISOSCELES COORDINATES
Geometry	Special configurations and special angles	30-60-90 triangle	special-angle computation		computation	30-60-90 TRIANGLE
Geometry	Special configurations and special angles	equilateral triangle	rotation / symmetry		construction	EQUILATERAL CONFIGURATION; EQUILATERAL SYMMETRY
Geometry	Projective and advanced geometry	Menelaus / Ceva configuration	directed ratio chase	Menelaus; Ceva	collinearity / concurrence	MENELAUS/CEVA; MENELAUS/PROJECTIVE FLAVOR; TRIG CEVA/MENELAUS; PASCAL/MENELAUS
Geometry	Projective and advanced geometry	Pascal configuration	projective theorem	Pascal theorem	collinearity	PASCAL; PASCAL THEOREM; DEGENERATE PASCAL
Geometry	Projective and advanced geometry	cross ratio	projective invariant	Cross ratio	transformation	CROSS RATIO; CROSS RATIOS
Geometry	Projective and advanced geometry	harmonic bundle	projective involution	Harmonic bundle	transformation	PROJECTIVE/HARMONIC BUNDLES
Geometry	Projective and advanced geometry	complete quadrilateral	projective configuration	Complete quadrilateral	transformation	PROJECTIVE/COMPLETE QUADRILATERAL
Geometry	Projective and advanced geometry	polar / contact chord	pole-polar method	La Hire / polar theory	collinearity / concurrence	POLAR/CONTACT CHORD; TANGENTS/POLARS
Geometry	Projective and advanced geometry	Newton line	projective geometry	Newton line	collinearity	NEWTON LINE
Geometry	Projective and advanced geometry	Miquel point	Miquel configuration	Miquel theorem	concurrence / cyclicity	MIQUEL/COAXALITY; MIQUEL/RADICAL AXIS
Geometry	Projective and advanced geometry	spiral similarity	spiral similarity	Reim theorem	transformation	REIM/SPIRAL SIMILARITY; PROJECTIVE/SPIRAL GEOMETRY
Geometry	Projective and advanced geometry	Simson line	projection on sides	Simson line	collinearity	SIMSON-LINE FLAVOR
Geometry	Geometry-flavored algebra	coordinate setup	analytic geometry		computation	ANALYTIC SETUP; PROJECTIVE/AFFINE COORDINATES; PROJECTIVE/ANALYTIC
Geometry	Geometry-flavored algebra	barycentric coordinates	coordinate bash		computation	BARYCENTRIC/COMPLEX; BARYCENTRICS/COMPLEX; BARYCENTRICS/COORDINATES
Geometry	Geometry-flavored algebra	complex plane	complex geometry		computation	COMPLEX/BARYCENTRIC; COMPLEX/COORDINATES; COMPLEX/TRILINEAR
Geometry	Geometry-flavored algebra	trigonometric geometry	trig Ceva / trig bash	Trig Ceva	computation	ANALYTIC/TRIG GEOMETRY; BARYCENTRIC/TRIG CEVA
Geometry	Geometry-flavored algebra	tangent coordinates	tangent length algebra		computation	TANGENT COORDINATES; CIRCLE WITH TANGENTS; COMMON TANGENTS
Geometry	Geometry-flavored algebra	area	area ratio / directed area		computation	AREA/PERIMETER; DIRECTED AREAS; AREA OVERLAP
Geometry	Transformational geometry	central symmetry	symmetry transform		simplification	CENTRAL SYMMETRY
Geometry	Transformational geometry	antipode	antipodal construction		construction	ANTIPODE ON CIRCUMCIRCLE
Geometry	3D and solid geometry	polyhedron	spatial geometry		computation	POLYHEDRA; VOLUME; CIRCUMSPHERE; 3D AFFINE GEOMETRY
Rows that should become proof-role tags, not subtopics

These are especially important to separate from mathematical content:

Raw imported tag	Correct field	Suggested value
CONSTRUCTION/IMPOSSIBILITY	Proof role	construction / impossibility
CONSTRUCTION/LOWER BOUND	Proof role	construction / lower bound
IMPOSSIBILITY	Proof role	impossibility
COUNTEREXAMPLE SEARCH	Proof role	counterexample search
COUNTEREXAMPLES	Proof role	counterexample
EXISTENCE/UNIQUENESS	Proof role	existence / uniqueness
CASE REDUCTION	Proof role	case reduction
SEARCH STRATEGY	Proof role	search
THRESHOLD ARGUMENT	Technique tag + Proof role	threshold argument; lower bound
EXTREMAL LOWER BOUND	Technique tag + Proof role	extremal argument; lower bound
RIGIDITY/CLASSIFICATION	Technique tag + Proof role	rigidity; classification
PROCESS TERMINATION	Proof role	termination
CONSTRUCTIVE DESIGN	Proof role	construction
CONSTRUCTIVE PROCESS	Proof role	construction
CONSTRUCTIVE RECURSION	Proof role	recursive construction
Rows that should become technique tags
Raw imported tag	Area	Canonical Subtopic	Technique tag
GREEDY	Combinatorics	Algorithms, automata, words, and constructive combinatorics	greedy argument
GREEDY ALGORITHMS	Combinatorics	Algorithms, automata, words, and constructive combinatorics	greedy algorithm
UNCROSSING	Combinatorics	Combinatorial geometry and topology	uncrossing
DOUBLE COUNTING/AVERAGING	Combinatorics	Counting and enumerative combinatorics	double counting / averaging
LINEARITY OF EXPECTATION	Combinatorics	Probability, entropy, coding, and information methods	expectation linearity
F_2 LINEAR ALGEBRA	Combinatorics	Linear algebraic combinatorics	F_2 linear algebra
INCIDENCE MATRICES	Combinatorics	Linear algebraic combinatorics	incidence matrix / rank method
PARITY DESCENT	Number Theory / Algebra	p-adic and valuation methods	parity descent
PARITY INVARIANTS	Combinatorics	Coloring, tiling, grids, and invariants	parity invariant
TANGENT-LINE BOUND	Algebra	Inequalities and optimization	tangent-line bound
LAGRANGE MULTIPLIERS	Algebra	Inequalities and optimization	constrained optimization
LP DUALITY	Algebra / Combinatorics	Inequalities and optimization	linear-programming duality
TRIG SUBSTITUTION	Algebra	Equations, substitutions, and transformations	trigonometric substitution
BARYCENTRICS/COORDINATES	Geometry	Geometry-flavored algebra	barycentric coordinates
COMPLEX/COORDINATES	Geometry	Geometry-flavored algebra	complex coordinates
MASS POINTS	Geometry	Core Euclidean geometry	mass points
RADICAL AXIS/COAXALITY	Geometry	Circle geometry	radical-axis method
CROSS RATIO	Geometry	Projective and advanced geometry	cross-ratio method
Rows that should become lemma/theorem tags
Raw imported tag	Area	Canonical Subtopic	Lemma/Theorem tag
KUMMER THEOREM	Number Theory	p-adic and valuation methods	Kummer theorem
EULER CRITERION	Number Theory	Congruences and modular arithmetic	Euler criterion
PASCAL THEOREM	Geometry	Projective and advanced geometry	Pascal theorem
PASCAL	Geometry	Projective and advanced geometry	Pascal theorem
MENELAUS/CEVA	Geometry	Projective and advanced geometry	Menelaus / Ceva
TRIG CEVA/MENELAUS	Geometry	Geometry-flavored algebra	Trig Ceva / Trig Menelaus
THALES THEOREM	Geometry	Core Euclidean geometry	Thales theorem
LAW OF COSINES	Geometry	Core Euclidean geometry	Law of cosines
SPERNER	Combinatorics	Set systems, posets, and extremal set theory	Sperner theorem
PITOT	Geometry	Circle geometry	Pitot theorem
NEWTON LINE	Geometry	Projective and advanced geometry	Newton line
SIMSON-LINE FLAVOR	Geometry	Projective and advanced geometry	Simson line
REIM/SPIRAL SIMILARITY	Geometry	Projective and advanced geometry	Reim theorem / spiral similarity
MIQUEL/COAXALITY	Geometry	Circle geometry	Miquel theorem
MIQUEL/RADICAL AXIS	Geometry	Circle geometry	Miquel theorem / radical axis
Main correction to your current table

Do not keep these as current mappings:

Current problematic pattern	Better treatment
GRAPH MATCHING → Combinatorial algebra and counting	Area = Combinatorics, Canonical Subtopic = Graph theory, Object tag = matching
EXTREMAL GRAPHS → Algebra	Area = Combinatorics, Canonical Subtopic = Graph theory / Extremal combinatorics, Technique tag = extremal graph argument
PASCAL → Combinatorics, Geometry	Usually Area = Geometry, Canonical Subtopic = Projective and advanced geometry, Lemma/Theorem tag = Pascal theorem
INCIDENCE GEOMETRY → Geometric inequalities	Usually Area = Geometry or Combinatorics, Canonical Subtopic = Projective / combinatorial geometry, not inequalities unless an actual bound is involved
INVARIANT ANGLE → Algebra	Should be Geometry technique: Technique tag = angle invariant
TRIG CEVA/MENELAUS → Algebra	Main area should be Geometry; trig is the method
GF(2) LINEAR ALGEBRA → blank	Area = Combinatorics, Canonical Subtopic = Linear algebraic combinatorics, Technique tag = F_2 linear algebra
GRID TOPOLOGY → blank	Area = Combinatorics, Canonical Subtopic = Coloring, tiling, grids, and invariants or Combinatorial geometry and topology
ORDER THEORY → Algebra, Combinatorics	Usually Area = Combinatorics, Canonical Subtopic = Set systems, posets, and extremal set theory



----------------
improve the topic tags clean up, considering new fields like object_tags, technique_tags,, lemma_theorem_tags, proof_roles"""

FOURTH_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE = _read_layered_topic_tag_table_file(
    "topic_tag_layer_taxonomy_fourth_batch.tsv",
)
FIFTH_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE = _read_layered_topic_tag_table_file(
    "topic_tag_layer_taxonomy_fifth_batch.tsv",
)
SIXTH_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE = _read_layered_topic_tag_table_file(
    "topic_tag_layer_taxonomy_sixth_batch.tsv",
)
SEVENTH_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE = _read_layered_topic_tag_table_file(
    "topic_tag_layer_taxonomy_seventh_batch.tsv",
)

FOURTH_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES = {
    "BINOMIALS",
    "BIPARTITE COVERING",
    "BIPARTITE COVERINGS",
    "BIPARTITE EDGE COLORING",
    "BIPARTITE MATCHING/HALL",
    "BIRKHOFF",
    "BORSUK-TYPE ARGUMENT",
    "CASE CLASSIFICATION",
    "CIRCLE WITH DIAMETER BC",
    "CONSTRUCTION AND LOWER BOUND",
    "CONVEXITY/JENSEN FLAVOR",
    "COORDINATES/POLARS",
}

FIFTH_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES = {
    "DISCRETE BRUNN-MINKOWSKI",
    "DISCREPANCY/INVARIANTS",
    "DISCREPANCY/VARIANCE LOWER BOUND",
    "DISCRETE IVT",
    "DISCRIMINANT/RATIONAL-ROOT ELIMINATION",
    "DISTANCE-TO-LINE FORMULA",
    "DOMINATION/GREEDY",
    "DOUBLE COUNTING / CAUCHY-SCHWARZ ON INCIDENCES",
    "DYADIC/ODD-PART COLORING",
    "EGZ/PIGEONHOLE",
}

SIXTH_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES = {
    "RATIONAL VALUES",
    "RATIONALITY CRITERIA",
    "RAVI-TYPE SUBSTITUTION",
    "RECURRENCE / M\u221a\xf1BIUS MAP",
    "ROTATION-EXTENSION (P\u221a\xecSA)",
    "STEWART/MEDIAN",
    "TUR\u221a\u00c5N/MANTEL",
    "REIM/RADICAL AXIS",
    "ROOTS OF UNITY/FILTERING",
    "VARIGNON",
    "VARIGNON PARALLELOGRAM",
    "TUTTE THEOREM",
}

SEVENTH_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES = {
    "MIDPOINT HOMOTHETY",
    "MIN-CUT",
    "MIQUEL/POWER",
    "NILPOTENCE",
    "ORTHOCENTER/SIMSON FLAVOR",
    "PERRON-FROBENIUS",
    "PLANAR TRIANGULATIONS",
    "QUADRATIC RESIDUES",
}

FOURTH_PASTED_COMPATIBILITY_MAPPINGS: tuple[LayeredTopicTagMapping, ...] = (
    _auxiliary_layer_mapping(
        raw_tag="CONSTRUCTION + LOWER BOUND",
        proof_role="construction / lower bound",
        status="method",
        stored_technique="CONSTRUCTION/LOWER BOUND",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Triangle centers and triangle configurations",
        raw_tag="INCENTER/INCIRCLE",
        object_tag="incenter; incircle",
        technique_tag="angle/length chase",
        proof_role="classification",
        preserve_source_domains=False,
        stored_technique="INCENTER/INCIRCLE",
    ),
)

FIFTH_PASTED_COMPATIBILITY_MAPPINGS: tuple[LayeredTopicTagMapping, ...] = (
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Coloring, tiling, grids, and invariants",
        raw_tag="GRID COLOURING",
        object_tag="grid",
        technique_tag="grid coloring",
        proof_role="obstruction",
        stored_technique="GRID COLORING",
    ),
)

SEVENTH_PASTED_COMPATIBILITY_MAPPINGS: tuple[LayeredTopicTagMapping, ...] = (
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Coloring, tiling, grids, and invariants",
        raw_tag="PARITY",
        object_tag="coloring; parity class",
        technique_tag="parity methods",
        proof_role="invariant proof",
        stored_technique="PARITY METHODS",
    ),
    _auxiliary_layer_mapping(
        area="Combinatorics",
        canonical_subtopic="Coloring, tiling, grids, and invariants",
        raw_tag="PARITY METHODS",
        object_tag="coloring; parity class",
        technique_tag="parity methods",
        proof_role="invariant proof",
        stored_technique="PARITY METHODS",
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Discrete functions, floors, rounding, and base representation",
        raw_tag="FLOOR FUNCTIONS",
        object_tag="floor function",
        technique_tag="floor/rounding analysis",
        stored_technique="FLOOR FUNCTIONS",
    ),
    _auxiliary_layer_mapping(
        area="Number Theory",
        canonical_subtopic="Chinese remainder theorem and local-to-global methods",
        raw_tag="CRT",
        object_tag="residue system",
        technique_tag="local-to-global",
        lemma_tag="Chinese remainder theorem",
        stored_technique="CHINESE REMAINDER THEOREM / LOCAL-GLOBAL",
    ),
    _auxiliary_layer_mapping(
        area="Number Theory",
        canonical_subtopic="Chinese remainder theorem and local-to-global methods",
        raw_tag="CHINESE REMAINDER THEOREM / LOCAL-GLOBAL",
        object_tag="residue system",
        technique_tag="local-to-global",
        lemma_tag="Chinese remainder theorem",
        stored_technique="CHINESE REMAINDER THEOREM / LOCAL-GLOBAL",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Core Euclidean geometry",
        raw_tag="PICK/SHOELACE",
        object_tag="Pick/shoelace/lattice area",
        technique_tag="lattice points; area; coordinate geometry",
        lemma_tag="Pick's theorem; shoelace formula",
        proof_role="area computation",
        stored_technique="PICK/SHOELACE",
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Algebraic structures and linear algebra",
        raw_tag="RANK/KERNEL/IMAGE",
        object_tag="rank/kernel/image",
        technique_tag="rank; kernel-image; matrix factorization",
        lemma_tag="rank-nullity",
        proof_role="structure proof",
        stored_technique="RANK / KERNEL / IMAGE",
    ),
    _auxiliary_layer_mapping(
        raw_tag="CONSTRUCTION",
        proof_role="construction",
        status="method",
        stored_technique="CONSTRUCTION",
    ),
    _auxiliary_layer_mapping(
        raw_tag="CASEWORK",
        proof_role="casework; finite checking",
        status="method",
        stored_technique="CASEWORK AND FINITE CHECKING",
    ),
    _auxiliary_layer_mapping(
        area="Geometry",
        canonical_subtopic="Geometry-flavored algebra",
        raw_tag="LATTICE POINTS",
        object_tag="lattice points",
        technique_tag="lattice method",
        proof_role="counting/structure",
        preserve_source_domains=False,
        stored_technique="LATTICE POINTS",
    ),
    _auxiliary_layer_mapping(
        area="Algebra",
        canonical_subtopic="Equations, substitutions, and transformations",
        raw_tag="RATIONAL PARAMETRIZATION",
        object_tag="rational expression",
        technique_tag="parametrization",
        proof_role="construction",
        preserve_source_domains=False,
        stored_technique="RATIONAL PARAMETRIZATION",
    ),
)

LAYERED_TOPIC_TAG_MAPPINGS: tuple[LayeredTopicTagMapping, ...] = (
    *BASE_LAYERED_TOPIC_TAG_MAPPINGS,
    *_build_layered_topic_tag_mappings(
        ATTACHED_LAYERED_TOPIC_TAG_TABLE,
        replacements=CANONICAL_SUBTOPIC_REPLACEMENTS,
    ),
    *_build_layered_topic_tag_mappings(
        PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE,
        replacements=PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
        raw_replacements=PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS,
        raw_stored_technique_replacements=PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
    ),
    *SECOND_PASTED_TECHNIQUE_ROWS,
    *SECOND_PASTED_LEMMA_ROWS,
    *_build_layered_topic_tag_mappings(
        SECOND_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE,
        replacements=SECOND_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
        drop_source_domain_aliases=SECOND_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES,
        raw_replacements=SECOND_PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS,
        raw_stored_technique_replacements=SECOND_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
        split_raw_aliases=True,
    ),
    *SECOND_PASTED_RAW_CORRECTION_ROWS,
    *SECOND_PASTED_PROOF_ROLE_ROWS,
    *THIRD_PASTED_LAYERED_TOPIC_TAG_MAPPINGS,
    *_build_layered_topic_tag_mappings(
        FOURTH_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE,
        replacements=FOURTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
        drop_source_domain_aliases=FOURTH_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES,
        raw_replacements=SECOND_PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS,
        raw_stored_technique_replacements=FOURTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
        split_raw_aliases=False,
    ),
    *FOURTH_PASTED_COMPATIBILITY_MAPPINGS,
    *_build_layered_topic_tag_mappings(
        FIFTH_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE,
        replacements=FIFTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
        drop_source_domain_aliases=FIFTH_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES,
        raw_replacements=SECOND_PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS,
        raw_stored_technique_replacements=FOURTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
        split_raw_aliases=False,
    ),
    *FIFTH_PASTED_COMPATIBILITY_MAPPINGS,
    *_build_layered_topic_tag_mappings(
        SIXTH_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE,
        replacements=SIXTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
        drop_source_domain_aliases=SIXTH_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES,
        raw_replacements=SECOND_PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS,
        raw_stored_technique_replacements=SIXTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
        split_raw_aliases=True,
    ),
    *_build_layered_topic_tag_mappings(
        SEVENTH_PASTED_BATCH_LAYERED_TOPIC_TAG_TABLE,
        replacements=SEVENTH_PASTED_BATCH_CANONICAL_SUBTOPIC_REPLACEMENTS,
        drop_source_domain_aliases=SEVENTH_PASTED_BATCH_DROP_SOURCE_DOMAIN_ALIASES,
        raw_replacements=SECOND_PASTED_BATCH_RAW_CANONICAL_SUBTOPIC_REPLACEMENTS,
        raw_stored_technique_replacements=SEVENTH_PASTED_BATCH_RAW_STORED_TECHNIQUE_REPLACEMENTS,
        split_raw_aliases=True,
    ),
    *SEVENTH_PASTED_COMPATIBILITY_MAPPINGS,
)
