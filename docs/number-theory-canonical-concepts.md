# Number Theory: final canonical concept list

**236 distinct Number Theory concepts** across 11 areas, plus **32 shared objects and proof strategies** in an appendix.

This finalizes the local reference list for the captured curriculum and benchmark sources. The nine ambiguous curriculum labels have explicit final decisions. Application aliases, stored tags, ratings, and production records are unchanged.

## Identity rules

- One identity covers duplicate spellings, role labels, and parameter variants. The prime, modulus, base, progression length, or specified ring is retained as variant metadata.
- Independently defined objects, properties, operations, and named theorems remain distinct. For example, the Jacobi symbol and Legendre symbol are separate, as are Hensel's lemma and LTE.
- Recognizable named problem classes such as perfect squares, Pell equations, and quadratic residues remain separate training concepts. A related or more general concept is not automatically a synonym.
- Compound labels describe several concepts or possible meanings. They do not become an extra canonical identity and are not placed in the single-identity alias CSV.
- A heuristic connection does not establish theorem applicability. A label lacking enough meaning to identify an atomic concept is explicitly excluded, with its source and reason retained.

## Final review results

The draft contained 246 Number Theory identities and 33 shared entries. The review consolidates 16 Number Theory parameter/application variants and one shared variant, and adds six precise identities needed to resolve ambiguous labels. The result is 236 Number Theory identities and 32 shared entries. Every retired ID has a redirect in `concept-redirects.json`; its benchmark profiles remain attached to the surviving identity.

All 264 curriculum labels have final dispositions. All 307 held Number Theory benchmark profiles are accounted for exactly once; two underspecified primitive-object/word profiles are excluded from identity assignment. All original rating fields are preserved. No rating is averaged or replaced.

## Decisions on the nine ambiguous curriculum labels

The concept names below are related scopes, decomposed components, or alternatives according to the decision column. They do not assert which theorem was used in an individual problem.

| Source label | Final decision | Canonical concepts / scope | Reason |
|---|---|---|---|
| Hensel-style lifting | General scope retained | Congruence and p-adic lifting | Classify as general congruence/p-adic lifting. The wording alone does not establish applicability of Hensel's lemma; no theorem alias is created. |
| p-adic density / local-global flavor | Combined heading excluded | p-adic congruences; Density arguments; Local-to-global arguments | Exclude this composite umbrella from the atomic list. These are related subjects, not synonyms; neither a density notion nor a local-global theorem is specified. |
| Ljunggren / Nagell flavor | Insufficiently specific; excluded | Excluded from canonical identities | Exclude the name-only hint. Nagell-Ljunggren and Lebesgue-Ljunggren-Nagell denote different equation families; the source contains no equation selecting one. |
| elliptic-curve flavor, if only heuristic | General scope retained | Elliptic curves in Diophantine problems | Retain the elliptic-curve object supplied by the layered taxonomy; mark the association as heuristic, without asserting a theorem or method applies. |
| AP/GP avoidance | Split into precise concepts | Arithmetic progressions; Geometric progressions | Retain arithmetic-progression and geometric-progression avoidance as separate task variants on these objects. The compound is not a canonical name or synonym. |
| Schur/Rado flavor | Split into precise concepts | Schur's monochromatic-equation theorem; Rado's partition-regularity theorem | Separate Schur's monochromatic x+y=z theorem and Rado's partition-regularity criterion. The flavor tag does not prove either theorem applies. |
| number of prime factors | Distinct alternatives retained | Distinct-prime-factor count omega(n); Prime-factor count with multiplicity Omega(n) | Keep both precise counts: omega(n) for distinct prime divisors and Omega(n) for prime factors with multiplicity. The bare label is excluded as an automatic alias; it does not assert both counts were used. |
| inverse phi / inverse sigma flavor | Split into precise concepts | Inverse totient problem; Inverse sum-of-divisors problem | Separate the preimage problems phi(n)=m and sigma(n)=m. These are not single-valued inverses and are not aliases for the forward functions. |
| phi/tau/sigma constraints | Split into precise concepts | Euler's totient function phi(n); Divisor-count function tau(n); Sum-of-divisors function sigma(n) | Decompose into the three named arithmetic-function identities, retaining the joint-constraint task as context. |

A concrete distinction: for n=12=2^2*3, omega(12)=2 and Omega(12)=3. The bare source label number of prime factors is retained as alternatives, never silently assigned to one.

## Consolidated identity variants

| Retired identity | Surviving concept | Review decision |
|---|---|---|
| powers-of-three | Prime powers | The prime base 3 is a parameter of prime powers; retain profiles 187/188 as base-3 variants. |
| mod-three | Congruences and modular arithmetic | The modulus 3 is a parameter; retain profiles 269/277 as small-modulus variants. |
| two-adic-valuation | p-adic valuations | The prime 2 is a parameter of v_p; retain its profile without counting another identity. |
| p-adic-carries | Carry analysis | Prime-base carry analysis is a context variant; Kummer's theorem remains a separate named result. |
| gaussian-factorization | Unique factorization in rings | The ring Z[i] is a specified instance of unique factorization in rings. |
| eisenstein-factorization | Unique factorization in rings | The ring Z[omega] is a specified instance of unique factorization in rings. |
| gaussian-norm | Algebraic norms and norm forms | The Gaussian norm is a ring-specific instance of the algebraic norm, with its formula retained as context. |
| eisenstein-norm | Algebraic norms and norm forms | The Eisenstein norm is a ring-specific instance of the algebraic norm, with its formula retained as context. |
| three-term-ap | Arithmetic progressions | Length 3 is a progression parameter; preserve the avoidance variant. |
| three-term-gp | Geometric progressions | Length 3 is a progression parameter; preserve ratio/nonzero constraints. |
| small-representatives | Residue representatives | A size constraint refines the representative-selection task; preserve profiles 300/301. |
| fermat-cycles | Modular periodicity and cycles | Fermat-based cycles are an application of modular periodicity; retain Fermat's little theorem as a distinct tool. |
| popcount | Digit sums | Popcount is the digit sum in base 2, recorded as a base-specific name. |
| base-p-digits | Positional base representation | Prime-base digit analysis uses positional representation with prime base as context. |
| negative-base | Positional base representation | A negative integer base is a positional-representation parameter; keep its sign convention. |
| factorial-base | Mixed-radix representation | The factorial number system is a specified mixed-radix system. |
| cubic-cancellation | Cancellation | Degree 3 is an application parameter of cancellation, not another identity. |

## Distinct canonical concepts

### Divisibility, primes, and factorization (38)

1. Divisibility
2. Divisibility chains
3. Divisibility graphs
4. Greatest common divisor (GCD)
5. Least common multiple (LCM)
6. GCD-LCM identities
7. Euclidean algorithm
8. Bezout's identity
9. Coprimality
10. Pairwise coprimality
11. Prime factorization
12. Prime numbers
13. Primality testing
14. Composite numbers
15. Prime divisors and prime-divisor analysis
16. Smallest and largest prime factors
17. Prime support
18. Prime-exponent vectors
19. Prime powers
20. Squarefree integers
21. Squarefree kernel / radical
22. Powerful numbers
23. Perfect powers
24. Perfect squares
25. Perfect cubes
26. Perfect-square obstructions
27. Gaps between squares
28. Divisors
29. Divisor posets and lattices
30. Divisor bounds
31. Smooth numbers
32. Primorials
33. Products of consecutive integers
34. Euclid's infinitude-of-primes argument
35. Bertrand-type prime bounds
36. Primes in intervals
37. Dirichlet's theorem on primes in arithmetic progressions
38. Mersenne numbers

### Congruences, orders, and modular arithmetic (28)

1. Congruences and modular arithmetic
2. Residue classes
3. Residue systems
4. Complete residue systems
5. Reduced residue systems
6. Modular inverses
7. Congruence equations and solutions
8. Roots of congruences
9. Modular obstructions
10. Modular constructions
11. Chinese remainder theorem
12. Fermat's little theorem
13. Euler's theorem
14. Wilson's theorem
15. Wilson-type products
16. Multiplicative order
17. Primitive roots
18. Unit groups modulo n
19. Cyclic groups and subgroups modulo n
20. Discrete logarithms
21. Carmichael function and universal exponent
22. Euler quotient
23. Modular exponentiation
24. Polynomial congruences
25. Modular invariants
26. Congruence sieves
27. Residue covering
28. Modular digit constraints

### Power residues and quadratic characters (8)

1. Quadratic residues
2. Cubic residues
3. Higher power residues
4. Legendre symbol
5. Jacobi symbol
6. Quadratic characters
7. Euler's criterion
8. Quadratic reciprocity

### Valuations and p-adic methods (22)

1. p-adic valuations
2. Valuation growth
3. Valuation descent
4. Parity of valuations
5. Valuation bounds
6. p-adic congruences
7. Congruence and p-adic lifting
8. Hensel's lemma and root lifting
9. p-adic roots
10. p-adic continuity
11. p-adic polynomial functions
12. Mahler basis
13. Lifting the exponent (LTE)
14. Legendre's factorial-valuation formula
15. Kummer's theorem
16. Lucas's theorem
17. Factorial valuations
18. Binomial valuations
19. p-adic obstructions
20. p-adic constructions
21. Wieferich-type obstructions
22. Wolstenholme-type congruences

### Diophantine equations, descent, and representations (32)

1. Diophantine equations and integer solutions
2. Diophantine inequalities
3. Rational solutions
4. Infinite descent
5. Vieta jumping
6. Pell equations
7. Markov-type equations
8. Pythagorean triples
9. Heronian triangles
10. Discriminant-square method
11. Quadratic Diophantine equations
12. Cubic Diophantine equations
13. Exponential Diophantine equations
14. Factorial Diophantine equations
15. Catalan-Mihailescu theorem and equations
16. S-unit equations
17. Unit equations
18. Egyptian fractions
19. Frobenius coin problem
20. Numerical semigroups
21. Rational points and parametrization of conics
22. Growth bounds for integer equations
23. Divisibility bounds for integer equations
24. Local obstructions
25. Reduction to primitive solutions
26. Coprime factor splitting
27. Difference of squares
28. Representation as a sum of two squares
29. Fermat's two-square theorem
30. Representation as a sum of three squares
31. Sums of powers
32. Elliptic curves in Diophantine problems

### Arithmetic functions and divisor structure (24)

1. Arithmetic functions
2. Divisor-count function tau(n)
3. Sum-of-divisors function sigma(n)
4. Euler's totient function phi(n)
5. Mobius function
6. Mobius inversion
7. Liouville function
8. Distinct-prime-factor count omega(n)
9. Dirichlet convolution
10. Divisor sums
11. Summatory divisor function
12. Multiplicative arithmetic functions
13. Completely multiplicative functions
14. Additive arithmetic functions
15. Totient chains
16. Divisor-function dynamics
17. Highly composite numbers
18. Practical numbers
19. Abundant numbers
20. Elementary average-order estimates
21. Euler products
22. Prime-factor count with multiplicity Omega(n)
23. Inverse totient problem
24. Inverse sum-of-divisors problem

### Algebraic number theory (19)

1. Gaussian integers
2. Eisenstein integers
3. Quadratic fields
4. Quadratic integer rings
5. Algebraic norms and norm forms
6. Unique factorization in rings
7. Binary quadratic forms
8. Representation by x^2 + d*y^2
9. Cyclotomic polynomials
10. Cyclotomic factorization
11. Primitive prime divisors
12. Zsigmondy's theorem
13. Lucas sequences
14. Fibonacci divisibility
15. Carmichael-type primitive-divisor arguments
16. Algebraic conjugation
17. Minimal polynomial arguments
18. Field-degree and irrationality obstructions
19. Hilbert's theorem 90

### Bases, digits, carries, and automata (17)

1. Positional base representation
2. Digits and digit constraints
3. Digit sums
4. Digital root
5. Digit products
6. Digit dynamic programming
7. Carry analysis
8. Carry-free constructions
9. Repunits
10. Repeating expansions and their periods
11. Digit palindromes
12. Automorphic numbers
13. Leading digits
14. Benford-type logarithmic mantissas
15. Mixed-radix representation
16. Digit automata and finite-state residue systems
17. Automatic sequences

### Additive and multiplicative combinatorics (22)

1. Arithmetic progressions
2. Geometric progressions
3. Additive bases
4. Additive combinatorics over integers
5. Sumsets
6. Product sets
7. Sum-product phenomena
8. Sum-free sets
9. Zero-sum sequences
10. Erdos-Ginzburg-Ziv theorem
11. Cauchy-Davenport theorem
12. Davenport constant
13. Van der Waerden's theorem
14. Sidon sets
15. Distinct differences
16. Difference sets
17. Modular additive groups
18. Multiplicative groups
19. Additive energy
20. Density arguments
21. Schur's monochromatic-equation theorem
22. Rado's partition-regularity theorem

### Rational approximation, floors, and fractional parts (14)

1. Dirichlet approximation
2. Farey fractions
3. Stern-Brocot tree
4. Continued fractions
5. Beatty sequences
6. Kronecker approximation
7. Fractional parts and arithmetic modulo 1
8. Equidistribution modulo 1
9. Floor and ceiling functions
10. Rounding and nearest-integer methods
11. Reduced fractions
12. Denominator analysis and control
13. Bounded denominators
14. Rational numbers

### Finite fields, lattice methods, and arithmetic dynamics (12)

1. Finite fields
2. Character sums
3. Geometry of numbers
4. Integrality
5. Factorials
6. Modular periodicity and cycles
7. Modular dynamics
8. Doubling map
9. Residue representatives
10. Parity
11. Parity descent
12. Bounded representations

## Shared appendix (32)

These occur in the Number Theory evidence and remain available as shared identities.

1. Factorization
2. Case analysis
3. Finite checking
4. Small-case forcing
5. Classification
6. Normalization and reduction
7. Difference method
8. Pigeonhole principle
9. Construction
10. Block decomposition and splitting
11. Intervals and consecutive intervals
12. Scaling and dilation
13. Clearing denominators
14. Cancellation
15. Cubic polynomials and maps
16. Polynomial degree arguments
17. Determinants
18. Determinant-one structures
19. Difference of cubes
20. Aurifeuillean-style identities
21. Sliding-window method
22. Local-to-global arguments
23. Order computation and bounds
24. Powers and exponentiation
25. Exponent comparison
26. Existence arguments
27. Finiteness arguments
28. Infinitude arguments
29. Structural decomposition
30. Integer configurations
31. Auxiliary quotients
32. Representation arguments

## Context-qualified legacy labels

The local fifth-batch taxonomy row 572 explicitly pairs FINITE LOGARITHM with the object discrete logarithms. Profiles 362 and 363 therefore attach to Discrete logarithms in this dataset. This does not declare a universal synonym: finite logarithm can have other meanings in other sources.

Hensel-style profiles 386 and 387 attach to general congruence/p-adic lifting, rather than automatically to Hensel's lemma. The vague prime and primitive objects / primitive sequence or word profiles 159 and 162 are excluded from identity assignment; their parent-family placement cannot establish primitive prime divisors.

## Evidence and scope

- The inputs contain 264 curriculum labels, 462 local NT-associated layered mappings, and 307 held NT benchmark profiles.
- Held benchmark fields match the recorded read-only metadata capture at **2026-10-25 22:30:42 UTC** (**26 October 2026, 06:30:42 MYT**). Narrative fields not in the capture were not compared.
- The earlier live metadata refresh did not complete because the SSH session did not load DATABASE_URL. This review uses local evidence and the dated metadata; it makes no claim about fresh production tag counts.
- 907 additional legacy label/role pairs still lack a single identity from the available source text. They are excluded from automatic aliasing and remain in `review-backlog.csv` for problem-level annotation. The finalized reference is not an exhaustive migration of every raw imported tag; these exclusions are not counted as canonical concepts.
- 42 accepted identities have differing attached profile fields. All profiles are retained separately, including those newly combined under a parameterized identity.

## Mathematical review references

The distinct-prime count is defined in [Eberl's formal arithmetic development](https://isa-afp.org/browser_info/current/AFP/Prime_Distribution_Elementary/Primes_Omega.html). The multiplicity count is explicitly defined here as Omega(n)=sum of prime-factor exponents.

Schur's equation theorem and Rado's criterion are distinct in [Schacht's Ramsey Theory notes](https://www.math.uni-hamburg.de/en/personen/schacht/lnotes/Ramsey.pdf). For lifting versus theorem applicability, see [Conrad's Hensel's Lemma notes](https://kconrad.math.uconn.edu/blurbs/gradnumthy/hensel.pdf).

The exclusion of Ljunggren / Nagell flavor reflects distinct named equation families: [Bennett and Levin](https://arxiv.org/abs/1312.4037) and [Dabrowski, Gunhan, and Soydan](https://arxiv.org/abs/2001.04736). The source gives no equation choosing between them.

Local source pointers and review reasons are recorded in `review-sources.json`.

## Detailed identity and profile ledger

| Concept ID | Canonical name | Area | Parent | Benchmark IDs | Profile review |
|---|---|---|---|---|---|
| divisibility | Divisibility | divisibility | — | 14, 17, 176 | profiles_differ |
| divisibility-chains | Divisibility chains | divisibility | divisibility | No attached profile | no_attached_profile |
| divisibility-graphs | Divisibility graphs | divisibility | divisibility | No attached profile | no_attached_profile |
| gcd | Greatest common divisor (GCD) | divisibility | — | 19 | consistent |
| lcm | Least common multiple (LCM) | divisibility | — | 20 | consistent |
| gcd-lcm-identities | GCD-LCM identities | divisibility | — | No attached profile | no_attached_profile |
| euclidean-algorithm | Euclidean algorithm | divisibility | — | 18 | consistent |
| bezout | Bezout's identity | divisibility | — | 16 | consistent |
| coprimality | Coprimality | divisibility | — | 181 | consistent |
| pairwise-coprimality | Pairwise coprimality | divisibility | coprimality | No attached profile | no_attached_profile |
| prime-factorization | Prime factorization | divisibility | — | 1503 | consistent |
| primes | Prime numbers | divisibility | — | 91, 94, 95 | profiles_differ |
| primality | Primality testing | divisibility | — | 158 | consistent |
| composites | Composite numbers | divisibility | — | 219, 220, 221, 222 | consistent |
| prime-divisors | Prime divisors and prime-divisor analysis | divisibility | — | 92, 93 | profiles_differ |
| extreme-prime-factor | Smallest and largest prime factors | divisibility | — | No attached profile | no_attached_profile |
| prime-support | Prime support | divisibility | — | 160 | consistent |
| prime-exponent-vectors | Prime-exponent vectors | divisibility | — | 1646, 1696 | consistent |
| prime-powers | Prime powers | divisibility | — | 187, 188 | consistent |
| squarefree | Squarefree integers | divisibility | — | 541 | consistent |
| radical | Squarefree kernel / radical | divisibility | — | No attached profile | no_attached_profile |
| powerful-numbers | Powerful numbers | divisibility | — | No attached profile | no_attached_profile |
| perfect-powers | Perfect powers | divisibility | — | 853 | consistent |
| perfect-squares | Perfect squares | divisibility | perfect-powers | 156, 166, 167 | profiles_differ |
| perfect-cubes | Perfect cubes | divisibility | perfect-powers | No attached profile | no_attached_profile |
| square-obstruction | Perfect-square obstructions | divisibility | — | 168 | consistent |
| square-gaps | Gaps between squares | divisibility | — | 154, 155 | profiles_differ |
| divisors | Divisors | divisibility | — | No attached profile | no_attached_profile |
| divisor-poset | Divisor posets and lattices | divisibility | — | 715 | consistent |
| divisor-bounds | Divisor bounds | divisibility | — | No attached profile | no_attached_profile |
| smooth-numbers | Smooth numbers | divisibility | — | No attached profile | no_attached_profile |
| primorials | Primorials | divisibility | — | No attached profile | no_attached_profile |
| consecutive-products | Products of consecutive integers | divisibility | — | 164, 165 | consistent |
| euclid-infinitude | Euclid's infinitude-of-primes argument | divisibility | — | 180, 244, 245, 246, 247 | profiles_differ |
| bertrand | Bertrand-type prime bounds | divisibility | — | No attached profile | no_attached_profile |
| prime-intervals | Primes in intervals | divisibility | — | No attached profile | no_attached_profile |
| dirichlet-primes | Dirichlet's theorem on primes in arithmetic progressions | divisibility | — | 241, 242 | consistent |
| mersenne | Mersenne numbers | divisibility | — | 184, 185 | profiles_differ |
| modular-arithmetic | Congruences and modular arithmetic | congruences | — | 5, 7, 12, 269, 277 | profiles_differ |
| residue-classes | Residue classes | congruences | — | 13, 262, 267, 278, 299, 310, 315, 316, 317 | profiles_differ |
| residue-systems | Residue systems | congruences | — | 546 | consistent |
| complete-residue-system | Complete residue systems | congruences | residue-systems | No attached profile | no_attached_profile |
| reduced-residue-system | Reduced residue systems | congruences | residue-systems | No attached profile | no_attached_profile |
| modular-inverses | Modular inverses | congruences | — | No attached profile | no_attached_profile |
| congruence-equations | Congruence equations and solutions | congruences | — | 275 | consistent |
| modular-roots | Roots of congruences | congruences | — | No attached profile | no_attached_profile |
| modular-obstructions | Modular obstructions | congruences | — | 270, 1404 | profiles_differ |
| modular-construction | Modular constructions | congruences | — | No attached profile | no_attached_profile |
| crt | Chinese remainder theorem | congruences | — | 265, 266 | consistent |
| fermat-little | Fermat's little theorem | congruences | — | 359 | consistent |
| euler-theorem | Euler's theorem | congruences | — | 948 | consistent |
| wilson | Wilson's theorem | congruences | — | No attached profile | no_attached_profile |
| wilson-products | Wilson-type products | congruences | — | No attached profile | no_attached_profile |
| multiplicative-order | Multiplicative order | congruences | — | No attached profile | no_attached_profile |
| primitive-roots | Primitive roots | congruences | — | No attached profile | no_attached_profile |
| unit-groups | Unit groups modulo n | congruences | — | No attached profile | no_attached_profile |
| cyclic-subgroups | Cyclic groups and subgroups modulo n | congruences | — | 345, 346 | consistent |
| discrete-logarithms | Discrete logarithms | congruences | — | 306, 348, 362, 363 | consistent |
| carmichael | Carmichael function and universal exponent | congruences | — | 305, 327, 328, 329, 330 | consistent |
| euler-quotient | Euler quotient | congruences | — | 355, 356 | consistent |
| modular-exponentiation | Modular exponentiation | congruences | — | 367 | consistent |
| polynomial-congruences | Polynomial congruences | congruences | — | No attached profile | no_attached_profile |
| modular-invariants | Modular invariants | congruences | — | No attached profile | no_attached_profile |
| congruence-sieves | Congruence sieves | congruences | — | No attached profile | no_attached_profile |
| residue-covering | Residue covering | congruences | — | No attached profile | no_attached_profile |
| modular-digit-constraints | Modular digit constraints | congruences | — | No attached profile | no_attached_profile |
| quadratic-residues | Quadratic residues | residues | power-residues | 271, 281, 540 | profiles_differ |
| cubic-residues | Cubic residues | residues | power-residues | No attached profile | no_attached_profile |
| power-residues | Higher power residues | residues | — | No attached profile | no_attached_profile |
| legendre-symbol | Legendre symbol | residues | — | 308 | consistent |
| jacobi-symbol | Jacobi symbol | residues | — | 375, 376 | consistent |
| quadratic-characters | Quadratic characters | residues | — | 312 | consistent |
| euler-criterion | Euler's criterion | residues | — | No attached profile | no_attached_profile |
| quadratic-reciprocity | Quadratic reciprocity | residues | — | 279, 280, 313 | consistent |
| p-adic-valuation | p-adic valuations | valuations | — | 43, 45, 46, 47, 282, 370, 384, 385, 564, 895 | profiles_differ |
| valuation-growth | Valuation growth | valuations | — | No attached profile | no_attached_profile |
| valuation-descent | Valuation descent | valuations | infinite-descent | No attached profile | no_attached_profile |
| valuation-parity | Parity of valuations | valuations | — | No attached profile | no_attached_profile |
| valuation-bounds | Valuation bounds | valuations | — | No attached profile | no_attached_profile |
| p-adic-congruences | p-adic congruences | valuations | — | No attached profile | no_attached_profile |
| lifting | Congruence and p-adic lifting | valuations | — | 263, 264, 276, 386, 387 | profiles_differ |
| hensel | Hensel's lemma and root lifting | valuations | lifting | 272, 273, 378 | profiles_differ |
| p-adic-roots | p-adic roots | valuations | — | 274 | consistent |
| p-adic-continuity | p-adic continuity | valuations | — | No attached profile | no_attached_profile |
| p-adic-polynomial-functions | p-adic polynomial functions | valuations | — | No attached profile | no_attached_profile |
| mahler-basis | Mahler basis | valuations | — | 388, 389 | consistent |
| lte | Lifting the exponent (LTE) | valuations | — | 284, 461, 563, 565 | profiles_differ |
| legendre-formula | Legendre's factorial-valuation formula | valuations | — | 885 | consistent |
| kummer | Kummer's theorem | valuations | — | 379, 380 | consistent |
| lucas-theorem | Lucas's theorem | valuations | — | No attached profile | no_attached_profile |
| factorial-valuations | Factorial valuations | valuations | — | No attached profile | no_attached_profile |
| binomial-valuations | Binomial valuations | valuations | — | No attached profile | no_attached_profile |
| p-adic-obstruction | p-adic obstructions | valuations | — | No attached profile | no_attached_profile |
| p-adic-construction | p-adic constructions | valuations | — | No attached profile | no_attached_profile |
| wieferich | Wieferich-type obstructions | valuations | — | No attached profile | no_attached_profile |
| wolstenholme | Wolstenholme-type congruences | valuations | — | No attached profile | no_attached_profile |
| diophantine-equations | Diophantine equations and integer solutions | diophantine | — | 533, 534 | profiles_differ |
| diophantine-inequalities | Diophantine inequalities | diophantine | — | No attached profile | no_attached_profile |
| rational-solutions | Rational solutions | diophantine | — | No attached profile | no_attached_profile |
| infinite-descent | Infinite descent | diophantine | — | 75 | consistent |
| vieta-jumping | Vieta jumping | diophantine | — | 560 | consistent |
| pell | Pell equations | diophantine | quadratic-diophantine | 559 | consistent |
| markov-equations | Markov-type equations | diophantine | quadratic-diophantine | No attached profile | no_attached_profile |
| pythagorean-triples | Pythagorean triples | diophantine | — | No attached profile | no_attached_profile |
| heronian-triangles | Heronian triangles | diophantine | — | No attached profile | no_attached_profile |
| discriminant-square | Discriminant-square method | diophantine | — | No attached profile | no_attached_profile |
| quadratic-diophantine | Quadratic Diophantine equations | diophantine | diophantine-equations | 1426 | consistent |
| cubic-diophantine | Cubic Diophantine equations | diophantine | diophantine-equations | No attached profile | no_attached_profile |
| exponential-diophantine | Exponential Diophantine equations | diophantine | diophantine-equations | No attached profile | no_attached_profile |
| factorial-diophantine | Factorial Diophantine equations | diophantine | diophantine-equations | No attached profile | no_attached_profile |
| catalan | Catalan-Mihailescu theorem and equations | diophantine | — | No attached profile | no_attached_profile |
| s-unit-equations | S-unit equations | diophantine | — | No attached profile | no_attached_profile |
| unit-equations | Unit equations | diophantine | — | No attached profile | no_attached_profile |
| egyptian-fractions | Egyptian fractions | diophantine | — | 690 | consistent |
| frobenius-coin | Frobenius coin problem | diophantine | — | 1138, 1466 | profiles_differ |
| numerical-semigroups | Numerical semigroups | diophantine | — | 1496 | consistent |
| conic-parametrization | Rational points and parametrization of conics | diophantine | — | No attached profile | no_attached_profile |
| growth-bounds | Growth bounds for integer equations | diophantine | — | No attached profile | no_attached_profile |
| divisibility-bounds | Divisibility bounds for integer equations | diophantine | — | No attached profile | no_attached_profile |
| local-obstructions | Local obstructions | diophantine | — | No attached profile | no_attached_profile |
| primitive-reduction | Reduction to primitive solutions | diophantine | — | 161 | consistent |
| coprime-factor-splitting | Coprime factor splitting | diophantine | — | No attached profile | no_attached_profile |
| difference-squares | Difference of squares | diophantine | — | 824 | consistent |
| sum-two-squares | Representation as a sum of two squares | diophantine | — | No attached profile | no_attached_profile |
| fermat-two-squares | Fermat's two-square theorem | diophantine | — | 1375, 1441 | profiles_differ |
| sum-three-squares | Representation as a sum of three squares | diophantine | — | No attached profile | no_attached_profile |
| sums-of-powers | Sums of powers | diophantine | — | No attached profile | no_attached_profile |
| arithmetic-functions | Arithmetic functions | arithmetic-functions | — | 936 | consistent |
| tau | Divisor-count function tau(n) | arithmetic-functions | — | 178 | consistent |
| sigma | Sum-of-divisors function sigma(n) | arithmetic-functions | — | 179 | consistent |
| phi | Euler's totient function phi(n) | arithmetic-functions | — | 947 | consistent |
| mobius-function | Mobius function | arithmetic-functions | — | No attached profile | no_attached_profile |
| mobius-inversion | Mobius inversion | arithmetic-functions | — | 721 | consistent |
| liouville | Liouville function | arithmetic-functions | — | 294, 295 | consistent |
| omega | Distinct-prime-factor count omega(n) | arithmetic-functions | — | No attached profile | no_attached_profile |
| dirichlet-convolution | Dirichlet convolution | arithmetic-functions | — | No attached profile | no_attached_profile |
| divisor-sums | Divisor sums | arithmetic-functions | — | No attached profile | no_attached_profile |
| summatory-divisor | Summatory divisor function | arithmetic-functions | — | No attached profile | no_attached_profile |
| multiplicative-functions | Multiplicative arithmetic functions | arithmetic-functions | — | No attached profile | no_attached_profile |
| completely-multiplicative | Completely multiplicative functions | arithmetic-functions | multiplicative-functions | No attached profile | no_attached_profile |
| additive-functions | Additive arithmetic functions | arithmetic-functions | — | No attached profile | no_attached_profile |
| totient-chains | Totient chains | arithmetic-functions | — | No attached profile | no_attached_profile |
| divisor-function-dynamics | Divisor-function dynamics | arithmetic-functions | — | No attached profile | no_attached_profile |
| highly-composite | Highly composite numbers | arithmetic-functions | — | 169, 182, 183 | profiles_differ |
| practical-numbers | Practical numbers | arithmetic-functions | — | 189, 190 | profiles_differ |
| abundant-numbers | Abundant numbers | arithmetic-functions | — | No attached profile | no_attached_profile |
| average-orders | Elementary average-order estimates | arithmetic-functions | — | No attached profile | no_attached_profile |
| euler-products | Euler products | arithmetic-functions | — | 248, 249 | consistent |
| gaussian-integers | Gaussian integers | algebraic | — | No attached profile | no_attached_profile |
| eisenstein-integers | Eisenstein integers | algebraic | — | No attached profile | no_attached_profile |
| quadratic-fields | Quadratic fields | algebraic | — | No attached profile | no_attached_profile |
| quadratic-integer-rings | Quadratic integer rings | algebraic | — | No attached profile | no_attached_profile |
| algebraic-norms | Algebraic norms and norm forms | algebraic | — | No attached profile | no_attached_profile |
| ufd | Unique factorization in rings | algebraic | — | No attached profile | no_attached_profile |
| binary-quadratic-forms | Binary quadratic forms | algebraic | — | No attached profile | no_attached_profile |
| quadratic-form-representations | Representation by x^2 + d*y^2 | algebraic | — | No attached profile | no_attached_profile |
| cyclotomic-polynomials | Cyclotomic polynomials | algebraic | — | No attached profile | no_attached_profile |
| cyclotomic-factorization | Cyclotomic factorization | algebraic | — | No attached profile | no_attached_profile |
| primitive-prime-divisors | Primitive prime divisors | algebraic | — | 603, 604 | profiles_differ |
| zsigmondy | Zsigmondy's theorem | algebraic | — | 163, 606 | profiles_differ |
| lucas-sequences | Lucas sequences | algebraic | — | No attached profile | no_attached_profile |
| fibonacci-divisibility | Fibonacci divisibility | algebraic | — | No attached profile | no_attached_profile |
| carmichael-primitive-divisors | Carmichael-type primitive-divisor arguments | algebraic | — | No attached profile | no_attached_profile |
| conjugation | Algebraic conjugation | algebraic | — | No attached profile | no_attached_profile |
| minimal-polynomials | Minimal polynomial arguments | algebraic | — | No attached profile | no_attached_profile |
| field-degree-obstructions | Field-degree and irrationality obstructions | algebraic | — | No attached profile | no_attached_profile |
| hilbert-90 | Hilbert's theorem 90 | algebraic | — | No attached profile | no_attached_profile |
| base-representation | Positional base representation | digits | — | 96, 1520 | profiles_differ |
| digits | Digits and digit constraints | digits | — | 517, 1538 | profiles_differ |
| digit-sums | Digit sums | digits | — | No attached profile | no_attached_profile |
| digital-root | Digital root | digits | — | No attached profile | no_attached_profile |
| digit-products | Digit products | digits | — | No attached profile | no_attached_profile |
| digit-dp | Digit dynamic programming | digits | — | No attached profile | no_attached_profile |
| carries | Carry analysis | digits | — | 381, 516 | profiles_differ |
| carry-free | Carry-free constructions | digits | carries | No attached profile | no_attached_profile |
| repunits | Repunits | digits | — | No attached profile | no_attached_profile |
| repeating-expansions | Repeating expansions and their periods | digits | — | No attached profile | no_attached_profile |
| digit-palindromes | Digit palindromes | digits | — | No attached profile | no_attached_profile |
| automorphic-numbers | Automorphic numbers | digits | — | No attached profile | no_attached_profile |
| leading-digits | Leading digits | digits | — | No attached profile | no_attached_profile |
| benford | Benford-type logarithmic mantissas | digits | — | No attached profile | no_attached_profile |
| mixed-radix | Mixed-radix representation | digits | — | No attached profile | no_attached_profile |
| digit-automata | Digit automata and finite-state residue systems | digits | — | No attached profile | no_attached_profile |
| automatic-sequences | Automatic sequences | digits | — | No attached profile | no_attached_profile |
| arithmetic-progressions | Arithmetic progressions | additive | — | 777 | consistent |
| geometric-progressions | Geometric progressions | additive | — | No attached profile | no_attached_profile |
| additive-bases | Additive bases | additive | — | No attached profile | no_attached_profile |
| additive-combinatorics | Additive combinatorics over integers | additive | — | No attached profile | no_attached_profile |
| sumsets | Sumsets | additive | — | No attached profile | no_attached_profile |
| product-sets | Product sets | additive | — | No attached profile | no_attached_profile |
| sum-product | Sum-product phenomena | additive | — | No attached profile | no_attached_profile |
| sum-free | Sum-free sets | additive | — | No attached profile | no_attached_profile |
| zero-sum | Zero-sum sequences | additive | — | No attached profile | no_attached_profile |
| egz | Erdos-Ginzburg-Ziv theorem | additive | — | No attached profile | no_attached_profile |
| cauchy-davenport | Cauchy-Davenport theorem | additive | — | No attached profile | no_attached_profile |
| davenport-constant | Davenport constant | additive | — | No attached profile | no_attached_profile |
| van-der-waerden | Van der Waerden's theorem | additive | — | No attached profile | no_attached_profile |
| sidon | Sidon sets | additive | — | No attached profile | no_attached_profile |
| distinct-differences | Distinct differences | additive | — | No attached profile | no_attached_profile |
| difference-sets | Difference sets | additive | — | 1051 | consistent |
| additive-groups | Modular additive groups | additive | — | No attached profile | no_attached_profile |
| multiplicative-groups | Multiplicative groups | additive | — | No attached profile | no_attached_profile |
| additive-energy | Additive energy | additive | — | 1604 | consistent |
| density | Density arguments | additive | — | No attached profile | no_attached_profile |
| dirichlet-approximation | Dirichlet approximation | approximation | — | No attached profile | no_attached_profile |
| farey | Farey fractions | approximation | — | 530 | consistent |
| stern-brocot | Stern-Brocot tree | approximation | — | No attached profile | no_attached_profile |
| continued-fractions | Continued fractions | approximation | — | No attached profile | no_attached_profile |
| beatty | Beatty sequences | approximation | — | 529 | consistent |
| kronecker | Kronecker approximation | approximation | — | No attached profile | no_attached_profile |
| fractional-parts | Fractional parts and arithmetic modulo 1 | approximation | — | 1298 | consistent |
| equidistribution | Equidistribution modulo 1 | approximation | — | No attached profile | no_attached_profile |
| floor-ceiling | Floor and ceiling functions | approximation | — | 520, 911 | profiles_differ |
| rounding | Rounding and nearest-integer methods | approximation | — | 523 | consistent |
| reduced-fractions | Reduced fractions | approximation | — | 191, 192 | consistent |
| denominators | Denominator analysis and control | approximation | — | 194, 233, 260, 261 | profiles_differ |
| denominator-bounds | Bounded denominators | approximation | — | 205, 230 | consistent |
| rational-numbers | Rational numbers | approximation | — | 1222 | consistent |
| finite-fields | Finite fields | structures | — | 973 | consistent |
| character-sums | Character sums | structures | — | 900 | consistent |
| geometry-of-numbers | Geometry of numbers | structures | — | 1381 | consistent |
| integrality | Integrality | structures | — | 1391 | consistent |
| factorials | Factorials | structures | — | 884, 1279 | profiles_differ |
| modular-periodicity | Modular periodicity and cycles | structures | modular-dynamics | 331, 332, 358, 360, 361, 364, 365 | profiles_differ |
| modular-dynamics | Modular dynamics | structures | — | No attached profile | no_attached_profile |
| doubling-map | Doubling map | structures | modular-dynamics | 349, 350 | consistent |
| residue-representatives | Residue representatives | structures | — | 209, 210, 259, 300, 301 | profiles_differ |
| parity | Parity | structures | — | 286, 287, 290, 297 | consistent |
| parity-descent | Parity descent | structures | infinite-descent | 382, 383 | consistent |
| bounded-representations | Bounded representations | structures | — | 206, 207 | consistent |
| factorization | Factorization | shared | — | 157 | consistent |
| case-analysis | Case analysis | shared | — | 173, 211, 212, 213, 214, 215, 216 | profiles_differ |
| finite-checking | Finite checking | shared | — | 293, 321, 322, 323, 324 | consistent |
| small-case-forcing | Small-case forcing | shared | — | 302 | consistent |
| classification | Classification | shared | — | 218 | consistent |
| normalization | Normalization and reduction | shared | — | 171, 257 | profiles_differ |
| differences | Difference method | shared | — | 174, 237, 238 | profiles_differ |
| pigeonhole | Pigeonhole principle | shared | — | 175, 243, 254, 255 | profiles_differ |
| construction | Construction | shared | — | 197, 224 | profiles_differ |
| block-methods | Block decomposition and splitting | shared | — | 199, 200, 201, 202 | profiles_differ |
| intervals | Intervals and consecutive intervals | shared | — | 223, 253 | profiles_differ |
| scaling | Scaling and dilation | shared | — | 203, 204, 239, 240 | profiles_differ |
| denominator-clearing | Clearing denominators | shared | — | 231, 232 | consistent |
| cancellation | Cancellation | shared | — | 208, 226 | profiles_differ |
| cubic-polynomials | Cubic polynomials and maps | shared | — | 227 | consistent |
| degree-arguments | Polynomial degree arguments | shared | — | 228, 229 | profiles_differ |
| determinants | Determinants | shared | — | 234 | consistent |
| unimodular | Determinant-one structures | shared | — | 235 | consistent |
| difference-cubes | Difference of cubes | shared | — | 236 | consistent |
| aurifeuillean | Aurifeuillean-style identities | shared | — | 195, 196 | consistent |
| sliding-window | Sliding-window method | shared | — | 319, 320 | consistent |
| local-to-global | Local-to-global arguments | shared | — | 309 | consistent |
| order-bounds | Order computation and bounds | shared | — | 368, 369 | consistent |
| exponentiation | Powers and exponentiation | shared | — | 357, 1545 | profiles_differ |
| exponent-comparison | Exponent comparison | shared | — | 1476 | consistent |
| existence | Existence arguments | shared | — | 377 | consistent |
| finiteness | Finiteness arguments | shared | — | 250 | consistent |
| infinitude | Infinitude arguments | shared | — | 251 | consistent |
| structural-decomposition | Structural decomposition | shared | — | 193 | consistent |
| integer-configurations | Integer configurations | shared | — | 252 | consistent |
| quotients | Auxiliary quotients | shared | — | 198, 256 | profiles_differ |
| representations | Representation arguments | shared | — | 258 | consistent |
| omega-total | Prime-factor count with multiplicity Omega(n) | arithmetic-functions | — | No attached profile | no_attached_profile |
| inverse-totient | Inverse totient problem | arithmetic-functions | — | No attached profile | no_attached_profile |
| inverse-sigma | Inverse sum-of-divisors problem | arithmetic-functions | — | No attached profile | no_attached_profile |
| elliptic-curves | Elliptic curves in Diophantine problems | diophantine | — | No attached profile | no_attached_profile |
| schur-ramsey | Schur's monochromatic-equation theorem | additive | — | No attached profile | no_attached_profile |
| rado-partition | Rado's partition-regularity theorem | additive | — | No attached profile | no_attached_profile |
