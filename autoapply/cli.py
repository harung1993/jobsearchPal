"""autoapply: the hands for the daily agent run. The agent decides; this opens, fills and uploads.

  autoapply find                      pull new matching roles from boards and feeds
  autoapply board add ATS SLUG        watch another company's job board (checked first)
  autoapply board list                boards being watched
  autoapply leads resolve [N]         find the top N leads on the company's own job board (no AI)
  autoapply alerts [--days N]         recent job-alert emails as text, to pull roles from
  autoapply sync-email [--days N] [--rebuild] [--no-review]  gather ATS/recruiter emails, then have the
                                      model sort them (--rebuild refiles; your corrections are kept)
  autoapply review-emails             sort the emails still waiting (sources and order: Settings page)
  autoapply daily-agent               the agent (claude or codex) and model picked for the daily run
  autoapply emails [--pending]        filed emails with their kind, as JSON
  autoapply emails set ID KIND [--job JOB_ID|none]  settle one by hand (confirmed, interview, rejected,
                                      offer, recruiter, ignored)
  autoapply import-history FILE.json  load past applications (tracker rows) into the dashboard
  autoapply log-run KIND ok|fail [MSG]  record a run (daily.sh uses it) for the dashboard
  autoapply add URL [--company C --title T]   track a role found elsewhere
  autoapply list [--status S]         show tracked roles
  autoapply list --prep               interviews that need a prep pack, with where to write it
  autoapply list --nudges             follow-up reminders that need a draft reply, with where to write it
  autoapply list --limits             today's caps from the Settings page (roles to tailor, packs, drafts)
  autoapply show JOB_ID               full posting text, for tailoring
  autoapply skip JOB_ID [--reason R]  mark a role not worth applying to
  autoapply scan URL [--ats A]        list the form's questions as JSON
  autoapply fill PLAN.json [--job ID] fill the form, upload PDFs, screenshot, stop before Submit
  autoapply brief [--send]            morning brief: today's picks, new replies, application status
  autoapply serve                     review page: check answers, decide consents, press Submit
  autoapply reset-password [--email E]  forgot the dashboard password: set a new one (signs every browser out)
  autoapply finish JOB_ID             (on your Mac) open the filled form in Chrome; you submit it
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from . import config, finder
from .db import DB
from .fillers import fill, scan
from .fillers.base import detect


def _out(obj):
    print(json.dumps(obj, indent=1, default=str))


def _review(s, db) -> dict:
    """Model review of waiting emails; a failure leaves them waiting and is logged, not raised."""
    from . import classify
    from .prefs import Prefs
    try:
        r = classify.review(db, Prefs(s.data_dir, s.raw))
        summary = ", ".join(f"{v} {k}" for k, v in r.items() if k != "errors")
        if r.get("errors"):
            summary += " · failed: " + ", ".join(r["errors"])
        db.log_run("classify", not r.get("errors") or r.get("left", 0) == 0, summary)
        return r
    except Exception as e:
        db.log_run("classify", False, str(e)[:300])
        return {"error": str(e)[:300], "left": len(db.pending_events())}


def _summary(out: dict) -> str:
    filed = sum(out["filed"].values())
    r = out.get("reviewed") or {}
    bits = [f"{filed} new email{'' if filed == 1 else 's'}"]
    sorted_n = sum(v for k, v in r.items() if k not in ("left", "error", "errors"))
    if sorted_n:
        bits.append(f"{sorted_n} sorted")
    if r.get("left"):
        bits.append(f"{r['left']} waiting for review")
    if r.get("error"):
        bits.append("sorting failed: " + r["error"][:80])
    for src, err in (r.get("errors") or {}).items():
        bits.append(f"{src} failed")
    return ", ".join(bits)


def _denied(raw: str) -> str | None:
    """A step that was refused a command didn't do its job: say which command, so the run shows it as failed."""
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    asks = [x.get("tool_input", {}).get("command") or x.get("tool_name") or "?"
            for x in (d.get("permission_denials") or []) if isinstance(x, dict)]
    return f"needed permission for {', '.join(sorted(set(map(str, asks))))[:200]}" if asks else None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autoapply", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("find")
    a = sub.add_parser("board"); a.add_argument("action", choices=["add", "list"]); a.add_argument("ats", nargs="?", choices=sorted(finder.FETCHERS)); a.add_argument("slug", nargs="?")
    a = sub.add_parser("alerts"); a.add_argument("--days", type=int, default=1)
    a = sub.add_parser("sync-email"); a.add_argument("--days", type=int, default=60); a.add_argument("--rebuild", action="store_true"); a.add_argument("--no-review", action="store_true")
    sub.add_parser("review-emails")
    sub.add_parser("daily-model")
    a = sub.add_parser("daily-agent"); a.add_argument("--stage", default="apply")
    sub.add_parser("daily-stages"); sub.add_parser("daily-picks"); sub.add_parser("todo-line"); sub.add_parser("pal-line")
    a = sub.add_parser("daily-prompt"); a.add_argument("stage"); a.add_argument("job_id", nargs="?", default="")
    a = sub.add_parser("candidates"); a.add_argument("--limit", type=int, default=12)
    a = sub.add_parser("quick-pick"); a.add_argument("--alerts", action="store_true")
    a = sub.add_parser("log-daily"); a.add_argument("agent"); a.add_argument("model", nargs="?", default="")
    a.add_argument("via", nargs="?", default="subscription"); a.add_argument("--stage", default="")
    sub.add_parser("daily-env")
    a = sub.add_parser("emails"); a.add_argument("action", nargs="?", choices=["set"]); a.add_argument("event_id", nargs="?")
    a.add_argument("kind", nargs="?"); a.add_argument("--job", default=""); a.add_argument("--pending", action="store_true")
    a = sub.add_parser("import-history"); a.add_argument("file")
    a = sub.add_parser("log-run"); a.add_argument("kind"); a.add_argument("result", choices=["ok", "fail"]); a.add_argument("msg", nargs="?", default="")
    a = sub.add_parser("add"); a.add_argument("url"); a.add_argument("--company", default=""); a.add_argument("--title", default="")
    a = sub.add_parser("list"); a.add_argument("--status"); a.add_argument("--prep", action="store_true"); a.add_argument("--nudges", action="store_true"); a.add_argument("--limits", action="store_true")
    a = sub.add_parser("show"); a.add_argument("job_id")
    a = sub.add_parser("check"); a.add_argument("job_id")
    a = sub.add_parser("leads"); a.add_argument("action", nargs="?", default="list", choices=["list", "sync", "resolve", "lookup", "job"])
    a.add_argument("key", nargs="?", default="")
    a.add_argument("--days", type=int, default=14)
    a = sub.add_parser("skip"); a.add_argument("job_id", nargs="+"); a.add_argument("--reason", default="")
    a = sub.add_parser("scan"); a.add_argument("url"); a.add_argument("--ats")
    sub.add_parser("resume-outline")
    a = sub.add_parser("build-docs"); a.add_argument("spec", help="docs.json, its folder, or an application slug")
    a = sub.add_parser("fill"); a.add_argument("plan"); a.add_argument("--job")
    a = sub.add_parser("brief"); a.add_argument("--send", action="store_true")
    a = sub.add_parser("skills"); a.add_argument("action", choices=["tag", "build", "show"]); a.add_argument("--limit", type=int)
    sub.add_parser("serve")
    sub.add_parser("setup-check")
    a = sub.add_parser("reset-password"); a.add_argument("--email", default="")
    a = sub.add_parser("finish"); a.add_argument("job_id"); a.add_argument("--server", default=os.environ.get("AUTOAPPLY_SERVER", ""))
    args = ap.parse_args(argv)
    if args.cmd == "finish":
        return finish(args.job_id, args.server)

    s = config.load(args.config, allow_example=args.cmd in ("serve", "setup-check", "reset-password"))
    if args.cmd == "reset-password":
        return reset_password(s, args.email)
    if args.cmd == "setup-check":
        from . import setup
        # The daily run stops only without contact details or job interests; the rest are warnings.
        st = setup.status(s, os.environ)
        labels = {"profile": "contact details", "interests": "job interests", "resume": "base resume",
                  "agent": "agent sign-in"}
        block = [labels[k] for k in st["left"] if k in ("profile", "interests")]
        warn = [labels[k] for k in st["left"] if k not in ("profile", "interests")]
        if block:
            sys.exit("setup not finished: " + ", ".join(block + warn) + " (dashboard > Setup)")
        print("ready" + (f" (missing: {', '.join(warn)})" if warn else ""))
        return
    db = DB(s.data_dir / "autoapply.db")
    headless = s.raw.get("browser", {}).get("headless", True)

    if args.cmd == "find":
        stats: dict = {}
        new = finder.run(s, db, stats)
        (s.data_dir / "sources.json").write_text(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "sources": stats}))
        failed = [k for k, v in stats.items() if v["error"]]
        db.log_run("find", True, f"{len(new)} new roles from {len(stats)} sources" + (f"; {len(failed)} failed" if failed else ""))
        _out([{k: j[k] for k in ("id", "company", "title", "location", "url")} for j in new])
    elif args.cmd == "log-run":
        db.log_run(args.kind, args.result == "ok", args.msg)
    elif args.cmd == "board":
        if args.action == "list":
            _out(finder.boards(s))
        else:
            if not (args.ats and args.slug):
                sys.exit("usage: autoapply board add ATS SLUG")
            try:
                n = finder.add_board(s, args.ats, args.slug)
            except Exception as e:
                sys.exit(f"{args.ats}:{args.slug} doesn't answer ({e}); check the slug in the careers URL")
            print(f"watching {args.ats}:{args.slug} ({n} open roles)")
    elif args.cmd == "alerts":
        from . import alerts
        _out(alerts.fetch(args.days, s.raw.get("alert_senders")))
    elif args.cmd == "sync-email":
        from . import emailsync
        try:
            if args.rebuild:
                emailsync.rebuild(db, args.days)
            counts = emailsync.sync(db, args.days, s.raw.get("recruiter_senders"), s.data_dir / "proof")
        except Exception as e:
            db.log_run("sync-email", False, str(e))
            raise
        out = {"filed": counts}
        try:  # every role in the alert emails, kept as a lead (Dashboard > Leads)
            from . import leads
            out["leads"] = leads.sync(db, s, min(args.days, 14))
            out["leads"]["on_company_site"] = leads.resolve(db, s)["found"]
        except Exception as e:
            out["leads"] = {"error": str(e)[:200]}
        if not args.no_review:
            out["reviewed"] = _review(s, db)
        db.log_run("sync-email", True, _summary(out))
        _out(out)
    elif args.cmd in ("daily-model", "daily-agent"):
        # daily.sh reads "agent model via" ("-" for no model); via is subscription, openrouter or blocked.
        from .prefs import Prefs
        pr = Prefs(s.data_dir, s.raw)
        d = pr.daily(db.spend_this_month(), getattr(args, "stage", "apply"))
        if args.cmd == "daily-model":
            print(d["model"])
        else:
            if d["via"] == "openrouter":  # remember the key's total so log-daily can work out what this run cost
                from . import classify
                before = classify.openrouter_spent(pr.key("OPENROUTER_API_KEY"))
                (s.data_dir / "daily").mkdir(exist_ok=True)
                (s.data_dir / "daily" / ".or-before").write_text("" if before is None else str(before))
            print(f"{d['agent']} {d['model'] or '-'} {d['via']}")
            if d["why"]:
                print(d["why"], file=sys.stderr)
    elif args.cmd == "daily-stages":
        # Which agent stages today's run needs, in order (apply stages come from daily-picks afterwards).
        from . import nudges, prep
        from .prefs import Prefs
        lim = Prefs(s.data_dir, s.raw).limits()
        stages = []
        manual = os.environ.get("AUTOAPPLY_TRIGGER") == "manual"  # Run now: just more applications
        if manual:
            pass
        elif lim["prep_per_day"] and prep.needed(db, s.data_dir, lim["prep_per_day"]):
            stages.append("prep")
        if not manual and lim["drafts_per_day"] and nudges.for_agent(db, s.data_dir, lim["drafts_per_day"]):
            stages.append("drafts")
        if lim["picks_per_day"]:
            stages.append("rank")
        print(" ".join(stages))
    elif args.cmd == "todo-line":
        # One line of open follow-up reminders for the phone push, e.g. "3 to do: Reply to ...; Follow up on ...".
        from . import nudges
        open_ = nudges.compute(db, s.data_dir, settings=s)
        if open_:
            names = "; ".join(n["title"] for n in open_[:4]) + ("; ..." if len(open_) > 4 else "")
            print(f"{len(open_)} to do: {names}")
    elif args.cmd == "pal-line":
        # The pal's one line for the top of the phone push (pal.push_line): good news first, never a promise.
        from . import pal, stats
        from .web import work_search
        print(pal.push_line(db, stats.compute(db, floor=work_search(s)[1]), datetime.now()))
    elif args.cmd == "daily-picks":
        from .prefs import Prefs
        try:
            picks = json.loads((s.data_dir / "daily" / "picks.json").read_text())
        except (OSError, ValueError):
            picks = []
        n = Prefs(s.data_dir, s.raw).limits()["picks_per_day"]
        from . import rank
        from .rank import Applied
        applied = Applied(db, int(Prefs(s.data_dir, s.raw).data.get("reapply_after_days", 90) or 0))
        ids, companies = [], set()
        for p in picks:
            j = db.get(p.get("id", "")) if isinstance(p, dict) else None
            if not j or j["status"] != "new":
                continue
            if rank._norm(j["company"]) in companies:  # one role per company per run: the rest stay on the shortlist
                continue
            why = applied.why(j["company"])
            if why:  # last guard before an apply session spends tokens
                db.update(j["id"], status="skipped", error=why)
                continue
            ids.append(j["id"])
            companies.add(rank._norm(j["company"]))
        ids = ids[:n]
        print("\n".join(ids))
    elif args.cmd == "daily-prompt":
        # The stage's prompt with today's details filled in; daily.sh pipes it to the agent.
        from .prefs import Prefs
        root = Path(__file__).resolve().parent.parent / "prompts" / "stages"
        if not re.fullmatch(r"[a-z]+", args.stage) or not (root / f"{args.stage}.md").exists():
            sys.exit(f"no stage {args.stage}")
        text = (root / f"{args.stage}.md").read_text()
        day = Prefs(s.data_dir, s.raw).data.get("discover_weekday", 1)
        if os.environ.get("AUTOAPPLY_TRIGGER") == "manual":
            day = 0  # discovery is once a week, on the scheduled run
        text = text.replace("{{DISCOVER}}", (root / "discover.md").read_text() if day and datetime.now().isoweekday() == day else "")
        if args.job_id and not db.get(args.job_id):
            sys.exit(f"no job {args.job_id}")
        print(text.replace("{{JOB_ID}}", args.job_id))
    elif args.cmd == "quick-pick":
        # Picks today's roles with one cheap OpenRouter call. Exits 2 when it's off (daily.sh then runs the rank agent).
        from . import rank
        from .prefs import Prefs
        pr = Prefs(s.data_dir, s.raw)
        model, key = pr.data.get("quick_pick_model") or "", pr.key("OPENROUTER_API_KEY")
        day = 0 if os.environ.get("AUTOAPPLY_TRIGGER") == "manual" else pr.data.get("discover_weekday", 1)
        if not model or not key or (day and datetime.now().isoweekday() == day):
            sys.exit(2)  # off, no key, or discovery day (that needs the agent's web search)
        if db.spend_this_month() >= float(pr.data.get("monthly_api_budget") or 0):
            sys.exit(2)
        n = pr.limits()["picks_per_day"]
        if args.alerts:
            # Step 1: the cheap model reads the alert emails and lists roles that fit; writes data/daily/alert-roles.json.
            from . import alerts
            try:
                gmail = os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")
                emails = alerts.fetch(1, s.raw.get("alert_senders")) if gmail else []  # no Gmail set up: nothing to read
                roles, u = rank.alert_roles(db, s, emails, model, key)
                err = None
            except Exception as e:
                roles, u, err = [], {"tokens": 0, "cost": 0.0}, str(e)[:300]
            if u["tokens"] or err:
                db.log_usage("daily", f"openrouter:{model}:alerts (openrouter)", 0, 0, u["cost"], 0, err, u["cost"], u["tokens"])
            (s.data_dir / "daily").mkdir(exist_ok=True)
            (s.data_dir / "daily" / "alert-roles.json").write_text(json.dumps(roles, indent=1))
            if err:
                print(f"alert read failed: {err}", file=sys.stderr)
                sys.exit(1)
            print(len(roles))
            return
        try:
            picks, u = rank.quick_pick(db, s, n, model, key)
            err = None
        except Exception as e:
            picks, u, err = [], {"tokens": 0, "cost": 0.0}, str(e)[:300]
        db.log_usage("daily", f"openrouter:{model}:rank (openrouter)", 0, 0, u["cost"], 0, err, u["cost"], u["tokens"])
        if err:
            print(f"quick pick failed: {err}", file=sys.stderr)
            sys.exit(1)
        (s.data_dir / "daily").mkdir(exist_ok=True)
        (s.data_dir / "daily" / "picks.json").write_text(json.dumps(picks, indent=1))
        names = [f"{j['company']} ({j['title']})" for j in (db.get(p["id"]) for p in picks) if j]
        print("Picked: " + ", ".join(names) if names else "No good matches today")
    elif args.cmd == "candidates":
        from . import rank
        _out(rank.candidates(db, s, args.limit))
    elif args.cmd == "daily-env":
        # Environment for running the daily agent on an OpenRouter key; daily.sh evals it. Prints nothing otherwise.
        import shlex
        from .prefs import Prefs
        pr = Prefs(s.data_dir, s.raw)
        d = pr.daily(db.spend_this_month())
        if d["via"] == "openrouter":
            key = pr.key("OPENROUTER_API_KEY")  # the stage's model is passed on the command line
            env_out = {"OPENROUTER_API_KEY": key}
            if d["agent"] == "claude":  # OpenRouter's Anthropic-compatible endpoint (its Claude Code guide)
                env_out.update({"ANTHROPIC_BASE_URL": "https://openrouter.ai/api", "ANTHROPIC_AUTH_TOKEN": key,
                                "ANTHROPIC_API_KEY": "", "ANTHROPIC_DEFAULT_HAIKU_MODEL": "~anthropic/claude-haiku-latest",
                                "CLAUDE_CODE_SUBAGENT_MODEL": d["model"]})
            for k, v in env_out.items():
                print(f"export {k}={shlex.quote(v)}")
    elif args.cmd == "log-daily":
        # daily.sh pipes the agent's output here: log its tokens and cost, print the summary line.
        from .prefs import Prefs
        raw = sys.stdin.read()
        text, est, tokens, err, cost = raw, 0.0, 0, None, 0.0
        if args.agent == "claude":
            from . import classify
            classify.LAST.clear()
            try:
                text = classify._claude_json(raw)
            except RuntimeError as e:
                text, err = "", str(e)
            est, tokens = classify.LAST.get("est", 0.0), classify.LAST.get("tokens", 0)
            err = err or _denied(raw)
        via = args.via
        if via == "openrouter":
            # Real spend: the key's usage now minus before the run. Falls back to the agent's own estimate.
            from . import classify
            before_f = s.data_dir / "daily" / ".or-before"
            try:
                before = float(before_f.read_text())
            except (OSError, ValueError):
                before = None
            after = classify.openrouter_spent(Prefs(s.data_dir, s.raw).key("OPENROUTER_API_KEY") or "")
            cost = max(0.0, after - before) if (after is not None and before is not None) else est
        label = f"{args.agent}:{args.model}" if args.model else args.agent
        if args.stage:
            label = f"{args.agent}:{args.model or 'default'}:{args.stage}"
        db.log_usage("daily", label + (" (openrouter)" if via == "openrouter" else ""), 0, 0, cost, 0, err, est, tokens)
        lines = [l for l in text.strip().splitlines() if l.strip()]
        print(f"Stopped: {err}" if err and err.startswith("needed permission") else (lines[-1] if lines else ""))
        if err:
            sys.exit(1)
    elif args.cmd == "review-emails":
        _out(_review(s, db))
    elif args.cmd == "emails":
        from . import emailsync
        if args.action == "set":
            if not (args.event_id and args.kind):
                sys.exit("usage: autoapply emails set EVENT_ID KIND [--job JOB_ID|none]")
            job = None if args.job == "none" else args.job
            try:
                ev = emailsync.review_event(db, args.event_id, args.kind, job_id=job, manual=True)
            except (KeyError, ValueError) as e:
                sys.exit(str(e))
            _out({k: ev[k] for k in ("id", "kind", "job_id", "subject")})
        else:
            rows = db.pending_events() if args.pending else db.events(all=True)
            _out([{k: e[k] for k in ("id", "at", "kind", "guess", "reviewed", "manual", "job_id", "sender", "subject")}
                  for e in rows if e["kind"] != "applied"])
    elif args.cmd == "import-history":
        from . import history
        print(f"imported {history.import_file(db, Path(args.file))} past applications")
    elif args.cmd == "add":
        jid = "manual:" + hashlib.sha1(args.url.encode()).hexdigest()[:10]
        db.upsert_job({"id": jid, "ats": detect(args.url).name, "company": args.company, "title": args.title,
                       "location": "", "url": args.url, "apply_url": args.url, "description": ""})
        print(jid)
    elif args.cmd == "list" and args.limits:
        from .prefs import Prefs
        _out(Prefs(s.data_dir, s.raw).limits())
    elif args.cmd == "list" and args.nudges:
        from . import nudges
        from .prefs import Prefs
        _out(nudges.for_agent(db, s.data_dir, Prefs(s.data_dir, s.raw).limits()["drafts_per_day"]))
    elif args.cmd == "list" and args.prep:
        from . import prep
        from .prefs import Prefs
        _out(prep.needed(db, s.data_dir, Prefs(s.data_dir, s.raw).limits()["prep_per_day"]))
    elif args.cmd == "list":
        rows = db.by_status(args.status) if args.status else db.all()
        _out([{k: r[k] for k in ("id", "status", "company", "title", "location", "found_at")} for r in rows])
    elif args.cmd == "show":
        _out(db.get(args.job_id) or sys.exit(f"no job {args.job_id}"))
    elif args.cmd == "leads":
        from . import leads
        if args.action == "sync":
            _out(leads.sync(db, s, args.days))
        elif args.action == "resolve":
            # The best untracked leads, looked up on the company's own job board (no AI). --days is unused here.
            _out(leads.resolve(db, s, limit=int(args.key or 30)))
        elif args.action == "lookup":
            # Starred leads for the alerts step to find on the company's own site; prints how many.
            todo = leads.starred_for_lookup(db, only=os.environ.get("AUTOAPPLY_LEAD", ""))
            if todo:
                (s.data_dir / "daily").mkdir(parents=True, exist_ok=True)
                (s.data_dir / "daily" / "alert-roles.json").write_text(json.dumps(todo, indent=1))
            print(len(todo))
        elif args.action == "job":
            # The tracked job behind a lead, once the alerts step found it on the company's site.
            leads.link_tracked(db)
            r = leads.get(db, args.key)
            if r and r["job_id"] and (db.get(r["job_id"]) or {}).get("status") == "new":
                print(r["job_id"])
        else:
            for r in leads.rows(db)[:200]:
                print(f"{r['score']:5.1f}  {r['status']:9}  {r['company']} | {r['title']} | {r['location']} | {r['source']}")
    elif args.cmd == "check":
        from . import preflight
        checks = preflight.for_job(db, s, args.job_id)
        for c in checks:
            mark = "ok  " if c["ok"] else ("FAIL" if c["hard"] else "warn")
            print(f"{mark} {c['group']}: {c['name']}" + (f" ({c['detail']})" if c["detail"] and not c["ok"] else ""))
        if preflight.blocking(checks):
            sys.exit(1)
    elif args.cmd == "skip":
        for jid in args.job_id:
            db.update(jid, status="skipped", error=args.reason)
    elif args.cmd == "scan":
        _out(scan(args.url, args.ats, headless=headless))
    elif args.cmd in ("resume-outline", "build-docs"):
        from . import docs
        from .setup import base_resume
        base = base_resume(s.root)
        if base is None:
            sys.exit("No base resume in materials/ (upload one on the Setup page).")
        if args.cmd == "resume-outline":
            _out(docs.outline(base))
            return
        spec_path = Path(args.spec)
        if not spec_path.exists():
            spec_path = s.data_dir / "applications" / args.spec
        if spec_path.is_dir():
            spec_path = spec_path / "docs.json"
        try:
            r = docs.build(base, json.loads(spec_path.read_text()), spec_path.parent,
                           last_name=s.profile.get("last_name", ""))
        except (OSError, ValueError) as e:  # SpecError and bad JSON alike: say what to fix
            sys.exit(f"build-docs: {e}")
        _out(r)
        if r["problems"]:
            sys.exit(1)
    elif args.cmd == "fill":
        plan = json.loads(Path(args.plan).read_text())
        # Consent answers and the go-ahead only ever come from you on the review page.
        plan.pop("approved_by_user", None)
        plan.pop("approved", None)
        if args.job and not plan.get("url"):
            plan["url"] = db.get(args.job)["apply_url"]
        report = fill(plan, s.profile, s.data_dir / "screenshots", headless)
        db.log_run("fill", not report.errors, f"{plan.get('url', '')[:80]}: {len(report.filled)} filled, {len(report.errors)} errors")
        out = report.as_dict()
        if args.job:
            db.update(args.job, status="filled", plan_json=plan, report_json=out,
                      screenshot=report.screenshot, error=None)
            from . import preflight
            out["checks_failed"] = [f"{c['group']}: {c['name']} ({c['detail']})" for c in preflight.for_job(db, s, args.job) if not c["ok"]]
        _out(out)
    elif args.cmd == "brief":
        from . import brief
        from .web import work_search
        label, floor = work_search(s)
        subject, text, html = brief.compose(db, os.environ.get("REVIEW_URL", ""), label=label, floor=floor, settings=s,
                                          data_dir=s.data_dir)
        if args.send:
            to = brief.send(subject, text, html)
            db.log_run("brief", True, f"sent to {to}")
            print(f"sent: {subject}")
        else:
            print(subject + "\n\n" + text)
    elif args.cmd == "skills":
        from . import skills
        from .prefs import Prefs
        pr = Prefs(s.data_dir, s.raw)
        if args.action == "tag":
            r = skills.tag(db, s, pr, args.limit)
            if "tagged" in r:
                db.log_run("skills", not r["failed_calls"], f"{r['tagged']} of {r['roles']} roles tagged")
            _out(r)
        elif args.action == "build":
            _out({"skills": skills.build_from_resume(s, pr, db)})
        else:
            _out({"enabled": skills.enabled(pr), "estimate": skills.estimate(pr), "mine": skills.mine(s)})
    elif args.cmd == "serve":
        import uvicorn
        from .web import make_app
        r = s.raw.get("review", {})
        # In Docker the dashboard listens on all interfaces inside the container; compose decides what's exposed.
        host = os.environ.get("AUTOAPPLY_HOST") or r.get("host", "127.0.0.1")
        uvicorn.run(make_app(s, db), host=host, port=int(os.environ.get("AUTOAPPLY_PORT") or r.get("port", 8787)))


def reset_password(s, email: str = "", ask=None, ask_secret=None):
    """Runs on the server: the only way back in when the password is forgotten. Creates the account if there is none."""
    import getpass
    from . import auth
    from .prefs import Prefs
    ask, ask_secret = ask or input, ask_secret or getpass.getpass
    current = auth.load(s.data_dir)
    email = (email or (current or {}).get("email") or ask("Email for your job search: ")).strip()
    pw = ask_secret(f"New password (at least {auth.MIN_LEN} characters): ")
    if err := auth.check_new(email, pw, ask_secret("Type it again: ")):
        sys.exit(err)
    auth.save(s.data_dir, email, pw)
    auth.ensure_token(Prefs(s.data_dir, s.raw))
    print(f"Password {'changed' if current else 'set'} for {email}. Every browser is signed out; sign in again.")


def finish(job_id: str, server: str):
    """Runs on your laptop: pulls the plan and PDFs from the review page and fills a visible Chrome."""
    import httpx
    from .fillers import handoff
    if not server:
        sys.exit("set AUTOAPPLY_SERVER (e.g. http://<server-ip>:8787) or pass --server")
    params = {"t": os.environ["AUTOAPPLY_TOKEN"]} if os.environ.get("AUTOAPPLY_TOKEN") else {}
    with httpx.Client(base_url=server.rstrip("/"), params=params, timeout=60) as c:
        r = c.get(f"/bundle/{job_id}")
        if r.status_code != 200:
            sys.exit(f"review page said {r.status_code} for {job_id}")
        b = r.json()
        folder = Path.home() / "autoapply-finish" / job_id.replace(":", "_").replace("/", "_")
        folder.mkdir(parents=True, exist_ok=True)
        plan = b["plan"]
        plan["files"] = {}
        for slot, name in b["files"].items():
            dest = folder / Path(name).name
            dest.write_bytes(c.get(f"/file/{slot}/{job_id}").raise_for_status().content)
            plan["files"][slot] = str(dest)
    job = b["job"]
    print(f"Opening {job['company']} · {job['title']} in Chrome. Check it, answer any captcha, and press Submit yourself.")
    print("Close the tab when you're done.")
    report = handoff(plan, b["profile"])
    left = [u["label"] for u in report.unanswered]
    if left:
        print("Left for you to answer:", "; ".join(left))
    print(f"Once it's sent, press 'I applied by hand' on {server.rstrip('/')}/job/{job_id} (the confirmation email also marks it).")


if __name__ == "__main__":
    main()
