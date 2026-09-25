"""bucket.py — transcript walking and catch-up scan for the standup skill.

Two mutually-exclusive modes:
  --date YYYY-MM-DD --project <encoded-cwd>   Bundle mode: emit text bundle
  --catch-up <project-output-dir>              Catch-up mode: emit dates-to-fill

Boundary rule (from spec): file walking, date filtering, role-based turn
extraction (with tool_result exclusion as the ONE allowed content filter),
session grouping, catch-up scan. Nothing else.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bucket",
        description="standup: transcript bucketing and catch-up scan",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Bundle mode: emit text bundle for this local date.",
    )
    mode.add_argument(
        "--catch-up",
        metavar="DIR",
        help="Catch-up mode: emit dates-to-fill (one per line) up to yesterday.",
    )
    project_group = p.add_mutually_exclusive_group()
    project_group.add_argument(
        "--project",
        metavar="ENCODED_CWD",
        help="(Bundle mode only) Encoded-cwd project key under ~/.claude/projects/.",
    )
    project_group.add_argument(
        "--all-projects",
        action="store_true",
        help="(Bundle mode only) Walk all projects under ~/.claude/projects/.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.date and not (args.project or args.all_projects):
        parser.error("--date requires --project or --all-projects")
    if args.all_projects and not args.date:
        parser.error("--all-projects requires --date")
    if args.date and args.all_projects:
        return _all_projects_mode(args.date)
    if args.date:
        return _bundle_mode(args.date, args.project)
    return _catchup_mode(args.catch_up)


def _project_dir(project: str) -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "projects" / project


@functools.cache
def _load_records(jsonl_path: Path) -> list[dict]:
    """Load JSONL records, skipping malformed lines silently.
    Transcripts are append-only; mid-write corruption is rare and isolated.

    Cached: --all-projects walks each JSONL up to ~3 times (decoded-name
    resolution, has-records pre-check, emit). The cache amortizes parsing
    across one process invocation. Callers must treat the returned list
    as read-only — mutating any element would corrupt subsequent reads."""
    out: list[dict] = []
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _utc_to_local_date(ts, tz: ZoneInfo | None = None) -> str | None:
    """Pure: ISO-ish UTC timestamp string → 'YYYY-MM-DD' in tz.

    `tz=None` uses the system local timezone (production default).
    Tests pass an explicit ZoneInfo to avoid env/tzdata coupling."""
    if not isinstance(ts, str):
        return None
    # fromisoformat in Python 3.11+ accepts 'Z'; replace for older compat.
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if tz is None:
        return dt.astimezone().date().isoformat()
    return dt.astimezone(tz).date().isoformat()


def _record_local_date(record: dict) -> str | None:
    """Return record's timestamp as a local-date string, or None if unparseable."""
    return _utc_to_local_date(record.get("timestamp"))


# --- Begin port from synth_harness.py:20-46 (canonical rules) ---
# Rationale: bucket.py must not import synth_harness (separate concerns
# per spec). These helpers are copied verbatim with attribution to keep
# the canonical role-extraction rules in one logical place. If
# synth_harness.py rules change, mirror them here.

def _is_real_user_turn(record: dict) -> bool:
    """A 'user' record that represents a real user turn boundary.

    Rules (from synth_harness.is_real_user_turn, main-transcript only):
    - type == 'user'
    - message.role == 'user'
    - isSidechain == False (subagent records excluded by spec)
    - isMeta != True (excludes <local-command-caveat> stubs)
    - content is a string, OR a list with NO tool_result blocks
    """
    if record.get("type") != "user":
        return False
    msg = record.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False
    if bool(record.get("isSidechain", False)):
        return False
    if record.get("isMeta") is True:
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def _extract_user_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p)
    return ""


def _extract_assistant_text(content: object) -> str:
    if not isinstance(content, list):
        return ""
    parts = [
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    return "\n".join(p for p in parts if p)


def _extract_turn(record: dict) -> tuple[str, str] | None:
    """Return (role, text) for records that count as turns; else None.

    Excludes assistant records on subagent sidechains."""
    msg = record.get("message")
    if not isinstance(msg, dict):
        return None
    role = msg.get("role")
    if role == "user":
        if not _is_real_user_turn(record):
            return None
        text = _extract_user_text(msg.get("content"))
        return ("user", text) if text else None
    if role == "assistant":
        if bool(record.get("isSidechain", False)):
            return None
        text = _extract_assistant_text(msg.get("content"))
        return ("assistant", text) if text else None
    return None
# --- End port ---


def _projects_root() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "projects"


def _emit_project_sessions(
    project_dir: Path, date: str, *, session_header_level: int
) -> bool:
    """Emit `## session <id>` (or `### session <id>`) blocks for one project.

    Returns True if anything was emitted (project had matching records),
    False otherwise. The caller is responsible for any leading project
    header and the blank-line separator between projects.
    """
    prefix = "#" * session_header_level
    any_emitted = False
    for jsonl in sorted(project_dir.glob("*.jsonl")):
        session_id = jsonl.stem
        session_lines: list[str] = []
        for rec in _load_records(jsonl):
            if _record_local_date(rec) != date:
                continue
            turn = _extract_turn(rec)
            if turn is None:
                continue
            role, text = turn
            session_lines.append(f"[{role}] {text}")
        if not session_lines:
            continue
        if any_emitted:
            print()  # blank line between sessions
        print(f"{prefix} session {session_id}")
        print()
        for line in session_lines:
            print(line)
        any_emitted = True
    return any_emitted


def _last_record_timestamp(jsonl: Path) -> str | None:
    """Return the timestamp of the last valid record (JSON-parses AND has
    a `timestamp` field). None if no valid record exists. ISO-string
    comparison matches chronological order for ISO-8601 UTC timestamps."""
    last_ts: str | None = None
    for rec in _load_records(jsonl):
        ts = rec.get("timestamp")
        if isinstance(ts, str):
            last_ts = ts
    return last_ts


def _first_cwd_in_file(jsonl: Path) -> str | None:
    """First record in this JSONL with a non-empty `cwd` string. None if absent."""
    for rec in _load_records(jsonl):
        cwd = rec.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    return None


def _resolve_decoded_name_and_cwd(project_dir: Path) -> tuple[str, str]:
    """Decoded name from the first sorted JSONL; cwd from the most-recent
    session by last-record timestamp. Each independent — name picks the
    first sorted JSONL because alphabetic determinism is fine for a
    human-readable label, while cwd picks recency because we want a path
    that's likely to exist on the current machine."""
    encoded = project_dir.name
    jsonls = sorted(project_dir.glob("*.jsonl"))
    if not jsonls:
        return (encoded, "")

    # Single-JSONL short-circuit: no recency selection needed; one walk
    # of the file gives us both name and cwd.
    if len(jsonls) == 1:
        cwd = _first_cwd_in_file(jsonls[0]) or ""
        name = Path(cwd).name if cwd else encoded
        return (name, cwd)

    # --- Name: first record with cwd in the first sorted JSONL ---
    first_cwd_for_name = _first_cwd_in_file(jsonls[0])
    name = Path(first_cwd_for_name).name if first_cwd_for_name else encoded

    # --- cwd: most-recent-session by last-record timestamp ---
    # Build (last_timestamp, sort-tiebreak filename, jsonl) for each
    # candidate that has at least one valid record.
    candidates: list[tuple[str, str, Path]] = []
    for jsonl in jsonls:
        ts = _last_record_timestamp(jsonl)
        if ts is None:
            continue  # zero valid records → excluded
        candidates.append((ts, jsonl.name, jsonl))
    if not candidates:
        return (name, "")
    # max() with the (ts, filename) key satisfies the spec's tiebreak rule:
    # max ts wins; equal ts → lexicographically-larger filename wins.
    _, _, winner = max(candidates, key=lambda t: (t[0], t[1]))
    cwd = _first_cwd_in_file(winner) or ""
    return (name, cwd)


def _project_has_records_on_date(project_dir: Path, date: str) -> bool:
    """Cheap pre-check: does any JSONL in the dir contain at least one
    extractable turn on the given local date? Avoids emitting a
    project header for projects with no matching records.

    Note: this double-walks each project (this pre-check + the later
    `_emit_project_sessions` call). Acceptable while N (projects) and
    M (JSONLs per project) are small. If I/O dominates in the future,
    refactor to a buffered writer that emits the header only after
    `_emit_project_sessions` reports it wrote something.
    """
    for jsonl in project_dir.glob("*.jsonl"):
        for rec in _load_records(jsonl):
            if _record_local_date(rec) != date:
                continue
            if _extract_turn(rec) is not None:
                return True
    return False


def _all_projects_mode(date: str) -> int:
    root = _projects_root()
    if not root.is_dir():
        print(f"bucket: projects dir not found: {root}", file=sys.stderr)
        return 1

    raw: list[tuple[str, str, Path]] = []  # (candidate_name, cwd, dir)
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        name, cwd = _resolve_decoded_name_and_cwd(project_dir)
        raw.append((name, cwd, project_dir))

    # Single pre-pass: any candidate name appearing more than once
    # collides — rewrite ALL its occurrences to the encoded-cwd verbatim.
    # Note: this includes stale projects (no records on the target date),
    # so a stale `cool-app` forces a fresh `cool-app` to its encoded form
    # even when the stale one isn't emitted. Deliberate: collision behavior
    # stays stable across days regardless of which projects are active.
    name_counts: dict[str, int] = {}
    for name, _, _ in raw:
        name_counts[name] = name_counts.get(name, 0) + 1
    candidates: list[tuple[str, str, Path]] = []
    for name, cwd, project_dir in raw:
        if name_counts[name] > 1:
            name = project_dir.name  # encoded-cwd verbatim
        candidates.append((name, cwd, project_dir))
    candidates.sort(key=lambda triple: triple[0])

    any_project_emitted = False
    for name, cwd, project_dir in candidates:
        if not _project_has_records_on_date(project_dir, date):
            continue
        if any_project_emitted:
            print()
        print(f"## project {name}")
        print(f"<!-- cwd: {cwd} -->" if cwd else "<!-- cwd: -->")
        print()
        _emit_project_sessions(project_dir, date, session_header_level=3)
        any_project_emitted = True
    return 0


def _bundle_mode(date: str, project: str) -> int:
    project_dir = _project_dir(project)
    if not project_dir.is_dir():
        print(
            f"bucket: project dir not found: {project_dir}",
            file=sys.stderr,
        )
        return 1
    _emit_project_sessions(project_dir, date, session_header_level=2)
    return 0


_DATE_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def _catchup_mode(project_output_dir: str) -> int:
    out_dir = Path(project_output_dir)
    yesterday = datetime.now().astimezone().date() - timedelta(days=1)
    max_date: date_cls | None = None
    if out_dir.is_dir():
        for entry in out_dir.iterdir():
            if not entry.is_file():
                continue
            m = _DATE_FILENAME_RE.match(entry.name)
            if not m:
                continue
            try:
                d = date_cls.fromisoformat(m.group(1))
            except ValueError:
                continue
            if d > yesterday:
                continue  # ignore future-dated entries
            if max_date is None or d > max_date:
                max_date = d
    start = (max_date + timedelta(days=1)) if max_date else yesterday
    if start > yesterday:
        return 0
    cur = start
    while cur <= yesterday:
        print(cur.isoformat())
        cur += timedelta(days=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
