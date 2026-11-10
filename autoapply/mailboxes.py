"""The email accounts jobsearchPal reads: one main inbox (recommended), optional extra inboxes, and other
addresses of yours that forward into the main one.

Main inbox: EMAIL_PROVIDER (gmail when unset), GMAIL_USER and GMAIL_APP_PASSWORD. The GMAIL_ names stay for
every provider so existing installs keep working. Extra inboxes: EXTRA_INBOXES, a JSON list of
{"provider", "user", "password"}, saved in data/secrets.json like the main login. Forwarded addresses:
OWN_ADDRESSES, comma-separated; mail from them counts as yours.

Every provider here signs in with an app password over IMAP (read-only) and sends the brief over SMTP.
Outlook.com and Hotmail are not in the list on purpose: Microsoft turned off app-password sign-in for
personal accounts in September 2024, so those addresses are forwarded to the main inbox instead.
"""
from __future__ import annotations

import json
import os

PROVIDERS = {
    "gmail": {"label": "Gmail", "imap": "imap.gmail.com", "smtp": ("smtp.gmail.com", 465, "ssl"),
              "app_password": "https://myaccount.google.com/apppasswords",
              "how": "Turn on 2-step verification, then create an app password at myaccount.google.com/apppasswords.",
              "domains": ("gmail.com", "googlemail.com")},
    "icloud": {"label": "iCloud Mail", "imap": "imap.mail.me.com", "smtp": ("smtp.mail.me.com", 587, "starttls"),
               "app_password": "https://account.apple.com/account/manage",
               "how": "At account.apple.com, Sign-In and Security, App-Specific Passwords, create one. Sign in with your full iCloud address.",
               "domains": ("icloud.com", "me.com", "mac.com")},
    "yahoo": {"label": "Yahoo Mail", "imap": "imap.mail.yahoo.com", "smtp": ("smtp.mail.yahoo.com", 465, "ssl"),
              "app_password": "https://login.yahoo.com/account/security",
              "how": "In Yahoo Account Security, Generate app password (turn on 2-step verification first).",
              "domains": ("yahoo.com", "ymail.com", "rocketmail.com")},
}

# How to forward job mail from another address into the main inbox, by provider. Shown on Setup.
FORWARDING = {
    "gmail": "Gmail: Settings, See all settings, Forwarding and POP/IMAP, Add a forwarding address. Gmail sends a code "
             "to your main inbox to confirm; then pick 'Forward a copy' and keep Gmail's copy.",
    "outlook": "Outlook.com or Hotmail: Settings, Mail, Forwarding, turn on forwarding, enter your main address, and tick "
               "'Keep a copy of forwarded messages'.",
    "icloud": "iCloud Mail: at icloud.com/mail, Settings, Mail Forwarding, forward to your main address and keep a copy.",
    "yahoo": "Yahoo Mail: Settings, More Settings, Mailboxes, pick the address, Forwarding, enter your main address and verify it.",
    "other": "Most providers have a Forwarding setting under Settings or Mail rules: forward everything (or just job mail) to "
             "your main address and keep a copy.",
}
OUTLOOK_DOMAINS = ("outlook.com", "hotmail.com", "live.com", "msn.com")


def provider_for(address: str) -> str:
    """The provider an address most likely uses, from its domain: gmail, outlook, icloud, yahoo or other."""
    dom = (address or "").rsplit("@", 1)[-1].strip().lower()
    if dom in OUTLOOK_DOMAINS:
        return "outlook"
    for key, p in PROVIDERS.items():
        if dom in p["domains"]:
            return key
    return "other"


def main_provider() -> str:
    p = (os.environ.get("EMAIL_PROVIDER") or "gmail").strip().lower()
    return p if p in PROVIDERS else "gmail"


def main() -> dict | None:
    """The main inbox, or None when it isn't set up."""
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and pw):
        return None
    return {"provider": main_provider(), "user": user.strip(), "password": pw, "main": True}


def extras() -> list[dict]:
    """Extra inboxes from EXTRA_INBOXES; bad entries are skipped."""
    try:
        rows = json.loads(os.environ.get("EXTRA_INBOXES") or "[]")
    except ValueError:
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("user") and r.get("password") and r.get("provider") in PROVIDERS:
            out.append({"provider": r["provider"], "user": str(r["user"]).strip(), "password": str(r["password"]), "main": False})
    return out


def accounts() -> list[dict]:
    """Every inbox to read, main first. Raises when there is no main inbox."""
    m = main()
    if not m:
        raise RuntimeError("set GMAIL_USER and GMAIL_APP_PASSWORD in .env, or connect your email on Setup")
    seen, out = set(), []
    for a in [m, *extras()]:
        if a["user"].lower() not in seen:
            seen.add(a["user"].lower())
            out.append(a)
    return out


def forwarded() -> list[str]:
    return [a.strip().lower() for a in (os.environ.get("OWN_ADDRESSES") or "").split(",") if "@" in a]


def own_addresses() -> set[str]:
    """Every address that is you: the main inbox, extra inboxes and forwarded addresses."""
    main_user = (os.environ.get("GMAIL_USER") or "").strip().lower()  # counts even before its password is saved
    return {a for a in [main_user, *(x["user"].lower() for x in extras()), *forwarded()] if a}


def save_extras(prefs, rows: list[dict]):
    prefs.set_key("EXTRA_INBOXES", json.dumps([{k: r[k] for k in ("provider", "user", "password")} for r in rows]) if rows else "")


def imap(account: dict):
    """An IMAP connection for this account, signed in. Use it as a context manager."""
    import imaplib
    m = imaplib.IMAP4_SSL(PROVIDERS[account["provider"]]["imap"])
    m.login(account["user"], account["password"])
    return m


def test(provider: str, user: str, pw: str) -> str:
    """'' when the login works, else a short reason in plain words."""
    import imaplib
    p = PROVIDERS.get(provider)
    if not p:
        return "Pick Gmail, iCloud or Yahoo. For Outlook or Hotmail, forward that mail to your main inbox instead."
    try:
        with imaplib.IMAP4_SSL(p["imap"], timeout=20) as m:
            m.login(user, pw)
        return ""
    except imaplib.IMAP4.error as e:
        msg = str(e)
        if "AUTH" in msg.upper() or "credentials" in msg.lower() or "invalid" in msg.lower():
            return f"{p['label']} refused the login. Use an app password, not your normal password. {p['how']}"
        return msg[:200]
    except OSError as e:
        return f"couldn't reach {p['label']}: {e}"[:200]
