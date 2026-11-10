"""Reads job-alert emails (LinkedIn, Built In, Indeed...) over IMAP so Claude can pull roles out of them.

Gmail, iCloud or Yahoo, with an app password: GMAIL_USER and GMAIL_APP_PASSWORD (and EMAIL_PROVIDER when it
isn't Gmail), plus any extra inboxes (see mailboxes.py). Reads All Mail, Spam and Trash (Inbox, Archive, Junk
and Trash where there is no All Mail). Read-only: messages are fetched with BODY.PEEK and stay unread.
"""
from __future__ import annotations

import email
import email.header
import email.utils
import html
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.message import Message

DEFAULT_SENDERS = [
    "jobalerts-noreply@linkedin.com",
    "jobs-noreply@linkedin.com",
    "builtin.com",
    "alert@indeed.com",
    "match.indeed.com",  # Indeed's job-match emails (donotreply@match.indeed.com)
    "glassdoor.com",
    "wellfound.com",
    "higheredjobs.com",
    "ziprecruiter.com",
    "dice.com",
]


def html_to_text(s: str) -> str:
    """Keeps link targets ("Title (url)"), since the job URL is the point of an alert."""
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: f" {m.group(2)} ({m.group(1)}) ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t ]+", " ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def message_text(msg: Message) -> str:
    plain, rich = None, None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html") or part.get_filename():
            continue
        body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/html" and rich is None:
            rich = html_to_text(body)
        elif ctype == "text/plain" and plain is None:
            plain = body
    # HTML keeps the real job links; plain-text alerts often hide them behind tracking redirects.
    return (rich or plain or "").strip()


FOLDER_FLAGS = ("\\All", "\\Junk", "\\Trash")  # All Mail leaves out Spam and Trash, so read those too


def _flagged(m) -> dict[str, str]:
    """Folder name by special-use flag (\\All, \\Junk, \\Trash, \\Sent, \\Archive), so any language works."""
    found = {}
    _, rows = m.list()
    for row in rows or []:
        line = row.decode(errors="replace") if isinstance(row, bytes) else str(row)
        mt = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if not mt:
            continue
        for f in ("\\All", "\\Junk", "\\Trash", "\\Sent", "\\Archive"):
            if f.lower() in mt["flags"].lower().split():
                found.setdefault(f, mt["name"].strip())
    return found


def folders(m, provider: str = "gmail") -> list[str]:
    """All Mail, Spam and Trash by their special-use flags, so it works in any Gmail language ("Bin", "Papierkorb").
    Providers without an All Mail folder (iCloud, Yahoo): Inbox, Archive, Junk and Trash."""
    found = _flagged(m)
    if "\\All" in found or provider == "gmail":
        return [found[f] for f in FOLDER_FLAGS if f in found] or ['"[Gmail]/All Mail"', '"[Gmail]/Spam"', '"[Gmail]/Trash"']
    return ["INBOX", *[found[f] for f in ("\\Archive", "\\Junk", "\\Trash") if f in found]]


def messages(days: int, senders: list[str], mailbox: str | None = None, gmail_queries: list[str] = (), words: list[str] = ()):
    """Yields (Message-ID, from name, from address, subject, datetime, text, raw bytes) for mail from
    any sender substring, or matching any Gmail search query, in the last `days` days, from every connected
    inbox (main first). Inboxes that aren't Gmail can't run Gmail's search language, so there `words` are
    looked up instead (plain IMAP TEXT search). Read-only: each folder is opened with readonly=True and bodies are
    fetched with BODY.PEEK, so nothing is marked read, moved or deleted."""
    from . import mailboxes
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    seen = set()
    for acct in mailboxes.accounts():
        gmail = acct["provider"] == "gmail"
        with imaplib.IMAP4_SSL(mailboxes.PROVIDERS[acct["provider"]]["imap"]) as m:
            m.login(acct["user"], acct["password"])
            boxes = [mailbox] if mailbox else folders(m, acct["provider"])
            for box in boxes:
                if m.select(box, readonly=True)[0] != "OK":
                    if box == boxes[0]:
                        m.select("INBOX", readonly=True)
                    else:
                        continue
                ids = set()
                for sender in senders:
                    _, data = m.search(None, "SINCE", since, "FROM", f'"{sender}"')
                    ids.update(data[0].split())
                if gmail:
                    for q in gmail_queries:
                        # X-GM-RAW takes Gmail's own search syntax (newer_than:, OR, -category:).
                        _, data = m.search(None, "X-GM-RAW", '"' + f"in:anywhere newer_than:{days}d {q}".replace('"', '\\"') + '"')
                        ids.update(data[0].split())
                else:
                    for w in words:
                        _, data = m.search(None, "SINCE", since, "TEXT", f'"{w}"')
                        ids.update(data[0].split())
                for i in sorted(ids, key=int):
                    _, data = m.fetch(i, "(BODY.PEEK[])")
                    msg = email.message_from_bytes(data[0][1])
                    mid = msg.get("Message-ID") or f"imap:{acct['user']}:{box}:{i.decode()}"
                    if mid in seen:
                        continue
                    seen.add(mid)
                    name, addr = email.utils.parseaddr(msg.get("From", ""))
                    try:
                        when = email.utils.parsedate_to_datetime(msg.get("Date"))
                    except (TypeError, ValueError):
                        when = datetime.now()
                    subject = str(email.header.make_header(email.header.decode_header(msg.get("Subject", ""))))
                    yield (mid, name, addr, subject, when, message_text(msg), data[0][1])


def fetch(days: int = 1, senders: list[str] | None = None, max_chars: int = 8000) -> list[dict]:
    return [{"from": addr, "subject": subject, "date": when.isoformat(), "text": text[:max_chars]}
            for _, _, addr, subject, when, text, _ in messages(days, senders or DEFAULT_SENDERS)]


def sent_mail(days: int):
    """Yields (Message-ID, datetime, [to/cc addresses], subject, In-Reply-To) for mail you sent in the last
    `days` days, from every connected inbox. Headers only, read-only: used to tell which emails you've already answered."""
    from . import mailboxes
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    for acct in mailboxes.accounts():
        with imaplib.IMAP4_SSL(mailboxes.PROVIDERS[acct["provider"]]["imap"]) as m:
            m.login(acct["user"], acct["password"])
            if acct["provider"] == "gmail":
                m.select('"[Gmail]/All Mail"', readonly=True)
                _, data = m.search(None, "X-GM-RAW", f'"in:sent newer_than:{days}d"')
            else:
                box = _flagged(m).get("\\Sent")
                if not box or m.select(box, readonly=True)[0] != "OK":
                    continue
                _, data = m.search(None, "SINCE", since)
            for i in data[0].split():
                _, d = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE TO CC SUBJECT IN-REPLY-TO)])")
                msg = email.message_from_bytes(d[0][1])
                try:
                    when = email.utils.parsedate_to_datetime(msg.get("Date"))
                except (TypeError, ValueError):
                    continue
                to = [a.lower() for _, a in email.utils.getaddresses(msg.get_all("To", []) + msg.get_all("Cc", [])) if a]
                subject = str(email.header.make_header(email.header.decode_header(msg.get("Subject", ""))))
                yield (msg.get("Message-ID") or f"imap-sent:{acct['user']}:{i.decode()}", when, to, subject,
                       (msg.get("In-Reply-To") or "").strip())
