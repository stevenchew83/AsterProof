"""Source resolution is maintenance work; catalogue/progress GETs never call this."""

from collections import defaultdict
from itertools import batched

from inspinia.pages.concept_assignment_service import projection_enabled
from inspinia.pages.concept_assignment_service import projection_payloads
from inspinia.pages.concept_assignment_trace import load_sources
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.statement_analytics import effective_mohs
from inspinia.pages.statement_analytics import effective_topic
from inspinia.pages.statement_concept_coverage import TAG_FIELDS
from inspinia.pages.statement_concept_coverage import _coverage
from inspinia.pages.statement_concept_coverage import statement_coverage_payloads
from inspinia.pages.technique_concepts import SUBJECT_LABELS

BATCH_SIZE = 256


def iter_catalogue_sources():
    assignment_mode = projection_enabled()
    statements = (
        ContestProblemStatement.objects.filter(is_active=True)
        .select_related("linked_problem")
        .only(
            "id",
            "problem_uuid",
            "statement_uuid",
            "linked_problem_id",
            "contest_name",
            "contest_year",
            "problem_code",
            "topic",
            "mohs",
            "is_active",
            "linked_problem__topic",
            "linked_problem__mohs",
        )
        .order_by("id")
    )
    for batch in batched(statements.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        if assignment_mode:
            mapped = projection_payloads(load_sources([s.problem_uuid for s in batch]))
            payloads = {s.pk: mapped[str(s.problem_uuid)] for s in batch}
        else:
            payloads = statement_coverage_payloads(batch)
        for s in batch:
            yield {
                "problem_uuid": s.problem_uuid,
                "statement_id": s.pk,
                "problem_id": s.linked_problem_id,
                "statement_uuid": s.statement_uuid,
                "label": f"{s.contest_name} {s.contest_year} {s.problem_code}",
                "contest": s.contest_name,
                "year": s.contest_year,
                "subject": SUBJECT_LABELS.get(str(effective_topic(s)).casefold(), ""),
                "mohs": effective_mohs(s),
                "coverage": payloads[s.pk]["concept_coverage"],
            }
    # An inactive statement still owns its archive link.
    archive = (
        ProblemSolveRecord.objects.filter(is_active=True, statement_entries__isnull=True)
        .order_by("id")
        .values(
            "id",
            "problem_uuid",
            "contest",
            "year",
            "problem",
            "topic",
            "mohs",
        )
    )
    for batch in batched(archive.iterator(chunk_size=BATCH_SIZE), BATCH_SIZE):
        if assignment_mode:
            payloads = projection_payloads(load_sources([r["problem_uuid"] for r in batch]))
        else:
            tags = defaultdict(list)
            for row in ProblemTopicTechnique.objects.filter(record_id__in=[r["id"] for r in batch]).values(
                "record_id",
                *TAG_FIELDS,
            ):
                tags[row["record_id"]].append(row)
            payloads = {str(r["problem_uuid"]): _coverage(tags[r["id"]], topic=r["topic"], active=True) for r in batch}
        for r in batch:
            yield {
                "problem_uuid": r["problem_uuid"],
                "statement_id": None,
                "problem_id": r["id"],
                "statement_uuid": None,
                "label": f"{r['contest']} {r['year']} {r['problem']}",
                "contest": r["contest"],
                "year": r["year"],
                "subject": SUBJECT_LABELS.get(str(r["topic"]).casefold(), ""),
                "mohs": r["mohs"],
                "coverage": payloads[str(r["problem_uuid"])]["concept_coverage"],
            }
