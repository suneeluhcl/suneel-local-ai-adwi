"""
adwi/obsidian_utils.py — shared Obsidian vault helpers (stdlib-only, no adwi imports).

Used by: adwi_cli.py, nightly.py, services/mcp/obsidian-bridge/server.py
"""

import re
from datetime import date as _date, datetime, timedelta
from pathlib import Path

_TEMPLATE = (
    "# {date}\n\n"
    "## Current Focus\n\n\n"
    "## Decisions\n\n\n"
    "## Ideas\n\n\n"
    "## Bugs / Fixes\n\n\n"
    "## Pending Approval\n\n\n"
)

# Sections scanned by the review workflow.
REVIEW_SECTIONS = [
    "## Current Focus",
    "## Decisions",
    "## Ideas",
    "## Bugs / Fixes",
    "## Pending Approval",
    "## Notes",
]

# Matches a leading "- HH:MM — " or "- HH:MM - " timestamp on a bullet entry.
_TS_PREFIX_RE = re.compile(r"^-\s*\d{2}:\d{2}\s*[—–-]+\s*")

# Section boundary pattern (used by append/extract helpers).
_SECTION_PAT_TMPL = r"^{heading}\n(.*?)(?=^##\s|^<!-- ADWI:|\Z)"


def _entry_body(s: str) -> str:
    """Return entry text with leading '- HH:MM — ' timestamp stripped (if present)."""
    stripped = s.strip()
    m = _TS_PREFIX_RE.match(stripped)
    return stripped[m.end():].strip() if m else stripped


def replace_marker_block(text: str, marker: str, block_body: str) -> str:
    """Replace or append a <!-- MARKER:START/END -->-delimited block.

    - Both START and END tags present: replaces the block in-place.
    - Tags absent: appends a new block at the end of the text.
    - Content outside the markers is never modified.
    """
    start_tag = f"<!-- {marker}:START -->"
    end_tag   = f"<!-- {marker}:END -->"
    new_block = f"{start_tag}\n{block_body}\n{end_tag}"
    if start_tag in text and end_tag in text:
        return re.sub(
            re.escape(start_tag) + r".*?" + re.escape(end_tag),
            new_block, text, flags=re.DOTALL,
        )
    return text.rstrip("\n") + "\n\n" + new_block + "\n"


def daily_note_template(date: str) -> str:
    """Return the default empty daily-note template for *date* (YYYY-MM-DD)."""
    return _TEMPLATE.format(date=date)


def today_note_path(vault: Path) -> Path:
    """Return the path for today's daily note (does not create the file)."""
    return vault / "daily-notes" / f"{datetime.now().strftime('%Y-%m-%d')}.md"


def append_under_heading(text: str, heading: str, entry: str) -> str:
    """Append *entry* under the first occurrence of *heading* in *text*.

    - heading: full heading line e.g. "## Ideas"
    - entry:   text to append  e.g. "- 14:32 — bought groceries"
    - Deduplication ignores the '- HH:MM — ' timestamp prefix so the same
      text captured at different times is not written twice to the same note.
    - Creates the heading at the end of *text* if it is absent.
    - Never inserts inside a <!-- ADWI:...: --> marker block.
    """
    h = heading.rstrip()
    entry_line  = entry.rstrip("\n")
    entry_body  = _entry_body(entry_line)

    pat = re.compile(
        _SECTION_PAT_TMPL.format(heading=re.escape(h)),
        re.DOTALL | re.MULTILINE,
    )
    m = pat.search(text)
    if m:
        body = m.group(1)
        # Dedup: compare body text, ignoring timestamps.
        for line in body.splitlines():
            if _entry_body(line) == entry_body and entry_body:
                return text
        # Exact-match fallback for non-timestamped entries.
        if entry_line in body:
            return text
        body_stripped = body.rstrip("\n")
        new_body = (body_stripped + "\n\n") if body_stripped else "\n"
        new_body += entry_line + "\n"
        return text[: m.start(1)] + new_body + text[m.start(1) + len(body) :]
    else:
        return text.rstrip("\n") + f"\n\n{h}\n\n{entry_line}\n"


def append_to_daily_section(vault: Path, date: str, section: str, entry: str) -> tuple:
    """Read/create *date*'s daily note and append *entry* under *section*.

    Returns (success: bool, message: str).
    """
    try:
        note_path = vault / "daily-notes" / f"{date}.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        existing = (
            note_path.read_text(encoding="utf-8")
            if note_path.exists()
            else daily_note_template(date)
        )
        note_path.write_text(append_under_heading(existing, section, entry), encoding="utf-8")
        return True, str(note_path)
    except Exception as exc:
        return False, str(exc)


def extract_sections(text: str, sections: list | None = None) -> dict:
    """Extract bullet entries from named sections in a daily note.

    Returns dict: section_heading → list of bullet entry strings.
    Only sections that have at least one bullet entry are included.
    """
    if sections is None:
        sections = REVIEW_SECTIONS
    result = {}
    for section in sections:
        h = section.rstrip()
        pat = re.compile(
            _SECTION_PAT_TMPL.format(heading=re.escape(h)),
            re.DOTALL | re.MULTILINE,
        )
        m = pat.search(text)
        if m:
            entries = [
                line.strip()
                for line in m.group(1).splitlines()
                if line.strip().startswith("- ") or line.strip().startswith("* ")
            ]
            if entries:
                result[section] = entries
    return result


def write_daily_plan(vault: Path, date: str, plan_body: str) -> tuple:
    """Write or update the ADWI:DAILY-PLAN marker block in *date*'s daily note.

    Returns (success: bool, message: str).
    """
    try:
        note_path = vault / "daily-notes" / f"{date}.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        existing = (
            note_path.read_text(encoding="utf-8")
            if note_path.exists()
            else daily_note_template(date)
        )
        note_path.write_text(
            replace_marker_block(existing, "ADWI:DAILY-PLAN", plan_body),
            encoding="utf-8",
        )
        return True, str(note_path)
    except Exception as exc:
        return False, str(exc)


def read_daily_plan(vault: Path, date: str) -> str | None:
    """Return the body of the ADWI:DAILY-PLAN block, or None if absent/blank."""
    note_path = vault / "daily-notes" / f"{date}.md"
    if not note_path.exists():
        return None
    text      = note_path.read_text(encoding="utf-8")
    start_tag = "<!-- ADWI:DAILY-PLAN:START -->"
    end_tag   = "<!-- ADWI:DAILY-PLAN:END -->"
    if start_tag not in text or end_tag not in text:
        return None
    body = text.split(start_tag, 1)[1].split(end_tag, 1)[0].strip()
    return body if body else None


def clear_marker_block(text: str, marker: str) -> str:
    """Set a marker block's body to empty string (idempotent).

    If the marker is absent the text is returned unchanged.
    Use this to semantically clear a block while keeping the tags in place,
    so read helpers (e.g. read_daily_plan) can treat the block as absent.
    """
    start_tag = f"<!-- {marker}:START -->"
    if start_tag not in text:
        return text
    return replace_marker_block(text, marker, "")


def collect_daily_entries(vault: Path, start_date: str, end_date: str,
                           sections: list | None = None) -> list:
    """Scan daily notes from *start_date* to *end_date* inclusive (YYYY-MM-DD).

    Returns list of dicts: {date, section, entries, path}.
    Records with no entries are omitted.
    """
    d_start = _date.fromisoformat(start_date)
    d_end   = _date.fromisoformat(end_date)
    result  = []
    current = d_start
    while current <= d_end:
        ds        = current.isoformat()
        note_path = vault / "daily-notes" / f"{ds}.md"
        if note_path.exists():
            text      = note_path.read_text(encoding="utf-8")
            extracted = extract_sections(text, sections)
            for section, entries in extracted.items():
                result.append(
                    {"date": ds, "section": section,
                     "entries": entries, "path": str(note_path)}
                )
        current += timedelta(days=1)
    return result
