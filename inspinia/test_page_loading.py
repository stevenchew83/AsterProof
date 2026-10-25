"""Repeatable navigation audit using synthetic data and the isolated pytest database.

Set PAGE_LOAD_AUDIT_OUTPUT to save measurements; timings are observations, not CI gates.
"""

import json
import os
import re
from datetime import date
from http import HTTPStatus
from pathlib import Path
from statistics import median
from time import perf_counter

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import StatementTopicTechnique
from inspinia.pages.models import UserProblemCompletion
from inspinia.pages.technique_progress_catalog import rebuild_technique_progress_catalog
from inspinia.problemsets.models import ProblemList
from inspinia.problemsets.models import ProblemListItem
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.training.models import Material
from inspinia.training.models import MaterialCompletion
from inspinia.training.models import Problem
from inspinia.training.models import Submission
from inspinia.training.models import Subtopic
from inspinia.users.models import User
from inspinia.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
COMPLETED_SUBTOPICS = 36


def _seed_audit_data(user):
    problems = ProblemSolveRecord.objects.bulk_create(
        [
            ProblemSolveRecord(
                year=2000 + index // 12,
                contest=f"Audit Contest {index % 12}",
                problem=f"P{index + 1}",
                topic=["A", "C", "G", "N"][index % 4],
                mohs=index % 61,
                core_ideas_value="Synthetic audit metadata. " * 30,
            )
            for index in range(240)
        ],
    )
    statements = ContestProblemStatement.objects.bulk_create(
        [
            ContestProblemStatement(
                linked_problem=problem,
                problem_uuid=problem.problem_uuid,
                contest_year=problem.year,
                contest_name=problem.contest,
                contest_year_problem=f"{problem.contest} {problem.year} {problem.problem}",
                problem_code=problem.problem,
                problem_number=index + 1,
                statement_latex="Prove that $a^2+b^2\\geq 2ab$.",
                topic=problem.topic,
                mohs=problem.mohs,
            )
            for index, problem in enumerate(problems)
        ],
    )
    StatementTopicTechnique.objects.bulk_create(
        [
            StatementTopicTechnique(statement=statement, technique="INEQUALITIES", domains=["ALGEBRA"])
            for statement in statements
        ],
    )
    UserProblemCompletion.objects.bulk_create(
        [
            UserProblemCompletion(
                user=user, statement=statement, problem=statement.linked_problem, completion_date=date(2026, 10, 1),
            )
            for statement in statements[:80]
        ],
    )
    for index in range(12):
        problem_list = ProblemList.objects.create(
            author=user,
            title=f"Audit list {index}",
            visibility=ProblemList.Visibility.PUBLIC,
        )
        ProblemListItem.objects.bulk_create(
            [
                ProblemListItem(problem_list=problem_list, problem=problem, position=position)
                for position, problem in enumerate(problems[:20])
            ],
        )
    for problem in problems[:20]:
        solution = ProblemSolution.objects.create(author=user, problem=problem, title="Audit solution")
        ProblemSolutionBlock.objects.bulk_create(
            [
                ProblemSolutionBlock(solution=solution, position=position, body_source="Proof. " * 200)
                for position in range(3)
            ],
        )
    subtopics = list(Subtopic.objects.select_related("topic").order_by("topic__order", "order", "title", "id"))
    for index, subtopic in enumerate(subtopics):
        material = Material.objects.create(
            subtopic=subtopic,
            title=f"Audit material {index}",
            slug=f"audit-material-{index}",
            content_markdown="Synthetic study notes.",
        )
        problem = Problem.objects.create(
            subtopic=subtopic,
            title=f"Audit problem {index}",
            slug=f"audit-problem-{index}",
            statement_markdown="Synthetic training problem.",
        )
        if index < COMPLETED_SUBTOPICS:
            MaterialCompletion.objects.create(user=user, material=material, points_awarded=10)
            Submission.objects.create(
                user=user,
                problem=problem,
                solution_markdown="Proof.",
                status=Submission.Status.ACCEPTED,
                awarded_points=40,
            )
    rebuild_technique_progress_catalog()
    return {
        "archive_problems": len(problems),
        "statements": len(statements),
        "subtopics": len(subtopics),
        "lists": 12,
        "solutions": 20,
    }


def test_navigation_page_loading(client, settings):
    settings.SHARED_PROGRESS_LEARNERS = {}
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "page-loading-audit",
        },
    }
    user = UserFactory(role=User.Role.ADMIN)
    dataset = _seed_audit_data(user)
    client.force_login(user)
    sidebar = (Path(settings.BASE_DIR) / "inspinia/templates/partials/sidenav.html").read_text()
    links = re.findall(r"route_name='([^']+)' label='([^']+)'", sidebar)
    routes = {}
    for route, label in links:
        routes.setdefault(route, label)
    results = []
    for route, label in routes.items():
        url = reverse(route)
        cache.clear()
        samples = []
        for _ in range(3):
            with CaptureQueriesContext(connection) as queries:
                started = perf_counter()
                response = client.get(url)
                elapsed = (perf_counter() - started) * 1000
            assert response.status_code == HTTPStatus.OK, (route, response.status_code)
            samples.append({"ms": round(elapsed, 2), "queries": len(queries)})
        results.append(
            {
                "route": route,
                "label": label,
                "url": url,
                "cold": samples[0],
                "warm_ms": round(median(sample["ms"] for sample in samples[1:]), 2),
                "warm_queries": samples[-1]["queries"],
                "html_bytes": len(response.content),
            },
        )
    output = os.environ.get("PAGE_LOAD_AUDIT_OUTPUT")
    if output:
        Path(output).write_text(json.dumps({"dataset": dataset, "pages": results}, indent=2) + "\n")
