"""Numbers for the dashboard, computed from the jobs and events tables."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from .db import DB

RESPONDED = ("interview", "rejected", "offer")


def _d(s: str | None) -> date | None:
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


def week_start(d: date) -> date:
    """Work-search weeks run Sunday to Saturday (as in Massachusetts DUA logs)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def compute(db: DB, today: date | None = None, weeks: int = 12, floor: int = 3) -> dict:
    today = today or date.today()
    jobs = db.all()
    applied = [j for j in jobs if j["status"] == "submitted" and _d(j["submitted_at"])]
    found = [j for j in jobs if not j["id"].startswith(("tracker:", "manual:"))]

    this_week = week_start(today)
    per_week = Counter(week_start(_d(j["submitted_at"])) for j in applied)
    series = [(this_week - timedelta(weeks=i), per_week.get(this_week - timedelta(weeks=i), 0))
              for i in range(weeks - 1, -1, -1)]

    responded = [j for j in applied if j["outcome"] in RESPONDED]
    waits = [(_d(j["outcome_at"]) - _d(j["submitted_at"])).days for j in responded
             if _d(j["outcome_at"]) and _d(j["outcome_at"]) >= _d(j["submitted_at"])]
    outcomes = Counter(j["outcome"] or "waiting" for j in applied)

    for j in applied:
        d = _d(j["submitted_at"])
        j["applied_label"] = d.strftime("%b %-d") if d.year == today.year else d.strftime("%b %-d, %Y")
        # Silence past a month is its own answer; don't keep calling it "waiting".
        j["state"] = j["outcome"] or ("no reply" if (today - d).days > 30 else "waiting")

    return {
        "today": today,
        "applied": len(applied),
        # Work-search activities (applications, recruiter contacts, interviews, RESEA), as the work-search log counts them.
        "this_week": next((w["count"] for w in dua_weeks(db, today) if w["start"] == this_week), 0),
        "this_week_start": this_week,
        "dua_floor": floor,
        "series": series,
        "response_rate": round(100 * len(responded) / len(applied)) if applied else 0,
        "responded": len(responded),
        "interviews": outcomes.get("interview", 0) + outcomes.get("offer", 0),
        "rejected": outcomes.get("rejected", 0),
        "waiting": sum(1 for j in applied if j["state"] in ("waiting", "confirmed")),
        "no_reply": sum(1 for j in applied if j["state"] == "no reply"),
        "avg_days_to_reply": round(sum(waits) / len(waits)) if waits else None,
        "funnel": [
            ("Applied", len(applied)),
            ("Heard back", len(responded)),
            ("Interview or offer", outcomes.get("interview", 0) + outcomes.get("offer", 0)),
            ("Offer", outcomes.get("offer", 0)),
        ],
        "pipeline_funnel": [
            ("Roles found", len(found)),
            ("Prepped and filled", sum(1 for j in found if j["status"] in ("prepped", "filled", "submitted"))),
            ("Sent", sum(1 for j in found if j["status"] == "submitted")),
        ],
        "top_companies": Counter(j["company"] for j in found if j["status"] != "skipped").most_common(8),
        "applications": sorted(applied, key=lambda j: j["submitted_at"], reverse=True),
        "ready": db.by_status("filled", "prepped"),  # prepped: apply by hand with the kit
        "new_count": sum(1 for j in jobs if j["status"] == "new"),
        "events": [e for e in db.events() if e["kind"] not in ("recruiter", "applied")][:8],
        "pending": db.pending_events(),
        "recruiters": recruiters(db)[:6],
        "runs": freshness(db.runs()),
        "recruiter_count": len(recruiters(db)),
    }


ACTIVITY = {"applied": "Job application", "confirmed": "Job application", "interview": "Interview",
            "recruiter": "Recruiter contact", "offer": "Offer", "rejected": "Employer reply"}


def dua_weeks(db: DB, today: date | None = None) -> list[dict]:
    """Work-search activities grouped by Sunday-Saturday week, newest first, in a work-search log's columns.
    Applications count once each (their confirmation emails are proof, not extra activities);
    recruiter contacts and interviews count as their own activities."""
    today = today or date.today()
    events = db.events()
    proofs: dict[str, list[str]] = {}
    for e in events:
        if e["job_id"] and e["proof"]:
            proofs.setdefault(e["job_id"], []).append(e["proof"])
    rows = []
    for j in db.by_status("submitted"):
        d = _d(j["submitted_at"])
        if d:
            rows.append({"date": d, "type": "Job application", "company": j["company"], "position": j["title"],
                         "how": j["ats"] or "", "contact": j["url"] or "", "pay": j.get("pay") or "", "result": j["outcome"] or "Applied",
                         "proof": proofs.get(j["id"], []), "counts": True})
    for e in events:
        if e["kind"] in ("recruiter", "interview", "offer"):
            d = _d(e["at"])
            rows.append({"date": d, "type": ACTIVITY[e["kind"]], "company": e["sender"].split(" <")[0],
                         "position": e["subject"], "how": "Email", "contact": e["sender"], "result": e["kind"],
                         "proof": [e["proof"]] if e["proof"] else [], "counts": True})
    from . import benefits  # RESEA meetings, seminars and other appointments you marked done count too
    for t in benefits.tasks(db, include_done=True):
        d = _d(t.get("done_at")) if t["done"] else None
        if d and t["kind"] == "resea":
            rows.append({"date": d, "type": "Reemployment appointment (RESEA)", "company": "Career center", "position": t["title"],
                         "how": "In person or online", "contact": "", "pay": "", "result": "Attended", "proof": [], "counts": True})
    from . import coach  # people you got in touch with about work: networking, if your state counts it
    counts = coach.contacts_count(db)
    for c in coach.contacts(db):
        d = _d(c["at"])
        if d:
            rows.append({"date": d, "type": "Networking contact", "company": c["company"] or "", "position": c["note"] or "",
                         "how": c["how"] or "", "contact": c["name"], "pay": "", "result": "Contacted", "proof": [],
                         "counts": counts})
    weeks: dict[date, list[dict]] = {}
    for r in rows:
        weeks.setdefault(week_start(r["date"]), []).append(r)
    return [{"start": wk, "end": wk + timedelta(days=6), "rows": sorted(rs, key=lambda r: r["date"]),
             "count": sum(r["counts"] for r in rs), "current": wk == week_start(today)}
            for wk, rs in sorted(weeks.items(), reverse=True)]


def recruiters(db: DB) -> list[dict]:
    """One row per recruiter sender: last contact first."""
    out: dict[str, dict] = {}
    for e in db.events():  # newest first
        if e["kind"] == "recruiter":
            r = out.setdefault(e["sender"], {"sender": e["sender"], "last_at": e["at"], "subject": e["subject"], "count": 0})
            r["count"] += 1
    return list(out.values())


RUN_LABELS = [("daily", "Daily run", 26), ("find", "Job search", 26), ("sync-email", "Email sync", 26), ("fill", "Last form fill", None), ("classify", "Email sorting", None), ("brief", "Morning brief", None)]


def freshness(runs: dict, now: datetime | None = None) -> list[dict]:
    """One entry per run kind: when it last ran, whether it worked, and whether it's overdue."""
    now = now or datetime.now()
    out = []
    for kind, label, stale_h in RUN_LABELS:
        r = runs.get(kind)
        if not r:
            out.append({"kind": kind, "label": label, "state": "never", "when": "never", "summary": ""})
            continue
        at = datetime.strptime(r["at"][:16], "%Y-%m-%d %H:%M")
        hours = (now - at).total_seconds() / 3600
        when = at.strftime("%-I:%M %p today") if at.date() == now.date() else at.strftime("%b %-d, %-I:%M %p")
        state = "fail" if not r["ok"] else ("stale" if stale_h and hours > stale_h else "ok")
        out.append({"kind": kind, "label": label, "state": state, "when": when, "summary": r["summary"] or ""})
    return out


PLATFORMS = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday", "workable": "Workable",
             "smartrecruiters": "SmartRecruiters", "rippling": "Rippling", "kula": "Kula", "clearcompany": "ClearCompany"}
REPLY_BUCKETS = [("Same week", 0, 7), ("1-2 weeks", 8, 14), ("2-4 weeks", 15, 30), ("Over a month", 31, 10**6)]


def detail(db: DB, today: date | None = None, floor: int = 3, weeks: int = 26) -> dict:
    """Everything the Stats page shows: trends, conversion, platforms, reply times, pipeline health."""
    today = today or date.today()
    base = compute(db, today, weeks, floor)
    jobs = db.all()
    applied = base["applications"]
    this_week = week_start(today)
    span = [this_week - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]

    found_wk = Counter(week_start(_d(j["found_at"])) for j in jobs
                       if _d(j["found_at"]) and not j["id"].startswith(("tracker:", "manual:")))
    applied_wk = dict(base["series"])
    events = db.events()
    rec_wk = Counter(week_start(_d(e["at"])) for e in events if e["kind"] == "recruiter" and _d(e["at"]))
    pipeline = [(wk, found_wk.get(wk, 0), applied_wk.get(wk, 0)) for wk in span]

    by_platform: dict[str, dict] = {}
    for j in applied:
        raw = (j["ats"] or "").lower()
        name = PLATFORMS.get(raw) or ("Not recorded" if raw in ("", "unknown") else raw.capitalize())
        p = by_platform.setdefault(name, {"name": name, "applied": 0, "responded": 0, "interviews": 0})
        p["applied"] += 1
        p["responded"] += j["outcome"] in RESPONDED
        p["interviews"] += j["outcome"] in ("interview", "offer")
    platforms = sorted(by_platform.values(), key=lambda p: -p["applied"])
    for p in platforms:
        p["rate"] = round(100 * p["responded"] / p["applied"]) if p["applied"] else 0

    waits = [(_d(j["outcome_at"]) - _d(j["submitted_at"])).days for j in applied
             if j["outcome"] in RESPONDED and _d(j["outcome_at"]) and _d(j["outcome_at"]) >= _d(j["submitted_at"])]
    reply_times = [(label, sum(lo <= w <= hi for w in waits)) for label, lo, hi in REPLY_BUCKETS]
    median_wait = sorted(waits)[len(waits) // 2] if waits else None

    wk_counts = {w["start"]: w["count"] for w in dua_weeks(db, today)}
    recent = span[-12:]
    met = sum(1 for wk in recent if wk_counts.get(wk, 0) >= floor)
    first = min((_d(j["submitted_at"]) for j in applied), default=None)
    active = [wk for wk in recent if first and wk >= week_start(first)]
    streak = 0
    for wk in reversed(span):
        if wk == this_week and wk_counts.get(wk, 0) < floor:
            continue  # the current week isn't over yet
        if wk_counts.get(wk, 0) >= floor:
            streak += 1
        else:
            break

    states = Counter(j["state"] for j in applied)
    skipped = Counter((j["error"] or "no reason").split(":")[0][:40] for j in jobs if j["status"] == "skipped")
    from . import coach
    return {**base,
            "weeks": weeks,
            # Beyond applications: counts only, from this install (no visits or opens are ever counted).
            "planned_weeks": coach.weeks_planned(db),
            "contacts_total": len(coach.contacts(db)),
            "contact_interviews": coach.interviews_from_contacts(db),
            "reflections": len(coach.reflections(db)),
            "found_series": [(wk, f) for wk, f, _ in pipeline],
            "recruiter_series": [(wk, rec_wk.get(wk, 0)) for wk in span],
            "platforms": platforms,
            "reply_times": reply_times,
            "median_wait": median_wait,
            "interview_rate": round(100 * base["interviews"] / base["applied"]) if base["applied"] else 0,
            "weeks_met": met, "weeks_active": len(active), "streak": streak,
            "states": [({"confirmed": "Received", "rejected": "Closed", "no reply": "No reply yet"}.get(k, k.capitalize()), states.get(k, 0)) for k in ("waiting", "confirmed", "interview", "offer", "rejected", "no reply")],
            "skip_reasons": skipped.most_common(6),
            "found_total": sum(found_wk.values()),
            "work_weeks": [(wk, wk_counts.get(wk, 0)) for wk in recent]}
