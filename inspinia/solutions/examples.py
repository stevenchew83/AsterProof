"""The small, self-contained example used by the public walkthrough and writing tool."""

INEQUALITY_TITLE = "A first inequality"
INEQUALITY_STATEMENT = (
    r"Let $a$, $b$, and $c$ be real numbers. Prove that "
    r"\[a^2+b^2+c^2\geq ab+bc+ca.\] When does equality hold?"
)
INEQUALITY_BLOCKS = (
    {"kind": "Idea", "slug": "idea", "body": "Compare the two sides by writing their difference as a sum of squares."},
    {"kind": "Claim", "slug": "claim", "body": r"\[2(a^2+b^2+c^2-ab-bc-ca)=(a-b)^2+(b-c)^2+(c-a)^2.\]"},
    {
        "kind": "Proof", "slug": "proof",
        "body": "Every square is non-negative, so the identity gives "
        r"$a^2+b^2+c^2-ab-bc-ca\geq 0$, as required.",
    },
    {
        "kind": "Conclusion", "slug": "conclusion",
        "body": "Equality holds if and only if all three squares vanish, which is equivalent to $a=b=c$.",
    },
)
