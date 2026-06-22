---
type: maintenance-guide
status: active
tags: [obsidian, maintenance, vault, markers]
updated: 2026-06-21
---

# Obsidian Maintenance

How the Adwi vault stays up-to-date automatically and what to do when something goes wrong.

---

## How Generated Marker Blocks Work

Adwi writes generated content into daily notes and knowledge files using HTML comment markers:

```
<!-- ADWI:MARKER-NAME:START -->
generated content here
<!-- ADWI:MARKER-NAME:END -->
```

**Behaviour:**
- If the markers are **absent** — content is appended at the end of the file.
- If the markers are **present** — content is replaced in-place. Manual text outside the markers is never touched.
- The shared helper is in `adwi/obsidian_utils.py` → `replace_marker_block(text, marker, block_body)`.

**Markers in use:**

| Marker | File | Written by |
|--------|------|------------|
| `ADWI:DAILY-SUMMARY` | `daily-notes/YYYY-MM-DD.md` | `nightly.py` step 11 (2 AM) |
| `ADWI:DAILY-BRIEF` | `daily-notes/YYYY-MM-DD.md` | `adwi_cli.py` `/daily-brief` command |
| `ADWI:HOME-STATUS` | `Adwi Home.md` | `nightly.py` step 12 (2 AM) |
| `ADWI:PENDING-APPROVAL` | `knowledge/Pending Approval.md` | `nightly.py` step 13 (2 AM) |

---

## What Files Are Refreshed Nightly

The 2 AM nightly loop (`adwi/nightly.py`) writes/refreshes:

1. `daily-notes/YYYY-MM-DD.md` — `ADWI:DAILY-SUMMARY` block (system status, git commit, web research, AI suggestions)
2. `Adwi Home.md` — `ADWI:HOME-STATUS` block (latest 7 notes, NLU status, pending summary)
3. `knowledge/Pending Approval.md` — `ADWI:PENDING-APPROVAL` block (brew updates, npm, AI suggestions, self-heal failures)

The `/daily-brief` command only writes the `ADWI:DAILY-BRIEF` block in today's daily note.

---

## Where Archives and Backups Live

| Path | Contents |
|------|----------|
| `obsidian-vault/logs/archive/daily-note-cleanup/2026-06-21/` | One-time 2026-06-21 cleanup — pre-marker `.bak` copies of all daily notes |

If you run a manual cleanup in the future, put backups under:
`obsidian-vault/logs/archive/daily-note-cleanup/YYYY-MM-DD/`

---

## What To Do If a Daily Note Gets Corrupted

**Symptoms:** duplicate headings, missing markers, truncated content.

**Recovery steps:**

1. Check if a backup exists in `obsidian-vault/logs/archive/daily-note-cleanup/`.
2. If yes — copy the `.bak` file back and re-apply the marker structure manually.
3. If no — the nightly loop will overwrite the `ADWI:DAILY-SUMMARY` block on the next run. Manual sections outside the markers are safe.

**To force-reset a daily note to template:**
```bash
python3 - <<'EOF'
from adwi.obsidian_utils import daily_note_template
from pathlib import Path
date = "2026-06-21"
p = Path("obsidian-vault/daily-notes") / f"{date}.md"
p.write_text(daily_note_template(date))
print(f"reset {p}")
EOF
```

**To manually run the Obsidian home/pending refresh:**
```bash
python3 -c "
import sys; sys.path.insert(0, 'adwi')
import nightly
nightly.step_update_obsidian_home({})
nightly.step_update_obsidian_pending({})
print('done')
"
```

---

## `.obsidian/` Vault Config

Obsidian stores its internal config in `obsidian-vault/.obsidian/`. Most of these files are local UI state and are **gitignored**:

| File | Status | Reason |
|------|--------|--------|
| `workspace.json` | gitignored | volatile — open tabs, window layout |
| `workspace-mobile.json` | gitignored | volatile — mobile layout |
| `graph.json` | gitignored | volatile — graph filter positions |
| `app.json` | gitignored | empty default, not meaningful |
| `appearance.json` | gitignored | empty default |
| `core-plugins.json` | **tracked** | stable — list of enabled built-in plugins |

If you add a community plugin, its config appears in `.obsidian/plugins/` — those are also gitignored by the pattern above.

---

## Related Notes

- [[Adwi Home]]
- [[knowledge/Pending Approval]]
- [[knowledge/System Map]]
- [adwi/obsidian_utils.py](../../adwi/obsidian_utils.py)
- [adwi/nightly.py](../../adwi/nightly.py)
