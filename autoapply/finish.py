"""How each application went out, and how often `autoapply-finish` ran.

The server can't see you press Submit in your own Chrome, so it counts what it can: each time the command fetched a
job's files (a "run"), and which button you pressed afterwards ("I sent it with the command" or "I applied by hand").
A job the command ran for, then marked applied by its confirmation email, counts as sent with the command.
"""
from __future__ import annotations

import json
import time

SCHEMA = """create table if not exists finish_log (
  job_id text not null,
  at text not null,
  kind text not null  -- run: the command fetched this job's files; command / hand: how you said you sent it
);
create index if not exists finish_log_job on finish_log (job_id);"""

HOW = ("app", "command", "hand", "elsewhere")
LABELS = {"app": "Sent by the app", "command": "With the command", "hand": "By hand", "elsewhere": "Logged from elsewhere"}


def ensure(db):
    db.conn.executescript(SCHEMA)


def _add(db, job_id: str, kind: str):
    ensure(db)
    db.conn.execute("insert into finish_log (job_id, at, kind) values (?, ?, ?)",
                    (job_id, time.strftime("%Y-%m-%d %H:%M"), kind))
    db.conn.commit()


def record_run(db, job_id: str):
    """The command fetched this job's files."""
    _add(db, job_id, "run")


def mark(db, job_id: str, how: str):
    """You said how you sent it: "command" or "hand". The latest one wins."""
    if how not in ("command", "hand"):
        raise ValueError(how)
    _add(db, job_id, how)


def ran(db, job_id: str) -> bool:
    ensure(db)
    return db.conn.execute("select 1 from finish_log where job_id = ? and kind = 'run' limit 1", (job_id,)).fetchone() is not None


def run_count(db) -> int:
    ensure(db)
    return db.conn.execute("select count(*) from finish_log where kind = 'run'").fetchone()[0]


def _by_job(db) -> dict[str, list[str]]:
    ensure(db)
    out: dict[str, list[str]] = {}
    for job_id, kind in db.conn.execute("select job_id, kind from finish_log order by rowid"):
        out.setdefault(job_id, []).append(kind)
    return out


def how_sent(db, job: dict, _log: dict | None = None) -> str:
    """app | command | hand | elsewhere, for a submitted job."""
    kinds = (_by_job(db) if _log is None else _log).get(job["id"], [])
    said = [k for k in kinds if k in ("command", "hand")]
    if said:
        return said[-1]
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
