from django.db import migrations

from inspinia.training.taxonomy import TRAINING_TAXONOMY
from inspinia.training.taxonomy import normalize_seed_title
from inspinia.training.taxonomy import unique_slug_for_title


def seed_expanded_training_taxonomy(apps, schema_editor) -> None:
    del schema_editor
    Topic = apps.get_model("training", "Topic")
    Subtopic = apps.get_model("training", "Subtopic")

    for topic_payload in TRAINING_TAXONOMY:
        topic, _created = Topic.objects.update_or_create(
            slug=topic_payload["slug"],
            defaults={
                "description": topic_payload["description"],
                "is_published": True,
                "order": topic_payload["order"],
                "title": normalize_seed_title(topic_payload["title"]),
            },
        )
        existing_slugs_by_title = {
            normalize_seed_title(subtopic.title): subtopic.slug for subtopic in Subtopic.objects.filter(topic=topic)
        }
        used_slugs = set(existing_slugs_by_title.values())

        for index, subtopic_title in enumerate(topic_payload["subtopics"], start=1):
            normalized_title = normalize_seed_title(subtopic_title)
            slug = existing_slugs_by_title.get(normalized_title)
            if slug is None:
                slug = unique_slug_for_title(normalized_title, used_slugs)
            used_slugs.add(slug)
            Subtopic.objects.update_or_create(
                topic=topic,
                slug=slug,
                defaults={
                    "description": "",
                    "is_published": True,
                    "order": index * 10,
                    "title": normalized_title,
                },
            )


def noop_reverse(apps, schema_editor) -> None:
    del apps, schema_editor


class Migration(migrations.Migration):
    dependencies = [
        ("training", "0002_seed_training_topics"),
    ]

    operations = [
        migrations.RunPython(seed_expanded_training_taxonomy, noop_reverse),
    ]
