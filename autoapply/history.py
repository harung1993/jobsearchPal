"""Your applications as a list you own: log one you sent elsewhere, import your old tracker (a CSV from Google Sheets or
Excel, or the JSON rows), and export them all as a CSV. Everything lives in the local database; no Google account needed.

One rule keeps it to one row per role, however it arrives: the same company (rank.company_key, so "Sigma Computing, Inc."
and the board slug "sigmacomputing" match) with the same title, or the same posting link, is the same application."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from .db import DB
from .rank import _norm, _url, company_key

# The tracker's columns, in the order the old JSON rows used. A CSV may name them in any order; HEADERS maps names to these.
COLUMNS = ["title", "company", "location", "applied", "pay", "found_on", "via", "notes", "url"]
HEADERS = {
    "title": ("position", "title", "role", "job title", "job"),
    "company": ("company", "employer", "organization", "organisation"),
    "location": ("location", "where", "city"),
    "applied": ("date applied", "applied", "applied on", "date", "applied date"),
    "pay": ("salary", "salary range", "pay", "compensation", "pay range"),
    "found_on": ("found on", "source", "found"),
    "via": ("applied via", "via", "how", "platform", "ats"),
    "notes": ("notes", "note", "comments", "status notes"),
    "url": ("link", "url", "posting", "job link", "posting link"),
}


def _date(s: str) -> str | None:
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y-%m-%d %H:%M", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d 12:00")
        except ValueError:
            pass
    return None


def outcome_from_notes(notes: str, year: int | None = None) -> tuple[str | None, str | None]:
    """Pulls 'Rejected 10/13' style notes into an outcome and a date (the applied year, else this year)."""
    m = re.search(r"\b(rejected|interview\w*|offer)\b[^0-9]{0,20}(\d{1,2})/(\d{1,2})", notes or "", re.I)
    if not m:
        return None, None
    kind = m.group(1).lower()
    kind = "interview" if kind.startswith("interview") else kind
    return kind, f"{year or date.today().year}-{int(m.group(2)):02d}-{int(m.group(3)):02d} 12:00"


def find(db: DB, company: str, title: str, url: str = "") -> dict | None:
    """The job already tracked for this role, applied or not; applications win over plain finds."""
    ck, t, u = company_key(company), _norm(title), _url(url)
    hits = [j for j in db.all()
            if (ck and t and company_key(j["company"]) == ck and _norm(j["title"]) == t)
            or (u and u in (_url(j.get("url")), _url(j.get("apply_url"))))]
    hits.sort(key=lambda j: (j["status"] != "submitted", j["status"] != "filled"))
    return hits[0] if hits else None


def _web(url: str) -> str:
    """A posting link only if it is an ordinary web address: it becomes a link on the dashboard, so a
    javascript: or data: value from an imported file must never get there."""
    url = (url or "").strip()
    p = urlparse(url)
    return url if p.scheme.lower() in ("http", "https") and p.netloc else ""


def log(db: DB, company: str, title: str, url: str = "", applied_on: str = "", pay: str = "", via: str = "",
        location: str = "", notes: str = "") -> dict:
    """Records one application you sent outside the tool. Returns {"id", "status": "added"|"marked"|"already"}:
    already = this role was tracked as applied before, and nothing changed."""
    company, title, url = company.strip(), title.strip(), _web(url)
    if not company or not title:
        raise ValueError("A company and a role title are needed.")
    when = _date(applied_on) if applied_on else datetime.now().strftime("%Y-%m-%d %H:%M")
    if not when:
        raise ValueError(f"Couldn't read the date {applied_on!r}. Use 2026-11-09 or 11/9/2026.")
    hit = find(db, company, title, url)
    if hit and hit["status"] == "submitted":
        return {"id": hit["id"], "status": "already", "job": hit}
    if hit:
        jid, result = hit["id"], "marked"
    else:
        jid = "manual:" + hashlib.sha1((_url(url) or f"{company_key(company)}|{_norm(title)}").encode()).hexdigest()[:10]
        db.upsert_job({"id": jid, "ats": _via(via, url), "company": company, "title": title, "location": location,
                       "url": url, "apply_url": url, "description": notes})
        db.update(jid, found_at=when)
        result = "added"
    db.update(jid, status="submitted", submitted_at=when, error=None,
              **({"pay": pay} if pay and not (hit or {}).get("pay") else {}))
    return {"id": jid, "status": result, "job": db.get(jid)}


def _via(via: str, url: str = "") -> str:
    if via.strip():
        return via.strip().split(" ")[0].lower()
    if url:
        from .fillers.base import detect
        return detect(url).name
    return "manual"


def _positional(r: list[str]) -> dict:
    return dict(zip(COLUMNS, (c.strip() for c in (list(r) + [""] * len(COLUMNS))[:len(COLUMNS)])))


def _mapper(header: list[str]):
    """A row -> dict reader for this header, or None when the header names none of our columns (then it's positional)."""
    names = [(h or "").strip().lower() for h in header]
    where = {}
    for col, aliases in HEADERS.items():
        for i, n in enumerate(names):
            if n in aliases and col not in where and i not in where.values():
                where[col] = i
    if not {"company", "title"} <= where.keys():
        return None
    return lambda r: {col: (r[i].strip() if i < len(r) else "") for col, i in where.items()}


def import_rows(db: DB, rows: list[list[str]]) -> int:
    """rows: header first. Columns are found by name (Position, Company, Date Applied, Salary, Applied via, Notes, Link...),
    or by position as in the old Job Tracker sheet. Rows without an applied date (leads, drafts) are left out.
    Returns how many applications were new; importing the same file twice adds nothing."""
    if not rows:
        return 0
    read = _mapper(rows[0]) or _positional
    n = 0
    for raw in rows[1:]:
        r = read(raw)
        r["url"] = _web(r.get("url", ""))
        company, title = r.get("company", ""), r.get("title", "")
        when = _date(r.get("applied", ""))
        if not (company and when):
            continue
        hit = find(db, company, title, r.get("url", ""))
        if hit:
            jid = hit["id"]
            if hit["status"] != "submitted":
                db.update(jid, status="submitted", submitted_at=when)
        else:
            jid = "tracker:" + hashlib.sha1(f"{company}|{title}".lower().encode()).hexdigest()[:10]
            db.upsert_job({"id": jid, "ats": _via(r.get("via", "")) if r.get("via") else "unknown", "company": company,
                           "title": title, "location": r.get("location", ""), "url": r.get("url", ""),
                           "apply_url": r.get("url", ""), "description": r.get("notes", "")})
            db.update(jid, status="submitted", submitted_at=when, found_at=when)
            n += 1
        kind, at = outcome_from_notes(r.get("notes", ""), int(when[:4]))
        extra = {"pay": r["pay"]} if r.get("pay") and not (hit or {}).get("pay") else {}
        if kind and not (hit or {}).get("outcome"):
            extra.update(outcome=kind, outcome_at=at)
        if extra:
            db.update(jid, **extra)
    return n


def import_csv(db: DB, text: str) -> int:
    return import_rows(db, [r for r in csv.reader(io.StringIO(text.lstrip("﻿"))) if any(c.strip() for c in r)])


def import_file(db: DB, path: Path) -> int:
    p = Path(path)
    if p.suffix.lower() == ".csv":
        return import_csv(db, p.read_text(encoding="utf-8-sig"))
    return import_rows(db, json.loads(p.read_text()))


EXPORT_HEADER = ["Position", "Company", "Location", "Date Applied", "Salary", "Applied via", "Status", "Reply", "Reply date",
                 "Link", "Notes"]


def export_csv(db: DB) -> str:
    """Every application, newest first, as a CSV that opens in any spreadsheet and imports back in unchanged."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(EXPORT_HEADER)
    jobs = sorted(db.by_status("submitted", "filled"), key=lambda j: j.get("submitted_at") or "", reverse=True)
    for j in jobs:
        w.writerow([j["title"], j["company"], j["location"] or "", (j.get("submitted_at") or "")[:10], j.get("pay") or "",
                    j["ats"] or "", "applied" if j["status"] == "submitted" else "filled, not sent yet",
                    j.get("outcome") or "", (j.get("outcome_at") or "")[:10], j.get("apply_url") or j.get("url") or "",
                    "" if not j["id"].startswith(("tracker:", "manual:")) else (j.get("description") or "")[:500]])
    return out.getvalue()
