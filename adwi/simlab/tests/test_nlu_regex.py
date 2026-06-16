"""
adwi/simlab/tests/test_nlu_regex.py

Focused regression tests for _REGEX_INTENTS in adwi/adwi_cli.py.
Tests every confirmed bug from the 2026-06-15 NLU eval master report
plus all Phase B new-intent patterns.

Run: python3 -m unittest adwi/simlab/tests/test_nlu_regex.py -v
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: extract _REGEX_INTENTS without importing the full adwi_cli module
# (avoids triggering Ollama, Qdrant, or hardware checks at test time).
# ---------------------------------------------------------------------------

_CLI_PATH = Path(__file__).resolve().parents[3] / "adwi" / "adwi_cli.py"

def _load_regex_intents():
    src = _CLI_PATH.read_text()
    start = src.index("_REGEX_INTENTS = [")
    end   = src.index("\ndef _regex_prefilter")
    ns: dict = {}
    exec(src[start:end], {"re": re}, ns)   # noqa: S102
    return ns["_REGEX_INTENTS"]

_REGEX_INTENTS = _load_regex_intents()


def _classify(text: str) -> str | None:
    """Replicate _regex_prefilter from adwi_cli.py."""
    for pattern, intent in _REGEX_INTENTS:
        if pattern.search(text):
            return intent
    return None


# ---------------------------------------------------------------------------
# Bug 1 — Status regex word-boundary false positives
# ---------------------------------------------------------------------------

class TestBug1StatusWordBoundary(unittest.TestCase):
    """Regex word boundaries prevent 'is'/'are'/'down'/'up' matching as
    substrings inside longer words (list→is, downloads→down, backup→up)."""

    def test_list_files_downloads_no_status(self):
        # Previously "l[is]t files...down[loads]" triggered status.
        result = _classify("list files in my downloads folder")
        self.assertNotEqual(result, "status",
            "'list files in my downloads folder' must NOT route to status")

    def test_downloads_word_no_status(self):
        result = _classify("this downloads fine")
        self.assertNotEqual(result, "status",
            "'this downloads fine' must NOT route to status via 'is'+'down'")

    def test_backup_up_no_status(self):
        # 'back[up]' contains 'up' — must not trigger status.
        result = _classify("is my backup recent")
        self.assertNotEqual(result, "status",
            "'backup' contains 'up' but must NOT trigger status")

    def test_real_status_is_running(self):
        self.assertEqual(_classify("is everything running"), "status")

    def test_real_status_are_services_up(self):
        self.assertEqual(_classify("are services up"), "status")

    def test_real_status_ollama_running(self):
        self.assertEqual(_classify("is ollama running"), "status")

    def test_real_status_is_down(self):
        self.assertEqual(_classify("is the stack down"), "status")


# ---------------------------------------------------------------------------
# Bug 2 — large_files must win over disk_usage
# ---------------------------------------------------------------------------

class TestBug2LargeFilesOrdering(unittest.TestCase):
    """disk_usage previously swallowed 'biggest/largest files' prompts because
    its regex appeared first with a superset pattern."""

    def test_biggest_files(self):
        self.assertEqual(_classify("what are the biggest files"), "large_files")

    def test_largest_files_home(self):
        self.assertEqual(_classify("largest files in my home directory"), "large_files")

    def test_top_n_biggest(self):
        self.assertEqual(_classify("top 10 biggest files"), "large_files")

    def test_huge_files(self):
        self.assertEqual(_classify("show me the huge files"), "large_files")

    def test_files_over_size(self):
        self.assertEqual(_classify("files over 500MB"), "large_files")

    def test_heaviest_on_disk_still_disk_usage(self):
        # "heaviest stuff on disk" — no 'files' object → disk_usage wins
        self.assertEqual(_classify("what's the heaviest stuff on disk"), "disk_usage")

    def test_disk_usage_still_works(self):
        self.assertEqual(_classify("how much disk space do I have"), "disk_usage")

    def test_check_disk(self):
        self.assertEqual(_classify("check my disk"), "disk_usage")

    def test_disk_analysis(self):
        self.assertEqual(_classify("disk space analysis"), "disk_usage")


# ---------------------------------------------------------------------------
# Bug 3 — self_heal must beat status for service-error prompts
# ---------------------------------------------------------------------------

class TestBug3SelfHealBeforeStatus(unittest.TestCase):
    """Status regex fired first on 'docker is not working' because self_heal
    appeared after it and only handled verb-first ordering."""

    def test_docker_not_working_repair(self):
        # Subject-first ordering: docker (subject) + not working (verb)
        self.assertEqual(_classify("docker is not working repair"), "self_heal")

    def test_adwi_isnt_working(self):
        # "isn't" contraction variation
        self.assertEqual(_classify("adwi isn't working properly"), "self_heal")

    def test_ollama_is_broken(self):
        self.assertEqual(_classify("ollama is broken"), "self_heal")

    def test_fix_docker_service(self):
        # Verb-first: fix ... service
        self.assertEqual(_classify("fix the docker service"), "self_heal")

    def test_stack_crashing(self):
        self.assertEqual(_classify("the stack is crashing"), "self_heal")


# ---------------------------------------------------------------------------
# Bug 4 — obsidian_daily must not be swallowed by obsidian_search
# ---------------------------------------------------------------------------

class TestBug4ObsidianDailyGuard(unittest.TestCase):
    """obsidian_search regex '(open|read|show).{0,10}note' previously fired
    on daily-note queries before any obsidian_daily pattern existed."""

    def test_daily_note(self):
        self.assertEqual(_classify("read my daily note"), "obsidian_daily")

    def test_open_todays_note(self):
        self.assertEqual(_classify("open today's note"), "obsidian_daily")

    def test_obsidian_daily_explicit(self):
        self.assertEqual(_classify("open my obsidian daily"), "obsidian_daily")

    def test_obsidian_search_still_works(self):
        # Generic vault search must still reach obsidian_search
        self.assertIn(
            _classify("search my obsidian vault for meeting notes"),
            ("obsidian_search", "rag_search"),
        )

    def test_open_obsidian_notes_is_search(self):
        self.assertEqual(_classify("open my obsidian notes"), "obsidian_search")


# ---------------------------------------------------------------------------
# Bug 7 — git_status regex broadened
# ---------------------------------------------------------------------------

class TestBug7GitStatusBroadened(unittest.TestCase):
    """git_status only caught 'git <subcommand>' and 3 literal phrases;
    11 common git queries routed to chat/memory/disk."""

    def test_show_recent_commits(self):
        self.assertEqual(_classify("show recent commits"), "git_status")

    def test_uncommitted_changes(self):
        self.assertEqual(_classify("are there uncommitted changes"), "git_status")

    def test_current_branch(self):
        self.assertEqual(_classify("what's the current branch"), "git_status")

    def test_unstaged_changes(self):
        self.assertEqual(_classify("show unstaged changes"), "git_status")

    def test_is_repo_clean(self):
        self.assertEqual(_classify("is the repo clean"), "git_status")

    def test_git_stat(self):
        self.assertEqual(_classify("git stat"), "git_status")

    def test_staged_files(self):
        self.assertEqual(_classify("show staged files"), "git_status")

    def test_explicit_git_status_still_works(self):
        self.assertEqual(_classify("run git status"), "git_status")

    def test_git_log(self):
        self.assertEqual(_classify("git log"), "git_status")


# ---------------------------------------------------------------------------
# Phase B — New intent patterns
# ---------------------------------------------------------------------------

class TestPhaseB_Nightly(unittest.TestCase):
    def test_nightly_status(self):
        self.assertEqual(_classify("nightly status"), "nightly_status")

    def test_when_nightly_ran(self):
        self.assertEqual(_classify("when did nightly last run"), "nightly_status")

    def test_show_nightly_log(self):
        self.assertEqual(_classify("show nightly log"), "nightly_status")

    def test_run_nightly(self):
        self.assertEqual(_classify("run nightly"), "nightly_run")

    def test_trigger_nightly_maintenance(self):
        self.assertEqual(_classify("trigger nightly maintenance"), "nightly_run")


class TestPhaseB_ModelSwitching(unittest.TestCase):
    def test_what_model_am_i_using(self):
        self.assertEqual(_classify("what model am I using"), "model_status")

    def test_which_model_active(self):
        self.assertEqual(_classify("which model is active"), "model_status")

    def test_show_model_status(self):
        self.assertEqual(_classify("show model status"), "model_status")

    def test_switch_to_local_model(self):
        self.assertEqual(_classify("switch to local model"), "use_local")

    def test_use_local_llm(self):
        self.assertEqual(_classify("use local llm"), "use_local")

    def test_use_qwen(self):
        self.assertEqual(_classify("use qwen"), "use_local")

    def test_switch_to_cloud(self):
        self.assertEqual(_classify("switch to cloud"), "use_cloud")

    def test_use_gemini(self):
        self.assertEqual(_classify("use gemini"), "use_cloud")


class TestPhaseB_Voice(unittest.TestCase):
    def test_voice_input(self):
        self.assertEqual(_classify("listen to my voice input"), "voice_in")

    def test_start_voice_recording(self):
        self.assertEqual(_classify("start voice recording"), "voice_in")

    def test_text_to_speech(self):
        self.assertEqual(_classify("text to speech"), "voice_out")

    def test_read_this_aloud(self):
        self.assertEqual(_classify("read this aloud"), "voice_out")

    def test_say_out_loud(self):
        self.assertEqual(_classify("say this out loud"), "voice_out")


class TestPhaseB_BackupOps(unittest.TestCase):
    def test_backup_status(self):
        self.assertEqual(_classify("backup status"), "backup_status")

    def test_last_backup_time(self):
        self.assertEqual(_classify("when was the last backup"), "backup_status")

    def test_is_backup_recent(self):
        self.assertEqual(_classify("is my backup recent"), "backup_status")

    def test_show_backup_log(self):
        self.assertEqual(_classify("show backup log"), "backup_log")

    def test_backup_history(self):
        self.assertEqual(_classify("backup history"), "backup_log")


class TestPhaseB_FileOps(unittest.TestCase):
    def test_list_files_downloads(self):
        # This was the Bug1 victim; now correctly → file_list
        self.assertEqual(_classify("list files in my downloads folder"), "file_list")

    def test_ls_documents(self):
        self.assertEqual(_classify("ls my documents folder"), "file_list")

    def test_what_files_in_tmp(self):
        self.assertEqual(_classify("what files are in /tmp"), "file_list")

    def test_read_py_file(self):
        self.assertEqual(_classify("read adwi_cli.py"), "file_read")

    def test_show_contents(self):
        self.assertEqual(_classify("show me the contents of .gitignore"), "file_read")

    def test_search_for_files(self):
        self.assertEqual(_classify("search for python files in my workspace"), "file_search")

    def test_find_all_yaml(self):
        self.assertEqual(_classify("find all yaml files"), "file_search")

    def test_locate_config(self):
        self.assertEqual(_classify("find files named config.yaml"), "file_search")


class TestPhaseB_EvalTest(unittest.TestCase):
    def test_eval_routing(self):
        self.assertEqual(_classify("run routing tests"), "eval_routing")

    def test_test_adwi(self):
        self.assertEqual(_classify("run adwi tests"), "test_adwi")

    def test_eval_adwi(self):
        self.assertEqual(_classify("evaluate adwi performance"), "eval_adwi")


# ---------------------------------------------------------------------------
# Regressions — patterns that must not change after patching
# ---------------------------------------------------------------------------

class TestRegressions(unittest.TestCase):
    """Guard against fixes that accidentally break previously working routes."""

    def test_disk_usage_basic(self):
        self.assertEqual(_classify("check my disk"), "disk_usage")

    def test_disk_usage_how_much(self):
        self.assertEqual(_classify("how much disk space do I have"), "disk_usage")

    def test_disk_usage_storage(self):
        self.assertEqual(_classify("storage usage breakdown"), "disk_usage")

    def test_generate_image(self):
        self.assertEqual(_classify("generate an image of a cat"), "generate_image")

    def test_generate_image_draw(self):
        self.assertEqual(_classify("draw me a picture of a sunset"), "generate_image")

    def test_git_status_explicit(self):
        self.assertEqual(_classify("run git status"), "git_status")

    def test_git_log(self):
        self.assertEqual(_classify("git log"), "git_status")

    def test_gmail_check(self):
        self.assertEqual(_classify("check my email"), "gmail")

    def test_web_search(self):
        self.assertEqual(_classify("search the web for llama3 benchmarks"), "web_search")

    def test_memory_recall(self):
        self.assertEqual(_classify("what do you remember about my setup?"), "memory_recall")

    def test_old_files(self):
        self.assertEqual(_classify("files I haven't opened in a year"), "old_files")

    def test_obsidian_search(self):
        self.assertEqual(_classify("search my obsidian notes for python"), "obsidian_search")

    def test_run_code(self):
        self.assertEqual(_classify("run this python script"), "run_code")

    def test_doctor_full_health_check(self):
        self.assertEqual(_classify("run a full health check"), "doctor")

    def test_doctor_deep_diagnostic(self):
        self.assertEqual(_classify("deep diagnostic please"), "doctor")


# ---------------------------------------------------------------------------
# Gmail Phases 1–3: read / open / thread / summarize / list_category
#                   archive / trash / mark_read / mark_unread / confirm / cancel
#                   draft_reply / compose / send / cancel_draft / show_draft
# ---------------------------------------------------------------------------

class TestGmailRoutingPhases1to3(unittest.TestCase):
    """Routing for Gmail Phases 1-3 — no Ollama required; pure regex."""

    # ── Phase 1 read / open ─────────────────────────────────────────────────

    def test_open_email_from_sender(self):
        self.assertEqual(_classify("open the email from Rahul"), "gmail_open")

    def test_open_latest_from(self):
        self.assertEqual(_classify("open the latest email from Priya"), "gmail_open")

    def test_read_email_number(self):
        self.assertEqual(_classify("read #3"), "gmail_read")

    def test_read_first(self):
        self.assertEqual(_classify("open the latest email"), "gmail_read")

    def test_summarize_this_email(self):
        self.assertEqual(_classify("summarize this email"), "gmail_summarize")

    def test_summarize_it_followup(self):
        # Classic multi-turn follow-up after opening an email
        self.assertEqual(_classify("summarize it"), "gmail_summarize")

    def test_tldr_that(self):
        self.assertEqual(_classify("tldr that"), "gmail_summarize")

    def test_tldr_thread(self):
        self.assertEqual(_classify("tldr the thread"), "gmail_summarize")

    def test_show_thread(self):
        self.assertEqual(_classify("show the thread"), "gmail_thread")

    def test_open_conversation(self):
        self.assertEqual(_classify("open the email conversation"), "gmail_thread")

    def test_list_promotions(self):
        self.assertEqual(_classify("show my promotions"), "gmail_list_category")

    def test_list_spam(self):
        self.assertEqual(_classify("show spam"), "gmail_list_category")

    def test_list_social(self):
        self.assertEqual(_classify("list social emails"), "gmail_list_category")

    # ── Phase 2 mutations ───────────────────────────────────────────────────

    def test_archive_promotions(self):
        self.assertEqual(_classify("archive all my promotions"), "gmail_archive")

    def test_archive_those(self):
        self.assertEqual(_classify("archive those emails"), "gmail_archive")

    def test_archive_from(self):
        self.assertEqual(_classify("archive emails from newsletters"), "gmail_archive")

    def test_trash_spam(self):
        self.assertEqual(_classify("trash all spam emails"), "gmail_trash")

    def test_trash_those(self):
        self.assertEqual(_classify("trash those messages"), "gmail_trash")

    def test_delete_promo_emails(self):
        self.assertEqual(_classify("delete all promotional emails"), "gmail_trash")

    def test_mark_as_read(self):
        self.assertEqual(_classify("mark all as read"), "gmail_mark_read")

    def test_mark_them_read(self):
        self.assertEqual(_classify("mark them as read"), "gmail_mark_read")

    def test_mark_as_unread(self):
        self.assertEqual(_classify("mark this as unread"), "gmail_mark_unread")

    def test_confirm_standalone(self):
        self.assertEqual(_classify("confirm"), "gmail_confirm")

    def test_yes_do_it(self):
        self.assertEqual(_classify("yes do it"), "gmail_confirm")

    def test_cancel_mutation(self):
        self.assertEqual(_classify("cancel"), "gmail_cancel")

    def test_never_mind(self):
        self.assertEqual(_classify("never mind"), "gmail_cancel")

    # ── Phase 3 draft / compose / send ──────────────────────────────────────

    def test_draft_reply_explicit(self):
        self.assertEqual(_classify("draft a reply"), "gmail_draft_reply")

    def test_reply_saying(self):
        self.assertEqual(_classify("reply saying I'll get back to you"), "gmail_draft_reply")

    def test_respond_saying(self):
        self.assertEqual(_classify("respond saying sounds good"), "gmail_draft_reply")

    def test_write_back_that(self):
        self.assertEqual(_classify("write back that I received it"), "gmail_draft_reply")

    def test_compose_new_email(self):
        self.assertEqual(_classify("compose a new email"), "gmail_compose")

    def test_write_email(self):
        self.assertEqual(_classify("write an email to Priya"), "gmail_compose")

    def test_email_saying(self):
        self.assertEqual(_classify("email Rahul saying thanks for the update"), "gmail_compose")

    def test_send_it(self):
        self.assertEqual(_classify("send it"), "gmail_send_draft")

    def test_send_the_draft(self):
        self.assertEqual(_classify("send the draft"), "gmail_send_draft")

    def test_go_ahead_send(self):
        self.assertEqual(_classify("go ahead and send it"), "gmail_send_draft")

    def test_send_the_reply(self):
        self.assertEqual(_classify("send the reply"), "gmail_send_draft")

    def test_cancel_draft(self):
        self.assertEqual(_classify("cancel the draft"), "gmail_cancel_draft")

    def test_discard_draft(self):
        self.assertEqual(_classify("discard the draft"), "gmail_cancel_draft")

    def test_show_draft(self):
        self.assertEqual(_classify("show the draft"), "gmail_show_draft")

    def test_preview_draft(self):
        self.assertEqual(_classify("preview the draft"), "gmail_show_draft")

    def test_what_does_draft_say(self):
        self.assertEqual(_classify("what does the draft say"), "gmail_show_draft")

    # ── cancel vs cancel_draft ordering ─────────────────────────────────────

    def test_cancel_vs_cancel_draft_mutation(self):
        # Bare "cancel" → gmail_cancel (mutation cancel, NOT draft cancel)
        self.assertEqual(_classify("cancel"), "gmail_cancel")

    def test_cancel_draft_not_cancel(self):
        # "cancel the draft" must NOT hit gmail_cancel (hits gmail_cancel_draft)
        result = _classify("cancel the draft")
        self.assertEqual(result, "gmail_cancel_draft")
        self.assertNotEqual(result, "gmail_cancel")


# ---------------------------------------------------------------------------
# Gmail Phases 4–7: rewrite / CC-BCC / inbound attachments / outbound attachments
# ---------------------------------------------------------------------------

class TestGmailRoutingPhases4to7(unittest.TestCase):
    """Routing for Gmail Phases 4-7 — pure regex, no Ollama needed."""

    # ── Phase 4 rewrite ─────────────────────────────────────────────────────

    def test_make_it_shorter(self):
        self.assertEqual(_classify("make it shorter"), "gmail_rewrite_draft")

    def test_rewrite_professional(self):
        self.assertEqual(_classify("rewrite the draft to be more professional"), "gmail_rewrite_draft")

    def test_make_email_briefer(self):
        self.assertEqual(_classify("make the email briefer"), "gmail_rewrite_draft")

    def test_edit_more_direct(self):
        self.assertEqual(_classify("edit this to be more direct"), "gmail_rewrite_draft")

    def test_mention_in_email(self):
        self.assertEqual(_classify("mention the deadline in the email"), "gmail_rewrite_draft")

    def test_add_note_to_draft(self):
        # "add a note about X to the draft" → rewrite_draft (no file-type keyword)
        self.assertEqual(_classify("add a note about shipping costs to the draft"), "gmail_rewrite_draft")

    # ── Phase 5 CC / BCC ────────────────────────────────────────────────────

    def test_add_cc(self):
        self.assertEqual(_classify("add cc Priya"), "gmail_add_cc")

    def test_cc_on_draft(self):
        self.assertEqual(_classify("cc Priya on this draft"), "gmail_add_cc")

    def test_cc_on_this_email(self):
        self.assertEqual(_classify("cc me on the email"), "gmail_add_cc")

    def test_add_bcc(self):
        self.assertEqual(_classify("add bcc myself"), "gmail_add_bcc")

    def test_bcc_on_draft(self):
        self.assertEqual(_classify("bcc Rahul on this draft"), "gmail_add_bcc")

    def test_bcc_to_message(self):
        self.assertEqual(_classify("bcc me to the message"), "gmail_add_bcc")

    # ── Phase 6 inbound attachments ─────────────────────────────────────────

    def test_show_attachments(self):
        self.assertEqual(_classify("show attachments"), "gmail_list_attachments")

    def test_list_attachments(self):
        self.assertEqual(_classify("list attachments on this email"), "gmail_list_attachments")

    def test_any_attachments(self):
        self.assertEqual(_classify("any attachments?"), "gmail_list_attachments")

    def test_what_files_attached(self):
        self.assertEqual(_classify("what files are attached"), "gmail_list_attachments")

    def test_save_pdf(self):
        self.assertEqual(_classify("save the PDF"), "gmail_save_attachment")

    def test_download_invoice(self):
        self.assertEqual(_classify("download the invoice"), "gmail_save_attachment")

    def test_save_first_attachment(self):
        self.assertEqual(_classify("save the first attachment"), "gmail_save_attachment")

    def test_summarize_attached_pdf(self):
        self.assertEqual(_classify("summarize the attached PDF"), "gmail_summarize_attachment")

    def test_whats_in_attachment(self):
        self.assertEqual(_classify("what's in the attachment"), "gmail_summarize_attachment")

    def test_tldr_invoice(self):
        self.assertEqual(_classify("tldr the invoice"), "gmail_summarize_attachment")

    # ── Phase 7 outbound attach ─────────────────────────────────────────────

    def test_attach_pdf_to_draft(self):
        self.assertEqual(_classify("attach the PDF to this draft"), "gmail_attach_file")

    def test_attach_invoice_bare(self):
        self.assertEqual(_classify("attach the invoice"), "gmail_attach_file")

    def test_add_spreadsheet_to_email(self):
        self.assertEqual(_classify("add the spreadsheet to this email"), "gmail_attach_file")

    def test_include_report_in_the_draft(self):
        self.assertEqual(_classify("include the report in the draft"), "gmail_attach_file")

    def test_include_report_in_this_draft(self):
        self.assertEqual(_classify("include the report in this draft"), "gmail_attach_file")

    def test_attach_saved_attachment(self):
        self.assertEqual(_classify("attach that saved attachment"), "gmail_attach_file")

    def test_attach_deck_to_reply(self):
        self.assertEqual(_classify("attach the deck to this reply"), "gmail_attach_file")

    def test_attach_document(self):
        self.assertEqual(_classify("attach the document"), "gmail_attach_file")

    # ── Ordering guards: Phase 7 must beat Phase 4 ─────────────────────────

    def test_add_pdf_beats_rewrite(self):
        # gmail_attach_file must win over gmail_rewrite_draft
        result = _classify("add the PDF to this draft")
        self.assertEqual(result, "gmail_attach_file")
        self.assertNotEqual(result, "gmail_rewrite_draft")

    def test_include_invoice_beats_rewrite(self):
        result = _classify("include the invoice in the email")
        self.assertEqual(result, "gmail_attach_file")
        self.assertNotEqual(result, "gmail_rewrite_draft")

    def test_text_only_add_is_rewrite(self):
        # No file-type keyword → gmail_rewrite_draft, not gmail_attach_file
        result = _classify("add a paragraph about the timeline to the email")
        self.assertEqual(result, "gmail_rewrite_draft")
        self.assertNotEqual(result, "gmail_attach_file")

    # ── Phase 6 inbound must not bleed into Phase 7 outbound ───────────────

    def test_save_attachment_not_attach_file(self):
        # save/download → gmail_save_attachment, not gmail_attach_file
        result = _classify("save the attached document")
        self.assertEqual(result, "gmail_save_attachment")
        self.assertNotEqual(result, "gmail_attach_file")

    def test_summarize_pdf_not_attach_file(self):
        result = _classify("summarize the PDF")
        self.assertEqual(result, "gmail_summarize_attachment")
        self.assertNotEqual(result, "gmail_attach_file")

    def test_list_attachments_not_attach_file(self):
        result = _classify("show attachments on this email")
        self.assertEqual(result, "gmail_list_attachments")
        self.assertNotEqual(result, "gmail_attach_file")


if __name__ == "__main__":
    unittest.main(verbosity=2)
