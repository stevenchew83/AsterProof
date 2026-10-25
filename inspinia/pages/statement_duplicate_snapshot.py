"""Refresh duplicate reports off-request, using a disk-backed comparison index."""

import bisect
import fcntl
import hashlib
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
from contextlib import closing
from contextlib import contextmanager
from datetime import timedelta
from difflib import SequenceMatcher
from pathlib import Path
from time import monotonic

from django.core.cache import cache
from django.db.models import Count
from django.db.models import Exists
from django.db.models import Max
from django.db.models import OuterRef
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inspinia.pages.contest_links import contest_dashboard_problem_url
from inspinia.pages.models import ContestProblemStatement
from inspinia.pages.models import ProblemSolveRecord
from inspinia.pages.statement_duplicates import SIMILARITY_MAX_BUCKET_SIZE
from inspinia.pages.statement_duplicates import SIMILARITY_MAX_LENGTH_DELTA_RATIO
from inspinia.pages.statement_duplicates import SIMILARITY_MIN_CHAR_COUNT
from inspinia.pages.statement_duplicates import SIMILARITY_MIN_SHARED_SHINGLES
from inspinia.pages.statement_duplicates import SIMILARITY_MIN_TOKEN_COUNT
from inspinia.pages.statement_duplicates import SIMILARITY_THRESHOLD
from inspinia.pages.statement_duplicates import _normalize_similarity_text
from inspinia.pages.statement_duplicates import _similarity_shingles
from inspinia.pages.statement_duplicates import _statement_preview
from inspinia.pages.statement_duplicates import normalize_exact_statement_text

MANIFEST_KEY = "statement-duplicates:snapshot:v1"
PAGE_SIZE = 25
SIMILAR_LIMIT = 250
CACHE_TIMEOUT = 3 * 60 * 60
MAX_AGE = timedelta(hours=1)
GROUP_KEY_LENGTH = 64
MIN_START_FREE_BYTES = 1024 * 1024 * 1024
RESERVED_FREE_BYTES = 512 * 1024 * 1024
DEFAULT_BUILD_SECONDS = 20 * 60
SCRATCH_MODE = 0o700


def source_signature():
    state = ContestProblemStatement.objects.aggregate(count=Count("pk"), latest=Max("updated_at"), last_id=Max("pk"))
    return {**state, "latest": state["latest"].isoformat() if state["latest"] else None}


def snapshot_context(*, page_number=None, group=None, member_page=None):
    """Only bounded cache reads and a small metadata aggregate; never a rebuild."""
    signature = source_signature()
    manifest = cache.get(MANIFEST_KEY)
    result = {
        "statement_duplicate_pending": True,
        "statement_duplicate_available": False,
        "statement_duplicate_stats": {
            "statement_total": signature["count"],
            "exact_duplicate_group_total": None,
            "exact_duplicate_row_total": None,
            "similar_pair_total": None,
        },
    }
    if not manifest:
        return result
    generation = manifest["generation"]
    pages = max(1, (manifest["exact_duplicate_group_total"] + PAGE_SIZE - 1) // PAGE_SIZE)
    page = _page_number(page_number, pages)
    rows = cache.get(_key(generation, f"exact:{page}"))
    similar = cache.get(_key(generation, "similar"))
    if rows is None or similar is None:
        return result
    member_pages = 1
    if group:
        if len(group) != GROUP_KEY_LENGTH or any(c not in "0123456789abcdef" for c in group):
            return result
        detail = cache.get(_key(generation, f"group:{group}"))
        if detail is None:
            return result
        member_pages = max(1, (detail["member_total"] + PAGE_SIZE - 1) // PAGE_SIZE)
        page_members = _page_number(member_page, member_pages)
        items = cache.get(_key(generation, f"members:{group}:{page_members}"))
        if items is None:
            return result
        rows = [{**detail, "problem_items": items, "problem_labels": "\n".join(i["label"] for i in items)}]
        result.update(
            statement_duplicate_group=group,
            statement_duplicate_member_page=page_members,
            statement_duplicate_member_previous=page_members - 1 if page_members > 1 else None,
            statement_duplicate_member_next=page_members + 1 if page_members < member_pages else None,
        )
    generated = parse_datetime(manifest["generated_at"])
    result.update(
        statement_duplicate_pending=False,
        statement_duplicate_available=True,
        statement_duplicate_generated_at=generated,
        statement_duplicate_stale=manifest["signature"] != signature or timezone.now() - generated > MAX_AGE,
        statement_duplicate_stats={
            key: manifest[key]
            for key in (
                "statement_total",
                "exact_duplicate_group_total",
                "exact_duplicate_row_total",
                "similar_pair_total",
            )
        },
        statement_duplicate_exact_rows=rows,
        statement_duplicate_similar_rows=similar,
        statement_duplicate_similar_display_total=len(similar),
        statement_duplicate_similar_limit=SIMILAR_LIMIT,
        statement_duplicate_page=page,
        statement_duplicate_pages=pages,
        statement_duplicate_previous=page - 1 if page > 1 else None,
        statement_duplicate_next=page + 1 if page < pages else None,
        statement_duplicate_member_pages=member_pages,
    )
    return result


def refresh_statement_duplicate_snapshot(*, force=False, max_seconds=DEFAULT_BUILD_SECONDS):
    """Called by the existing catalog scheduler; publish only a complete generation."""
    with _refresh_lock() as acquired:
        if not acquired:
            return False
        started = monotonic()
        signature = source_signature()
        previous = cache.get(MANIFEST_KEY)
        if previous and not force and previous["signature"] == signature:
            if timezone.now() - parse_datetime(previous["generated_at"]) < MAX_AGE and _generation_complete(previous):
                return False
        generation = uuid.uuid4().hex
        generation_keys = []

        def publish(key, value):
            _store(key, value)
            generation_keys.append(key)

        # Readback matters: production Redis deliberately ignores backend errors.
        probe = _key(generation, "probe")
        _store(probe, generation)
        with (
            _scratch_index() as directory,
            closing(sqlite3.connect(Path(directory) / "index.sqlite3")) as db,
        ):
            guard = _build_guard(directory, started=started, max_seconds=max_seconds)
            guard()
            db.set_progress_handler(lambda: guard() or 0, 10_000)
            db.executescript("""
                PRAGMA page_size=4096;
                PRAGMA max_page_count=131072;
                PRAGMA cache_size=-4096;
                PRAGMA temp_store=FILE;
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                CREATE TABLE statements (id INTEGER PRIMARY KEY, exact TEXT, similar TEXT, eligible INTEGER,
                    year INTEGER, contest TEXT, day TEXT, label TEXT, url TEXT,
                    preview TEXT, length INTEGER, line TEXT);
                CREATE TABLE buckets (shingle BLOB PRIMARY KEY, count INTEGER NOT NULL) WITHOUT ROWID;
                CREATE TABLE members (shingle BLOB, id INTEGER, PRIMARY KEY(shingle,id)) WITHOUT ROWID;
            """)
            _index_statements(db, guard=guard)
            db.executescript(
                "CREATE INDEX exact_text ON statements(exact); CREATE INDEX member_id ON members(id,shingle);",
            )
            exact_total, row_total = _publish_exact_pages(db, generation, store=publish)
            similar, similar_total = _similar_pairs(db, guard=guard)
            publish(_key(generation, "similar"), similar)
            index_bytes = (Path(directory) / "index.sqlite3").stat().st_size
        # A changing source never produces a manifest claiming the newer source.
        if source_signature() != signature:
            return False
        inventory_pages = 0
        for offset in range(0, len(generation_keys), 100):
            _store(_key(generation, f"inventory:{inventory_pages}"), generation_keys[offset : offset + 100])
            inventory_pages += 1
        # Renew and check every chunk after completion, before publishing a manifest.
        for key in generation_keys:
            if not cache.touch(key, timeout=CACHE_TIMEOUT):
                message = "Duplicate report generation became incomplete"
                raise RuntimeError(message)
        manifest = {
            "generation": generation,
            "inventory_pages": inventory_pages,
            "build_seconds": round(monotonic() - started, 2),
            "index_bytes": index_bytes,
            "generated_at": timezone.now().isoformat(),
            "signature": signature,
            "statement_total": signature["count"],
            "exact_duplicate_group_total": exact_total,
            "exact_duplicate_row_total": row_total,
            "similar_pair_total": similar_total,
        }
        if not _generation_complete(manifest):
            message = "Duplicate report generation verification failed"
            raise RuntimeError(message)
        _store(MANIFEST_KEY, manifest, timeout=CACHE_TIMEOUT - 3600)
        return True


def _index_statements(db, *, guard):
    source = (
        ContestProblemStatement.objects.annotate(
            has_problem=Exists(ProblemSolveRecord.objects.filter(problem_uuid=OuterRef("problem_uuid"))),
        )
        .order_by("-contest_year", "contest_name", "day_label", "problem_number", "problem_code")
        .values(
            "id",
            "statement_latex",
            "contest_year",
            "contest_name",
            "day_label",
            "contest_year_problem",
            "problem_uuid",
            "problem_code",
            "linked_problem_id",
            "linked_problem__contest_year_problem",
            "has_problem",
        )
    )
    for item in source.iterator(chunk_size=100):
        guard()
        text = item["statement_latex"] or ""
        exact = normalize_exact_statement_text(text)
        similar = _normalize_similarity_text(text)
        tokens = tuple(similar.split())
        eligible = len(similar) >= SIMILARITY_MIN_CHAR_COUNT and len(tokens) >= SIMILARITY_MIN_TOKEN_COUNT
        url = (
            contest_dashboard_problem_url(
                item["contest_name"],
                year=item["contest_year"],
                problem_label=item["contest_year_problem"],
                fallback=f"{item['contest_year']}-{item['problem_code']}",
            )
            if item["linked_problem_id"] or item["has_problem"]
            else ""
        )
        linked = item["linked_problem__contest_year_problem"]
        line = " · ".join(
            (
                item["contest_year_problem"],
                item["day_label"] or "Unlabeled",
                f"Linked to {linked}" if linked else "Unlinked",
                f"UUID {item['problem_uuid']}",
            ),
        )
        db.execute(
            "INSERT INTO statements VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item["id"],
                exact,
                similar,
                eligible,
                item["contest_year"],
                item["contest_name"],
                item["day_label"],
                item["contest_year_problem"],
                url,
                _statement_preview(text),
                len(text),
                line,
            ),
        )
        if eligible:
            for shingle in _similarity_shingles(tokens):
                shingle_key = hashlib.sha256(shingle.encode()).digest()
                db.execute(
                    "INSERT INTO buckets VALUES (?,1) ON CONFLICT(shingle) DO UPDATE SET count=count+1",
                    (shingle_key,),
                )
                count = db.execute("SELECT count FROM buckets WHERE shingle=?", (shingle_key,)).fetchone()[0]
                if count <= SIMILARITY_MAX_BUCKET_SIZE:
                    db.execute("INSERT INTO members VALUES (?,?)", (shingle_key, item["id"]))
                elif count == SIMILARITY_MAX_BUCKET_SIZE + 1:
                    db.execute("DELETE FROM members WHERE shingle=?", (shingle_key,))
    db.commit()


def _publish_exact_pages(db, generation, *, store):
    page, page_rows, total, row_total = 1, [], 0, 0
    for exact, count in db.execute(
        "SELECT exact,COUNT(*) c FROM statements WHERE exact<>'' "
        "GROUP BY exact HAVING c>1 ORDER BY c DESC,MAX(length) DESC,MIN(label)",
    ):
        group = hashlib.sha256(exact.encode()).hexdigest()
        representative = db.execute(
            "SELECT preview,length FROM statements WHERE exact=? ORDER BY year DESC,contest,day,label LIMIT 1",
            (exact,),
        ).fetchone()
        year_min, year_max = db.execute(
            "SELECT MIN(year),MAX(year) FROM statements WHERE exact=?",
            (exact,),
        ).fetchone()
        label_total = db.execute("SELECT COUNT(DISTINCT label) FROM statements WHERE exact=?", (exact,)).fetchone()[0]
        members_page, members, preview_items, member_total = 1, [], [], 0
        for label, year, url in db.execute(
            "SELECT label,latest_year,url FROM ("
            "SELECT label,MAX(year) OVER (PARTITION BY label) latest_year,url,"
            "ROW_NUMBER() OVER (PARTITION BY label ORDER BY CASE WHEN url='' THEN 1 ELSE 0 END,"
            "year DESC,contest,day,id) position FROM statements WHERE exact=?"
            ") WHERE position=1 ORDER BY latest_year,label",
            (exact,),
        ):
            item = {"label": label, "contest_year": year, "url": url}
            members.append(item)
            member_total += 1
            if len(preview_items) < PAGE_SIZE:
                preview_items.append(item)
            if len(members) == PAGE_SIZE:
                if label_total > PAGE_SIZE:
                    store(_key(generation, f"members:{group}:{members_page}"), members)
                members_page, members = members_page + 1, []
        if members and label_total > PAGE_SIZE:
            store(_key(generation, f"members:{group}:{members_page}"), members)
        row = {
            "duplicate_count": count,
            "statement_length": representative[1],
            "preview": representative[0],
            "year_span_label": str(year_min) if year_min == year_max else f"{year_min}-{year_max}",
            "group_key": group,
            "member_total": member_total,
            "problem_items": preview_items,
            "problem_labels": "\n".join(i["label"] for i in preview_items),
        }
        if member_total > PAGE_SIZE:
            store(_key(generation, f"group:{group}"), row)
        page_rows.append(row)
        total, row_total = total + 1, row_total + count
        if len(page_rows) == PAGE_SIZE:
            store(_key(generation, f"exact:{page}"), page_rows)
            page, page_rows = page + 1, []
    if page_rows or total == 0:
        store(_key(generation, f"exact:{page}"), page_rows)
    return total, row_total


def _similar_pairs(db, *, guard=lambda: None):
    best, total = [], 0
    for left_id, left_text, left_exact, left_line, left_preview in db.execute(
        "SELECT id,similar,exact,line,preview FROM statements WHERE eligible=1 ORDER BY id",
    ):
        pairs = db.execute(
            "SELECT other.id,COUNT(*) c FROM members own JOIN members other ON own.shingle=other.shingle "
            "WHERE own.id=? AND other.id>? GROUP BY other.id HAVING c>=?",
            (left_id, left_id, SIMILARITY_MIN_SHARED_SHINGLES),
        )
        for right_id, overlap in pairs:
            guard()
            right_text, right_exact, right_line, right_preview = db.execute(
                "SELECT similar,exact,line,preview FROM statements WHERE id=?",
                (right_id,),
            ).fetchone()
            if left_exact == right_exact:
                continue
            if (
                abs(len(left_text) - len(right_text)) / max(len(left_text), len(right_text))
                > SIMILARITY_MAX_LENGTH_DELTA_RATIO
            ):
                continue
            matcher = SequenceMatcher(None, left_text, right_text)
            if matcher.real_quick_ratio() < SIMILARITY_THRESHOLD or matcher.quick_ratio() < SIMILARITY_THRESHOLD:
                continue
            score = matcher.ratio()
            if score < SIMILARITY_THRESHOLD:
                continue
            row = {
                "similarity_score": score,
                "similarity_percent": round(score * 100, 1),
                "shared_shingles": overlap,
                "left_statement": left_line,
                "left_preview": left_preview,
                "right_statement": right_line,
                "right_preview": right_preview,
            }
            bisect.insort(best, ((-score, -overlap, left_line, right_line), left_id, right_id, row))
            if len(best) > SIMILAR_LIMIT:
                best.pop()
            total += 1
    return [item[-1] for item in best], total


@contextmanager
def _refresh_lock():
    path = Path(tempfile.gettempdir()) / f"asterproof-duplicates-{os.getuid()}.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def _scratch_index():
    # Stable storage lets the next lock owner recover files left by SIGKILL or
    # a service timeout, without accumulating one directory per failed run.
    directory = Path(tempfile.gettempdir()) / f"asterproof-duplicate-index-{os.getuid()}"
    directory.mkdir(mode=SCRATCH_MODE, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != SCRATCH_MODE:
        message = "Duplicate report scratch directory is not private"
        raise RuntimeError(message)

    def clean():
        for name in ("index.sqlite3", "index.sqlite3-journal", "index.sqlite3-wal", "index.sqlite3-shm"):
            (directory / name).unlink(missing_ok=True)

    clean()
    if shutil.disk_usage(directory).free < MIN_START_FREE_BYTES:
        message = "Insufficient free space for duplicate report refresh"
        raise RuntimeError(message)

    try:
        yield directory
    finally:
        clean()


def _build_guard(directory, *, started, max_seconds):
    last_disk_check = 0

    def check():
        nonlocal last_disk_check
        now = monotonic()
        if now - started > max_seconds:
            message = "Duplicate report refresh exceeded its time budget"
            raise RuntimeError(message)
        if now - last_disk_check >= 1:
            last_disk_check = now
            if shutil.disk_usage(directory).free < RESERVED_FREE_BYTES:
                message = "Duplicate report refresh reached reserved disk headroom"
                raise RuntimeError(message)

    return check


def _key(generation, suffix):
    return f"statement-duplicates:v1:{generation}:{suffix}"


def _store(key, value, *, timeout=CACHE_TIMEOUT):
    cache.set(key, value, timeout=timeout)
    if cache.get(key) != value:
        message = "Duplicate report cache publication failed"
        raise RuntimeError(message)


def _page_number(raw, pages):
    try:
        return min(max(1, int(raw or 1)), pages)
    except (ValueError, TypeError):
        return 1


def _generation_complete(manifest):
    if not manifest.get("inventory_pages"):
        return False
    for page in range(manifest["inventory_pages"]):
        keys = cache.get(_key(manifest["generation"], f"inventory:{page}"))
        if not keys or len(cache.get_many(keys)) != len(keys):
            return False
    return True
