"""The pal's voice: which morning it is, what to celebrate (once), the rejection note, and an honest market line.

Pure functions of the database, stats.compute() and the clock, so every page, the morning brief and the phone push
say the same thing. The words follow VOICE.md: honest about how hard this is, on the person's side, never a promise
of an outcome, never a research figure, never a softened number.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

MARKET_FILE = Path(__file__).parent / "market.yaml"
MARKET_MAX_AGE_DAYS = 45    # "right now" must be true this month: a line older than this stops showing (see VOICE.md, rule 9)
QUIET_DAYS = 10             # no reply of any kind for this long reads as a quiet stretch
LONG_SEARCH_WEEKS = 12      # from the first application; the market line joins the morning from here
CELEBRATE_DAYS = 7          # only fresh news celebrates, so a first deploy doesn't replay old interviews
REJECTION_NOTE_DAYS = 3

# One line per state per day, rotated by date so the same words don't greet you two mornings running.
# {co} is the company, {ready} a short phrase about what's waiting.
LINES = {
    "offer": ["You did this. Every application and every hard morning led here. Take a breath before you decide.",
              "This is the one you've been working toward. Take your time with it."],
    "interview": ["{co} wants to talk. Let's look at that first.",
                  "Good news first: {co} wrote back about an interview."],
    "reply": ["{co} wrote back. Let's look at that first.",
              "Someone's reaching out: {co}. Worth a look this morning."],
    # Not personal, not permanent, and one thing in their control; never "it's never you" (Kroft, Lange and Notowidigdo 2013; see VOICE.md, rule 3).
    "rejection": ["{co} said no this time. It stings. It's one stone in a very big ocean, and it doesn't decide the rest of your search.",
                  "A no from {co}. That stings, and it's fine that it does. One stone in a big ocean; most applications end "
                  "this way, even good ones. {ready}"],
    # After a week or more with nothing done: no catch-up list, just what's ready and one place to start.
    "back": ["No catch-up list today: just what's ready, and one place to start. {ready}",
             "Time away is part of a long search. Let's start with one thing. {ready}"],
    "evening": ["You've done enough for today. Everything here will still be waiting in the morning.",
                "Searching is real work. It's fine to stop for today."],
    "monday": ["Last week's effort still counts. {record}{ready}",
               "A fresh week, and a gentle place to start. {ready}"],
    "start": ["Starting a search is a lot. We'll take it one morning at a time. {ready}",
              "This is where your search lives now. {ready}"],
    "quiet": ["Quiet weeks are common right now; it says more about the market than about you. {record}{ready}",
              "No news is the hardest part of a search. What you've sent is still out there. {ready}",
              "A slow week doesn't undo the work you've done. {record}{ready}"],
    "default": ["Here's where things stand. {record}{ready}",
                "Glad you're here. {record}{ready}",
                "One step at a time today. {ready}"],
}
HEADLINE = {"offer": "An offer came in.", "interview": "Someone wants to talk.", "reply": "Someone wrote back.",
            "monday": "New week.", "start": "Welcome.", "back": "Welcome back."}


def _at(e: dict) -> datetime | None:
    try:
        return datetime.strptime(str(e.get("at") or "")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            return datetime.strptime(str(e.get("at") or "")[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _co(name: str) -> str:
    return name.title() if name and name.islower() else (name or "")


def company(db, e: dict) -> str:
    """The company an email is about: the tracked job's company, else the sender's display name."""
    job = db.get(e["job_id"]) if e.get("job_id") else None
    if job and job.get("company"):
        return _co(job["company"])
    return (e.get("sender") or "").split(" <")[0].strip().strip('"') or "A company"


def _recent(db, kinds: tuple, since: datetime) -> list[dict]:
    return [e for e in db.events() if e["kind"] in kinds and (_at(e) or datetime.min) >= since]


def _ready_phrase(s: dict) -> str:
    n = len(s.get("ready") or [])
    if n:
        return f"{'One role is' if n == 1 else f'{n} roles are'} ready when you are."
    if not s.get("applied"):
        return "The next daily run brings your first roles to look at."
    return "The next run looks for more."


def _record(s: dict, now: datetime) -> str:
    """Encouragement from what the person has done, never a forecast (Oettingen and Mayer 2002; VOICE.md, rule 2)."""
    sent = [a for a in s.get("applications") or [] if a.get("submitted_at")]
    yday = (now.date() - timedelta(days=1)).isoformat()
    n_yday = sum(1 for a in sent if a["submitted_at"][:10] == yday)
    if n_yday:
        return f"Yesterday you sent {n_yday}, and that counts. "
    if int(s.get("interviews") or 0) >= 2:
        return f"You've had {s['interviews']} interviews from this search, so employers do pick you out. "
    week = s.get("this_week_start")
    n_week = sum(1 for a in sent if week and a["submitted_at"][:10] >= week.isoformat())
    if n_week:
        return f"You've sent {n_week} this week. "
    return ""


def salutation(now: datetime, first_name: str) -> str:
    part = "Morning" if now.hour < 12 else ("Afternoon" if now.hour < 18 else "Evening")
    return f"{part}, {first_name}." if first_name else f"{part}."


def greeting(db, s: dict, now: datetime, first_name: str = "") -> dict:
    """{"state", "title", "line", "market"}: the welcome at the top of the dashboard (and the brief)."""
    ev = None
    state = "default"
    checks = [("offer", ("offer",), 7), ("interview", ("interview",), 3), ("reply", ("recruiter",), 2), ("rejection", ("rejected",), 2)]
    for name, kinds, days in checks:
        hits = _recent(db, kinds, now - timedelta(days=days))
        if hits:
            state, ev = name, hits[0]
            break
    else:
        heard = _recent(db, ("confirmed", "interview", "rejected", "offer", "recruiter"), now - timedelta(days=QUIET_DAYS))
        from . import coach
        if s.get("applied") and coach.away_days(db, s, now.date()) >= coach.AWAY_DAYS:
            state = "back"
        elif now.hour >= 20:
            state = "evening"
        elif now.weekday() == 0 and now.hour < 12 and s.get("applied"):
            state = "monday"
        elif not s.get("applied"):
            state = "start"
        elif not heard:
            state = "quiet"
    variants = LINES[state]
    line = variants[now.toordinal() % len(variants)].format(co=company(db, ev) if ev else "", ready=_ready_phrase(s),
                                                             record=_record(s, now)).strip()
    title = salutation(now, first_name)
    if state in HEADLINE:
        title = f"{title} {HEADLINE[state]}"
    first = min((a["submitted_at"] for a in s.get("applications") or [] if a.get("submitted_at")), default=None)
    long_search = bool(first) and (now - datetime.strptime(first[:10], "%Y-%m-%d")).days >= LONG_SEARCH_WEEKS * 7
    market = market_line(now.date()) if state in ("quiet", "rejection") or (long_search and state == "default") else None
    return {"state": state, "title": title, "line": line, "market": market}


def celebration(db, s: dict, today: date, label: str = "work search") -> dict | None:
    """The one unseen celebration to play now, biggest first: an offer, an interview, then this week's effort met.
    Keyed by job (or company), so several emails about one interview celebrate once. The caller marks it seen
    (db.set_nudge(key, "done")) once it has been shown."""
    seen = db.nudge_states()
    since = datetime.combine(today - timedelta(days=CELEBRATE_DAYS), datetime.min.time())
    for kind in ("offer", "interview"):
        for e in _recent(db, (kind,), since):
            co = company(db, e)
            # Once per job, not per email: one interview process sends scheduling, confirmation and reminder emails.
            key = f"celebrate:{kind}:{e.get('job_id') or co.lower()}"
            if key in seen or any(k.startswith(f"celebrate:{kind}:") and k.endswith(f":{e['id']}") for k in seen):
                continue
            if kind == "offer":
                return {"key": key, "kind": kind, "title": f"An offer from {co}",
                        "line": "You did this. Every application, every follow-up and every hard morning led here. "
                                "Take a breath before you decide."}
            return {"key": key, "kind": kind, "title": f"{co} wants to talk",
                    "line": "You got their attention. A prep pack with likely questions and your best stories is on its way."}
    floor, done = int(s.get("dua_floor") or 0), int(s.get("this_week") or 0)
    week = s.get("this_week_start")
    if floor and done >= floor and week:
        key = f"celebrate:week:{week.isoformat()}"
        if key not in seen:
            return {"key": key, "kind": "week", "title": "That's this week covered",
                    "line": f"{done} activities logged for your {label}. The rest of the week is yours."}
    return milestone(db, s, today)


# Applications sent, counted up. Small moments that credit effort from the record (VOICE rules 2, 5 and 7): never a target,
# never a streak, and nothing is said between them.
MILESTONES = (1, 10, 25, 50, 75, 100, 150, 200, 300)


def milestone(db, s: dict, today: date) -> dict | None:
    """The newest milestone of applications sent, once, and only when the application that reached it went out in the
    last CELEBRATE_DAYS (a first deploy on a long search doesn't announce old ones)."""
    sent = sorted(str(j.get("submitted_at") or "")[:10] for j in (s.get("applications") or []) if j.get("submitted_at"))
    reached = [m for m in MILESTONES if len(sent) >= m]
    if not reached:
        return None
    m = reached[-1]
    if sent[m - 1] < (today - timedelta(days=CELEBRATE_DAYS)).isoformat():
        return None
    key = f"celebrate:milestone:{m}"
    if key in db.nudge_states():
        return None
    if m == 1:
        return {"key": key, "kind": "milestone", "title": "Your first application is out",
                "line": "Starting is often the hardest part, and you've started."}
    return {"key": key, "kind": "milestone", "title": f"{m} applications sent",
            "line": f"Each one took reading, tailoring and deciding. That's {m} doors you knocked on."}


def rejection_note(db, today: date) -> dict | None:
    """The newest rejection from the last few days that the person hasn't put away yet."""
    since = datetime.combine(today - timedelta(days=REJECTION_NOTE_DAYS), datetime.min.time())
    seen = db.nudge_states()
    for e in _recent(db, ("rejected",), since):
        key = f"pal:rejection:{e['id']}"
        if key not in seen:
            return {"key": key, "company": company(db, e), "event": e}
    return None


def market_line(today: date) -> dict | None:
    """The current honest market sentence from market.yaml, with its source and date; None when missing or stale."""
    import yaml
    try:
        data = yaml.safe_load(MARKET_FILE.read_text()) or {}
        lines = data.get("lines") or []
    except (OSError, yaml.YAMLError, AttributeError):
        return None
    for ln in lines if isinstance(lines, list) else []:
        try:
            checked = ln["checked"] if isinstance(ln["checked"], date) else date.fromisoformat(str(ln["checked"]))
        except (KeyError, TypeError, ValueError):
            continue
        if ln.get("text") and ln.get("source") and 0 <= (today - checked).days <= MARKET_MAX_AGE_DAYS:
            return {"text": str(ln["text"]), "source": str(ln["source"]), "url": str(ln.get("url") or ""),
                    "checked": checked.isoformat()}
    return None


def push_line(db, s: dict, now: datetime) -> str:
    """One short, kind line for the phone push."""
    g = greeting(db, s, now)
    # A rejection is never pushed on its own: bad news waits for the brief, batched (VOICE.md, rule 10).
    ev_line = {"offer": "An offer came in. Open it when you're ready.",
               "interview": "Someone wants to talk. Your dashboard has the details.",
               "reply": "Someone wrote back. Worth a look this morning."}
    if g["state"] in ev_line:
        return ev_line[g["state"]]
    n = len(s.get("ready") or [])
    return f"{'One role is' if n == 1 else f'{n} roles are'} ready for you. No rush." if n else "Nothing new to send today. Rest counts too."
