from __future__ import annotations

from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.technique_progress_catalog import queue_technique_progress_catalog_refresh


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
