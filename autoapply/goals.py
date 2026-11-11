"""Weekly goals: a few totals the person sets on Sunday (applications, and hours for reaching out, interview prep
and learning), spread across the days they pick, counted up each day, and a look-back that flows into next week.

Why: writing a plan helped people find work in a field trial, and reminders added nothing (Abel et al.); specific
"when" plans turn intentions into search (van Hooft et al. 2005); a structured day goes with better wellbeing out
of work (Jahoda; Feather and Bond 1983). Mood and progress swing day to day (Wanberg, Zhu and van Hooft 2010), so the
week is the goal and a short day is credit, never a failure: counts go up, there are no streaks, nothing nags
(VOICE.md rules 2, 6 and 7). The plan never changes the daily run or the work-search count.

Stored in pal_notes (coach.note): the plan at plan:<week> (roles, days, contact as before, plus goals and per_day),
time marked done at done:<day>, and the look-back note at lookback:<week>. Old plans without goals read as before.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, timedelta
from typing import Mapping

from . import coach
from .stats import week_start

GOALS = ("apps", "reach", "prep", "learn")
TIMED = ("reach", "prep", "learn")
LABELS = {"apps": "Applications", "reach": "Reaching out", "prep": "Interview prep", "learn": "Learning"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
MAX_APPS = 200          # a week
MAX_MINUTES = 2400      # 40 h a week, per goal
MAX_DONE = 960          # 16 h in one day, per goal
STEP = 30               # time goals move in half hours


def _zero() -> dict:
    return {g: 0 for g in GOALS}


def day_name(d: date) -> str:
    return coach.DAYS[(d.weekday() + 1) % 7]


def day_date(week: date, name: str) -> date:
    return week + timedelta(days=coach.DAYS.index(name))


def _int(v, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return lo


def _hours(v) -> int:
    """'1.5', '1:30' or '2' hours -> minutes, rounded to half hours; anything else is 0."""
    s = str(v or "").strip()
    try:
        if ":" in s:
            h, m = s.split(":", 1)
            mins = int(h or 0) * 60 + int(m or 0)
        else:
            mins = float(s) * 60
    except (ValueError, OverflowError):
        return 0
    if not math.isfinite(mins):
        return 0
    return max(0, min(MAX_MINUTES, int(round(mins / STEP)) * STEP))


def parse_totals(form: Mapping) -> dict:
    out = _zero()
    out["apps"] = _int(form.get("apps"), 0, MAX_APPS)
    for g in TIMED:
        out[g] = _hours(form.get(f"{g}_h"))
    return out


def _clean(totals: Mapping) -> dict:
    out = _zero()
    for g in GOALS:
        out[g] = _int(totals.get(g), 0, MAX_APPS if g == "apps" else MAX_MINUTES)
    return out


def _split(n: int, k: int) -> list[int]:
    base, extra = divmod(n, k)
    return [base + (1 if i < extra else 0) for i in range(k)]


def spread(totals: Mapping, days: list[str], week: date, start: date) -> dict:
    """The totals over the chosen days on or after start (Mon-Fri when none are chosen). Remainders go to the
    earliest days; time goals divide in half hours."""
    chosen = [d for d in coach.DAYS if d in (days or WEEKDAYS) and day_date(week, d) >= start]
    if not chosen:
        return {}
    out = {d: _zero() for d in chosen}
    for g in GOALS:
        n = int(totals.get(g) or 0)
        parts = _split(n, len(chosen)) if g == "apps" else [u * STEP for u in _split(n // STEP, len(chosen))]
        for d, v in zip(chosen, parts):
            out[d][g] = v
    return out


def _sums(per_day: Mapping) -> dict:
    out = _zero()
    for v in per_day.values():
        for g in GOALS:
            out[g] += int(v.get(g) or 0)
    return out


def week_goals(plan: Mapping | None) -> dict | None:
    if not plan or "goals" not in plan:
        return None
    return _sums(plan.get("per_day") or {})


def save_week(db, week: date, totals: Mapping, days: list[str], roles: str, contact: str, today: date) -> dict:
    """Save the week's totals. Days before today keep what they had; the rest is spread over today and the later
    chosen days (or today alone when none is left). The week's goals are always the sum of its days."""
    totals = _clean(totals)
    old = coach.plan(db, week) or {}
    start = max(today, week)
    past = {d: dict(v) for d, v in (old.get("per_day") or {}).items() if day_date(week, d) < start}
    left = {g: max(0, totals[g] - _sums(past)[g]) for g in GOALS}
    days = [d for d in coach.DAYS if d in days]
    later = spread(left, days, week, start)
    if not later:
        later = spread(left, [day_name(min(start, week + timedelta(days=6)))], week, week)
    per_day = {**past, **later}
    p = {"roles": coach._clip(roles, 200), "days": days, "contact": coach._clip(contact, 120),
         "goals": _sums(per_day), "per_day": per_day}
    coach.set_note(db, f"plan:{week.isoformat()}", p)
    coach.touch(db)
    return p


def set_day(db, week: date, day: str, goal: str, value) -> dict | None:
    """Change one day's planned amount; the week's total follows."""
    p = coach.plan(db, week)
    if not p or "goals" not in p or goal not in GOALS or day not in coach.DAYS:
        return None
    hi = MAX_APPS if goal == "apps" else MAX_MINUTES
    v = _int(value, 0, hi)
    if goal != "apps":
        v = (v // STEP) * STEP
    p["per_day"].setdefault(day, _zero())[goal] = v
    p["goals"] = _sums(p["per_day"])
    coach.set_note(db, f"plan:{week.isoformat()}", p)
    coach.touch(db)
    return p


# ---- what was done -------------------------------------------------------------------------------

def _done(db, day: date) -> dict:
    return coach.note(db, f"done:{day.isoformat()}") or {}


def _planned(db, day: date) -> dict:
    p = coach.plan(db, week_start(day)) or {}
    return {**_zero(), **((p.get("per_day") or {}).get(day_name(day)) or {})}


def mark_done(db, day: date, goal: str, minutes=None) -> int:
    """Time spent on reaching out, prep or learning. None credits the time planned for that day."""
    if goal not in TIMED:
        raise ValueError(goal)
    v = _planned(db, day)[goal] or STEP if minutes is None else _int(minutes, 0, MAX_DONE)
    v = min(v, MAX_DONE)
    d = _done(db, day)
    d[goal] = v
    coach.set_note(db, f"done:{day.isoformat()}", d)
    coach.touch(db)
    return v


def _week_actuals(db, week: date) -> dict:
    """{iso day: {apps, reach, prep, learn, people}} for the seven days of a week, in one pass."""
    days = [week + timedelta(days=i) for i in range(7)]
    isos = {d.isoformat() for d in days}
    apps = Counter(str(j["submitted_at"])[:10] for j in db.all()
                   if j["status"] == "submitted" and j["submitted_at"] and str(j["submitted_at"])[:10] in isos)
    people = Counter(str(c.get("at") or "")[:10] for c in coach.contacts(db))
    out = {}
    for d in days:
        k = d.isoformat()
        done = _done(db, d)
        out[k] = {"apps": apps.get(k, 0), "people": people.get(k, 0), **{g: int(done.get(g) or 0) for g in TIMED}}
    return out


def actuals(db, day: date) -> dict:
    return _week_actuals(db, week_start(day))[day.isoformat()]


def move_to_tomorrow(db, day: date, goal: str) -> bool:
    """Put what's left of today's goal on the next chosen day this week. The week's total stays the same."""
    week = week_start(day)
    p = coach.plan(db, week)
    nxt = _next_day(p, day)
    if not nxt or goal not in GOALS:
        return False
    name = day_name(day)
    planned = int(((p["per_day"].get(name) or {}).get(goal)) or 0)
    left = planned - actuals(db, day)[goal]
    if left <= 0:
        return False
    p["per_day"][name][goal] = planned - left
    p["per_day"].setdefault(nxt, _zero())[goal] = int(p["per_day"][nxt].get(goal) or 0) + left
    p["goals"] = _sums(p["per_day"])
    coach.set_note(db, f"plan:{week.isoformat()}", p)
    coach.touch(db)
    return True


def _next_day(p: Mapping | None, day: date) -> str | None:
    if not p or "goals" not in p:
        return None
    week = week_start(day)
    chosen = p.get("days") or WEEKDAYS
    return next((d for d in coach.DAYS if d in chosen and day_date(week, d) > day), None)


# ---- views ---------------------------------------------------------------------------------------

def _frac(done: int, planned: int) -> float:
    return min(1.0, done / planned) if planned else 0.0


def _strip(p: Mapping | None, acts: Mapping, week: date, today: date) -> list[dict]:
    per_day = (p or {}).get("per_day") or {}
    out = []
    for name in coach.DAYS:
        d = day_date(week, name)
        plan = {g: int(v) for g, v in (per_day.get(name) or {}).items() if g in GOALS and int(v or 0) > 0}
        a = acts[d.isoformat()]
        fr = [(_frac(a[g], n)) for g, n in plan.items()]
        out.append({"day": name, "date": d, "planned": bool(plan), "frac": sum(fr) / len(fr) if fr else 0.0,
                    "rest": not plan, "today": d == today, "past": d < today,
                    "active": any(a[g] for g in GOALS) or bool(a["people"])})
    return out


def today_view(db, today: date) -> dict | None:
    week = week_start(today)
    p = coach.plan(db, week)
    if not p or "goals" not in p:
        return None
    acts = _week_actuals(db, week)
    a = acts[today.isoformat()]
    mine = (p.get("per_day") or {}).get(day_name(today)) or {}
    nxt = _next_day(p, today)
    blocks = []
    for g in GOALS:
        n = int(mine.get(g) or 0)
        if n <= 0:
            continue
        met = a[g] >= n
        blocks.append({"goal": g, "label": LABELS[g], "planned": n, "done": a[g], "frac": _frac(a[g], n), "met": met,
                       "can_move": bool(nxt) and not met, "people": a["people"] if g == "reach" else 0})
    so_far = {k: sum(v[k] for d, v in acts.items() if d <= today.isoformat()) for k in (*GOALS, "people")}
    return {"date": today, "day": day_name(today), "rest": not blocks, "blocks": blocks, "week_so_far": so_far,
            "goals": p["goals"], "strip": _strip(p, acts, week, today), "next_day": nxt,
            "met": bool(blocks) and all(b["met"] for b in blocks)}


def week_view(db, week: date, today: date | None = None) -> dict:
    p = coach.plan(db, week)
    g_ = week_goals(p)
    acts = _week_actuals(db, week)
    did = {k: sum(v[k] for v in acts.values()) for k in (*GOALS, "people")}
    rows = [{"goal": g, "label": LABELS[g], "did": did[g], "planned": (g_ or {}).get(g, 0),
             "frac": _frac(did[g], (g_ or {}).get(g, 0))} for g in GOALS]
    set_ = [r for r in rows if r["planned"] > 0]
    return {"week": week, "rows": rows, "did": did, "people": did["people"], "planned": g_ is not None,
            "met": bool(set_) and all(r["did"] >= r["planned"] for r in set_),
            "strip": _strip(p, acts, week, today or week + timedelta(days=7)),
            "note": str(coach.note(db, f"lookback:{week.isoformat()}") or "")}


def lookback(db, today: date) -> dict | None:
    """Last week, until this week has any plan or is skipped. None when last week had no plan and nothing done."""
    week = week_start(today)
    if coach.plan(db, week) or f"pal:plan-skip:{week.isoformat()}" in db.nudge_states():
        return None
    v = week_view(db, week - timedelta(days=7))
    if not v["planned"] and not any(v["did"].values()):
        return None
    return v


def save_note(db, week: date, text: str) -> None:
    t = re.sub(r"\s+", " ", str(text or "")).strip()[:300]
    coach.set_note(db, f"lookback:{week.isoformat()}", t or None)


def prefill(db, week: date) -> dict | None:
    for n in reversed(coach.notes(db, "plan:")):
        if n["key"] < f"plan:{week.isoformat()}" and isinstance(n["value"], dict) and "goals" in n["value"]:
            return week_goals(n["value"])
    return None


def new_met(db, today: date) -> list[dict]:
    """Met moments not shown yet: each block, the whole day, the whole week. The caller marks each key done."""
    v = today_view(db, today)
    if not v:
        return []
    seen = db.nudge_states()
    iso = today.isoformat()
    out = [{"key": f"goals:met:{iso}:{b['goal']}", "scope": "block", "goal": b["goal"]} for b in v["blocks"] if b["met"]]
    if v["met"]:
        out.append({"key": f"goals:met:{iso}", "scope": "day"})
    week = week_start(today)
    if week_view(db, week, today)["met"]:
        out.append({"key": f"goals:met:week:{week.isoformat()}", "scope": "week"})
    return [m for m in out if m["key"] not in seen]


def history(db, today: date, weeks: int = 12) -> list[dict]:
    this = week_start(today)
    out = []
    for i in range(1, weeks + 1):
        v = week_view(db, this - timedelta(days=7 * i))
        if v["planned"]:
            out.append(v)
    return out


# ---- words ---------------------------------------------------------------------------------------

def fmt_minutes(m: int) -> str:
    """90 -> '1.5 h', 180 -> '3 h', 30 -> '30 m'."""
    m = int(m or 0)
    if m < 60:
        return f"{m} m"
    h = m / 60
    return f"{h:g} h" if h == int(h) or (m % 30 == 0) else f"{h:.1f} h"


def amount(goal: str, n: int) -> str:
    if goal == "apps":
        return f"{n} application{'' if n == 1 else 's'}"
    return fmt_minutes(n)


def summary(did: Mapping) -> str:
    """'14 applications, 3 h reaching out (4 people), 1.5 h learning': counted up, zeros left out."""
    bits = []
    if did.get("apps"):
        bits.append(amount("apps", did["apps"]))
    people = int(did.get("people") or 0)
    ppl = f"{people} {'person' if people == 1 else 'people'}"
    if did.get("reach"):
        bits.append(f"{fmt_minutes(did['reach'])} reaching out" + (f" ({ppl})" if people else ""))
    elif people:
        bits.append(f"{ppl} reached")
    if did.get("prep"):
        bits.append(f"{fmt_minutes(did['prep'])} interview prep")
    if did.get("learn"):
        bits.append(f"{fmt_minutes(did['learn'])} learning")
    return ", ".join(bits)


def today_line(v: Mapping | None) -> str:
    """'5 applications · Learning 30 m' for the morning email."""
    if not v or v["rest"]:
        return ""
    return " · ".join(amount("apps", b["planned"]) if b["goal"] == "apps" else f"{b['label']} {fmt_minutes(b['planned'])}"
                      for b in v["blocks"])
