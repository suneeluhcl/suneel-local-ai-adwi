"""
Gmail helper for Adwi — Phase 3: read/search/thread/category + mutation + draft/send.
Uses OAuth2 with client credentials from secrets.local.env.
Token stored in secrets/gmail-token.json (never printed).

Scope: gmail.modify — covers ALL operations: read, archive, trash, mark-read,
       create drafts, send drafts. No separate compose/send scope needed.

Phase 2 scope change from readonly → modify:
  Run /gmail-auth once to re-authorize. Scope detection is automatic.

Phase 3 note: no additional scope change required beyond Phase 2.
  gmail.modify already covers drafts.create, drafts.send, drafts.delete.
"""
import json
import os
import base64
from pathlib import Path

SECRETS_DIR  = Path.home() / "SuneelWorkSpace" / "secrets"
TOKEN_FILE   = SECRETS_DIR / "gmail-token.json"
SCOPES       = ["https://www.googleapis.com/auth/gmail.modify"]


def _load_secrets() -> dict:
    env_file = SECRETS_DIR / "secrets.local.env"
    d = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def get_service():
    """Return an authenticated Gmail service. Re-runs OAuth if scope mismatch."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        # Detect scope mismatch (e.g. old readonly token, now need modify)
        token_scopes = set(getattr(creds, "scopes", None) or [])
        required_scopes = set(SCOPES)
        if creds.valid and not required_scopes.issubset(token_scopes):
            creds = None  # Force re-auth to pick up expanded scopes

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None  # Refresh failed — full re-auth needed

    if not creds or not creds.valid:
        s = _load_secrets()
        client_config = {
            "installed": {
                "client_id":     s.get("GOOGLE_CLIENT_ID", ""),
                "client_secret": s.get("GOOGLE_CLIENT_SECRET", ""),
                "project_id":    s.get("GOOGLE_PROJECT_ID", ""),
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        if not client_config["installed"]["client_id"]:
            raise RuntimeError("GOOGLE_CLIENT_ID not set in secrets.local.env")
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
        TOKEN_FILE.chmod(0o600)

    return build("gmail", "v1", credentials=creds)


def _extract_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload (recursive)."""
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            d = part.get("body", {}).get("data", "")
            if d:
                return base64.urlsafe_b64decode(d).decode("utf-8", errors="replace")
        if part.get("parts"):
            result = _extract_body(part)
            if result:
                return result
    return ""


def list_emails(max_results=10, query="", inbox_only=True):
    """List recent emails newest-first. Returns dicts with thread_id included."""
    service = get_service()
    params = {"userId": "me", "maxResults": max_results * 2}
    if inbox_only and not query:
        params["labelIds"] = ["INBOX"]
    if query:
        if "label:" not in query and "in:" not in query:
            params["q"] = f"in:inbox {query}"
        else:
            params["q"] = query
    results = service.users().messages().list(**params).execute()
    messages = results.get("messages", [])

    emails = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
        emails.append({
            "id":           msg["id"],
            "thread_id":    detail.get("threadId", ""),
            "subject":      headers.get("Subject", "(no subject)"),
            "from":         headers.get("From", ""),
            "date":         headers.get("Date", ""),
            "snippet":      detail.get("snippet", "")[:200],
            "internalDate": int(detail.get("internalDate", 0)),
        })

    emails.sort(key=lambda e: e["internalDate"], reverse=True)
    return emails[:max_results]


def read_email(msg_id: str) -> dict:
    """Read full text of an email by ID. Includes thread_id and RFC-2822 message_id."""
    service = get_service()
    detail = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()
    headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
    body = _extract_body(detail.get("payload", {})) or detail.get("snippet", "")
    return {
        "id":         msg_id,
        "thread_id":  detail.get("threadId", ""),
        "subject":    headers.get("Subject", "(no subject)"),
        "from":       headers.get("From", ""),
        "to":         headers.get("To", ""),
        "date":       headers.get("Date", ""),
        "message_id": headers.get("Message-ID", ""),  # RFC-2822 ID for In-Reply-To threading
        "body":       body[:5000],
    }


def get_thread(thread_id: str) -> dict:
    """Load all messages in a thread."""
    service = get_service()
    t = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    msgs = []
    for msg in t.get("messages", []):
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = _extract_body(msg.get("payload", {})) or msg.get("snippet", "")
        msgs.append({
            "id":      msg["id"],
            "from":    headers.get("From", ""),
            "to":      headers.get("To", ""),
            "date":    headers.get("Date", ""),
            "subject": headers.get("Subject", ""),
            "body":    body[:2000],
            "snippet": msg.get("snippet", ""),
        })
    subject = msgs[0]["subject"] if msgs else "(no subject)"
    return {"thread_id": thread_id, "subject": subject, "messages": msgs, "count": len(msgs)}


def list_category(category: str = "INBOX", max_results: int = 10) -> list:
    """List emails by Gmail category label."""
    service = get_service()
    params = {"userId": "me", "maxResults": max_results * 2, "labelIds": [category]}
    results = service.users().messages().list(**params).execute()
    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
        emails.append({
            "id":           msg["id"],
            "thread_id":    detail.get("threadId", ""),
            "subject":      headers.get("Subject", "(no subject)"),
            "from":         headers.get("From", ""),
            "date":         headers.get("Date", ""),
            "snippet":      detail.get("snippet", "")[:200],
            "internalDate": int(detail.get("internalDate", 0)),
        })
    emails.sort(key=lambda e: e["internalDate"], reverse=True)
    return emails[:max_results]


def get_label_counts() -> dict:
    """Get message counts for INBOX, UNREAD, SENT, SPAM."""
    service = get_service()
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    counts = {}
    for label in labels:
        if label["name"] in ("INBOX", "UNREAD", "SENT", "SPAM"):
            detail = service.users().labels().get(userId="me", id=label["id"]).execute()
            counts[label["name"]] = {
                "total":  detail.get("messagesTotal", 0),
                "unread": detail.get("messagesUnread", 0),
            }
    return counts


# ── Phase 2: mutation helpers (require gmail.modify scope) ────────────────────

def _batch_modify(msg_ids: list, add_labels: list = None, remove_labels: list = None) -> int:
    """Apply a label modification to a batch of messages. Returns count processed."""
    if not msg_ids:
        return 0
    service = get_service()
    body = {}
    if add_labels:    body["addLabelIds"] = add_labels
    if remove_labels: body["removeLabelIds"] = remove_labels
    # Gmail batchModify accepts up to 1000 IDs per call
    for i in range(0, len(msg_ids), 1000):
        service.users().messages().batchModify(
            userId="me",
            body={"ids": msg_ids[i:i+1000], **body}
        ).execute()
    return len(msg_ids)


def archive_messages(msg_ids: list) -> int:
    """Archive messages (remove INBOX label). Returns count modified."""
    return _batch_modify(msg_ids, remove_labels=["INBOX"])


def trash_messages(msg_ids: list) -> int:
    """Move messages to Trash. Uses individual trash() calls for correct semantics."""
    if not msg_ids:
        return 0
    service = get_service()
    count = 0
    for mid in msg_ids:
        service.users().messages().trash(userId="me", id=mid).execute()
        count += 1
    return count


def mark_read(msg_ids: list) -> int:
    """Mark messages as read (remove UNREAD label). Returns count modified."""
    return _batch_modify(msg_ids, remove_labels=["UNREAD"])


def mark_unread(msg_ids: list) -> int:
    """Mark messages as unread (add UNREAD label). Returns count modified."""
    return _batch_modify(msg_ids, add_labels=["UNREAD"])


# ── Phase 3: draft / send helpers (gmail.modify scope covers all of these) ───

_ATTACH_MAX_BYTES = 20 * 1024 * 1024  # 20 MB per-file safety cap


def _build_raw_message(to: str, subject: str, body: str,
                        in_reply_to: str = "", references: str = "",
                        cc: str = "", bcc: str = "",
                        attachments: list = []) -> str:
    """
    Build a base64url-encoded MIME message string for the Gmail API.
    When attachments is non-empty, produces multipart/mixed with a text/plain part
    followed by one MIMEBase part per file.  Falls back to plain MIMEText when
    attachments is empty, preserving the pre-Phase-7 behaviour exactly.
    """
    from email.mime.text import MIMEText as _MIMEText
    if attachments:
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders as _enc
        import mimetypes
        msg = MIMEMultipart("mixed")
        msg.attach(_MIMEText(body, "plain", "utf-8"))
        for fpath in attachments:
            p = Path(fpath)
            ctype, enc = mimetypes.guess_type(str(p))
            if ctype is None or enc is not None:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            data = p.read_bytes()
            part = MIMEBase(maintype, subtype)
            part.set_payload(data)
            _enc.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=p.name)
            msg.attach(part)
    else:
        msg = _MIMEText(body, "plain", "utf-8")
    msg["To"]      = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"]  = cc
    if bcc:
        msg["Bcc"] = bcc
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = references or in_reply_to
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_draft_reply(reply_to_msg_id: str, message_id_header: str,
                        thread_id: str, to: str, subject: str, body: str,
                        cc: str = "", bcc: str = "",
                        attachments: list = []) -> dict:
    """Create a Gmail draft reply in the same thread. Returns draft context dict."""
    service = get_service()
    subj = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    raw  = _build_raw_message(to, subj, body,
                               in_reply_to=message_id_header,
                               references=message_id_header,
                               cc=cc, bcc=bcc, attachments=attachments)
    body_payload = {"message": {"raw": raw}}
    if thread_id:
        body_payload["message"]["threadId"] = thread_id
    draft = service.users().drafts().create(userId="me", body=body_payload).execute()
    return {
        "draft_id":             draft["id"],
        "thread_id":            thread_id,
        "message_id":           message_id_header,
        "to":                   to,
        "cc":                   cc,
        "bcc":                  bcc,
        "subject":              subj,
        "body":                 body,
        "mode":                 "reply",
        "outbound_attachments": [],
    }


def create_draft_compose(to: str, subject: str, body: str,
                          cc: str = "", bcc: str = "",
                          attachments: list = []) -> dict:
    """Create a Gmail draft for a new (non-reply) email. Returns draft context dict."""
    service = get_service()
    raw   = _build_raw_message(to, subject, body, cc=cc, bcc=bcc, attachments=attachments)
    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}}
    ).execute()
    return {
        "draft_id":             draft["id"],
        "thread_id":            None,
        "to":                   to,
        "cc":                   cc,
        "bcc":                  bcc,
        "subject":              subject,
        "body":                 body,
        "mode":                 "compose",
        "outbound_attachments": [],
    }


def get_my_email() -> str:
    """Return the authenticated Gmail account's email address."""
    service = get_service()
    return service.users().getProfile(userId="me").execute().get("emailAddress", "")


def get_draft(draft_id: str) -> dict:
    """Fetch draft details from Gmail. Returns subject/to/body dict."""
    service = get_service()
    d = service.users().drafts().get(userId="me", id=draft_id, format="full").execute()
    msg = d.get("message", {})
    headers = {h["name"]: h["value"]
               for h in msg.get("payload", {}).get("headers", [])}
    body = _extract_body(msg.get("payload", {})) or msg.get("snippet", "")
    return {
        "draft_id": d["id"],
        "to":       headers.get("To", ""),
        "subject":  headers.get("Subject", ""),
        "body":     body[:3000],
    }


def send_draft(draft_id: str) -> dict:
    """Send an existing Gmail draft. Returns sent message info dict."""
    service = get_service()
    return service.users().drafts().send(
        userId="me",
        body={"id": draft_id}
    ).execute()


def delete_draft(draft_id: str) -> None:
    """Delete a Gmail draft (permanent — moves to Trash area, not inbox)."""
    service = get_service()
    service.users().drafts().delete(userId="me", id=draft_id).execute()


def update_draft(draft_id: str, to: str, subject: str, body: str,
                  thread_id: str = None, message_id_header: str = None,
                  cc: str = "", bcc: str = "",
                  attachments: list = []) -> dict:
    """Replace the content of an existing Gmail draft in-place. Returns updated context dict."""
    service = get_service()
    raw = _build_raw_message(to, subject, body,
                              in_reply_to=message_id_header or "",
                              references=message_id_header or "",
                              cc=cc, bcc=bcc, attachments=attachments)
    body_payload = {"message": {"raw": raw}}
    if thread_id:
        body_payload["message"]["threadId"] = thread_id
    result = service.users().drafts().update(
        userId="me", id=draft_id, body=body_payload
    ).execute()
    return {
        "draft_id":   result["id"],
        "to":         to,
        "cc":         cc,
        "bcc":        bcc,
        "subject":    subject,
        "body":       body,
        "thread_id":  thread_id,
        "message_id": message_id_header,
    }


# ── Phase 4: contact resolution ───────────────────────────────────────────────

def resolve_contact(name: str, max_candidates: int = 5) -> list:
    """
    Resolve a display name to email addresses using Gmail sent/received history.
    Returns list of dicts: [{"email": "...", "display": "...", "count": N}, ...]
    sorted by frequency (most-emailed first).
    """
    import re as _re
    from collections import Counter

    service = get_service()
    name_lower = name.lower()

    def _parse_address(header_val: str) -> list:
        """Parse one or more 'Display <email>' entries from a header value."""
        found = []
        for part in header_val.split(","):
            part = part.strip()
            email_m = _re.search(r"<([^>]+@[^>]+)>", part) or _re.search(r"(\S+@\S+\.\S+)", part)
            if not email_m:
                continue
            email_addr = email_m.group(1).strip().lower()
            disp_m = _re.match(r'^"?(.+?)"?\s*<', part.strip())
            display = disp_m.group(1).strip() if disp_m else email_addr.split("@")[0]
            # Only include if name word appears in display name or email prefix
            if (_re.search(r'\b' + _re.escape(name_lower) + r'\b', display.lower()) or
                    _re.search(r'\b' + _re.escape(name_lower) + r'\b', email_addr.split("@")[0])):
                found.append((email_addr, display))
        return found

    email_counter: Counter = Counter()
    email_display: dict    = {}

    # Search sent mail
    try:
        sent = service.users().messages().list(
            userId="me", q=f"to:{name} in:sent", maxResults=20
        ).execute()
        for msg in (sent.get("messages") or []):
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["To"]
            ).execute()
            headers = {h["name"]: h["value"]
                       for h in detail.get("payload", {}).get("headers", [])}
            for email_addr, display in _parse_address(headers.get("To", "")):
                email_counter[email_addr] += 1
                if email_addr not in email_display:
                    email_display[email_addr] = display
    except Exception:
        pass

    # Search received mail
    try:
        rcvd = service.users().messages().list(
            userId="me", q=f"from:{name}", maxResults=15
        ).execute()
        for msg in (rcvd.get("messages") or []):
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From"]
            ).execute()
            headers = {h["name"]: h["value"]
                       for h in detail.get("payload", {}).get("headers", [])}
            for email_addr, display in _parse_address(headers.get("From", "")):
                email_counter[email_addr] += 1
                if email_addr not in email_display:
                    email_display[email_addr] = display
    except Exception:
        pass

    candidates = []
    for email_addr, count in email_counter.most_common(max_candidates):
        candidates.append({
            "email":   email_addr,
            "display": email_display.get(email_addr, email_addr.split("@")[0]),
            "count":   count,
        })
    return candidates


# ── Phase 6: attachment helpers ───────────────────────────────────────────────

def _extract_attachments(payload: dict, msg_id: str = "") -> list:
    """
    Recursively extract attachment metadata from a Gmail message payload part.
    Returns list of dicts: {filename, mime_type, size, attachment_id, message_id}.
    Only includes parts that have both a filename and an attachmentId (real attachments,
    not inline text/html body parts).
    """
    result = []
    fname  = payload.get("filename", "")
    att_id = payload.get("body", {}).get("attachmentId", "")
    if fname and att_id:
        result.append({
            "filename":      fname,
            "mime_type":     payload.get("mimeType", "application/octet-stream"),
            "size":          payload.get("body", {}).get("size", 0),
            "attachment_id": att_id,
            "message_id":    msg_id,
        })
    for part in payload.get("parts", []):
        result.extend(_extract_attachments(part, msg_id))
    return result


def list_attachments(msg_id: str) -> list:
    """List attachment metadata on a single message. Returns list of attachment dicts."""
    service = get_service()
    detail  = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()
    return _extract_attachments(detail.get("payload", {}), msg_id)


def list_thread_attachments(thread_id: str) -> list:
    """List all attachments across every message in a thread."""
    service = get_service()
    t = service.users().threads().get(
        userId="me", id=thread_id, format="full"
    ).execute()
    result = []
    for msg in t.get("messages", []):
        result.extend(_extract_attachments(msg.get("payload", {}), msg["id"]))
    return result


def fetch_attachment(msg_id: str, attachment_id: str) -> bytes:
    """Fetch the raw bytes of an attachment from Gmail. Returns decoded bytes."""
    service = get_service()
    att = service.users().messages().attachments().get(
        userId="me", messageId=msg_id, id=attachment_id
    ).execute()
    data = att.get("data", "")
    return base64.urlsafe_b64decode(data) if data else b""


def save_attachment(msg_id: str, attachment_id: str, filename: str,
                    save_dir: Path) -> Path:
    """
    Fetch an attachment from Gmail and write it to save_dir.
    Sanitizes the filename (strips directory traversal, limits chars).
    Appends a numeric suffix if the destination already exists.
    Returns the saved Path.
    """
    import re as _re
    # Strip path components and restrict to safe chars
    safe_name = Path(filename).name
    safe_name = _re.sub(r"[^\w.\-() ]", "_", safe_name)[:200].strip()
    if not safe_name:
        safe_name = f"attachment_{attachment_id[:8]}"
    save_dir.mkdir(parents=True, exist_ok=True)
    dest = save_dir / safe_name
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        n = 1
        while dest.exists():
            dest = save_dir / f"{stem}_{n}{suffix}"
            n += 1
    data = fetch_attachment(msg_id, attachment_id)
    dest.write_bytes(data)
    return dest
