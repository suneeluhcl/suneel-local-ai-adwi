"""
commands/gmail.py — Gmail listing, display, and bounded mutating commands (Phases 5A + 6).

Phase 5A (read-only): show-draft, followups, scheduled, drafts, rules, promos,
spam, social, attachments.

Phase 6A (preview→confirm/cancel/undo cluster): archive, trash, mark-read,
mark-unread, confirm (with /confirm alias), cancel, undo. All mutations require
an explicit /gmail-confirm step — the preview commands only stage the action in
_GMAIL_CTX["pending"]; no live Gmail API call until confirm is issued.

Phase 6B (filter rule cluster): rule-build, rule-apply, rule-cancel. Rule
creation goes through a pending_rule preview step before apply.

Phase 7 (draft lifecycle cluster): compose, send-draft, cancel-draft, forward.
Compose and forward accept NL text args; send-draft and cancel-draft take no
args and use inline input() confirmations for safety.

Phase 8 (draft-editing cluster): rewrite, update-subject, add-cc, add-bcc.
All operate on the existing _GMAIL_CTX["draft"] in-place via gh.update_draft().
No live send; no draft creation or deletion.

Phase 9 (draft management cluster): open-draft, delete-draft. Operate on
_GMAIL_CTX["draft_list"] and _GMAIL_CTX["draft"]; use _resolve_draft_ref()
for ordinal/name disambiguation. delete-draft requires y/n confirmation.

Phase 10 (draft-reply): draft a reply to the current email. Requires
_GMAIL_CTX["current_email"]; optionally uses current_thread for context-aware
mode. LLM generates body, creates Gmail draft, shows preview — no live send.

Phase 11 (schedule cluster): schedule-send, cancel-scheduled, reschedule,
open-scheduled. All operate on the local scheduled-sends JSON queue via
_resolve_scheduled_ref() / _resolve_schedule_time(); no live send on any path.
open-scheduled makes a read-only gh.get_draft() call to load the draft.

Phase 12 (follow-up reminder cluster): followup, cancel-followup. Both operate
on the local follow-up reminder store (_load/_save_followup_reminders); no live
send. List-followups was already migrated in Phase 5A as /gmail-followups.

Deferred to Phase 13+: extract-tasks, triage, attachment mutations.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adwi.command_registry import CommandRegistry


def _cli():
    import importlib.util
    from pathlib import Path
    if "adwi_cli" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "adwi_cli",
            Path(__file__).parent.parent / "adwi_cli.py",
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["adwi_cli"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules["adwi_cli"]


# ── Phase 5A handlers (read-only) ─────────────────────────────────────────────


def _show_draft(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_show_draft()


def _followups(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_list_followups()


def _scheduled(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_list_scheduled()


def _drafts(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_list_drafts(args)


def _rules(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_filter_list(args)


def _promos(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_list_category("promotions")


def _spam(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_list_category("spam")


def _social(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_list_category("social")


def _attachments(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_list_attachments(args)


# ── Phase 6A handlers (preview→confirm/cancel/undo cluster) ───────────────────


def _archive(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_archive(args)


def _trash(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_trash_emails(args)


def _mark_read(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_mark_read(args)


def _mark_unread(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_mark_unread(args)


def _confirm(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_confirm()


def _cancel_action(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_cancel()


def _undo(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_undo()


# ── Phase 7 handlers (draft lifecycle cluster) ────────────────────────────────


def _compose(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_compose(args)


def _send_draft(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_send_draft()


def _cancel_draft(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_cancel_draft()


def _forward(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_forward(args)


# ── Phase 10 handler (draft-reply) ────────────────────────────────────────────


def _draft_reply(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_draft_reply(args)


# ── Phase 11 handlers (schedule cluster) ──────────────────────────────────────


def _schedule_send(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_schedule_send(args)


def _cancel_scheduled(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_cancel_scheduled_send(args)


def _reschedule(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_reschedule_send(args)


def _open_scheduled(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_open_scheduled_draft(args)


# ── Phase 12 handlers (follow-up reminder cluster) ────────────────────────────


def _followup(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_followup_reminder(args)


def _cancel_followup(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_cancel_followup(args)


# ── Phase 9 handlers (draft management cluster) ───────────────────────────────


def _open_draft(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_open_draft(args)


def _delete_draft(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_delete_draft(args)


# ── Phase 8 handlers (draft-editing cluster) ──────────────────────────────────


def _rewrite(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_rewrite_draft(args)


def _update_subject(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_update_subject(args)


def _add_cc(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_add_cc(args)


def _add_bcc(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_add_bcc(args)


# ── Phase 6B handlers (filter rule build→apply/cancel cluster) ────────────────


def _rule_build(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_filter_build(args)


def _rule_apply(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_filter_apply(args)


def _rule_cancel(args: str, ctx: dict) -> None:
    _cli().cmd_gmail_filter_cancel(args)


# ── Registration ──────────────────────────────────────────────────────────────


def register(registry: "CommandRegistry") -> None:
    # Phase 5A — read-only listing/display

    registry.register(
        "/gmail-show-draft",
        description="Show the current pending Gmail draft",
        category="gmail",
        intents=["gmail_show_draft"],
    )(_show_draft)

    registry.register(
        "/gmail-followups",
        description="List all Gmail follow-up reminders with live reply-detection",
        category="gmail",
        intents=["gmail_list_followups"],
    )(_followups)

    registry.register(
        "/gmail-scheduled",
        description="Show all Adwi-scheduled pending Gmail sends",
        category="gmail",
        intents=["gmail_list_scheduled"],
    )(_scheduled)

    registry.register(
        "/gmail-drafts",
        description="List all Gmail drafts with metadata",
        category="gmail",
        intents=["gmail_list_drafts"],
        args_schema={"filter": "str?"},
    )(_drafts)

    registry.register(
        "/gmail-rules",
        description="List locally saved Gmail filter rules",
        category="gmail",
        intents=["gmail_filter_list"],
        args_schema={"filter": "str?"},
    )(_rules)

    registry.register(
        "/gmail-promos",
        description="List Gmail Promotions category emails",
        category="gmail",
        intents=["gmail_list_category"],
    )(_promos)

    registry.register(
        "/gmail-spam",
        description="List Gmail Spam folder emails",
        category="gmail",
    )(_spam)

    registry.register(
        "/gmail-social",
        description="List Gmail Social category emails",
        category="gmail",
    )(_social)

    registry.register(
        "/gmail-attachments",
        description="List attachments on the current email or thread",
        category="gmail",
        intents=["gmail_list_attachments"],
        args_schema={"filter": "str?"},
    )(_attachments)

    # Phase 6A — preview→confirm/cancel/undo cluster

    registry.register(
        "/gmail-archive",
        description="Archive the current email or matching emails (preview before apply)",
        category="gmail",
        intents=["gmail_archive"],
        args_schema={"query": "str?"},
    )(_archive)

    registry.register(
        "/gmail-trash",
        description="Trash the current email or matching emails (preview before apply)",
        category="gmail",
        intents=["gmail_trash"],
        args_schema={"query": "str?"},
    )(_trash)

    registry.register(
        "/gmail-mark-read",
        description="Mark the current email or matching emails as read (preview before apply)",
        category="gmail",
        intents=["gmail_mark_read"],
        args_schema={"query": "str?"},
    )(_mark_read)

    registry.register(
        "/gmail-mark-unread",
        description="Mark the current email or matching emails as unread (preview before apply)",
        category="gmail",
        intents=["gmail_mark_unread"],
        args_schema={"query": "str?"},
    )(_mark_unread)

    registry.register(
        "/gmail-confirm",
        description="Confirm a pending Gmail action (archive / trash / mark)",
        category="gmail",
        aliases=["/confirm"],
        intents=["gmail_confirm"],
    )(_confirm)

    registry.register(
        "/gmail-cancel",
        description="Cancel the current pending Gmail action",
        category="gmail",
        intents=["gmail_cancel"],
    )(_cancel_action)

    registry.register(
        "/gmail-undo",
        description="Undo the last Gmail mutation (archive / trash / mark)",
        category="gmail",
        intents=["gmail_undo"],
    )(_undo)

    # Phase 6B — filter rule build→apply/cancel cluster

    registry.register(
        "/gmail-rule",
        description="Build a Gmail filter rule from natural language (preview before apply)",
        category="gmail",
        intents=["gmail_filter_build"],
        args_schema={"description": "str?"},
    )(_rule_build)

    registry.register(
        "/gmail-rule-apply",
        description="Apply the pending Gmail filter rule",
        category="gmail",
        intents=["gmail_filter_apply"],
    )(_rule_apply)

    registry.register(
        "/gmail-rule-cancel",
        description="Cancel the pending Gmail filter rule without applying",
        category="gmail",
        intents=["gmail_filter_cancel"],
    )(_rule_cancel)

    # Phase 7 — draft lifecycle cluster

    registry.register(
        "/gmail-compose",
        description="Compose a new email draft with contact resolution and CC/BCC support",
        category="gmail",
        intents=["gmail_compose"],
        args_schema={"instruction": "str?"},
    )(_compose)

    registry.register(
        "/gmail-send-draft",
        description="Send the current pending Gmail draft (shows preview, requires confirmation)",
        category="gmail",
        intents=["gmail_send_draft"],
    )(_send_draft)

    registry.register(
        "/gmail-cancel-draft",
        description="Cancel and delete the current pending Gmail draft",
        category="gmail",
        intents=["gmail_cancel_draft"],
    )(_cancel_draft)

    registry.register(
        "/gmail-forward",
        description="Forward the current email to a new recipient (creates a forward draft for review)",
        category="gmail",
        intents=["gmail_forward"],
        args_schema={"target": "str?"},
    )(_forward)

    # Phase 8 — draft-editing cluster

    registry.register(
        "/gmail-rewrite",
        description="Rewrite the current draft body per instruction (shorter, more formal, etc.)",
        category="gmail",
        intents=["gmail_rewrite_draft"],
        args_schema={"instruction": "str?"},
    )(_rewrite)

    registry.register(
        "/gmail-update-subject",
        description="Update the subject line of the current draft (LLM-generated or literal)",
        category="gmail",
        intents=["gmail_update_subject"],
        args_schema={"instruction": "str?"},
    )(_update_subject)

    registry.register(
        "/gmail-add-cc",
        description="Add a CC recipient to the current draft (contact resolution + Gmail draft update)",
        category="gmail",
        intents=["gmail_add_cc"],
        args_schema={"contact": "str?"},
    )(_add_cc)

    registry.register(
        "/gmail-add-bcc",
        description="Add a BCC recipient to the current draft (contact resolution + Gmail draft update)",
        category="gmail",
        intents=["gmail_add_bcc"],
        args_schema={"contact": "str?"},
    )(_add_bcc)

    # Phase 9 — draft management cluster

    registry.register(
        "/gmail-open-draft",
        description="Switch active draft context to a specific draft by ordinal or name",
        category="gmail",
        intents=["gmail_open_draft"],
        args_schema={"ref": "str?"},
    )(_open_draft)

    registry.register(
        "/gmail-delete-draft",
        description="Delete a draft by ordinal, name, or current draft (shows preview + confirm)",
        category="gmail",
        intents=["gmail_delete_draft"],
        args_schema={"ref": "str?"},
    )(_delete_draft)

    # Phase 10 — draft-reply

    registry.register(
        "/gmail-draft-reply",
        description="Draft a reply to the current email; LLM generates body, shows preview, no send",
        category="gmail",
        intents=["gmail_draft_reply"],
        args_schema={"instruction": "str?"},
    )(_draft_reply)

    # Phase 11 — schedule cluster

    registry.register(
        "/gmail-schedule",
        description="Schedule the current draft to send at a future time (preview + confirm, no live send)",
        category="gmail",
        intents=["gmail_schedule_send"],
        args_schema={"time": "str?"},
    )(_schedule_send)

    registry.register(
        "/gmail-cancel-scheduled",
        description="Cancel a pending scheduled send by index, ID, or most recent (confirm required)",
        category="gmail",
        intents=["gmail_cancel_scheduled"],
        args_schema={"ref": "str?"},
    )(_cancel_scheduled)

    registry.register(
        "/gmail-reschedule",
        description="Move a pending scheduled send to a new time (preview + confirm, no live send)",
        category="gmail",
        intents=["gmail_reschedule_send"],
        args_schema={"ref_and_time": "str?"},
    )(_reschedule)

    registry.register(
        "/gmail-open-scheduled",
        description="Load the draft from a pending scheduled send into session context for editing",
        category="gmail",
        intents=["gmail_open_scheduled"],
        args_schema={"ref": "str?"},
    )(_open_scheduled)

    # Phase 12 — follow-up reminder cluster

    registry.register(
        "/gmail-followup",
        description="Set a follow-up reminder on last sent email or current thread (confirm, no auto-send)",
        category="gmail",
        intents=["gmail_followup_reminder"],
        args_schema={"time": "str?"},
    )(_followup)

    registry.register(
        "/gmail-cancel-followup",
        description="Cancel an active follow-up reminder by index or most recent (confirm required)",
        category="gmail",
        intents=["gmail_cancel_followup"],
        args_schema={"ref": "str?"},
    )(_cancel_followup)
