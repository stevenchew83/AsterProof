"""Select only the separately approved, hash-frozen additive schema plans."""

from __future__ import annotations

from scripts.deployment import concept_schema
from scripts.deployment import curated_collections_schema
from scripts.deployment import newsletter_automation_schema
from scripts.deployment import newsletter_schema
from scripts.deployment import onboarding_schema
from scripts.deployment import solution_analytics_schema
from scripts.deployment import solution_collections_schema
from scripts.deployment import solution_pdf_schema
from scripts.deployment import solution_sharing_schema
from scripts.deployment import website_schema


def schema_for_disclosure(value):  # noqa: PLR0911 - Keep each frozen allowance explicit.
    if isinstance(value, dict) and value.get("migration") == curated_collections_schema.MIGRATION:
        return curated_collections_schema
    if isinstance(value, dict) and value.get("migration") == solution_collections_schema.MIGRATION:
        return solution_collections_schema
    if isinstance(value, dict) and value.get("migration") == onboarding_schema.MIGRATION:
        return onboarding_schema
    if isinstance(value, dict) and value.get("migration") == solution_analytics_schema.MIGRATION:
        return solution_analytics_schema
    if isinstance(value, dict) and value.get("migration") == solution_sharing_schema.MIGRATION:
        return solution_sharing_schema
    if isinstance(value, dict) and value.get("migration") == newsletter_automation_schema.MIGRATION:
        return newsletter_automation_schema
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
