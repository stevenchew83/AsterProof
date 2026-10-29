import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_automation_migration_preserves_existing_consent_campaigns_and_attempts():
    before_target = [("website", "0002_newsletter_campaigns")]
    after_target = [("website", "0003_newsletter_automation")]
    executor = MigrationExecutor(connection)
    executor.migrate(before_target)
    old_apps = executor.loader.project_state(before_target).apps
    Subscriber = old_apps.get_model("website", "NewsletterSubscriber")  # noqa: N806
    Campaign = old_apps.get_model("website", "NewsletterCampaign")  # noqa: N806
    Delivery = old_apps.get_model("website", "NewsletterDelivery")  # noqa: N806
    now = timezone.now()
    nonce = uuid.uuid4()
    subscriber = Subscriber.objects.create(
        email="preserved@example.com",
        status="confirmed",
        requested_at=now,
        confirmed_at=now,
        confirmation_nonce=nonce,
    )
    campaign = Campaign.objects.create(
        subject="Historical campaign", body_markdown="Preserve this.", status="completed",
    )
    delivery = Delivery.objects.create(
        campaign=campaign,
        subscriber=subscriber,
        recipient_email=subscriber.email,
        subject=campaign.subject,
        consent_confirmed_at=now,
        campaign_version=1,
        status="accepted",
        attempted_at=now,
        finished_at=now,
    )
    prior = {
        model._meta.model_name: list(model.objects.order_by("pk").values())  # noqa: SLF001
        for model in (Subscriber, Campaign, Delivery)
    }
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(after_target)
        new_apps = executor.loader.project_state(after_target).apps
        for model in (Subscriber, Campaign, Delivery):
            name = model._meta.model_name  # noqa: SLF001
            fields = [field.attname for field in model._meta.fields]  # noqa: SLF001
            current = new_apps.get_model("website", name)
            assert list(current.objects.order_by("pk").values(*fields)) == prior[name]
        saved = new_apps.get_model("website", "NewsletterDelivery").objects.get(pk=delivery.pk)
        assert saved.delivery_result == "unconfirmed"
        assert not new_apps.get_model("website", "NewsletterAutomation").objects.exists()
    finally:
        MigrationExecutor(connection).migrate(after_target)
