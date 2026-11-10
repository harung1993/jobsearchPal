"""Review page. The only place a plan gets approved_by_user and a Submit gets clicked."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader
from starlette.concurrency import run_in_threadpool

from . import stats
from .db import DB
from .fillers import fill, submit

env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)
env.globals["ws_label"] = "Work search"
env.globals["strptime"] = lambda s: datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
env.filters["hue"] = lambda s: sum(ord(c) * (i + 7) for i, c in enumerate((s or "?").lower())) % 360  # a steady colour per company
# "confirmed" (the stored kind) read as a confirmed interview; it only means the application was received.
# "rejected" reads as "closed" in lists: the count stays exact, it just stops leading (VOICE.md).
env.filters["label"] = lambda k: {"confirmed": "received", "rejected": "closed", "no reply": "no reply yet"}.get(k, k)
env.filters["pillcls"] = lambda k: {"rejected": "closed"}.get(k, k)  # a closed application is a neutral fact, not an alarm (red)


SHORTLIST = 5  # roles on "Ready for you" each day: the prepared ones plus the next best to triage
DECLINE_REASONS = {"fit": "not a fit", "location": "location", "pay": "pay", "applied": "already applied", "other": "other"}

def page(name: str, **ctx) -> HTMLResponse:
    return HTMLResponse(env.get_template(name).render(**ctx))


KIND_LABELS = [("confirmed", "Received (auto-reply)"), ("interview", "Interview"), ("rejected", "Rejection"), ("offer", "Offer"),
               ("recruiter", "Recruiter"), ("agency", "Unemployment agency"), ("ignored", "Not job-related")]


def state_rules() -> dict:
    """Every state's work-search rule (autoapply/work_search_states.yaml), with when and where it was checked."""
    import yaml
    data = yaml.safe_load((Path(__file__).parent / "work_search_states.yaml").read_text())
    for r in data["states"].values():
        ww = r.get("waiting_week")  # text in the checked data ("One unpaid week...", "None"), a bool in older files
        r["waiting_week_note"] = (ww if isinstance(ww, str) and not ww.strip().lower().startswith("none")
                                  else (r.get("waiting_week_note") or "") if ww is True else "")
        r["waiting_week"] = bool(r["waiting_week_note"]) if isinstance(ww, str) else bool(ww)
        r["checked"] = str(r.get("checked") or data["checked"])
        r.setdefault("source", data["source"])
    return data["states"]


def general_notes() -> list[str]:
    """Caveats that apply in every state (taxes, severance, reporting part-time pay...)."""
    import yaml
    return yaml.safe_load((Path(__file__).parent / "work_search_states.yaml").read_text()).get("general") or []


def my_state(settings) -> dict | None:
    """The rule for the state picked on the Setup page, or None."""
    code = str((settings.raw.get("work_search") or {}).get("state") or "").upper()
    rules = state_rules()
    return {"code": code, **rules[code]} if code in rules else None


def work_search(settings) -> tuple[str, int]:
    """Label and weekly minimum for the work-search log, e.g. {label: DUA, weekly_minimum: 3}."""
    ws = settings.raw.get("work_search") or {}
    return ws.get("label", "Work search"), int(ws.get("weekly_minimum", 3))


def make_app(settings, db: DB) -> FastAPI:
    app = FastAPI()
    shots = settings.data_dir / "screenshots"
    headless = settings.raw.get("browser", {}).get("headless", True)

    from . import auth
    from .prefs import Prefs as _Prefs
    throttle = auth.Throttle()
    if auth.load(settings.data_dir):
        auth.ensure_token(_Prefs(settings.data_dir, settings.raw))  # the `autoapply finish` key, if it went missing

    def _denied(request: Request, to: str):
        """A browser page load goes to `to` (303); anything else (fetch, curl, finish) gets 401."""
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(to, status_code=303)
        return HTMLResponse("sign in first", status_code=401)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        # Sign-in is required everywhere once the account exists, and the account is created first.
        from urllib.parse import quote
        path = request.url.path
        if path.startswith(("/bundle/", "/file/")) and auth.token_ok(request.query_params.get("t")):
            return await call_next(request)  # `autoapply finish` on the laptop: machine key, no cookie
        if path in ("/login", "/logout", "/account"):
            return await call_next(request)  # these routes check for themselves
        account = auth.load(settings.data_dir)
        if auth.valid_cookie(account, request.cookies.get(auth.COOKIE)):
            return await call_next(request)
        if not account:
            t = request.query_params.get("t")
            return _denied(request, "/account" + (f"?t={quote(t)}" if t else ""))
        nxt = path + (f"?{request.url.query}" if request.url.query else "")
        return _denied(request, "/login" + (f"?next={quote(nxt)}" if nxt != "/" else ""))

    def _bare(name: str, status: int = 200, **ctx) -> HTMLResponse:
        # Pre-sign-in pages: no base.html and no inner page() (it would show the nav and the waiting-email count).
        return HTMLResponse(env.get_template(name).render(**ctx), status_code=status)

    def _signed_in(to: str, account: dict) -> RedirectResponse:
        r = RedirectResponse(to, status_code=303)
        r.set_cookie(auth.COOKIE, auth.make_cookie(account), max_age=auth.MAX_AGE, httponly=True, samesite="lax", path="/")
        r.delete_cookie("aa")  # the old token cookie
        return r

    def _upgrade_proof(request: Request, t: str = "") -> bool:
        """An install that had a dashboard password (AUTOAPPLY_TOKEN) and no account yet: only its owner may
        create the account, shown by the old cookie or the old ?t= link. A fresh install has no token yet."""
        if not auth.machine_token():
            return True
        return auth.token_ok(t) or auth.token_ok(request.cookies.get("aa"))

    @app.get("/account")
    def account_page(request: Request, t: str = ""):
        if auth.load(settings.data_dir):
            return RedirectResponse("/", status_code=303)
        return _bare("login.html", mode="create", t=t, proof=_upgrade_proof(request, t), min_len=auth.MIN_LEN)

    @app.post("/account")
    def account_create(request: Request, email: str = Form(""), password: str = Form(""), again: str = Form(""), t: str = Form("")):
        if auth.load(settings.data_dir):
            return RedirectResponse("/", status_code=303)
        if not _upgrade_proof(request, t):
            return _bare("login.html", 403, mode="create", t="", proof=False, min_len=auth.MIN_LEN)
        if err := auth.check_new(email, password, again):
            return _bare("login.html", 400, mode="create", t=t, proof=True, min_len=auth.MIN_LEN, err=err, email=email)
        auth.save(settings.data_dir, email, password)
        auth.ensure_token(_Prefs(settings.data_dir, settings.raw))
        return _signed_in("/", auth.load(settings.data_dir))

    @app.get("/login")
    def login_page(request: Request, next: str = "/"):  # noqa: A002
        account = auth.load(settings.data_dir)
        if not account:
            return RedirectResponse("/account", status_code=303)
        if auth.valid_cookie(account, request.cookies.get(auth.COOKIE)):
            return RedirectResponse(auth.safe_next(next), status_code=303)
        return _bare("login.html", mode="login", next=auth.safe_next(next))

    @app.post("/login")
    def login(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("/")):  # noqa: A002
        account = auth.load(settings.data_dir)
        if not account:
            return RedirectResponse("/account", status_code=303)
        ip = request.client.host if request.client else "?"
        nxt = auth.safe_next(next)
        if throttle.blocked(ip):
            return _bare("login.html", 429, mode="login", next=nxt, email=email,
                         err="Too many wrong tries. Wait a few minutes, then try again.")
        if not auth.verify(account, email, password):
            throttle.fail(ip)
            return _bare("login.html", 401, mode="login", next=nxt, email=email, err="That email and password don't match.")
        throttle.clear(ip)
        return _signed_in(nxt, account)

    @app.post("/logout")
    def logout():
        r = RedirectResponse("/login", status_code=303)
        r.delete_cookie(auth.COOKIE, path="/")
        return r

    def load(job_id):
        job = db.get(job_id)
        if not job:
            raise HTTPException(404)
        return job, json.loads(job["plan_json"] or "{}"), json.loads(job["report_json"] or "{}")

    ws_label, _ = work_search(settings)
    env.globals["ws_label"] = ws_label

    def page(name: str, **ctx) -> HTMLResponse:  # noqa: F811  every page shows the waiting-email badge
        from . import setup
        return HTMLResponse(env.get_template(name).render(pending_count=len(db.pending_events()),
                                                          setup_left=len(setup.status(settings, os.environ)["left"]), **ctx))

    @app.get("/")
    def index(msg: str = "", log: str = ""):
        if settings.raw.get("_from_example"):
            return RedirectResponse("/setup", status_code=303)  # fresh install
        from . import prep
        from . import nudges
        todo = nudges.compute(db, settings.data_dir, settings=settings)
        for n in todo:
            n["compose"] = nudges.gmail_compose_url(n)
        from .prefs import Prefs
        from .rank import shortlist
        s = stats.compute(db, floor=work_search(settings)[1])
        more = shortlist(db, settings, SHORTLIST - len(s["ready"]), skip_companies=[j["company"] for j in s["ready"]])
        from . import skills as sk
        if sk.enabled(Prefs(settings.data_dir, settings.raw)) and (my := sk.mine(settings)):
            for j in [*s["ready"], *more]:
                j["skill_line"] = sk.summary(sk.for_job(db.get(j["id"]) or j, my))
        now = datetime.now()
        s["now_hour"] = now.hour
        from . import jobsources
        from . import pal
        src = jobsources.overview(settings, db)
        first_name = (settings.profile or {}).get("first_name", "")
        cel = pal.celebration(db, s, now.date(), label=work_search(settings)[0])
        from . import coach
        ivs = prep.interviews(db, settings.data_dir)
        greet = pal.greeting(db, s, now, first_name)
        wk_plan = coach.plan(db, s["this_week_start"])
        back = greet["state"] == "back"
        resp = page("index.html", s=s, shortlist=more, decline_reasons=DECLINE_REASONS, src_on=src["on"], src_total=src["total"], first_name=first_name,
                    interviews=ivs[:6], greet=greet, plan=wk_plan, plan_line=coach.plan_line(wk_plan), plan_days=coach.DAYS,
                    plan_open=not wk_plan and f"pal:plan-skip:{s['this_week_start'].isoformat()}" not in db.nudge_states(),
                    offer=None if back else coach.offer(db, settings, s, now.date(), bool(ivs)), back=back, if_then=coach.if_then(db),
                    celebrate=cel, rejection=pal.rejection_note(db, now.date()), week_left=_week_left(s, now.date()),
                    todo=todo, nav="dashboard", running=run_state(), picks_default=Prefs(settings.data_dir, settings.raw).limits()["picks_per_day"],
                    msg=msg[:300], open_log=log == "1", today=now.date().isoformat())
        if cel:
            db.set_nudge(cel["key"], "done")  # each celebration plays once
        return resp

    def _week_left(s: dict, today: date) -> str:
        """The pal's line for the weekly minimum: quiet when covered, one gentle line when short."""
        left = max(0, s["dua_floor"] - s["this_week"])
        if not left:
            return "This week is covered."
        when = "today" if today.weekday() == 5 else "by Saturday"  # weeks run Sunday to Saturday
        return f"{'One more' if left == 1 else f'{left} more'} {when} covers this week."

    @app.post("/applications/log")
    def log_application(company: str = Form(""), title: str = Form(""), url: str = Form(""), applied_on: str = Form(""),
                        via: str = Form(""), pay: str = Form("")):
        """One application you sent outside the tool. The same role is never added twice."""
        from . import history
        try:
            r = history.log(db, company, title, url=url.strip(), applied_on=applied_on.strip(), via=via, pay=pay.strip())
        except ValueError as e:
            return RedirectResponse(f"/?log=1&msg={quote(str(e))}#applications", status_code=303)
        j = r["job"]
        if r["status"] == "already":
            when = (j.get("submitted_at") or "")[:10]
            msg = f"You already have {j['title']} at {j['company']}{' from ' + when if when else ''}, so nothing was added."
        else:
            msg = (f"Added {j['title']} at {j['company']}. That's one more door you knocked on. It counts toward your week,"
                   " and the daily run won't offer that role again.")
        return RedirectResponse(f"/?msg={quote(msg)}#applications", status_code=303)

    @app.post("/applications/import")
    async def import_applications(file: UploadFile = File(...)):
        from . import history
        raw = await file.read()
        if len(raw) > 2_000_000:
            return RedirectResponse(f"/?msg={quote('That file is over 2 MB. Export just the tracker sheet as CSV.')}#applications",
                                    status_code=303)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        before = len(db.by_status("submitted"))
        try:
            added = history.import_csv(db, text)
        except Exception as e:  # a malformed CSV shouldn't take the dashboard down
            return RedirectResponse(f"/?msg={quote('Could not read that CSV: ' + str(e)[:120])}#applications", status_code=303)
        marked = len(db.by_status("submitted")) - before - added
        msg = (f"Imported {added} application{'' if added == 1 else 's'}"
               + (f", and marked {marked} the tool already knew as applied" if marked > 0 else "")
               + ". Ones you already had were left as they were." if added or marked > 0 else
               "Nothing new in that file: every application in it is already here, or it has no Company, Position and Date Applied columns.")
        return RedirectResponse(f"/?msg={quote(msg)}#applications", status_code=303)

    @app.get("/applications.csv")
    def export_applications():
        from . import history
        return Response(history.export_csv(db), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="applications-{date.today().isoformat()}.csv"'})

    @app.post("/pal/seen")
    def pal_seen(key: str = Form(...), back: str = Form("/")):
        """Puts away a pal note (a rejection note) so it doesn't come back."""
        from . import auth as _auth
        if key.startswith(("pal:", "celebrate:")):
            db.set_nudge(key, "done")
        return RedirectResponse(_auth.safe_next(back), status_code=303)

    def start_run(**extra) -> bool:
        """Starts scripts/daily.sh in the background (manual trigger). False when a run is already going."""
        import subprocess
        if run_state():
            return False
        script = Path(__file__).resolve().parent.parent / "scripts" / "daily.sh"
        log = open(settings.data_dir / "cron.log", "a")
        env = {**os.environ, "AUTOAPPLY_TRIGGER": "manual", **extra}
        subprocess.Popen(["bash", str(script)], cwd=script.parent.parent, env=env, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)  # keeps going if the dashboard restarts
        time.sleep(0.5)  # let it take the lock so the page shows it running
        return True

    @app.post("/decline/{job_id:path}")
    def decline(job_id: str, reason: str = Form("other")):
        """Decline from the dashboard: the role leaves Ready for you, and the reason counts in Stats."""
        job, _, _ = load(job_id)
        label = DECLINE_REASONS.get(reason, "other")
        if job["status"] in ("new", "filled"):
            db.update(job_id, status="skipped", error=f"Declined ({label})")
            from . import coach
            coach.touch(db)
            from . import leads
            leads.ensure(db)
            db.conn.execute("update leads set status = 'dismissed' where job_id = ?", (job_id,))
            db.conn.commit()
        return RedirectResponse("/#ready-h", status_code=303)

    @app.post("/prepare/{job_id:path}")
    def prepare(job_id: str):
        """Prepare one shortlisted role now: tailor and fill it. Uses credits; never submits."""
        job, _, _ = load(job_id)
        from . import coach
        coach.touch(db)
        if job["status"] == "new" and start_run(AUTOAPPLY_JOB=job_id, AUTOAPPLY_PICKS="1"):
            db.log_run("run-now", True, f"prepare: {job_id}")
        return RedirectResponse("/", status_code=303)

    def run_state() -> dict | None:
        """The run going right now, from daily.sh's lock and progress line; None when nothing runs."""
        import fcntl
        lock = settings.data_dir / "daily" / ".lock"
        if not lock.exists():
            return None
        with open(lock) as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return None  # nobody holds it
            except OSError:
                pass
        try:
            started, trigger, step = (settings.data_dir / "daily" / ".running").read_text().strip().split("\t", 2)
            at = datetime.fromisoformat(started).strftime("%-I:%M %p").lower()
        except (OSError, ValueError):
            started, trigger, step, at = "", "", "", ""
        return {"at": at, "trigger": trigger, "step": step}

    @app.post("/run")
    def run_now(picks: int = Form(2)):
        """Run now: the same pass as the morning run, for more applications today. Never submits anything."""
        from . import coach
        coach.touch(db)
        if start_run(AUTOAPPLY_PICKS=str(max(1, min(5, picks)))):
            db.log_run("run-now", True, f"started with {picks} role{'s' if picks != 1 else ''}")
        return RedirectResponse("/", status_code=303)

    @app.post("/nudge/{key}")
    def nudge_action(key: str, action: str = Form(...), days: int = Form(3)):
        from datetime import timedelta
        if key.startswith("task-") and key[5:].isdigit() and action == "done":  # an unemployment to-do you added
            from . import benefits
            benefits.set_task(db, int(key[5:]), done=True)
            return RedirectResponse("/#todo", status_code=303)
        if action == "done":
            db.set_nudge(key, "done")
            from . import coach
            coach.touch(db)
        elif action == "snooze":
            db.set_nudge(key, "snoozed", (datetime.now() + timedelta(days=max(1, min(days, 30)))).strftime("%Y-%m-%d %H:%M"))
        elif action == "reopen":
            db.set_nudge(key, None)
        else:
            raise HTTPException(400)
        return RedirectResponse("/#todo", status_code=303)

    @app.post("/plan")
    async def plan_save(request: Request):
        """The person's own plan for this week. Optional; nothing reminds them of it (reminders added nothing in the trial)."""
        from . import coach
        f = await request.form()
        week = stats.week_start(date.today())
        if f.get("action") == "skip":
            db.set_nudge(f"pal:plan-skip:{week.isoformat()}", "done")
        else:
            coach.save_plan(db, week, str(f.get("roles") or ""), [str(d) for d in f.getlist("days")], str(f.get("contact") or ""))
        return RedirectResponse("/#plan", status_code=303)

    @app.post("/contacts")
    def contact_action(action: str = Form("add"), name: str = Form(""), company: str = Form(""), how: str = Form(""),
                       note: str = Form(""), at: str = Form(""), cid: int = Form(0), counts: str = Form("")):
        """People you got in touch with about work. They go in the work-search log as networking contacts."""
        from . import coach
        if action == "add":
            coach.add_contact(db, name, company, how, note, at)
        elif action == "delete" and cid:
            coach.delete_contact(db, cid)
        elif action == "counts":
            coach.set_note(db, "ws:count_contacts", counts == "yes")
        return RedirectResponse("/dua#people", status_code=303)

    @app.get("/reflect")
    def reflect_page(back: str = ""):
        from . import auth as _auth
        from . import coach
        return page("reflect.html", values=coach.VALUES, past=coach.reflections(db), back=_auth.safe_next(back) if back else "",
                    nav="dashboard")

    @app.post("/reflect")
    async def reflect_save(request: Request):
        from . import auth as _auth
        from . import coach
        f = await request.form()
        coach.save_reflection(db, [str(v) for v in f.getlist("values")], str(f.get("text") or ""))
        for k in ("pal:values:early", "pal:values:interview"):
            db.set_nudge(k, "done")
        back = str(f.get("back") or "")
        return RedirectResponse(_auth.safe_next(back) if back else "/reflect#saved", status_code=303)

    @app.get("/letters")
    def letters_page(saved: str = ""):
        """How your cover letters sound: choices with sample lines, words to avoid, notes, letters you liked."""
        from . import voice
        return page("letters.html", nav="settings", v=voice.load(db), tones=voice.TONES, lengths=voice.LENGTHS,
                    openings=voice.OPENINGS, samples={f"{t}|{o}": s for (t, o), s in voice.SAMPLES.items()},
                    common=voice.COMMON_AVOID, recent=voice.recent(settings.data_dir), saved=bool(saved))

    @app.post("/letters")
    async def letters_save(request: Request):
        from . import voice
        f = await request.form()
        voice.save(db, settings.root, str(f.get("tone") or ""), str(f.get("length") or ""), str(f.get("opening") or ""),
                   str(f.get("avoid") or ""), str(f.get("notes") or ""), [str(f.get("sample1") or ""), str(f.get("sample2") or "")])
        return RedirectResponse("/letters?saved=1", status_code=303)

    @app.post("/letter/{job_id:path}")
    def letter_rewrite(job_id: str, note: str = Form(""), keep: str = Form("")):
        """Rewrite this one cover letter with your note, then refill the form. Uses credits; never submits."""
        from . import coach, voice
        job, plan, _ = load(job_id)
        note = " ".join(note.split())[:600]
        slug = voice.letter_slug(plan, settings.data_dir)
        if job["status"] == "submitted" or not slug:
            return RedirectResponse(f"/job/{job_id}", status_code=303)
        coach.touch(db)
        coach.set_note(db, f"letter-note:{job_id}", {"note": note, "at": datetime.now().strftime("%Y-%m-%d %H:%M")})
        if keep and note:
            voice.add_note(db, settings.root, note)
        if start_run(AUTOAPPLY_JOB=job_id, AUTOAPPLY_LETTER="1"):
            db.log_run("run-now", True, f"letter: {job_id}")
            db.update(job_id, error=None)
        else:
            db.update(job_id, error="Another run is going. Try the rewrite again when it finishes.")
        return RedirectResponse(f"/job/{job_id}#letter", status_code=303)

    @app.post("/setback")
    def setback_save(if_then: str = Form(""), key: str = Form("")):
        """Saves the person's own plan for a hard day; shown again with the next rejection."""
        from . import coach
        coach.set_note(db, "setback:ifthen", " ".join(if_then.split())[:200] or None)
        if key.startswith("pal:setback:"):
            db.set_nudge(key, "done")
        return RedirectResponse("/", status_code=303)

    @app.post("/titles/add")
    def titles_add(title: str = Form(...), back: str = Form("/skills#titles")):
        """Adds a related title to the search (config.yaml), so the next run looks for it too."""
        from . import auth as _auth
        from . import setup
        setup.add_title(settings, title)
        return RedirectResponse(_auth.safe_next(back), status_code=303)

    @app.get("/leads")
    def leads_page(show: str = "open"):
        from . import leads
        from .prefs import Prefs
        from .rank import Applied
        every = leads.rows(db)
        applied = Applied(db, int(Prefs(settings.data_dir, settings.raw).data.get("reapply_after_days", 90) or 0))
        for r in every:
            r["applied"] = "" if r["job_id"] else applied.why(r["company"], r["title"], r["url"])
        groups = {"open": [r for r in every if r["status"] in ("new", "starred") and not r["job_id"]],
                  "starred": [r for r in every if r["status"] == "starred"],
                  "tracked": [r for r in every if r["job_id"]],
                  "dismissed": [r for r in every if r["status"] == "dismissed"], "all": every}
        show = show if show in groups else "open"
        tabs = [("open", "To look at"), ("starred", "Starred"), ("tracked", "Tracked"), ("dismissed", "Dismissed"), ("all", "All")]
        from . import jobsources
        src = jobsources.overview(settings, db)
        return page("leads.html", rows=groups[show][:500], tabs=[(k, l, len(groups[k])) for k, l in tabs], show=show, nav="leads",
                    running=run_state(), src=src, src_open=src["on"] < src["total"] // 2 or not every)

    @app.post("/leads/apply")
    def lead_apply(key: str = Form(...)):
        """Auto apply on one lead: find it on the company's site, tailor and fill. Never submits."""
        from . import leads
        if not leads.get(db, key) or run_state():
            return RedirectResponse("/leads", status_code=303)
        leads.set_status(db, key, "starred")
        if start_run(AUTOAPPLY_LEAD=key, AUTOAPPLY_PICKS="1"):
            db.log_run("run-now", True, f"auto apply: {key}")
        return RedirectResponse("/leads?show=starred", status_code=303)

    @app.post("/leads")
    def lead_action(key: str = Form(...), status: str = Form(...), show: str = Form("open")):
        from . import leads
        try:
            leads.set_status(db, key, status)
        except ValueError:
            raise HTTPException(400)
        return RedirectResponse(f"/leads?show={show}#leads", status_code=303)

    @app.get("/stats")
    def stats_page():
        return page("stats.html", s=stats.detail(db, floor=work_search(settings)[1]), nav="stats")

    @app.get("/skills")
    def skills_page():
        from . import learn
        from . import coach
        return page("learn.html", g=learn.gaps(db, settings), nav="skills", related=coach.related_titles(db, settings),
                    my_titles=(settings.raw.get("search") or {}).get("title_keywords") or [])

    @app.post("/skills/mark")
    def skills_mark(skill: str = Form(...), mark: str = Form(...)):
        from . import learn
        learn.set_mark(settings, skill, mark)
        return RedirectResponse("/skills", status_code=303)

    @app.get("/job/{job_id:path}")
    def job_page(job_id: str):
        job, plan, report = load(job_id)
        shown = {k: v for k, v in plan.items() if k not in ("approved", "approved_by_user")}
        files = [(slot, Path(p).name) for slot, p in plan.get("files", {}).items() if _servable(p)]
        from . import preflight
        checks = preflight.for_job(db, settings, job_id) if job["status"] != "submitted" else []
        from . import coach, voice
        rs = run_state()
        letter = {"can": job["status"] != "submitted" and bool(voice.letter_slug(plan, settings.data_dir)),
                  "last": coach.note(db, f"letter-note:{job_id}"),
                  "busy": bool(rs and rs["step"] in (f"letter {job_id}", f"refilling {job_id}")),
                  "voice_set": voice.is_set(db)}
        return page("job.html", nav="", job=job, report=report, approved=plan.get("approved", {}), files=files, checks=checks,
                    blocked=preflight.blocking(checks), letter=letter,
                    notes=_notes(plan), plan_text=json.dumps(shown, indent=1), handoff=_handoff(job, report))

    def _handoff(job: dict, report: dict) -> str:
        # The bot never works around captchas: when one blocks Submit, you finish on the site.
        if job["status"] == "submitted" or report.get("submitted"):
            return ""
        errs = " ".join(str(e.get("error", "")) for e in report.get("errors", []))
        if "captcha" in errs.lower():
            return "The site showed a captcha, which only you can answer."
        if report.get("submit_clicked"):
            return "Submit was pressed but no confirmation came back."
        return ""

    @app.get("/shot/{job_id:path}")
    def shot(job_id: str):
        job, _, _ = load(job_id)
        p = Path(job["screenshot"] or "")
        if not p.exists() or shots.resolve() not in p.resolve().parents:
            raise HTTPException(404)
        return FileResponse(p)

    def _servable(p: str) -> bool:
        # Only files inside data/ or materials/: the answers box is editable, so never serve arbitrary paths.
        try:
            rp = Path(p).resolve()
        except (OSError, TypeError):
            return False
        roots = [settings.data_dir.resolve(), (settings.root / "materials").resolve()]
        return rp.is_file() and any(r in rp.parents for r in roots)

    def _notes(plan: dict) -> str:
        # notes.md sits next to the tailored resume (data/applications/<slug>/notes.md).
        for p in plan.get("files", {}).values():
            n = Path(p).parent / "notes.md"
            if _servable(str(n)):
                return n.read_text()[:20000]
        return ""

    @app.get("/bundle/{job_id:path}")
    def bundle(job_id: str):
        """Everything `autoapply finish` needs to fill the form in a visible browser on your laptop."""
        job, plan, _ = load(job_id)
        plan = {**plan, "approved_by_user": False}
        slots = {slot: Path(p).name for slot, p in plan.get("files", {}).items() if _servable(p)}
        return {"job": {k: job[k] for k in ("id", "company", "title", "url", "apply_url")},
                "plan": plan, "files": slots, "profile": settings.profile}

    @app.get("/file/{slot}/{job_id:path}")
    def doc(slot: str, job_id: str):
        _, plan, _ = load(job_id)
        p = plan.get("files", {}).get(slot)
        if not p or not _servable(p):
            raise HTTPException(404)
        return FileResponse(p)

    proof_root = settings.data_dir / "proof"

    def _record_applied(job: dict, shot: str | None):
        """An 'applied' event for the DUA record, with the after-submit screenshot as proof."""
        when = datetime.now()
        proof = None
        if shot and Path(shot).exists():
            from .emailsync import week_dir
            d = week_dir(proof_root, when)
            d.mkdir(parents=True, exist_ok=True)
            proof = str(d / f"{when:%Y-%m-%d_%H%M}_{job['company']}_applied.png")
            shutil.copy(shot, proof)
        db.add_event({"id": f"applied:{job['id']}", "job_id": job["id"], "kind": "applied", "at": f"{when:%Y-%m-%d %H:%M}",
                      "sender": job["company"], "subject": f"Applied: {job['title']}", "proof": proof})

    @app.post("/sync")
    async def sync_now():
        from . import emailsync
        try:
            counts = await run_in_threadpool(emailsync.sync, db, 7, settings.raw.get("recruiter_senders"), proof_root)
            db.log_run("sync-email", True, ", ".join(f"{v} {k}" for k, v in counts.items()) or "nothing new")
            try:
                from . import leads
                await run_in_threadpool(leads.sync, db, settings, 3)
            except Exception:
                pass
            from .cli import _review
            await run_in_threadpool(_review, settings, db)
        except Exception as e:  # shown on the strip; no traceback page
            db.log_run("sync-email", False, str(e))
        return RedirectResponse("/emails" if db.pending_events() else "/", status_code=303)

    @app.get("/emails")
    def emails(show: str = ""):
        from . import classify
        every = [e for e in db.events(all=True) if e["kind"] != "applied"]
        groups = {"waiting": [e for e in every if not e["reviewed"]],
                  "replies": [e for e in every if e["reviewed"] and e["kind"] in ("confirmed", "interview", "rejected", "offer")],
                  "recruiter": [e for e in every if e["reviewed"] and e["kind"] == "recruiter"],
                  "agency": [e for e in every if e["reviewed"] and e["kind"] == "agency"],
                  "ignored": [e for e in every if e["reviewed"] and e["kind"] == "ignored"],
                  "all": every}
        if show not in groups:  # land on the first tab with something in it
            show = next((k for k in ("waiting", "replies", "recruiter") if groups[k]), "all")
        tabs = [("waiting", "Not sorted", len(groups["waiting"])), ("replies", "Replies", len(groups["replies"])),
                ("recruiter", "Recruiters", len(groups["recruiter"])), ("agency", "Unemployment", len(groups["agency"])), ("ignored", "Not job-related", len(groups["ignored"])),
                ("all", "All", len(every))]
        from .prefs import PROVIDERS, Prefs
        chain = Prefs(settings.data_dir, settings.raw).chain()
        name = " then ".join(PROVIDERS[p]["name"] for p in chain[:2]) if chain else "Nobody (no model source is on)"
        jobs = sorted(db.by_status("submitted", "filled"), key=lambda j: (j["company"] or "").lower())
        return page("emails.html", rows=groups[show][:300], tabs=tabs, show=show, kinds=KIND_LABELS, jobs=jobs,
                    classifier=name, nav="emails")

    @app.post("/emails/{event_id:path}")
    def set_email(event_id: str, kind: str = Form(""), job: str = Form(""), show: str = Form("waiting")):
        from . import emailsync
        ev = db.get_event(event_id)
        if not ev:
            raise HTTPException(404)
        job_id = None if job == "none" else (job or "")
        if not kind:  # only the application changed on an unsorted email
            if ev["reviewed"]:
                kind = ev["kind"]
            else:
                db.set_event(event_id, job_id=job_id or None)
                return RedirectResponse(f"/emails?show={show}", status_code=303)
        try:
            emailsync.review_event(db, event_id, kind, job_id=job_id, manual=True)
            from . import coach
            coach.touch(db)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))
        return RedirectResponse(f"/emails?show={show}", status_code=303)

    @app.get("/prep/{job_id:path}")
    def prep_page(job_id: str):
        from . import prep
        job = db.get(job_id)
        if not job:
            raise HTTPException(404)
        row = next((r for r in prep.interviews(db, settings.data_dir) if r["job"]["id"] == job_id), None)
        p = prep.prep_path(settings.data_dir, job)
        body = prep.render(p.read_text()) if p.exists() else ""
        from . import coach
        return page("prep.html", job=job, row=row, body=body, nav="dashboard", reflected=bool(coach.reflections(db)))

    @app.get("/settings")
    def settings_page(msg: str = "", tab: str = "sorting"):
        if tab == "setup":
            return RedirectResponse("/setup", status_code=303)
        tab = tab if tab in ("sorting", "daily", "costs") else "sorting"
        from . import classify
        from .prefs import DAILY_AGENTS, DAILY_MODELS, PROVIDERS, Prefs
        pr = Prefs(settings.data_dir, settings.raw)
        st = classify.status(pr)
        orm = classify.openrouter_models(settings.data_dir / "openrouter-models.json") if (
            "openrouter" in pr.data["enabled"] or pr.key("OPENROUTER_API_KEY") or pr.data.get("daily_via") == "openrouter") else []
        u30 = db.usage_summary(30)
        daily = u30.get("daily") or {}
        sorting = [v for k, v in u30.items() if k != "daily"]
        costs = {"daily_runs": daily.get("calls") or 0, "daily_tokens": daily.get("tokens") or 0, "daily_est": daily.get("est") or 0,
                 "sort_est": sum(v.get("est") or 0 for v in sorting),
                 "sort_cost": sum(v.get("cost") or 0 for v in sorting) + (daily.get("cost") or 0),
                 "month_spend": db.spend_this_month(), "by_day": db.usage_by_day(14), "by_stage": db.usage_by_stage(30)}
        from . import skills as sk
        return page("settings.html", skills_est=sk.estimate(pr), skills_text=sk.to_lines(sk.mine(settings)),
                    skills_usage=db.conn.execute("select count(*), coalesce(sum(tokens),0), coalesce(sum(cost),0), coalesce(sum(emails),0)"
                                                 " from usage where source = 'skills' and at >= date('now', '-30 day')").fetchone(),
                    p=pr.data, prefs=pr, providers=PROVIDERS, status=st, usage=u30, costs=costs,
                    or_models=orm, daily_models=DAILY_MODELS, daily_agents=DAILY_AGENTS, key_hint=pr.key_hint("OPENROUTER_API_KEY"),
                    pending=len(db.pending_events()), msg=msg, nav="settings", tab=tab,
                    daily=pr.daily(db.spend_this_month()), or_default=__import__("autoapply.prefs", fromlist=["x"]).DAILY_OR_DEFAULT)

    @app.post("/settings")
    async def save_settings(request: Request):
        from . import classify
        from .prefs import DAILY_AGENTS, DAILY_MODELS, PROVIDERS, Prefs
        f = await request.form()
        pr = Prefs(settings.data_dir, settings.raw)
        d = pr.data
        if "sources_form" in f or any(k.startswith("on::") for k in f):  # only the Email sorting tab has these
            d["enabled"] = [p for p in d["order"] if f.get(f"on::{p}")]
        for p in PROVIDERS:
            if f"model::{p}" in f:
                d["models"][p] = str(f.get(f"model::{p}") or "").strip()[:120]
        try:
            d["min_confidence"] = max(0.0, min(1.0, float(f.get("min_confidence") or d["min_confidence"])))
        except ValueError:
            pass
        if "daily_model" in f and f.get("daily_model", "") in DAILY_MODELS:
            d["daily_model"] = f.get("daily_model", "")
        if f.get("daily_agent") in DAILY_AGENTS:
            d["daily_agent"] = f.get("daily_agent")
        if "daily_light_model" in f and f.get("daily_light_model", "") in DAILY_MODELS:
            d["daily_light_model"] = f.get("daily_light_model", "")
        for k in ("daily_codex_light_model", "daily_or_light_model", "quick_pick_model"):
            if k in f:
                v = str(f.get(k) or "").strip()
                if re.fullmatch(r"[A-Za-z0-9._:/~\[\]-]{0,120}", v):
                    d[k] = v
        if "discover_weekday" in f:
            try:
                d["discover_weekday"] = max(0, min(7, int(f.get("discover_weekday"))))
            except (TypeError, ValueError):
                pass
        if f.get("daily_via") in ("subscription", "openrouter"):
            d["daily_via"] = f.get("daily_via")
        if "daily_or_model" in f:
            om = str(f.get("daily_or_model") or "").strip()
            if re.fullmatch(r"[A-Za-z0-9._:/~\[\]-]{0,120}", om):  # also ends up on daily.sh's command line
                d["daily_or_model"] = om
        if "daily_codex_model" in f:
            cm = str(f.get("daily_codex_model") or "").strip()
            if re.fullmatch(r"[A-Za-z0-9._:/-]{0,80}", cm):  # it ends up on daily.sh's command line
                d["daily_codex_model"] = cm
        for k, lo, hi in (("picks_per_day", 0, 5), ("prep_per_day", 0, 5), ("drafts_per_day", 0, 20)):
            try:
                d[k] = max(lo, min(hi, int(f.get(k, d[k]))))
            except (TypeError, ValueError):
                pass
        if "skills_form" in f:
            d["skills_enabled"] = bool(f.get("skills_enabled"))
            if f.get("skills_via") in ("openrouter", "claude"):
                d["skills_via"] = f.get("skills_via")
            sm = str(f.get("skills_model") or "").strip()
            if re.fullmatch(r"[A-Za-z0-9._:/~\[\]-]{0,120}", sm):
                d["skills_model"] = sm
            try:
                d["skills_per_day"] = max(5, min(100, int(f.get("skills_per_day") or 25)))
            except ValueError:
                pass
            if "my_skills" in f:
                from . import skills as sk
                sk.save_mine(settings, sk.parse_lines(str(f.get("my_skills") or "")))
        if "limits_form" in f:
            d["prep_enabled"], d["drafts_enabled"] = bool(f.get("prep_enabled")), bool(f.get("drafts_enabled"))
        try:
            d["monthly_api_budget"] = max(0.0, min(1000.0, float(f.get("monthly_api_budget", d["monthly_api_budget"]))))
        except (TypeError, ValueError):
            pass
        url = str(f.get("ollama_url") or "").strip()
        if url.startswith(("http://", "https://")):
            d["ollama_url"] = url.rstrip("/")
        key = str(f.get("openrouter_key") or "").strip()
        if key:
            pr.set_key("OPENROUTER_API_KEY", key)
        if f.get("forget_key"):
            pr.set_key("OPENROUTER_API_KEY", "")
        action, msg = str(f.get("action") or "save"), "Saved."
        verb, _, name = action.partition(":")
        if name in d["order"] and verb in ("up", "down"):
            i = d["order"].index(name)
            j = i - 1 if verb == "up" else i + 1
            if 0 <= j < len(d["order"]):
                d["order"][i], d["order"][j] = d["order"][j], d["order"][i]
            msg = f"Moved {PROVIDERS[name]['name']} {verb}."
        pr.save()
        if verb == "test" and name in PROVIDERS:
            r = await run_in_threadpool(classify.test_source, name, pr)
            d.setdefault("tests", {})[name] = {**r, "at": datetime.now().strftime("%b %-d, %-I:%M %p"), "model": pr.model(name)}
            pr.save()
            msg = ""
        elif verb == "skills" and name in ("build", "tag"):
            from . import skills as sk
            try:
                if name == "build":
                    n = await run_in_threadpool(sk.build_from_resume, settings, pr, db)
                    msg = f"Drafted {n} skills from your resume. Check and edit the list, then Save."
                else:
                    r = await run_in_threadpool(sk.tag, db, settings, pr, None)
                    msg = r.get("skipped") or f"Listed skills for {r['tagged']} of {r['roles']} roles."
            except Exception as e:
                msg = f"Skill matching: {str(e)[:160]}"
        elif verb == "sort":
            from .cli import _review
            r = await run_in_threadpool(_review, settings, db)
            n = sum(v for k, v in r.items() if k not in ("left", "errors", "error"))
            msg = f"Sorted {n} email{'' if n == 1 else 's'}; {r.get('left', 0)} still waiting." + (
                " Failed: " + "; ".join(f"{k}: {v[:80]}" for k, v in r["errors"].items()) if r.get("errors") else "")
        from urllib.parse import quote
        tab = str(f.get("tab") or "sorting")
        tab = tab if tab in ("sorting", "daily", "costs") else "sorting"
        return RedirectResponse(f"/settings?tab={tab}&msg={quote(msg)}" + (f"#src-{name}" if name else ""), status_code=303)

    # ---- first-run setup: writes profile.yaml, config.yaml, materials/ and data/secrets.json ----
    def _back(msg: str, anchor: str = "") -> RedirectResponse:
        from urllib.parse import quote
        return RedirectResponse(f"/setup?msg={quote(msg)}" + (f"#{anchor}" if anchor else ""), status_code=303)

    @app.get("/setup")
    def setup_page(msg: str = "", err: str = ""):
        from . import setup
        from .finder import FEEDS
        from .prefs import Prefs
        st = setup.status(settings, os.environ)
        prof = setup.load_profile(settings.root)
        if not st["steps"]["profile"]["done"]:
            # Blank out the example's Jane Doe values, then prefill from the resume.
            example = setup._yaml(settings.root / "profile.example.yaml")
            prof = {k: ("" if example.get(k) == v and k not in ("work_authorized", "requires_sponsorship", "willing_to_relocate",
                                                                "how_did_you_hear") else v) for k, v in prof.items()}
            for k, v in setup.resume_contact(setup.base_resume(settings.root)).items():
                prof[k] = prof.get(k) or v
        cfg = setup.load_config(settings.root) if not st["fresh"] else {}
        search = cfg.get("search") or {}
        boards = "\n".join(f"{b['ats']} {b['slug']}" for b in cfg.get("boards") or [])
        rss = "\n".join((f"{f['name']} | {f['url']}" if f.get("name") else f["url"]) if isinstance(f, dict) else f
                         for f in cfg.get("rss_feeds") or [])
        from .sources import RSS_PRESETS
        try:
            src_stats = json.loads((settings.data_dir / "sources.json").read_text())
        except (OSError, ValueError):
            src_stats = {}
        pr = Prefs(settings.data_dir, settings.raw)
        return page("setup.html", nav="settings", tab="setup", st=st, standing=setup.STANDING, decline=setup.DECLINE,
                    stand=setup.standing_values(prof), prof=prof, fields=setup.PROFILE_FIELDS, yes_no=setup.YES_NO,
                    titles=", ".join(search.get("title_keywords") or []), exclude=", ".join(search.get("exclude_keywords") or []),
                    us_only=search.get("us_only", True), boards=boards, rss=rss, rss_presets=RSS_PRESETS, src_stats=src_stats,
                    keys={k: pr.key_hint(k) for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "USAJOBS_API_KEY", "USAJOBS_EMAIL")}, feeds=setup.FEED_LABELS,
                    feeds_on=cfg.get("feeds", list(FEEDS)) if cfg else [*FEEDS, "themuse", "himalayas", "jobicy"], ws=cfg.get("work_search") or {}, states=state_rules(),
                    about=setup.load_about(settings.data_dir), about_fields=setup.ABOUT_FIELDS,
                    resume=setup.base_resume(settings.root), gmail_user=os.environ.get("GMAIL_USER", ""),
                    gmail_env=pr.from_env("GMAIL_APP_PASSWORD"),
                    msg=msg, err=err)

    @app.post("/setup/profile")
    async def setup_profile(request: Request):
        from . import setup
        f = dict(await request.form())
        if not (str(f.get("first_name") or "").strip() and str(f.get("last_name") or "").strip()
                and "@" in str(f.get("email") or "")):
            return _back("First name, last name and email are needed.", "profile")
        setup.save_profile(settings, f)
        setup.name_placeholder_resume(settings.root, settings.profile.get("last_name", ""))
        return _back("Saved your contact details to profile.yaml.", "interests")

    @app.post("/setup/interests")
    async def setup_interests(request: Request):
        from . import setup
        f = dict(await request.form())
        if not setup._lines(str(f.get("titles") or "")):
            return _back("Add at least one job title to look for.", "interests")
        from .prefs import Prefs
        pr = Prefs(settings.data_dir, settings.raw)
        for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "USAJOBS_API_KEY", "USAJOBS_EMAIL"):
            v = str(f.get(k) or "").strip()
            if v and not pr.from_env(k):
                pr.set_key(k, v[:200])
        r = setup.save_interests(settings, f)
        env.globals["ws_label"] = (settings.raw.get("work_search") or {}).get("label", "Work search")
        msg = "Saved your job interests to config.yaml."
        if r["bad"]:
            msg += " Couldn't read: " + "; ".join(r["bad"][:5]) + ". Use a careers-page URL, 'greenhouse slug', or a feed URL."
        if r["missing_keys"]:
            msg += " Skipped until you fill in the free API keys box: " + ", ".join(r["missing_keys"]) + "."
        return _back(msg, "about")

    @app.post("/setup/resume")
    async def setup_resume(docx: UploadFile = File(None), pdf: UploadFile = File(None)):
        from . import setup
        limit = 10 * 1024 * 1024
        d = await docx.read(limit + 1) if docx and docx.filename else None
        p = await pdf.read(limit + 1) if pdf and pdf.filename else None
        if not d and not p:
            return _back("Pick your resume's .docx file first.", "resume")
        if (d and len(d) > limit) or (p and len(p) > limit):
            return _back("That file is over 10 MB.", "resume")
        if p and not d and not setup.base_resume(settings.root):
            return _back("The .docx is needed: tailored resumes are built from it. The PDF is optional.", "resume")
        last = settings.profile.get("last_name") or ""
        r = await run_in_threadpool(setup.save_resume, settings.root, last, d, p)
        if r["error"]:
            return _back(r["error"], "resume")
        if not last:  # name it after the resume's own header when contact details aren't saved yet
            guess = setup.resume_contact(setup.base_resume(settings.root)).get("last_name", "")
            if renamed := setup.name_placeholder_resume(settings.root, guess):
                r = {"docx": renamed, "pdf": renamed.replace(".docx", ".pdf") if r["pdf"] else None}
        made = " and ".join(x for x in (r["docx"], r["pdf"]) if x)
        return _back(f"Saved {made} in materials/." + ("" if r["pdf"] or p else
                     " No PDF was made (LibreOffice isn't installed here), so upload one too."), "profile")

    @app.post("/setup/about")
    async def setup_about(request: Request):
        from . import setup
        setup.save_about(settings.root, settings.data_dir, dict(await request.form()))
        return _back("Saved to materials/context/setup.md. The agent reads it before every application.", "gmail")

    @app.post("/setup/gmail")
    async def setup_gmail(request: Request):
        from . import setup
        from .prefs import Prefs
        f = await request.form()
        pr = Prefs(settings.data_dir, settings.raw)
        user = str(f.get("gmail_user") or "").strip()
        pw = re.sub(r"\s", "", str(f.get("gmail_password") or ""))
        if f.get("action") == "forget":
            for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "BRIEF_TO"):
                pr.set_key(k, "")
            return _back("Removed the saved Gmail login.", "gmail")
        pw = pw or (os.environ.get("GMAIL_APP_PASSWORD") or "")
        if "@" not in user or not pw:
            return _back("Enter your Gmail address and an app password.", "gmail")
        problem = await run_in_threadpool(setup.test_gmail, user, pw)
        if problem:
            return _back(f"Not saved: {problem}", "gmail")
        if not pr.from_env("GMAIL_USER"):
            pr.set_key("GMAIL_USER", user)
        if not pr.from_env("GMAIL_APP_PASSWORD"):
            pr.set_key("GMAIL_APP_PASSWORD", pw)
        brief_to = str(f.get("brief_to") or "").strip()
        if "@" in brief_to and not pr.from_env("BRIEF_TO"):
            pr.set_key("BRIEF_TO", brief_to)
        return _back("Gmail works. Job alerts and replies will be read (read-only), and the brief sent from it.", "agent")

    @app.get("/dua")
    def dua(company: str = ""):
        from . import benefits
        from . import coach
        rule = my_state(settings)
        return page("dua.html", people=coach.contacts(db)[:40], how=coach.HOW, contacts_count=coach.contacts_count(db),
                    prefill_company=company[:80], weeks=stats.dua_weeks(db), floor=work_search(settings)[1], rule=rule, nav="work", today=date.today(),
                    claim=benefits.claim(settings), runway=benefits.runway(settings, rule), days=benefits.DAYS,
                    tasks=benefits.tasks(db, include_done=True), resources=benefits.RESOURCES, general=general_notes(),
                    letters=[e for e in db.events() if e["kind"] == "agency"][:8])

    @app.post("/dua/claim")
    async def dua_claim(request: Request):
        from . import benefits
        benefits.save_claim(settings, dict(await request.form()))
        return RedirectResponse("/dua#claim", status_code=303)

    @app.post("/dua/task")
    def dua_task(action: str = Form(...), title: str = Form(""), due: str = Form(""), task_id: int = Form(0)):
        from . import benefits
        if action == "add" and title.strip():
            benefits.add_task(db, title, due)
        elif action == "resea":
            benefits.add_resea(db, (my_state(settings) or {}).get("code", ""))
        elif action == "due" and task_id:
            d = benefits._date(due)
            db.conn.execute("update ui_tasks set due = ? where id = ?", (d.isoformat() if d else None, task_id))
            db.conn.commit()
        elif action in ("done", "undo", "delete") and task_id:
            benefits.set_task(db, task_id, done=action == "done" if action != "delete" else None, delete=action == "delete")
        return RedirectResponse("/dua#tasks", status_code=303)

    @app.get("/dua/{week}.zip")
    def dua_zip(week: str):
        wk = next((w for w in stats.dua_weeks(db) if w["start"].isoformat() == week), None)
        if not wk:
            raise HTTPException(404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["Date", "Activity Type", "Company", "Position", "Pay rate", "How", "Contact", "Result", "Proof files"])
            for r in wk["rows"]:
                w.writerow([r["date"].isoformat(), r["type"], r["company"], r["position"], r.get("pay", ""), r["how"], r["contact"],
                            r["result"], "; ".join(Path(p).name for p in r["proof"])])
            z.writestr(f"work-search-{week}.csv", out.getvalue())
            d = proof_root / week
            for f in sorted(d.iterdir()) if d.is_dir() else []:
                z.write(f, f"proof/{f.name}")
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"content-disposition": f'attachment; filename="work-search-week-{week}.zip"'})

    @app.get("/proof/{week}/{name}")
    def proof_file(week: str, name: str):
        p = (proof_root / week / name).resolve()
        if proof_root.resolve() not in p.parents or not p.is_file():
            raise HTTPException(404)
        return FileResponse(p)

    @app.post("/job/{job_id:path}")
    async def act(job_id: str, request: Request, action: str = Form(...), plan: str = Form("{}"), approve: str = Form("")):
        job, old_plan, old_report = load(job_id)
        form = await request.form()
        from . import coach
        coach.touch(db)
        try:
            new_plan = json.loads(plan)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"answers JSON is invalid: {e}")
        new_plan.setdefault("answers", {})
        for k, v in form.items():
            if k.startswith("ans::") and v:
                new_plan["answers"][k[5:]] = v
        # Held answers come only from this form, never from the JSON box.
        new_plan["approved"] = {k[6:]: v for k, v in form.items() if k.startswith("held::") and v}
        new_plan["held_reviewed"] = True  # from now on a blank consent stays blank: no standing answer fills it
        new_plan["approved_by_user"] = False

        if action == "skip":
            db.update(job_id, status="skipped", plan_json=new_plan)
        elif action == "manual":
            db.update(job_id, status="submitted", plan_json=new_plan, error=None,
                      submitted_at=time.strftime("%Y-%m-%d %H:%M"))
            _record_applied(job, None)
        elif action == "refill":
            r = await run_in_threadpool(fill, new_plan, settings.profile, shots, headless)  # sync Playwright can't share the event loop
            db.update(job_id, status="filled", plan_json=new_plan, report_json=r.as_dict(), screenshot=r.screenshot, error=None)
        elif action == "submit":
            if old_report.get("submit_clicked") and not old_report.get("submitted") and form.get("resubmit") != "yes":
                db.update(job_id, plan_json=new_plan,
                          error="Submit was already pressed once without a confirmation. Check your email, then tick 'submit again' if it really didn't go through.")
                return RedirectResponse(f"/job/{job_id}", status_code=303)
            if approve != "yes":
                db.update(job_id, plan_json=new_plan, error="Tick the review box to submit.")
                return RedirectResponse(f"/job/{job_id}", status_code=303)
            from . import preflight
            db.update(job_id, plan_json=new_plan)  # check what you just chose, not the old answers
            stop = preflight.blocking(preflight.for_job(db, settings, job_id))
            if stop:
                db.update(job_id, error="Not submitted. Fix these first: " + "; ".join(f"{c['group']}: {c['name']}" for c in stop))
                return RedirectResponse(f"/job/{job_id}", status_code=303)
            new_plan["approved_by_user"] = True
            r = await run_in_threadpool(submit, new_plan, settings.profile, shots, headless)
            done = r.submitted
            if r.submit_clicked and not done:
                r.errors.append({"label": "(submit)", "error": "Submit was pressed but not confirmed. Don't retry until you've checked your email."})
            new_plan["approved_by_user"] = False  # one approval, one click
            db.update(job_id, status="submitted" if done else "filled", plan_json=new_plan, report_json=r.as_dict(),
                      screenshot=r.screenshot, error=None if done else "; ".join(e["error"] for e in r.errors),
                      submitted_at=time.strftime("%Y-%m-%d %H:%M") if done else None)
            if done:
                _record_applied(job, r.screenshot)
        return RedirectResponse(f"/job/{job_id}", status_code=303)

    return app
