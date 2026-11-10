"""SQLite store for jobs and their pipeline state."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
create table if not exists jobs (
  id text primary key,            -- '<ats>:<slug>:<job id>'
  ats text, company text, title text, location text, url text, apply_url text,
  description text,
  found_at text default current_timestamp,
  score integer, score_reason text,
  status text default 'new',       -- new, skipped, prepped, filled, submitted, failed
  plan_json text,                  -- answers + file paths; editable on the review page
  report_json text,                -- last fill/submit report
  screenshot text, error text,
  submitted_at text,
  pay text,                        -- posted range, free text
  outcome text,                    -- confirmed, interview, rejected, offer (latest email signal)
  outcome_at text
);
create table if not exists events (
  id text primary key,             -- email Message-ID, so a resync never double-counts
  job_id text, kind text,          -- confirmed, interview, rejected, offer
  at text, sender text, subject text,
  proof text                       -- saved .eml / screenshot path, for DUA records
);
"""

RUNS_SCHEMA = """
create table if not exists runs (
  kind text primary key,           -- find, sync-email, fill, daily
  at text, ok integer, summary text
);
create table if not exists sent (    -- mail you sent (headers only), to tell what you've answered
  id text primary key, at text, to_addrs text, subject text, in_reply_to text
);
create table if not exists nudge_state ( -- reminders you marked done or snoozed
  key text primary key, state text, until text
);
create table if not exists usage (   -- one row per call to an email-sorting model source
  at text default (datetime('now', 'localtime')), source text, model text,
  emails integer, sorted integer, cost real, ms integer, error text
);
"""

# Columns added after v0.1; ALTERed into older databases on open.
MIGRATIONS = {"pay": "text", "outcome": "text", "outcome_at": "text", "skills_json": "text"}

STATUSES = ["new", "skipped", "prepped", "filled", "submitted", "failed"]  # prepped: files and answers, no form filled


class DB:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.executescript(RUNS_SCHEMA)
        have = {r[1] for r in self.conn.execute("pragma table_info(jobs)")}
        for col, typ in MIGRATIONS.items():
            if col not in have:
                self.conn.execute(f"alter table jobs add column {col} {typ}")
        ecols = {r[1] for r in self.conn.execute("pragma table_info(events)")}
        if "proof" not in ecols:
            self.conn.execute("alter table events add column proof text")
        # guess: what the keyword rules said; reviewed: a model or you settled the kind; manual: you did.
        for col, typ in {"body": "text", "guess": "text", "reviewed": "integer default 0", "manual": "integer default 0",
                         "sorted_by": "text", "confidence": "real"}.items():
            if col not in ecols:
                self.conn.execute(f"alter table events add column {col} {typ}")
        self.conn.execute("update events set reviewed = 1 where kind = 'applied'")
        ucols = {r[1] for r in self.conn.execute("pragma table_info(usage)")}
        for col in ("est", "tokens"):  # est: what it would cost at API prices (subscription runs); tokens in + out
            if col not in ucols:
                self.conn.execute(f"alter table usage add column {col} {'real' if col == 'est' else 'integer'} default 0")
        self.conn.commit()

    def upsert_job(self, job: dict) -> bool:
        """Insert if unseen. Returns True when the job is new."""
        cur = self.conn.execute(
            "insert or ignore into jobs (id, ats, company, title, location, url, apply_url, description)"
            " values (:id, :ats, :company, :title, :location, :url, :apply_url, :description)",
            job,
        )
        self.conn.commit()
        return cur.rowcount == 1

    def update(self, job_id: str, **fields):
        for k in ("plan_json", "report_json"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k], indent=1)
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        self.conn.execute(f"update jobs set {sets} where id = :id", {**fields, "id": job_id})
        self.conn.commit()

    def get(self, job_id: str) -> dict | None:
        row = self.conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def by_status(self, *statuses: str) -> list[dict]:
        q = f"select * from jobs where status in ({','.join('?' * len(statuses))}) order by score desc, found_at desc"
        return [dict(r) for r in self.conn.execute(q, statuses)]

    def all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("select * from jobs order by found_at desc")]

    def add_event(self, ev: dict) -> bool:
        ev = {"proof": None, "body": None, "guess": None, "reviewed": 1, "manual": 0, **ev}
        cur = self.conn.execute(
            "insert or ignore into events (id, job_id, kind, at, sender, subject, proof, body, guess, reviewed, manual)"
            " values (:id, :job_id, :kind, :at, :sender, :subject, :proof, :body, :guess, :reviewed, :manual)", ev)
        self.conn.commit()
        return cur.rowcount == 1

    def events(self, all: bool = False) -> list[dict]:
        """Settled events, newest first. Unreviewed and ignored emails only come back with all=True."""
        q = "select * from events" + ("" if all else " where reviewed = 1 and kind != 'ignored'") + " order by at desc"
        return [dict(r) for r in self.conn.execute(q)]

    def pending_events(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("select * from events where reviewed = 0 order by at")]

    def get_event(self, event_id: str) -> dict | None:
        row = self.conn.execute("select * from events where id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def set_event(self, event_id: str, **fields):
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        self.conn.execute(f"update events set {sets} where id = :id", {**fields, "id": event_id})
        self.conn.commit()

    def has_event(self, event_id: str) -> bool:
        return self.conn.execute("select 1 from events where id = ?", (event_id,)).fetchone() is not None

    def event_kind(self, event_id: str) -> str | None:
        row = self.conn.execute("select kind from events where id = ?", (event_id,)).fetchone()
        return row[0] if row else None

    def delete_event(self, event_id: str):
        self.conn.execute("delete from events where id = ?", (event_id,))
        self.conn.commit()

    def add_sent(self, msg_id: str, at: str, to_addrs: list[str], subject: str, in_reply_to: str):
        self.conn.execute("insert or ignore into sent (id, at, to_addrs, subject, in_reply_to) values (?, ?, ?, ?, ?)",
                          (msg_id, at, " ".join(to_addrs), subject[:200], in_reply_to))
        self.conn.commit()

    def sent(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("select * from sent order by at")]

    def nudge_states(self) -> dict[str, dict]:
        return {r["key"]: dict(r) for r in self.conn.execute("select * from nudge_state")}

    def set_nudge(self, key: str, state: str | None, until: str | None = None):
        if state is None:
            self.conn.execute("delete from nudge_state where key = ?", (key,))
        else:
            self.conn.execute("insert or replace into nudge_state (key, state, until) values (?, ?, ?)", (key, state, until))
        self.conn.commit()

    def log_usage(self, source: str, model: str, emails: int, sorted_n: int, cost: float, ms: int, error: str | None,
                  est: float = 0.0, tokens: int = 0):
        """cost: money actually billed (OpenRouter); est: API-price equivalent of subscription use."""
        self.conn.execute("insert into usage (source, model, emails, sorted, cost, ms, error, est, tokens)"
                          " values (?, ?, ?, ?, ?, ?, ?, ?, ?)", (source, model, emails, sorted_n, cost, ms, error, est, tokens))
        self.conn.commit()

    def spend_this_month(self) -> float:
        r = self.conn.execute("select coalesce(sum(cost), 0) from usage where at >= strftime('%Y-%m-01', 'now', 'localtime')").fetchone()
        return float(r[0] or 0)

    def usage_by_day(self, days: int = 30) -> list[dict]:
        q = ("select substr(at, 1, 10) day, max(case when source = 'daily' then 1 else 0 end) runs,"
             " sum(tokens) tokens, sum(cost) cost, sum(est) est from usage where at >= datetime('now', 'localtime', ?)"
             " group by day order by day")
        return [dict(r) for r in self.conn.execute(q, (f"-{days} days",))]

    def usage_by_stage(self, days: int = 30) -> list[dict]:
        """Daily-run usage per stage (rank, apply, prep, drafts), from the model label agent:model:stage."""
        q = ("select model, count(*) n, sum(tokens) tokens, sum(est) est, sum(cost) cost from usage"
             " where source = 'daily' and at >= datetime('now', 'localtime', ?) group by model")
        by: dict[str, dict] = {}
        for r in self.conn.execute(q, (f"-{days} days",)):
            parts = (r["model"] or "").split(":")
            stage = parts[-1].split(" ")[0] if len(parts) >= 3 else "whole run"  # model ids can hold ':' (…:free)
            b = by.setdefault(stage, {"stage": stage, "n": 0, "tokens": 0, "est": 0.0, "cost": 0.0, "models": set()})
            b["n"] += r["n"]; b["tokens"] += r["tokens"] or 0; b["est"] += r["est"] or 0; b["cost"] += r["cost"] or 0
            if len(parts) >= 2:
                b["models"].add(":".join(parts[1:-1]) if len(parts) >= 3 else parts[1])
        order = {"rank": 0, "apply": 1, "prep": 2, "drafts": 3, "whole run": 4}
        return sorted(({**b, "models": ", ".join(sorted(b["models"]))} for b in by.values()), key=lambda b: order.get(b["stage"], 9))

    def usage_summary(self, days: int = 30) -> dict[str, dict]:
        """Per source over the last N days: calls, emails sorted, cost, average time, last error."""
        q = ("select source, count(*) calls, sum(sorted) sorted, sum(emails) emails, sum(cost) cost, avg(ms) ms,"
             " sum(est) est, sum(tokens) tokens,"
             " sum(error is not null) failures, max(at) last from usage where at >= datetime('now', 'localtime', ?)"
             " group by source")
        out = {r["source"]: dict(r) for r in self.conn.execute(q, (f"-{days} days",))}
        if "daily" in out:  # a run is several stage sessions now: count mornings, not sessions
            out["daily"]["sessions"] = out["daily"]["calls"]
            out["daily"]["calls"] = self.conn.execute(
                "select count(distinct substr(at, 1, 10)) from usage where source = 'daily' and at >= datetime('now', 'localtime', ?)",
                (f"-{days} days",)).fetchone()[0]
        for src, row in out.items():
            e = self.conn.execute("select error, at from usage where source = ? and error is not null order by at desc limit 1",
                                  (src,)).fetchone()
            row["last_error"] = dict(e) if e else None
        return out

    def log_run(self, kind: str, ok: bool, summary: str = ""):
        """Keeps the latest run of each kind, for the dashboard's freshness strip."""
        self.conn.execute("insert or replace into runs (kind, at, ok, summary) values (?, datetime('now', 'localtime'), ?, ?)",
                          (kind, int(ok), summary[:300]))
        self.conn.commit()

    def runs(self) -> dict[str, dict]:
        return {r["kind"]: dict(r) for r in self.conn.execute("select * from runs")}
