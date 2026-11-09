"""What helps a search, beyond the tone: the person's own weekly plan, people they know, related titles for a
narrow search, preparing for setbacks, a short values reflection, and a gentle return after time away.

Each piece comes from the job-search evidence (graded in palStack's research notes; the main sources are named
in VOICE.md). The person stays in charge: everything here is optional, can be put away, and sends no reminders.
Nothing is measured beyond counts from this install's own database (no visits, no opens).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

SCHEMA = """
create table if not exists pal_notes (   -- things the person wrote for themselves: plans, if-then, reflections
  key text primary key, value text, at text default (datetime('now', 'localtime'))
);
create table if not exists contacts (    -- people you got in touch with about work (count as networking)
  id integer primary key autoincrement, at text, name text, company text, how text, note text,
  created text default (datetime('now', 'localtime'))
);
"""

DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]   # work-search weeks run Sunday to Saturday
HOW = ["Email", "Message (LinkedIn or similar)", "Call", "Coffee or video chat", "Event or meetup", "Other"]
AWAY_DAYS = 7               # this long with nothing done reads as "away"; the return is gentle, never a catch-up list
SETBACK_EARLY_DAYS = 21     # the setback card shows in the first weeks of a search...
SETBACK_LATER = (49, 70)    # ...and again around week 8, when searches often start to feel long
NARROW_TITLES = 3           # a search on this many titles or fewer counts as narrow
NARROW_AFTER_WEEKS = 8      # related titles are offered on the dashboard once a narrow search has run this long

# Values for the reflection: the person picks what matters to them. Self-affirmation as in the field trials:
# pick your own values, write why one matters and a time you acted on it.
VALUES = ["Family", "Friendship", "Learning", "Craft and doing good work", "Helping others", "Honesty", "Independence",
          "Creativity", "Fairness", "Faith or spirituality", "Health", "Humor", "Community", "Curiosity", "Courage",
          "Patience"]

SENIORITY = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "head", "chief", "i", "ii", "iii", "iv", "associate",
             "intern", "of", "and", "the", "a", "an", "for", "to", "in", "at", "with", "remote", "hybrid", "contract", "temp"}


def ensure(db):
    db.conn.executescript(SCHEMA)


# ---- notes the person writes ---------------------------------------------------------------------

def note(db, key: str):
    ensure(db)
    row = db.conn.execute("select value from pal_notes where key = ?", (key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def set_note(db, key: str, value) -> None:
    ensure(db)
    if value is None:
        db.conn.execute("delete from pal_notes where key = ?", (key,))
    else:
        db.conn.execute("insert or replace into pal_notes (key, value, at) values (?, ?, datetime('now', 'localtime'))",
                        (key, json.dumps(value)))
    db.conn.commit()


def notes(db, prefix: str) -> list[dict]:
    ensure(db)
    out = []
    for r in db.conn.execute("select key, value, at from pal_notes where key like ? order by key", (prefix + "%",)):
        try:
            out.append({"key": r[0], "value": json.loads(r[1]), "at": r[2]})
        except (TypeError, ValueError):
            pass
    return out


def touch(db) -> None:
    """The person did something (sent, declined, logged, wrote a plan). Used only to notice a long gap."""
    set_note(db, "last_action", datetime.now().strftime("%Y-%m-%d %H:%M"))


def _clip(s, n: int) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


# ---- 1. the weekly plan the person writes --------------------------------------------------------

def plan(db, week: date) -> dict | None:
    return note(db, f"plan:{week.isoformat()}")


def save_plan(db, week: date, roles: str, days: list[str], contact: str) -> dict | None:
    """A plan with nothing in it is removed; otherwise kept as written (trimmed). No reminders follow."""
    p = {"roles": _clip(roles, 200), "days": [d for d in DAYS if d in days], "contact": _clip(contact, 120)}
    if not (p["roles"] or p["days"] or p["contact"]):
        set_note(db, f"plan:{week.isoformat()}", None)
        return None
    set_note(db, f"plan:{week.isoformat()}", p)
    touch(db)
    return p


def plan_line(p: dict | None) -> str:
    """'Analytics roles · Mon, Wed, Thu · get in touch with Sam' for the dashboard and the brief."""
    if not p:
        return ""
    bits = [p["roles"]] if p.get("roles") else []
    if p.get("days"):
        bits.append(", ".join(p["days"]))
    if p.get("contact"):
        bits.append(f"get in touch with {p['contact']}")
    return " · ".join(bits)


def weeks_planned(db) -> int:
    return len(notes(db, "plan:"))


# ---- 2. people you know --------------------------------------------------------------------------

def add_contact(db, name: str, company: str = "", how: str = "", note_text: str = "", at: str = "") -> int | None:
    name = _clip(name, 80)
    if not name:
        return None
    try:
        day = date.fromisoformat(at[:10]).isoformat() if at else date.today().isoformat()
    except ValueError:
        day = date.today().isoformat()
    ensure(db)
    cur = db.conn.execute("insert into contacts (at, name, company, how, note) values (?, ?, ?, ?, ?)",
                          (day, name, _clip(company, 80), how if how in HOW else "Other", _clip(note_text, 200)))
    db.conn.commit()
    touch(db)
    return cur.lastrowid


def contacts(db) -> list[dict]:
    ensure(db)
    return [dict(r) for r in db.conn.execute("select * from contacts order by at desc, id desc")]


def delete_contact(db, cid: int) -> None:
    ensure(db)
    db.conn.execute("delete from contacts where id = ?", (cid,))
    db.conn.commit()


def contacts_count(db) -> bool:
    """Whether contacts count toward the weekly work-search number. Off until the person turns it on: not every
    state accepts networking, and the official count is never padded (VOICE.md, rule 11). The state's rule is
    shown next to the switch."""
    return bool(note(db, "ws:count_contacts"))


def interviews_from_contacts(db) -> int:
    """Interviews and offers at a company where you'd talked to someone (company names compared loosely)."""
    cos = {_norm(c["company"]) for c in contacts(db) if c.get("company")}
    if not cos:
        return 0
    return sum(1 for j in db.by_status("submitted") if j.get("outcome") in ("interview", "offer") and _norm(j["company"]) in cos)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# ---- 3. related titles for a narrow, long search -------------------------------------------------

def _words(t: str) -> set[str]:
    return {w for w in _norm(t).split() if w not in SENIORITY and len(w) > 1}


def _clean_title(t: str) -> str:
    t = re.split(r"\s[-–|(,/]\s?|\s\(", t or "")[0]  # "Data Analyst - Remote (Contract)" -> "Data Analyst"
    words = [w for w in _norm(t).split() if w not in SENIORITY or w in ("of", "and")]
    while words and words[0] in ("of", "and"):
        words.pop(0)
    return " ".join(words).strip()


def related_titles(db, settings, limit: int = 5) -> list[dict]:
    """Titles from roles already found (job boards and alert emails) that share a word with your search but aren't
    in it, most often seen first. Seen at least twice, so one odd posting isn't a suggestion."""
    search = settings.raw.get("search") or {}
    mine = [str(t).lower() for t in search.get("title_keywords") or []]
    avoid = [str(t).lower() for t in search.get("exclude_keywords") or []]
    if not mine:
        return []
    my_words = set().union(*(_words(t) for t in mine))
    seen: dict[str, dict] = {}
    titles = [r[0] for r in db.conn.execute("select title from jobs where id not like 'tracker:%' and id not like 'manual:%'")]
    try:
        titles += [r[0] for r in db.conn.execute("select title from leads")]
    except Exception:  # noqa: BLE001  the leads table only exists once alerts have been read
        pass
    for raw in titles:
        t = _clean_title(raw)
        if not t or len(t) > 50 or any(k in t for k in mine) or any(a and a in t for a in avoid):
            continue
        shared = _words(t) & my_words
        if not shared or len(_words(t)) < 2:
            continue
        row = seen.setdefault(t, {"title": t, "count": 0})
        row["count"] += 1
    out = sorted((r for r in seen.values() if r["count"] >= 2), key=lambda r: (-r["count"], r["title"]))
    return out[:limit]


def narrow_and_long(settings, s: dict, today: date) -> bool:
    titles = (settings.raw.get("search") or {}).get("title_keywords") or []
    first = _first_sent(s)
    return bool(titles) and len(titles) <= NARROW_TITLES and bool(first) and (today - first).days >= NARROW_AFTER_WEEKS * 7


def _first_sent(s: dict) -> date | None:
    days = [a["submitted_at"][:10] for a in s.get("applications") or [] if a.get("submitted_at")]
    return date.fromisoformat(min(days)) if days else None


# ---- 4. preparing for setbacks -------------------------------------------------------------------

def setback_phase(s: dict, today: date) -> str | None:
    first = _first_sent(s)
    if not first:
        return None
    days = (today - first).days
    if 0 <= days <= SETBACK_EARLY_DAYS:
        return "early"
    if SETBACK_LATER[0] <= days <= SETBACK_LATER[1]:
        return "later"
    return None


def if_then(db) -> str:
    return str(note(db, "setback:ifthen") or "")


# ---- 5. the values reflection --------------------------------------------------------------------

def reflections(db) -> list[dict]:
    return list(reversed(notes(db, "values:")))


def save_reflection(db, values: list[str], text: str) -> bool:
    picked = [v for v in VALUES if v in values][:3]
    text = str(text or "").strip()[:4000]
    if not picked and not text:
        return False
    set_note(db, f"values:{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}", {"values": picked, "text": text})
    touch(db)
    return True


# ---- 6. a gentle return --------------------------------------------------------------------------

def away_days(db, s: dict, today: date) -> int:
    """Days since the person last did anything here; 0 when there's nothing to go on (a new install)."""
    last = [a["submitted_at"][:10] for a in s.get("applications") or [] if a.get("submitted_at")]
    if (la := note(db, "last_action")):
        last.append(str(la)[:10])
    if not last:
        return 0
    try:
        return max(0, (today - date.fromisoformat(max(last))).days)
    except ValueError:
        return 0


# ---- the dashboard: one offer at a time ----------------------------------------------------------

def offer(db, settings, s: dict, today: date, has_interview: bool) -> dict | None:
    """The one optional card to show under the welcome, or None. Setback preparation first (it matters most
    when it's on time), then the reflection before a first interview, then related titles, then the early
    reflection. Each is put away for good with /pal/seen."""
    seen = db.nudge_states()
    phase = setback_phase(s, today)
    if phase and f"pal:setback:{phase}" not in seen:
        return {"kind": "setback", "key": f"pal:setback:{phase}", "phase": phase, "if_then": if_then(db)}
    if has_interview and not reflections(db) and "pal:values:interview" not in seen:
        return {"kind": "values", "key": "pal:values:interview", "why": "interview"}
    if narrow_and_long(settings, s, today):
        titles = related_titles(db, settings, 4)
        key = f"pal:titles:{today.strftime('%Y-%m')}"  # put away for this month; a new month may bring new titles
        if titles and key not in seen:
            return {"kind": "titles", "key": key, "titles": titles}
    first = _first_sent(s)
    if first and (today - first).days <= 28 and not reflections(db) and "pal:values:early" not in seen:
        return {"kind": "values", "key": "pal:values:early", "why": "early"}
    return None
