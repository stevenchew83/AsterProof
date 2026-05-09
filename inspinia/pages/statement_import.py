from __future__ import annotations

import contextlib
import html
import ipaddress
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from dataclasses import field
from html.parser import HTMLParser
from http import HTTPStatus
from io import BytesIO
from typing import TypedDict

from django.db import transaction

from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.statement_analytics_sync import sync_statement_analytics_from_linked_problem

PdfReader = None

IGNORED_STATEMENT_LINES = {
    "Stuttgarden",
    "Click to reveal hidden text",
    "view topic",
}
URL_FETCH_TIMEOUT_SECONDS = 20
URL_FETCH_MAX_BYTES = 15 * 1024 * 1024
URL_FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; AsterProofLatexPreview/1.0; +https://asterproof.local/tools/latex-preview)"
)
AOPS_HOSTS = {"artofproblemsolving.com", "www.artofproblemsolving.com"}
AOPS_COMMUNITY_COLLECTION_RE = re.compile(
    r"^/community/c(?P<collection_id>\d+)(?:_(?P<slug>[^/]+))?/?$",
    flags=re.IGNORECASE,
)
AOPS_PRINTABLE_COLLECTION_RE = re.compile(
    r"^/downloads/printable_post_collections/(?P<collection_id>\d+)(?:\.pdf)?/?$",
    flags=re.IGNORECASE,
)
AOPS_READER_URL_PREFIX = "https://r.jina.ai/http://"
AOPS_LATEX_IMAGE_HOST = "latex.artofproblemsolving.com"
MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>(?:\\.|[^\]\\])*)\]\((?P<url>[^)\s]+)\)", flags=re.DOTALL)
AOPS_READER_VIEW_TOPIC_LINK_RE = re.compile(r"^(?:\[)?view topic(?:\]\([^)]+\))?$", flags=re.IGNORECASE)
LATEX_SOURCE_TOKEN_RE = re.compile(r"\\[A-Za-z]+|_[A-Za-z0-9{]|\\\(|\\\[|\^\{")
PDF_LINE_GROUP_Y_TOLERANCE = 9
PDF_SMALL_MATH_FONT_SIZE = 9
PDF_SCRIPT_Y_DELTA = 2
PDF_MATH_FONT_MARKERS = ("CMMI", "CMSY", "MSBM", "CMEX")
PDF_TEXT_NUMBER_FONT_MARKERS = ("CMR",)
PDF_MATH_SYMBOL_RE = re.compile(r"[+\-=<>≤≥×∥±∠◦Γℓ→∞∈⊥|]")
PDF_AOPS_COPYRIGHT_RE = re.compile(r"^©\s+\d{4}\s+AoPS Incorporated\s+\d+\s*$")
PDF_LATEX_REPLACEMENTS = {
    "−": "-",
    "±": r"\pm",
    "∥": r"\parallel",
    "×": r"\times",
    "≥": r"\ge",
    "≤": r"\le",
    "∠": r"\angle",
    "◦": r"^\circ",
    "→": r"\to",
    "∞": r"\infty",
    "∈": r"\in",
    "⊥": r"\perp",
    "Γ": r"\Gamma",
    "ℓ": r"\ell",
}
AOPS_SLUG_WORD_REPLACEMENTS = {
    "allrussian": "All-Russian",
    "imo": "IMO",
    "jmo": "JMO",
    "mo": "MO",
    "nmo": "NMO",
    "tst": "TST",
    "usa": "USA",
    "usamo": "USAMO",
    "usaamo": "USAAMO",
    "usajmo": "USAJMO",
}
HEADER_LINE_RE = re.compile(
    r"^\s*(?P<year_start>\d{4})(?:\s*(?:/|-)\s*(?P<year_end>\d{4}))?\s+(?P<contest>.+?)\s*$",
)
HEADER_YEAR_SUFFIX_RE = re.compile(
    r"^\s*(?P<contest>.+?)\s+(?P<year>\d{4})(?:\d)?\s*$",
)
HEADER_YEAR_MIDDLE_RE = re.compile(
    r"^\s*(?P<prefix>.+?)\s+(?P<year>\d{4})(?:\d)?\s+(?P<suffix>.+?)\s*$",
)
YEAR_PREFIXED_SECTION_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s+(?P<label>[A-Za-z].+?)\s*$",
)
YEAR_SUFFIXED_SECTION_RE = re.compile(
    r"^\s*(?P<label>[A-Za-z].+?)\s+(?P<year>\d{4})(?:\d)?\s*$",
)
DAY_LABEL_RE = re.compile(
    r"^Day\s*(?P<token>\d+|[IVXLCDM]+)(?:(?:\s*[,:-]\s*|\s+)(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
TST_DAY_LABEL_RE = re.compile(
    r"^TST\s*#?\s*(?P<number>\d+)(?:\s+(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
ROUND_LABEL_RE = re.compile(r"^(?:\d+\s+)?(?P<label>Round\s+[A-Za-z0-9].*)$", flags=re.IGNORECASE)
SOLUTION_LINE_RE = re.compile(r"^Solution$", flags=re.IGNORECASE)
TEST_LABEL_RE = re.compile(
    r"^Test\s+(?P<number>\d+|[IVXLCDM]+)(?:\s+(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
PART_LABEL_RE = re.compile(
    r"^Part\s+(?P<number>\d+|[IVXLCDM]+)(?:\s+(?P<detail>.+))?$",
    flags=re.IGNORECASE,
)
SEASON_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s+(?P<year>\d{4})$",
    flags=re.IGNORECASE,
)
YEAR_FIRST_SEASON_SECTION_RE = re.compile(
    r"^(?P<year>\d{4})\s+(?P<season>Fall|Autumn|Spring)$",
    flags=re.IGNORECASE,
)
LEVEL_SECTION_RE = re.compile(
    r"^(?P<division>Junior|Senior)\s+(?P<track>[AO])-Level$",
    flags=re.IGNORECASE,
)
DIVISION_SECTION_RE = re.compile(r"^(?P<division>Junior|Juniors|Senior|Seniors)$", flags=re.IGNORECASE)
TRACK_SECTION_RE = re.compile(r"^(?P<track>[AO])(?:\s*-\s*|\s+)Level$", flags=re.IGNORECASE)
GRADE_SECTION_RE = re.compile(r"^Grade\s+(?P<number>\d{1,2})$", flags=re.IGNORECASE)
GRADE_LEVEL_SECTION_RE = re.compile(r"^Grade\s+level\s+(?P<number>\d{1,2})$", flags=re.IGNORECASE)
INLINE_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s+(?P<year>\d{4})\s+(?P<track>[AO])-level\s+(?P<division>Junior|Senior)$",
    flags=re.IGNORECASE,
)
HYPHENATED_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s+(?P<year>\d{4})\s*-\s*(?P<division>Junior|Senior)\s+(?P<track>[AO])-level$",
    flags=re.IGNORECASE,
)
YEARLESS_HYPHENATED_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s*-\s*(?P<division>Junior|Senior)\s+(?P<track>[AO])-level$",
    flags=re.IGNORECASE,
)
YEARLESS_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<season>Fall|Autumn|Spring)\s+(?P<division>Junior|Senior)\s+(?P<track>[AO])-level(?:\s+Paper)?$",
    flags=re.IGNORECASE,
)
ROUND_PREFIXED_YEARLESS_SEASON_LEVEL_SECTION_RE = re.compile(
    r"^(?P<round>[IVXLCDM]+)\.\s*(?P<season>Fall|Autumn|Spring)\s*-\s*(?P<division>Junior|Senior)(?:\s*-\s*|\s+)(?P<track>[AO])-level(?:\s+Paper)?$",
    flags=re.IGNORECASE,
)
ROUND_AND_SECTION_RE = re.compile(
    r"^(?P<round>First|Second|Third|Final)\s+Round\s+(?P<label>.+)$",
    flags=re.IGNORECASE,
)
NAMED_DAY_SECTION_RE = re.compile(r"^.+,\s*Day\s+(?:\d+|[IVXLCDM]+)(?:\b.*)?$", flags=re.IGNORECASE)
NUMBERED_SIBLING_SECTION_RE = re.compile(r"^(?P<family>[A-Za-z][A-Za-z ]*?)\s+\d+$")
EXAM_AND_DAY_LABEL_RE = re.compile(
    r"^(?P<exam>First|Second|Third|Final)\s+exam\s*,\s*(?P<day>Day\s*(?:\d+|[IVXLCDM]+)(?:(?:\s*[,:-]\s*|\s+).+)?)$",
    flags=re.IGNORECASE,
)
PROBLEM_START_RE = re.compile(
    r"^(?:\((?P<catalog_number>\d{1,4})\)\s*)?(?:#\s*)?(?:(?P<prefix>[A-Za-z]{1,4})\s*)?(?P<number>\d{1,3})[.)#]?(?:\s+(?P<statement>.+))?$",
    flags=re.IGNORECASE,
)
GRADE_PREFIXED_PROBLEM_START_RE = re.compile(
    r"^(?P<grade>\d{1,2})\.(?P<number>\d{1,3})[.)#]?(?:\s+(?P<statement>.+))?$",
)
PROBLEM_KEYWORD_START_RE = re.compile(
    r"^(?:Problem|Question)\s+(?P<number>\d{1,3})[.):]?(?:\s+(?P<statement>.+))?$",
    flags=re.IGNORECASE,
)
ALPHA_PROBLEM_CODE_RE = re.compile(r"^(?P<code>[A-Z])(?:[.)])?\s+(?P<statement>.+)$")
TEXT_ONLY_EMPH_INLINE_RE = re.compile(r"\$(?P<content>\\emph\{[^$]+?\})\$")
TEXT_ONLY_EMPH_PAREN_RE = re.compile(r"\\\((?P<content>\\emph\{.*?\})\\\)", flags=re.DOTALL)
TEXT_ONLY_EMPH_DISPLAY_RE = re.compile(r"\$\$(?P<content>\\emph\{.*?\})\$\$", flags=re.DOTALL)
TEXT_ONLY_EMPH_BRACKET_RE = re.compile(r"\\\[(?P<content>\\emph\{.*?\})\\\]", flags=re.DOTALL)
SHORT_SECTION_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9][A-Za-z0-9]*){0,3}$")
PAPER_SECTION_RE = re.compile(
    r"^(?:Junior|Senior)\s+[AO]-Level\s+Paper,\s+(?:Fall|Autumn|Spring)\s+\d{4}$",
    flags=re.IGNORECASE,
)
SEASON_FIRST_PAPER_SECTION_RE = re.compile(
    r"^(?:Fall|Autumn|Spring)\s+\d{4},\s+(?:Junior|Senior)\s+[AO]-level$",
    flags=re.IGNORECASE,
)
SPECIAL_PROBLEM_CODE_RE = re.compile(r"^(?P<code>Bonus)[.)]?\s+(?P<statement>.+)$", flags=re.IGNORECASE)
INNER_NUMBERED_STATEMENT_RE = re.compile(r"^(?P<number>\d{1,3})[.)]\s+(?P<statement>.+)$")
TRAILING_AUTHOR_LINE_RE = re.compile(
    r"^[A-Z][A-Za-z'.-]*(?: [A-Z][A-Za-z'.-]*)*(?: and [A-Z][A-Za-z'.-]*(?: [A-Z][A-Za-z'.-]*)*)?$",
)
TRAILING_PROPOSED_BY_LINE_RE = re.compile(
    r"^(?:\(?\s*)(?:proposed|created)(?: by)?\b.+$",
    flags=re.IGNORECASE,
)
USERNAME_LINE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
NOTE_METADATA_LINE_RE = re.compile(
    r"^(?:"
    r"note|remark on \d{1,2}\.\d{1,3}|junior version (?:posted )?here|"
    r"senior version (?:posted )?here|\(translated from here\.\)"
    r")$",
    flags=re.IGNORECASE,
)
DOTTED_PROBLEM_CODE_RE = re.compile(r"^(?P<group>\d{1,2})\.(?P<number>\d{1,3})$")
SECTION_DATE_LINE_RE = re.compile(
    r"^(?:"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r"|[A-Za-z]+\s+\d{1,2},\s+\d{4}"
    r")$",
    flags=re.IGNORECASE,
)
SECTION_TIME_LINE_RE = re.compile(r"^Time:\s+.+$", flags=re.IGNORECASE)
SECTION_HEADER_LABELS = frozenset(
    {
        "Algebra",
        "Combinatorics",
        "Geometry",
        "Number Theory",
    },
)
LATEX_STATEMENT_SAMPLE = (
    "2026 Spain Mathematical Olympiad3\n"
    "Day 1\n"
    "1\tFind the value of a positive integer $N$ such that"
    "\\[2026<\\frac{1}{\\sqrt{1}}+\\frac{1}{\\sqrt{2}}+\\frac{1}{\\sqrt{3}}"
    "+\\dots+\\frac{1}{\\sqrt{N}}<2027.\\]\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "2\tLet $ABC$ be a triangle with $AB<BC$. The perpendicular bisector of $AC$ intersects $BC$ "
    "in $D$. The circle passing through $A,C,D$ contains a point $E\\neq D$ such that $DE$ is "
    "parallel to $AB$. Prove that $AE^2+BC^2=BE^2$.\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "3\tWe say that a sequence $a_1, a_2, \\dots$ of positive integers is roceña if, for all "
    "$n\\geq 4$,\\[a_n=a_{n-1}+\\gcd(a_{n-2},a_{n-3})-1.\\]Does there exist any roceña sequence "
    "such that $2\\leq a_n\\leq 100\\cdot n^{100}$ for all $n\\geq 1$?\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "Day 2\n"
    "4\tFor each positive integer $n$, let $a(n)$ be the largest value of $k$ such that $n$ is "
    "a multiple of all of $1, 2, \\dots, k$. Prove that if $\\sqrt[3]{a(n)}$ is an integer, "
    "then $\\sqrt[3]{a(n+2520)}$ is an integer.\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "5\tThe restaurant of the Hotel Las Rozas has three signature dishes: artichokes, beef and "
    "cod. Every evening the restaurant cooks one instance of each dish, so two guests cannot eat "
    "the same dish on the same evening. Let $n\\geq 3$. $n$ guests $H_1, H_2, \\dots, H_n$ will "
    "stay at the hotel, where for each $1\\leq k\\leq n$ the guest $H_k$ stays from the day $k$ "
    "at noon until the day $k+3$ at noon. Every guest wishes to try all three dishes, one on "
    "each evening of their stay.\n"
    "\n"
    "Determine, as a function of $n$, the number of ways to arrange the dish that each guest will "
    "eat on each dinner, from the evening of the first day until the evening of the $(n+2)$-th "
    "day, fulfilling the wishes of every guest.\n"
    "\n"
    "Stuttgarden\n"
    "\n"
    "6\tIn the scalene triangle $ABC$, the incircle $\\omega$ touches $BC, CA, AB$ at $D, E, F$ "
    "respectively. Let $G$ be the point on the line $EF$ such that $AG$ is parallel to $BC$. "
    "Prove that $\\omega$ contains the orthocenter of the triangle $ADG$."
)


class PreviewDayRow(TypedDict):
    label: str
    problem_count: int


class PreviewProblemRow(TypedDict):
    contest_year_problem: str
    day_label: str
    problem_code: str
    problem_number: int
    statement_latex: str
    linked_problem_label: str


class ProblemStatementPreviewPayload(TypedDict):
    contest_name: str
    contest_year: int
    day_rows: list[PreviewDayRow]
    problem_count: int
    problems: list[PreviewProblemRow]


class ProblemStatementSavePreviewPayload(TypedDict):
    create_count: int
    update_count: int
    unchanged_count: int
    existing_count: int
    existing_problem_codes: list[str]
    update_problem_codes: list[str]
    unchanged_problem_codes: list[str]


class ProblemStatementImportValidationError(ValueError):
    """Raised when pasted contest statement text cannot be parsed reliably."""


@dataclass(frozen=True)
class FetchedStatementText:
    text: str
    source_label: str


@dataclass(frozen=True)
class _PdfTextChunk:
    text: str
    x: float
    y: float
    font_size: float
    font_name: str
    order: int


@dataclass
class _PdfLineGroup:
    y: float
    y_values: list[float] = field(default_factory=list)
    chunks: list[_PdfTextChunk] = field(default_factory=list)


class _VisibleTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
    _SKIPPED_TAGS = {"head", "script", "style", "svg", "title", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in self._SKIPPED_TAGS:
            self._skip_depth += 1
            return
        if normalized_tag in self._BLOCK_TAGS:
            self._append_newline()

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in self._SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if normalized_tag in self._BLOCK_TAGS:
            self._append_newline(count=2)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._parts and not self._parts[-1].endswith(("\n", " ")):
            self._parts.append(" ")
        self._parts.append(text)

    def _append_newline(self, *, count: int = 1) -> None:
        if not self._parts:
            return
        trailing_newlines = len("".join(self._parts)[-count:]) - len("".join(self._parts)[-count:].rstrip("\n"))
        if trailing_newlines < count:
            self._parts.append("\n" * (count - trailing_newlines))

    def text(self) -> str:
        return _normalize_extracted_text("".join(self._parts))


def _normalize_extracted_text(raw_text: str) -> str:
    normalized = raw_text.replace("\x00", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.splitlines()]

    collapsed_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if collapsed_lines and not previous_blank:
                collapsed_lines.append("")
                previous_blank = True
            continue
        collapsed_lines.append(line)
        previous_blank = False

    while collapsed_lines and not collapsed_lines[-1]:
        collapsed_lines.pop()

    return "\n".join(collapsed_lines).strip()


def _content_type_charset(content_type: str) -> str:
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    if match is None:
        return "utf-8"
    return match.group(1).strip("\"'")


def _decode_fetched_text(payload: bytes, content_type: str) -> str:
    charset = _content_type_charset(content_type)
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _extract_visible_text_from_html(html_text: str) -> str:
    extractor = _VisibleTextExtractor()
    extractor.feed(html.unescape(html_text))
    extractor.close()
    extracted_text = extractor.text()
    if not extracted_text:
        msg = "No readable text was found at the fetched URL."
        raise ProblemStatementImportValidationError(msg)
    return extracted_text


def _is_aops_printable_latex_error_page(html_text: str, *, source_url: str) -> bool:
    normalized = " ".join(html_text.split()).casefold()
    return "there is a latex error in one of the posts" in normalized and "artofproblemsolving.com" in source_url


def _reject_known_remote_error_page(html_text: str, *, source_url: str) -> None:
    normalized = " ".join(html_text.split()).casefold()
    if "attention required! | cloudflare" in normalized or "you are unable to access" in normalized:
        msg = "The remote site blocked the URL fetch. Try a printable PDF URL, or paste the contest text."
        raise ProblemStatementImportValidationError(msg)
    if _is_aops_printable_latex_error_page(html_text, source_url=source_url):
        msg = (
            "AoPS could not build the printable collection because one included post has a LaTeX error. "
            "Fix the collection or paste the contest text."
        )
        raise ProblemStatementImportValidationError(msg)
    if "this collection is not printable" in normalized and "artofproblemsolving.com" in source_url:
        msg = "This AoPS collection is not printable. Paste the contest text instead."
        raise ProblemStatementImportValidationError(msg)


def _is_blocked_url_host(hostname: str) -> bool:
    normalized_hostname = hostname.strip("[]").casefold()
    if normalized_hostname == "localhost" or normalized_hostname.endswith(".local"):
        return True

    with contextlib.suppress(ValueError):
        address = ipaddress.ip_address(normalized_hostname)
        return (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    return False


def _validated_source_url(source_url: str) -> str:
    candidate = source_url.strip()
    if not candidate:
        msg = "Enter a URL before fetching."
        raise ProblemStatementImportValidationError(msg)

    parsed_url = urllib.parse.urlparse(candidate)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        msg = "Enter a full HTTP or HTTPS URL."
        raise ProblemStatementImportValidationError(msg)

    hostname = parsed_url.hostname or ""
    if _is_blocked_url_host(hostname):
        msg = "URLs pointing to local or private network hosts are not allowed."
        raise ProblemStatementImportValidationError(msg)

    return urllib.parse.urlunparse(parsed_url)


def _aops_printable_url(source_url: str) -> str | None:
    parsed_url = urllib.parse.urlparse(source_url)
    hostname = (parsed_url.hostname or "").casefold()
    if hostname not in AOPS_HOSTS:
        return None

    match = AOPS_COMMUNITY_COLLECTION_RE.match(parsed_url.path)
    if match is None:
        match = AOPS_PRINTABLE_COLLECTION_RE.match(parsed_url.path)
    if match is None:
        return None

    collection_id = match.group("collection_id")
    return f"https://artofproblemsolving.com/downloads/printable_post_collections/{collection_id}.pdf"


def _aops_reader_url(source_url: str) -> str | None:
    parsed_url = urllib.parse.urlparse(source_url)
    hostname = (parsed_url.hostname or "").casefold()
    if hostname not in AOPS_HOSTS:
        return None
    if AOPS_COMMUNITY_COLLECTION_RE.match(parsed_url.path) is None:
        return None
    return f"{AOPS_READER_URL_PREFIX}{source_url}"


def _title_case_aops_slug_word(word: str) -> str:
    normalized_word = word.casefold()
    if normalized_word in AOPS_SLUG_WORD_REPLACEMENTS:
        return AOPS_SLUG_WORD_REPLACEMENTS[normalized_word]
    return normalized_word.capitalize()


def _aops_collection_header_from_url(source_url: str) -> str | None:
    parsed_url = urllib.parse.urlparse(source_url)
    match = AOPS_COMMUNITY_COLLECTION_RE.match(parsed_url.path)
    if match is None:
        return None

    slug = match.group("slug") or ""
    slug_parts = [part for part in re.split(r"[_-]+", slug) if part]
    year_index = next((index for index, part in enumerate(slug_parts) if re.fullmatch(r"\d{4}", part)), None)
    if year_index is None:
        return None

    contest_words = slug_parts[:year_index] + slug_parts[year_index + 1 :]
    if not contest_words:
        return None

    titled_words: list[str] = []
    index = 0
    while index < len(contest_words):
        word = contest_words[index].casefold()
        if word == "all" and index + 1 < len(contest_words) and contest_words[index + 1].casefold() == "russian":
            titled_words.append("All-Russian")
            index += 2
            continue
        titled_words.append(_title_case_aops_slug_word(word))
        index += 1

    return f"{slug_parts[year_index]} {' '.join(titled_words)}"


def _latex_from_aops_markdown_image_alt(alt_text: str, *, image_url: str) -> str:
    parsed_image_url = urllib.parse.urlparse(image_url)
    if (parsed_image_url.hostname or "").casefold() != AOPS_LATEX_IMAGE_HOST:
        return ""

    candidate = html.unescape(alt_text).strip()
    if ":" in candidate and candidate.split(":", 1)[0].strip().casefold().startswith("image"):
        candidate = candidate.split(":", 1)[1].strip()
    if not candidate:
        return ""

    if candidate.startswith(r"\(") and candidate.endswith(r"\)"):
        return f"${candidate[2:-2].strip()}$"
    if candidate.startswith(r"\[") and candidate.endswith(r"\]"):
        return "\\[\n" + candidate[2:-2].strip() + "\n\\]"
    if candidate.startswith("$") and candidate.endswith("$"):
        return candidate
    return ""


def _replace_aops_markdown_image(match: re.Match[str]) -> str:
    latex = _latex_from_aops_markdown_image_alt(
        match.group("alt"),
        image_url=match.group("url"),
    )
    if not latex:
        return ""
    if latex.startswith((r"\[", "$$")):
        return f"\n{latex}\n"
    return latex


def _aops_reader_markdown_body(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().casefold() == "markdown content:":
            return "\n".join(lines[index + 1 :])
    return markdown_text


def _aops_collection_id(source_url: str) -> str | None:
    parsed_url = urllib.parse.urlparse(source_url)
    match = AOPS_COMMUNITY_COLLECTION_RE.match(parsed_url.path)
    if match is None:
        match = AOPS_PRINTABLE_COLLECTION_RE.match(parsed_url.path)
    if match is None:
        return None
    return match.group("collection_id")


def _next_nonempty_reader_line(lines: list[str], current_index: int) -> str:
    for line in lines[current_index + 1 :]:
        stripped_line = line.strip()
        if stripped_line:
            return stripped_line
    return ""


def _is_aops_reader_collection_metadata_line(line: str, *, next_line: str) -> bool:
    normalized_line = " ".join(line.split()).casefold()
    normalized_next_line = " ".join(next_line.split()).casefold()
    if (
        re.fullmatch(r"\d+", normalized_line)
        and normalized_next_line.startswith("for ")
        and "grade" in normalized_next_line
    ):
        return True
    return normalized_line.startswith("for ") and "grade" in normalized_line


def _is_aops_reader_content_start(line: str) -> bool:
    candidate = " ".join(line.split())
    return bool(
        _normalized_day_label(candidate)
        or _normalized_grade_section_label(candidate)
        or _normalized_grade_level_section_label(candidate)
        or _is_problem_start_candidate(candidate),
    )


def _is_aops_reader_footer_line(line: str) -> bool:
    stripped_line = line.strip()
    footer_lines = (
        "Art of Problem Solving is an",
        "aops programs",
        "Something appears to not have loaded correctly.",
    )
    return (
        "aops-online-footer.svg" in stripped_line
        or stripped_line.startswith("Copyright ©")
        or stripped_line in footer_lines
    )


def _trim_aops_reader_page_chrome(markdown_text: str, *, source_url: str) -> str:
    lines = markdown_text.splitlines()
    collection_id = _aops_collection_id(source_url)
    if collection_id is not None:
        printable_marker = f"/downloads/printable_post_collections/{collection_id}"
        for index, line in enumerate(lines):
            if printable_marker in line:
                lines = lines[index + 1 :]
                break

    start_index = 0
    for index, line in enumerate(lines):
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if _is_aops_reader_collection_metadata_line(
            stripped_line,
            next_line=_next_nonempty_reader_line(lines, index),
        ):
            continue
        if _is_aops_reader_content_start(stripped_line):
            start_index = index
            break

    lines = lines[start_index:]
    end_index = len(lines)
    for index, line in enumerate(lines):
        if _is_aops_reader_footer_line(line):
            end_index = index
            break
    return "\n".join(lines[:end_index])


def _is_aops_reader_view_topic_line(line: str) -> bool:
    return AOPS_READER_VIEW_TOPIC_LINK_RE.fullmatch(line.strip()) is not None


def _can_join_aops_reader_problem_code_line(next_line: str) -> bool:
    candidate = next_line.strip()
    if not candidate:
        return False
    if USERNAME_LINE_RE.fullmatch(candidate):
        return False
    return not (
        PROBLEM_KEYWORD_START_RE.match(candidate)
        or GRADE_PREFIXED_PROBLEM_START_RE.match(candidate)
        or PROBLEM_START_RE.match(candidate)
        or SPECIAL_PROBLEM_CODE_RE.match(candidate)
        or _normalized_grade_section_label(candidate)
        or _normalized_grade_level_section_label(candidate)
        or _normalized_day_label(candidate)
    )


def _strip_aops_reader_author_lines(text: str) -> str:
    lines = text.splitlines()
    kept_lines: list[str] = []
    for index, line in enumerate(lines):
        stripped_line = line.strip()
        if _is_aops_reader_view_topic_line(stripped_line):
            continue
        next_index = index + 1
        while next_index < len(lines) and not lines[next_index].strip():
            next_index += 1
        next_line = lines[next_index].strip() if next_index < len(lines) else ""
        if USERNAME_LINE_RE.fullmatch(stripped_line) and (
            not next_line
            or _is_aops_reader_view_topic_line(next_line)
            or GRADE_PREFIXED_PROBLEM_START_RE.fullmatch(next_line)
            or _normalized_grade_section_label(next_line)
            or _normalized_grade_level_section_label(next_line)
        ):
            continue
        if stripped_line.startswith("_") and stripped_line.endswith("_") and len(stripped_line) > 2:
            kept_lines.append(stripped_line[1:-1])
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def _join_standalone_aops_reader_problem_codes(text: str) -> str:
    lines = text.splitlines()
    joined_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped_line = line.strip()
        problem_match = GRADE_PREFIXED_PROBLEM_START_RE.fullmatch(stripped_line)
        if problem_match is None:
            problem_match = PROBLEM_START_RE.fullmatch(stripped_line)
        if problem_match is not None and not (problem_match.group("statement") or "").strip():
            next_index = index + 1
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            if next_index < len(lines) and _can_join_aops_reader_problem_code_line(lines[next_index]):
                joined_lines.append(f"{stripped_line} {lines[next_index].strip()}")
                index = next_index + 1
                continue
        joined_lines.append(line)
        index += 1
    return "\n".join(joined_lines)


def _join_aops_reader_day_date_lines(text: str) -> str:
    lines = text.splitlines()
    joined_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped_line = line.strip()
        if _normalized_day_label(stripped_line):
            next_index = index + 1
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            if next_index < len(lines):
                date_label = _normalized_section_date_label(lines[next_index].strip())
                if date_label is not None:
                    joined_lines.append(f"{stripped_line} {date_label}")
                    index = next_index + 1
                    continue
        joined_lines.append(line)
        index += 1
    return "\n".join(joined_lines)


def _normalize_aops_reader_markdown(markdown_text: str, *, source_url: str) -> str:
    reader_body = _trim_aops_reader_page_chrome(
        _aops_reader_markdown_body(markdown_text),
        source_url=source_url,
    )
    converted_text = MARKDOWN_IMAGE_RE.sub(
        _replace_aops_markdown_image,
        reader_body,
    )
    reader_text = _strip_aops_reader_author_lines(_normalize_extracted_text(converted_text))
    reader_text = _join_aops_reader_day_date_lines(reader_text)
    normalized_text = _normalize_extracted_text(
        _join_standalone_aops_reader_problem_codes(reader_text),
    )
    header = _aops_collection_header_from_url(source_url)
    if header is None:
        return normalized_text

    first_line = next((line.strip() for line in normalized_text.splitlines() if line.strip()), "")
    if (
        _normalized_day_label(first_line) is None
        and (
            HEADER_LINE_RE.match(first_line)
            or HEADER_YEAR_SUFFIX_RE.match(first_line)
            or HEADER_YEAR_MIDDLE_RE.match(first_line)
        )
    ):
        return normalized_text
    return _normalize_extracted_text(f"{header}\n\n{normalized_text}")


def _fetch_aops_reader_statement_text(source_url: str) -> FetchedStatementText | None:
    reader_url = _aops_reader_url(source_url)
    if reader_url is None:
        return None

    payload, content_type = _request_url_payload(reader_url)
    decoded_text = _decode_fetched_text(payload, content_type)
    _reject_known_remote_error_page(decoded_text, source_url=reader_url)
    extracted_text = _normalize_aops_reader_markdown(decoded_text, source_url=source_url)
    if not extracted_text:
        msg = "No readable text was found at the fetched URL."
        raise ProblemStatementImportValidationError(msg)
    return FetchedStatementText(text=extracted_text, source_label="URL fetch")


def _parsed_statement_problem_count(text: str) -> int:
    with contextlib.suppress(ProblemStatementImportValidationError):
        return len(parse_contest_problem_statements(text).problems)
    return 0


def _latex_source_score(text: str) -> int:
    return len(LATEX_SOURCE_TOKEN_RE.findall(text))


def _is_better_aops_reader_text(*, reader_text: str, current_text: str) -> bool:
    reader_problem_count = _parsed_statement_problem_count(reader_text)
    current_problem_count = _parsed_statement_problem_count(current_text)
    if reader_problem_count > current_problem_count:
        return True
    if reader_problem_count == 0 or reader_problem_count != current_problem_count:
        return False
    return _latex_source_score(reader_text) > _latex_source_score(current_text)


def _fetch_better_aops_reader_statement_text(source_url: str, *, current_text: str) -> FetchedStatementText | None:
    with contextlib.suppress(ProblemStatementImportValidationError):
        reader_fetched = _fetch_aops_reader_statement_text(source_url)
        if reader_fetched is not None and _is_better_aops_reader_text(
            reader_text=reader_fetched.text,
            current_text=current_text,
        ):
            return reader_fetched
    return None


def _request_url_payload(source_url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(  # noqa: S310
        source_url,
        headers={
            "Accept": "application/pdf,text/html,text/plain,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": URL_FETCH_USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=URL_FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = getattr(response, "status", HTTPStatus.OK)
            payload = response.read(URL_FETCH_MAX_BYTES + 1)
            content_type = response.getheader("Content-Type", "") or ""
    except ProblemStatementImportValidationError:
        raise
    except (TimeoutError, OSError, ValueError, urllib.error.URLError) as exc:
        msg = "Could not fetch the URL. Check that it is public and reachable."
        raise ProblemStatementImportValidationError(msg) from exc

    if status >= HTTPStatus.BAD_REQUEST:
        msg = f"The URL returned HTTP {status}."
        raise ProblemStatementImportValidationError(msg)
    if len(payload) > URL_FETCH_MAX_BYTES:
        msg = "Fetched URL is too large. Use a PDF upload or paste the contest text instead."
        raise ProblemStatementImportValidationError(msg)
    if not payload:
        msg = "Fetched URL did not return any content."
        raise ProblemStatementImportValidationError(msg)
    return payload, content_type


def _pdf_reader_for(uploaded_file):
    reader_cls = PdfReader
    if reader_cls is None:
        with contextlib.suppress(ImportError):
            from pypdf import PdfReader as installed_reader_cls

            reader_cls = installed_reader_cls

    if reader_cls is None:
        msg = "PDF parsing dependency is unavailable. Install pypdf and try again."
        raise ProblemStatementImportValidationError(msg)

    try:
        return reader_cls(uploaded_file)
    except Exception as exc:
        msg = "Could not read the uploaded PDF. Please upload a valid text-based PDF file."
        raise ProblemStatementImportValidationError(msg) from exc


def _pdf_font_name(font_dict) -> str:
    if not font_dict:
        return ""
    return str(font_dict.get("/BaseFont") or "")


def _is_pdf_math_font(font_name: str) -> bool:
    return any(marker in font_name for marker in PDF_MATH_FONT_MARKERS)


def _is_pdf_number_font(font_name: str) -> bool:
    return any(marker in font_name for marker in PDF_TEXT_NUMBER_FONT_MARKERS)


def _pdf_chunk_has_math_symbol(text: str) -> bool:
    return PDF_MATH_SYMBOL_RE.search(text) is not None


def _is_definitely_math_pdf_chunk(chunk: _PdfTextChunk) -> bool:
    return (
        _is_pdf_math_font(chunk.font_name)
        or _pdf_chunk_has_math_symbol(chunk.text)
        or (_is_pdf_number_font(chunk.font_name) and chunk.font_size <= PDF_SMALL_MATH_FONT_SIZE)
    )


def _normalized_pdf_text_part(text: str) -> str:
    return (
        " ".join(text.split())
        .replace("ﬁ", "fi")
        .replace("ﬂ", "fl")
        .replace("ﬀ", "ff")
        .replace("ﬃ", "ffi")
        .replace("ﬄ", "ffl")
    )


def _normalized_pdf_math_text(text: str) -> str:
    normalized = _normalized_pdf_text_part(text)
    for source, replacement in PDF_LATEX_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)
    return normalized


def _append_latex_superscript(base: str, superscript: str) -> str:
    if not base:
        return f"^{{{superscript}}}"
    return f"{base}^{{{superscript}}}"


def _normalized_pdf_math_spacing(raw_math: str) -> str:
    normalized = re.sub(r"\s*([,+\-=])\s*", r" \1 ", raw_math)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.replace(r"\frac ", r"\frac")
    return normalized


def _render_pdf_math_run(chunks: list[_PdfTextChunk], *, baseline: float) -> str:
    rendered_parts: list[str] = []
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        token = _normalized_pdf_math_text(chunk.text).strip()
        if not token:
            index += 1
            continue

        if (
            chunk.font_size <= PDF_SMALL_MATH_FONT_SIZE
            and index + 1 < len(chunks)
            and chunks[index + 1].font_size <= PDF_SMALL_MATH_FONT_SIZE
            and chunk.y > chunks[index + 1].y + PDF_SCRIPT_Y_DELTA
        ):
            numerator = token
            denominator = _normalized_pdf_math_text(chunks[index + 1].text).strip()
            index += 2
            while (
                index < len(chunks)
                and chunks[index].font_size <= PDF_SMALL_MATH_FONT_SIZE
                and chunks[index].y < baseline + 1
            ):
                next_token = _normalized_pdf_math_text(chunks[index].text).strip()
                if next_token:
                    if chunks[index].y > chunks[index - 1].y + 1:
                        denominator = _append_latex_superscript(denominator, next_token)
                    else:
                        denominator += next_token
                index += 1
            rendered_parts.append(rf"\frac{{{numerator}}}{{{denominator}}}")
            continue

        if chunk.font_size <= 8 and chunk.y > baseline + PDF_SCRIPT_Y_DELTA:
            if rendered_parts:
                rendered_parts[-1] = _append_latex_superscript(rendered_parts[-1], token)
            else:
                rendered_parts.append(f"^{{{token}}}")
        elif chunk.font_size <= 8 and chunk.y < baseline - PDF_SCRIPT_Y_DELTA:
            if rendered_parts:
                rendered_parts[-1] = f"{rendered_parts[-1]}_{{{token}}}"
            else:
                rendered_parts.append(f"_{{{token}}}")
        else:
            rendered_parts.append(token)
        index += 1

    return _normalized_pdf_math_spacing(" ".join(part for part in rendered_parts if part))


def _pdf_line_baseline(chunks: list[_PdfTextChunk]) -> float:
    candidates = [chunk.y for chunk in chunks if chunk.font_size >= PDF_SMALL_MATH_FONT_SIZE]
    if candidates:
        return statistics.median(candidates)
    return statistics.median(chunk.y for chunk in chunks)


def _pdf_math_flags(chunks: list[_PdfTextChunk]) -> list[bool]:
    definite_flags = [_is_definitely_math_pdf_chunk(chunk) for chunk in chunks]
    math_flags: list[bool] = []
    for index, chunk in enumerate(chunks):
        is_math = definite_flags[index]
        if _is_pdf_number_font(chunk.font_name) and not is_math:
            is_math = (
                _pdf_chunk_has_math_symbol(chunk.text)
                or (index > 0 and definite_flags[index - 1])
                or (index + 1 < len(chunks) and definite_flags[index + 1])
            )
        math_flags.append(is_math)
    return math_flags


def _render_pdf_latexish_line(chunks: list[_PdfTextChunk]) -> str:
    baseline = _pdf_line_baseline(chunks)
    math_flags = _pdf_math_flags(chunks)
    rendered_parts: list[str] = []
    math_run: list[_PdfTextChunk] = []

    def flush_math_run() -> None:
        if not math_run:
            return
        rendered_math = _render_pdf_math_run(math_run, baseline=baseline)
        math_run.clear()
        if rendered_math:
            rendered_parts.append(f"${rendered_math}$")

    for chunk, is_math in zip(chunks, math_flags):
        if is_math:
            math_run.append(chunk)
            continue
        flush_math_run()
        text_part = _normalized_pdf_text_part(chunk.text)
        if text_part:
            rendered_parts.append(text_part)

    flush_math_run()
    line = " ".join(part.strip() for part in rendered_parts if part.strip())
    line = re.sub(r"\s+([,.;:?])", r"\1", line)
    return re.sub(r"\s+", " ", line).strip()


def _pdf_line_groups(chunks: list[_PdfTextChunk]) -> list[_PdfLineGroup]:
    groups: list[_PdfLineGroup] = []
    for chunk in chunks:
        for group in groups:
            if abs(chunk.y - group.y) <= PDF_LINE_GROUP_Y_TOLERANCE:
                group.chunks.append(chunk)
                group.y_values.append(chunk.y)
                group.y = statistics.median(group.y_values)
                break
        else:
            groups.append(_PdfLineGroup(y=chunk.y, y_values=[chunk.y], chunks=[chunk]))
    return sorted(groups, key=lambda group: -group.y)


def _clean_pdf_latexish_text(raw_text: str) -> str:
    cleaned_lines: list[str] = []
    seen_aops_header = False
    for line in raw_text.splitlines():
        stripped = line.strip()
        if PDF_AOPS_COPYRIGHT_RE.fullmatch(stripped):
            continue
        if stripped == "Art of Problem Solving is an ACS WASC Accredited School.":
            continue
        if section_match := re.fullmatch(r"[–-]\s+(Grade\s+\d{1,2}|Day\s+\d+)", stripped, flags=re.IGNORECASE):
            stripped = section_match.group(1)
            line = stripped
        if stripped.startswith("AoPS Community "):
            if seen_aops_header:
                continue
            seen_aops_header = True
        cleaned_lines.append(line)
    return _normalize_extracted_text("\n".join(cleaned_lines))


def _extract_latexish_text_from_pdf_page(page) -> str:
    chunks: list[_PdfTextChunk] = []
    order = 0

    def visitor_text(text, _cm, tm, font_dict, font_size) -> None:
        nonlocal order
        normalized_text = str(text).replace("\x00", "")
        normalized_text = normalized_text.replace("\r\n", "\n").replace("\r", "\n")
        try:
            x = float(tm[4])
            y = float(tm[5])
        except (IndexError, TypeError, ValueError):
            x = 0.0
            y = 0.0
        for part in normalized_text.splitlines():
            if not part.strip():
                continue
            chunks.append(
                _PdfTextChunk(
                    text=part,
                    x=x,
                    y=y,
                    font_size=float(font_size or 0),
                    font_name=_pdf_font_name(font_dict),
                    order=order,
                ),
            )
            order += 1

    try:
        page.extract_text(visitor_text=visitor_text)
    except TypeError:
        return page.extract_text() or ""
    except Exception as exc:
        msg = "Could not extract text from one or more PDF pages."
        raise ProblemStatementImportValidationError(msg) from exc

    if not chunks:
        return ""

    rendered_lines: list[str] = []
    for group in _pdf_line_groups(chunks):
        line_chunks = sorted(group.chunks, key=lambda chunk: chunk.order)
        rendered_line = _render_pdf_latexish_line(line_chunks)
        if rendered_line:
            rendered_lines.append(rendered_line)
    return "\n".join(rendered_lines)


def extract_statement_latexish_text_from_pdf(uploaded_file) -> str:
    with contextlib.suppress(AttributeError, OSError):
        uploaded_file.seek(0)

    reader = _pdf_reader_for(uploaded_file)
    page_chunks: list[str] = []
    for page in reader.pages:
        extracted = _extract_latexish_text_from_pdf_page(page).strip()
        if extracted:
            page_chunks.append(extracted)

    extracted_text = _clean_pdf_latexish_text("\n\n".join(page_chunks))
    if not extracted_text:
        msg = "No extractable text was found in the uploaded PDF. The file may be image-only."
        raise ProblemStatementImportValidationError(msg)
    return extracted_text


def fetch_statement_text_from_url(source_url: str) -> FetchedStatementText:
    validated_url = _validated_source_url(source_url)
    printable_url = _aops_printable_url(validated_url)
    fetch_url = printable_url or validated_url
    payload, content_type = _request_url_payload(fetch_url)

    if "pdf" in content_type.casefold() or payload.startswith(b"%PDF"):
        stream = BytesIO(payload)
        stream.name = "remote-statement-source.pdf"
        extracted_text = extract_statement_latexish_text_from_pdf(stream)
        if printable_url is not None:
            reader_fetched = _fetch_better_aops_reader_statement_text(validated_url, current_text=extracted_text)
            if reader_fetched is not None:
                return reader_fetched
        return FetchedStatementText(text=extracted_text, source_label="URL fetch")

    decoded_text = _decode_fetched_text(payload, content_type)
    if printable_url is not None and _is_aops_printable_latex_error_page(decoded_text, source_url=fetch_url):
        reader_fetched = _fetch_aops_reader_statement_text(validated_url)
        if reader_fetched is not None:
            return reader_fetched
    _reject_known_remote_error_page(decoded_text, source_url=fetch_url)
    if "html" in content_type.casefold() or b"<html" in payload[:2048].casefold():
        extracted_text = _extract_visible_text_from_html(decoded_text)
    else:
        extracted_text = _normalize_extracted_text(decoded_text)

    if not extracted_text:
        msg = "No readable text was found at the fetched URL."
        raise ProblemStatementImportValidationError(msg)
    return FetchedStatementText(text=extracted_text, source_label="URL fetch")


def extract_statement_text_from_pdf(uploaded_file) -> str:
    with contextlib.suppress(AttributeError, OSError):
        uploaded_file.seek(0)

    reader = _pdf_reader_for(uploaded_file)
    page_chunks: list[str] = []
    for page in reader.pages:
        try:
            raw_text = page.extract_text() or ""
        except Exception as exc:
            msg = "Could not extract text from one or more PDF pages."
            raise ProblemStatementImportValidationError(msg) from exc

        normalized = raw_text.replace("\x00", "")
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.strip()
        if normalized:
            page_chunks.append(normalized)

    extracted_text = "\n\n".join(page_chunks).strip()
    if not extracted_text:
        msg = "No extractable text was found in the uploaded PDF. The file may be image-only."
        raise ProblemStatementImportValidationError(msg)

    return extracted_text


@dataclass(frozen=True)
class ParsedContestProblemStatement:
    day_label: str
    problem_code: str
    problem_number: int
    statement_latex: str


@dataclass(frozen=True)
class ParsedContestStatementImport:
    contest_year: int
    contest_name: str
    problems: tuple[ParsedContestProblemStatement, ...]


@dataclass(frozen=True)
class ProblemStatementImportResult:
    created_count: int
    updated_count: int
    linked_problem_count: int


@dataclass(frozen=True)
class ProblemStatementRelinkResult:
    checked_count: int
    linked_count: int
    newly_linked_count: int
    skipped_count: int
    unlinked_count: int
    updated_count: int


@dataclass
class _StatementParseState:
    contest_year: int | None = None
    contest_name: str = ""
    current_day: str = ""
    current_primary_section: str = ""
    current_secondary_section: str = ""
    allows_section_date_metadata: bool = False
    allows_day_subsection: bool = False
    current_problem_code: str | None = None
    current_problem_number: int | None = None
    awaiting_new_problem: bool = False
    current_statement_lines: list[str] = field(default_factory=list)
    parsed_problems: list[ParsedContestProblemStatement] = field(default_factory=list)


def _clean_contest_name(raw_name: str) -> str:
    cleaned_name = re.sub(r"(?<![\s\d])\d$", "", raw_name.strip())
    return cleaned_name.strip()


def _parse_header_line(header_line: str) -> tuple[int, str]:
    match = HEADER_LINE_RE.match(header_line)
    if match:
        contest_year = int(match.group("year_end") or match.group("year_start"))
        contest_name = _clean_contest_name(match.group("contest"))
        if not contest_name:
            msg = "Contest name is empty after parsing the header line."
            raise ProblemStatementImportValidationError(msg)
        return contest_year, contest_name

    match = HEADER_YEAR_MIDDLE_RE.match(header_line)
    if match:
        contest_year = int(match.group("year"))
        contest_name = _clean_contest_name(
            f"{match.group('prefix')} {match.group('suffix')}",
        )
        if not contest_name:
            msg = "Contest name is empty after parsing the header line."
            raise ProblemStatementImportValidationError(msg)
        return contest_year, contest_name

    match = HEADER_YEAR_SUFFIX_RE.match(header_line)
    if not match:
        msg = "Could not parse the contest header. Expected a line like '2026 Spain Mathematical Olympiad'."
        raise ProblemStatementImportValidationError(msg)

    contest_year = int(match.group("year"))
    contest_name = _clean_contest_name(match.group("contest"))
    if not contest_name:
        msg = "Contest name is empty after parsing the header line."
        raise ProblemStatementImportValidationError(msg)
    return contest_year, contest_name


def _collapse_statement_lines(lines: list[str]) -> str:
    trimmed_lines = [line.rstrip() for line in lines]
    while trimmed_lines and not trimmed_lines[0].strip():
        trimmed_lines.pop(0)
    while trimmed_lines and not trimmed_lines[-1].strip():
        trimmed_lines.pop()

    collapsed_lines: list[str] = []
    previous_blank = False
    for line in trimmed_lines:
        if not line.strip():
            if previous_blank:
                continue
            collapsed_lines.append("")
            previous_blank = True
            continue
        collapsed_lines.append(line.strip())
        previous_blank = False

    return _normalize_statement_latex("\n".join(collapsed_lines).strip())


def _supports_trailing_credit_cleanup(day_label: str, *, contest_name: str) -> bool:
    normalized_contest_name = contest_name.casefold()
    normalized_day_label = day_label.casefold()
    return (
        re.search(r"(?:^|\s)tst(?:\s|$)", normalized_contest_name) is not None
        or "team selection test" in normalized_contest_name
        or "training camp" in normalized_contest_name
        or "practice test" in normalized_contest_name
        or normalized_day_label.startswith(
            (
                "tst #",
                "test ",
                "first exam",
                "second exam",
                "third exam",
                "final exam",
            ),
        )
        or " · test " in normalized_day_label
        or "selection test" in normalized_day_label
        or "training camp" in normalized_day_label
    )


def _is_trailing_credit_line(line: str, *, day_label: str, contest_name: str) -> bool:
    if line.strip().casefold() == "unavailable":
        return False
    if not _supports_trailing_credit_cleanup(day_label, contest_name=contest_name):
        return False
    return bool(
        TRAILING_PROPOSED_BY_LINE_RE.fullmatch(line)
        or TRAILING_AUTHOR_LINE_RE.fullmatch(line),
    )


def _is_generic_trailing_metadata_line(line: str) -> bool:
    stripped_line = line.strip()
    if not stripped_line:
        return False
    if stripped_line.casefold() == "unavailable":
        return False
    if stripped_line in IGNORED_STATEMENT_LINES:
        return True
    if NOTE_METADATA_LINE_RE.fullmatch(stripped_line):
        return True
    if USERNAME_LINE_RE.fullmatch(stripped_line):
        return True
    return _looks_like_author_credit_line(stripped_line)


def _looks_like_inline_author_credit_suffix(line: str) -> bool:
    candidate = " ".join(line.split())
    if not _looks_like_author_credit_line(candidate):
        return False
    return "," in candidate or " and " in candidate or len(candidate.split()) >= 2


def _looks_like_inline_trailing_credit_suffix(
    line: str,
    *,
    day_label: str,
    contest_name: str,
) -> bool:
    candidate = " ".join(line.split())
    return _looks_like_inline_author_credit_suffix(candidate) or _is_trailing_credit_line(
        candidate,
        day_label=day_label,
        contest_name=contest_name,
    )


def _trim_trailing_inline_author_suffix(
    line: str,
    *,
    day_label: str,
    contest_name: str,
) -> str:
    stripped_line = line.rstrip()
    for separator in (r"\]", "$$", ".", "?", "!"):
        separator_index = stripped_line.rfind(separator)
        if separator_index < 0:
            continue
        candidate = stripped_line[separator_index + len(separator) :].strip()
        if not _looks_like_inline_trailing_credit_suffix(
            candidate,
            day_label=day_label,
            contest_name=contest_name,
        ):
            continue
        return stripped_line[: separator_index + len(separator)].rstrip()
    return stripped_line


def _trim_trailing_problem_metadata(lines: list[str], *, day_label: str, contest_name: str) -> list[str]:
    trimmed_lines = list(lines)

    while trimmed_lines and not trimmed_lines[-1].strip():
        trimmed_lines.pop()

    if trimmed_lines:
        trimmed_lines[-1] = _trim_trailing_inline_author_suffix(
            trimmed_lines[-1],
            day_label=day_label,
            contest_name=contest_name,
        )
        while trimmed_lines and not trimmed_lines[-1].strip():
            trimmed_lines.pop()

    while trimmed_lines and _is_trailing_credit_line(
        trimmed_lines[-1].strip(),
        day_label=day_label,
        contest_name=contest_name,
    ):
        trimmed_lines.pop()
        while trimmed_lines and not trimmed_lines[-1].strip():
            trimmed_lines.pop()

    while trimmed_lines and _is_generic_trailing_metadata_line(trimmed_lines[-1]):
        trimmed_lines.pop()
        while trimmed_lines and not trimmed_lines[-1].strip():
            trimmed_lines.pop()

    return trimmed_lines


def _normalize_statement_latex(statement_latex: str) -> str:
    normalized = TEXT_ONLY_EMPH_INLINE_RE.sub(
        lambda match: f"$\\text{{{match.group('content')}}}$",
        statement_latex,
    )
    normalized = TEXT_ONLY_EMPH_PAREN_RE.sub(
        lambda match: f"\\(\\text{{{match.group('content')}}}\\)",
        normalized,
    )
    normalized = TEXT_ONLY_EMPH_DISPLAY_RE.sub(
        lambda match: f"$$\\text{{{match.group('content')}}}$$",
        normalized,
    )
    return TEXT_ONLY_EMPH_BRACKET_RE.sub(
        lambda match: f"\\[\\text{{{match.group('content')}}}\\]",
        normalized,
    )


def _normalized_statement_lines(raw_text: str) -> list[str]:
    stripped_text = raw_text.strip()
    if not stripped_text:
        msg = "Paste contest text before parsing."
        raise ProblemStatementImportValidationError(msg)
    return [line.rstrip() for line in stripped_text.splitlines()]


def _parse_contest_header(lines: list[str]) -> tuple[int, str, list[str]]:
    header_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if header_index is None:
        msg = "Paste contest text before parsing."
        raise ProblemStatementImportValidationError(msg)

    first_header_line = lines[header_index].strip()
    try:
        contest_year, contest_name = _parse_header_line(first_header_line)
        return contest_year, contest_name, lines[header_index + 1 :]
    except ProblemStatementImportValidationError:
        next_header_index = next(
            (index for index in range(header_index + 1, len(lines)) if lines[index].strip()),
            None,
        )
        if next_header_index is None:
            raise
        next_header_line = lines[next_header_index].strip()
        if _looks_like_post_header_content(next_header_line):
            contest_year, contest_name = _parse_header_line(first_header_line)
            return contest_year, contest_name, lines[header_index + 1 :]
        contest_year, _ = _parse_header_line(lines[next_header_index].strip())
        contest_name = _clean_contest_name(first_header_line)
        if not contest_name:
            raise
        return contest_year, contest_name, lines[header_index + 1 :]


def _flush_problem(state: _StatementParseState) -> None:
    if state.current_problem_number is None:
        return

    statement_latex = _collapse_statement_lines(
        _trim_trailing_problem_metadata(
            state.current_statement_lines,
            day_label=state.current_day,
            contest_name=state.contest_name,
        ),
    )
    if not statement_latex:
        msg = f"Problem {state.current_problem_number} does not have any statement text."
        raise ProblemStatementImportValidationError(msg)

    state.parsed_problems.append(
        ParsedContestProblemStatement(
            day_label=state.current_day,
            problem_code=state.current_problem_code or f"P{state.current_problem_number}",
            problem_number=state.current_problem_number,
            statement_latex=statement_latex,
        ),
    )
    state.current_problem_code = None
    state.current_problem_number = None
    state.awaiting_new_problem = False
    state.current_statement_lines = []


def _compose_section_label(primary: str, secondary: str) -> str:
    if primary and secondary:
        return f"{primary} · {secondary}"
    return primary or secondary


def _compose_nested_section_label(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


def _set_primary_section(
    state: _StatementParseState,
    label: str,
    *,
    allows_section_date_metadata: bool = False,
    allows_day_subsection: bool = False,
) -> None:
    state.current_primary_section = label
    state.current_secondary_section = ""
    state.current_day = _compose_section_label(
        state.current_primary_section,
        state.current_secondary_section,
    )
    state.allows_section_date_metadata = allows_section_date_metadata
    state.allows_day_subsection = allows_day_subsection


def _set_secondary_section(state: _StatementParseState, label: str) -> None:
    state.current_secondary_section = label
    state.current_day = _compose_section_label(
        state.current_primary_section,
        state.current_secondary_section,
    )
    state.allows_section_date_metadata = False
    state.allows_day_subsection = False


def _set_division_section(state: _StatementParseState, label: str) -> None:
    _set_secondary_section(state, label)


def _division_from_secondary_label(label: str) -> str:
    stripped_label = label.strip()
    if stripped_label.startswith("Junior"):
        return "Junior"
    if stripped_label.startswith("Senior"):
        return "Senior"
    return ""


def _set_track_section(state: _StatementParseState, label: str) -> None:
    division = _division_from_secondary_label(state.current_secondary_section)
    _set_secondary_section(state, f"{division} {label}".strip())


def _is_structured_day_subsection_part(label: str) -> bool:
    candidate = " ".join(label.split())
    return bool(
        _normalized_day_label(candidate)
        or _normalized_test_label(candidate)
        or _normalized_exam_day_label(candidate),
    )


def _set_day_subsection(state: _StatementParseState, day_label: str) -> None:
    if not state.current_secondary_section:
        _set_secondary_section(state, day_label)
        return

    secondary_parts = [part for part in state.current_secondary_section.split(" · ") if part]
    if (
        len(secondary_parts) >= 2
        and _is_structured_day_subsection_part(secondary_parts[-2])
        and _normalized_section_date_label(secondary_parts[-1]) is not None
    ):
        secondary_parts = secondary_parts[:-2]
    elif secondary_parts and _is_structured_day_subsection_part(secondary_parts[-1]):
        secondary_parts = secondary_parts[:-1]
    secondary_parts.append(day_label)
    _set_secondary_section(state, _compose_nested_section_label(*secondary_parts))


def _next_nonempty_lines(lines: list[str], current_index: int, *, limit: int = 1) -> list[str]:
    candidates: list[str] = []
    for raw_line in lines[current_index + 1 :]:
        candidate = raw_line.strip()
        if not candidate:
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def _is_scrape_metadata_line(
    line: str,
    *,
    next_nonempty_line: str | None,
    following_nonempty_line: str | None,
    third_nonempty_line: str | None,
) -> bool:
    if line in IGNORED_STATEMENT_LINES:
        return True
    if SOLUTION_LINE_RE.fullmatch(line):
        return True
    if (
        following_nonempty_line == "view topic"
        and next_nonempty_line is not None
        and USERNAME_LINE_RE.fullmatch(next_nonempty_line)
        and _looks_like_author_credit_line(line)
    ):
        return True
    if (
        _looks_like_author_credit_line(line)
        and next_nonempty_line is not None
        and NOTE_METADATA_LINE_RE.fullmatch(next_nonempty_line)
        and following_nonempty_line is not None
        and USERNAME_LINE_RE.fullmatch(following_nonempty_line)
        and third_nonempty_line == "view topic"
    ):
        return True
    if (
        NOTE_METADATA_LINE_RE.fullmatch(line)
        and next_nonempty_line is not None
        and USERNAME_LINE_RE.fullmatch(next_nonempty_line)
        and following_nonempty_line == "view topic"
    ):
        return True
    return next_nonempty_line == "view topic"


def _normalized_section_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    for label in SECTION_HEADER_LABELS:
        if candidate.casefold() == label.casefold():
            return label
    return None


def _normalized_section_date_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    if SECTION_DATE_LINE_RE.fullmatch(candidate) is None:
        return None
    return candidate


def _looks_like_author_credit_line(line: str) -> bool:
    candidate = " ".join(line.split())
    candidate = re.sub(
        r"\s*\((?:Junior|Senior) version (?:posted )?here\)\s*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    if not candidate or len(candidate) > 120:
        return False
    if "proposed by" in candidate.casefold():
        return False
    if candidate.startswith("http"):
        return False
    if any(character.isdigit() for character in candidate):
        return False
    if any(character in candidate for character in "$\\=<>/?{}[]_"):
        return False

    for segment in re.split(r",| and ", candidate):
        segment = segment.strip()
        if not segment:
            return False
        tokens = segment.split()
        if len(tokens) > 4:
            return False
        for token in tokens:
            normalized_token = token.strip("().").replace("’", "'")
            if not normalized_token:
                return False
            if not any(character.isalpha() for character in normalized_token):
                return False
            if not all(character.isalpha() or character in ".'-" for character in normalized_token):
                return False
            first_alpha = next(
                (character for character in normalized_token if character.isalpha()),
                "",
            )
            if not first_alpha or first_alpha != first_alpha.upper():
                return False
    return True


def _normalized_paper_section_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    if PAPER_SECTION_RE.fullmatch(candidate) or SEASON_FIRST_PAPER_SECTION_RE.fullmatch(candidate):
        return candidate
    return None


def _normalized_season_section_label(line: str) -> str | None:
    candidate = " ".join(line.split())
    match = SEASON_SECTION_RE.fullmatch(candidate)
    if match is None:
        match = YEAR_FIRST_SEASON_SECTION_RE.fullmatch(candidate)
    if match is None:
        return None
    return f"{match.group('season').title()} {match.group('year')}"


def _normalized_division_section_label(line: str) -> str | None:
    match = DIVISION_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    division = match.group("division").casefold()
    return "Junior" if division.startswith("junior") else "Senior"


def _normalized_level_section_label(line: str) -> str | None:
    match = LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"{match.group('division').title()} {match.group('track').upper()}-Level"


def _normalized_track_section_label(line: str) -> str | None:
    match = TRACK_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"{match.group('track').upper()}-Level"


def _normalized_grade_section_label(line: str) -> str | None:
    match = GRADE_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"Grade {int(match.group('number'))}"


def _normalized_grade_level_section_label(line: str) -> str | None:
    match = GRADE_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"Grade level {int(match.group('number'))}"


def _normalized_inline_season_level_label(line: str) -> str | None:
    match = INLINE_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {match.group('year')}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_hyphenated_season_level_label(line: str) -> str | None:
    match = HYPHENATED_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {match.group('year')}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_yearless_hyphenated_season_level_label(
    line: str,
    *,
    contest_year: int | None,
) -> str | None:
    if contest_year is None:
        return None
    match = YEARLESS_HYPHENATED_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {contest_year}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_yearless_season_level_label(
    line: str,
    *,
    contest_year: int | None,
) -> str | None:
    if contest_year is None:
        return None
    match = YEARLESS_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {contest_year}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_round_prefixed_yearless_season_level_label(
    line: str,
    *,
    contest_year: int | None,
) -> str | None:
    if contest_year is None:
        return None
    match = ROUND_PREFIXED_YEARLESS_SEASON_LEVEL_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return (
        f"{match.group('season').title()} {contest_year}"
        f" · {match.group('division').title()} {match.group('track').upper()}-Level"
    )


def _normalized_problem_statement_text(statement: str, *, number: int) -> str:
    candidate = statement.strip()
    inner_match = INNER_NUMBERED_STATEMENT_RE.match(candidate)
    if inner_match is not None and int(inner_match.group("number")) == number:
        return inner_match.group("statement").strip()
    return candidate


def _current_grade_section_number(state: _StatementParseState) -> int | None:
    section_label = state.current_primary_section or state.current_day
    for pattern in (GRADE_SECTION_RE, GRADE_LEVEL_SECTION_RE):
        match = pattern.fullmatch(section_label)
        if match is not None:
            return int(match.group("number"))
    return None


def _current_dotted_problem_group(state: _StatementParseState) -> int | None:
    if not state.current_problem_code:
        return None
    match = DOTTED_PROBLEM_CODE_RE.fullmatch(state.current_problem_code)
    if match is None:
        return None
    return int(match.group("group"))


def _is_section_metadata_line(line: str | None) -> bool:
    if line is None:
        return False
    return bool(
        SECTION_DATE_LINE_RE.fullmatch(line)
        or SECTION_TIME_LINE_RE.fullmatch(line),
    )


def _looks_like_generic_section_header_candidate(candidate: str) -> bool:
    if not candidate or not candidate[0].isalpha():
        return False
    if len(candidate) > 120:
        return False
    if candidate.endswith((".", "!", "?", ":", ";")):
        return False
    if any(character in candidate for character in "$\\=<>/?{}[]_"):
        return False
    return all(
        character.isalnum() or character.isspace() or character in "(),'&#-"
        for character in candidate
    )


def _is_named_day_section_header(candidate: str) -> bool:
    return NAMED_DAY_SECTION_RE.fullmatch(candidate) is not None


def _is_numbered_sibling_section(current_label: str, candidate_label: str) -> bool:
    current_match = NUMBERED_SIBLING_SECTION_RE.fullmatch(current_label)
    candidate_match = NUMBERED_SIBLING_SECTION_RE.fullmatch(candidate_label)
    if current_match is None or candidate_match is None:
        return False
    return current_match.group("family").casefold() == candidate_match.group("family").casefold()


def _supports_named_day_subsections(candidate: str) -> bool:
    normalized_candidate = candidate.casefold()
    return any(
        keyword in normalized_candidate
        for keyword in ("test", "selection", "squad", "camp", "exam")
    )


def _is_problem_start_candidate(line: str | None) -> bool:
    if line is None:
        return False
    return bool(
        PROBLEM_KEYWORD_START_RE.match(line)
        or GRADE_PREFIXED_PROBLEM_START_RE.match(line)
        or
        PROBLEM_START_RE.match(line)
        or SPECIAL_PROBLEM_CODE_RE.match(line)
        or ALPHA_PROBLEM_CODE_RE.match(line),
    )


def _looks_like_post_header_content(line: str | None) -> bool:
    if line is None:
        return False
    normalized_line = " ".join(line.split())
    return bool(
        _normalized_day_label(normalized_line)
        or _normalized_tst_day_label(normalized_line)
        or _normalized_exam_day_label(normalized_line)
        or _normalized_part_label(normalized_line)
        or TEST_LABEL_RE.fullmatch(normalized_line)
        or ROUND_LABEL_RE.fullmatch(normalized_line)
        or _is_problem_start_candidate(line),
    )


def _is_structured_section_header(line: str | None) -> bool:
    if line is None:
        return False
    normalized_line = " ".join(line.split())
    return bool(
        _normalized_day_label(normalized_line)
        or _normalized_tst_day_label(normalized_line)
        or _normalized_exam_day_label(normalized_line)
        or _normalized_part_label(normalized_line)
        or _normalized_test_label(normalized_line)
        or ROUND_LABEL_RE.fullmatch(normalized_line)
        or _normalized_round_and_section_label(normalized_line),
    )


def _is_generic_section_header(
    line: str,
    *,
    next_nonempty_line: str | None,
    following_nonempty_line: str | None,
    third_nonempty_line: str | None,
) -> bool:
    candidate = " ".join(line.split())
    normalized_next_line = " ".join((next_nonempty_line or "").split())
    candidate_problem_match = PROBLEM_START_RE.match(candidate)
    if _is_section_metadata_line(candidate):
        return False
    if (
        candidate_problem_match is not None
        and candidate_problem_match.group("statement")
        and not _is_structured_section_header(candidate)
        and not (
            _is_section_metadata_line(next_nonempty_line)
            and _is_problem_start_candidate(following_nonempty_line)
        )
    ):
        return False
    if SHORT_SECTION_HEADER_RE.fullmatch(candidate) and _is_problem_start_candidate(next_nonempty_line):
        return True
    if (
        " " in candidate
        and SHORT_SECTION_HEADER_RE.fullmatch(candidate)
        and _looks_like_generic_section_header_candidate(normalized_next_line)
        and (
            _is_problem_start_candidate(following_nonempty_line)
            or (
                _is_section_metadata_line(following_nonempty_line)
                and _is_problem_start_candidate(third_nonempty_line)
            )
        )
    ):
        return True
    if _is_problem_start_candidate(candidate):
        return False
    if (
        SHORT_SECTION_HEADER_RE.fullmatch(candidate)
        and _looks_like_generic_section_header_candidate(normalized_next_line)
        and (
            _is_problem_start_candidate(following_nonempty_line)
            or (
                _is_section_metadata_line(following_nonempty_line)
                and _is_problem_start_candidate(third_nonempty_line)
            )
        )
    ):
        return True
    if not _looks_like_generic_section_header_candidate(candidate):
        return False
    if _is_named_day_section_header(candidate) and (
        _is_problem_start_candidate(next_nonempty_line)
        or (
            _is_named_day_section_header(normalized_next_line)
            and _is_problem_start_candidate(following_nonempty_line)
        )
    ):
        return True
    if (
        _supports_named_day_subsections(candidate)
        and DAY_LABEL_RE.fullmatch(" ".join((next_nonempty_line or "").split()))
        and (
            _is_problem_start_candidate(following_nonempty_line)
            or (
                _is_section_metadata_line(following_nonempty_line)
                and _is_problem_start_candidate(third_nonempty_line)
            )
        )
    ):
        return True
    if _is_section_metadata_line(next_nonempty_line) and _is_problem_start_candidate(following_nonempty_line):
        return True
    return bool(
        _is_section_metadata_line(next_nonempty_line)
        and _is_section_metadata_line(following_nonempty_line)
        and _is_problem_start_candidate(third_nonempty_line),
    )


def _next_problem_number_for_current_section(state: _StatementParseState) -> int:
    section_problem_numbers = [
        problem.problem_number
        for problem in state.parsed_problems
        if problem.day_label == state.current_day
    ]
    return max(section_problem_numbers, default=0) + 1


def _normalized_day_label(line: str) -> str | None:
    match = DAY_LABEL_RE.fullmatch(line)
    if match is None:
        return None
    token = match.group("token")
    normalized_token = token if token.isdigit() else token.upper()
    label = f"Day {normalized_token}"
    detail = " ".join((match.group("detail") or "").split())
    if not detail:
        return label
    return f"{label} · {detail}"


def _normalized_tst_day_label(line: str) -> str | None:
    match = TST_DAY_LABEL_RE.fullmatch(line)
    if match is None:
        return None
    label = f"TST #{int(match.group('number'))}"
    detail = " ".join((match.group("detail") or "").split())
    detail = re.sub(r"(?<=\d)\(", " (", detail)
    if not detail:
        return label
    return f"{label} · {detail}"


def _normalized_exam_day_label(line: str) -> str | None:
    match = EXAM_AND_DAY_LABEL_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    day_label = _normalized_day_label(match.group("day"))
    if day_label is None:
        return None
    return f"{match.group('exam').title()} exam · {day_label}"


def _normalized_year_prefixed_section_label(
    line: str,
    *,
    contest_year: int | None,
    next_nonempty_line: str | None,
) -> str | None:
    if contest_year is None or next_nonempty_line is None:
        return None
    match = YEAR_PREFIXED_SECTION_RE.fullmatch(line)
    if match is None or int(match.group("year")) != contest_year:
        return None
    if not _is_problem_start_candidate(next_nonempty_line):
        return None
    return _clean_contest_name(match.group("label"))


def _normalized_year_suffixed_section_label(
    line: str,
    *,
    contest_year: int | None,
    contest_name: str,
    next_nonempty_line: str | None,
) -> str | None:
    if contest_year is None or next_nonempty_line is None:
        return None
    if _is_section_metadata_line(line) or _is_structured_section_header(next_nonempty_line):
        return None
    match = YEAR_SUFFIXED_SECTION_RE.fullmatch(line)
    if match is None or int(match.group("year")) != contest_year:
        return None
    if not _is_problem_start_candidate(next_nonempty_line):
        return None
    section_label = _clean_contest_name(match.group("label"))
    if section_label.casefold() != contest_name.casefold():
        return None
    return section_label


def _normalized_test_label(line: str) -> str | None:
    match = TEST_LABEL_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    token = match.group("number")
    normalized_token = str(int(token)) if token.isdigit() else token.upper()
    label = f"Test {normalized_token}"
    detail = " ".join((match.group("detail") or "").split())
    if not detail:
        return label
    if detail.startswith("(") and detail.endswith(")"):
        return f"{label} {detail}"
    return f"{label} · {detail}"


def _normalized_part_label(line: str) -> str | None:
    match = PART_LABEL_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    token = match.group("number")
    normalized_token = str(int(token)) if token.isdigit() else token.upper()
    label = f"Part {normalized_token}"
    detail = " ".join((match.group("detail") or "").split())
    if not detail:
        return label
    return f"{label} · {detail}"


def _normalized_round_and_section_label(line: str) -> str | None:
    match = ROUND_AND_SECTION_RE.fullmatch(" ".join(line.split()))
    if match is None:
        return None
    return f"{match.group('round').title()} Round · {match.group('label')}"


def _start_special_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    state.current_problem_code = match.group("code").upper()
    state.current_problem_number = _next_problem_number_for_current_section(state)
    state.awaiting_new_problem = False
    state.current_statement_lines = [match.group("statement").strip()]


def _start_alpha_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    state.current_problem_code = match.group("code").upper()
    state.current_problem_number = _next_problem_number_for_current_section(state)
    state.awaiting_new_problem = False
    state.current_statement_lines = [match.group("statement").strip()]


def _start_numbered_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    number = int(match.group("number"))
    prefix = (match.group("prefix") or "P").upper()
    statement_text = (match.group("statement") or "").strip()
    state.current_problem_code = f"{prefix}{number}"
    state.current_problem_number = number
    state.awaiting_new_problem = False
    state.current_statement_lines = (
        [_normalized_problem_statement_text(statement_text, number=number)]
        if statement_text
        else []
    )


def _start_keyword_numbered_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    number = int(match.group("number"))
    statement_text = (match.group("statement") or "").strip()
    state.current_problem_code = f"P{number}"
    state.current_problem_number = number
    state.awaiting_new_problem = False
    state.current_statement_lines = (
        [_normalized_problem_statement_text(statement_text, number=number)]
        if statement_text
        else []
    )


def _start_grade_prefixed_problem(state: _StatementParseState, match: re.Match[str]) -> None:
    _flush_problem(state)
    grade = int(match.group("grade"))
    number = int(match.group("number"))
    statement_text = (match.group("statement") or "").strip()
    state.current_problem_code = f"{grade}.{number}"
    state.current_problem_number = number
    state.awaiting_new_problem = False
    state.current_statement_lines = (
        [_normalized_problem_statement_text(statement_text, number=number)]
        if statement_text
        else []
    )


def _can_start_inline_numbered_problem(
    state: _StatementParseState,
    problem_match: re.Match[str],
) -> bool:
    if state.current_problem_number is None:
        return True
    if state.awaiting_new_problem:
        return True
    if problem_match.group("catalog_number"):
        return True

    prefix = (problem_match.group("prefix") or "").strip()
    if prefix:
        return True
    if state.current_problem_code and state.current_problem_code.isalpha():
        return False

    number = int(problem_match.group("number"))
    statement = (problem_match.group("statement") or "").lstrip()
    if not statement:
        return False
    first_char = statement[:1]
    return number == state.current_problem_number + 1 and first_char.isalpha()


def _can_start_grade_prefixed_problem(
    state: _StatementParseState,
    problem_match: re.Match[str],
) -> bool:
    current_grade = _current_grade_section_number(state)
    problem_group = int(problem_match.group("grade"))
    statement = (problem_match.group("statement") or "").strip()
    if current_grade is not None:
        if current_grade != problem_group:
            return False

        if state.current_problem_number is None or state.awaiting_new_problem:
            return True

        return bool(statement and int(problem_match.group("number")) > state.current_problem_number)

    if not statement:
        return False
    if state.current_problem_number is None or state.awaiting_new_problem:
        return True

    current_group = _current_dotted_problem_group(state)
    return (
        (current_group is not None and current_group != problem_group)
        or int(problem_match.group("number")) > state.current_problem_number
    )


def _can_start_alpha_problem(state: _StatementParseState) -> bool:
    return state.current_problem_number is None or state.awaiting_new_problem


def _can_start_keyword_numbered_problem(
    state: _StatementParseState,
    problem_match: re.Match[str],
) -> bool:
    if state.current_problem_number is None or state.awaiting_new_problem:
        return True

    statement = (problem_match.group("statement") or "").strip()
    if not statement:
        return False

    return int(problem_match.group("number")) == state.current_problem_number + 1


def _consume_header_or_problem_line(
    line: str,
    *,
    next_nonempty_line: str | None,
    following_nonempty_line: str | None,
    third_nonempty_line: str | None,
    state: _StatementParseState,
) -> bool:
    consumed = True
    if exam_day_label := _normalized_exam_day_label(line):
        _flush_problem(state)
        state.current_primary_section = exam_day_label.split(" · ", 1)[0]
        state.current_secondary_section = exam_day_label.split(" · ", 1)[1]
        state.current_day = exam_day_label
    elif day_label := _normalized_day_label(line):
        _flush_problem(state)
        if state.current_primary_section.startswith("TST #") or (
            state.current_primary_section
            and not state.current_primary_section.startswith("Day ")
            and (state.allows_day_subsection or bool(state.current_secondary_section))
        ):
            _set_day_subsection(state, day_label)
        else:
            _set_primary_section(state, day_label)
    elif tst_day_label := _normalized_tst_day_label(line):
        _flush_problem(state)
        _set_primary_section(state, tst_day_label)
    elif year_prefixed_section_label := _normalized_year_prefixed_section_label(
        line,
        contest_year=state.contest_year,
        next_nonempty_line=next_nonempty_line,
    ):
        _flush_problem(state)
        _set_primary_section(state, year_prefixed_section_label)
    elif year_suffixed_section_label := _normalized_year_suffixed_section_label(
        line,
        contest_year=state.contest_year,
        contest_name=state.contest_name,
        next_nonempty_line=next_nonempty_line,
    ):
        _flush_problem(state)
        _set_primary_section(state, year_suffixed_section_label)
    elif round_and_section_label := _normalized_round_and_section_label(line):
        _flush_problem(state)
        state.current_primary_section = round_and_section_label.split(" · ", 1)[0]
        state.current_secondary_section = round_and_section_label.split(" · ", 1)[1]
        state.current_day = round_and_section_label
    elif inline_season_level_label := _normalized_inline_season_level_label(line):
        _flush_problem(state)
        state.current_primary_section = inline_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = inline_season_level_label.split(" · ", 1)[1]
        state.current_day = inline_season_level_label
    elif hyphenated_season_level_label := _normalized_hyphenated_season_level_label(line):
        _flush_problem(state)
        state.current_primary_section = hyphenated_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = hyphenated_season_level_label.split(" · ", 1)[1]
        state.current_day = hyphenated_season_level_label
    elif yearless_hyphenated_season_level_label := _normalized_yearless_hyphenated_season_level_label(
        line,
        contest_year=state.contest_year,
    ):
        _flush_problem(state)
        state.current_primary_section = yearless_hyphenated_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = yearless_hyphenated_season_level_label.split(" · ", 1)[1]
        state.current_day = yearless_hyphenated_season_level_label
    elif yearless_season_level_label := _normalized_yearless_season_level_label(
        line,
        contest_year=state.contest_year,
    ):
        _flush_problem(state)
        state.current_primary_section = yearless_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = yearless_season_level_label.split(" · ", 1)[1]
        state.current_day = yearless_season_level_label
    elif round_prefixed_yearless_season_level_label := _normalized_round_prefixed_yearless_season_level_label(
        line,
        contest_year=state.contest_year,
    ):
        _flush_problem(state)
        state.current_primary_section = round_prefixed_yearless_season_level_label.split(" · ", 1)[0]
        state.current_secondary_section = round_prefixed_yearless_season_level_label.split(" · ", 1)[1]
        state.current_day = round_prefixed_yearless_season_level_label
    elif season_label := _normalized_season_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, season_label)
    elif division_label := _normalized_division_section_label(line):
        _flush_problem(state)
        _set_division_section(state, division_label)
    elif track_label := _normalized_track_section_label(line):
        _flush_problem(state)
        _set_track_section(state, track_label)
    elif grade_label := _normalized_grade_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, grade_label, allows_day_subsection=True)
    elif grade_level_label := _normalized_grade_level_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, grade_level_label, allows_day_subsection=True)
    elif round_match := ROUND_LABEL_RE.fullmatch(line):
        _flush_problem(state)
        _set_primary_section(state, round_match.group("label").title())
    elif part_label := _normalized_part_label(line):
        _flush_problem(state)
        _set_primary_section(state, part_label)
    elif test_label := _normalized_test_label(line):
        _flush_problem(state)
        if (
            (
                state.current_primary_section
                and not state.current_secondary_section
                and _normalized_test_label(state.current_primary_section) is None
                and _is_problem_start_candidate(next_nonempty_line)
            )
            or state.current_primary_section.startswith("Round ")
            or state.current_primary_section.startswith("TST #")
        ):
            _set_secondary_section(state, test_label)
        else:
            _set_primary_section(
                state,
                test_label,
                allows_day_subsection=(
                    DAY_LABEL_RE.fullmatch(" ".join((next_nonempty_line or "").split())) is not None
                ),
            )
    elif (
        state.current_primary_section
        and state.allows_section_date_metadata
        and not state.current_secondary_section
        and (section_date_label := _normalized_section_date_label(line))
        and (
            _is_problem_start_candidate(next_nonempty_line)
            or (
                _is_section_metadata_line(next_nonempty_line)
                and _is_problem_start_candidate(following_nonempty_line)
            )
        )
    ):
        _flush_problem(state)
        _set_secondary_section(state, section_date_label)
    elif level_label := _normalized_level_section_label(line):
        _flush_problem(state)
        _set_secondary_section(state, level_label)
    elif paper_label := _normalized_paper_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, paper_label)
    elif section_label := _normalized_section_label(line):
        _flush_problem(state)
        _set_primary_section(state, section_label)
    elif _is_generic_section_header(
        line,
        next_nonempty_line=next_nonempty_line,
        following_nonempty_line=following_nonempty_line,
        third_nonempty_line=third_nonempty_line,
    ):
        _flush_problem(state)
        generic_section_label = " ".join(line.split())
        if (
            state.current_primary_section
            and not state.current_secondary_section
            and " " in generic_section_label
            and _is_problem_start_candidate(next_nonempty_line)
            and not _is_structured_section_header(next_nonempty_line)
            and not _is_numbered_sibling_section(state.current_primary_section, generic_section_label)
            and not (
                _is_named_day_section_header(state.current_primary_section)
                and _is_named_day_section_header(generic_section_label)
            )
        ):
            _set_secondary_section(state, generic_section_label)
        else:
            _set_primary_section(
                state,
                generic_section_label,
                allows_section_date_metadata=(
                    SHORT_SECTION_HEADER_RE.fullmatch(generic_section_label) is None
                    or any(character.isdigit() for character in generic_section_label)
                ),
                allows_day_subsection=(
                    _supports_named_day_subsections(generic_section_label)
                    and DAY_LABEL_RE.fullmatch(" ".join((next_nonempty_line or "").split())) is not None
                ),
            )
    elif (
        (state.current_problem_number is None or state.awaiting_new_problem)
        and (special_problem_match := SPECIAL_PROBLEM_CODE_RE.match(line))
    ):
        _start_special_problem(state, special_problem_match)
    elif (keyword_problem_match := PROBLEM_KEYWORD_START_RE.match(line)) and _can_start_keyword_numbered_problem(
        state,
        keyword_problem_match,
    ):
        _start_keyword_numbered_problem(state, keyword_problem_match)
    elif (grade_problem_match := GRADE_PREFIXED_PROBLEM_START_RE.match(line)) and _can_start_grade_prefixed_problem(
        state,
        grade_problem_match,
    ):
        _start_grade_prefixed_problem(state, grade_problem_match)
    elif (alpha_problem_match := ALPHA_PROBLEM_CODE_RE.match(line)) and _can_start_alpha_problem(state):
        _start_alpha_problem(state, alpha_problem_match)
    elif (problem_match := PROBLEM_START_RE.match(line)) and _can_start_inline_numbered_problem(
        state,
        problem_match,
    ):
        _start_numbered_problem(state, problem_match)
    else:
        consumed = False
    return consumed


def _consume_statement_line(
    raw_line: str,
    *,
    next_nonempty_line: str | None,
    following_nonempty_line: str | None,
    third_nonempty_line: str | None,
    state: _StatementParseState,
) -> None:
    line = raw_line.strip()
    if not line:
        if state.current_problem_number is not None:
            state.current_statement_lines.append("")
        return

    if _is_scrape_metadata_line(
        line,
        next_nonempty_line=next_nonempty_line,
        following_nonempty_line=following_nonempty_line,
        third_nonempty_line=third_nonempty_line,
    ):
        if state.current_problem_number is not None:
            state.awaiting_new_problem = True
        return

    if _consume_header_or_problem_line(
        line,
        next_nonempty_line=next_nonempty_line,
        following_nonempty_line=following_nonempty_line,
        third_nonempty_line=third_nonempty_line,
        state=state,
    ):
        return

    if state.current_problem_number is not None:
        state.current_statement_lines.append(line)
        state.awaiting_new_problem = False


def parse_contest_problem_statements(raw_text: str) -> ParsedContestStatementImport:
    lines = _normalized_statement_lines(raw_text)
    contest_year, contest_name, remaining_lines = _parse_contest_header(lines)
    state = _StatementParseState(contest_year=contest_year, contest_name=contest_name)

    for index, raw_line in enumerate(remaining_lines):
        next_nonempty_lines = _next_nonempty_lines(remaining_lines, index, limit=3)
        _consume_statement_line(
            raw_line,
            next_nonempty_line=next_nonempty_lines[0] if next_nonempty_lines else None,
            following_nonempty_line=next_nonempty_lines[1] if len(next_nonempty_lines) > 1 else None,
            third_nonempty_line=next_nonempty_lines[2] if len(next_nonempty_lines) > 2 else None,
            state=state,
        )

    _flush_problem(state)

    if not state.parsed_problems:
        msg = "No numbered problems were detected in the pasted text."
        raise ProblemStatementImportValidationError(msg)

    parsed_problems = _promote_implicit_senior_sections(state.parsed_problems)

    return ParsedContestStatementImport(
        contest_year=contest_year,
        contest_name=contest_name,
        problems=tuple(parsed_problems),
    )


def _promote_implicit_senior_sections(
    parsed_problems: list[ParsedContestProblemStatement],
) -> list[ParsedContestProblemStatement]:
    primary_sections_with_explicit_junior = {
        label_parts[0]
        for problem in parsed_problems
        if problem.day_label
        for label_parts in [problem.day_label.split(" · ")]
        if len(label_parts) >= 2 and label_parts[1] == "Junior"
    }

    if not primary_sections_with_explicit_junior:
        return parsed_problems

    rewritten_problems: list[ParsedContestProblemStatement] = []
    for problem in parsed_problems:
        label_parts = [part for part in problem.day_label.split(" · ") if part]
        if (
            len(label_parts) >= 2
            and label_parts[0] in primary_sections_with_explicit_junior
            and not any(part in {"Junior", "Senior"} for part in label_parts[1:])
        ):
            label_parts.insert(1, "Senior")
            rewritten_problems.append(
                ParsedContestProblemStatement(
                    day_label=" · ".join(label_parts),
                    problem_code=problem.problem_code,
                    problem_number=problem.problem_number,
                    statement_latex=problem.statement_latex,
                ),
            )
            continue
        rewritten_problems.append(problem)
    return rewritten_problems


def _find_linked_problem(
    *,
    contest_year: int,
    contest_name: str,
    problem_code: str,
    problem_number: int,
) -> ProblemSolveRecord | None:
    linked_problem = ProblemSolveRecord.objects.filter(
        year=contest_year,
        contest=contest_name,
        problem__iexact=problem_code,
    ).first()
    if linked_problem is not None:
        return linked_problem
    if problem_code.upper() != f"P{problem_number}":
        return None
    return ProblemSolveRecord.objects.filter(
        year=contest_year,
        contest=contest_name,
        problem=str(problem_number),
    ).first()


def _problem_code_occurrences(
    parsed_import: ParsedContestStatementImport,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for problem in parsed_import.problems:
        counts[problem.problem_code] = counts.get(problem.problem_code, 0) + 1
    return counts


def _existing_statement_lookup(
    parsed_import: ParsedContestStatementImport,
) -> tuple[
    dict[tuple[str, str], ContestProblemStatement],
    dict[str, list[ContestProblemStatement]],
]:
    existing_rows = list(
        ContestProblemStatement.objects.filter(
            contest_year=parsed_import.contest_year,
            contest_name=parsed_import.contest_name,
            problem_code__in=[problem.problem_code for problem in parsed_import.problems],
        ),
    )
    existing_by_day_and_code = {
        (statement.day_label, statement.problem_code): statement
        for statement in existing_rows
    }
    existing_by_code: dict[str, list[ContestProblemStatement]] = {}
    for statement in existing_rows:
        existing_by_code.setdefault(statement.problem_code, []).append(statement)
    return existing_by_day_and_code, existing_by_code


def _find_existing_statement(
    *,
    day_label: str,
    problem_code: str,
    problem_code_counts: dict[str, int],
    existing_by_day_and_code: dict[tuple[str, str], ContestProblemStatement],
    existing_by_code: dict[str, list[ContestProblemStatement]],
) -> ContestProblemStatement | None:
    exact_match = existing_by_day_and_code.get((day_label, problem_code))
    if exact_match is not None or problem_code_counts[problem_code] != 1:
        return exact_match

    fallback_matches = existing_by_code.get(problem_code, [])
    if len(fallback_matches) == 1:
        return fallback_matches[0]
    return None


def build_problem_statement_preview_payload(
    parsed_import: ParsedContestStatementImport,
) -> ProblemStatementPreviewPayload:
    day_counts: dict[str, int] = {}
    problem_rows: list[PreviewProblemRow] = []
    problem_code_counts = _problem_code_occurrences(parsed_import)

    for parsed_problem in parsed_import.problems:
        day_key = parsed_problem.day_label or "Unlabeled"
        day_counts[day_key] = day_counts.get(day_key, 0) + 1
        linked_problem = None
        if problem_code_counts[parsed_problem.problem_code] == 1:
            linked_problem = _find_linked_problem(
                contest_year=parsed_import.contest_year,
                contest_name=parsed_import.contest_name,
                problem_code=parsed_problem.problem_code,
                problem_number=parsed_problem.problem_number,
            )
        problem_rows.append(
            {
                "contest_year_problem": (
                    f"{parsed_import.contest_name} {parsed_import.contest_year} {parsed_problem.problem_code}"
                ),
                "day_label": parsed_problem.day_label or "Unlabeled",
                "problem_code": parsed_problem.problem_code,
                "problem_number": parsed_problem.problem_number,
                "statement_latex": parsed_problem.statement_latex,
                "linked_problem_label": (
                    linked_problem.contest_year_problem or ""
                    if linked_problem
                    else ""
                ),
            },
        )

    day_rows: list[PreviewDayRow] = [
        {"label": label, "problem_count": count}
        for label, count in day_counts.items()
    ]

    return {
        "contest_name": parsed_import.contest_name,
        "contest_year": parsed_import.contest_year,
        "day_rows": day_rows,
        "problem_count": len(problem_rows),
        "problems": problem_rows,
    }


def build_problem_statement_save_preview(
    parsed_import: ParsedContestStatementImport,
) -> ProblemStatementSavePreviewPayload:
    problem_code_counts = _problem_code_occurrences(parsed_import)
    existing_by_day_and_code, existing_by_code = _existing_statement_lookup(parsed_import)

    create_count = 0
    update_count = 0
    unchanged_count = 0
    existing_problem_codes: list[str] = []
    update_problem_codes: list[str] = []
    unchanged_problem_codes: list[str] = []

    for parsed_problem in parsed_import.problems:
        existing_statement = _find_existing_statement(
            day_label=parsed_problem.day_label,
            problem_code=parsed_problem.problem_code,
            problem_code_counts=problem_code_counts,
            existing_by_day_and_code=existing_by_day_and_code,
            existing_by_code=existing_by_code,
        )
        if existing_statement is None:
            create_count += 1
            continue

        existing_problem_codes.append(parsed_problem.problem_code)
        linked_problem = None
        if problem_code_counts[parsed_problem.problem_code] == 1:
            linked_problem = _find_linked_problem(
                contest_year=parsed_import.contest_year,
                contest_name=parsed_import.contest_name,
                problem_code=parsed_problem.problem_code,
                problem_number=parsed_problem.problem_number,
            )
        linked_problem_id = linked_problem.id if linked_problem is not None else None
        is_unchanged = (
            existing_statement.day_label == parsed_problem.day_label
            and existing_statement.statement_latex == parsed_problem.statement_latex
            and existing_statement.linked_problem_id == linked_problem_id
        )
        if is_unchanged:
            unchanged_count += 1
            unchanged_problem_codes.append(parsed_problem.problem_code)
        else:
            update_count += 1
            update_problem_codes.append(parsed_problem.problem_code)

    return {
        "create_count": create_count,
        "update_count": update_count,
        "unchanged_count": unchanged_count,
        "existing_count": len(existing_problem_codes),
        "existing_problem_codes": existing_problem_codes,
        "update_problem_codes": update_problem_codes,
        "unchanged_problem_codes": unchanged_problem_codes,
    }


@transaction.atomic
def import_problem_statements(
    parsed_import: ParsedContestStatementImport,
) -> ProblemStatementImportResult:
    created_count = 0
    updated_count = 0
    linked_problem_count = 0
    problem_code_counts = _problem_code_occurrences(parsed_import)
    existing_by_day_and_code, existing_by_code = _existing_statement_lookup(parsed_import)

    for parsed_problem in parsed_import.problems:
        linked_problem = None
        if problem_code_counts[parsed_problem.problem_code] == 1:
            linked_problem = _find_linked_problem(
                contest_year=parsed_import.contest_year,
                contest_name=parsed_import.contest_name,
                problem_code=parsed_problem.problem_code,
                problem_number=parsed_problem.problem_number,
            )
        statement_entry = _find_existing_statement(
            day_label=parsed_problem.day_label,
            problem_code=parsed_problem.problem_code,
            problem_code_counts=problem_code_counts,
            existing_by_day_and_code=existing_by_day_and_code,
            existing_by_code=existing_by_code,
        )
        if statement_entry is None:
            statement_entry = ContestProblemStatement.objects.create(
                contest_year=parsed_import.contest_year,
                contest_name=parsed_import.contest_name,
                day_label=parsed_problem.day_label,
                linked_problem=linked_problem,
                problem_number=parsed_problem.problem_number,
                problem_code=parsed_problem.problem_code,
                statement_latex=parsed_problem.statement_latex,
            )
            existing_by_day_and_code[(statement_entry.day_label, statement_entry.problem_code)] = statement_entry
            existing_by_code.setdefault(statement_entry.problem_code, []).append(statement_entry)
            created_count += 1
        else:
            previous_key = (statement_entry.day_label, statement_entry.problem_code)
            statement_entry.day_label = parsed_problem.day_label
            statement_entry.linked_problem = linked_problem
            statement_entry.problem_number = parsed_problem.problem_number
            statement_entry.problem_code = parsed_problem.problem_code
            statement_entry.statement_latex = parsed_problem.statement_latex
            statement_entry.save()
            if previous_key != (statement_entry.day_label, statement_entry.problem_code):
                existing_by_day_and_code.pop(previous_key, None)
                existing_by_day_and_code[(statement_entry.day_label, statement_entry.problem_code)] = statement_entry
            updated_count += 1

        if statement_entry.linked_problem_id is not None:
            statement_entry.refresh_from_db()
            sync_statement_analytics_from_linked_problem(statement_entry)
            linked_problem_count += 1

    return ProblemStatementImportResult(
        created_count=created_count,
        updated_count=updated_count,
        linked_problem_count=linked_problem_count,
    )


@transaction.atomic
def relink_problem_statement_rows() -> ProblemStatementRelinkResult:
    checked_count = 0
    linked_count = 0
    newly_linked_count = 0
    skipped_count = 0
    unlinked_count = 0
    updated_count = 0
    statements = list(ContestProblemStatement.objects.select_related("linked_problem").order_by("id"))
    problem_code_counts: dict[tuple[int, str, str], int] = {}
    claimed_problem_uuids = {
        statement.problem_uuid: statement.id
        for statement in statements
    }

    for statement in statements:
        code_key = (
            statement.contest_year,
            statement.contest_name,
            statement.problem_code,
        )
        problem_code_counts[code_key] = problem_code_counts.get(code_key, 0) + 1

    for statement in statements:
        code_key = (
            statement.contest_year,
            statement.contest_name,
            statement.problem_code,
        )
        if problem_code_counts[code_key] != 1:
            skipped_count += 1
            checked_count += 1
            if statement.linked_problem_id is not None:
                linked_count += 1
            else:
                unlinked_count += 1
            continue

        linked_problem = _find_linked_problem(
            contest_year=statement.contest_year,
            contest_name=statement.contest_name,
            problem_code=statement.problem_code,
            problem_number=statement.problem_number,
        )
        previous_linked_problem_id = statement.linked_problem_id
        next_linked_problem_id = linked_problem.id if linked_problem is not None else None
        previous_problem_uuid = statement.problem_uuid

        if linked_problem is not None:
            conflicting_statement_id = claimed_problem_uuids.get(linked_problem.problem_uuid)
            if conflicting_statement_id not in (None, statement.id):
                skipped_count += 1
                checked_count += 1
                if statement.linked_problem_id is not None:
                    linked_count += 1
                else:
                    unlinked_count += 1
                continue

        if previous_linked_problem_id != next_linked_problem_id:
            statement.linked_problem = linked_problem
            statement.save(update_fields={"linked_problem", "updated_at"})
            updated_count += 1
            if previous_linked_problem_id is None and next_linked_problem_id is not None:
                newly_linked_count += 1
            claimed_problem_uuids.pop(previous_problem_uuid, None)
            claimed_problem_uuids[statement.problem_uuid] = statement.id
            if statement.linked_problem_id is not None:
                statement.refresh_from_db()
                sync_statement_analytics_from_linked_problem(statement)

        checked_count += 1
        if statement.linked_problem_id is not None:
            linked_count += 1
        else:
            unlinked_count += 1

    return ProblemStatementRelinkResult(
        checked_count=checked_count,
        linked_count=linked_count,
        newly_linked_count=newly_linked_count,
        skipped_count=skipped_count,
        unlinked_count=unlinked_count,
        updated_count=updated_count,
    )
