from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Contest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("short_code", models.CharField(max_length=64, unique=True)),
                (
                    "contest_type",
                    models.CharField(
                        choices=[
                            ("imo", "IMO"),
                            ("shortlist", "Shortlist"),
                            ("apmo", "APMO"),
                            ("rmm", "RMM"),
                            ("egmo", "EGMO"),
                            ("tst", "TST"),
                            ("training", "Training"),
                            ("custom", "Custom"),
                        ],
                        max_length=32,
                    ),
                ),
                ("year", models.PositiveIntegerField()),
                ("round", models.CharField(blank=True, max_length=100)),
                ("country", models.CharField(blank=True, max_length=100)),
                ("official_url", models.URLField(blank=True)),
                ("official_pdf_url", models.URLField(blank=True)),
                (
                    "visibility_state",
                    models.CharField(
                        choices=[("draft", "Draft"), ("internal", "Internal"), ("public", "Public")],
                        default="public",
                        max_length=16,
                    ),
                ),
            ],
            options={"ordering": ["-year", "short_code"]},
        ),
        migrations.CreateModel(
            name="Tag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64, unique=True)),
                ("slug", models.SlugField(unique=True)),
                (
                    "category",
                    models.CharField(
                        choices=[("topic", "Topic"), ("technique", "Technique"), ("theme", "Theme")],
                        default="topic",
                        max_length=16,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Problem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(help_text="P1-P6 or custom label", max_length=64)),
                ("title", models.CharField(blank=True, max_length=255)),
                ("statement", models.TextField()),
                ("editorial_difficulty", models.PositiveSmallIntegerField(default=3)),
                ("editorial_quality", models.PositiveSmallIntegerField(default=3)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("hidden", "Hidden"), ("experimental", "Experimental")],
                        default="active",
                        max_length=16,
                    ),
                ),
                (
                    "canonical_problem",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="duplicates",
                        to="catalog.problem",
                    ),
                ),
                (
                    "contest",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="problems",
                        to="catalog.contest",
                    ),
                ),
            ],
            options={"ordering": ["contest__year", "label"], "unique_together": {("contest", "label")}},
        ),
        migrations.CreateModel(
            name="ProblemTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("problem", models.ForeignKey(on_delete=models.CASCADE, to="catalog.problem")),
                ("tag", models.ForeignKey(on_delete=models.CASCADE, to="catalog.tag")),
            ],
            options={"unique_together": {("problem", "tag")}},
        ),
        migrations.AddField(
            model_name="problem",
            name="tags",
            field=models.ManyToManyField(related_name="problems", through="catalog.ProblemTag", to="catalog.tag"),
        ),
        migrations.CreateModel(
            name="ProblemReference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("url", models.URLField(blank=True)),
                (
                    "problem",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="references", to="catalog.problem"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="RelatedProblem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "relation_type",
                    models.CharField(
                        choices=[
                            ("similar", "Similar to"),
                            ("generalisation", "Generalisation of"),
                            ("uses_lemma", "Uses lemma from"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "source_problem",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="related_from", to="catalog.problem"),
                ),
                (
                    "target_problem",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="related_to", to="catalog.problem"),
                ),
            ],
            options={"unique_together": {("source_problem", "target_problem", "relation_type")}},
        ),
    ]
