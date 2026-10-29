"""Select only the separately approved, hash-frozen additive schema plans."""

from __future__ import annotations

from scripts.deployment import concept_schema
from scripts.deployment import newsletter_schema
from scripts.deployment import solution_pdf_schema
from scripts.deployment import website_schema


def schema_for_disclosure(value):
    if isinstance(value, dict) and value.get("migration") == solution_pdf_schema.MIGRATION:
        return solution_pdf_schema
    if isinstance(value, dict) and value.get("migration") == newsletter_schema.MIGRATION:
        return newsletter_schema
    if isinstance(value, dict) and value.get("migration") == website_schema.MIGRATION:
        return website_schema
    # Unknown plans still fail the original strict disclosure validator.
    return concept_schema


def validate_disclosure(value, *, target_sha):
    return schema_for_disclosure(value).validate_disclosure(value, target_sha=target_sha)
