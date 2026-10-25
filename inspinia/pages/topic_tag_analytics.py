"""Grouped archive analytics with bounded directory and chart payloads."""

from collections import Counter
from collections import defaultdict

from django.core.paginator import Paginator
from django.db.models import Avg
from django.db.models import BooleanField
from django.db.models import Case
from django.db.models import CharField
from django.db.models import Count
from django.db.models import Func
from django.db.models import Max
from django.db.models import Min
from django.db.models import Q
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Trim
from django.db.models.functions import Upper
from django.urls import reverse
from django.utils.http import urlencode

from inspinia.pages.algebra_tag_search import tag_token_query
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.topic_labels import FULL_TOPIC_LABEL_MAP

TOPIC_CHART_POINT_LIMIT = 200
TECHNIQUE_DIRECTORY_PAGE_SIZE = 25


class DomainMember(Func):
    """Exact JSON-array membership on the two supported database engines."""

    output_field = BooleanField()
    arity = 2

    def as_postgresql(self, compiler, connection, **extra_context):
        field, field_params = compiler.compile(self.source_expressions[0])
        value, value_params = compiler.compile(self.source_expressions[1])
        return f"({field} @> jsonb_build_array(CAST({value} AS text)))", [*field_params, *value_params]

    def as_sqlite(self, compiler, connection, **extra_context):
        field, field_params = compiler.compile(self.source_expressions[0])
        value, value_params = compiler.compile(self.source_expressions[1])
        # Both expressions are compiler-generated SQL; user input stays in bound parameters.
        sql = f"EXISTS (SELECT 1 FROM json_each({field}) WHERE value = {value})"  # noqa: S608
        return sql, [*field_params, *value_params]


def topic_tag_analytics_data(filters, *, page_number=None, sort="problems"):
    base = ProblemTopicTechnique.objects.alias(topic_key=Upper(Trim("record__topic"))).annotate(
        topic_label=Case(
            *[When(topic_key=key, then=Value(label)) for key, label in FULL_TOPIC_LABEL_MAP.items()],
            default=Trim("record__topic"),
            output_field=CharField(),
        ),
    )
    for token in filters["q"].split():
        search = (
            tag_token_query(token, source="problem")
            | tag_token_query(token, source="problem", field="domains")
            | Q(record__contest__icontains=token)
            | Q(record__problem__icontains=token)
            | Q(record__contest_year_problem__icontains=token)
            | Q(record__topic__icontains=token)
        )
        if token.isdigit():
            search |= Q(record__year=int(token))
        base = base.filter(search)

    options = {
        "contests": list(
            base.exclude(record__contest="")
            .order_by("record__contest")
            .values_list("record__contest", flat=True)
            .distinct(),
        ),
        "topics": list(
            base.exclude(topic_label="").order_by("topic_label").values_list("topic_label", flat=True).distinct(),
        ),
        "years": [str(y) for y in base.order_by("-record__year").values_list("record__year", flat=True).distinct()],
        "domains": sorted({d for ds in base.order_by().values_list("domains", flat=True).distinct() for d in ds if d}),
    }
    scoped = base
    for param, field in (("contest", "record__contest"), ("topic", "topic_label"), ("year", "record__year")):
        if filters[param]:
            scoped = scoped.filter(**{field: filters[param]})
    if filters["domain"]:
        scoped = scoped.filter(DomainMember("domains", Value(filters["domain"])))

    ordering = {
        "problems": "-problem_count",
        "contests": "-contest_count",
        "mohs": "-avg_mohs",
        "years": "-active_years",
        "name": "technique",
    }.get(sort, "-problem_count")
    directory = list(
        scoped.order_by()
        .values("technique")
        .annotate(
            problem_count=Count("id"),
            contest_count=Count("record__contest", distinct=True, filter=~Q(record__contest="")),
            topic_count=Count("topic_label", distinct=True, filter=~Q(topic_label="")),
            active_years=Count("record__year", distinct=True),
            year_min=Min("record__year"),
            year_max=Max("record__year"),
            avg_mohs=Avg("record__mohs"),
            max_mohs=Max("record__mohs"),
        )
        .order_by(ordering, "technique"),
    )
    domains = defaultdict(set)
    for technique, labels in scoped.order_by().values_list("technique", "domains").distinct().iterator(chunk_size=500):
        domains[technique].update(d for d in labels if d)
    for row in directory:
        row["domains"] = sorted(domains[row["technique"]])
        row["domain_count"] = len(row["domains"])
        row["domains_label"] = ", ".join(row["domains"])
        row["avg_mohs"] = round(float(row["avg_mohs"]), 2)
        row["year_span_label"] = (
            str(row["year_min"]) if row["year_min"] == row["year_max"] else f"{row['year_min']}-{row['year_max']}"
        )
        row["search_href"] = (
            reverse("pages:topic_tag_dashboard")
            + "?"
            + urlencode(
                {k: v for k, v in {**filters, "q": row["technique"]}.items() if v},
            )
        )

    page = Paginator(directory, TECHNIQUE_DIRECTORY_PAGE_SIZE).get_page(page_number)
    visible = {row["technique"]: row for row in page.object_list}
    _enrich_visible_rows(scoped, visible)

    by_domain = _domain_counts(scoped)
    totals = scoped.aggregate(
        rows=Count("id"),
        problems=Count("record_id", distinct=True),
        contests=Count("record__contest", distinct=True, filter=~Q(record__contest="")),
        topics=Count("topic_label", distinct=True, filter=~Q(topic_label="")),
    )
    return {
        "directory": directory,
        "page": page,
        "options": options,
        "totals": totals,
        "domain_total": len(by_domain),
        "has_source": base.exists(),
        "year_volume": [
            {"year": x["record__year"], "c": x["c"]}
            for x in scoped.order_by("record__year").values("record__year").annotate(c=Count("id"))
        ],
        "topic_volume": [
            {"topic": x["topic_label"], "c": x["c"]}
            for x in scoped.exclude(topic_label="")
            .order_by("topic_label")
            .values("topic_label")
            .annotate(c=Count("id"))
        ],
        "domain_volume": [
            {"domain": name, "c": count}
            for name, count in sorted(by_domain.items(), key=lambda pair: (-pair[1], pair[0]))[:12]
        ],
    }


def _enrich_visible_rows(scoped, visible):
    contest_counts = defaultdict(Counter)
    topic_counts = defaultdict(Counter)
    years = defaultdict(set)
    visible_scope = scoped.filter(technique__in=visible)
    for item in (
        visible_scope.order_by()
        .values("technique", "record__contest", "topic_label", "record__year")
        .annotate(c=Count("id"))
        .iterator(chunk_size=500)
    ):
        technique = item["technique"]
        if item["record__contest"]:
            contest_counts[technique][item["record__contest"]] += item["c"]
        if item["topic_label"]:
            topic_counts[technique][item["topic_label"]] += item["c"]
        years[technique].add(item["record__year"])
    for technique, row in visible.items():
        contests, topics = contest_counts[technique], topic_counts[technique]
        row.update(
            contests=sorted(contests),
            topics=sorted(topics),
            topics_label=", ".join(sorted(topics)),
            years=[str(y) for y in sorted(years[technique])],
            sample_contests_label=", ".join(sorted(contests, key=lambda c: (-contests[c], c))[:3]),
            sample_topics_label=", ".join(sorted(topics, key=lambda t: (-topics[t], t))[:3]),
        )


def _domain_counts(scoped):
    by_domain = Counter()
    for item in scoped.order_by().values("domains").annotate(c=Count("id")).iterator(chunk_size=500):
        for domain in item["domains"]:
            if domain:
                by_domain[domain] += item["c"]
    return by_domain
