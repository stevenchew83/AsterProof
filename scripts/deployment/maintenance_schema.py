"""Literal dispatch for independently frozen maintenance allowances."""

from scripts.deployment import catalogue_schema
from scripts.deployment import community_proof_schema
from scripts.deployment import community_schema
from scripts.deployment import ranking_profile_schema


def validate_disclosure(value, *, target_sha):
    if isinstance(value, dict) and value.get("kind") == ranking_profile_schema.KIND:
        return ranking_profile_schema.validate_disclosure(value, target_sha=target_sha)
    if isinstance(value, dict) and value.get("kind") == community_proof_schema.KIND:
        return community_proof_schema.validate_disclosure(value, target_sha=target_sha)
    if isinstance(value, dict) and value.get("kind") == community_schema.KIND:
        return community_schema.validate_disclosure(value, target_sha=target_sha)
    return catalogue_schema.validate_disclosure(value, target_sha=target_sha)


def validate_build_evidence(release, disclosure):
    if disclosure.get("kind") == ranking_profile_schema.KIND:
        ranking_profile_schema.validate_build_evidence(release, disclosure)
        return
    if disclosure.get("kind") == community_proof_schema.KIND:
        community_proof_schema.validate_build_evidence(release, disclosure)
        return
    if disclosure.get("kind") == community_schema.KIND:
        community_schema.validate_build_evidence(release, disclosure)
    else:
        catalogue_schema.validate_build_evidence(release, disclosure)
