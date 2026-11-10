"""Cheap pre-ranking in Python, so the daily agent reads a short list instead of every new role.

The score is a rough fit signal, not a decision: title keyword hits, overlap between the posting and the
words on your base resume and notes, and freshness. The agent still reads the top few and picks.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

STOP = set("""a an and are as at be by for from has have in is it its of on or our that the their this to we will with
you your they them who what which while all any can more most other some such than then there these those into about
over under also not only very just been being were was do does did per via etc using use used work working team teams
experience years year role roles company job jobs including include strong ability skills skill across within new""".split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9+#.]{1,30}", (text or "").lower()) if w not in STOP and not w.endswith(".")]


def profile_text(root: Path) -> str:
    """Your base resume and notes as plain text."""
    from .setup import base_resume
    texts = []
    r = base_resume(root)
    if r:
        try:
            from docx import Document
            d = Document(str(r))
            texts.append("\n".join(p.text for p in d.paragraphs))
            texts += [c.text for t in d.tables for row in t.rows for c in row.cells]
        except Exception:
            pass
    for p in [root / "CLAUDE.local.md", *sorted((root / "materials" / "context").glob("*.md"))]:
        try:
            texts.append(p.read_text()[:20000])
        except OSError:
            pass
    return "\n".join(texts)


def profile_terms(root: Path, limit: int = 120) -> set[str]:
    """The most frequent meaningful words in your base resume and notes."""
    c = Counter(_words(profile_text(root)))
    return {w for w, _ in c.most_common(limit)}


# Seniority read from a title. "mid" is a title with none of these words (Data Engineer, Analytics Engineer II).
LEVELS = [("entry", "Entry"), ("mid", "Mid-level"), ("senior", "Senior and staff"), ("lead", "Lead and principal"),
          ("manager", "Manager and up")]
_LEVEL_RX = [("manager", r"\b(manager|director|head|vp|vice president|chief)\b"), ("lead", r"\b(lead|principal)\b"),
             ("senior", r"\b(senior|sr\.?|staff)\b"), ("entry", r"\b(junior|jr\.?|entry|associate|graduate|new grad|intern)\b")]


def level_of(title: str) -> str:
    t = (title or "").lower()
    return next((lvl for lvl, rx in _LEVEL_RX if re.search(rx, t)), "mid")


def score(job: dict, search: dict, terms: set[str], now: datetime | None = None, my_skills: list | None = None) -> float:
    title = (job.get("title") or "").lower()
    s = 3.0 * sum(1 for k in search.get("title_keywords") or [] if k in title)
    levels = search.get("levels") or []
    if levels:  # the levels you picked on Setup: a small lift for those, a small drop for the rest
        s += 1.0 if level_of(title) in levels else -1.0
    elif re.search(r"\b(senior|sr\.?|staff|lead|principal|head|manager|director)\b", title):
        s += 1.0  # nothing picked: the old lean toward senior titles
    desc = set(_words(job.get("description") or ""))
    if terms and desc:
        s += 6.0 * len(desc & terms) / max(20, min(len(terms), 80))
    try:
        age = ((now or datetime.now()) - datetime.fromisoformat(str(job.get("found_at"))[:19])).days
        s += max(0.0, 2.0 - 0.25 * age)
    except ValueError:
        pass
    if job.get("ats") == "feed":
        s -= 0.5  # needs a hop to the real posting
    if my_skills:  # optional AI skill matching (skills.py): the posting's must-haves you have count most
        from .skills import for_job
        m = for_job(job, my_skills)
        if m:
            s += 5.0 * m["ratio"] + 1.0 * m["nice_ratio"]
    return round(s, 2)


DONE = {"submitted": "applied", "filled": "filled a form", "prepped": "prepped an application"}


class Applied:
    """Companies you've applied to lately: from the tool's own applications (including ones imported from your
    tracker or marked "applied by hand") and from synced emails like "Thank you for applying to Acme"."""

    EVENT_KINDS = ("confirmed", "rejected", "interview", "offer", "applied")

    def __init__(self, db, days: int = 90, now: datetime | None = None):
        now = now or datetime.now()
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d") if days else "0000"
        self.jobs = {}   # company key -> an application inside the re-apply window
        self.roles = {}  # (company key, title) -> any application ever: the same role is never applied to twice
        self.urls = {}   # posting link -> the same, for a role whose title changed
        for j in db.by_status("submitted", "filled", "prepped"):  # prepped: files made for it, applying by hand
            when = str(j.get("submitted_at") or j.get("found_at") or "")[:10]
            hit = (j["status"], when, j["title"])
            ck = company_key(j["company"])
            self.roles.setdefault((ck, _norm(j["title"])), hit)
            for u in (j.get("url"), j.get("apply_url")):
                if _url(u):
                    self.urls.setdefault(_url(u), hit)
            if j["status"] in ("filled", "prepped") or not when or when >= cutoff:
                self.jobs.setdefault(ck, hit)
        self.mail = " | ".join(_norm(f"{e['sender']} {e['subject']}") for e in db.events()
                               if e["kind"] in self.EVENT_KINDS and str(e["at"])[:10] >= cutoff)

    def same_role(self, company: str, title: str = "", url: str = "") -> str:
        """Why this exact role is off the table ("" = it isn't): applied or filled before, by title or by link."""
        role = self.roles.get((company_key(company), _norm(title))) if title else None
        role = role or (self.urls.get(_url(url)) if _url(url) else None)
        if not role:
            return ""
        st, when, t = role
        return (f"already {DONE.get(st, 'filled a form')} for this role at {company}"
                f" ({t}{', ' + when if when else ''})")

    def why(self, company: str, title: str = "", url: str = "") -> str:
        """Why to skip this role ("" = fine). The same role is skipped forever; the company only inside the window."""
        c = _norm(company)
        if not c:
            return ""
        role = self.same_role(company, title, url)
        if role:
            return role
        ck = company_key(company)
        if ck in self.jobs:
            st, when, title = self.jobs[ck]
            return f"already {DONE.get(st, 'filled a form')} at {company} ({title}{', ' + when if when else ''})"
        if len(c) >= 3 and re.search(rf"(^| ){re.escape(c)}( |$)", self.mail):
            return f"already applied at {company} (from your email)"
        return ""


def candidates(db, settings, limit: int = 12, desc_chars: int = 1200) -> list[dict]:
    """New roles, best first, with trimmed descriptions. Saves each score on the job. Companies you applied to
    lately are skipped here, before any model sees them."""
    from .prefs import Prefs
    search = settings.raw.get("search") or {}
    terms = profile_terms(settings.root)
    prefs = Prefs(settings.data_dir, settings.raw)
    applied = Applied(db, int(prefs.data.get("reapply_after_days", 90) or 0))
    from . import skills
    my = skills.mine(settings) if skills.enabled(prefs) else []
    rows = []
    for j in db.by_status("new"):
        why = applied.why(j["company"], j["title"], j.get("apply_url") or j.get("url"))
        if why:
            db.update(j["id"], status="skipped", error=why)
            continue
        sc = score(j, search, terms, my_skills=my)
        rows.append((sc, j))
        if j.get("score") != sc:
            db.update(j["id"], score=sc)
    rows.sort(key=lambda r: r[0], reverse=True)
    out = []
    for sc, j in rows[:limit]:
        d = re.sub(r"\s+", " ", j.get("description") or "").strip()
        out.append({"id": j["id"], "score": sc, "company": j["company"], "title": j["title"], "location": j["location"],
                    "ats": j["ats"], "url": j["url"], "found_at": j["found_at"],
                    "description": d[:desc_chars] + ("…" if len(d) > desc_chars else ""),
                    **({"skills": skills.summary(skills.for_job(j, my))} if my and j.get("skills_json") else {})})
    return out


def shortlist(db, settings, n: int = 5, skip_companies=()) -> list[dict]:
    """Today's best roles not prepared yet, for the dashboard: the run's own picks first, then the best-scored new
    roles. One per company, none you applied to lately. Read only: no scores or statuses are written."""
    from .prefs import Prefs
    if n <= 0:
        return []
    applied = Applied(db, int(Prefs(settings.data_dir, settings.raw).data.get("reapply_after_days", 90) or 0))
    try:
        picks = json.loads((settings.data_dir / "daily" / "picks.json").read_text())
    except (OSError, ValueError):
        picks = []
    why = {p["id"]: p.get("why", "") for p in picks if isinstance(p, dict) and p.get("id")}
    pool = [j for j in (db.get(i) for i in why) if j] + db.by_status("new")
    seen, out = {_norm(c) for c in skip_companies}, []
    for j in pool:
        c = _norm(j["company"])
        if j["status"] != "new" or not c or c in seen or applied.why(j["company"], j["title"], j.get("apply_url") or j.get("url")):
            continue
        seen.add(c)
        out.append({**j, "why": why.get(j["id"], "")})
        if len(out) >= n:
            break
    return out


QUICK_PROMPT = """You pick which new job postings are worth applying to today, for the person described below.
Pick at most {n}, at most one per company. Fit to the person comes first, then freshness, then pay. Skip roles they already applied to.
It's fine to pick fewer, or none, if nothing fits well. Fit decides, never a weekly quota: don't pick a weak fit to make up a count.

About the person:
{about}

Already applied to (skip these companies' same roles):
{applied}

Candidates (pre-ranked by a rough keyword score, best first):
{cands}

Reply with JSON only, no prose: {{"picks": [{{"id": "<candidate id>", "why": "<one line on fit>"}}]}}"""


def _about(root: Path, chars: int = 4000) -> str:
    parts = []
    for p in [root / "CLAUDE.local.md", *sorted((root / "materials" / "context").glob("*.md"))]:
        try:
            parts.append(p.read_text())
        except OSError:
            pass
    return "\n\n".join(parts)[:chars] or "(no notes yet; judge by the titles and the resume keywords)"


def quick_pick(db, settings, n: int, model: str, key: str, limit: int = 15) -> tuple[list[dict], dict]:
    """One cheap chat call instead of an agent session: candidates in, picks out. Returns (picks, usage)."""
    from . import classify
    cands = candidates(db, settings, limit, desc_chars=700)
    if not cands or n <= 0:
        return [], {"tokens": 0, "cost": 0.0}
    applied = sorted({f"{j['company']} ({j['title']})" for j in db.by_status("submitted")})[-60:]
    lines = [f"- id={c['id']} | {c['company']} | {c['title']} | {c['location'] or '?'} | found {str(c['found_at'])[:10]}"
             f"\n  {c['description']}" for c in cands]
    prompt = QUICK_PROMPT.format(n=n, about=_about(settings.root), applied="\n".join(applied) or "(none)",
                                 cands="\n".join(lines))
    data = classify._post("https://openrouter.ai/api/v1/chat/completions",
                          {"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}],
                           "response_format": {"type": "json_object"}, "usage": {"include": True}}, key)
    u = data.get("usage") or {}
    usage = {"tokens": int(u.get("total_tokens") or 0), "cost": float(u.get("cost") or 0)}
    text = data["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        raw = json.loads(m.group(0))["picks"]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError(f"the model's reply wasn't the JSON asked for: {text[:200]}")
    ok = {c["id"]: c for c in cands}
    picks, seen = [], set()
    for p in raw if isinstance(raw, list) else []:
        jid = p.get("id") if isinstance(p, dict) else None
        if jid in ok and jid not in seen:  # only ids we offered: the model can't add jobs
            seen.add(jid)
            c = ok[jid]
            picks.append({"id": jid, "why": str(p.get("why") or "")[:200],
                          **({"by_hand": True} if c["ats"] == "workday" else {})})
    return picks[:n], usage


ALERT_PROMPT = """These are job-alert emails (LinkedIn, Indeed, HigherEdJobs and others) for the person described below.
List the roles in them that clearly fit the person, at most {n}, best first. Leave out roles they already applied to.
It's fine to list none.

About the person:
{about}

Already applied to:
{applied}

Emails:
{emails}

Reply with JSON only, no prose:
{{"roles": [{{"company": "<company>", "title": "<job title>", "link": "<the link in the email, if any>", "why": "<one line>"}}]}}"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# Endings that don't make a company different: "Acme, Inc." is Acme, and a job board slug "acmecom" or "acmehq" is too.
_LEGAL = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "gmbh"}
_SLUG_TAILS = ("com", "hq")


def company_key(name: str) -> str:
    """One key per company across sources. Board slugs come lower-case and run together ("sigmacomputing", "nichecom");
    a tracker row says "Sigma Computing, Inc.". Spaces and legal endings go, and a trailing "com"/"hq" when 3+ letters stay."""
    words = _norm(name).split()
    while len(words) > 1 and words[-1] in _LEGAL:
        words.pop()
    k = "".join(words)
    for tail in _SLUG_TAILS:
        if k.endswith(tail) and len(k) - len(tail) >= 3:
            return k[: -len(tail)]
    return k


def _url(u: str | None) -> str:
    """A posting link without scheme, www, fragment, utm tags or trailing slash, so one posting matches however it was
    copied. The rest of the query stays: some boards put the job id there (?gh_jid=, ?currentJobId=)."""
    u = (u or "").strip().lower().split("#")[0]
    if not u.startswith("http"):
        return ""
    u = re.sub(r"^https?://(www\.)?", "", u)
    u = re.sub(r"[?&]utm_[^&]*", "", u).replace("/?", "?").rstrip("?&/")
    return u


def alert_roles(db, settings, emails: list[dict], model: str, key: str, limit: int = 8) -> tuple[list[dict], dict]:
    """One cheap call over the alert emails: the roles worth looking up. Drops ones already tracked."""
    from . import classify
    if not emails:
        return [], {"tokens": 0, "cost": 0.0}
    applied = sorted({f"{j['company']} ({j['title']})" for j in db.by_status("submitted")})[-60:]
    body = "\n\n".join(f"--- {e['from']} | {e['subject']}\n{e['text'][:3000]}" for e in emails)[:40000]
    prompt = ALERT_PROMPT.format(n=limit, about=_about(settings.root), applied="\n".join(applied) or "(none)", emails=body)
    data = classify._post("https://openrouter.ai/api/v1/chat/completions",
                          {"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}],
                           "response_format": {"type": "json_object"}, "usage": {"include": True}}, key)
    u = data.get("usage") or {}
    usage = {"tokens": int(u.get("total_tokens") or 0), "cost": float(u.get("cost") or 0)}
    text = data["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        raw = json.loads(m.group(0))["roles"]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError(f"the model's reply wasn't the JSON asked for: {text[:200]}")
    have = {(_norm(j["company"]), _norm(j["title"])) for j in db.all()}
    out = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict) or not r.get("company") or not r.get("title"):
            continue
        k = (_norm(r["company"]), _norm(r["title"]))
        if k in have:
            continue
        have.add(k)
        out.append({f: str(r.get(f) or "")[:300] for f in ("company", "title", "link", "why")})
    return out[:limit], usage
