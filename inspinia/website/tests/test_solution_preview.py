"""Standalone solution conversion and PDF export keep account work untouched."""

import signal
import subprocess
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.models import UserProblemCompletion
from inspinia.solutions.examples import INEQUALITY_BLOCKS
from inspinia.solutions.examples import INEQUALITY_STATEMENT
from inspinia.solutions.forms import PREVIEW_BLOCK_LIMIT
from inspinia.solutions.models import ProblemSolution
from inspinia.solutions.models import ProblemSolutionBlock
from inspinia.solutions.models import SolutionBlockType
from inspinia.solutions.pdf_latex import SolutionPdfCompileError
from inspinia.solutions.pdf_latex import SolutionPdfToolError
from inspinia.solutions.pdf_latex import _run_restricted_latex
from inspinia.solutions.pdf_latex import compile_solution_tex_to_pdf
from inspinia.solutions.pdf_latex import latex_escape_plain_text
from inspinia.users.tests.factories import UserFactory
from inspinia.website.solution_preview_latex import PUBLIC_PDF_TIMEOUT
from inspinia.website.solution_preview_latex import public_pdf_slot
from inspinia.website.solution_preview_latex import validate_public_latex

pytestmark = pytest.mark.django_db


def preview_data():
    types = dict(SolutionBlockType.objects.values_list("slug", "pk"))
    data = {
        "title": "My inequality", "problem_statement": INEQUALITY_STATEMENT,
        "blocks-TOTAL_FORMS": str(len(INEQUALITY_BLOCKS)), "blocks-INITIAL_FORMS": "0",
        "blocks-MIN_NUM_FORMS": "0", "blocks-MAX_NUM_FORMS": str(PREVIEW_BLOCK_LIMIT),
    }
    for index, block in enumerate(INEQUALITY_BLOCKS):
        data.update({
            f"blocks-{index}-block_type": str(types[block["slug"]]),
            f"blocks-{index}-title": "", f"blocks-{index}-body_format": "latex",
            f"blocks-{index}-body_source": block["body"], f"blocks-{index}-ORDER": str(index + 1),
        })
    return data


@pytest.fixture(autouse=True)
def isolate_pdf_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tool(client):
    return client, reverse("website:solution_preview")


def test_homepage_and_tool_are_public_for_anonymous_and_pending_users(client):
    for logged_in in (False, True):
        if logged_in:
            client.force_login(UserFactory(is_approved=False))
        for url in (reverse("pages:home"), reverse("website:solution_preview")):
            response = client.get(url)
            assert response.status_code == HTTPStatus.OK
            html = response.content.decode()
            assert "Download PDF" in html
            assert "A first inequality" in html
            assert "No sign-in needed" in html
            assert "Solution Writer" in html
            if url == reverse("website:solution_preview"):
                assert "convert LaTeX to PDF" in html
            signup_button = "data-signup-handoff>create an account</button>"
            if not logged_in:
                assert signup_button in html
                assert html.index(signup_button) < html.index('<article class="public-tool-paper"')
            else:
                assert signup_button not in html
            assert "data-workspace-handoff" in html
            assert "data-draft-recovery" in html
            assert 'aria-label="Main navigation"' in html
            assert 'class="website-tools-menu"' in html
            assert reverse("website:solution_preview") in html
            assert len(response.context["formset"].forms) == len(INEQUALITY_BLOCKS)
            assert 'class="sidenav-menu"' not in html
        assert not ProblemSolution.objects.exists()
        assert not UserProblemCompletion.objects.exists()
    assert client.get(reverse("pages:latex_preview")).url == reverse("users:approval_pending")


def test_pdf_download_uses_current_unsaved_blocks_and_evan_layout(tool, monkeypatch):
    client, url = tool
    compiled = {}

    def compile_pdf(source, **kwargs):
        compiled.update(source=source, **kwargs)
        return b"%PDF-1.4\nexample"

    monkeypatch.setattr("inspinia.website.solution_preview.compile_solution_tex_to_pdf", compile_pdf)
    data = preview_data()
    data["action"] = "download_pdf"
    data["blocks-0-body_source"] = "My latest unsaved idea."
    response = client.post(url, data)

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "application/pdf"
    assert 'filename="my-inequality.pdf"' in response["Content-Disposition"]
    assert "no-store" in response["Cache-Control"]
    assert b"".join(response.streaming_content).startswith(b"%PDF")
    assert r"\documentclass[11pt]{scrartcl}" in compiled["source"]
    assert r"\usepackage[sexy,noasy]{evan}" in compiled["source"]
    assert "My latest unsaved idea." in compiled["source"]
    assert r"\begin{claim}" in compiled["source"]
    assert r"\begin{proof}" in compiled["source"]
    assert r"\author{}" in compiled["source"]
    assert compiled["timeout"] <= PUBLIC_PDF_TIMEOUT
    assert compiled["restrict_file_access"] is True
    assert not ProblemSolution.objects.exists()
    assert not ProblemSolutionBlock.objects.exists()
    assert not UserProblemCompletion.objects.exists()


def test_pdf_uses_block_order_deletion_and_literal_plain_text(tool, monkeypatch):
    client, url = tool
    sources = []
    monkeypatch.setattr(
        "inspinia.website.solution_preview.compile_solution_tex_to_pdf",
        lambda source, **kwargs: sources.append(source) or b"%PDF",
    )
    data = preview_data()
    data.update({
        "blocks-0-ORDER": "4", "blocks-0-body_source": "Last block.",
        "blocks-1-DELETE": "on", "blocks-2-ORDER": "1", "blocks-2-body_format": "plain_text",
        "blocks-2-body_source": r"Literal $x$ and \input{private} cost 5%.",
        "blocks-3-ORDER": "2",
    })

    response = client.post(url, data)

    assert response.status_code == HTTPStatus.OK
    source = sources[0]
    assert r"Literal \$x\$ and \textbackslash{}input\{private\} cost 5\%." in source
    assert source.index("Literal") < source.index("Equality holds") < source.index("Last block.")
    assert INEQUALITY_BLOCKS[1]["body"] not in source


@pytest.mark.parametrize("failure", ["empty", "too_long", "too_many", "unknown_type", "existing_id"])
def test_invalid_document_retains_input_and_does_not_compile(tool, monkeypatch, failure):
    client, url = tool
    data = preview_data()
    data["title"] = "Keep this title"
    if failure == "empty":
        for index in range(len(INEQUALITY_BLOCKS)):
            data[f"blocks-{index}-body_source"] = ""
    elif failure == "too_long":
        data["blocks-0-body_source"] = "x" * 12_001
    elif failure == "too_many":
        data["blocks-TOTAL_FORMS"] = str(PREVIEW_BLOCK_LIMIT + 1)
    elif failure == "unknown_type":
        data["blocks-0-block_type"] = "99999999"
    else:
        problem = ProblemSolveRecord.objects.create(contest="PRIVATE", year=2026, problem="P1", topic="ALG", mohs=5)
        private = ProblemSolution.objects.create(author=UserFactory(), problem=problem)
        block = ProblemSolutionBlock.objects.create(solution=private, position=1, body_source="Private argument")
        data["blocks-INITIAL_FORMS"] = "1"
        data["blocks-0-id"] = str(block.pk)

    def forbidden_compile(*args, **kwargs):
        pytest.fail("Invalid input must not invoke the PDF compiler")

    monkeypatch.setattr("inspinia.website.solution_preview.compile_solution_tex_to_pdf", forbidden_compile)
    response = client.post(url, data)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Keep this title" in response.content.decode()
    assert "Private argument" not in response.content.decode()
    assert not UserProblemCompletion.objects.exists()


@pytest.mark.parametrize(
    ("error", "expected_status", "message"),
    [
        (SolutionPdfCompileError("bad tex"), HTTPStatus.BAD_REQUEST, "Check the LaTeX"),
        (SolutionPdfToolError("missing tool"), HTTPStatus.SERVICE_UNAVAILABLE, "temporarily unavailable"),
    ],
)
def test_export_failure_keeps_the_document_editable(tool, monkeypatch, error, expected_status, message):
    client, url = tool

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("inspinia.website.solution_preview.compile_solution_tex_to_pdf", fail)
    response = client.post(url, preview_data())

    assert response.status_code == expected_status
    html = response.content.decode()
    assert message in html
    assert "My inequality" in html
    assert INEQUALITY_BLOCKS[0]["body"] in html
    assert not ProblemSolution.objects.exists()


def test_export_keeps_csrf_protection():
    client = Client(enforce_csrf_checks=True)
    assert client.post(reverse("website:solution_preview"), preview_data()).status_code == HTTPStatus.FORBIDDEN


def test_plain_text_escaping_does_not_reescape_inserted_commands():
    assert latex_escape_plain_text(r"\ {x} $5 & 10%_~^#") == (
        r"\textbackslash{} \{x\} \$5 \& 10\%\_\textasciitilde{}\textasciicircum{}\#"
    )


def test_standalone_compilation_disables_shell_and_external_file_access(monkeypatch):
    monkeypatch.setattr("inspinia.solutions.pdf_latex.shutil.which", lambda binary: "/usr/bin/latexmk")
    calls = []

    def compile_pdf(command, **kwargs):
        calls.append((command, kwargs))
        (Path(kwargs["cwd"]) / "main.pdf").write_bytes(b"%PDF-1.4\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("inspinia.solutions.pdf_latex._run_restricted_latex", compile_pdf)

    assert compile_solution_tex_to_pdf(
        "example", timeout=20, latex_binary="latexmk", restrict_file_access=True,
    ).startswith(b"%PDF")
    command, options = calls[0]
    assert "-no-shell-escape" in command
    assert options["env"]["openin_any"] == "p"
    assert options["env"]["openout_any"] == "p"
    assert options["env"]["shell_escape"] == "f"
    assert options["env"]["TEXMFOUTPUT"] == str(options["cwd"])


@pytest.mark.parametrize("fragment", [
    r"\input{/etc/passwd}", r"\include{private}", r"\openin1=private", r"\openout1=private",
    r"\write18{whoami}", r"\immediate\write18{whoami}", r"\csname input\endcsname{private}",
    r"\catcode`X=0 Xinput{private}", r"\def\x{\x}\x", r"\newcommand{\x}{1}",
    r"\begin{filecontents}{private}secret\end{filecontents}", r"\end{document}",
    r"\begin{minted}{python}print(1)\end{minted}", r"\includegraphics{/etc/passwd}",
    r"\href{https://example.com}{link}", r"\require{html}", r"\@input{private}",
    r"\in^^70ut{private}", r"\begingroup\input{private}", "{" * 33 + "x" + "}" * 33,
])
def test_public_math_validation_rejects_tex_programs(fragment):
    with pytest.raises(ValidationError):
        validate_public_latex(fragment)


@pytest.mark.parametrize("fragment", [
    r"\[\frac{a^2+b^2}{2}\geq ab\]", r"$\alpha+\beta=\pi$",
    r"\begin{aligned}x&=1\\y&=\sqrt{2}\end{aligned}",
    r"\begin{cases}x^2 & x\geq0\\ -x & x<0\end{cases}",
    r"\textbf{Idea.} Compare $\sum_{i=1}^n x_i$ and $\prod_i x_i$.",
    r"Costs 10\%. The set is $\{1,2,3\}$.",
    r"\begin{enumerate}\item First.\item Second.\end{enumerate}",
])
def test_public_math_validation_accepts_math_and_text(fragment):
    validate_public_latex(fragment)


@pytest.mark.parametrize("field", ["problem_statement", "blocks-0-body_source", "blocks-0-title"])
def test_unsafe_fragments_never_reach_the_public_compiler(tool, monkeypatch, field):
    client, url = tool
    data = preview_data()
    data[field] = r"\input{/etc/passwd}"
    def forbidden(*args, **kwargs):
        pytest.fail("Unsafe fragments must not reach TeX")
    monkeypatch.setattr("inspinia.website.solution_preview.compile_solution_tex_to_pdf", forbidden)
    response = client.post(url, data)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "does not support" in response.content.decode()
    assert r"\input{/etc/passwd}" in response.content.decode()


def test_anonymous_export_limits_and_compiler_slots_preserve_input(tool, monkeypatch):
    client, url = tool
    monkeypatch.setattr("inspinia.website.solution_preview.compile_solution_tex_to_pdf", lambda *a, **k: b"%PDF")
    for _ in range(6):
        response = client.post(url, preview_data())
        assert response.status_code == HTTPStatus.OK
        response.close()
    response = client.post(url, preview_data(), HTTP_X_FORWARDED_FOR="203.0.113.50")
    assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert response["Retry-After"] == "60"
    assert "My inequality" in response.content.decode()
    assert not ProblemSolution.objects.exists()
    cache.clear()
    cache.set("public-solution-pdf:slot:0", "busy", 60)
    cache.set("public-solution-pdf:slot:1", "busy", 60)
    assert client.post(url, preview_data()).status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert cache.get("public-solution-pdf:slot:0") == "busy"


def test_pdf_slot_is_released_after_a_compilation_error(tool, monkeypatch):
    client, url = tool
    def fail(*args, **kwargs):
        message = "bad math"
        raise SolutionPdfCompileError(message)
    monkeypatch.setattr("inspinia.website.solution_preview.compile_solution_tex_to_pdf", fail)
    assert client.post(url, preview_data()).status_code == HTTPStatus.BAD_REQUEST
    assert cache.get("public-solution-pdf:slot:0") is None


def test_pdf_rate_limit_fails_closed_on_cache_failure(rf, monkeypatch):
    def fail(*args, **kwargs):
        message = "offline"
        raise OSError(message)
    monkeypatch.setattr("inspinia.website.solution_preview_latex.cache.add", fail)
    with public_pdf_slot(rf.post("/")) as available:
        assert available is False


def test_public_pdf_cache_suppressed_errors_do_not_bypass_limits(rf, monkeypatch):
    monkeypatch.setattr("inspinia.website.solution_preview_latex.cache.add", lambda *a, **k: None)
    monkeypatch.setattr("inspinia.website.solution_preview_latex.cache.incr", lambda *a, **k: None)
    with public_pdf_slot(rf.post("/")) as available:
        assert available is False


def test_public_tex_timeout_stops_the_whole_compiler_group(monkeypatch, tmp_path):
    calls = []
    options = {}
    command = ["latexmk", "main.tex"]
    class Compiler:
        pid = 23456
        returncode = 0
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def communicate(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(command, 20)
            return "", "stopped"
    def launch(*args, **kwargs):
        options.update(kwargs)
        return Compiler()
    killed = []
    monkeypatch.setattr("inspinia.solutions.pdf_latex.subprocess.Popen", launch)
    monkeypatch.setattr("inspinia.solutions.pdf_latex.os.killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        _run_restricted_latex(command, cwd=tmp_path, env={}, timeout=20)
    assert options["start_new_session"] is True
    assert killed == [(Compiler.pid, signal.SIGKILL)]
    assert calls == [{"timeout": 20}, {}]
