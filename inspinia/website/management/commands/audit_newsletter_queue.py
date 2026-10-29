"""Count-only, non-mutating readiness check for the reviewed worker installation."""

import json

from django.core.management.base import BaseCommand
from django.db import connection
from django.db import transaction

from inspinia.website.models import NewsletterAutomation
from inspinia.website.models import NewsletterCampaign
from inspinia.website.models import NewsletterDelivery


class Command(BaseCommand):
    help = "Read only aggregate newsletter activation readiness; never send or change records."
    requires_system_checks = []

    def handle(self, *args, **options):
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = '2s'")
            active = NewsletterCampaign.objects.filter(status__in=["sending", "scheduled"])
            policy_exists = NewsletterAutomation._meta.db_table in connection.introspection.table_names()  # noqa: SLF001
            result = {
                "sending_campaigns": active.filter(status="sending").count(),
                "scheduled_campaigns": active.filter(status="scheduled").count(),
                "queued_active_deliveries": NewsletterDelivery.objects.filter(
                    campaign__in=active, status__in=["queued", "sending"],
                ).count(),
                "lecture_automation_enabled": (
                    NewsletterAutomation.objects.filter(pk=1, lecture_enabled=True).exists()
                    if policy_exists else False
                ),
            }
        self.stdout.write(json.dumps(result, sort_keys=True))
