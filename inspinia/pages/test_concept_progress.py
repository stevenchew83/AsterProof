# ruff: noqa: PLR2004
"""Canonical progress, completion precedence, permission boundaries, and usable drill-downs."""

import csv
from io import StringIO
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages.concept_alias_policy import ROLE_FIELDS
from inspinia.pages.concept_analytics import PAGE_SIZE
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import ProblemTopicTechnique
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import TechniqueBenchmark
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.technique_concepts import CONCEPTS
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def learner(client):
    user = UserFactory()
    client.force_login(user)
    return user, client


def statement(number=1, **values):
    return ContestProblemStatement.objects.create(
        **{
            "contest_name": "IMO",
            "contest_year": 2026,
            "topic": "ALG",
            "mohs": 20,
            "problem_number": number,
            "problem_code": f"P{number}",
            "statement_latex": "Find x.",
            **values,
        },
    )


def tag(parent, cid="am-gm"):
    definition = CONCEPTS[cid]
    subject = definition.get("subject", "Algebra")
    code = {"Algebra": "ALG", "Geometry": "GEO", "Combinatorics": "COMB", "Number Theory": "NT"}[subject]
    values = {"technique": definition["label"], "main_topic": code, "domains": [code]}
    for kind, caption in definition["aliases"]:
        if field := ROLE_FIELDS.get(kind):
            if field not in {"technique", "canonical_subtopic"}:
                values.setdefault(field, []).append(caption)
    model, key = (
        (StatementTopicTechnique, "statement")
        if isinstance(parent, ContestProblemStatement)
        else (
            ProblemTopicTechnique,
            "record",
        )
    )
    return model.objects.create(**{key: parent, **values})


def get(client, slug="", **params):
    route = (
        reverse("pages:technique_progress_topic_detail", args=[slug]) if slug else reverse("pages:technique_dashboard")
    )
    response = client.get(route, params)
    assert response.status_code == 200
    return response


def test_canonical_roles_and_areas_count_shared_problem_once(learner):
    user, client = learner
    problem = statement()
    tag(problem)
    tag(problem, "cauchy-schwarz")
    tag(problem, "vieta")
    UserProblemCompletion.objects.create(user=user, statement=problem, status="solved")
    result = get(client)
    stats = result.context["stats"]
    assert stats["total"] == stats["solved"] == 1
    assert stats["remaining"] == 0
    assert stats["practiced"] == stats["concepts"] == 3
    assert stats["areas"] == 2
    assert stats["percent"] == 100
    rows = result.context["progress_page"].object_list
    assert {r["label"] for r in rows} == {
        "Inequalities and optimization",
        "Polynomials and algebraic manipulation",
    }
    assert all(r["total"] == r["solved"] == 1 for r in rows)
    assert sum(r["solved"] for r in rows) == 2  # Areas can overlap; the overall count remains one.
    html = result.content.decode()
    assert "Area &amp; Concepts Progress" in html
    assert 'id="area-concept-progress-table"' in html
    assert "Canonical subtopic" not in html
    assert "Recognition burden" not in html
    assert "Request rebuild" not in html


@pytest.mark.parametrize(
    ("status", "solved"),
    [("unattempted", 0), ("attempted", 0), ("solved", 1), ("checked", 1), ("written", 1), ("published", 1)],
)
def test_only_solved_statuses_count_as_completed(learner, status, solved):
    user, client = learner
    problem = statement()
    tag(problem)
    UserProblemCompletion.objects.create(user=user, statement=problem, status=status)
    result = get(client)
    assert result.context["stats"]["solved"] == solved
    assert result.context["stats"]["remaining"] == 1 - solved
    assert result.context["stats"]["practiced"] == solved


def test_statement_completion_overrides_legacy_and_changes_are_immediate(learner):
    user, client = learner
    archive = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="ALG", mohs=50)
    primary = statement(linked_problem=archive, mohs=10)
    tag(primary)
    UserProblemCompletion.objects.create(user=user, problem=archive, status="solved")
    assert get(client).context["stats"]["solved"] == 1
    completion = UserProblemCompletion.objects.create(user=user, statement=primary, status="attempted")
    assert get(client).context["stats"]["solved"] == 0
    completion.status = "checked"
    completion.save()
    assert get(client).context["stats"]["solved"] == 1
    completion.status = "unattempted"
    completion.save()
    assert get(client).context["stats"]["solved"] == 0


def test_statement_tags_override_archive_and_inactive_records_stay_excluded(learner):
    _, client = learner
    archive = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P1", topic="ALG", mohs=10)
    tag(archive)
    primary = statement(linked_problem=archive)
    StatementTopicTechnique.objects.create(statement=primary, technique="BAD SOURCE", normalization_status="corrupt")
    inactive = statement(2, is_active=False)
    tag(inactive)
    orphan = ProblemSolveRecord.objects.create(year=2026, contest="IMO", problem="P3", topic="ALG", mohs=0)
    tag(orphan)
    result = get(client)
    assert result.context["stats"]["total"] == 1
    assert result.context["unmapped_total"] == 1
    assert get(client, mode="concepts").context["progress_page"][0]["median_mohs"] == 0


def test_subjects_follow_canonical_concepts_and_have_clean_labels(learner):
    _, client = learner
    mixed = statement(topic="GEO")
    # Deliberately conflicting raw topic/domain metadata must not pollute subject labels.
    source = tag(mixed)
    source.domains = ["ALG", "COMB-GEO", "INEQ", "COMPLEX", "VEC"]
    source.save()
    result = get(client)
    subjects = {r["label"]: r for r in result.context["subject_rows"]}
    assert set(subjects) == {"Algebra", "Geometry", "Number Theory", "Combinatorics"}
    assert subjects["Algebra"]["total"] == 1
    assert subjects["Geometry"]["total"] == 0
    algebra = get(client, slug="algebra")
    assert algebra.context["stats"]["total"] == 1
    assert get(client, slug="geometry").context["stats"]["total"] == 0
    assert "COMB-GEO" not in result.content.decode()


def test_non_admin_cannot_select_other_user_in_pages_or_exports(learner):
    _, client = learner
    other = UserFactory()
    problem = statement()
    tag(problem)
    UserProblemCompletion.objects.create(user=other, statement=problem, status="published")
    for slug in ("", "algebra"):
        result = get(client, slug=slug, user=other.pk, mode="concepts")
        assert result.context["selected_user"] != other
        assert result.context["stats"]["solved"] == 0
        assert result.context["can_select_user"] is False
        assert result.context["user_options"] == []
        assert "target_user_id" not in result.context["completion_url"]
        exported = get(client, slug=slug, user=other.pk, mode="concepts", export="csv")
        row = next(csv.DictReader(StringIO(exported.content.decode("utf-8-sig"))))
        assert row["Completed"] == "0"


def test_admin_selection_survives_all_navigation_and_exports(client):
    admin, selected = UserFactory(role=User.Role.ADMIN), UserFactory()
    client.force_login(admin)
    problem = statement()
    tag(problem)
    UserProblemCompletion.objects.create(user=selected, statement=problem, status="written")
    result = get(client, user=selected.pk)
    assert result.context["selected_user"] == selected
    assert result.context["stats"]["solved"] == 1
    links = [r["url"] for r in result.context["subject_rows"]]
    links += [r["url"] for r in result.context["progress_page"]]
    links += [r["url"] for r in result.context["mode_tabs"]]
    links += [result.context["export_url"], result.context["all_subjects_url"]]
    assert all(parse_qs(urlsplit(url).query)["user"] == [str(selected.pk)] for url in links)
    assert parse_qs(urlsplit(result.context["completion_url"]).query)["target_user_id"] == [str(selected.pk)]
    topic = get(client, slug="algebra", user=selected.pk)
    assert topic.context["selected_user"] == selected
    assert topic.context["stats"]["solved"] == 1


def test_admin_invalid_or_inactive_user_falls_back_to_self(client):
    admin, inactive = UserFactory(role=User.Role.ADMIN), UserFactory(is_active=False)
    client.force_login(admin)
    for value in ("invalid", "-1", str(inactive.pk), "99999999999999999999999999"):
        assert get(client, user=value).context["selected_user"] == admin


def test_area_concept_problem_drilldown_uses_exact_canonical_membership(learner):
    user, client = learner
    first, second, third = [statement(n) for n in range(1, 4)]
    tag(first)
    tag(second)
    tag(third, "vieta")
    UserProblemCompletion.objects.create(user=user, statement=first, status="solved")
    area = next(r for r in get(client).context["progress_page"] if r["label"] == "Inequalities and optimization")
    params = {k: v[0] for k, v in parse_qs(urlsplit(area["url"]).query).items()}
    area_result = get(client, **params)
    assert area_result.context["filters"]["mode"] == "concepts"
    assert area_result.context["stats"]["total"] == 2
    concepts = area_result.context["progress_page"].object_list
    assert [r["id"] for r in concepts] == ["am-gm"]
    detail_params = {k: v[0] for k, v in parse_qs(urlsplit(concepts[0]["url"]).query).items()}
    detail = get(client, **detail_params)
    assert detail.context["selected_concept"]["id"] == "am-gm"
    assert detail.context["progress_page"].paginator.count == 1
    assert detail.context["progress_page"][0]["statement_id"] == second.pk
    completed = get(client, mode="problems", concept="am-gm", state="completed")
    assert completed.context["progress_page"][0]["statement_id"] == first.pk


def test_concepts_without_problems_are_not_marked_complete(learner):
    _, client = learner
    result = get(client, slug="algebra", mode="concepts", state="empty", q="Jensen")
    assert result.context["progress_page"].paginator.count == 1
    assert result.context["stats"]["total"] == 0
    assert "No problems yet" in result.content.decode()
    complete = get(client, slug="algebra", mode="concepts", state="completed")
    assert complete.context["progress_page"].paginator.count == 0


def test_practice_priority_and_average_solved_mohs(learner):
    user, client = learner
    for n, mohs in enumerate((4, 8, 50), start=1):
        problem = statement(n, mohs=mohs)
        tag(problem)
        if n < 3:
            UserProblemCompletion.objects.create(user=user, statement=problem, status="solved")
    for n in range(4, 9):
        tag(statement(n), "vieta")
    result = get(client)
    assert result.context["practice_rows"][0]["id"] == "am-gm"
    assert result.context["practice_rows"][0]["solved_average_mohs"] == 6
    assert result.context["practice_rows"][0]["median_mohs"] == 8


def test_problem_pagination_and_export_include_all_matches(learner):
    _, client = learner
    for number in range(1, 122):
        tag(statement(number))
    result = get(client, concept="am-gm", mode="problems", state="remaining")
    assert result.context["stats"]["total"] == 121
    assert len(result.context["progress_page"].object_list) == PAGE_SIZE
    last = get(client, concept="am-gm", mode="problems", state="remaining", page=5)
    assert last.context["progress_page"].end_index() == 121
    export = get(client, concept="am-gm", mode="problems", state="remaining", export="csv")
    assert len(list(csv.DictReader(StringIO(export.content.decode("utf-8-sig"))))) == 121


def test_search_sorting_and_safe_csv(learner):
    _, client = learner
    tag(statement(1, contest_name="=FORMULA"))
    area = get(client, mode="concepts", q="AM-GM", sort="name")
    assert [r["id"] for r in area.context["progress_page"]] == ["am-gm"]
    empty = get(client, q="<script>test</script>")
    assert "&lt;script&gt;" in empty.content.decode()
    assert "<script>test</script>" not in empty.content.decode()
    export = get(client, mode="problems", concept="am-gm", export="csv")
    row = next(csv.DictReader(StringIO(export.content.decode("utf-8-sig"))))
    assert row["Problem"].startswith("'=FORMULA")


def test_study_notes_are_expandable_instead_of_table_columns(learner):
    _, client = learner
    tag(statement())
    TechniqueBenchmark.objects.create(
        pk=CONCEPTS["am-gm"]["canonical_benchmark_id"],
        kind="lemma",
        label="AM-GM",
        label_key="am-gm",
        key_insight_spoiler_free="Look for equality conditions.",
        pitfalls="Check nonnegative inputs.",
    )
    response = get(client, concept="am-gm", mode="problems")
    html = response.content.decode()
    assert "Study notes for AM-GM" in html
    assert "Look for equality conditions." in html
    assert "Check nonnegative inputs." in html
    assert "Recognition burden" not in html


def test_unknown_subject_requires_sign_in_and_returns_404(learner):
    _, client = learner
    url = reverse("pages:technique_progress_topic_detail", args=["calculus"])
    assert client.get(url).status_code == 404
    client.logout()
    assert client.get(reverse("pages:technique_dashboard")).status_code == 302
    assert client.get(reverse("pages:technique_progress_topic_detail", args=["algebra"])).status_code == 302


def test_queries_and_response_stay_bounded(learner):
    _, client = learner
    for number in range(1, 32):
        tag(statement(number, statement_latex="large body " * 500, rationale="large rationale " * 500))
    with CaptureQueriesContext(connection) as queries:
        response = get(client, mode="concepts")
    source = [
        q["sql"]
        for q in queries
        if any(
            t in q["sql"]
            for t in (
                'FROM "pages_contestproblemstatement"',
                'FROM "pages_problemsolverecord"',
                'FROM "pages_statementtopictechnique"',
                'FROM "pages_problemtopictechnique"',
                'FROM "pages_userproblemcompletion"',
            )
        )
    ]
    assert len(source) <= 12
    assert all('"statement_latex"' not in sql and '"rationale"' not in sql for sql in source)
    assert len(response.content) < 150_000


def test_rounding_does_not_mark_incomplete_progress_as_complete():
    from inspinia.pages.concept_progress import _counts

    rows = {n: {"is_solved": n < 9999, "mohs": None} for n in range(10000)}
    counts = _counts(rows)
    assert counts["remaining"] == 1
    assert counts["percent"] < 100


def test_completed_concepts_open_review_instead_of_an_empty_practice_list(learner):
    user, client = learner
    problem = statement()
    tag(problem)
    UserProblemCompletion.objects.create(user=user, statement=problem, status="published")
    response = get(client, mode="concepts", state="completed")
    row = response.context["progress_page"][0]
    query = {k: v[0] for k, v in parse_qs(urlsplit(row["url"]).query).items()}
    assert query["state"] == "completed"
    assert get(client, **query).context["progress_page"][0]["statement_id"] == problem.pk
    assert ">Review " in response.content.decode()


def test_search_accepts_canonical_aliases(learner):
    _, client = learner
    tag(statement(), "vieta")
    response = get(client, mode="concepts", q="Vieta's formulas")
    assert [r["id"] for r in response.context["progress_page"]] == ["vieta"]


def test_old_other_subject_bookmark_redirects_to_canonical_overview(learner):
    _, client = learner
    response = client.get(reverse("pages:technique_progress_topic_detail", args=["other"]), {"user": "123"})
    assert response.status_code == 302
    assert response.url == reverse("pages:technique_dashboard") + "?user=123"
