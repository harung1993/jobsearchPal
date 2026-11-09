"""Follow-up reminders: emails you haven't answered, recruiters who went quiet, and applications with no news.

Worked out each time from the sorted emails and your Sent mail (headers only), so nothing to keep in sync.
You can mark one done or snooze it from the dashboard. The daily run writes a draft reply for each one
(`autoapply list --nudges` says where); nothing is ever sent for you.
"""
from __future__ import annotations

import email.utils
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from .db import DB

REPLY_AFTER_DAYS = 1        # a recruiter email you haven't answered
INTERVIEW_AFTER_HOURS = 12  # an interview invite you haven't answered
CHASE_AFTER_DAYS = 5        # you wrote last and the recruiter hasn't answered
APP_AFTER_DAYS = 14         # an application with only a confirmation, or nothing
STOP_AFTER_DAYS = 45        # older threads drop off

NO_REPLY = ("no-reply", "noreply", "donotreply", "do-not-reply", "notifications@", "mailer-daemon")


def _t(s: str | None) -> datetime | None:
    try:
        return datetime.strptime((s or "")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _addr(sender: str) -> tuple[str, str]:
    name, addr = email.utils.parseaddr(sender or "")
    return (name or addr.split("@")[0] or "them"), addr.lower()


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def draft_path(data_dir: Path, key: str) -> Path:
    return data_dir / "drafts" / f"{key}.md"


def compute(db: DB, data_dir: Path | None = None, now: datetime | None = None, include_hidden: bool = False,
            settings=None) -> list[dict]:
    """With settings, unemployment to-dos (claim day, work search, RESEA steps, agency letters) come too."""
    now = now or datetime.now()
    states = db.nudge_states()
    sent = [(s, _t(s["at"])) for s in db.sent()]

    def sent_to(addr: str, after: datetime) -> datetime | None:
        hits = [t for s, t in sent if t and t > after and addr and addr in (s["to_addrs"] or "").split()]
        return max(hits) if hits else None

    out: list[dict] = []
    events = db.events()  # settled only, newest first
    latest_from: dict[str, dict] = {}
    for e in events:
        _, a = _addr(e["sender"])
        if a and a not in latest_from:
            latest_from[a] = e

    for a, e in latest_from.items():
        at = _t(e["at"])
        if not at or (now - at).days > STOP_AFTER_DAYS or e["kind"] not in ("recruiter", "interview", "offer"):
            continue
        name, _ = _addr(e["sender"])
        job = db.get(e["job_id"]) if e["job_id"] else None
        about = f"{job['company']} · {job['title']}" if job else e["subject"]
        answered = sent_to(a, at)
        automated = any(x in a for x in NO_REPLY)
        if not answered:
            wait = timedelta(hours=INTERVIEW_AFTER_HOURS) if e["kind"] in ("interview", "offer") else timedelta(days=REPLY_AFTER_DAYS)
            if now - at < wait:
                continue
            if e["kind"] in ("interview", "offer"):
                title = (f"Book your interview time with {job['company'] if job else name}" if automated
                         else f"Reply to {name} about the {'offer' if e['kind'] == 'offer' else 'interview'}")
                kind = "interview"
            else:
                title, kind = f"Reply to {name}", "reply"
            out.append({"key": _key("reply", e["id"]), "kind": kind, "title": title, "about": about, "since": e["at"],
                        "days": (now - at).days, "to": "" if automated else a, "subject": e["subject"], "event": e,
                        "job": job, "why": f"They wrote {(now - at).days or 'less than 1'} day(s) ago. A short reply keeps it warm."})
        elif e["kind"] == "recruiter" and not automated and (now - answered).days >= CHASE_AFTER_DAYS \
                and (now - answered).days <= STOP_AFTER_DAYS:
            out.append({"key": _key("chase", a, answered.isoformat()), "kind": "chase", "title": f"Check in with {name}",
                        "about": about, "since": answered.strftime("%Y-%m-%d %H:%M"), "days": (now - answered).days,
                        "to": a, "subject": e["subject"], "event": e, "job": job,
                        "why": f"You last wrote {(now - answered).days} days ago. A friendly check-in is normal."})

    heard = {e["job_id"] for e in events if e["job_id"] and e["kind"] in ("interview", "offer", "rejected")}
    for j in db.by_status("submitted"):
        sub = _t(j["submitted_at"])
        if not sub or j["outcome"] not in (None, "", "confirmed") or j["id"] in heard:
            continue
        age = (now - sub).days
        if APP_AFTER_DAYS <= age <= STOP_AFTER_DAYS:
            out.append({"key": _key("app", j["id"]), "kind": "application", "title": f"Follow up on {j['company']}",
                        "about": j["title"], "since": j["submitted_at"], "days": age, "to": "", "subject": "",
                        "event": None, "job": j,
                        "why": f"Applied {age} days ago · no reply yet. Following up is normal."})

    if settings is not None:
        from . import benefits, stats
        from .web import my_state, work_search
        weeks = {w["start"]: w["count"] for w in stats.dua_weeks(db, now.date())}
        this = stats.week_start(now.date())
        out += benefits.todos(db, settings, my_state(settings), work_search(settings)[1], weeks.get(this, 0),
                              weeks.get(this - timedelta(days=7), 0), now)

    for n in out:
        st = states.get(n["key"])
        n["state"] = (st or {}).get("state") or "open"
        if n["state"] == "snoozed" and (st.get("until") or "") <= now.strftime("%Y-%m-%d %H:%M"):
            n["state"] = "open"
        if data_dir:
            p = draft_path(data_dir, n["key"])
            n["draft_path"] = str(p)
            n["draft"] = p.read_text() if p.exists() else ""
    order = {"appeal": 0, "claim": 0, "interview": 1, "resea": 1, "task": 1, "agency": 2, "worksearch": 2,
             "reply": 3, "chase": 4, "application": 5}
    out.sort(key=lambda n: (order[n["kind"]], -n["days"]))
    return out if include_hidden else [n for n in out if n["state"] == "open"]


def for_agent(db: DB, data_dir: Path, limit: int | None = None) -> list[dict]:
    """Open reminders without a draft yet, with what the agent needs to write one (at most `limit`)."""
    rows = []
    for n in compute(db, data_dir):
        if n["draft"] or n["kind"] not in ("reply", "chase", "application", "interview") or n["kind"] == "interview" and not n["to"]:
            continue  # booking links need you, not a draft
        e, j = n["event"] or {}, n["job"] or {}
        rows.append({"key": n["key"], "kind": n["kind"], "title": n["title"], "why": n["why"], "draft_path": n["draft_path"],
                     "to": n["to"], "subject": n["subject"], "company": j.get("company"), "role": j.get("title"),
                     "their_email": {"from": e.get("sender"), "at": e.get("at"), "text": (e.get("body") or "")[:2500]} if e else None})
    return rows if limit is None else rows[:limit]


def gmail_compose_url(n: dict) -> str:
    from urllib.parse import quote
    if not n.get("to"):
        return ""
    subj = n["subject"] if (n["subject"] or "").lower().startswith("re:") else f"Re: {n['subject']}"
    return (f"https://mail.google.com/mail/?view=cm&fs=1&to={quote(n['to'])}&su={quote(subj)}"
            f"&body={quote(n.get('draft') or '')}")
