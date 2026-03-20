import re

from django.db import models


class ProblemSolveRecord(models.Model):
    """
    Stores one row from the Excel analytics sheet.

    Note: fields store the raw cell text for strings (including prefixes like
    "IMO slot guess:"), so we can parse/split them later without losing data.
    """

    year = models.IntegerField()
    topic = models.CharField(max_length=32)
    mohs = models.IntegerField()

    contest = models.CharField(max_length=64)
    problem = models.CharField(max_length=64)

    # Second "CONTEST" column in the sample, e.g. "BMO SL 2020 P1".
    contest_year_problem = models.CharField(max_length=128, null=True, blank=True)

    solve_date = models.DateField(null=True, blank=True)

    confidence = models.TextField(null=True, blank=True)
    imo_slot_guess = models.TextField(null=True, blank=True)
    # Normalized candidate IMO slot numbers extracted from `imo_slot_guess`.
    # Examples:
    # - "IMO slot guess: P1/4" -> "4"
    # - "IMO slot guess: P1/4 - P2/5" -> "4,5"
    # - "IMO slot guess: -" -> NULL
    imo_slot_guess_value = models.TextField(null=True, blank=True)
    topic_tags = models.TextField(null=True, blank=True)
    rationale = models.TextField(null=True, blank=True)
    # Rationale text with prefixes removed (for example "Rationale:" / "Rationale (1-2 lines):").
    rationale_value = models.TextField(null=True, blank=True)
    # Pitfalls text with prefixes removed (e.g. strip "Common pitfalls:" prefix).
    pitfalls_value = models.TextField(null=True, blank=True)
    pitfalls = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "contest", "problem"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "contest", "problem"],
                name="pages_problemsolverecord_unique_year_contest_problem",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.year} {self.contest} {self.problem}"

    @staticmethod
    def parse_imo_slot_guess_value(raw: str | None) -> str | None:
        """
        Parse many free-form "IMO slot guess" cell variants into candidate slot numbers.

        Output format:
        - NULL if no slot candidates found
        - Otherwise a comma-separated list of numbers extracted from (Problem, Slot) pairs.
          For example:
          - "IMO slot guess: P1/4" -> "1,4"
          - "IMO slot guess: P1/4-P2/5" -> "1,4,2,5"

        Note:
        - For pairs we always interpret the left number as the problem number and the right number as the slot.
        - For standalone "P4"/"P5"/"P6", we interpret it as a slot-only value and return just that number.
        """
        if not raw:
            return None

        text = str(raw).strip()
        if not text or text in {"\u2014", "-", "\u2013"}:
            return None

        # Normalize common unicode dash variants to simplify range parsing.
        text = re.sub(r"[\u2013\u2014\u2212]", "-", text)

        extracted_numbers: list[int] = []

        # Match slash pairs like:
        # - P1/4, P2/5, P3/6
        # - P1/P4
        # - P4/5
        # - P6/3
        pair_re = re.compile(r"\bP(?P<a>\d+)\s*/\s*(?:P)?(?P<b>\d+)\b")
        seen_pairs: set[tuple[int, int]] = set()
        for m in pair_re.finditer(text):
            problem = int(m.group("a"))
            slot = int(m.group("b"))
            pair = (problem, slot)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            extracted_numbers.extend([problem, slot])

        # Also match standalone slot candidates like "P4", "P5", "P6".
        # Important: strip away any "P<something>/P<something>" pairs first so
        # we don't accidentally treat the numerator "P3" in "P3/6" as a
        # standalone slot "3".
        text_without_pairs = pair_re.sub("", text)
        standalone_re = re.compile(r"\bP(?P<slot>[1-9])\b")
        seen_standalone_slots: set[int] = set()
        for m in standalone_re.finditer(text_without_pairs):
            slot_only = int(m.group("slot"))
            if slot_only in seen_standalone_slots:
                continue
            seen_standalone_slots.add(slot_only)
            extracted_numbers.append(slot_only)

        if not extracted_numbers:
            return None

        return ",".join(str(n) for n in extracted_numbers)

    @staticmethod
    def parse_rationale_value(raw: str | None) -> str | None:
        """
        Normalize free-form "Rationale ..." cell content.

        Examples:
        - "Rationale: Very short, parity punchline."
        - "Rationale (1-2 lines): Looks like ... full sentence."

        Returns:
        - NULL if no content found
        - Otherwise the part after the first ':' (after optional "(N-M lines)").
        """
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None

        # Normalize dash variants for the line-count annotation.
        normalized = re.sub(r"[\u2013\u2014\u2212]", "-", text)

        # Supports both "Rationale: <value>" and "Rationale (1-2 lines): <value>".
        rationale_re = re.compile(
            r"^\s*Rationale(?:\s*\(\s*\d+\s*-\s*\d+\s*lines?\s*\))?\s*:\s*(?P<value>.+?)\s*$",
            flags=re.IGNORECASE | re.DOTALL,
        )
        m = rationale_re.match(normalized)
        if m:
            return m.group("value").strip() or None

        # If it doesn't match the expected prefix format, keep the raw text as-is.
        # This supports cases where `rationale` is already just the rationale sentence.
        return text

    @staticmethod
    def parse_pitfalls_value(raw: str | None) -> str | None:
        """
        Normalize free-form "Common pitfalls ..." cell content.

        Examples:
        - "Common pitfalls: Greedy reasoning instead of identifying cold positions."

        Returns:
        - NULL if no content found
        - Otherwise the part after the first ':' (if present with the expected prefix),
          or the raw text if the prefix doesn't match.
        """
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None

        normalized = re.sub(r"[\u2013\u2014\u2212]", "-", text)
        pitfalls_re = re.compile(
            r"^\s*Common\s+pitfalls\s*:\s*(?P<value>.+?)\s*$",
            flags=re.IGNORECASE | re.DOTALL,
        )
        m = pitfalls_re.match(normalized)
        if m:
            return m.group("value").strip() or None

        return text

    def save(self, *args, **kwargs) -> None:
        self.imo_slot_guess_value = self.parse_imo_slot_guess_value(self.imo_slot_guess)
        self.rationale_value = self.parse_rationale_value(self.rationale)
        self.pitfalls_value = self.parse_pitfalls_value(self.pitfalls)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "imo_slot_guess_value",
                "rationale_value",
                "pitfalls_value",
            }

        super().save(*args, **kwargs)


class ProblemTopicTechnique(models.Model):
    """
    One parsed technique tag for a problem row, with associated domain label(s).

    `domains` is a JSON list of strings (SQLite-friendly; on Postgres you may later
    migrate to ARRAY if desired).
    """

    record = models.ForeignKey(
        ProblemSolveRecord,
        on_delete=models.CASCADE,
        related_name="topic_techniques",
    )
    technique = models.CharField(max_length=512)
    domains = models.JSONField(blank=True, default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["record", "technique"],
                name="pages_problemtopictechnique_unique_record_technique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.record.pk}: {self.technique}"
