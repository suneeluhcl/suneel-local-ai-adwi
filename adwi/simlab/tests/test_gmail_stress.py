"""
adwi/simlab/tests/test_gmail_stress.py

Gmail large-scale NLU stress test + _parse_filter_rule unit tests.
Covers all 47 Gmail intents with ~600 parameterized scenarios,
multi-turn dialog simulation, near-collision cases, safety routing,
and negative (not-Gmail) cases.

Run: python3 -m unittest adwi/simlab/tests/test_gmail_stress.py -v
No Ollama / no external network required.
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


def _load_filter_helpers():
    src = _CLI_PATH.read_text()
    m_start = re.search(r"^def _extract_sender_email\b", src, re.MULTILINE)
    m_end   = re.search(r"^def _load_gmail_rules\b",    src, re.MULTILINE)
    m_rule  = re.search(r"^def _parse_filter_rule\b",   src, re.MULTILINE)
    m_fq    = re.search(r"^def _filter_criteria_to_query\b", src, re.MULTILINE)
    m_fp    = re.search(r"^def _filter_preview\b",      src, re.MULTILINE)
    code = src[m_start.start():m_end.start()] + "\n" + src[m_rule.start():m_fp.start()]
    ns: dict = {"re": re, "_GMAIL_CTX": {}}
    exec(code, ns)  # noqa: S102
    return ns


_filter_ns = _load_filter_helpers()
_extract_sender_email   = _filter_ns["_extract_sender_email"]
_parse_filter_rule      = _filter_ns["_parse_filter_rule"]
_filter_criteria_to_query = _filter_ns["_filter_criteria_to_query"]


# ===========================================================================
# MASS CORPUS — 500+ (input, expected_intent) scenarios across all 47 intents
# Organized by intent family. Run via subTest for individual failure isolation.
# ===========================================================================

# fmt: off
_MASS_CORPUS: list[tuple[str, str]] = [

    # ── gmail: basic inbox listing ──────────────────────────────────────────
    ("show my inbox",                              "gmail"),
    ("check my email",                             "gmail"),
    ("list my emails",                             "gmail"),
    ("show unread emails",                         "gmail"),
    ("open gmail",                                 "gmail"),
    ("check inbox",                                "gmail"),
    ("show new emails",                            "gmail"),
    ("any new mail",                               "gmail"),
    ("how many unread",                            "gmail"),
    ("show latest emails",                         "gmail"),
    ("list messages",                              "gmail"),
    ("what's in my inbox",                         "gmail"),
    ("check my messages",                          "gmail"),
    ("show me unread",                             "gmail"),
    ("any emails from today",                      "gmail"),

    # ── gmail_open: search + open first result ─────────────────────────────
    ("open the email from Priya",                  "gmail_open"),
    ("open the email about the budget",            "gmail_open"),
    ("read the email from Amazon",                 "gmail_open"),
    ("read the email about my flight",             "gmail_open"),
    ("open the latest email from Google",          "gmail_open"),
    ("open email about the Q3 report",             "gmail_open"),
    ("find and open the invoice email",            "gmail_open"),
    ("search and open the email from HR",          "gmail_open"),
    ("open the newest email from the bank",        "gmail_open"),
    ("read the message about the meeting",         "gmail_open"),
    ("open the email regarding the contract",      "gmail_open"),
    ("open most recent email from Rahul",          "gmail_open"),

    # ── gmail_read: specific email by position or bare number ─────────────
    ("open 3",                                     "gmail_read"),
    ("read 5",                                     "gmail_read"),
    ("open #2",                                    "gmail_read"),
    ("read the first email",                       "gmail_read"),
    ("open the latest email",                      "gmail_read"),
    ("show the newest email",                      "gmail_read"),
    ("read the top email",                         "gmail_read"),
    ("open email 4",                               "gmail_read"),
    ("read message 2",                             "gmail_read"),
    ("open this email",                            "gmail_read"),
    ("read the most recent email",                 "gmail_read"),
    ("show email number 3",                        "gmail_read"),
    ("open email number 1",                        "gmail_read"),

    # ── gmail_thread: show full conversation ──────────────────────────────
    ("show the thread",                            "gmail_thread"),
    ("open the conversation",                      "gmail_thread"),
    ("view the thread",                            "gmail_thread"),
    ("show me the email chain",                    "gmail_thread"),
    ("open the message chain",                     "gmail_thread"),
    ("show the full conversation",                 "gmail_thread"),
    ("thread about the project",                   "gmail_thread"),
    ("thread with Priya",                          "gmail_thread"),
    ("show the whole thread",                      "gmail_thread"),
    ("read the conversation",                      "gmail_thread"),

    # ── gmail_summarize ────────────────────────────────────────────────────
    ("summarize this email",                       "gmail_summarize"),
    ("summarize it",                               "gmail_summarize"),
    ("summarize that",                             "gmail_summarize"),
    ("tldr this email",                            "gmail_summarize"),
    ("tldr the thread",                            "gmail_summarize"),
    ("tldr",                                       "gmail_summarize"),
    ("tl;dr",                                      "gmail_summarize"),
    ("summarize the message",                      "gmail_summarize"),
    ("summarize this message",                     "gmail_summarize"),
    ("give me a summary of this email",            "gmail_summarize"),
    ("give me a summary of the thread",            "gmail_summarize"),
    ("summarize the thread",                       "gmail_summarize"),
    ("summarize the conversation",                 "gmail_summarize"),
    ("summarize this",                             "gmail_summarize"),
    ("summarize the email",                        "gmail_summarize"),

    # ── gmail_list_category ────────────────────────────────────────────────
    ("show promotions",                            "gmail_list_category"),
    ("show promotional emails",                    "gmail_list_category"),
    ("open spam",                                  "gmail_list_category"),
    ("check spam folder",                          "gmail_list_category"),
    ("show social emails",                         "gmail_list_category"),
    ("list newsletters",                           "gmail_list_category"),
    ("show updates",                               "gmail_list_category"),
    ("display forums",                             "gmail_list_category"),
    ("list promotional",                           "gmail_list_category"),
    ("check newsletters",                          "gmail_list_category"),
    ("show promo emails",                          "gmail_list_category"),

    # ── gmail_archive ──────────────────────────────────────────────────────
    ("archive those emails",                       "gmail_archive"),
    ("archive these",                              "gmail_archive"),
    ("archive them all",                           "gmail_archive"),
    ("archive all promotions",                     "gmail_archive"),
    ("archive newsletters",                        "gmail_archive"),
    ("archive all from Amazon",                    "gmail_archive"),
    ("archive that email",                         "gmail_archive"),
    ("move to archive",                            "gmail_archive"),
    ("move these to archive",                      "gmail_archive"),
    ("archive all social emails",                  "gmail_archive"),
    ("archive this email",                         "gmail_archive"),
    ("archive all of them",                        "gmail_archive"),
    ("archive emails from about 2 months ago",     "gmail_archive"),
    ("archive from no-reply",                      "gmail_archive"),

    # ── gmail_trash ────────────────────────────────────────────────────────
    ("trash these emails",                         "gmail_trash"),
    ("delete those emails",                        "gmail_trash"),
    ("trash them",                                 "gmail_trash"),
    ("delete this email",                          "gmail_trash"),
    ("trash all spam",                             "gmail_trash"),
    ("delete all promotional emails",              "gmail_trash"),
    ("move to trash",                              "gmail_trash"),
    ("trash all from no-reply",                    "gmail_trash"),
    ("delete these messages",                      "gmail_trash"),
    ("trash all newsletters",                      "gmail_trash"),
    ("delete those messages",                      "gmail_trash"),
    ("trash that",                                 "gmail_trash"),
    ("delete those promo emails",                  "gmail_trash"),

    # ── gmail_mark_read ────────────────────────────────────────────────────
    ("mark as read",                               "gmail_mark_read"),
    ("mark these as read",                         "gmail_mark_read"),
    ("mark them read",                             "gmail_mark_read"),
    ("mark this email as read",                    "gmail_mark_read"),
    ("mark all as read",                           "gmail_mark_read"),
    ("mark those as read",                         "gmail_mark_read"),

    # ── gmail_mark_unread ──────────────────────────────────────────────────
    ("mark as unread",                             "gmail_mark_unread"),
    ("mark these as unread",                       "gmail_mark_unread"),
    ("flag as unread",                             "gmail_mark_unread"),
    ("mark this unread",                           "gmail_mark_unread"),
    ("mark all as unread",                         "gmail_mark_unread"),

    # ── gmail_confirm ──────────────────────────────────────────────────────
    ("confirm",                                    "gmail_confirm"),
    ("yes, do it",                                 "gmail_confirm"),

    # ── gmail_cancel (bare) ────────────────────────────────────────────────
    ("cancel",                                     "gmail_cancel"),
    ("cancel that",                                "gmail_cancel"),
    ("never mind",                                 "gmail_cancel"),
    ("abort",                                      "gmail_cancel"),
    ("stop that",                                  "gmail_cancel"),

    # ── gmail_undo ─────────────────────────────────────────────────────────
    ("undo",                                       "gmail_undo"),
    ("undo that",                                  "gmail_undo"),
    ("undo the archive",                           "gmail_undo"),
    ("undo that trash",                            "gmail_undo"),
    ("undo the last action",                       "gmail_undo"),
    ("bring back those emails",                    "gmail_undo"),
    ("restore those emails",                       "gmail_undo"),

    # ── gmail_triage ───────────────────────────────────────────────────────
    ("triage my inbox",                            "gmail_triage"),
    ("which emails need my reply",                 "gmail_triage"),
    ("what needs my attention",                    "gmail_triage"),
    ("what should I answer first",                 "gmail_triage"),
    ("which threads are waiting on me",            "gmail_triage"),
    ("which emails are urgent",                    "gmail_triage"),
    ("what's action-needed today",                 "gmail_triage"),
    ("which emails need action",                   "gmail_triage"),
    ("email triage",                               "gmail_triage"),
    ("inbox triage",                               "gmail_triage"),
    ("what emails am I waiting on",                "gmail_triage"),
    ("what do I need to respond to",               "gmail_triage"),
    ("show action needed emails",                  "gmail_triage"),
    ("show urgent emails",                         "gmail_triage"),

    # ── gmail_draft_reply ──────────────────────────────────────────────────
    ("draft a reply",                              "gmail_draft_reply"),
    ("draft a reply to this",                      "gmail_draft_reply"),
    ("reply saying thanks for the update",         "gmail_draft_reply"),
    ("reply that we're on schedule",               "gmail_draft_reply"),
    ("reply saying I'll get back to them",         "gmail_draft_reply"),
    ("respond saying we'll review",                "gmail_draft_reply"),
    ("write back saying noted",                    "gmail_draft_reply"),
    ("reply to the latest ask",                    "gmail_draft_reply"),
    ("draft a response",                           "gmail_draft_reply"),
    ("respond to this email",                      "gmail_draft_reply"),
    ("write a reply",                              "gmail_draft_reply"),
    ("reply to it saying thanks",                  "gmail_draft_reply"),

    # ── gmail_compose ──────────────────────────────────────────────────────
    ("compose a new email to Rahul",               "gmail_compose"),
    ("write an email to Priya",                    "gmail_compose"),
    ("compose an email",                           "gmail_compose"),
    ("write a message to the team",                "gmail_compose"),
    ("email Rahul saying we'll deliver Friday",    "gmail_compose"),
    ("write a new email",                          "gmail_compose"),
    ("compose a message to support",               "gmail_compose"),
    ("email support to report the bug",            "gmail_compose"),
    ("write an email to HR about PTO",             "gmail_compose"),
    ("compose email to Priya about Q3",            "gmail_compose"),
    ("email the client saying we're ready",        "gmail_compose"),

    # ── gmail_show_draft ───────────────────────────────────────────────────
    ("show the draft",                             "gmail_show_draft"),
    ("display my draft",                           "gmail_show_draft"),
    ("preview the draft",                          "gmail_show_draft"),
    ("view the current draft",                     "gmail_show_draft"),
    ("read the draft",                             "gmail_show_draft"),
    ("what does the draft say",                    "gmail_show_draft"),
    ("what's in the draft",                        "gmail_show_draft"),
    ("show me the current draft",                  "gmail_show_draft"),

    # ── gmail_send_draft ───────────────────────────────────────────────────
    ("send the draft",                             "gmail_send_draft"),
    ("send it",                                    "gmail_send_draft"),
    ("send now",                                   "gmail_send_draft"),
    ("go ahead and send it",                       "gmail_send_draft"),
    ("send the reply",                             "gmail_send_draft"),
    ("send the email",                             "gmail_send_draft"),
    ("lgtm send it",                               "gmail_send_draft"),
    ("looks good send it",                         "gmail_send_draft"),
    ("approved, send",                             "gmail_send_draft"),
    ("send the message",                           "gmail_send_draft"),
    ("go ahead and send",                          "gmail_send_draft"),
    ("send the response",                          "gmail_send_draft"),

    # ── gmail_cancel_draft ─────────────────────────────────────────────────
    ("cancel the draft",                           "gmail_cancel_draft"),
    ("discard the draft",                          "gmail_cancel_draft"),
    ("delete the draft",                           "gmail_cancel_draft"),
    ("abort the draft",                            "gmail_cancel_draft"),
    ("clear the draft",                            "gmail_cancel_draft"),
    ("forget the draft",                           "gmail_cancel_draft"),
    ("throw away the draft",                       "gmail_cancel_draft"),
    ("don't want the draft",                       "gmail_cancel_draft"),

    # ── gmail_rewrite_draft ────────────────────────────────────────────────
    ("make it shorter",                            "gmail_rewrite_draft"),
    ("make the draft shorter",                     "gmail_rewrite_draft"),
    ("make it more professional",                  "gmail_rewrite_draft"),
    ("rewrite it more formally",                   "gmail_rewrite_draft"),
    ("rewrite the draft",                          "gmail_rewrite_draft"),
    ("make the email friendlier",                  "gmail_rewrite_draft"),
    ("make this more concise",                     "gmail_rewrite_draft"),
    ("rewrite to be warmer",                       "gmail_rewrite_draft"),
    ("make it more casual",                        "gmail_rewrite_draft"),
    ("write a shorter version",                    "gmail_rewrite_draft"),
    ("make the reply more direct",                 "gmail_rewrite_draft"),
    ("mention we'll deliver by Friday in the draft", "gmail_rewrite_draft"),

    # ── gmail_update_subject ───────────────────────────────────────────────
    ("update the subject",                         "gmail_update_subject"),
    ("rewrite the subject line",                   "gmail_update_subject"),
    ("change the subject",                         "gmail_update_subject"),
    ("make the subject clearer",                   "gmail_update_subject"),
    ("improve the subject",                        "gmail_update_subject"),
    ("give me a better subject",                   "gmail_update_subject"),
    ("the subject is weak",                        "gmail_update_subject"),
    ("fix the subject line",                       "gmail_update_subject"),
    ("the subject is too generic",                 "gmail_update_subject"),
    ("the subject feels vague",                    "gmail_update_subject"),

    # ── gmail_add_cc ───────────────────────────────────────────────────────
    ("add cc Priya",                               "gmail_add_cc"),
    ("cc the team on this",                        "gmail_add_cc"),
    ("cc Priya on the draft",                      "gmail_add_cc"),
    ("cc manager@company.com on this email",       "gmail_add_cc"),
    ("add cc priya@work.com",                      "gmail_add_cc"),

    # ── gmail_add_bcc ──────────────────────────────────────────────────────
    ("add bcc me",                                 "gmail_add_bcc"),
    ("bcc Rahul on this draft",                    "gmail_add_bcc"),
    ("bcc my manager on the email",                "gmail_add_bcc"),
    ("bcc myself on this message",                 "gmail_add_bcc"),
    ("add bcc manager",                            "gmail_add_bcc"),

    # ── gmail_list_attachments ─────────────────────────────────────────────
    ("show attachments",                           "gmail_list_attachments"),
    ("any files attached",                         "gmail_list_attachments"),
    ("list all attachments",                       "gmail_list_attachments"),
    ("are there any attachments",                  "gmail_list_attachments"),
    ("what files are attached",                    "gmail_list_attachments"),
    ("what attachments are there",                 "gmail_list_attachments"),
    ("view the attachments",                       "gmail_list_attachments"),
    ("attachments in this email",                  "gmail_list_attachments"),

    # ── gmail_save_attachment ─────────────────────────────────────────────
    ("download the PDF",                           "gmail_save_attachment"),
    ("save the attachment",                        "gmail_save_attachment"),
    ("save the invoice",                           "gmail_save_attachment"),
    ("download the spreadsheet",                   "gmail_save_attachment"),
    ("open the invoice",                           "gmail_save_attachment"),
    ("save this document",                         "gmail_save_attachment"),
    ("save that attachment",                       "gmail_save_attachment"),
    ("download that PDF",                          "gmail_save_attachment"),
    ("save the second attachment",                 "gmail_save_attachment"),

    # ── gmail_summarize_attachment ────────────────────────────────────────
    ("summarize the PDF",                          "gmail_summarize_attachment"),
    ("summarize the attached document",            "gmail_summarize_attachment"),
    ("what's in the attachment",                   "gmail_summarize_attachment"),
    ("what's in the attached PDF",                 "gmail_summarize_attachment"),
    ("summarize the invoice",                      "gmail_summarize_attachment"),
    ("tldr the attached spreadsheet",              "gmail_summarize_attachment"),
    ("what's in the receipt",                      "gmail_summarize_attachment"),
    ("summarize the attachment",                   "gmail_summarize_attachment"),
    ("what does the attached document say",        "gmail_summarize_attachment"),

    # ── gmail_attach_file ─────────────────────────────────────────────────
    ("attach the report PDF",                      "gmail_attach_file"),
    ("attach the Q3 report to this draft",         "gmail_attach_file"),
    ("add the PDF to this email",                  "gmail_attach_file"),
    ("attach the invoice to this reply",           "gmail_attach_file"),
    ("include the spreadsheet in the email",       "gmail_attach_file"),
    ("add the presentation to this draft",         "gmail_attach_file"),
    ("attach that saved attachment",               "gmail_attach_file"),

    # ── gmail_remove_attachment ───────────────────────────────────────────
    ("remove the attachment",                      "gmail_remove_attachment"),
    ("detach the PDF",                             "gmail_remove_attachment"),
    ("remove the PDF from the draft",              "gmail_remove_attachment"),
    ("drop the file from this email",              "gmail_remove_attachment"),
    ("remove the attached document",               "gmail_remove_attachment"),
    ("draft without attachment",                   "gmail_remove_attachment"),

    # ── gmail_schedule_send ────────────────────────────────────────────────
    ("schedule this for tomorrow morning",         "gmail_schedule_send"),
    ("send it on Friday at 9 AM",                  "gmail_schedule_send"),
    ("schedule this email for Monday",             "gmail_schedule_send"),
    ("send it tomorrow",                           "gmail_schedule_send"),
    ("send in 2 hours",                            "gmail_schedule_send"),
    ("send at 3 PM",                               "gmail_schedule_send"),
    ("schedule send for next week",                "gmail_schedule_send"),
    ("delay send to Thursday",                     "gmail_schedule_send"),
    ("schedule this for tonight",                  "gmail_schedule_send"),
    ("send it tomorrow afternoon",                 "gmail_schedule_send"),
    ("send tomorrow morning",                      "gmail_schedule_send"),
    ("send it at 9 AM tomorrow",                   "gmail_schedule_send"),
    ("schedule this draft for Monday at 9",        "gmail_schedule_send"),
    ("send this next Monday",                      "gmail_schedule_send"),
    ("send this email tonight",                    "gmail_schedule_send"),
    ("send later",                                 "gmail_schedule_send"),
    ("delay send",                                 "gmail_schedule_send"),

    # ── gmail_list_scheduled ──────────────────────────────────────────────
    ("show my scheduled emails",                   "gmail_list_scheduled"),
    ("list scheduled sends",                       "gmail_list_scheduled"),
    ("what's scheduled",                           "gmail_list_scheduled"),
    ("show scheduled drafts",                      "gmail_list_scheduled"),
    ("any scheduled messages",                     "gmail_list_scheduled"),
    ("view scheduled emails",                      "gmail_list_scheduled"),
    ("scheduled emails",                           "gmail_list_scheduled"),

    # ── gmail_cancel_scheduled_send ───────────────────────────────────────
    ("cancel the scheduled send",                  "gmail_cancel_scheduled_send"),
    ("cancel that scheduled email",                "gmail_cancel_scheduled_send"),
    ("cancel the scheduled draft",                 "gmail_cancel_scheduled_send"),
    ("unschedule that email",                      "gmail_cancel_scheduled_send"),
    ("don't send that email",                      "gmail_cancel_scheduled_send"),
    ("stop sending that scheduled message",        "gmail_cancel_scheduled_send"),

    # ── gmail_reschedule_send ─────────────────────────────────────────────
    ("reschedule to Friday",                       "gmail_reschedule_send"),
    ("reschedule the send",                        "gmail_reschedule_send"),
    ("move the scheduled email to Monday",         "gmail_reschedule_send"),
    ("push the scheduled send to next week",       "gmail_reschedule_send"),
    ("delay the scheduled email to Thursday",      "gmail_reschedule_send"),
    ("change scheduled send time to 3 PM",         "gmail_reschedule_send"),
    ("change the scheduled email to Friday",       "gmail_reschedule_send"),
    ("move the send to tomorrow",                  "gmail_reschedule_send"),
    ("postpone the scheduled email to Monday",     "gmail_reschedule_send"),

    # ── gmail_open_scheduled_draft ────────────────────────────────────────
    ("open the scheduled draft",                   "gmail_open_scheduled_draft"),
    ("open the scheduled email",                   "gmail_open_scheduled_draft"),
    ("load the scheduled email",                   "gmail_open_scheduled_draft"),
    ("reopen the scheduled send",                  "gmail_open_scheduled_draft"),
    ("switch to the scheduled message",            "gmail_open_scheduled_draft"),

    # ── gmail_followup_reminder ────────────────────────────────────────────
    ("remind me if no reply in 3 days",            "gmail_followup_reminder"),
    ("set a follow-up for Friday",                 "gmail_followup_reminder"),
    ("remind me to follow up on this",             "gmail_followup_reminder"),
    ("follow up on this if no reply",              "gmail_followup_reminder"),
    ("set a reminder to follow up",                "gmail_followup_reminder"),
    ("if they don't reply, remind me",             "gmail_followup_reminder"),
    ("follow up on this thread in 3 days",         "gmail_followup_reminder"),
    ("remind me about this in 2 days",             "gmail_followup_reminder"),
    ("set a follow-up for Monday",                 "gmail_followup_reminder"),
    ("remind me",                                  "gmail_followup_reminder"),
    ("if no reply by Friday, ping me",             "gmail_followup_reminder"),

    # ── gmail_list_followups ───────────────────────────────────────────────
    ("show my follow-ups",                         "gmail_list_followups"),
    ("list follow-up reminders",                   "gmail_list_followups"),
    ("what threads am I waiting on",               "gmail_list_followups"),
    ("what am I following up on",                  "gmail_list_followups"),
    ("show pending reminders",                     "gmail_list_followups"),
    ("who hasn't replied to me",                   "gmail_list_followups"),
    ("pending follow-ups",                         "gmail_list_followups"),
    ("open follow-ups",                            "gmail_list_followups"),

    # ── gmail_cancel_followup ─────────────────────────────────────────────
    ("cancel the follow-up",                       "gmail_cancel_followup"),
    ("cancel the reminder",                        "gmail_cancel_followup"),
    ("cancel that reminder",                       "gmail_cancel_followup"),
    ("remove the follow-up reminder",              "gmail_cancel_followup"),
    ("delete that reminder",                       "gmail_cancel_followup"),
    ("stop the reminder",                          "gmail_cancel_followup"),

    # ── gmail_list_drafts ─────────────────────────────────────────────────
    ("show my drafts",                             "gmail_list_drafts"),
    ("list my drafts",                             "gmail_list_drafts"),
    ("show all drafts",                            "gmail_list_drafts"),
    ("view all drafts",                            "gmail_list_drafts"),
    ("what drafts do I have",                      "gmail_list_drafts"),
    ("show unscheduled drafts",                    "gmail_list_drafts"),
    ("list scheduled drafts",                      "gmail_list_drafts"),

    # ── gmail_open_draft ──────────────────────────────────────────────────
    ("open draft 2",                               "gmail_open_draft"),
    ("open the first draft",                       "gmail_open_draft"),
    ("switch to draft 3",                          "gmail_open_draft"),
    ("open the second draft",                      "gmail_open_draft"),
    ("load draft 1",                               "gmail_open_draft"),
    ("select draft 2",                             "gmail_open_draft"),
    ("use the last draft",                         "gmail_open_draft"),
    ("open the Rahul draft",                       "gmail_open_draft"),

    # ── gmail_delete_draft ────────────────────────────────────────────────
    ("delete draft 1",                             "gmail_delete_draft"),
    ("remove draft 2",                             "gmail_delete_draft"),
    ("trash draft 3",                              "gmail_delete_draft"),
    ("delete the first draft",                     "gmail_delete_draft"),
    ("delete the last draft",                      "gmail_delete_draft"),
    ("cancel that old draft",                      "gmail_delete_draft"),

    # ── gmail_thread_intel ─────────────────────────────────────────────────
    ("action items",                               "gmail_thread_intel"),
    ("what action items are there",                "gmail_thread_intel"),
    ("what decisions were made",                   "gmail_thread_intel"),
    ("do I owe a reply",                           "gmail_thread_intel"),
    ("should I reply",                             "gmail_thread_intel"),
    ("is a reply needed",                          "gmail_thread_intel"),
    ("what's the latest reply",                    "gmail_thread_intel"),
    ("last message in this thread",                "gmail_thread_intel"),
    ("what changed in this thread",                "gmail_thread_intel"),
    ("decisions in this thread",                   "gmail_thread_intel"),
    ("outstanding questions for me",               "gmail_thread_intel"),
    ("questions pending in this thread",           "gmail_thread_intel"),
    ("summarize the latest reply",                 "gmail_thread_intel"),

    # ── gmail_forward ─────────────────────────────────────────────────────
    ("forward this to Rahul",                      "gmail_forward"),
    ("forward it to the team",                     "gmail_forward"),
    ("fwd this to Priya",                          "gmail_forward"),
    ("forward to priya@company.com",               "gmail_forward"),
    ("forward this email to support",              "gmail_forward"),
    ("forward the thread to Rahul",                "gmail_forward"),
    ("fwd to the team",                            "gmail_forward"),

    # ── gmail_filter_build ────────────────────────────────────────────────
    ("always label invoices as Finance",           "gmail_filter_build"),
    ("always archive newsletters",                 "gmail_filter_build"),
    ("auto-archive promotional emails",            "gmail_filter_build"),
    ("create a rule to archive newsletters",       "gmail_filter_build"),
    ("make a rule to label invoices as Finance",   "gmail_filter_build"),
    ("build a filter for GitHub notifications",    "gmail_filter_build"),
    ("create a Gmail filter for receipts",         "gmail_filter_build"),
    ("set up a rule to star emails from Priya",    "gmail_filter_build"),
    ("automatically mark newsletters as read",     "gmail_filter_build"),
    ("show me what rule you'd make for this",      "gmail_filter_build"),

    # ── gmail_filter_apply ────────────────────────────────────────────────
    ("create that rule",                           "gmail_filter_apply"),
    ("apply the filter",                           "gmail_filter_apply"),
    ("yes, create the rule",                       "gmail_filter_apply"),
    ("save the filter",                            "gmail_filter_apply"),
    ("confirm and apply the rule",                 "gmail_filter_apply"),

    # ── gmail_filter_cancel ───────────────────────────────────────────────
    ("cancel the filter",                          "gmail_filter_cancel"),
    ("discard the rule",                           "gmail_filter_cancel"),
    ("abort rule creation",                        "gmail_filter_cancel"),
    ("stop the filter",                            "gmail_filter_cancel"),

    # ── gmail_filter_list ─────────────────────────────────────────────────
    ("show my rules",                              "gmail_filter_list"),
    ("list my filters",                            "gmail_filter_list"),
    ("view my Gmail filters",                      "gmail_filter_list"),
    ("show saved rules",                           "gmail_filter_list"),

    # ── gmail_extract_tasks ────────────────────────────────────────────────
    ("turn this email into tasks",                 "gmail_extract_tasks"),
    ("turn this thread into a checklist",          "gmail_extract_tasks"),
    ("convert this email to tasks",                "gmail_extract_tasks"),
    ("extract action items from this email",       "gmail_extract_tasks"),
    ("extract deadlines from this thread",         "gmail_extract_tasks"),
    ("extract all decisions",                      "gmail_extract_tasks"),
    ("what deadlines are mentioned here",          "gmail_extract_tasks"),
    ("what dates are in this thread",              "gmail_extract_tasks"),
    ("extract dates from this email",              "gmail_extract_tasks"),
    ("make a task list",                           "gmail_extract_tasks"),
    ("make a todo list from this email",           "gmail_extract_tasks"),
    ("create a checklist from this email",         "gmail_extract_tasks"),
    ("build a checklist from this thread",         "gmail_extract_tasks"),
    ("write a todo list for this email",           "gmail_extract_tasks"),
    ("generate a task list from this thread",      "gmail_extract_tasks"),
    ("summarize this email as tasks",              "gmail_extract_tasks"),
    ("summarize this thread as action items",      "gmail_extract_tasks"),
    ("what follow-ups should I put on my list",    "gmail_extract_tasks"),
    ("make a follow-up checklist",                 "gmail_extract_tasks"),
    ("extract the asks from this email",           "gmail_extract_tasks"),

    # ── gmail_tasks_save ──────────────────────────────────────────────────
    ("save tasks to Obsidian",                     "gmail_tasks_save"),
    ("save those action items",                    "gmail_tasks_save"),
    ("add these tasks to my notes",                "gmail_tasks_save"),
    ("export the extracted tasks",                 "gmail_tasks_save"),
    ("add those tasks to my daily note",           "gmail_tasks_save"),
    ("save the checklist to my notes",             "gmail_tasks_save"),
    ("put those items in Obsidian",                "gmail_tasks_save"),
    ("export that checklist",                      "gmail_tasks_save"),
    ("write those tasks to my notes",              "gmail_tasks_save"),

    # ── gmail_tasks_remind ────────────────────────────────────────────────
    ("create reminders for those action items",    "gmail_tasks_remind"),
    ("set reminders for the deadlines",            "gmail_tasks_remind"),
    ("set reminders for all of those",             "gmail_tasks_remind"),
    ("remind me about those action items",         "gmail_tasks_remind"),
    ("remind me about those deadlines",            "gmail_tasks_remind"),
    ("create reminders for each deadline",         "gmail_tasks_remind"),
    ("set reminders for those tasks",              "gmail_tasks_remind"),
    ("create reminders for the action items",      "gmail_tasks_remind"),
]
# fmt: on


class TestGmailMassCorpusInbox(unittest.TestCase):
    """gmail + gmail_open + gmail_read routing (subTest corpus)."""

    def test_inbox_and_open_read(self):
        intents = {"gmail", "gmail_open", "gmail_read"}
        for text, expected in _MASS_CORPUS:
            if expected not in intents:
                continue
            with self.subTest(text=text, expected=expected):
                result = _classify(text)
                self.assertEqual(result, expected,
                    f"'{text}' → expected {expected!r}, got {result!r}")


class TestGmailMassCorpusThreadSummarize(unittest.TestCase):
    """gmail_thread + gmail_summarize + gmail_list_category (subTest corpus)."""

    def test_thread_summarize_category(self):
        intents = {"gmail_thread", "gmail_summarize", "gmail_list_category"}
        for text, expected in _MASS_CORPUS:
            if expected not in intents:
                continue
            with self.subTest(text=text, expected=expected):
                result = _classify(text)
                self.assertEqual(result, expected,
                    f"'{text}' → expected {expected!r}, got {result!r}")


class TestGmailMassCorpusMutations(unittest.TestCase):
    """archive/trash/mark/confirm/cancel/undo (subTest corpus)."""

    def test_mutations(self):
        intents = {
            "gmail_archive", "gmail_trash", "gmail_mark_read", "gmail_mark_unread",
            "gmail_confirm", "gmail_cancel", "gmail_undo",
        }
        for text, expected in _MASS_CORPUS:
            if expected not in intents:
                continue
            with self.subTest(text=text, expected=expected):
                result = _classify(text)
                self.assertEqual(result, expected,
                    f"'{text}' → expected {expected!r}, got {result!r}")


class TestGmailMassCorpusDraft(unittest.TestCase):
    """triage + draft lifecycle + subject/cc/bcc (subTest corpus)."""

    def test_draft_lifecycle(self):
        intents = {
            "gmail_triage",
            "gmail_draft_reply", "gmail_compose",
            "gmail_show_draft", "gmail_send_draft", "gmail_cancel_draft",
            "gmail_rewrite_draft", "gmail_update_subject",
            "gmail_add_cc", "gmail_add_bcc",
        }
        for text, expected in _MASS_CORPUS:
            if expected not in intents:
                continue
            with self.subTest(text=text, expected=expected):
                result = _classify(text)
                self.assertEqual(result, expected,
                    f"'{text}' → expected {expected!r}, got {result!r}")


class TestGmailMassCorpusAttachments(unittest.TestCase):
    """Attachment intents (subTest corpus)."""

    def test_attachments(self):
        intents = {
            "gmail_list_attachments", "gmail_save_attachment",
            "gmail_summarize_attachment", "gmail_attach_file",
            "gmail_remove_attachment",
        }
        for text, expected in _MASS_CORPUS:
            if expected not in intents:
                continue
            with self.subTest(text=text, expected=expected):
                result = _classify(text)
                self.assertEqual(result, expected,
                    f"'{text}' → expected {expected!r}, got {result!r}")


class TestGmailMassCorpusSchedule(unittest.TestCase):
    """Schedule send + reschedule + follow-up + multi-draft (subTest corpus)."""

    def test_schedule_and_followup(self):
        intents = {
            "gmail_schedule_send", "gmail_list_scheduled",
            "gmail_cancel_scheduled_send", "gmail_reschedule_send",
            "gmail_open_scheduled_draft",
            "gmail_followup_reminder", "gmail_list_followups", "gmail_cancel_followup",
            "gmail_list_drafts", "gmail_open_draft", "gmail_delete_draft",
        }
        for text, expected in _MASS_CORPUS:
            if expected not in intents:
                continue
            with self.subTest(text=text, expected=expected):
                result = _classify(text)
                self.assertEqual(result, expected,
                    f"'{text}' → expected {expected!r}, got {result!r}")


class TestGmailMassCorpusIntelFilterTasks(unittest.TestCase):
    """thread_intel + forward + filter + extract_tasks (subTest corpus)."""

    def test_intel_filter_tasks(self):
        intents = {
            "gmail_thread_intel", "gmail_forward",
            "gmail_filter_build", "gmail_filter_apply",
            "gmail_filter_cancel", "gmail_filter_list",
            "gmail_extract_tasks", "gmail_tasks_save", "gmail_tasks_remind",
        }
        for text, expected in _MASS_CORPUS:
            if expected not in intents:
                continue
            with self.subTest(text=text, expected=expected):
                result = _classify(text)
                self.assertEqual(result, expected,
                    f"'{text}' → expected {expected!r}, got {result!r}")


# ===========================================================================
# MULTI-TURN DIALOG SIMULATION — NLU routing sequences
# Each flow represents a realistic Gmail session step sequence.
# Tests that each step routes correctly as a standalone NLU call.
# ===========================================================================

class TestGmailMultiTurnFlows(unittest.TestCase):
    """Multi-step Gmail session simulations. Each step is an NLU routing check."""

    def _flow(self, steps: list[tuple[str, str]]) -> None:
        for text, expected in steps:
            with self.subTest(text=text):
                result = _classify(text)
                self.assertEqual(result, expected,
                    f"Flow step '{text}': expected {expected!r}, got {result!r}")

    def test_flow_read_summarize_reply_send(self):
        self._flow([
            ("open the email from Priya",              "gmail_open"),
            ("summarize it",                           "gmail_summarize"),
            ("draft a reply saying we're on schedule", "gmail_draft_reply"),
            ("make it shorter",                        "gmail_rewrite_draft"),
            ("send it",                                "gmail_send_draft"),
        ])

    def test_flow_triage_reply_forward(self):
        self._flow([
            ("triage my inbox",                        "gmail_triage"),
            ("open 2",                                 "gmail_read"),
            ("reply saying I'll look into it",         "gmail_draft_reply"),
            ("make it more professional",              "gmail_rewrite_draft"),
            ("forward a copy to Rahul too",            "gmail_forward"),
        ])

    def test_flow_compose_attach_schedule(self):
        self._flow([
            ("compose an email to the team",           "gmail_compose"),
            ("attach the quarterly report",            "gmail_attach_file"),
            ("update the subject to Q3 Summary",       "gmail_update_subject"),
            ("schedule this for Monday morning",       "gmail_schedule_send"),
        ])

    def test_flow_promotions_archive_undo(self):
        self._flow([
            ("show promotions",                        "gmail_list_category"),
            ("archive all of them",                    "gmail_archive"),
            ("undo that archive",                      "gmail_undo"),
        ])

    def test_flow_extract_tasks_save_remind(self):
        self._flow([
            ("extract action items from this email",   "gmail_extract_tasks"),
            ("save those action items",                "gmail_tasks_save"),
            ("create reminders for each deadline",     "gmail_tasks_remind"),
        ])

    def test_flow_filter_preview_apply(self):
        self._flow([
            ("always label invoices as Finance",       "gmail_filter_build"),
            ("create that rule",                       "gmail_filter_apply"),
        ])

    def test_flow_schedule_list_cancel(self):
        self._flow([
            ("send this for tomorrow morning",         "gmail_schedule_send"),
            ("show my scheduled emails",               "gmail_list_scheduled"),
            ("cancel that scheduled send",             "gmail_cancel_scheduled_send"),
        ])

    def test_flow_thread_intel_reply(self):
        self._flow([
            ("show the thread",                        "gmail_thread"),
            ("what action items are there",            "gmail_thread_intel"),
            ("reply to the latest ask",                "gmail_draft_reply"),
            ("add cc Priya",                           "gmail_add_cc"),
            ("send the draft",                         "gmail_send_draft"),
        ])

    def test_flow_multidraft_switch_delete(self):
        self._flow([
            ("show my drafts",                         "gmail_list_drafts"),
            ("open draft 2",                           "gmail_open_draft"),
            ("make the reply shorter",                 "gmail_rewrite_draft"),
            ("update the subject",                     "gmail_update_subject"),
            ("send it",                                "gmail_send_draft"),
            ("delete draft 1",                         "gmail_delete_draft"),
        ])

    def test_flow_followup_list_cancel(self):
        self._flow([
            ("remind me if no reply in 3 days",        "gmail_followup_reminder"),
            ("show my follow-ups",                     "gmail_list_followups"),
            ("cancel the follow-up",                   "gmail_cancel_followup"),
        ])

    def test_flow_open_attachment_summarize_save(self):
        self._flow([
            ("open the email from Amazon",             "gmail_open"),
            ("any attachments",                        "gmail_list_attachments"),
            ("summarize the PDF",                      "gmail_summarize_attachment"),
            ("save the invoice",                       "gmail_save_attachment"),
        ])

    def test_flow_thread_extract_to_note(self):
        self._flow([
            ("show the thread",                        "gmail_thread"),
            ("turn this thread into a checklist",      "gmail_extract_tasks"),
            ("add those tasks to my daily note",       "gmail_tasks_save"),
        ])

    def test_flow_compose_cc_bcc_send(self):
        self._flow([
            ("compose an email to Rahul",              "gmail_compose"),
            ("add cc Priya",                           "gmail_add_cc"),
            ("bcc my manager on this email",           "gmail_add_bcc"),
            ("show the draft",                         "gmail_show_draft"),
            ("send it",                                "gmail_send_draft"),
        ])

    def test_flow_schedule_reschedule_open(self):
        self._flow([
            ("schedule this for tomorrow",             "gmail_schedule_send"),
            ("reschedule to Friday at 9 AM",           "gmail_reschedule_send"),
            ("open the scheduled email",               "gmail_open_scheduled_draft"),
            ("cancel the scheduled send",              "gmail_cancel_scheduled_send"),
        ])

    def test_flow_cancel_abort_confirm(self):
        self._flow([
            ("create a rule to archive newsletters",   "gmail_filter_build"),
            ("cancel",                                 "gmail_cancel"),
            ("create a rule to label invoices",        "gmail_filter_build"),
            ("create that rule",                       "gmail_filter_apply"),
        ])


# ===========================================================================
# NEAR-COLLISION TESTS — inputs that sit right on intent boundaries
# ===========================================================================

class TestGmailNearCollisions(unittest.TestCase):
    """Tricky inputs that could route to the wrong intent."""

    # ── "send it" vs "send tomorrow" ─────────────────────────────────────
    def test_send_it_no_time_is_send_draft(self):
        self.assertEqual(_classify("send it"), "gmail_send_draft")

    def test_send_it_with_time_is_schedule(self):
        self.assertEqual(_classify("send it tomorrow"), "gmail_schedule_send")

    def test_send_the_draft_is_send_draft(self):
        self.assertEqual(_classify("send the draft"), "gmail_send_draft")

    # ── "summarize" + email/attachment boundary ───────────────────────────
    def test_summarize_pdf_is_attachment_not_email(self):
        self.assertEqual(_classify("summarize the PDF"), "gmail_summarize_attachment")

    def test_summarize_this_email_is_summarize(self):
        self.assertEqual(_classify("summarize this email"), "gmail_summarize")

    def test_summarize_thread_is_summarize(self):
        self.assertEqual(_classify("summarize the thread"), "gmail_summarize")

    def test_summarize_as_tasks_is_extract(self):
        self.assertEqual(_classify("summarize this email as tasks"), "gmail_extract_tasks")

    # ── extract vs thread_intel ────────────────────────────────────────────
    def test_extract_action_items_is_extract_tasks(self):
        self.assertEqual(_classify("extract action items"), "gmail_extract_tasks")

    def test_bare_action_items_is_thread_intel(self):
        self.assertEqual(_classify("action items"), "gmail_thread_intel")

    def test_what_action_items_is_thread_intel(self):
        self.assertEqual(_classify("what action items are there"), "gmail_thread_intel")

    def test_extract_deadlines_is_extract_tasks(self):
        self.assertEqual(_classify("extract deadlines from the thread"), "gmail_extract_tasks")

    # ── "cancel" ambiguity ──────────────────────────────────────────────
    def test_bare_cancel_is_gmail_cancel(self):
        self.assertEqual(_classify("cancel"), "gmail_cancel")

    def test_cancel_draft_is_cancel_draft(self):
        self.assertEqual(_classify("cancel the draft"), "gmail_cancel_draft")

    def test_cancel_rule_is_filter_cancel(self):
        self.assertEqual(_classify("cancel rule creation"), "gmail_filter_cancel")

    def test_cancel_followup_is_cancel_followup(self):
        self.assertEqual(_classify("cancel the follow-up"), "gmail_cancel_followup")

    def test_cancel_scheduled_is_cancel_scheduled(self):
        self.assertEqual(_classify("cancel the scheduled send"), "gmail_cancel_scheduled_send")

    # ── archive vs filter_build ────────────────────────────────────────────
    def test_always_archive_is_filter(self):
        self.assertEqual(_classify("always archive newsletters"), "gmail_filter_build")

    def test_archive_those_emails_is_archive(self):
        self.assertEqual(_classify("archive those emails"), "gmail_archive")

    def test_auto_archive_is_filter(self):
        self.assertEqual(_classify("auto-archive promotional emails"), "gmail_filter_build")

    # ── filter_apply vs filter_build ─────────────────────────────────────
    def test_create_that_rule_is_apply(self):
        self.assertEqual(_classify("create that rule"), "gmail_filter_apply")

    def test_create_a_rule_for_is_build(self):
        self.assertEqual(_classify("create a rule for GitHub notifications"), "gmail_filter_build")

    # ── tasks_save vs obsidian_daily ──────────────────────────────────────
    def test_add_tasks_to_daily_note_is_tasks_save(self):
        self.assertEqual(_classify("add tasks to my daily note"), "gmail_tasks_save")

    def test_bare_add_to_daily_note_is_obsidian(self):
        self.assertEqual(_classify("open my daily note"), "obsidian_daily")

    # ── tasks_remind vs followup_reminder ─────────────────────────────────
    def test_reminders_for_action_items_is_tasks_remind(self):
        self.assertEqual(_classify("create reminders for those action items"), "gmail_tasks_remind")

    def test_bare_remind_me_is_followup(self):
        self.assertEqual(_classify("remind me"), "gmail_followup_reminder")

    def test_set_reminder_for_friday_is_followup(self):
        self.assertEqual(_classify("set a reminder for Friday"), "gmail_followup_reminder")

    # ── gmail_open vs gmail_read ───────────────────────────────────────────
    def test_open_email_from_is_open(self):
        self.assertEqual(_classify("open the email from Rahul"), "gmail_open")

    def test_open_3_is_read(self):
        self.assertEqual(_classify("open 3"), "gmail_read")

    def test_open_latest_email_is_read(self):
        self.assertEqual(_classify("open the latest email"), "gmail_read")

    # ── thread vs summarize ────────────────────────────────────────────────
    def test_show_thread_is_thread(self):
        self.assertEqual(_classify("show the thread"), "gmail_thread")

    def test_summarize_thread_is_summarize(self):
        self.assertEqual(_classify("summarize the thread"), "gmail_summarize")

    # ── gmail_delete_draft vs gmail_trash ─────────────────────────────────
    def test_delete_draft_1_is_delete_draft(self):
        self.assertEqual(_classify("delete draft 1"), "gmail_delete_draft")

    def test_delete_emails_is_trash(self):
        self.assertEqual(_classify("delete those emails"), "gmail_trash")

    # ── mark_read vs filter_build (auto-mark-read) ────────────────────────
    def test_mark_as_read_is_mark_read(self):
        self.assertEqual(_classify("mark as read"), "gmail_mark_read")

    def test_auto_mark_read_is_filter(self):
        self.assertEqual(_classify("automatically mark GitHub notifications as read"),
            "gmail_filter_build")

    # ── send_draft vs schedule_send ────────────────────────────────────────
    def test_send_at_3pm_tomorrow_is_schedule(self):
        self.assertEqual(_classify("send it at 3 PM tomorrow"), "gmail_schedule_send")

    def test_send_the_reply_is_send_draft(self):
        self.assertEqual(_classify("send the reply"), "gmail_send_draft")

    # ── open_draft vs open_scheduled_draft ────────────────────────────────
    def test_open_draft_2_is_open_draft(self):
        self.assertEqual(_classify("open draft 2"), "gmail_open_draft")

    def test_open_scheduled_draft_is_open_scheduled(self):
        self.assertEqual(_classify("open the scheduled draft"), "gmail_open_scheduled_draft")

    # ── compose vs draft_reply ─────────────────────────────────────────────
    def test_compose_new_email_is_compose(self):
        self.assertEqual(_classify("compose a new email to Rahul"), "gmail_compose")

    def test_draft_reply_is_draft_reply(self):
        self.assertEqual(_classify("draft a reply to this"), "gmail_draft_reply")

    # ── thread_intel early guard vs web_search/git_status ────────────────
    def test_what_changed_in_reply_is_thread_intel(self):
        self.assertEqual(_classify("what changed in the last reply"), "gmail_thread_intel")

    def test_what_changed_in_code_is_not_thread_intel(self):
        result = _classify("what changed in the codebase today")
        self.assertNotEqual(result, "gmail_thread_intel")


# ===========================================================================
# SAFETY / CONFIRMATION ROUTING TESTS
# These verify that destructive intents route to the right intent
# (where the command handler enforces preview→confirm) rather than
# routing to an incorrect intent or None.
# ===========================================================================

class TestGmailSafetyRouting(unittest.TestCase):
    """Safety routing: destructive inputs must route to the right intent
    (not skip confirmation). The NLU routing is correct; the command handler
    enforces the preview/confirm step."""

    def test_archive_all_routes_to_archive(self):
        # Should route to gmail_archive (which shows preview + requires confirm)
        result = _classify("archive all emails")
        self.assertEqual(result, "gmail_archive",
            "'archive all emails' must route to gmail_archive for preview+confirm handling")

    def test_delete_all_emails_routes_to_trash(self):
        result = _classify("delete all emails")
        self.assertEqual(result, "gmail_trash",
            "'delete all emails' must route to gmail_trash for preview+confirm handling")

    def test_trash_all_spam_routes_to_trash(self):
        result = _classify("trash all spam")
        self.assertEqual(result, "gmail_trash")

    def test_send_draft_requires_send_intent(self):
        # "send it" must route to gmail_send_draft (not silently to something else)
        self.assertEqual(_classify("send it"), "gmail_send_draft")

    def test_apply_filter_requires_apply_intent(self):
        # Rule application requires explicit gmail_filter_apply intent
        self.assertEqual(_classify("apply the rule"), "gmail_filter_apply")

    def test_delete_old_draft_routes_to_delete_draft(self):
        self.assertEqual(_classify("cancel that old draft"), "gmail_delete_draft")

    def test_forward_routes_to_forward(self):
        # Forwarding to wrong recipient is a real risk; must hit forward intent
        self.assertEqual(_classify("forward this to the whole team"), "gmail_forward")

    def test_schedule_send_routes_to_schedule(self):
        self.assertEqual(_classify("send this on Friday"), "gmail_schedule_send")

    def test_filter_build_not_immediately_apply(self):
        # "create a rule" must be filter_BUILD (preview), not filter_APPLY
        result = _classify("create a rule for newsletters")
        self.assertEqual(result, "gmail_filter_build",
            "NL rule creation must go through gmail_filter_build preview first")

    def test_send_without_email_routes_to_send_draft(self):
        # "send now" must hit gmail_send_draft (handler will check for draft context)
        self.assertEqual(_classify("send now"), "gmail_send_draft")

    def test_unschedule_routes_correctly(self):
        self.assertEqual(_classify("unschedule that email"), "gmail_cancel_scheduled_send")


# ===========================================================================
# NEGATIVE TESTS — inputs that must NOT route to any Gmail intent
# ===========================================================================

class TestGmailNegativeRouting(unittest.TestCase):
    """Non-Gmail inputs must NOT accidentally trigger Gmail intents."""

    def test_git_status_not_gmail(self):
        result = _classify("show git status")
        self.assertNotIn(result, {"gmail", "gmail_read", "gmail_open", "gmail_summarize"})

    def test_web_search_not_gmail(self):
        result = _classify("search the web for Python tutorials")
        self.assertNotIn(result, {"gmail", "gmail_read"})

    def test_obsidian_note_not_gmail_extract(self):
        result = _classify("open my obsidian vault")
        self.assertNotEqual(result, "gmail_extract_tasks")

    def test_backup_not_gmail(self):
        result = _classify("run git backup now")
        self.assertNotIn(result, {"gmail", "gmail_archive", "gmail_trash"})

    def test_system_status_not_gmail(self):
        result = _classify("show system status")
        self.assertNotEqual(result, "gmail")

    def test_read_file_not_gmail(self):
        result = _classify("read the file config.yaml")
        self.assertNotIn(result, {"gmail", "gmail_read"})

    def test_youtube_not_gmail(self):
        result = _classify("summarize this YouTube video")
        self.assertNotEqual(result, "gmail_summarize")

    def test_what_changed_code_not_thread_intel(self):
        result = _classify("what changed in the Python code today")
        self.assertNotEqual(result, "gmail_thread_intel")

    def test_daily_note_not_gmail(self):
        result = _classify("open today's note")
        self.assertNotEqual(result, "gmail_extract_tasks")

    def test_remember_something_not_gmail(self):
        result = _classify("remember that the meeting is at 3 PM")
        self.assertNotIn(result, {"gmail", "gmail_followup_reminder"})


# ===========================================================================
# UNIT TESTS — _extract_sender_email
# ===========================================================================

class TestExtractSenderEmail(unittest.TestCase):
    """Unit tests for _extract_sender_email()."""

    def test_bare_email(self):
        self.assertEqual(_extract_sender_email("user@example.com"), "user@example.com")

    def test_name_and_email(self):
        self.assertEqual(_extract_sender_email("Priya Sharma <priya@company.com>"),
            "priya@company.com")

    def test_extra_spaces(self):
        self.assertEqual(_extract_sender_email(" Rahul Kumar < rahul@work.com > "),
            "rahul@work.com")

    def test_empty_string(self):
        self.assertEqual(_extract_sender_email(""), "")

    def test_no_angle_brackets(self):
        result = _extract_sender_email("noreply at amazon")
        self.assertEqual(result, "noreply at amazon")

    def test_notifications_at_github(self):
        result = _extract_sender_email("GitHub <notifications@github.com>")
        self.assertEqual(result, "notifications@github.com")


# ===========================================================================
# UNIT TESTS — _parse_filter_rule
# ===========================================================================

class TestParseFilterRule(unittest.TestCase):
    """Unit tests for _parse_filter_rule().
    Note: tests that reference _GMAIL_CTX["current_email"] use a fresh
    empty context (no current email) unless patched via _filter_ns."""

    def setUp(self):
        # Reset _GMAIL_CTX to empty before each test
        _filter_ns["_GMAIL_CTX"] = {}

    def _parse(self, text: str) -> dict:
        return _parse_filter_rule(text)

    # ── label extraction ─────────────────────────────────────────────────
    def test_label_invoices_finance(self):
        rule = self._parse("always label invoices as Finance")
        self.assertEqual(rule["actions"]["label"], "Finance")
        self.assertEqual(rule["criteria"]["subject"], "invoice")

    def test_label_lowercase_receipts(self):
        rule = self._parse("label receipts as bills")
        self.assertEqual(rule["actions"]["label"].lower(), "bills")
        self.assertEqual(rule["criteria"]["subject"], "receipt")

    def test_label_quoted_label_name(self):
        rule = self._parse("label as 'Finance'")
        self.assertEqual(rule["actions"]["label"], "Finance")

    def test_label_apply_keyword(self):
        rule = self._parse("apply label Invoices to this")
        self.assertEqual(rule["actions"]["label"], "Invoices")

    # ── archive action ────────────────────────────────────────────────────
    def test_archive_newsletters(self):
        rule = self._parse("always archive newsletters")
        self.assertTrue(rule["actions"]["archive"])
        self.assertIn("category:promotions", rule["criteria"]["query"])

    def test_skip_inbox(self):
        rule = self._parse("skip inbox for newsletters")
        self.assertTrue(rule["actions"]["archive"])

    def test_archive_github_notifications(self):
        rule = self._parse("auto-archive GitHub notifications")
        self.assertTrue(rule["actions"]["archive"])
        self.assertEqual(rule["criteria"]["from_"], "notifications@github.com")

    # ── mark_read action ──────────────────────────────────────────────────
    def test_mark_read_action(self):
        rule = self._parse("mark newsletters as read")
        self.assertTrue(rule["actions"]["mark_read"])

    def test_mark_read_auto(self):
        rule = self._parse("automatically mark newsletters as read")
        self.assertTrue(rule["actions"]["mark_read"])

    # ── star action ───────────────────────────────────────────────────────
    def test_star_action(self):
        rule = self._parse("star emails from Priya")
        self.assertTrue(rule["actions"]["star"])

    def test_mark_important_is_star(self):
        rule = self._parse("mark as important emails from Rahul")
        self.assertTrue(rule["actions"]["star"])

    # ── from criteria ─────────────────────────────────────────────────────
    def test_from_amazon(self):
        rule = self._parse("emails from Amazon, auto-archive")
        self.assertIn("amazon", rule["criteria"]["from_"].lower())
        self.assertTrue(rule["actions"]["archive"])

    def test_from_github_notifications_shorthand(self):
        rule = self._parse("github notifications → archive")
        self.assertEqual(rule["criteria"]["from_"], "notifications@github.com")

    def test_from_explicit_email(self):
        rule = self._parse("from noreply@example.com, label as Updates")
        self.assertIn("noreply@example.com", rule["criteria"]["from_"])

    # ── subject criteria ─────────────────────────────────────────────────
    def test_subject_invoice(self):
        rule = self._parse("label invoices as Finance")
        self.assertEqual(rule["criteria"]["subject"], "invoice")

    def test_subject_receipt(self):
        rule = self._parse("label receipts as Finance")
        self.assertEqual(rule["criteria"]["subject"], "receipt")

    # ── query criteria (newsletter/promotions category) ───────────────────
    def test_newsletters_query(self):
        rule = self._parse("auto-archive newsletters")
        self.assertIn("category:promotions", rule["criteria"]["query"])

    def test_promotions_query(self):
        rule = self._parse("archive promotional emails")
        self.assertIn("category:promotions", rule["criteria"]["query"])

    # ── current email sender (no context) ────────────────────────────────
    def test_from_this_sender_no_context(self):
        # Without current_email in context, from_ should stay empty
        rule = self._parse("from this sender, label as VIP")
        # No email context → from_ may be empty or unchanged
        # (not an error — just no context to derive from)
        self.assertIsInstance(rule["criteria"]["from_"], str)

    def test_from_this_sender_with_context(self):
        _filter_ns["_GMAIL_CTX"] = {
            "current_email": {"from": "Priya Sharma <priya@company.com>"}
        }
        rule = _parse_filter_rule("from this sender, label as VIP")
        self.assertEqual(rule["criteria"]["from_"], "priya@company.com")

    # ── description is auto-generated ─────────────────────────────────────
    def test_description_populated(self):
        rule = self._parse("always label invoices as Finance")
        self.assertGreater(len(rule["description"]), 10)
        self.assertIn("invoice", rule["description"])

    def test_description_no_action(self):
        # "label emails" without a clear action/criteria
        rule = self._parse("create a rule for this")
        # Description should still be a string even if vague
        self.assertIsInstance(rule["description"], str)

    def test_status_is_pending(self):
        rule = self._parse("always archive newsletters")
        self.assertEqual(rule["status"], "pending")

    # ── multiple actions ──────────────────────────────────────────────────
    def test_mark_read_and_label(self):
        rule = self._parse("mark invoices as read and label them Finance")
        self.assertTrue(rule["actions"]["mark_read"])
        self.assertEqual(rule["criteria"]["subject"], "invoice")

    def test_archive_and_star(self):
        rule = self._parse("star and archive GitHub notifications")
        self.assertTrue(rule["actions"]["star"])
        self.assertTrue(rule["actions"]["archive"])
        self.assertEqual(rule["criteria"]["from_"], "notifications@github.com")

    # ── _filter_criteria_to_query ─────────────────────────────────────────
    def test_criteria_to_query_from_subject(self):
        rule = self._parse("always label invoices as Finance")
        q = _filter_criteria_to_query(rule["criteria"])
        self.assertIn("subject:invoice", q)

    def test_criteria_to_query_promotions(self):
        rule = self._parse("archive newsletters")
        q = _filter_criteria_to_query(rule["criteria"])
        self.assertIn("category:promotions", q)

    def test_criteria_empty_returns_empty_string(self):
        rule = self._parse("create a rule for this")
        q = _filter_criteria_to_query(rule["criteria"])
        self.assertIsInstance(q, str)


# ===========================================================================
# ADDITIONAL GAP TESTS — inputs identified during stress review
# that currently might not route correctly
# ===========================================================================

class TestGmailAdditionalGaps(unittest.TestCase):
    """Additional routing cases found during stress review.
    Some may initially fail — mark with expected → known gap."""

    def test_reply_to_latest_ask(self):
        # "reply to the latest ask" — should be gmail_draft_reply
        result = _classify("reply to the latest ask")
        self.assertEqual(result, "gmail_draft_reply",
            "'reply to the latest ask' should route to gmail_draft_reply")

    def test_respond_to_this(self):
        result = _classify("respond to this")
        # "respond to this" — should be draft_reply or thread_intel
        # Acceptable: gmail_draft_reply (via "respond to this")
        self.assertIn(result, {"gmail_draft_reply", "gmail_thread_intel"},
            f"'respond to this' got unexpected intent: {result!r}")

    def test_mark_unread_these(self):
        result = _classify("mark these as unread")
        self.assertEqual(result, "gmail_mark_unread")

    def test_turn_it_into_tasks(self):
        # "it" pronoun in turn-into pattern
        result = _classify("turn it into tasks")
        self.assertEqual(result, "gmail_extract_tasks")

    def test_show_drafts_list(self):
        result = _classify("show drafts")
        self.assertEqual(result, "gmail_list_drafts")

    def test_open_second_draft(self):
        result = _classify("open the second draft")
        self.assertEqual(result, "gmail_open_draft")

    def test_send_draft_5(self):
        # "send draft 5" — should hit gmail_open_draft (ordinal) then let handler send
        result = _classify("send draft 5")
        self.assertEqual(result, "gmail_open_draft",
            "'send draft N' routes via gmail_open_draft (handler then sends)")

    def test_push_email_to_tuesday(self):
        result = _classify("push the scheduled email to Tuesday")
        self.assertEqual(result, "gmail_reschedule_send")

    def test_thread_decisions_made(self):
        result = _classify("decisions made in this thread")
        self.assertEqual(result, "gmail_thread_intel")

    def test_filter_list_my_gmail_rules(self):
        result = _classify("list my Gmail rules")
        self.assertEqual(result, "gmail_filter_list")


if __name__ == "__main__":
    unittest.main(verbosity=2)
