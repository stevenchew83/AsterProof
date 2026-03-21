from django.db import migrations

DEFAULT_BLOCK_TYPES = [
    {
        "slug": "plain",
        "label": "Plain",
        "description": "General body text without a stronger structural role.",
        "sort_order": 10,
        "allows_children": False,
    },
    {
        "slug": "section",
        "label": "Section",
        "description": "Top-level section or major phase of a solution.",
        "sort_order": 20,
        "allows_children": True,
    },
    {
        "slug": "idea",
        "label": "Idea",
        "description": "A strategy sketch or motivating thought.",
        "sort_order": 30,
        "allows_children": True,
    },
    {
        "slug": "claim",
        "label": "Claim",
        "description": "A named intermediate claim.",
        "sort_order": 40,
        "allows_children": True,
    },
    {
        "slug": "proof",
        "label": "Proof",
        "description": "A proof block, often attached to a claim or part.",
        "sort_order": 50,
        "allows_children": True,
    },
    {
        "slug": "case",
        "label": "Case",
        "description": "A major case split.",
        "sort_order": 60,
        "allows_children": True,
    },
    {
        "slug": "subcase",
        "label": "Subcase",
        "description": "A nested case split inside a case block.",
        "sort_order": 70,
        "allows_children": True,
    },
    {
        "slug": "part",
        "label": "Part",
        "description": "A numbered or named part of the argument.",
        "sort_order": 80,
        "allows_children": True,
    },
    {
        "slug": "observation",
        "label": "Observation",
        "description": "A short observation or lemma-like note.",
        "sort_order": 90,
        "allows_children": False,
    },
    {
        "slug": "computation",
        "label": "Computation",
        "description": "An algebraic or arithmetic derivation block.",
        "sort_order": 100,
        "allows_children": False,
    },
    {
        "slug": "conclusion",
        "label": "Conclusion",
        "description": "A closing step such as therefore or hence.",
        "sort_order": 110,
        "allows_children": False,
    },
    {
        "slug": "remark",
        "label": "Remark",
        "description": "An aside, note, or alternative comment.",
        "sort_order": 120,
        "allows_children": False,
    },
]


def seed_solution_block_types(apps, schema_editor) -> None:
    del schema_editor
    SolutionBlockType = apps.get_model("solutions", "SolutionBlockType")
    for payload in DEFAULT_BLOCK_TYPES:
        SolutionBlockType.objects.update_or_create(
            slug=payload["slug"],
            defaults={
                "allows_children": payload["allows_children"],
                "description": payload["description"],
                "is_system": True,
                "label": payload["label"],
                "sort_order": payload["sort_order"],
            },
        )


def unseed_solution_block_types(apps, schema_editor) -> None:
    del schema_editor
    SolutionBlockType = apps.get_model("solutions", "SolutionBlockType")
    SolutionBlockType.objects.filter(
        slug__in=[payload["slug"] for payload in DEFAULT_BLOCK_TYPES],
        is_system=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("solutions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_solution_block_types, unseed_solution_block_types),
    ]
