"""Canonical area metadata for the bounded completion-record inventory."""

from collections import defaultdict

from django.urls import reverse

from inspinia.pages.concept_assignment_service import projection_enabled
from inspinia.pages.concept_assignment_service import projection_payloads
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.statement_concept_coverage import TAG_FIELDS
from inspinia.pages.statement_concept_coverage import TagCoverageResolver
from inspinia.pages.statement_concept_coverage import _coverage
from inspinia.pages.statement_concept_coverage import statement_coverage_payloads
from inspinia.pages.topic_labels import display_topic_label


def completion_record_area_metadata(completions):
    """Resolve only visible identities; statement tags own their linked archive source."""
    statements = {c.statement_id: c.statement for c in completions if c.statement_id}
    legacy_ids = {c.problem_id for c in completions if not c.statement_id and c.problem_id}
    linked = {}
    for statement in (
        ContestProblemStatement.objects.filter(linked_problem_id__in=legacy_ids)
        .select_related("linked_problem")
        .only(
            "id",
            "statement_uuid",
            "problem_uuid",
            "linked_problem_id",
            "topic",
            "mohs",
            "is_active",
            "linked_problem__topic",
            "linked_problem__mohs",
        )
        .order_by("-is_active", "id")
    ):
        linked.setdefault(statement.linked_problem_id, statement)
        statements[statement.pk] = statement

    assignment_mode = projection_enabled()
    keys = {}
    if assignment_mode:
        keys = {
            completion.pk: str(
                (completion.statement if completion.statement_id else linked.get(completion.problem_id)).problem_uuid
                if completion.statement_id or completion.problem_id in linked
                else completion.problem.problem_uuid,
            )
            for completion in completions
        }
        payloads = projection_payloads(load_sources(keys.values()))
    else:
        resolver = TagCoverageResolver()
        payloads = statement_coverage_payloads(list(statements.values()), resolver=resolver)
    archive_tags = defaultdict(list)
    for tag in (
        ProblemTopicTechnique.objects.filter(record_id__in=[] if assignment_mode else legacy_ids - linked.keys())
        .order_by(
            "technique",
            "id",
        )
        .values("record_id", *TAG_FIELDS)
    ):
        archive_tags[tag["record_id"]].append(tag)

    result = {}
    for completion in completions:
        statement = completion.statement if completion.statement_id else linked.get(completion.problem_id)
        if assignment_mode:
            payload = payloads[keys[completion.pk]]
        elif statement is not None:
            payload = payloads[statement.pk]
        else:
            problem = completion.problem
            payload = _coverage(
                archive_tags[problem.pk],
                topic=problem.topic,
                active=problem.is_active,
                resolver=resolver,
            )
        if completion.statement_id:
            topic, mohs = effective_topic(completion.statement), effective_mohs(completion.statement)
        else:
            topic, mohs = completion.problem.topic, completion.problem.mohs
        result[completion.pk] = {
            "areas": payload["concept_areas"],
            "area_mapping_status": payload["concept_coverage_status"],
            "topic": display_topic_label(topic) if topic else "Unspecified",
            "mohs": mohs if mohs is not None else "",
            "statement_url": reverse("pages:problem_statement_detail", args=[statement.statement_uuid])
            if statement is not None
            else "",
        }
    return result
