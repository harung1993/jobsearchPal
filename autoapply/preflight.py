"""Pre-submit checks: is everything the company will get complete and right?

Runs after every fill and on the review page. A failed hard check keeps Submit locked; a warning is shown
but doesn't block. Nothing here changes a file or the form; it only reads.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

PLACEHOLDERS = re.compile(r"\[(company|role|title|name|hiring manager|position)[^\]]*\]|\bTODO\b|\bTBD\b|lorem ipsum|\{\{|\}\}|XX+\b", re.I)
DATE_RANGE = re.compile(r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{1,2}/\d{4}|\d{4})"
                        r"\s*[-–—to]+\s*"
                        r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{1,2}/\d{4}|\d{4}|present|current|now)\b", re.I)
MAX_PAGES = {"resume": 2, "cover": 1}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("–", "-").replace("—", "-")).strip().lower()


def pdf_text(path: Path) -> tuple[str, int] | None:
    """(text, pages) via pypdf, else poppler's pdftotext/pdfinfo. None when neither can read it."""
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in r.pages), len(r.pages)
    except ImportError:
        pass
    except Exception:
        return None
    if shutil.which("pdftotext") and shutil.which("pdfinfo"):
        try:
            text = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=30).stdout
            info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=30).stdout
            pages = int((re.search(r"^Pages:\s+(\d+)", info, re.M) or [0, 0])[1])
            return text, pages
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    return None


def page_texts(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
        return [(p.extract_text() or "") for p in PdfReader(str(path)).pages]
    except Exception:
        return []


def base_dates(root: Path) -> list[str]:
    """Date ranges from the base resume (e.g. 'Mar 2019 - Sep 2026'): the tailored one must keep every one."""
    from .setup import base_resume
    b = base_resume(root)
    if not b:
        return []
    try:
        import docx
        text = "\n".join(p.text for p in docx.Document(str(b)).paragraphs)
        for t in docx.Document(str(b)).tables:
            text += "\n" + "\n".join(c.text for row in t.rows for c in row.cells)
    except Exception:
        return []
    return sorted({_norm(m.group(0)) for m in DATE_RANGE.finditer(text)})


def _kind(slot: str, path: str) -> str:
    s = f"{slot} {Path(path).name}".lower()
    return "cover" if "cover" in s else ("resume" if "resume" in s or "cv" in s else "")


def check(job: dict, plan: dict, report: dict, profile: dict, root: Path, other_companies: list[str] = ()) -> list[dict]:
    out: list[dict] = []

    def add(group, name, ok, detail="", hard=True):
        out.append({"group": group, "name": name, "ok": bool(ok), "detail": detail, "hard": hard})

    company = (job.get("company") or "").strip()
    files = plan.get("files") or {}
    if not any(_kind(s, p) == "resume" for s, p in files.items()):
        add("Documents", "Resume attached", False, "No resume in the plan's files.")
    dates = base_dates(root)
    name = " ".join(x for x in (profile.get("first_name"), profile.get("last_name")) if x)
    for slot, p in files.items():
        kind = _kind(slot, p)
        path = Path(p) if Path(p).is_absolute() else root / p
        label = {"resume": "Resume", "cover": "Cover letter"}.get(kind, Path(p).name)
        g = f"{label} ({path.name})"
        if not path.is_file():
            add(g, "File exists", False, str(p))
            continue
        docx_twin = path.with_suffix(".docx")
        if path.suffix.lower() == ".pdf" and docx_twin.is_file():
            stale = docx_twin.stat().st_mtime - path.stat().st_mtime
            add(g, "PDF is up to date with the Word file", stale <= 1,
                f"The .docx was changed {int(stale)}s after the PDF was made. Rebuild the PDF." if stale > 1 else "")
        if path.suffix.lower() != ".pdf":
            continue
        got = pdf_text(path)
        if got is None:
            add(g, "PDF can be read", False, "Couldn't read the PDF text (install pypdf or poppler-utils).", hard=False)
            continue
        text, pages = got
        flat = _norm(text)
        if kind in MAX_PAGES:
            add(g, f"At most {MAX_PAGES[kind]} page{'s' if MAX_PAGES[kind] > 1 else ''}", 0 < pages <= MAX_PAGES[kind], f"{pages} pages")
        per = page_texts(path)
        if len(per) > 1:
            last = len(_norm(per[-1]))
            add(g, "No near-empty last page", last >= 300, f"Last page has only {last} characters: something spilled over." if last < 300 else "", hard=False)
        if name:
            add(g, "Has your name", _norm(name) in flat)
        if profile.get("email"):
            add(g, "Has your email", profile["email"].lower() in flat.replace(" ", ""), hard=kind == "resume")
        bad = sorted({m.group(0) for m in PLACEHOLDERS.finditer(text)})
        add(g, "No placeholder text", not bad, ", ".join(bad[:5]))
        if kind == "resume" and dates:
            missing = [d for d in dates if d not in flat]
            add(g, "Every job date from your base resume", not missing,
                "Missing: " + "; ".join(missing[:4]) if missing else f"{len(dates)} date ranges found")
        if kind == "cover" and company:
            add(g, f"Names {company}", _norm(company) in flat)
            wrong = [c for c in other_companies if c and _norm(c) != _norm(company) and len(c) > 3
                     and re.search(rf"\b{re.escape(_norm(c))}\b", flat)]
            add(g, "No other company's name", not wrong, ", ".join(wrong[:3]), hard=False)

    req_open = [u["label"] for u in report.get("unanswered", []) if u.get("required")]
    add("Form", "Every required question answered", not req_open, "; ".join(req_open[:4]))
    held_open = [h["label"] for h in report.get("held", []) if h.get("required")
                 and not ((plan.get("approved") or {}).get(h["label"]) or h.get("value"))]
    add("Form", "Required consents chosen by you", not held_open, "; ".join(held_open[:4]))
    errs = [f"{e.get('label')}: {e.get('error')}" for e in report.get("errors", [])]
    add("Form", "No fill errors", not errs, "; ".join(errs[:3]))
    # A list, not a dict: two fields can share a label (Ashby's "Phone" number and its "Phone" text-consent question).
    filled = [(f.get("label", "").lower(), str(f.get("value", ""))) for f in report.get("filled", [])]
    for key, pat in (("email", "e-mail|email"), ("phone", "phone")):
        want = str(profile.get(key) or "")
        got = [v for lbl, v in filled if re.search(pat, lbl)
               and (key != "phone" or re.sub(r"\D", "", v))]  # the consent answer has no digits: not a phone number
        if want and got:
            same = any(re.sub(r"\D", "", v) == re.sub(r"\D", "", want) if key == "phone" else v.strip().lower() == want.lower() for v in got)
            add("Form", f"{key.capitalize()} matches your profile", same, f"form has {got[0]}" if not same else "")
    return out


def blocking(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["hard"] and not c["ok"]]


def for_job(db, settings, job_id: str) -> list[dict]:
    import json
    job = db.get(job_id)
    if not job:
        return []
    plan, report = json.loads(job["plan_json"] or "{}"), json.loads(job["report_json"] or "{}")
    others = sorted({j["company"] for j in db.by_status("submitted", "filled") if j.get("company")})
    return check(job, plan, report, settings.profile or {}, settings.root, others)
