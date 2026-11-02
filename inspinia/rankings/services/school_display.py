"""Read-only school labels shared by the original ranking pages.

Results retain their source-school fallback; only reviewed attributions override
it. Alias resolution is one hop and never changes the underlying school links.
"""

from django.db.models import Case
from django.db.models import CharField
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Subquery
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django.db.models.functions import Lower
from django.db.models.functions import Substr
from django.db.models.functions import Trim

from inspinia.rankings.analysis_models import SchoolAlias

SOURCE_SCHOOL_PREFIX = "School in source result: "


def with_school_display(queryset, *, results=False):
    """Annotate a queryset before ordering, filtering and pagination."""
    if results:
        source_name = Substr("remarks", len(SOURCE_SCHOOL_PREFIX) + 1)
        queryset = queryset.annotate(
            recorded_school=Case(
                When(school_attribution__verified=True, then=F("school_attribution__school__name")),
                When(remarks__startswith=SOURCE_SCHOOL_PREFIX, then=source_name),
                default=Coalesce("student__school__name", Value("")),
                output_field=CharField(),
            ),
            school_alias_key=Case(
                When(school_attribution__verified=True, then=F("school_attribution__school__normalized_name")),
                When(remarks__startswith=SOURCE_SCHOOL_PREFIX, then=Lower(Trim(source_name))),
                default=Coalesce("student__school__normalized_name", Value("")),
                output_field=CharField(),
            ),
        )
    else:
        queryset = queryset.annotate(
            recorded_school=Coalesce("school__name", Value("")),
            school_alias_key=Coalesce("school__normalized_name", Value("")),
        )
    canonical = SchoolAlias.objects.filter(
        active=True,
        normalized_name=OuterRef("school_alias_key"),
    ).values("school__name")[:1]
    return queryset.annotate(
        school_display=Coalesce(Subquery(canonical), F("recorded_school"), output_field=CharField()),
    )
