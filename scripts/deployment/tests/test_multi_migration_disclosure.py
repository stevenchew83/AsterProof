"""Exercise the workflow's actual expected-plan code for each bounded allowance."""

import json
import textwrap
from pathlib import Path

import pytest

from scripts.deployment import assessment_prototype_schema
from scripts.deployment import concept_schema
from scripts.deployment import learning_schema

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("schema", "identities"),
    [
        (assessment_prototype_schema, [
            "solutions.0011_problem_evaluation_packages",
            "solutions.0012_synthetic_review_prototype",
        ]),
        (learning_schema, [
            "learning.0001_initial",
            "learning.0002_contentdraft_is_archived",
            "pages.0046_prerequisitegraphstate_catalogueprerequisite",
            "training.0006_learningpath_learningpathrevision_learningpathitem_and_more",
        ]),
        (concept_schema, [concept_schema.MIGRATION]),
    ],
)
def test_actual_workflow_discloses_every_migration_in_the_exact_allowance(schema, identities):
    workflow = (ROOT / ".github/workflows/production-deploy.yml").read_text()
    start = workflow.index("                  from scripts.deployment.additive_schema import")
    end = workflow.index("              schema = validate_disclosure", start)
    code = textwrap.dedent(workflow[start:end])
    namespace = {"json": json, "os_disclosure": json.dumps({"migration": schema.MIGRATION})}
    exec(compile(code, "production-deploy-expected-plan", "exec"), namespace)  # noqa: S102 - Execute reviewed workflow code, never request input.
    assert namespace["expected"] == [
        {"migration": identity, "classification": "backward-compatible-schema"}
        for identity in identities
    ]
