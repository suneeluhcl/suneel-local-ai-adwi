"""Tests for adwi/obsidian_utils.py — marker-block helpers."""

import importlib.util
import sys
import unittest
from pathlib import Path

# Load obsidian_utils from its known path without requiring adwi to be a package.
_spec = importlib.util.spec_from_file_location(
    "obsidian_utils",
    Path(__file__).resolve().parents[1] / "obsidian_utils.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
replace_marker_block    = _mod.replace_marker_block
clear_marker_block      = _mod.clear_marker_block
daily_note_template     = _mod.daily_note_template
today_note_path         = _mod.today_note_path
append_under_heading    = _mod.append_under_heading
append_to_daily_section = _mod.append_to_daily_section
extract_sections        = _mod.extract_sections
collect_daily_entries   = _mod.collect_daily_entries
write_daily_plan        = _mod.write_daily_plan
read_daily_plan         = _mod.read_daily_plan


class TestReplaceMarkerBlock(unittest.TestCase):

    def _make_note(self, manual="manual content here"):
        return f"# 2026-01-01\n\n## Notes\n\n{manual}\n"

    # ── append when absent ────────────────────────────────────────────────────

    def test_appends_block_when_absent(self):
        note = self._make_note()
        result = replace_marker_block(note, "ADWI:TEST", "generated body")
        self.assertIn("<!-- ADWI:TEST:START -->", result)
        self.assertIn("<!-- ADWI:TEST:END -->", result)
        self.assertIn("generated body", result)

    def test_appends_after_existing_content(self):
        note = self._make_note("my manual notes")
        result = replace_marker_block(note, "ADWI:TEST", "new body")
        self.assertTrue(result.index("my manual notes") < result.index("<!-- ADWI:TEST:START -->"))

    # ── replace when present ─────────────────────────────────────────────────

    def test_replaces_existing_block(self):
        note = (
            "# 2026-01-01\n\n"
            "<!-- ADWI:TEST:START -->\nold body\n<!-- ADWI:TEST:END -->\n"
        )
        result = replace_marker_block(note, "ADWI:TEST", "new body")
        self.assertIn("new body", result)
        self.assertNotIn("old body", result)

    def test_replace_keeps_exactly_one_block(self):
        note = (
            "before\n"
            "<!-- ADWI:TEST:START -->\nold\n<!-- ADWI:TEST:END -->\n"
            "after\n"
        )
        result = replace_marker_block(note, "ADWI:TEST", "replaced")
        self.assertEqual(result.count("<!-- ADWI:TEST:START -->"), 1)
        self.assertEqual(result.count("<!-- ADWI:TEST:END -->"), 1)

    # ── preserves manual content ─────────────────────────────────────────────

    def test_preserves_content_before_marker(self):
        note = "## Manual\n\nmy handwritten note\n\n<!-- ADWI:TEST:START -->\nold\n<!-- ADWI:TEST:END -->\n"
        result = replace_marker_block(note, "ADWI:TEST", "auto")
        self.assertIn("my handwritten note", result)

    def test_preserves_content_after_marker(self):
        note = "<!-- ADWI:TEST:START -->\nold\n<!-- ADWI:TEST:END -->\n\n## After\n\nstill here\n"
        result = replace_marker_block(note, "ADWI:TEST", "auto")
        self.assertIn("still here", result)

    def test_preserves_other_marker_blocks(self):
        note = (
            "<!-- ADWI:A:START -->\nbody-a\n<!-- ADWI:A:END -->\n"
            "<!-- ADWI:B:START -->\nbody-b\n<!-- ADWI:B:END -->\n"
        )
        result = replace_marker_block(note, "ADWI:A", "new-a")
        self.assertIn("new-a", result)
        self.assertIn("body-b", result)

    # ── idempotency ──────────────────────────────────────────────────────────

    def test_multiple_updates_idempotent(self):
        note = self._make_note()
        r1 = replace_marker_block(note, "ADWI:TEST", "body v1")
        r2 = replace_marker_block(r1,   "ADWI:TEST", "body v2")
        r3 = replace_marker_block(r2,   "ADWI:TEST", "body v2")
        self.assertEqual(r2, r3)
        self.assertIn("body v2", r3)
        self.assertNotIn("body v1", r3)

    def test_block_count_stable_across_multiple_writes(self):
        note = self._make_note()
        for i in range(5):
            note = replace_marker_block(note, "ADWI:TEST", f"iteration {i}")
        self.assertEqual(note.count("<!-- ADWI:TEST:START -->"), 1)

    # ── block body with special characters ──────────────────────────────────

    def test_handles_multiline_block_body(self):
        body = "line 1\nline 2\n```json\n{}\n```"
        note = self._make_note()
        result = replace_marker_block(note, "ADWI:TEST", body)
        self.assertIn("line 1\nline 2", result)

    def test_handles_empty_block_body(self):
        note = self._make_note()
        result = replace_marker_block(note, "ADWI:TEST", "")
        self.assertIn("<!-- ADWI:TEST:START -->", result)
        self.assertIn("<!-- ADWI:TEST:END -->", result)


class TestClearMarkerBlock(unittest.TestCase):

    _NOTE = (
        "# 2026-01-01\n\n"
        "## Manual Section\n\nsome handwritten text\n\n"
        "<!-- ADWI:DAILY-PLAN:START -->\n"
        "## Daily Plan\n- real plan item\n"
        "<!-- ADWI:DAILY-PLAN:END -->\n"
        "<!-- ADWI:DAILY-BRIEF:START -->\nbrief content\n<!-- ADWI:DAILY-BRIEF:END -->\n"
    )

    def test_clears_body_to_empty(self):
        result = clear_marker_block(self._NOTE, "ADWI:DAILY-PLAN")
        start = result.index("<!-- ADWI:DAILY-PLAN:START -->")
        end   = result.index("<!-- ADWI:DAILY-PLAN:END -->")
        body  = result[start + len("<!-- ADWI:DAILY-PLAN:START -->"):end].strip()
        self.assertEqual(body, "")

    def test_preserves_manual_content(self):
        result = clear_marker_block(self._NOTE, "ADWI:DAILY-PLAN")
        self.assertIn("some handwritten text", result)

    def test_preserves_other_marker_blocks(self):
        result = clear_marker_block(self._NOTE, "ADWI:DAILY-PLAN")
        self.assertIn("<!-- ADWI:DAILY-BRIEF:START -->", result)
        self.assertIn("brief content", result)

    def test_idempotent_if_marker_absent(self):
        text = "# 2026-01-01\n\n## Notes\n\nno plan here\n"
        result = clear_marker_block(text, "ADWI:DAILY-PLAN")
        self.assertEqual(result, text)

    def test_read_daily_plan_returns_none_after_clear(self):
        import tempfile, shutil
        tmp   = tempfile.mkdtemp()
        vault = Path(tmp) / "vault"
        (vault / "daily-notes").mkdir(parents=True)
        try:
            write_daily_plan(vault, "2026-01-01", "plan body")
            self.assertIsNotNone(read_daily_plan(vault, "2026-01-01"))
            note_path = vault / "daily-notes" / "2026-01-01.md"
            text = note_path.read_text(encoding="utf-8")
            note_path.write_text(clear_marker_block(text, "ADWI:DAILY-PLAN"), encoding="utf-8")
            self.assertIsNone(read_daily_plan(vault, "2026-01-01"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDailyNoteTemplate(unittest.TestCase):

    def test_contains_date(self):
        t = daily_note_template("2026-06-21")
        self.assertIn("# 2026-06-21", t)

    def test_contains_standard_sections(self):
        t = daily_note_template("2026-06-21")
        for section in ("Current Focus", "Decisions", "Ideas", "Bugs / Fixes", "Pending Approval"):
            self.assertIn(section, t)

    def test_no_marker_blocks_in_fresh_template(self):
        t = daily_note_template("2026-06-21")
        self.assertNotIn("<!-- ADWI:", t)


class TestTodayNotePath(unittest.TestCase):

    def test_returns_path_in_daily_notes(self):
        from pathlib import Path
        vault = Path("/tmp/fake-vault")
        p = today_note_path(vault)
        self.assertEqual(p.parent, vault / "daily-notes")
        self.assertTrue(p.name.endswith(".md"))

    def test_filename_matches_iso_date(self):
        import re
        from pathlib import Path
        p = today_note_path(Path("/tmp/v"))
        self.assertRegex(p.name, r"^\d{4}-\d{2}-\d{2}\.md$")


class TestAppendUnderHeading(unittest.TestCase):

    _SAMPLE = (
        "# 2026-01-01\n\n"
        "## Current Focus\n\nfocus item\n\n"
        "## Ideas\n\n\n"
        "## Bugs / Fixes\n\n"
    )

    def test_appends_to_existing_nonempty_section(self):
        result = append_under_heading(self._SAMPLE, "## Current Focus", "- new task")
        self.assertIn("focus item", result)
        self.assertIn("- new task", result)
        # new entry must be after the existing content
        self.assertGreater(result.index("- new task"), result.index("focus item"))

    def test_appends_to_existing_empty_section(self):
        result = append_under_heading(self._SAMPLE, "## Ideas", "- my idea")
        self.assertIn("- my idea", result)

    def test_creates_section_if_absent(self):
        result = append_under_heading(self._SAMPLE, "## Notes", "- new note")
        self.assertIn("## Notes", result)
        self.assertIn("- new note", result)

    def test_no_duplicate_on_second_call(self):
        r1 = append_under_heading(self._SAMPLE, "## Ideas", "- dedup me")
        r2 = append_under_heading(r1, "## Ideas", "- dedup me")
        self.assertEqual(r1, r2)

    def test_preserves_content_outside_section(self):
        result = append_under_heading(self._SAMPLE, "## Ideas", "- x")
        self.assertIn("focus item", result)
        self.assertIn("## Bugs / Fixes", result)

    def test_stops_before_adwi_marker(self):
        text = (
            "## Ideas\n\n"
            "<!-- ADWI:DAILY-SUMMARY:START -->\ngenerated\n<!-- ADWI:DAILY-SUMMARY:END -->\n"
        )
        result = append_under_heading(text, "## Ideas", "- captured")
        # Entry must appear before the marker, not inside it
        self.assertLess(result.index("- captured"), result.index("<!-- ADWI:DAILY-SUMMARY:START -->"))

    def test_entry_placed_before_next_heading(self):
        result = append_under_heading(self._SAMPLE, "## Current Focus", "- after existing")
        focus_end = result.index("## Ideas")
        entry_pos = result.index("- after existing")
        self.assertLess(entry_pos, focus_end)

    def test_idempotent_multiple_writes(self):
        text = self._SAMPLE
        for _ in range(5):
            text = append_under_heading(text, "## Ideas", "- repeated")
        self.assertEqual(text.count("- repeated"), 1)


class TestAppendToDailySection(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self._vault = self._tmp / "vault"
        self._vault.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_creates_note_if_absent(self):
        ok, msg = append_to_daily_section(self._vault, "2026-01-01", "## Ideas", "- fresh idea")
        self.assertTrue(ok)
        note = (self._vault / "daily-notes" / "2026-01-01.md").read_text()
        self.assertIn("- fresh idea", note)

    def test_appends_to_existing_note(self):
        note_path = self._vault / "daily-notes" / "2026-01-01.md"
        note_path.parent.mkdir(parents=True)
        note_path.write_text("# 2026-01-01\n\n## Ideas\n\nexisting idea\n")
        ok, _ = append_to_daily_section(self._vault, "2026-01-01", "## Ideas", "- new idea")
        self.assertTrue(ok)
        content = note_path.read_text()
        self.assertIn("existing idea", content)
        self.assertIn("- new idea", content)

    def test_returns_tuple_with_path_on_success(self):
        ok, msg = append_to_daily_section(self._vault, "2026-01-02", "## Notes", "- hi")
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(msg, str)
        self.assertTrue(ok)
        self.assertIn("2026-01-02", msg)


class TestDailyPlan(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp   = Path(tempfile.mkdtemp())
        self._vault = self._tmp / "vault"
        (self._vault / "daily-notes").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_write_creates_marker_block(self):
        ok, path = write_daily_plan(self._vault, "2026-01-01", "### Top Focus\n- finish task")
        self.assertTrue(ok)
        content = (self._vault / "daily-notes" / "2026-01-01.md").read_text()
        self.assertIn("<!-- ADWI:DAILY-PLAN:START -->", content)
        self.assertIn("<!-- ADWI:DAILY-PLAN:END -->", content)
        self.assertIn("finish task", content)

    def test_write_updates_in_place(self):
        write_daily_plan(self._vault, "2026-01-01", "v1 content")
        write_daily_plan(self._vault, "2026-01-01", "v2 content")
        content = (self._vault / "daily-notes" / "2026-01-01.md").read_text()
        self.assertIn("v2 content", content)
        self.assertNotIn("v1 content", content)
        self.assertEqual(content.count("ADWI:DAILY-PLAN:START"), 1)

    def test_write_preserves_manual_sections(self):
        note_path = self._vault / "daily-notes" / "2026-01-01.md"
        note_path.write_text("# 2026-01-01\n\n## Ideas\n\n- my manual idea\n")
        write_daily_plan(self._vault, "2026-01-01", "plan body")
        content = note_path.read_text()
        self.assertIn("my manual idea", content)
        self.assertIn("plan body", content)

    def test_read_returns_none_when_absent(self):
        self.assertIsNone(read_daily_plan(self._vault, "2026-01-01"))

    def test_read_returns_none_for_missing_file(self):
        self.assertIsNone(read_daily_plan(self._vault, "1999-12-31"))

    def test_read_returns_plan_body(self):
        write_daily_plan(self._vault, "2026-01-01", "### Top Focus\n- get things done")
        body = read_daily_plan(self._vault, "2026-01-01")
        self.assertIsNotNone(body)
        self.assertIn("get things done", body)

    def test_read_returns_none_after_clear(self):
        # Writing an empty-ish body and reading back
        write_daily_plan(self._vault, "2026-01-01", "")
        result = read_daily_plan(self._vault, "2026-01-01")
        self.assertIsNone(result)

    def test_write_creates_note_from_template_if_absent(self):
        ok, _ = write_daily_plan(self._vault, "2026-02-01", "test plan")
        self.assertTrue(ok)
        content = (self._vault / "daily-notes" / "2026-02-01.md").read_text()
        self.assertIn("# 2026-02-01", content)
        self.assertIn("## Current Focus", content)


class TestTimestampDedup(unittest.TestCase):
    """append_under_heading should dedup by text body, ignoring - HH:MM — prefix."""

    def test_same_text_different_timestamp_not_duplicated(self):
        text = "# 2026-01-01\n\n## Ideas\n\n"
        r1 = append_under_heading(text, "## Ideas", "- 14:00 — my idea")
        r2 = append_under_heading(r1, "## Ideas", "- 15:30 — my idea")
        self.assertEqual(r1, r2)
        self.assertEqual(r1.count("my idea"), 1)

    def test_different_text_different_timestamp_both_written(self):
        text = "# 2026-01-01\n\n## Ideas\n\n"
        r1 = append_under_heading(text, "## Ideas", "- 14:00 — first idea")
        r2 = append_under_heading(r1, "## Ideas", "- 15:30 — second idea")
        self.assertIn("first idea", r2)
        self.assertIn("second idea", r2)

    def test_non_timestamp_entry_still_deduped(self):
        text = "# 2026-01-01\n\n## Notes\n\n"
        r1 = append_under_heading(text, "## Notes", "- some note")
        r2 = append_under_heading(r1, "## Notes", "- some note")
        self.assertEqual(r1, r2)
        self.assertEqual(r1.count("some note"), 1)

    def test_timestamp_and_plain_text_same_body_deduped(self):
        text = "# 2026-01-01\n\n## Ideas\n\n"
        r1 = append_under_heading(text, "## Ideas", "- 14:00 — cool idea")
        # Same body without timestamp → should not add again
        r2 = append_under_heading(r1, "## Ideas", "- 16:00 — cool idea")
        self.assertEqual(r2.count("cool idea"), 1)


class TestExtractSections(unittest.TestCase):

    _NOTE = (
        "# 2026-01-15\n\n"
        "## Current Focus\n\n"
        "- 09:00 — finish the NLU audit\n"
        "- 10:00 — write tests\n\n"
        "## Decisions\n\n"
        "- 11:30 — use stdlib-only in bridge\n\n"
        "## Ideas\n\n\n"
        "## Bugs / Fixes\n\n"
        "- found null-pointer in backup\n\n"
        "## Pending Approval\n\n"
        "<!-- ADWI:DAILY-SUMMARY:START -->\ngenerated\n<!-- ADWI:DAILY-SUMMARY:END -->\n"
    )

    def test_extracts_populated_sections(self):
        result = extract_sections(self._NOTE)
        self.assertIn("## Current Focus", result)
        self.assertIn("## Decisions", result)
        self.assertIn("## Bugs / Fixes", result)

    def test_empty_section_not_in_result(self):
        result = extract_sections(self._NOTE)
        self.assertNotIn("## Ideas", result)

    def test_entry_values_are_bullet_lines(self):
        result = extract_sections(self._NOTE)
        for entry in result["## Current Focus"]:
            self.assertTrue(entry.startswith("- ") or entry.startswith("* "))

    def test_marker_block_content_excluded(self):
        result = extract_sections(self._NOTE)
        all_entries = [e for entries in result.values() for e in entries]
        self.assertNotIn("generated", all_entries)

    def test_specific_sections_filter(self):
        result = extract_sections(self._NOTE, ["## Decisions"])
        self.assertIn("## Decisions", result)
        self.assertNotIn("## Current Focus", result)

    def test_count_of_focus_entries(self):
        result = extract_sections(self._NOTE)
        self.assertEqual(len(result["## Current Focus"]), 2)

    def test_plan_block_content_excluded(self):
        """Generated ADWI:DAILY-PLAN content must not appear in section extracts."""
        note = (
            "# 2026-01-15\n\n"
            "## Current Focus\n\n"
            "- 09:00 — real task\n\n"
            "<!-- ADWI:DAILY-PLAN:START -->\n"
            "## Daily Plan\n- plan-only entry\n"
            "<!-- ADWI:DAILY-PLAN:END -->\n"
        )
        result = extract_sections(note)
        all_entries = [e for entries in result.values() for e in entries]
        self.assertNotIn("- plan-only entry", all_entries)


class TestCollectDailyEntries(unittest.TestCase):

    def setUp(self):
        import tempfile, shutil
        self._tmp = Path(tempfile.mkdtemp())
        self._vault = self._tmp / "vault"
        (self._vault / "daily-notes").mkdir(parents=True)
        self._note_16 = (
            "# 2026-01-16\n\n"
            "## Ideas\n\n"
            "- 09:00 — idea on the 16th\n\n"
        )
        self._note_17 = (
            "# 2026-01-17\n\n"
            "## Decisions\n\n"
            "- 10:00 — decided to use stdlib\n\n"
        )
        (self._vault / "daily-notes" / "2026-01-16.md").write_text(self._note_16)
        (self._vault / "daily-notes" / "2026-01-17.md").write_text(self._note_17)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_collects_entries_across_range(self):
        result = collect_daily_entries(self._vault, "2026-01-16", "2026-01-17")
        dates = {r["date"] for r in result}
        self.assertIn("2026-01-16", dates)
        self.assertIn("2026-01-17", dates)

    def test_missing_dates_skipped(self):
        result = collect_daily_entries(self._vault, "2026-01-14", "2026-01-17")
        dates = {r["date"] for r in result}
        self.assertNotIn("2026-01-14", dates)
        self.assertNotIn("2026-01-15", dates)

    def test_result_structure(self):
        result = collect_daily_entries(self._vault, "2026-01-16", "2026-01-16")
        self.assertEqual(len(result), 1)
        r = result[0]
        self.assertIn("date", r)
        self.assertIn("section", r)
        self.assertIn("entries", r)
        self.assertIn("path", r)

    def test_empty_range_returns_empty(self):
        result = collect_daily_entries(self._vault, "2026-02-01", "2026-02-05")
        self.assertEqual(result, [])

    def test_single_day_entries_correct(self):
        result = collect_daily_entries(self._vault, "2026-01-16", "2026-01-16")
        self.assertEqual(result[0]["section"], "## Ideas")
        self.assertIn("- 09:00 — idea on the 16th", result[0]["entries"])


if __name__ == "__main__":
    unittest.main()
