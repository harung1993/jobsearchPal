"""Leads: every role that job-alert emails (LinkedIn, Indeed and others) mention, kept so you can sort and
prioritize them later. Only a couple a day get tailored; the rest wait here instead of being forgotten.

Parsing is plain Python on the alert's text part: LinkedIn and Indeed list each job as a few short lines
(title, company, location, sometimes salary) ending with "View job: <url>". No model is needed.
"""
from __future__ import annotations

import email
import re
from datetime import datetime

from . import alerts

NOISE = re.compile(r"actively hiring|connection|alumni|apply with|easy apply|promoted|your job alert|^hi\b|^hello\b|"
                   r"work setting:|^new\b.*\bjobs?\b|matches your|be an early applicant|^view job|^apply now|^\W*$|"
                   r"easily apply|responsive employer|urgently hiring|^jobs are based on|^salaries estimated", re.I)
SEPARATOR = re.compile(r"^-{5,}$|^_{5,}$|^={5,}$")
VIEW = re.compile(r"^(?:view job|view this job|see job|apply now)\s*:?\s*(https?://\S+)", re.I)
# Indeed's multi-job digest: no label, just the job's tracking link on its own line under each block.
BARE = re.compile(r"^(https?://(?:www\.)?indeed\.com/(?:pagead/clk|rc/clk|viewjob|m/viewjob)\S*)$", re.I)
SCHEMA = """
create table if not exists leads (
  key text primary key,            -- company|title, normalised: the same role from LinkedIn and Indeed is one lead
  title text, company text, location text, salary text, url text, source text,
  first_seen text, last_seen text, seen integer default 1,
  score real default 0, status text default 'new', job_id text
);
"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def key(company: str, title: str) -> str:
    return f"{_norm(company)}|{_norm(title)}"


def plain_text(raw: bytes) -> str:
    msg = email.message_from_bytes(raw)
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
    return ""


def source_of(addr: str) -> str:
    a = (addr or "").lower()
    for name in ("linkedin", "indeed", "glassdoor", "ziprecruiter", "builtin", "wellfound", "dice", "higheredjobs"):
        if name in a:
            return {"builtin": "Built In", "ziprecruiter": "ZipRecruiter", "higheredjobs": "HigherEdJobs"}.get(name, name.capitalize())
    return a.split("@")[-1] or "email"


def parse(text: str) -> list[dict]:
    """Jobs from an alert's plain text: the short lines just above each "View job: <url>"."""
    lines = [l.strip() for l in (text or "").splitlines()]
    out = []
    for i, line in enumerate(lines):
        m = VIEW.match(line) or BARE.match(line)
        if not m:
            continue
        block = []
        for prev in reversed(lines[max(0, i - 12):i]):
            if SEPARATOR.match(prev) or VIEW.match(prev) or BARE.match(prev) or prev.startswith("http"):
                break
            block.insert(0, prev)
        salary = next((re.sub(r"(?i)^salary:\s*", "", b) for b in block if re.match(r"(?i)^salary:|^\$\d", b)), "")
        keep = [b for b in block if b and len(b) <= 110 and not NOISE.search(b) and not re.match(r"(?i)^salary:|^\$\d", b)]
        if len(keep) < 2:
            continue
        title, company = keep[0], keep[1]
        location = keep[2] if len(keep) > 2 else ""
        if " - " in company and (not location or BARE.match(line)):  # Indeed: "Company - Location"
            company, location = (x.strip() for x in company.split(" - ", 1))
        url = m.group(1).split("?")[0] if "linkedin.com" in m.group(1) else m.group(1)
        out.append({"title": title[:200], "company": company[:120], "location": location[:120],
                    "salary": salary[:80], "url": url[:1000]})
    return out


def ensure(db):
    db.conn.executescript(SCHEMA)
    have = {r[1] for r in db.conn.execute("pragma table_info(leads)")}
    # apply_url, ats_checked (11/4): the company's own posting, found without AI.
    # tried_at, note (11/10): when Auto apply last ran on this lead and what it found, shown on the Leads page.
    for col in ("apply_url", "ats_checked", "tried_at", "note"):
        if col not in have:
            db.conn.execute(f"alter table leads add column {col} text")


def save(db, found: list[dict], source: str, when: datetime, search: dict, terms: set) -> int:
    """Adds new leads and bumps ones seen again. Returns how many were new."""
    from .rank import score
    ensure(db)
    new = 0
    at = when.strftime("%Y-%m-%d %H:%M")
    for j in found:
        k = key(j["company"], j["title"])
        if not k.strip("|") or "|" not in k or not k.split("|")[0] or not k.split("|")[1]:
            continue
        row = db.conn.execute("select seen, source from leads where key = ?", (k,)).fetchone()
        if row:
            srcs = sorted(set(filter(None, (row["source"] or "").split(", "))) | {source})
            db.conn.execute("update leads set seen = seen + 1, last_seen = max(last_seen, ?), source = ?, "
                            "salary = coalesce(nullif(salary, ''), ?) where key = ?", (at, ", ".join(srcs), j["salary"], k))
            continue
        s = score({"title": j["title"], "description": "", "found_at": at}, search, terms, now=when)
        db.conn.execute("insert into leads (key, title, company, location, salary, url, source, first_seen, last_seen, score) "
                        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (k, j["title"], j["company"], j["location"], j["salary"], j["url"], source, at, at, round(s, 2)))
        new += 1
    db.conn.commit()
    return new


TRACKED = {"submitted": "applied", "filled": "ready", "skipped": "dismissed"}  # job status -> lead status


def link_tracked(db):
    """A lead whose role is now tracked (added from the company's site) points at that job."""
    ensure(db)
    by_key = {key(j["company"], j["title"]): j for j in db.all() if j.get("company") and j.get("title")}
    for r in db.conn.execute("select key from leads where job_id is null").fetchall():
        j = by_key.get(r["key"])
        if j:
            st = TRACKED.get(j["status"], "tracked")
            db.conn.execute("update leads set job_id = ?, status = case when status = 'starred' and ? = 'tracked' "
                            "then 'starred' else ? end where key = ?", (j["id"], st, st, r["key"]))
    db.conn.commit()


def sync(db, settings, days: int = 3) -> dict:
    """Reads alert emails (All Mail, Spam, Trash; read-only) and files every role in them as a lead."""
    from .rank import profile_terms
    ensure(db)
    search, terms = settings.raw.get("search") or {}, profile_terms(settings.root)
    senders = settings.raw.get("alert_senders") or alerts.DEFAULT_SENDERS
    emails = jobs = new = 0
    for _, _, addr, _, when, text, raw in alerts.messages(days, senders):
        found = parse(plain_text(raw)) or parse(text)
        emails += 1
        jobs += len(found)
        new += save(db, found, source_of(addr), when.replace(tzinfo=None) if when.tzinfo else when, search, terms)
    link_tracked(db)
    return {"emails": emails, "roles": jobs, "new": new}


def rows(db, status: str = "") -> list[dict]:
    ensure(db)
    q, args = "select * from leads", ()
    if status:
        q, args = q + " where status = ?", (status,)
    return [dict(r) for r in db.conn.execute(q + " order by (status = 'starred') desc, score desc, last_seen desc", args)]


def set_status(db, k: str, status: str):
    if status not in ("new", "starred", "dismissed"):
        raise ValueError(status)
    ensure(db)
    db.conn.execute("update leads set status = ? where key = ?", (status, k))
    db.conn.commit()


def set_note(db, k: str, text: str, when: datetime | None = None):
    """What the last Auto apply on this lead found (e.g. "the posting says it has been filled"), with the time."""
    ensure(db)
    when = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")
    db.conn.execute("update leads set tried_at = ?, note = ? where key = ?", (when, (text or "").strip()[:400], k))
    db.conn.commit()


def get(db, k: str) -> dict | None:
    ensure(db)
    r = db.conn.execute("select * from leads where key = ?", (k,)).fetchone()
    return dict(r) if r else None


def starred_for_lookup(db, limit: int = 8, only: str = "") -> list[dict]:
    """Starred leads not tracked yet, in the shape the alerts step reads (data/daily/alert-roles.json).
    only: one lead's key (Auto apply on the Leads page), starred or not."""
    link_tracked(db)
    if only:
        r = get(db, only)
        return [{"company": r["company"], "title": r["title"], "link": r["url"], "why": "you asked to apply"}] if r and not r["job_id"] else []
    return [{"company": r["company"], "title": r["title"], "link": r["url"], "why": "you starred it"}
            for r in db.conn.execute("select * from leads where status = 'starred' and job_id is null "
                                     "order by score desc limit ?", (limit,))]


# ---------- finding a lead on the company's own job board, with no AI ----------

SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|corp|corporation|co|company|plc|gmbh|group|holdings|technologies|technology|labs|hq)\b")
RESOLVE_ATS = ("greenhouse", "lever", "ashby", "workable")


def slugs(company: str) -> list[str]:
    """Board slugs a company probably uses: "Coalition, Inc." -> coalition; "Rocket Money" -> rocketmoney, rocket-money."""
    full = _norm(company)
    short = re.sub(r"\s+", " ", SUFFIX.sub(" ", full)).strip() or full
    out = []
    for words in (short, full):
        for s in (words.replace(" ", ""), words.replace(" ", "-")):
            if s and s not in out:
                out.append(s)
    return out


def same_title(a: str, b: str) -> float:
    """How alike two job titles are, 0..1 (word overlap, so "Sr." vs "Senior" and word order matter little)."""
    syn = {"sr": "senior", "jr": "junior", "mgr": "manager", "eng": "engineer", "engineering": "engineer", "ii": "2", "iii": "3"}
    ta = {syn.get(w, w) for w in _norm(a).split()}
    tb = {syn.get(w, w) for w in _norm(b).split()}
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def resolve(db, settings, limit: int = 30, fetchers: dict | None = None, now: datetime | None = None) -> dict:
    """Looks up the best untracked leads on the company's public Greenhouse, Lever, Ashby or Workable board (plain
    HTTP, no model). A match is added as a job, so it joins the normal pipeline, and the lead links to it.
    Each lead is tried once a week; starred leads first, then by score."""
    from datetime import timedelta
    from . import finder
    fetchers = fetchers or {a: finder.FETCHERS[a] for a in RESOLVE_ATS}
    ensure(db)
    now = now or datetime.now()
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    todo = db.conn.execute("select * from leads where job_id is null and status in ('new', 'starred') "
                           "and (ats_checked is null or ats_checked < ?) "
                           "order by (status = 'starred') desc, score desc, last_seen desc limit ?", (week_ago, limit)).fetchall()
    watched = {_norm(b["slug"]).replace(" ", ""): b for b in finder.boards(settings)}
    boards: dict[str, list] = {}
    found = 0
    for r in todo:
        co = _norm(r["company"])
        if co not in boards:
            tries = [(b["ats"], b["slug"]) for k, b in watched.items() if k in slugs(r["company"]) and b["ats"] in fetchers]
            tries += [(a, s) for s in slugs(r["company"]) for a in fetchers]
            boards[co] = []
            for ats, slug in tries:
                try:
                    jobs = fetchers[ats](slug)
                except Exception:  # no such board (404) or the site is down: try the next
                    continue
                if jobs:
                    boards[co] = jobs
                    break
        best = max(boards[co], key=lambda j: same_title(r["title"], j["title"]), default=None)
        if best and same_title(r["title"], best["title"]) >= 0.75:
            job = {k: ("" if v is None else v) for k, v in best.items()}
            job["company"] = r["company"]  # the board only knows its slug
            db.upsert_job(job)  # already tracked from a watched board: keeps that job and its status
            st = TRACKED.get(db.get(job["id"])["status"], "tracked")
            db.conn.execute("update leads set job_id = ?, apply_url = ?, status = case when status = 'starred' and ? = 'tracked' "
                            "then 'starred' else ? end where key = ?", (job["id"], job["url"], st, st, r["key"]))
            found += 1
        db.conn.execute("update leads set ats_checked = ? where key = ?", (now.strftime("%Y-%m-%d %H:%M"), r["key"]))
    db.conn.commit()
    return {"checked": len(todo), "found": found, "companies": len(boards)}
