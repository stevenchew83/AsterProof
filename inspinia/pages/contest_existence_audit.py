from __future__ import annotations

import csv
import json
import re
import urllib.error
from collections import OrderedDict
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from html.parser import HTMLParser
from io import StringIO
from typing import TypedDict
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen

from django.db.models import Count

from inspinia.pages.contest_names import normalize_contest_name
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests.exceptions import RequestException as CurlRequestException
except ImportError:  # pragma: no cover - dependency is optional at runtime.
    curl_requests = None
    CURL_REQUEST_EXCEPTIONS = ()
else:
    CURL_REQUEST_EXCEPTIONS = (CurlRequestException,)


class ContestExistenceAuditValidationError(ValueError):
    """Raised when pasted contest-audit text cannot be parsed."""


@dataclass(frozen=True)
class ParsedContestHeader:
    year: int
    contest_name: str
    first_line_number: int
    occurrence_count: int


class ContestExistenceAuditRow(TypedDict):
    analytics_count: int
    analytics_status: str
    contest_name: str
    first_line_number: int
    occurrence_count: int
    overall_status: str
    statement_count: int
    statement_status: str
    suggestions: list[str]
    suggestions_label: str
    year: int


class ContestExistenceAuditPayload(TypedDict):
    export_tsv: str
    row_count: int
    rows: list[ContestExistenceAuditRow]
    summary: dict[str, int]


YEAR_HEADER_RE = re.compile(r"^(?P<year>\d{4})\s+(?P<title>.+?)\s*$")
TRAILING_YEAR_RE = re.compile(r"\s+\d{4}\s*$")
EMBEDDED_YEAR_SUBTITLE_RE = re.compile(r"^(?P<title>.+\S)\d{4}\s+.+$")
GLUED_ACRONYM_SUBTITLE_RE = re.compile(r"^(?P<title>[A-Z]{2,8})(?=[A-Z][a-z])")
GLUED_TERMINAL_SUBTITLE_RE = re.compile(
    r"^(?P<title>.+?(?:Mathematics|Olympi.d|Competition|Round|Tests?|TSTST|TST(?!ST)|MO))(?=[A-Z0-9'])",
)
GENERIC_HEADER_WORDS = {"contest", "contests"}
SUGGESTION_LIMIT = 3
SUGGESTION_MIN_RATIO = 0.35
SOURCE_FETCH_BYTE_LIMIT = 2_000_000
SOURCE_FETCH_TIMEOUT_SECONDS = 20
HTTP_ERROR_STATUS_FLOOR = 400
ALLOWED_AOPS_HOST_SUFFIX = "artofproblemsolving.com"
AOPS_AJAX_URL = "https://artofproblemsolving.com/m/community/ajax.php"
AOPS_MAX_FOLDER_PAGE_FETCHES = 100
AOPS_INCOMPLETE_RENDERED_TEXT = "Something appears to not have loaded correctly"
AOPS_BROWSER_IMPERSONATION = "safari17_0"
AOPS_SESSION_RE = re.compile(r"AoPS\.session\s*=\s*(?P<session>\{.*?\});", flags=re.DOTALL)
READER_FALLBACK_PREFIX = "https://r.jina.ai/"
READER_FALLBACK_HTTP_STATUSES = {403, 429}
HTML_CONTENT_TYPE_RE = re.compile(r"\bhtml\b", flags=re.IGNORECASE)
CHARSET_RE = re.compile(r"charset=([A-Za-z0-9._-]+)", flags=re.IGNORECASE)
AOPS_COMMUNITY_TITLE_RE = re.compile(r"^AoPS Community\s+(?P<title>\d{4}\s+.+)$", flags=re.IGNORECASE)
AOPS_DOUBLED_FIELD_YEAR_RE = re.compile(r"^\s*(?P<title>\d{4}\s+.+?)\s{2,}.+$")
AOPS_ICON_PREFIXED_YEAR_RE = re.compile(r"^(?:x|8)\s+(?P<title>\d{4}\s+.+)$", flags=re.IGNORECASE)
AOPS_COMMUNITY_CATEGORY_ID_RE = re.compile(r"/community/c(?P<category_id>\d+)")


class _AuditSourceHtmlTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "a",
        "article",
        "body",
        "br",
        "dd",
        "div",
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
        "li",
        "main",
        "p",
        "section",
        "td",
        "th",
        "title",
        "tr",
    }
    _SKIP_TAGS = {"script", "style", "svg", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._current_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in self._BLOCK_TAGS:
            self._flush_current_line()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in self._BLOCK_TAGS:
            self._flush_current_line()

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = _collapse_whitespace(unescape(data))
        if text:
            self._current_parts.append(text)

    def close(self):
        super().close()
        self._flush_current_line()

    def _flush_current_line(self):
        line = _collapse_whitespace(" ".join(self._current_parts))
        self._current_parts = []
        if line:
            self.lines.append(line)


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def _validate_aops_source_url(source_url: str) -> str:
    url = source_url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        msg = "Enter a full AoPS URL beginning with https://."
        raise ContestExistenceAuditValidationError(msg)

    hostname = parsed.hostname or ""
    if hostname != ALLOWED_AOPS_HOST_SUFFIX and not hostname.endswith(f".{ALLOWED_AOPS_HOST_SUFFIX}"):
        msg = "Contest audit URL must be on artofproblemsolving.com."
        raise ContestExistenceAuditValidationError(msg)

    if not parsed.path.startswith(("/community/", "/downloads/")):
        msg = "Enter an AoPS community or downloads URL."
        raise ContestExistenceAuditValidationError(msg)

    return url


def _decode_source_document(raw_content: bytes, content_type: str) -> str:
    charset_match = CHARSET_RE.search(content_type)
    encodings = [charset_match.group(1)] if charset_match else []
    encodings.extend(["utf-8", "latin-1"])

    for encoding in encodings:
        try:
            return raw_content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_content.decode("utf-8", errors="replace")


def _expand_aops_source_lines(raw_lines: list[str]) -> list[str]:
    lines: list[str] = []
    for raw_line in raw_lines:
        doubled_field_year_match = AOPS_DOUBLED_FIELD_YEAR_RE.match(raw_line)
        if doubled_field_year_match:
            lines.append(_collapse_whitespace(doubled_field_year_match.group("title")))
            continue

        line = _collapse_whitespace(raw_line)
        if not line:
            continue
        community_title_match = AOPS_COMMUNITY_TITLE_RE.match(line)
        if community_title_match:
            lines.append(community_title_match.group("title"))
        icon_prefixed_year_match = AOPS_ICON_PREFIXED_YEAR_RE.match(line)
        if icon_prefixed_year_match:
            lines.append(icon_prefixed_year_match.group("title"))
        lines.append(line)
    return lines


def _html_to_source_text(document: str) -> str:
    parser = _AuditSourceHtmlTextParser()
    parser.feed(document)
    parser.close()

    return "\n".join(_expand_aops_source_lines(parser.lines))


def _plain_to_source_text(document: str) -> str:
    return "\n".join(_expand_aops_source_lines(document.splitlines()))


def _read_source_response(
    fetch_url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[str, bytes]:
    request_headers = {
        "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8",
        "User-Agent": "AsterProof contest existence audit",
    }
    if headers:
        request_headers.update(headers)
    request = Request(  # noqa: S310
        fetch_url,
        data=data,
        headers=request_headers,
    )
    with urlopen(request, timeout=SOURCE_FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
        content_type = response.headers.get("Content-Type", "")
        raw_content = response.read(SOURCE_FETCH_BYTE_LIMIT + 1)
    return content_type, raw_content


def _read_browser_source_response(
    browser_session,
    fetch_url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[str, bytes]:
    request_headers = {
        "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8",
        "User-Agent": "AsterProof contest existence audit",
    }
    if headers:
        request_headers.update(headers)

    if data is None:
        response = browser_session.get(fetch_url, headers=request_headers, timeout=SOURCE_FETCH_TIMEOUT_SECONDS)
    else:
        response = browser_session.post(
            fetch_url,
            data=data,
            headers=request_headers,
            timeout=SOURCE_FETCH_TIMEOUT_SECONDS,
        )

    if response.status_code >= HTTP_ERROR_STATUS_FLOOR:
        msg = f"AoPS returned HTTP {response.status_code} while loading paginated contest data."
        raise ContestExistenceAuditValidationError(msg)

    return response.headers.get("Content-Type", ""), response.content[: SOURCE_FETCH_BYTE_LIMIT + 1]


def _aops_community_category_id(source_url: str) -> int | None:
    match = AOPS_COMMUNITY_CATEGORY_ID_RE.search(urlparse(source_url).path)
    if match is None:
        return None
    return int(match.group("category_id"))


def _aops_session_request_params(document: str) -> dict[str, str]:
    match = AOPS_SESSION_RE.search(document)
    if match is None:
        return {}

    try:
        session_data = json.loads(match.group("session"))
    except json.JSONDecodeError:
        return {}

    if not isinstance(session_data, dict):
        return {}

    session_id = _collapse_whitespace(str(session_data.get("id", "")))
    if not session_id:
        return {}

    return {
        "aops_logged_in": "true" if session_data.get("logged_in") else "false",
        "aops_session_id": session_id,
        "aops_user_id": str(session_data.get("user_id") or 1),
    }


def _fetch_aops_browser_session(source_url: str) -> tuple[object, dict[str, str]] | None:
    if curl_requests is None:
        return None

    browser_session = curl_requests.Session(impersonate=AOPS_BROWSER_IMPERSONATION)
    content_type, raw_content = _read_browser_source_response(browser_session, source_url)
    if len(raw_content) > SOURCE_FETCH_BYTE_LIMIT:
        return None

    document = _decode_source_document(raw_content, content_type)
    session_params = _aops_session_request_params(document)
    if not session_params:
        return None

    return browser_session, session_params


def _fetch_aops_ajax_response(
    action: str,
    params: dict[str, str | int],
    *,
    browser_session=None,
    referer: str = "https://artofproblemsolving.com/community",
    session_params: dict[str, str] | None = None,
) -> dict:
    form_data = {"a": action}
    form_data.update({key: str(value) for key, value in params.items()})
    if session_params:
        form_data.update(session_params)

    request_kwargs = {
        "data": urlencode(form_data).encode(),
        "headers": {
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
        },
    }
    if browser_session is None:
        content_type, raw_content = _read_source_response(AOPS_AJAX_URL, **request_kwargs)
    else:
        content_type, raw_content = _read_browser_source_response(browser_session, AOPS_AJAX_URL, **request_kwargs)

    if len(raw_content) > SOURCE_FETCH_BYTE_LIMIT:
        msg = "The AoPS paginated response is too large to audit in one request."
        raise ContestExistenceAuditValidationError(msg)

    payload = json.loads(_decode_source_document(raw_content, content_type))
    if not isinstance(payload, dict) or payload.get("error_code"):
        msg = "AoPS did not return usable paginated contest data."
        raise ContestExistenceAuditValidationError(msg)

    response = payload.get("response", {})
    if not isinstance(response, dict):
        msg = "AoPS returned malformed paginated contest data."
        raise ContestExistenceAuditValidationError(msg)
    return response


def _aops_year_prefixed_item_lines(items: list) -> list[str]:
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_text = _collapse_whitespace(str(item.get("item_text", "")))
        if YEAR_HEADER_RE.match(item_text):
            lines.append(item_text)
    return lines


def _source_text_from_aops_category_response(
    category_id: int,
    response: dict,
    *,
    browser_session=None,
    referer: str = "https://artofproblemsolving.com/community",
    session_params: dict[str, str] | None = None,
) -> str:
    category = response.get("category")
    items = category.get("items", []) if isinstance(category, dict) else []
    if not isinstance(category, dict) or not isinstance(items, list):
        return ""

    items = [*items]
    if category.get("category_type") == "folder":
        no_more_items = bool(category.get("no_more_items"))
        page_fetches = 0
        while not no_more_items and page_fetches < AOPS_MAX_FOLDER_PAGE_FETCHES:
            next_response = _fetch_aops_ajax_response(
                "fetch_items_categories",
                {
                    "log_visit": 0,
                    "parent_category_id": category_id,
                    "seek_items": 1,
                    "sought_category_ids": "[]",
                    "start_num": len(items),
                },
                browser_session=browser_session,
                referer=referer,
                session_params=session_params,
            )
            next_items = next_response.get("new_items", next_response.get("items", []))
            if not isinstance(next_items, list):
                items = []
                break
            items.extend(next_items)
            no_more_items = bool(next_response.get("no_more_items")) or not next_items
            page_fetches += 1
        if not no_more_items:
            items = []

    return "\n".join(_aops_year_prefixed_item_lines(items))


def _fetch_aops_paginated_category_source_text(source_url: str) -> str:
    category_id = _aops_community_category_id(source_url)
    if category_id is None:
        return ""

    try:
        response = _fetch_aops_ajax_response("fetch_category_data", {"category_id": category_id})
        return _source_text_from_aops_category_response(category_id, response)
    except (
        ContestExistenceAuditValidationError,
        TimeoutError,
        OSError,
        TypeError,
        ValueError,
        urllib.error.URLError,
    ):
        pass

    try:
        browser_context = _fetch_aops_browser_session(source_url)
        if browser_context is None:
            return ""
        browser_session, session_params = browser_context
        response = _fetch_aops_ajax_response(
            "fetch_category_data",
            {"category_id": category_id},
            browser_session=browser_session,
            referer=source_url,
            session_params=session_params,
        )
        return _source_text_from_aops_category_response(
            category_id,
            response,
            browser_session=browser_session,
            referer=source_url,
            session_params=session_params,
        )
    except (
        *CURL_REQUEST_EXCEPTIONS,
        ContestExistenceAuditValidationError,
        TimeoutError,
        OSError,
        TypeError,
        ValueError,
        urllib.error.URLError,
    ):
        return ""


def _reader_fallback_url(validated_url: str) -> str:
    return f"{READER_FALLBACK_PREFIX}{validated_url}"


def _fetch_source_response(validated_url: str) -> tuple[str, bytes]:
    try:
        return _read_source_response(validated_url)
    except urllib.error.HTTPError as exc:
        if exc.code not in READER_FALLBACK_HTTP_STATUSES:
            msg = f"Could not fetch the AoPS URL. AoPS returned HTTP {exc.code}."
            raise ContestExistenceAuditValidationError(msg) from exc
        try:
            return _read_source_response(_reader_fallback_url(validated_url))
        except (TimeoutError, OSError, ValueError, urllib.error.URLError) as fallback_exc:
            msg = (
                f"Could not fetch the AoPS URL directly (HTTP {exc.code}) or through "
                "the reader fallback. Try again later, or open the AoPS page in a browser."
            )
            raise ContestExistenceAuditValidationError(msg) from fallback_exc
    except (TimeoutError, OSError, ValueError, urllib.error.URLError) as exc:
        msg = "Could not fetch the AoPS URL. Check that the page is reachable and try again."
        raise ContestExistenceAuditValidationError(msg) from exc


def _reject_incomplete_aops_rendered_source(source_url: str, source_text: str) -> None:
    if _aops_community_category_id(source_url) is None or AOPS_INCOMPLETE_RENDERED_TEXT not in source_text:
        return

    msg = (
        "Could not load all AoPS contest entries. AoPS blocked its paginated category data, "
        "and the rendered fallback only exposed the first batch."
    )
    raise ContestExistenceAuditValidationError(msg)


def fetch_contest_existence_audit_source_text(source_url: str) -> str:
    validated_url = _validate_aops_source_url(source_url)

    paginated_source_text = _fetch_aops_paginated_category_source_text(validated_url)
    if paginated_source_text.strip():
        return paginated_source_text

    content_type, raw_content = _fetch_source_response(validated_url)
    if len(raw_content) > SOURCE_FETCH_BYTE_LIMIT:
        msg = "The AoPS page is too large to audit in one request."
        raise ContestExistenceAuditValidationError(msg)
    if not raw_content.strip():
        msg = "The AoPS URL returned an empty response."
        raise ContestExistenceAuditValidationError(msg)

    document = _decode_source_document(raw_content, content_type)
    if HTML_CONTENT_TYPE_RE.search(content_type) or "<html" in document[:500].lower():
        source_text = _html_to_source_text(document)
    else:
        source_text = _plain_to_source_text(document)
    _reject_incomplete_aops_rendered_source(validated_url, source_text)
    return source_text


def _is_generic_header(title: str) -> bool:
    letters_only = re.sub(r"[^a-z]", "", title.lower())
    return letters_only in GENERIC_HEADER_WORDS


def _title_compare_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", TRAILING_YEAR_RE.sub("", title).lower())


def _dedupe_concatenated_title(title: str) -> str:
    for split_index in range(1, len(title)):
        prefix = title[:split_index].strip(" '\"-")
        suffix = title[split_index:].strip(" '\"-")
        if not prefix or not suffix:
            continue
        if _title_compare_key(suffix) == _title_compare_key(prefix):
            return prefix
        if re.fullmatch(rf"\d{{4}}\s*{re.escape(prefix)}", suffix):
            return prefix
    return title


def _strip_repeated_leading_phrase(title: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", title)
    if not words:
        return title

    leading_phrase = " ".join(words[: min(3, len(words))])
    search_start = len(leading_phrase)
    repeat_index = title.find(leading_phrase, search_start)
    if repeat_index == -1:
        return title

    return title[:repeat_index].strip(" '\"-")


def _strip_glued_aops_subtitle(title: str) -> str:
    embedded_year_match = EMBEDDED_YEAR_SUBTITLE_RE.match(title)
    if embedded_year_match:
        return embedded_year_match.group("title").strip(" '\"-")

    acronym_match = GLUED_ACRONYM_SUBTITLE_RE.match(title)
    if acronym_match:
        return acronym_match.group("title")

    repeated_title = _strip_repeated_leading_phrase(title)
    if repeated_title != title:
        return repeated_title

    terminal_match = GLUED_TERMINAL_SUBTITLE_RE.match(title)
    if terminal_match:
        return terminal_match.group("title").strip(" '\"-")

    return title


def _clean_parsed_contest_name(raw_title: str) -> str:
    title = _collapse_whitespace(raw_title)
    title = _strip_glued_aops_subtitle(title)
    title = TRAILING_YEAR_RE.sub("", title).strip()
    title = _dedupe_concatenated_title(title)
    title = _strip_glued_aops_subtitle(title)
    return normalize_contest_name(title)


def parse_contest_existence_audit_text(raw_text: str) -> tuple[ParsedContestHeader, ...]:
    if not raw_text.strip():
        msg = "Paste contest text before checking."
        raise ContestExistenceAuditValidationError(msg)

    headers_by_key: OrderedDict[tuple[int, str], dict[str, int | str]] = OrderedDict()
    skipped_year_lines = 0
    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.lstrip()
        match = YEAR_HEADER_RE.match(line)
        if match is None:
            continue

        raw_title = match.group("title")
        if _is_generic_header(raw_title):
            skipped_year_lines += 1
            continue

        contest_name = _clean_parsed_contest_name(raw_title)
        if not contest_name or _is_generic_header(contest_name):
            skipped_year_lines += 1
            continue

        key = (int(match.group("year")), contest_name)
        if key not in headers_by_key:
            headers_by_key[key] = {
                "contest_name": contest_name,
                "first_line_number": line_number,
                "occurrence_count": 0,
                "year": key[0],
            }
        headers_by_key[key]["occurrence_count"] = int(headers_by_key[key]["occurrence_count"]) + 1

    if not headers_by_key:
        if skipped_year_lines:
            msg = "Only generic year headings were detected; paste contest header lines such as '2026 USAMO'."
            raise ContestExistenceAuditValidationError(msg)
        msg = "No year-prefixed contest headers were detected."
        raise ContestExistenceAuditValidationError(msg)

    return tuple(
        ParsedContestHeader(
            year=int(row["year"]),
            contest_name=str(row["contest_name"]),
            first_line_number=int(row["first_line_number"]),
            occurrence_count=int(row["occurrence_count"]),
        )
        for row in headers_by_key.values()
    )


def _statement_counts_by_key() -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    rows = (
        ContestProblemStatement.objects.values("contest_year", "contest_name")
        .annotate(row_count=Count("id"))
        .order_by("contest_year", "contest_name")
    )
    for row in rows:
        key = (int(row["contest_year"]), normalize_contest_name(str(row["contest_name"])))
        counts[key] = counts.get(key, 0) + int(row["row_count"])
    return counts


def _analytics_counts_by_key() -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    rows = (
        ProblemSolveRecord.objects.values("year", "contest")
        .annotate(row_count=Count("id"))
        .order_by("year", "contest")
    )
    for row in rows:
        key = (int(row["year"]), normalize_contest_name(str(row["contest"])))
        counts[key] = counts.get(key, 0) + int(row["row_count"])
    return counts


def _contest_names_by_year(
    statement_counts: dict[tuple[int, str], int],
    analytics_counts: dict[tuple[int, str], int],
) -> dict[int, list[str]]:
    names_by_year: dict[int, set[str]] = defaultdict(set)
    for year, contest_name in list(statement_counts) + list(analytics_counts):
        names_by_year[year].add(contest_name)
    return {year: sorted(contest_names) for year, contest_names in names_by_year.items()}


def _status_for_counts(statement_count: int, analytics_count: int) -> str:
    if statement_count and analytics_count:
        return "both_found"
    if statement_count:
        return "statements_only"
    if analytics_count:
        return "analytics_only"
    return "missing"


def _suggest_contests(*, contest_name: str, year: int, names_by_year: dict[int, list[str]]) -> list[str]:
    scored_names: list[tuple[float, str]] = []
    needle = contest_name.lower()
    for candidate in names_by_year.get(year, []):
        if candidate == contest_name:
            continue
        ratio = SequenceMatcher(None, needle, candidate.lower()).ratio()
        if ratio >= SUGGESTION_MIN_RATIO:
            scored_names.append((ratio, candidate))
    scored_names.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _ratio, candidate in scored_names[:SUGGESTION_LIMIT]]


def _build_export_tsv(rows: list[ContestExistenceAuditRow]) -> str:
    output = StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(
        [
            "LINE",
            "YEAR",
            "CONTEST",
            "OCCURRENCES",
            "STATEMENT STATUS",
            "STATEMENT COUNT",
            "ANALYTICS STATUS",
            "ANALYTICS COUNT",
            "OVERALL STATUS",
            "SUGGESTIONS",
        ],
    )
    for row in rows:
        writer.writerow(
            [
                row["first_line_number"],
                row["year"],
                row["contest_name"],
                row["occurrence_count"],
                row["statement_status"],
                row["statement_count"],
                row["analytics_status"],
                row["analytics_count"],
                row["overall_status"],
                row["suggestions_label"],
            ],
        )
    return output.getvalue().rstrip("\n")


def build_contest_existence_audit_payload(
    parsed_headers: tuple[ParsedContestHeader, ...],
) -> ContestExistenceAuditPayload:
    statement_counts = _statement_counts_by_key()
    analytics_counts = _analytics_counts_by_key()
    names_by_year = _contest_names_by_year(statement_counts, analytics_counts)
    rows: list[ContestExistenceAuditRow] = []
    summary = {
        "analytics_only_total": 0,
        "both_found_total": 0,
        "missing_total": 0,
        "partial_total": 0,
        "parsed_total": len(parsed_headers),
        "statements_only_total": 0,
    }

    for header in parsed_headers:
        key = (header.year, normalize_contest_name(header.contest_name))
        statement_count = statement_counts.get(key, 0)
        analytics_count = analytics_counts.get(key, 0)
        overall_status = _status_for_counts(statement_count, analytics_count)
        statement_status = "found" if statement_count else "missing"
        analytics_status = "found" if analytics_count else "missing"
        suggestions = (
            []
            if overall_status == "both_found"
            else _suggest_contests(
                contest_name=header.contest_name,
                year=header.year,
                names_by_year=names_by_year,
            )
        )

        if overall_status == "both_found":
            summary["both_found_total"] += 1
        elif overall_status == "statements_only":
            summary["statements_only_total"] += 1
            summary["partial_total"] += 1
        elif overall_status == "analytics_only":
            summary["analytics_only_total"] += 1
            summary["partial_total"] += 1
        else:
            summary["missing_total"] += 1

        rows.append(
            {
                "analytics_count": analytics_count,
                "analytics_status": analytics_status,
                "contest_name": header.contest_name,
                "first_line_number": header.first_line_number,
                "occurrence_count": header.occurrence_count,
                "overall_status": overall_status,
                "statement_count": statement_count,
                "statement_status": statement_status,
                "suggestions": suggestions,
                "suggestions_label": ", ".join(suggestions),
                "year": header.year,
            },
        )

    return {
        "export_tsv": _build_export_tsv(rows),
        "row_count": len(rows),
        "rows": rows,
        "summary": summary,
    }
