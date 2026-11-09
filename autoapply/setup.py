"""First-run setup from the dashboard: the same files you'd otherwise edit by hand.

- Contact details and standard answers -> profile.yaml
- Job interests (titles, companies to watch, feeds) -> config.yaml
- Base resume -> materials/<Last name> Resume - Base.docx (+ .pdf)
- What you're looking for -> materials/context/setup.md (the agent reads materials/context/*.md)
- Gmail and the `autoapply finish` key -> data/secrets.json (owner-only; .env still wins)

Nothing here is required to come from the page: hand-edited files work as before.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

import yaml

from .prefs import find_cli

PROFILE_FIELDS = [
    ("first_name", "First name"), ("last_name", "Last name"), ("email", "Email"), ("phone", "Phone"),
    ("location", "City, State"), ("zip", "ZIP code"), ("linkedin", "LinkedIn URL"), ("github", "GitHub URL"),
    ("website", "Website"), ("current_company", "Current or last employer"),
    ("name_pronunciation", "Name pronunciation (optional)"),
]
# Your standing answers for questions the agent never answers. The filler pre-fills them and the review
# page shows them in a highlighted box for you to check before Submit. Blank = left for you each time.
CONSENT_MATCH = "consent|privacy|personal data|acknowledge|i agree|terms|ai policy|certify"
STANDING = [
    ("consent", "Privacy notices, data-processing consent, AI-policy and accuracy acknowledgements", CONSENT_MATCH),
    ("hispanic", "Hispanic or Latino?", r"hispanic|latin[oax]"),
    ("race", "Race / ethnicity", r"\brace\b|ethnic"),
    ("gender", "Gender", r"gender|\bsex\b"),
    ("orientation", "Sexual orientation", r"sexual orientation"),
    ("pronouns", "Pronouns", r"pronoun"),
    ("veteran", "Veteran status", r"veteran"),
    ("disability", "Disability status", r"disabilit"),
]
DECLINE = ["Decline to self-identify", "I don't wish to answer", "Prefer not to say"]
YES_NO = [("work_authorized", "Authorized to work in the US?"), ("requires_sponsorship", "Need visa sponsorship?"),
          ("willing_to_relocate", "Willing to relocate?")]
ABOUT_FIELDS = [
    ("roles", "Roles and level you want", "e.g. Senior or Staff Data Engineer; open to Analytics Engineering lead roles"),
    ("pay", "Pay ask", "e.g. $180K base; won't go below $160K"),
    ("where", "Where you'll work", "e.g. Remote in the US, or hybrid within an hour of Boston. No full-time onsite."),
    ("authorization", "Work authorization", "e.g. US citizen, no sponsorship needed"),
    ("strengths", "What to emphasize", "Projects, results and skills you want every application to lead with"),
    ("avoid", "What to avoid", "Companies or industries to skip, claims never to make, titles to never use"),
    ("other", "Anything else the agent should know", "Notice period, start date, preferred file naming, tone"),
]
FEED_LABELS = {"remoteok": "Remote OK", "remotive": "Remotive", "hn_whos_hiring": "Hacker News: Who's hiring",
               "themuse": "The Muse", "himalayas": "Himalayas (remote)", "jobicy": "Jobicy (remote)",
               "adzuna": "Adzuna (big US aggregator, free key)", "usajobs": "USAJOBS (federal, free key)"}
ATS_HOSTS = [  # careers-page URL -> (ats, slug)
    (r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)", "greenhouse"),
    (r"jobs(?:\.eu)?\.lever\.co/([\w.-]+)", "lever"),
    (r"jobs\.ashbyhq\.com/([\w.%-]+)", "ashby"),
    (r"apply\.workable\.com/([\w-]+)", "workable"),
    (r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", "smartrecruiters"),
]
REQUIRED = ("profile", "interests", "resume", "agent")


def _yaml(p: Path) -> dict:
    try:
        return yaml.safe_load(p.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _lines(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[\n,]", text or "") if x.strip()]


def materials(root: Path) -> Path:
    return root / "materials"


def base_resume(root: Path) -> Path | None:
    """The resume to tailor from: '... Resume - Base.docx', else any .docx with 'resume' in its name."""
    m = materials(root)
    if not m.is_dir():
        return None
    docs = sorted(m.glob("*.docx"))
    for d in docs:
        if re.search(r"resume.*base", d.stem, re.I):
            return d
    return next((d for d in docs if "resume" in d.stem.lower()), None)


def agent_ready(prefs=None) -> dict:
    claude, codex = find_cli("claude"), find_cli("codex")
    if prefs is not None and prefs.data.get("daily_via") == "openrouter":
        cli = prefs.data.get("daily_agent", "claude")
        has_cli = bool(claude if cli == "claude" else codex)
        key = bool(prefs.key("OPENROUTER_API_KEY"))
        return {"done": has_cli and key, "claude": bool(claude), "codex": bool(codex), "who": [],
                "note": ("runs on your OpenRouter key" if has_cli and key else
                         "OpenRouter picked, but no key yet" if has_cli else f"{cli} not installed")}
    home = Path.home()
    claude_in = (home / ".claude" / ".credentials.json").exists() or (home / ".claude.json").exists()
    codex_in = (home / ".codex" / "auth.json").exists()
    who = [n for n, ok in (("Claude Code", claude and claude_in), ("Codex", codex and codex_in)) if ok]
    return {"done": bool(who), "claude": bool(claude), "codex": bool(codex), "who": who,
            "note": f"{' and '.join(who)} signed in" if who else
                    ("installed, not signed in yet" if claude or codex else "no agent CLI found")}


def _prefs(settings):
    from .prefs import Prefs
    try:
        return Prefs(settings.data_dir, settings.raw)
    except Exception:
        return None


def status(settings, environ: dict) -> dict:
    root = settings.root
    prof = _yaml(root / "profile.yaml")
    cfg = root / "config.yaml"
    titles = ((settings.raw.get("search") or {}).get("title_keywords") or []) if cfg.exists() else []
    resume = base_resume(root)
    about = materials(root) / "context"
    has_about = (root / "CLAUDE.local.md").exists() or (about.is_dir() and any(about.glob("*.md")))
    steps = {
        # Done once it's yours: a real "Jane" counts; the untouched example (Jane Doe, jane.doe@example.com) doesn't.
        "profile": {"done": bool(prof.get("first_name")) and (prof.get("email") or "").lower() != "jane.doe@example.com",
                    "note": f"{prof.get('first_name', '')} {prof.get('last_name', '')}".strip() or "not set"},
        "interests": {"done": cfg.exists() and bool(titles),
                      "note": f"{len(titles)} titles" if cfg.exists() and titles else "not set"},
        "resume": {"done": bool(resume), "note": resume.name if resume else "not uploaded"},
        "about": {"done": has_about, "note": "written" if has_about else "optional, but it makes answers much better"},
        "gmail": {"done": bool(environ.get("GMAIL_USER") and environ.get("GMAIL_APP_PASSWORD")),
                  "note": environ.get("GMAIL_USER") or "optional: job alerts, replies and the morning brief"},
        "agent": agent_ready(_prefs(settings)),
    }
    left = [k for k in REQUIRED if not steps[k]["done"]]
    return {"steps": steps, "left": left, "ready": not left, "fresh": bool(settings.raw.get("_from_example"))}


# ---- profile.yaml ---------------------------------------------------------------------------------

def load_profile(root: Path) -> dict:
    p = _yaml(root / "profile.yaml")
    return p if p else _yaml(root / "profile.example.yaml")


def standing_values(prof: dict) -> dict:
    """{key: value} of your saved standing answers, for the Setup form."""
    out = {}
    for k, _, match in STANDING:
        for r in prof.get("standing_answers") or []:
            if r.get("match") == match:
                out[k] = r.get("value", "")
    return out


def save_profile(settings, form: dict) -> dict:
    root = settings.root
    prof = load_profile(root)
    is_example = not (root / "profile.yaml").exists()
    for k, _ in PROFILE_FIELDS:
        prof[k] = str(form.get(k) or "").strip()[:200]
    for k, _ in YES_NO:
        if form.get(k) in ("Yes", "No"):
            prof[k] = form[k]
    if "standing_form" in form:
        rules = []
        for k, _, match in STANDING:
            v = "yes" if k == "consent" and form.get(f"stand::{k}") else (
                "" if k == "consent" else str(form.get(f"stand::{k}") or "").strip()[:120])
            if v:
                rules.append({"match": match, "value": v})
        prof["standing_answers"] = rules
    pay = re.sub(r"[^\d]", "", str(form.get("salary_expectation") or ""))
    prof["salary_expectation"] = pay
    if is_example:
        prof["how_did_you_hear"] = prof.get("how_did_you_hear") or "Company website"
    full = f"{prof['first_name']} {prof['last_name']}".strip()
    for r in prof.get("rules") or []:
        if "full name" in str(r.get("match", "")) and "value" in r:
            r["value"] = full  # the example ships "Jane Doe"
    if prof.get("name_pronunciation") and not any("pronunc" in str(r.get("match", "")) for r in prof.get("rules") or []):
        prof.setdefault("rules", []).append({"match": "pronunc", "key": "name_pronunciation"})
    head = "# Written by the dashboard's Setup page. Edit here or there.\n"
    (root / "profile.yaml").write_text(head + yaml.safe_dump(prof, sort_keys=False, allow_unicode=True))
    settings.profile.clear()
    settings.profile.update(prof)
    return prof


# ---- config.yaml ----------------------------------------------------------------------------------

def parse_board(line: str) -> tuple[str, str] | None:
    """'greenhouse gitlab', 'lever:netflix' or a careers-page URL -> (ats, slug)."""
    from .finder import FETCHERS
    s = line.strip()
    for pat, ats in ATS_HOSTS:
        if m := re.search(pat, s, re.I):
            return ats, m.group(1).rstrip("/")
    if m := re.fullmatch(r"(\w+)[\s:/]+([\w.-]+)", s):
        if m.group(1).lower() in FETCHERS:
            return m.group(1).lower(), m.group(2)
    return None


def load_config(root: Path) -> dict:
    c = _yaml(root / "config.yaml")
    return c if c else _yaml(root / "config.example.yaml")


def save_interests(settings, form: dict) -> dict:
    """Returns {"bad": [lines it couldn't read], "missing_keys": [keyed sites turned on without a key]}."""
    from .sources import EXTRA
    root = settings.root
    cfg = load_config(root)
    cfg.pop("_from_example", None)
    search = cfg.setdefault("search", {})
    search["title_keywords"] = [t.lower() for t in _lines(form.get("titles", ""))][:40]
    search["exclude_keywords"] = [t.lower() for t in _lines(form.get("exclude", ""))][:40]
    search["us_only"] = bool(form.get("us_only"))
    boards, bad = [], []
    for line in str(form.get("companies") or "").splitlines():
        if not line.strip():
            continue
        b = parse_board(line)
        if b and b not in boards:
            boards.append(b)
        elif not b:
            bad.append(line.strip()[:120])
    cfg["boards"] = [{"ats": a, "slug": s} for a, s in boards[:300]]
    cfg["feeds"] = [f for f in FEED_LABELS if form.get(f"feed::{f}")]
    feeds = []
    for line in str(form.get("rss") or "").splitlines():  # "Name | URL" or just the URL
        name, _, url = line.rpartition("|") if "|" in line else ("", "", line)
        url = url.strip()
        if url.startswith(("http://", "https://")) and url not in [f["url"] for f in feeds]:
            feeds.append({"name": name.strip()[:80], "url": url[:500]} if name.strip() else {"url": url[:500]})
        elif line.strip():
            bad.append(line.strip()[:120])
    cfg["rss_feeds"] = feeds[:50]
    import os
    names = {"ADZUNA_APP_ID": "app ID", "ADZUNA_APP_KEY": "app key", "USAJOBS_API_KEY": "key",
             "USAJOBS_EMAIL": "sign-up email"}
    missing = []
    for f in cfg["feeds"]:
        if f in EXTRA and EXTRA[f][2]:
            lack = [names.get(k, k) for k in EXTRA[f][2] if not (str(form.get(k) or "").strip() or os.environ.get(k))]
            if lack:  # say which field is empty: USAJOBS needs the sign-up email as well as the key
                missing.append(f"{EXTRA[f][1].split(' (')[0]} (needs its {' and '.join(lack)})")
    ws = cfg.setdefault("work_search", {"label": "Work search", "weekly_minimum": 3})
    if "ws_state" in form:
        from .web import state_rules
        code = str(form.get("ws_state") or "").upper()
        if code in state_rules():
            ws["state"] = code
        else:
            ws.pop("state", None)
    if form.get("ws_label"):
        ws["label"] = str(form["ws_label"]).strip()[:40]
    try:
        ws["weekly_minimum"] = max(0, min(50, int(form.get("ws_min") or ws.get("weekly_minimum", 3))))
    except ValueError:
        pass
    head = ("# Written by the dashboard's Setup page. Edit here or there.\n"
            "# More boards can live in boards.yaml (`autoapply board add ATS SLUG`).\n")
    (root / "config.yaml").write_text(head + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    settings.raw.clear()
    settings.raw.update(cfg)
    return {"bad": bad, "missing_keys": missing}


# ---- resume ---------------------------------------------------------------------------------------

def _is_docx(data: bytes) -> bool:
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "word/document.xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


def save_resume(root: Path, last_name: str, docx: bytes | None, pdf: bytes | None) -> dict:
    """Saves the base resume. Without a PDF, LibreOffice makes one when it's installed."""
    m = materials(root)
    m.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w .'-]", "", last_name or "").strip() or "My"
    stem = f"{name} Resume - Base"
    out = {"docx": None, "pdf": None, "error": ""}
    if docx is not None:
        if not _is_docx(docx):
            return {**out, "error": "That isn't a Word .docx file. In Google Docs: File > Download > Microsoft Word."}
        old = base_resume(root)
        if old and old.name != f"{stem}.docx":
            old.rename(old.with_name(old.stem + f".old-{datetime.now():%Y%m%d%H%M}.docx"))
        (m / f"{stem}.docx").write_bytes(docx)
        out["docx"] = f"{stem}.docx"
    if pdf is not None:
        if not pdf.startswith(b"%PDF"):
            return {**out, "error": "The second file isn't a PDF."}
        (m / f"{stem}.pdf").write_bytes(pdf)
        out["pdf"] = f"{stem}.pdf"
    elif docx is not None:
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice:
            try:
                # A user id with no passwd entry (Docker with APP_UID=501 on a Mac) has no usable home, and
                # LibreOffice then quits on "User installation could not be completed": give it its own profile dir.
                lo_profile = Path(tempfile.gettempdir()) / f"lo-profile-{os.getuid()}"
                subprocess.run([soffice, f"-env:UserInstallation={lo_profile.as_uri()}", "--headless", "--convert-to", "pdf",
                                "--outdir", str(m), str(m / f"{stem}.docx")],
                               capture_output=True, timeout=180, check=True)
                out["pdf"] = f"{stem}.pdf" if (m / f"{stem}.pdf").exists() else None
            except (subprocess.SubprocessError, OSError):
                pass
    return out


def name_placeholder_resume(root: Path, last_name: str) -> str | None:
    """A resume uploaded before the contact details is saved as 'My Resume - Base'; give it the last name."""
    last = re.sub(r"[^\w .'-]", "", last_name or "").strip()
    m = materials(root)
    src = m / "My Resume - Base.docx"
    if not last or last == "My" or not src.exists() or (m / f"{last} Resume - Base.docx").exists():
        return None
    for ext in (".docx", ".pdf"):
        f = m / f"My Resume - Base{ext}"
        if f.exists():
            f.rename(m / f"{last} Resume - Base{ext}")
    return f"{last} Resume - Base.docx"


def resume_contact(path: Path | None) -> dict:
    """Name, email, phone and links from the top of a resume, to prefill the contact form."""
    if not path:
        return {}
    try:
        from docx import Document
        d = Document(str(path))
    except Exception:
        return {}
    texts = [p.text.strip() for p in d.paragraphs if p.text.strip()][:12]
    for t in d.tables[:2]:
        texts += [c.text.strip() for row in t.rows for c in row.cells if c.text.strip()][:12]
    blob = "\n".join(texts)
    out = {}
    if m := re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", blob):
        out["email"] = m.group(0)
    if m := re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", blob):
        out["phone"] = m.group(0)
    if m := re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?", blob, re.I):
        out["linkedin"] = m.group(0) if m.group(0).startswith("http") else "https://" + m.group(0)
    if m := re.search(r"(?:https?://)?github\.com/[\w-]+", blob, re.I):
        out["github"] = m.group(0) if m.group(0).startswith("http") else "https://" + m.group(0)
    for t in texts[:3]:
        words = t.split()
        if 2 <= len(words) <= 4 and all(w[:1].isupper() for w in words) and not re.search(r"[@\d|]", t):
            out["first_name"], out["last_name"] = words[0].title(), words[-1].title()
            break
    return out


# ---- about you ------------------------------------------------------------------------------------

def about_path(root: Path) -> Path:
    return materials(root) / "context" / "setup.md"


def load_about(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / "setup.json").read_text()).get("about", {})
    except (OSError, ValueError):
        return {}


def save_about(root: Path, data_dir: Path, form: dict):
    about = {k: str(form.get(k) or "").strip()[:4000] for k, _, _ in ABOUT_FIELDS}
    p = data_dir / "setup.json"
    try:
        saved = json.loads(p.read_text())
    except (OSError, ValueError):
        saved = {}
    saved["about"] = about
    p.write_text(json.dumps(saved, indent=1))
    md = ["# About me (from the Setup page)", "",
          "Facts the agent uses when it ranks jobs, tailors materials and answers questions. "
          "Never invent anything beyond these and the resume.", ""]
    for k, label, _ in ABOUT_FIELDS:
        if about[k]:
            md += [f"## {label}", "", about[k], ""]
    out = about_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md))


# ---- gmail ----------------------------------------------------------------------------------------

def test_gmail(user: str, pw: str) -> str:
    """'' when the login works, else a short reason."""
    import imaplib
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", timeout=20) as m:
            m.login(user, pw)
        return ""
    except imaplib.IMAP4.error as e:
        msg = str(e)
        return ("Gmail refused the login. Use an app password (Google Account > Security > App passwords), "
                "not your normal password.") if "AUTH" in msg.upper() or "credentials" in msg.lower() else msg[:200]
    except OSError as e:
        return f"couldn't reach Gmail: {e}"[:200]
