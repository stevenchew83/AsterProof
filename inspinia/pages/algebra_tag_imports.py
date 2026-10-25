"""Activate import canonicalization only with the reviewed alias metadata installed."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection
from django.db.models import F
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.db.models.functions import NullIf
from django.db.models.functions import Trim
from django.db.models.functions import Upper

from inspinia.pages.algebra_tag_aliases import ALGEBRA_TOPICS
from inspinia.pages.algebra_tag_aliases import AlgebraAliasError
from inspinia.pages.algebra_tag_aliases import load_policy
from inspinia.pages.models import TechniqueBenchmarkAlias

IMPORT_LOCK_KEY = 653175041206451
_active_session = ContextVar("algebra_alias_import_session", default=None)


def normalization_active() -> bool:
    session = _active_session.get()
    if session is not None:
        return session
    policy = load_policy()
    keys = [r["alias_key"] for r in (*policy["activation_aliases"], *policy["shadow_aliases"])]
    aliases = {
        (r.kind, r.alias_key): r
        for r in TechniqueBenchmarkAlias.objects.select_related("benchmark").filter(alias_key__in=keys)
    }
    activation = policy["activation_aliases"]
    installed = [aliases.get((r["kind"], r["alias_key"])) for r in activation]
    if not any(installed):
        return False
    valid = all(
        alias and alias.benchmark.kind == rule["target_kind"] and alias.benchmark.label_key == rule["target_label_key"]
        for alias, rule in zip(installed, activation, strict=True)
    )
    valid = valid and all(
        (alias := aliases.get((rule["kind"], rule["alias_key"])))
        and alias.benchmark.kind == rule["kind"]
        and alias.benchmark.label_key == rule["alias_key"]
        for rule in policy["shadow_aliases"]
    )
    if not valid:
        message = "Algebra alias metadata is incomplete; repair it before importing algebra tags."
        raise AlgebraAliasError(message)
    return True


def legacy_taxonomy_rows(queryset, *, source: str):
    """Keep legacy global cleanup/backfill from undoing the activated algebra policy."""
    if not normalization_active():
        return queryset
    if source == "problem":
        topic, active = F("record__topic"), "record__is_active"
    else:
        topic = Coalesce(
            NullIf(Trim("statement__topic"), Value("")),
            F("statement__linked_problem__topic"),
            Value(""),
        )
        active = "statement__is_active"
    return queryset.annotate(algebra_policy_topic=Upper(Trim(topic))).exclude(
        **{"algebra_policy_topic__in": ALGEBRA_TOPICS, active: True},
    )


@contextmanager
def algebra_import_session():
    """One readiness query per import transaction; serialize the activation handover."""
    if _active_session.get() is not None:
        yield
        return
    if not connection.in_atomic_block:
        message = "Algebra import normalization requires an atomic import transaction."
        raise AlgebraAliasError(message)
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock_shared(%s)", [IMPORT_LOCK_KEY])
    token = _active_session.set(normalization_active())
    try:
        yield
    finally:
        _active_session.reset(token)
