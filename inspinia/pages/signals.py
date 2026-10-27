from __future__ import annotations

from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.db.models.signals import pre_save
from django.dispatch import receiver

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.technique_progress import mark_technique_progress_user_options_stale
from inspinia.pages.technique_progress_catalog import queue_technique_progress_catalog_refresh
from inspinia.users.models import User


@receiver(post_save, sender=ContestProblemStatement)
@receiver(post_delete, sender=ContestProblemStatement)
def queue_statement_catalog_refresh(sender, instance: ContestProblemStatement, **kwargs) -> None:
    queue_technique_progress_catalog_refresh(statement_ids=[instance.id])


@receiver(post_save, sender=StatementTopicTechnique)
@receiver(post_delete, sender=StatementTopicTechnique)
def queue_statement_tag_catalog_refresh(sender, instance: StatementTopicTechnique, **kwargs) -> None:
    queue_technique_progress_catalog_refresh(statement_ids=[instance.statement_id])


@receiver(post_save, sender=ProblemTopicTechnique)
@receiver(post_delete, sender=ProblemTopicTechnique)
def queue_problem_tag_catalog_refresh(sender, instance: ProblemTopicTechnique, **kwargs) -> None:
    queue_technique_progress_catalog_refresh(problem_ids=[instance.record_id])


@receiver(post_save, sender=User)
@receiver(post_delete, sender=User)
def expire_technique_progress_user_options(sender, instance: User, **kwargs) -> None:
    mark_technique_progress_user_options_stale()


# Disabled by default until the separate schema prerequisite and reviewed seed.
@receiver(post_save, sender=ContestProblemStatement)
@receiver(post_delete, sender=ContestProblemStatement)
@receiver(post_save, sender=ProblemSolveRecord)
@receiver(post_delete, sender=ProblemSolveRecord)
@receiver(post_save, sender=StatementTopicTechnique)
@receiver(post_delete, sender=StatementTopicTechnique)
@receiver(post_save, sender=ProblemTopicTechnique)
@receiver(post_delete, sender=ProblemTopicTechnique)
def invalidate_concept_assignments(sender, instance, **kwargs):
    from django.conf import settings

    if not getattr(settings, "CONCEPT_ASSIGNMENTS_ENABLED", False):
        return
    from inspinia.pages.concept_assignment_service import invalidate_assignments

    if isinstance(instance, (ContestProblemStatement, ProblemSolveRecord)):
        values = [instance.problem_uuid]
    elif isinstance(instance, StatementTopicTechnique):
        values = ContestProblemStatement.objects.filter(pk=instance.statement_id).values_list(
            "problem_uuid", flat=True,
        )
    else:
        values = ProblemSolveRecord.objects.filter(pk=instance.record_id).values_list("problem_uuid", flat=True)
    invalidate_assignments(values)


from inspinia.solutions.models import ProblemSolution  # noqa: E402
from inspinia.solutions.models import ProblemSolutionBlock  # noqa: E402


@receiver(pre_save, sender=ProblemSolution)
def remember_published_concept_evidence(sender, instance, **kwargs):
    from django.conf import settings

    if getattr(settings, "CONCEPT_ASSIGNMENTS_ENABLED", False) and instance.pk:
        instance.concept_was_published = ProblemSolution.objects.filter(
            pk=instance.pk, status=ProblemSolution.Status.PUBLISHED,
        ).exists()


@receiver(post_save, sender=ProblemSolution)
@receiver(post_delete, sender=ProblemSolution)
@receiver(post_save, sender=ProblemSolutionBlock)
@receiver(post_delete, sender=ProblemSolutionBlock)
def invalidate_solution_concept_evidence(sender, instance, **kwargs):
    from django.conf import settings

    if not getattr(settings, "CONCEPT_ASSIGNMENTS_ENABLED", False):
        return
    from inspinia.pages.concept_assignment_service import invalidate_assignments

    solution = instance if isinstance(instance, ProblemSolution) else instance.solution
    if solution.status != ProblemSolution.Status.PUBLISHED and not getattr(solution, "concept_was_published", False):
        return
    values = ProblemSolveRecord.objects.filter(pk=solution.problem_id).values_list("problem_uuid", flat=True)
    invalidate_assignments(values)
