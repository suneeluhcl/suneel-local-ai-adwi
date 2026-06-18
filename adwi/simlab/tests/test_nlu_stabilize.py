"""
adwi/simlab/tests/test_nlu_stabilize.py

NLU stabilization sprint test suite — chat bleed, benchmark, organize families.
All tests are regex-only (no Ollama/network required).

Run: python3 -m unittest adwi/simlab/tests/test_nlu_stabilize.py -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_CLI_PATH = Path(__file__).resolve().parents[3] / "adwi" / "adwi_cli.py"


def _load_regex_intents():
    src = _CLI_PATH.read_text()
    start = src.index("_REGEX_INTENTS = [")
    end   = src.index("\ndef _regex_prefilter")
    ns: dict = {}
    exec(src[start:end], {"re": re}, ns)  # noqa: S102
    return ns["_REGEX_INTENTS"]


_REGEX_INTENTS = _load_regex_intents()


def _classify(text: str) -> str | None:
    for pattern, intent in _REGEX_INTENTS:
        if pattern.search(text):
            return intent
    return None


class TestBenchmarkFamily(unittest.TestCase):
    """Benchmark intent — FIX-SPRINT-001a/b/c."""

    def _check(self, prompt, expected="benchmark"):
        self.assertEqual(_classify(prompt), expected, msg=f"'{prompt}'")

    # Early guard: must beat status for "how fast is adwi"
    def test_how_fast_adwi_responding(self):
        self._check("how fast is adwi responding")

    def test_how_fast_llama_versioned(self):
        self._check("how fast is llama3.1:8b")

    def test_how_fast_llama_on_machine(self):
        self._check("how fast is llama3.1 on this machine")

    def test_how_fast_ollama(self):
        self._check("how fast is ollama responding")

    def test_how_fast_model(self):
        self._check("how fast is my model")

    # New patterns: tokens per second, inference speed, performant
    def test_tokens_per_second(self):
        self._check("how many tokens per second am i getting")

    def test_bare_tokens_per_sec(self):
        self._check("tokens per second right now")

    def test_inference_speed(self):
        self._check("what's my inference speed")

    def test_inference_rate(self):
        self._check("my inference rate seems slow")

    def test_how_performant_llama(self):
        self._check("how performant is llama3.1:8b on my mac")

    def test_how_performant_model(self):
        self._check("how performant is the model")

    # Non-regressions: these must stay as status, not benchmark
    def test_is_adwi_running_stays_status(self):
        self._check("is adwi running", "status")

    def test_is_ollama_up_stays_status(self):
        self._check("is ollama up", "status")

    def test_is_adwi_available_stays_status(self):
        self._check("is adwi available", "status")

    # Advisory benchmark → LLM (no regex match expected)
    def test_advisory_why_slow_no_regex(self):
        # "why is ollama slow" is advisory → LLM handles as chat; no regex should fire to benchmark
        got = _classify("why is ollama slow")
        self.assertNotEqual(got, "benchmark", msg="advisory → should not fire benchmark regex")

    def test_advisory_how_to_speed_up(self):
        got = _classify("how can I speed up my LLM")
        self.assertNotEqual(got, "benchmark")


class TestOrganizeFamily(unittest.TestCase):
    """Organize intent — regex coverage."""

    def _check(self, prompt, expected="organize"):
        self.assertEqual(_classify(prompt), expected, msg=f"'{prompt}'")

    def test_organize_workspace(self):
        self._check("help organize my workspace")

    def test_organize_bare(self):
        self._check("organize my files")

    def test_structure_project_folders(self):
        self._check("how to structure my project folders")

    def test_sort_downloads(self):
        self._check("sort my downloads folder")

    def test_recommend_folder_structure(self):
        self._check("recommend a folder structure for my projects")

    def test_tidy_files(self):
        self._check("tidy up my files")

    # Collisions: must NOT fire organize for cleanup-intent prompts
    def test_purge_old_downloads_not_organize(self):
        self.assertNotEqual(_classify("purge old downloads"), "organize")

    def test_delete_junk_not_organize(self):
        self.assertNotEqual(_classify("delete my junk files"), "organize")


class TestCleanupFamily(unittest.TestCase):
    """Cleanup intent — FIX-SPRINT-004: purge/remove leftover before old_files fires."""

    def _check(self, prompt, expected="cleanup"):
        self.assertEqual(_classify(prompt), expected, msg=f"'{prompt}'")

    def test_purge_old_downloads(self):
        self._check("purge old downloads")

    def test_remove_leftover_installers(self):
        self._check("remove leftover installers")

    def test_clean_old_cache_files(self):
        self._check("clean old cache files")

    def test_remove_old_packages(self):
        self._check("remove old packages")

    def test_delete_old_temp_files(self):
        self._check("delete old temp files")

    def test_clear_old_logs(self):
        self._check("clear old logs")

    # Non-regressions: old_files must still work
    def test_find_old_files_stays_old_files(self):
        self._check("find files I haven't opened in a year", "old_files")

    def test_stale_files_stays_old_files(self):
        self._check("show stale files", "old_files")

    def test_leftover_data_stays_old_files(self):
        # "leftover data" without a cleanup verb → old_files
        self._check("show leftover data", "old_files")


class TestWhatNextVsCapabilities(unittest.TestCase):
    """what_next guard — FIX-SPRINT-002: before capabilities broad pattern."""

    def test_generate_ideas_adwi_features(self):
        self.assertEqual(_classify("generate ideas for new adwi features"), "what_next")

    def test_low_hanging_fruit(self):
        self.assertEqual(_classify("what adwi features are low-hanging fruit"), "what_next")

    def test_brainstorm_improvements(self):
        self.assertEqual(_classify("brainstorm adwi improvements"), "what_next")

    # Non-regressions: capabilities must still fire
    def test_adwi_commands_still_capabilities(self):
        self.assertEqual(_classify("show me adwi commands"), "capabilities")

    def test_adwi_capabilities_still_capabilities(self):
        self.assertEqual(_classify("what are adwi's capabilities"), "capabilities")

    def test_adwi_feature_list_capabilities(self):
        # CYCLE-6 fix: "adwi feature list" → capabilities (guard added before what_next)
        self.assertEqual(_classify("adwi feature list"), "capabilities")


class TestInspectCodeVsGenerateImage(unittest.TestCase):
    """inspect_code guard — FIX-SPRINT-003: function names before generate_image."""

    def test_function_in_adwi(self):
        self.assertEqual(_classify("generate_image function in adwi"), "inspect_code")

    def test_handler_in_adwi(self):
        self.assertEqual(_classify("show me the generate_image handler"), "inspect_code")

    def test_cmd_function_in_adwi(self):
        self.assertEqual(_classify("cmd_gmail_compose function in adwi"), "inspect_code")

    # Non-regressions: generate_image must still fire
    def test_generate_sunset_stays_generate_image(self):
        self.assertEqual(_classify("generate an image of a sunset"), "generate_image")

    def test_create_picture_stays_generate_image(self):
        self.assertEqual(_classify("create a picture of a dog"), "generate_image")

    def test_draw_artwork_needs_image_word(self):
        # "draw a mountain landscape" has no "image/picture/photo" noun → no regex match (pre-existing)
        # correct cases that DO work:
        self.assertEqual(_classify("draw a mountain image"), "generate_image")
        self.assertEqual(_classify("create a picture of mountains"), "generate_image")


class TestDiskUsageAdvisoryGuard(unittest.TestCase):
    """chat guard — FIX-SPRINT-005: advisory disk questions must not fire disk_usage."""

    def test_what_generates_disk_usage(self):
        self.assertEqual(_classify("what generates the most disk usage on a mac"), "chat")

    def test_how_does_disk_space_get_used(self):
        self.assertEqual(_classify("how does disk space get used up"), "chat")

    def test_what_causes_disk_usage(self):
        self.assertEqual(_classify("what causes disk usage to grow"), "chat")

    def test_how_does_storage_fill_up(self):
        self.assertEqual(_classify("how does storage fill up"), "chat")

    # Non-regressions: action disk_usage must still fire
    def test_check_disk_usage(self):
        self.assertEqual(_classify("check my disk usage"), "disk_usage")

    def test_how_much_disk_space(self):
        self.assertEqual(_classify("how much disk space do I have"), "disk_usage")

    def test_whats_eating_disk(self):
        self.assertEqual(_classify("what's eating my disk space"), "disk_usage")

    def test_show_disk_usage(self):
        self.assertEqual(_classify("show disk usage"), "disk_usage")


class TestImplementIdeaVsWhatNext(unittest.TestCase):
    """implement_idea guard — FIX-SPRINT-006."""

    def test_implement_suggested_improvement(self):
        self.assertEqual(_classify("implement the suggested improvement"), "implement_idea")

    def test_implement_recommended_feature(self):
        self.assertEqual(_classify("implement the recommended feature"), "implement_idea")

    def test_build_proposed_change(self):
        self.assertEqual(_classify("build the proposed change"), "implement_idea")

    # Non-regressions: what_next must still fire
    def test_what_should_i_build_next(self):
        self.assertEqual(_classify("what should I build next for adwi"), "what_next")

    def test_suggest_adwi_improvements(self):
        self.assertEqual(_classify("suggest adwi improvements"), "what_next")


class TestWebSearchVsGmailSummarize(unittest.TestCase):
    """web_search guard — FIX-SPRINT-007: search+summarize combo."""

    def test_search_web_and_summarize(self):
        self.assertEqual(_classify("search web for ollama news and summarize it"), "web_search")

    def test_search_online_and_summarize(self):
        self.assertEqual(_classify("search online for llama news and give me a summary"), "web_search")

    def test_look_up_for_and_summarize(self):
        self.assertEqual(_classify("look up for kubernetes news and tldr it"), "web_search")

    # Non-regressions: gmail_summarize must still fire for email context
    def test_summarize_this_email_stays_gmail(self):
        self.assertEqual(_classify("summarize this email"), "gmail_summarize")

    def test_summarize_the_thread_stays_gmail(self):
        self.assertEqual(_classify("summarize the thread"), "gmail_summarize")

    def test_tldr_email_stays_gmail(self):
        self.assertEqual(_classify("tldr this email"), "gmail_summarize")

    def test_summarize_it_stays_gmail(self):
        self.assertEqual(_classify("summarize it"), "gmail_summarize")


class TestGmailNonRegression(unittest.TestCase):
    """Verify all Gmail gains from burn-in remain intact."""

    def _c(self, prompt, expected):
        self.assertEqual(_classify(prompt), expected, msg=f"'{prompt}'")

    def test_open_latest_message(self):
        self._c("open the latest message", "gmail_read")

    def test_which_draft_pdf(self):
        self._c("which draft has the PDF attached", "gmail_list_drafts")

    def test_send_email_to_x(self):
        self._c("send an email to my team", "gmail_compose")

    def test_send_the_draft(self):
        self._c("send the draft", "gmail_send_draft")

    def test_go_ahead_and_send(self):
        self._c("go ahead and send", "gmail_send_draft")

    def test_rewrite_the_draft(self):
        self._c("rewrite the draft", "gmail_rewrite_draft")

    def test_flag_as_unread(self):
        self._c("flag this as unread", "gmail_mark_unread")

    def test_move_to_archive(self):
        self._c("move to archive", "gmail_archive")

    def test_triage_inbox(self):
        self._c("which emails need action", "gmail_triage")

    def test_any_files_attached(self):
        self._c("any files attached to this email", "gmail_list_attachments")


if __name__ == "__main__":
    unittest.main(verbosity=2)
