"""Where jobs come from: every source in one list with its status and how to turn it on.

New users shouldn't have to find Setup's job-sites checkboxes or know that LinkedIn and HigherEdJobs only work
through alert emails. This is read-only: it looks at config.yaml, saved keys, the last search's counts
(data/sources.json) and which alert senders have shown up in Leads.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

# Alert emails people can set up, with where to do it. Order is roughly how many roles each brings in.
ALERTS = [
    ("LinkedIn", "linkedin.com", "In LinkedIn: search Jobs, then turn on 'Set alert' (daily, by email). Add a few with tight filters.",
     "https://www.linkedin.com/jobs/"),
    ("Indeed", "indeed.com", "On Indeed: search, then 'Get new jobs for this search by email'. Indeed's job-match emails count too.",
     "https://www.indeed.com/"),
    ("HigherEdJobs", "higheredjobs.com", "Universities and colleges. My Account, then Job Agent: pick categories and email it daily.",
     "https://www.higheredjobs.com/"),
    ("Built In", "builtin.com", "Tech companies by city. Save a search and turn on job alerts.", "https://builtin.com/jobs"),
    ("Glassdoor", "glassdoor.com", "Save a search and turn on job alerts.", "https://www.glassdoor.com/Job/"),
    ("Wellfound", "wellfound.com", "Startups. Set your job preferences to get matches by email.", "https://wellfound.com/jobs"),
    ("ZipRecruiter", "ziprecruiter.com", "Save a search and turn on job alerts.", "https://www.ziprecruiter.com/"),
    ("Dice", "dice.com", "Tech roles. Save a search and turn on alerts.", "https://www.dice.com/"),
]


def _last_search(settings) -> dict:
    try:
        return json.loads((settings.data_dir / "sources.json").read_text()).get("sources", {})
    except (OSError, ValueError):
        return {}


def _alert_counts(db, days: int = 14) -> dict[str, int]:
    """Leads seen per alert sender in the last `days` days, keyed by the sender's domain fragment."""
    since = (date.today() - timedelta(days=days)).isoformat()
    try:
        rows = db.conn.execute("select lower(source), count(*) from leads where last_seen >= ? group by 1", (since,)).fetchall()
    except Exception:  # leads table not created yet
        return {}
    out = {}
    for src, n in rows:
        for name, frag, _, _ in ALERTS:
            if name.lower().replace(" ", "") in (src or "").replace(" ", ""):
                out[frag] = out.get(frag, 0) + n
    return out


def overview(settings, db) -> dict:
    """{"groups": [...], "on": n, "total": n}. Each item: name, status (on/off/needs), detail, action, href."""
    from .finder import boards
    from .prefs import Prefs
    from .setup import FEED_LABELS
    from .sources import EXTRA

    prefs = Prefs(settings.data_dir, settings.raw)
    feeds = set(settings.raw.get("feeds") or [])
    last = _last_search(settings)
    groups = []

    blist = boards(settings)
    n_boards = len(blist)
    groups.append({"title": "Company job boards", "blurb": "Checked first every day, straight from each company's own careers page.",
                   "items": [{"name": f"{n_boards} companies watched" if n_boards else "No companies yet",
                              "status": "on" if n_boards else "off",
                              "detail": "Greenhouse, Lever, Ashby, Workable and SmartRecruiters careers pages. The weekly run adds good ones it finds.",
                              "action": "Add companies", "href": "/setup#interests"}]})

    items = []
    for key, label in FEED_LABELS.items():
        needs = (EXTRA.get(key) or (None, None, None))[2]
        missing = [k for k in (needs or ()) if not prefs.key(k)]
        got = last.get(key) or {}
        if key not in feeds:
            status, detail = "off", "Turn it on in Setup." + (" Needs a free key." if needs else "")
        elif missing:
            status, detail = "needs", "Turned on, but missing " + " and ".join(m.replace("_", " ").title() for m in missing) + "."
        else:
            status = "on"
            detail = (f"Last search: {got.get('fetched', 0)} roles, {got.get('new', 0)} new." if got else "Runs with the next search.")
            if got.get("error"):
                status, detail = "needs", f"Last search failed: {str(got['error'])[:80]}"
        items.append({"name": label.split(" (")[0], "status": status, "detail": detail,
                      "action": "Set up" if status != "on" else "", "href": "/setup#interests"})
    rss = settings.raw.get("rss_feeds") or []
    items.append({"name": f"RSS feeds ({len(rss)})" if rss else "RSS feeds", "status": "on" if rss else "off",
                  "detail": "Any job site with an RSS feed, like We Work Remotely." if not rss else "Checked with every search.",
                  "action": "" if rss else "Add a feed", "href": "/setup#interests"})
    groups.append({"title": "Job sites", "blurb": "Public job sites searched for your titles. Free; two need a free key.", "items": items})

    gmail = bool(prefs.key("GMAIL_USER") and prefs.key("GMAIL_APP_PASSWORD"))
    seen = _alert_counts(db)
    items = []
    for name, frag, how, url in ALERTS:
        n = seen.get(frag, 0)
        if not gmail:
            status, detail = "needs", "Connect Gmail first, then set up the alert. " + how
        elif n:
            status, detail = "on", f"{n} role{'s' if n != 1 else ''} from its emails in the last 2 weeks."
        else:
            status, detail = "off", how
        items.append({"name": name, "status": status, "detail": detail, "action": "" if status == "on" else "How",
                      "href": url if gmail else "/setup#gmail", "external": gmail})
    groups.append({"title": "Job-alert emails", "blurb": "Sites that don't allow automated searching (LinkedIn, Indeed, HigherEdJobs) "
                   "come in through their alert emails. Each good role is then looked up on the company's own site.", "items": items})

    every = [i for g in groups for i in g["items"]]
    return {"groups": groups, "on": sum(i["status"] == "on" for i in every), "total": len(every),
            "companies": _companies(blist, db), "boards": groups[0]["items"][0],
            "working": [i for g in groups[1:] for i in g["items"] if i["status"] == "on"],
            "needs": [i for g in groups[1:] for i in g["items"] if i["status"] == "needs"],
            "off": [i for g in groups[1:] for i in g["items"] if i["status"] == "off"]}


def _pretty(slug: str) -> str:
    """'gohighlevel' -> 'Gohighlevel', 'red-hat' -> 'Red Hat'; names that already have capitals stay as they are."""
    s = re.sub(r"[-_]+", " ", slug).strip()
    return s if any(ch.isupper() for ch in s) else s.title()


def _companies(blist: list[dict], db) -> list[dict]:
    """Each watched company, A to Z, with how many roles were found on its board in the last 30 days."""
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    try:
        found = {(a, (c or "").lower()): n for a, c, n in db.conn.execute(
            "select ats, lower(company), count(*) from jobs where found_at >= ? group by 1, 2", (since,))}
    except Exception:  # noqa: BLE001 - counts are a nicety
        found = {}
    out = [{"name": _pretty(b["slug"]), "ats": b["ats"], "roles": found.get((b["ats"], b["slug"].lower()), 0)} for b in blist]
    return sorted(out, key=lambda c: c["name"].lower())
