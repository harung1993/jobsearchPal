"""How each application went out, and how often `autoapply-finish` ran.

The server can't see you press Submit in your own Chrome, so it counts what it can: each time the command fetched a
job's files (a "run"); when the command saw the site's confirmation page ("auto"); and which button you pressed
("I sent it with the command" or "I applied by hand"). A job the command ran for, then marked applied by its
confirmation email, counts as sent with the command. A command mark can be undone ("undo"), which puts the job back.
"""
from __future__ import annotations

import json
import time

SCHEMA = """create table if not exists finish_log (
  job_id text not null,
  at text not null,
  kind text not null,  -- run: the command fetched this job's files; auto: it saw the confirmation page;
                       -- command / hand: how you said you sent it; undo: a command mark taken back
  detail text          -- JSON for a mark: the status and lead status before it, the confirmation seen
);
create index if not exists finish_log_job on finish_log (job_id);"""

HOW = ("app", "command", "hand", "elsewhere")
LABELS = {"app": "Sent by the app", "command": "With the command", "hand": "By hand", "elsewhere": "Logged from elsewhere"}


def ensure(db):
    db.conn.executescript(SCHEMA)
    if "detail" not in {r[1] for r in db.conn.execute("pragma table_info(finish_log)")}:
        db.conn.execute("alter table finish_log add column detail text")  # first version (PR #35) had none
        db.conn.commit()


def _add(db, job_id: str, kind: str, detail: dict | None = None):
    ensure(db)
    db.conn.execute("insert into finish_log (job_id, at, kind, detail) values (?, ?, ?, ?)",
                    (job_id, time.strftime("%Y-%m-%d %H:%M"), kind, json.dumps(detail) if detail else None))
    db.conn.commit()


def record_run(db, job_id: str):
    """The command fetched this job's files."""
    _add(db, job_id, "run")


def mark(db, job_id: str, how: str, before: dict | None = None, confirmation: str = ""):
    """How it was sent: "command" or "hand" (your button), or "auto" (the command saw the confirmation page).
    before: {"status", "lead"} as they were, so a command mark can be undone. The latest mark wins."""
    if how not in ("command", "hand", "auto"):
        raise ValueError(how)
    _add(db, job_id, how, {**(before or {}), **({"confirmation": confirmation[:200]} if confirmation else {})})


def last_mark(db, job_id: str) -> dict | None:
    """The mark that stands now ({"kind", "at", "detail"}), with undone ones taken off; None if there is none."""
    ensure(db)
    marks = []
    for kind, at, detail in db.conn.execute(
            "select kind, at, detail from finish_log where job_id = ? and kind in ('command', 'hand', 'auto', 'undo') "
            "order by rowid", (job_id,)):
        if kind == "undo":
            if marks:
                marks.pop()
        else:
            marks.append({"kind": kind, "at": at, "detail": json.loads(detail) if detail else {}})
    return marks[-1] if marks else None


def undo(db, job_id: str) -> dict | None:
    """Takes back a command mark ("auto" or "command"). Returns the mark undone, or None if there wasn't one."""
    m = last_mark(db, job_id)
    if not m or m["kind"] not in ("auto", "command"):
        return None
    _add(db, job_id, "undo")
    return m


def ran(db, job_id: str) -> bool:
    ensure(db)
    return db.conn.execute("select 1 from finish_log where job_id = ? and kind = 'run' limit 1", (job_id,)).fetchone() is not None


def run_count(db) -> int:
    ensure(db)
    return db.conn.execute("select count(*) from finish_log where kind = 'run'").fetchone()[0]


def _by_job(db) -> dict[str, list[str]]:
    """Each job's kinds in order, with undone marks taken off (an "undo" removes the mark before it)."""
    ensure(db)
    out: dict[str, list[str]] = {}
    for job_id, kind in db.conn.execute("select job_id, kind from finish_log order by rowid"):
        kinds = out.setdefault(job_id, [])
        if kind == "undo":
            for i in range(len(kinds) - 1, -1, -1):
                if kinds[i] in ("command", "hand", "auto"):
                    del kinds[i]
                    break
        else:
            kinds.append(kind)
    return out


def how_sent(db, job: dict, _log: dict | None = None) -> str:
    """app | command | hand | elsewhere, for a submitted job."""
    kinds = (_by_job(db) if _log is None else _log).get(job["id"], [])
    said = [k for k in kinds if k in ("command", "hand", "auto")]
    if said:
        return "command" if said[-1] == "auto" else said[-1]
    try:
        if json.loads(job.get("report_json") or "{}").get("submitted"):
            return "app"
    except ValueError:
        pass
    if "run" in kinds:
        return "command"  # the command ran, then the confirmation email marked it applied
    if job["id"].startswith(("tracker:", "manual:")):
        return "elsewhere"
    return "hand"


def split(db, applied: list[dict]) -> list[tuple[str, int]]:
    """(label, count) for each way an application went out, in a fixed order."""
    log = _by_job(db)
    counts = {h: 0 for h in HOW}
    for j in applied:
        counts[how_sent(db, j, log)] += 1
    return [(LABELS[h], counts[h]) for h in HOW]
