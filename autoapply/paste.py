"""Paste a job: reads a whole pasted job post (a LinkedIn job page, a company careers page, a job email) into the
fields a lead needs. Plain Python, no model: the person checks and fixes the fields before anything is saved.

LinkedIn pages copied whole carry the nav bar, Premium ads, a "More jobs" list and the messaging bar. Only the
job's own lines and the text under "About the job" are kept.
"""
from __future__ import annotations

import re

from .history import _web

PAY = re.compile(r"\$\s?[\d.,]+\s?[KkMm]?(?:\s?/\s?(?:yr|year|hr|hour))?\s*(?:-|–|to)\s*\$\s?[\d.,]+\s?[KkMm]?"
                 r"(?:\s?/\s?(?:yr|year|hr|hour))?(?:\s+(?:a|per)\s+(?:year|hour))?")
SETTING = re.compile(r"\b(on-?site|in[- ]office|hybrid|remote)\b", re.I)
URL = re.compile(r"https?://[^\s<>\"')]+")
# LinkedIn: the description runs from "About the job" to the first of these.
LI_END = re.compile(r"^(fair chance notices|set alert for similar jobs|about the company|more jobs|show more|"
                    r"unlock hiring insights|see more jobs like this|job search smarter)\b", re.I)
LI_PLACE = re.compile(r"^(?P<co>.+?)\s+•\s+(?P<loc>.+?)(?:\s+\((?P<set>On-site|Hybrid|Remote)\))?$")
LABEL = re.compile(r"^(location|salary|pay|compensation|company|title|job title|role)\s*:\s*(.*)$", re.I)
FIELDS = ("company", "title", "location", "work_setting", "pay", "url", "description")


def is_link(text: str) -> bool:
    """The whole paste is one ordinary web address."""
    t = (text or "").strip()
    return bool(t) and not re.search(r"\s", t) and bool(_web(t))


def _setting(s: str) -> str:
    m = SETTING.search(s or "")
    if not m:
        return ""
    w = m.group(1).lower()
    return "remote" if w == "remote" else "hybrid" if w == "hybrid" else "on-site"


def _pay(text: str) -> str:
    m = PAY.search(text or "")
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else ""


def _link(text: str) -> str:
    for u in URL.findall(text or ""):
        u = u.rstrip(".,;")
        if "linkedin.com" not in u and _web(u):
            return u
    return ""


def _tidy(lines: list[str]) -> str:
    text = "\n".join(l.rstrip() for l in lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:20000]


def _linkedin(lines: list[str]) -> dict | None:
    co_i = next((i for i, l in enumerate(lines) if re.match(r"^Company, .+\.$", l)), None)
    about = next((i for i, l in enumerate(lines) if l.lower() == "about the job"), None)
    if co_i is None and about is None:
        return None
    out = dict.fromkeys(FIELDS, "")
    top = lines[: about if about is not None else len(lines)]
    if co_i is not None:
        out["company"] = re.match(r"^Company, (.+)\.$", lines[co_i]).group(1).strip()
        nxt = next((l for l in lines[co_i + 1:] if l), "")
        out["title"] = re.split(r"\s*\((?:Verified job|Promoted)\)", nxt)[0].strip()  # "T (Verified job)T" -> "T"
    for l in top:
        m = LI_PLACE.match(l)
        if m and (not out["company"] or m.group("co").strip() == out["company"]):
            out["company"] = out["company"] or m.group("co").strip()
            out["location"] = m.group("loc").strip()
            out["work_setting"] = _setting(m.group("set") or "")
            break
    if not out["work_setting"]:
        out["work_setting"] = next((_setting(l) for l in top if len(l) < 20 and _setting(l)), "")
    out["pay"] = next((_pay(l) for l in top if _pay(l)), "")
    body = []
    for l in lines[(about + 1) if about is not None else len(lines):]:
        if LI_END.match(l):
            break
        body.append(l)
    out["description"] = _tidy(body)
    out["url"] = _link("\n".join(body))
    return out


def _generic(lines: list[str]) -> dict:
    out = dict.fromkeys(FIELDS, "")
    rest = [l for l in lines if l]
    labelled = {}
    for l in rest[:15]:
        m = LABEL.match(l)
        if m and m.group(2).strip():
            labelled[m.group(1).lower()] = m.group(2).strip()
    plain = [l for l in rest[:6] if not LABEL.match(l) and not _pay(l) and not URL.search(l) and len(l) <= 110]
    out["title"] = labelled.get("title") or labelled.get("job title") or labelled.get("role") or (plain[0] if plain else "")
    out["company"] = labelled.get("company") or (plain[1] if len(plain) > 1 and not SETTING.fullmatch(plain[1]) else "")
    out["location"] = labelled.get("location", "")
    text = "\n".join(rest)
    out["pay"] = _pay(labelled.get("salary") or labelled.get("pay") or labelled.get("compensation") or "") or _pay(text)
    out["work_setting"] = _setting(out["location"]) or _setting("\n".join(rest[:15]))
    out["url"] = _link(text)
    if len(rest) > 2:
        head = {out["title"], out["company"]}
        lines = [l for l in lines if l not in head and not LABEL.match(l)]
    out["description"] = _tidy(lines)
    return out


def read(text: str) -> dict:
    """Company, title, location, work_setting (on-site | hybrid | remote | ""), pay, url and description from a pasted
    job post. Unknown fields are "". Never raises on odd input."""
    lines = [l.strip() for l in (text or "").replace("\r", "").splitlines()]
    out = _linkedin(lines) or _generic(lines)
    return {k: (out.get(k) or "")[: 20000 if k == "description" else 300] for k in FIELDS}


LINK_ATS = {"greenhouse.io": "greenhouse", "lever.co": "lever", "ashbyhq.com": "ashby"}


def from_link(url: str, fetchers: dict | None = None) -> dict | None:
    """A bare link to a public Greenhouse, Lever or Ashby posting, read through the board's own API (no login, no
    model). None for any other site (LinkedIn and Workday need the page's text pasted) or when it isn't found."""
    from urllib.parse import urlparse
    from . import finder
    u = urlparse((url or "").strip())
    ats = next((a for host, a in LINK_ATS.items() if u.netloc == host or u.netloc.endswith("." + host)), None)
    parts = [p for p in u.path.split("/") if p]
    if not ats or len(parts) < 2:
        return None
    slug = parts[0]
    try:
        jobs = (fetchers or finder.FETCHERS)[ats](slug)
    except Exception:  # no such board, or the site is down
        return None
    path = "/" + "/".join(parts) + "/"
    job = next((j for j in jobs if f"/{str(j['id']).rsplit(':', 1)[-1]}/" in path), None)
    if not job:
        return None
    text = re.sub(r"<[^>]+>", "\n", job.get("description") or "")
    return {"company": slug.replace("-", " ").title(), "title": job.get("title") or "", "location": job.get("location") or "",
            "work_setting": _setting(job.get("location") or ""), "pay": _pay(text), "url": _web(job.get("url") or url),
            "description": _tidy([l.strip() for l in text.splitlines()])}
