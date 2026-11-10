"""Unemployment benefits: the claim's details, how many weeks are left, appointments (like RESEA) and letters
from the agency, as to-dos next to the job-search ones.

Everything here is a reminder. Nothing is filed with the agency, and the numbers are estimates from what you
typed in Settings: your agency's own letters and site are the authority.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

TASKS_SCHEMA = """
create table if not exists ui_tasks (   -- unemployment appointments and deadlines you add (RESEA, seminars...)
  id integer primary key autoincrement, title text, due text, done integer default 0, kind text default 'task',
  note text, created text default (datetime('now', 'localtime')), done_at text
);
"""

# Steps most states' RESEA (Reemployment Services and Eligibility Assessment) follows. The letter you get
# names the real deadlines: these only give you rows to put them in.
RESEA_STEPS = ["RESEA orientation or seminar", "First RESEA meeting with a career center", "Follow-up RESEA meeting"]
RESEA_STEPS_BY_STATE = {
    "MA": ["Career Center Seminar (sign up in JobQuest)", "Initial RESEA review at your MassHire Career Center",
           "Second RESEA review (scheduled at the first one)"],
}

# Free activities most states count toward the weekly work search. A state's own list (counts) replaces it.
SUGGESTIONS = ["Apply to a job you qualify for", "Go to a workshop at your local American Job Center (career center)",
               "Attend a job fair (many are online)", "Update your profile on your state's job bank",
               "Contact an employer or recruiter about openings", "Go to a networking event or professional meetup"]

# Help people often don't know about. National links only: state ones come from the state's entry.
RESOURCES = [
    ("Health coverage", "Losing job-based coverage opens a 60-day window for a Marketplace plan, often cheaper than COBRA.",
     "https://www.healthcare.gov/coverage-outside-open-enrollment/special-enrollment-period/"),
    ("Food help (SNAP)", "Unemployment benefits count as income, but many people on them still qualify.",
     "https://www.fns.usda.gov/snap/state-directory"),
    ("211", "Free local help with rent, utilities, food and more. Call or text 211.", "https://www.211.org/"),
    ("Your local career center", "American Job Centers offer free workshops, resume help and training money.",
     "https://www.careeronestop.org/LocalHelp/AmericanJobCenters/find-american-job-centers.aspx"),
    ("Free legal help", "If a claim is denied or stopped, free legal aid can help with the appeal.", "https://www.lawhelp.org/"),
]

# Letters from the agency. Gmail search (read-only) plus a check on each message.
# Career centers often write under their own brand, not a .gov address: MassHire (MA), WorkSource (WA, GA),
# CareerSource (FL), OhioMeansJobs, American Job Centers... These names count as official senders too.
CAREER_CENTERS = re.compile(r"masshire|jobquest|worksource|careersource|ohiomeansjobs|american job cent|job ?cent(er|re)"
                            r"|career ?cent(er|re)|workforce (solutions|development|board)|employment security|labor (and|&) industry"
                            r"|department of labor|\bdol\b|\bedd\b|\bdes\b|\bdew\b|\bides\b|\btwc\b|\bdua\b", re.I)
AGENCY_QUERIES = ['(from:gov OR from:state OR from:masshire OR from:jobquest OR from:worksource OR from:careersource '
                  'OR from:ohiomeansjobs OR from:workforce OR from:"job center" OR from:"career center" OR from:"employment security") '
                  '(unemployment OR RESEA OR reemployment OR "work search" OR claimant OR "benefit year" OR correspondence '
                  'OR determination OR appeal OR hearing OR appointment OR orientation OR "career center") -subject:"Job search brief"']
AGENCY_SEARCH_WORDS = ["unemployment", "RESEA", "reemployment", "work search", "benefit year", "career center"]  # non-Gmail inboxes
AGENCY_WORDS = re.compile(r"unemployment|\bresea\b|reemployment|work search|claimant|benefit year|correspondence"
                          r"|determination|appeal|hearing|weekly (benefit )?(claim|certification)|masshire|jobquest|your claim"
                          r"|disqualif|eligibility|career cent(er|re)|orientation|workshop", re.I)
RESEA = re.compile(r"\bresea\b|reemployment services and eligibility|re-?employment services", re.I)
_DAY = r"(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"
_DATE = r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)"
# "Your RESEA appointment is scheduled for Tuesday, November 18, 2026 at 10:00 AM"
APPOINTMENT = re.compile(r"(?:appointment|meeting|orientation|session|seminar|workshop|interview)\b[^.\n]{0,80}?"
                         r"(?:\bon|\bfor|scheduled for|is set for|date:?)\s+" + _DAY + _DATE
                         + r"(?:[^.\n]{0,20}?\b(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)))?", re.I)
DENIAL = re.compile(r"\b(denied|disqualif\w*|ineligible|not eligible|overpayment|benefits? (have been |were |are )?(stopped|suspended))\b", re.I)
DUE = re.compile(r"(?:by|before|no later than|due|deadline[: ]+|on or before)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)", re.I)


def _h(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def ensure(db):
    db.conn.executescript(TASKS_SCHEMA)
    if "done_at" not in {r[1] for r in db.conn.execute("pragma table_info(ui_tasks)")}:
        db.conn.execute("alter table ui_tasks add column done_at text")


def claim(settings) -> dict:
    """The claim's details from config.yaml work_search (set on the work-search page)."""
    ws = settings.raw.get("work_search") or {}
    return {"start": ws.get("claim_start") or "", "weekly_benefit": ws.get("weekly_benefit") or "",
            "weeks_allowed": ws.get("weeks_allowed") or "", "certify_day": ws.get("certify_day") or ""}


def _date(s) -> date | None:
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def runway(settings, rule: dict | None, today: date | None = None) -> dict | None:
    """Weeks of benefits left, estimated from the claim start and the weeks allowed. None without both."""
    c = claim(settings)
    start, today = _date(c["start"]), today or date.today()
    try:
        allowed = int(c["weeks_allowed"])
    except (TypeError, ValueError):
        allowed = 0
    if not start or allowed <= 0 or start > today:
        return None
    week_no = (today - start).days // 7 + 1  # week 1 is the week you filed
    waiting = bool((rule or {}).get("waiting_week"))
    paid = max(0, week_no - 1 - (1 if waiting else 0))  # weeks fully behind you that could have been paid
    left = max(0, allowed - paid)
    try:
        weekly = float(str(c["weekly_benefit"]).replace("$", "").replace(",", ""))
    except ValueError:
        weekly = 0.0
    return {"week_no": week_no, "allowed": allowed, "left": left, "ends": today + timedelta(weeks=left),
            "waiting": waiting, "weekly": weekly, "remaining_money": round(weekly * left) if weekly else None,
            "pct": min(100, round(100 * (allowed - left) / allowed))}


def save_claim(settings, form: dict) -> None:
    import yaml
    path = settings.root / "config.yaml"
    cfg = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    ws = cfg.setdefault("work_search", {"label": "Work search", "weekly_minimum": 3})
    d = _date(form.get("claim_start"))
    ws["claim_start"] = d.isoformat() if d else ""
    amt = re.sub(r"[^\d.]", "", str(form.get("weekly_benefit") or ""))[:8]
    ws["weekly_benefit"] = amt
    weeks = str(form.get("weeks_allowed") or "").strip()
    ws["weeks_allowed"] = int(weeks) if weeks.isdigit() and 0 < int(weeks) <= 99 else ""
    day = str(form.get("certify_day") or "")
    ws["certify_day"] = day if day in DAYS else ""
    head = "# Written by the dashboard. Edit here or there.\n"
    path.write_text(head + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    settings.raw.setdefault("work_search", {}).update({k: ws[k] for k in ("claim_start", "weekly_benefit", "weeks_allowed", "certify_day")})


def tasks(db, include_done: bool = False) -> list[dict]:
    ensure(db)
    q = "select * from ui_tasks" + ("" if include_done else " where done = 0") + " order by done, coalesce(due, '9999'), id"
    return [dict(r) for r in db.conn.execute(q)]


def add_task(db, title: str, due: str = "", kind: str = "task", note: str = "") -> int:
    ensure(db)
    d = _date(due)
    cur = db.conn.execute("insert into ui_tasks (title, due, kind, note) values (?, ?, ?, ?)",
                          (title.strip()[:160], d.isoformat() if d else None, kind if kind in ("task", "resea") else "task", note[:400]))
    db.conn.commit()
    return cur.lastrowid


def set_task(db, task_id: int, done: bool | None = None, delete: bool = False):
    ensure(db)
    if delete:
        db.conn.execute("delete from ui_tasks where id = ?", (task_id,))
    elif done is not None:
        # The day it was done (or its date, if that's already past) is the day it counts in the work-search log.
        db.conn.execute("update ui_tasks set done = ?, done_at = case when ? then coalesce(case when due <= date('now', 'localtime') "
                        "then due end, date('now', 'localtime')) end where id = ?", (int(done), int(done), task_id))
    db.conn.commit()


def add_resea(db, state: str = "") -> int:
    """Adds the RESEA steps (no dates yet) unless they're there already."""
    have = {t["title"] for t in tasks(db, include_done=True)}
    steps = [s for s in RESEA_STEPS_BY_STATE.get(state.upper(), RESEA_STEPS) if s not in have]
    for s in steps:
        add_task(db, s, kind="resea")
    return len(steps)


def is_agency(addr: str, subject: str, text: str, state_domain: str = "", name: str = "") -> bool:
    """A letter or notice from an unemployment agency or its career centers: an official sender (a .gov or
    state.xx.us address, your state's agency domain, or a career-center brand in the address or sender name)
    writing about the claim, RESEA, appointments or work search."""
    a = (addr or "").lower()
    dom = a.rsplit("@", 1)[-1]
    official = (dom.endswith(".gov") or ".gov>" in a or ".state." in dom
                or bool(state_domain and dom.endswith(state_domain)) or bool(CAREER_CENTERS.search(f"{name} {dom}")))
    return bool(official and AGENCY_WORDS.search(f"{subject}\n{(text or '')[:3000]}"))


def letters(db) -> list[dict]:
    """Agency emails, newest first, each with resea (bool) and when: an appointment or due date found in it."""
    out = []
    for e in db.events():
        if e["kind"] != "agency":
            continue
        body = f"{e['subject'] or ''}\n{e.get('body') or ''}"
        try:
            at = datetime.strptime(e["at"][:16], "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            at = datetime.now()
        appt = appointment(body, at)
        due = None if appt else due_date(body, at)
        when = (f"appointment {appt[0].strftime('%a %b %-d')}" + (f", {appt[1]}" if appt[1] else "")) if appt else (
            f"due {due.strftime('%a %b %-d')}" if due else "")
        out.append({**e, "resea": bool(RESEA.search(body)), "denial": bool(DENIAL.search(body)), "when": when,
                    "from": (e["sender"] or "").split(" <")[0]})
    return out


def tasks_from_letters(db, days: int = 120) -> int:
    """Every recent agency letter with a RESEA date that has no task yet gets one. Returns how many were added."""
    n = 0
    for e in db.events():
        if e["kind"] != "agency":
            continue
        try:
            at = datetime.strptime(e["at"][:16], "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        if (datetime.now() - at).days > days:
            continue
        n += bool(task_from_letter(db, e["id"], e["subject"] or "", e.get("body") or "", at))
    return n


def appointment(text: str, at: datetime) -> tuple[date, str] | None:
    """The first appointment a letter names ("scheduled for Tuesday, November 18 at 10:00 AM"): (date, "10:00 AM")."""
    m = APPOINTMENT.search(text or "")
    if not m:
        return None
    d = due_date(f"by {re.sub(r'(st|nd|rd|th)(?=,|\s|$)', '', m.group(1))}", at)
    return (d, (m.group(2) or "").upper().replace(".", "")) if d else None


def _due_sentence(text: str) -> str:
    """The letter's own words for what is due: "Complete a Career Center Seminar" from "...Seminar before 11/20/2026."."""
    m = DUE.search(text or "")
    if not m:
        return ""
    start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start()), text.rfind(":", 0, m.start())) + 1
    words = re.sub(r"\s+", " ", text[start:m.start()]).strip(" ,;-")
    return f"RESEA: {words[:70]}" if 3 <= len(words) <= 120 else ""


def task_from_letter(db, event_id: str, subject: str, text: str, at: datetime) -> int | None:
    """A RESEA letter with a date becomes a RESEA task with that date (once per letter). Returns the task id."""
    body = f"{subject}\n{text or ''}"
    if not RESEA.search(body):
        return None
    appt = appointment(body, at)
    due = appt[0] if appt else due_date(body, at)
    if not due:
        return None
    ensure(db)
    tag = f"[letter {_h(event_id)}]"
    if db.conn.execute("select 1 from ui_tasks where note like ?", (f"%{tag}%",)).fetchone():
        return None
    title = ("RESEA appointment" + (f" at {appt[1]}" if appt and appt[1] else "")) if appt else _due_sentence(body) or "RESEA: reply or step due"
    return add_task(db, title, due.isoformat(), kind="resea",
                    note=f"From the letter of {at:%b %-d}: {subject[:120]} {tag}")


def state_domain(rule: dict | None) -> str:
    host = urlparse((rule or {}).get("url") or "").netloc.lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else ""


def due_date(text: str, at: datetime) -> date | None:
    """The first deadline a letter names ("by November 20", "no later than 12/4"), in the letter's year."""
    m = DUE.search(text or "")
    if not m:
        return None
    s = re.sub(r"\.", "", m.group(1)).replace("Sept", "Sep").replace("sept", "sep")
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d", "%B %d", "%m/%d/%Y", "%m/%d/%y", "%m/%d"):
        yearless = "%Y" not in fmt and "%y" not in fmt
        try:
            d = datetime.strptime(f"{s.strip()} {at.year}" if yearless else s.strip(), f"{fmt} %Y" if yearless else fmt).date()
        except ValueError:
            continue
        if yearless:
            if d < at.date() - timedelta(days=30):
                d = d.replace(year=at.year + 1)
        return d
    return None


def todos(db, settings, rule: dict | None, floor: int, this_week: int, last_week: int, now: datetime | None = None) -> list[dict]:
    """Unemployment to-dos in the reminder shape nudges.compute uses (key, kind, title, about, why, days...)."""
    now = now or datetime.now()
    today = now.date()
    out = []

    def item(key, kind, title, about, why, days=0, since=""):
        out.append({"key": key, "kind": kind, "title": title, "about": about, "why": why, "days": days,
                    "since": since or now.strftime("%Y-%m-%d %H:%M"), "to": "", "subject": "", "event": None, "job": None})

    c = claim(settings)
    if c["certify_day"] and DAYS[today.weekday()] == c["certify_day"]:
        item(f"certify-{today.isoformat()}", "claim", "Request this week's benefit payment",
             (rule or {}).get("name") or "Unemployment",
             f"Today is your claim day. Last week (Sun-Sat) has {last_week} of {floor} work search activities logged"
             f"{'' if last_week >= floor else ': add any you did but the tool missed before you certify'}; this week has {this_week} so far.")
    collecting = bool(rule or c["start"] or c["certify_day"])  # only nag people who said they're on a claim
    if collecting and floor and this_week < floor and today.weekday() in (2, 3, 4, 5):  # Wednesday to Saturday
        left = floor - this_week
        ideas = (rule or {}).get("counts") or SUGGESTIONS
        item(f"behind-{today.isoformat()}", "worksearch", f"{left} more work search activit{'y' if left == 1 else 'ies'} this week",
             f"{this_week} of {floor} so far; the week ends Saturday",
             "Ideas that usually count: " + "; ".join(ideas[:4]) + ".")
    for t in tasks(db):
        d = _date(t["due"])
        if d is None or (d - today).days <= 14 or t["kind"] == "resea":  # RESEA steps can stop benefits: always shown
            when = "no date yet: add it from your letter" if d is None else (
                f"due {d.strftime('%a %b %-d')}" + (" (overdue)" if d < today else f", in {(d - today).days} days" if d > today else " (today)"))
            item(f"task-{t['id']}", "resea" if t["kind"] == "resea" else "task", t["title"], when,
                 t["note"] or ("Missing a RESEA step can stop your benefits." if t["kind"] == "resea" else "From your unemployment to-dos."),
                 days=(today - d).days if d else -999)  # soonest date first, undated last
    for e in db.events():
        if e["kind"] != "agency":
            continue
        at = datetime.strptime(e["at"][:16], "%Y-%m-%d %H:%M")
        if (now - at).days > 30:
            break
        body = f"{e['subject']}\n{e.get('body') or ''}"
        due = due_date(body, at)
        if DENIAL.search(body):
            appeal = (rule or {}).get("appeal_days")
            item(f"appeal-{_h(e['id'])}", "appeal", "Read this decision and check the appeal deadline", e["subject"][:90],
                 (f"Appeals in {rule['name']} are due within {appeal} days of the decision's date. " if appeal else
                  "Appeals usually must be filed within 10 to 30 days; the letter gives the exact date. ")
                 + "Keep certifying every week while you appeal. Free legal aid: lawhelp.org.", days=(now - at).days, since=e["at"])
        else:
            item(f"agency-{_h(e['id'])}", "agency", f"Read: {e['subject'][:80]}",
                 f"From {e['sender'].split(' <')[0]}" + (f" · due {due.strftime('%b %-d')}" if due else ""),
                 "A letter from your unemployment agency. Many need an answer or an appointment by a date.",
                 days=(now - at).days, since=e["at"])
    return out
