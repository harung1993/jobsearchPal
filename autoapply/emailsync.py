"""Turns ATS and recruiter emails into events (confirmed, interview, rejected, offer, recruiter) and
files a copy of each one under data/proof/<week>/ so there is a record if a benefits office asks."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from . import alerts
from .db import DB

ATS_SENDERS = [
    "greenhouse.io", "greenhouse-mail.io", "lever.co", "ashbyhq.com", "myworkday.com", "myworkdayjobs.com",
    "rippling.com", "workablemail.com", "smartrecruiters.com", "kula.ai", "clearcompany.com", "eightfold.ai",
    "icims.com", "jobvite.com", "bamboohr.com",
]

# Checked in order: a rejection often also says "thank you for applying".
RULES = [
    ("offer", r"pleased to (extend|offer)|offer letter|formal offer"),
    ("rejected", r"unfortunately|not (to )?(be )?mov(e|ing) forward|other candidates|decided to (pursue|proceed)"
                 r"|not (been )?selected|position (has been|was) filled|no longer (being )?consider|won.t be moving"
                 r"|move forward with (another|other)|another candidate|regret to inform|decided not to"
                 r"|will not be (moving|proceeding)|not (be )?(a|the right) (match|fit) at this time"),
    ("interview", r"schedule (a|an|your|time)|interview (with|invitation|availability)|invite you to"
                  r"|availability for (a|an)|next step(s)? (is|in our|would be)|phone screen|recruiter (call|screen)"),
    ("confirmed", r"thank(s| you) for (applying|your application|your interest)|application (was |has been )?"
                  r"(received|submitted)|we('ve| have) received your application|received your application"),
]
# "We'll schedule interviews once we've reviewed resumes" is an acknowledgement, not an invite.
NOT_YET = re.compile(r"if (there is|there's|we (see|find)) (a|an) (fit|match)|if (your|you|we)\b[^.]{0,80}(qualif|fit|match|move forward)"
                     r"|once we('ve| have)? (been able to )?review|review (all|submitted|your) (applications|resumes|application|resume)"
                     r"|(plan|hope) to schedule interviews|will (keep you posted|be in touch)", re.I)
RANK = {"confirmed": 1, "interview": 2, "rejected": 3, "offer": 4}

# Recruiter outreach arrives from anyone, so it's found by Gmail search rather than by sender.
RECRUITER_QUERIES = [
    '-category:promotions -category:social -from:jobalerts-noreply@linkedin.com '
    '(recruiter OR "talent acquisition" OR "right to represent" OR RTR OR "your background" '
    'OR "your profile" OR "your experience" OR "InMail" OR staffing) -subject:"Job search brief"',
]
# The same search for inboxes that aren't Gmail (no Gmail search language there): plain words, matched anywhere.
# Broader than the Gmail query; is_recruiter() still decides what counts.
RECRUITER_WORDS = ["recruiter", "talent acquisition", "right to represent", "your background", "your profile", "InMail"]
RECRUITER = re.compile(
    r"recruit|talent acquisition|staffing|right to represent|\brtr\b|inmail|your (background|profile|experience)"
    r"|(great|exciting|new) (opportunity|role)|reach(ing)? out|open to (new )?(roles|opportunities)", re.I)
NOT_RECRUITER = re.compile(r"newsletter|unsubscribe from this list|webinar|job alert|jobs you may be interested"
                           r"|proxy ?vote|shareholder|important information|account statement|linkedin premium|premium (free )?trial", re.I)
# Account emails from an ATS that aren't news about the application.
NOT_STATUS = re.compile(r"sign-?in link|verification code|verify your (email|account)|reset your password"
                        r"|security code|confirm you.re a human", re.I)


# Recruiters write as people. Alerts, banks and marketing come from these.
BULK_SENDER = re.compile(r"no-?reply|donotreply|do-not-reply|alert|notification|newsletter|marketing|news@|info@"
                         r"|indeed|glassdoor|ziprecruiter|dice\.com|monster\.com|wellfound|builtin"
                         r"|americanexpress|aexp|bank|chase\.com|fidelity|vanguard|schwab|proxyvote|paypal|venmo", re.I)
# LinkedIn relays real recruiter messages (InMail, messages) but everything else from it is bulk.
LINKEDIN_PERSON = re.compile(r"inmail|hit-reply|messaging|messages-noreply", re.I)


def is_recruiter(name: str, addr: str, subject: str, text: str) -> bool:
    a = (addr or "").lower()
    if "linkedin.com" in a:
        if not LINKEDIN_PERSON.search(a) or re.search(r"premium|job alert|jobs? (for|you)", subject, re.I):
            return False
    elif BULK_SENDER.search(a) or BULK_SENDER.search(name or ""):
        return False
    blob = f"{name} {subject}\n{text[:3000]}"
    return bool(RECRUITER.search(blob)) and not NOT_RECRUITER.search(f"{subject}\n{text[:1500]}")


def week_dir(proof_root: Path, when: datetime) -> Path:
    from .stats import week_start
    return proof_root / week_start(when.date()).isoformat()


def save_proof(proof_root: Path | None, when: datetime, label: str, kind: str, raw: bytes, text: str, headers: str) -> str | None:
    """Writes the original .eml plus a readable .txt; returns the .eml path."""
    if not (proof_root and raw):
        return None
    d = week_dir(proof_root, when)
    d.mkdir(parents=True, exist_ok=True)
    stem = f"{when:%Y-%m-%d_%H%M}_{re.sub(r'[^A-Za-z0-9]+', '-', label).strip('-')[:40] or 'unknown'}_{kind}"
    (d / f"{stem}.eml").write_bytes(raw)
    (d / f"{stem}.txt").write_text(headers + "\n\n" + text)
    return str(d / f"{stem}.eml")


def classify(subject: str, text: str) -> str | None:
    blob = f"{subject}\n{text[:4000]}"
    if NOT_STATUS.search(subject):
        return None
    for kind, pat in RULES:
        if re.search(pat, blob, re.I):
            if kind == "interview" and NOT_YET.search(blob):
                return "confirmed"
            return kind
    return None


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def match_job(jobs: list[dict], name: str, addr: str, subject: str, text: str) -> dict | None:
    """The applied job whose company shows up in the sender, subject or body (longest name wins)."""
    hay = _key(f"{name} {addr} {subject} {text[:3000]}")
    best = None
    for j in jobs:
        k = _key(j["company"])
        if len(k) >= 3 and k in hay and (best is None or len(k) > len(_key(best["company"]))):
            best = j
    return best


KINDS = ["confirmed", "interview", "rejected", "offer", "recruiter", "agency", "ignored"]


def is_own(addr: str) -> bool:
    """Mail from one of your own addresses: the main inbox, extra inboxes, and OWN_ADDRESSES (comma-separated)."""
    from . import mailboxes
    return (addr or "").strip().lower() in mailboxes.own_addresses()


def apply_event(db: DB, jobs: list[dict], msg_id: str, name: str, addr: str, subject: str, when, text: str,
                raw: bytes = b"", proof_root: Path | None = None) -> str | None:
    """Files a candidate email as unreviewed, with the keyword rules' guess. Nothing counts (stats, outcomes,
    the work-search log) until review_event settles it, either from the model (classify.py) or from you."""
    old = db.get_event(msg_id)
    if is_own(addr):
        # Your own replies aren't a new contact: they're read from Sent mail for reminders, and counting them
        # here doubled recruiter contacts in the work-search log. Drop any already filed, unless you set it by hand.
        if old and not old["manual"]:
            db.delete_event(msg_id)
        return None
    if old and old["reviewed"]:
        return None  # settled already; only a --rebuild (or you, on the Emails page) changes it
    from . import benefits
    if benefits.is_agency(addr, subject, text):
        # A letter from the unemployment agency or a career center: a to-do, not a job reply. Filed as settled.
        if not old:
            proof = save_proof(proof_root, when, name or addr, "agency", raw, text,
                               f"From: {name} <{addr}>\nDate: {when:%Y-%m-%d %H:%M}\nSubject: {subject}")
            db.add_event({"id": msg_id, "job_id": None, "kind": "agency", "guess": "agency",
                          "at": when.strftime("%Y-%m-%d %H:%M"), "sender": f"{name} <{addr}>" if name else addr,
                          "subject": subject[:200], "proof": proof, "body": text[:4000], "reviewed": 1})
        return "agency"
    from_ats = any(d in addr.lower() for d in ATS_SENDERS)
    if subject.startswith("Job search brief") or NOT_STATUS.search(subject):
        guess, keep = None, False  # our own brief quotes other emails; sign-in links and codes aren't news
    else:
        guess = classify(subject, text)
        recruiter = is_recruiter(name, addr, subject, text)
        if recruiter and not from_ats and guess not in ("confirmed", "rejected", "offer"):
            guess = "recruiter"
        job = match_job(jobs, name, addr, subject, text)
        # Worth a look: anything from an ATS, recruiter-looking mail, or status words about one of your applications.
        keep = from_ats or recruiter or bool(guess and job)
    if not keep:
        if old:
            db.delete_event(msg_id)
        return None
    if old:
        return None  # already waiting for review
    job = match_job(jobs, name, addr, subject, text)
    proof = save_proof(proof_root, when, job["company"] if job else (name or addr), guess or "email", raw, text,
                       f"From: {name} <{addr}>\nDate: {when:%Y-%m-%d %H:%M}\nSubject: {subject}")
    db.add_event({"id": msg_id, "job_id": job["id"] if job else None, "kind": guess or "unsure", "guess": guess,
                  "at": when.strftime("%Y-%m-%d %H:%M"), "sender": f"{name} <{addr}>" if name else addr,
                  "subject": subject[:200], "proof": proof, "body": text[:4000], "reviewed": 0})
    return guess or "unsure"


def review_event(db: DB, event_id: str, kind: str, job_id: str | None = "", manual: bool = False) -> dict:
    """Settles an email's kind (and optionally which application it's about), then updates that job's outcome.
    job_id "" keeps the current match; None clears it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    ev = db.get_event(event_id)
    if not ev:
        raise KeyError(event_id)
    if ev["manual"] and not manual:
        return ev  # your correction wins over the model
    old_job, old_kind = ev["job_id"], ev["kind"]
    new_job = old_job if job_id == "" else job_id
    if new_job and not db.get(new_job):
        raise KeyError(new_job)
    db.set_event(event_id, kind=kind, job_id=new_job, reviewed=1, manual=int(manual or ev["manual"]))
    if kind == "ignored" and ev["proof"]:
        _drop_proof(ev["proof"])  # not a job email, so it doesn't belong in the work-search proof
        db.set_event(event_id, proof=None)
    if old_job and (old_job != new_job or old_kind != kind):
        _reset_outcome(db, old_job, {old_kind})
    if new_job and kind in RANK:
        cur = db.get(new_job)
        at = ev["at"]
        if kind == "confirmed" and cur["status"] == "filled":
            # Submit was pressed but the page never confirmed; the ATS email settles it.
            db.update(new_job, status="submitted", submitted_at=at, error=None)
        if RANK[kind] >= RANK.get(cur.get("outcome") or "", 0):
            db.update(new_job, outcome=kind, outcome_at=at)
    return db.get_event(event_id)


def _drop_proof(proof: str | None):
    for p in (proof, proof[:-4] + ".txt" if proof and proof.endswith(".eml") else None):
        if p:
            Path(p).unlink(missing_ok=True)


def _reset_outcome(db: DB, job_id: str, dropped: set[str]):
    """After an event is removed or changed, an outcome that only it supported goes back to the best one left."""
    cur = db.get(job_id)
    if not cur or (cur.get("outcome") or "") not in dropped:
        return
    left = [e for e in db.events() if e["job_id"] == job_id and e["kind"] in RANK]
    if any(e["kind"] == cur["outcome"] for e in left):
        return
    best = max(left, key=lambda e: (RANK[e["kind"]], e["at"] or ""), default=None)
    db.update(job_id, outcome=best["kind"] if best else None, outcome_at=best["at"] if best else None)


def rebuild(db: DB, days: int) -> int:
    """Forgets email events from the last N days (and their proof copies) so the next sync refiles them.
    Your own corrections from the Emails page are kept."""
    from datetime import timedelta
    cut = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    n = 0
    dropped: dict[str, set[str]] = {}
    for e in db.events(all=True):
        if e["kind"] != "applied" and not e["manual"] and (e["at"] or "") >= cut:
            if e["job_id"]:
                dropped.setdefault(e["job_id"], set()).add(e["kind"])
            _drop_proof(e["proof"])
            db.delete_event(e["id"])
            n += 1
    for job_id, kinds in dropped.items():
        _reset_outcome(db, job_id, kinds)
    return n


def sync_sent(db: DB, days: int = 60) -> int:
    """Headers of mail you sent, so reminders know what you've already answered."""
    n = 0
    for msg_id, when, to, subject, irt in alerts.sent_mail(days):
        db.add_sent(msg_id, when.strftime("%Y-%m-%d %H:%M"), to, subject, irt)
        n += 1
    return n


def sync(db: DB, days: int = 60, extra_senders: list[str] | None = None, proof_root: Path | None = None) -> dict:
    jobs = db.by_status("submitted", "filled")
    counts: dict[str, int] = {}
    try:
        sync_sent(db, days)
    except Exception:  # reminders just get less precise; the reply sync still runs
        pass
    from .benefits import AGENCY_QUERIES, AGENCY_SEARCH_WORDS
    for msg in alerts.messages(days, ATS_SENDERS + (extra_senders or []), gmail_queries=RECRUITER_QUERIES + AGENCY_QUERIES,
                              words=RECRUITER_WORDS + AGENCY_SEARCH_WORDS):
        kind = apply_event(db, jobs, *msg, proof_root=proof_root)
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return counts
