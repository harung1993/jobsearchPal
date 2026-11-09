"""Review page: nothing submits without the tick box, and consent answers come only from the form."""
import json
from pathlib import Path

import yaml

from autoapply.config import Settings
from autoapply.db import DB
from autoapply.fillers import fill
from web_client import client

from test_fillers import PROFILE, base_url, pdfs  # noqa: F401  (fixtures)

CONSENT = "I acknowledge the Privacy Notice and consent to processing of my personal data"


def setup(tmp_path, base_url, pdfs):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile=PROFILE)
    db = DB(s.data_dir / "t.db")
    url = f"{base_url}/gh/"
    db.upsert_job({"id": "manual:gh", "ats": "greenhouse", "company": "Acme", "title": "AE", "location": "",
                   "url": url, "apply_url": url, "description": ""})
    plan = {"url": url, "ats": "greenhouse", "files": pdfs, "answers": {"Why do you want to work here?": "x"}}
    r = fill(plan, PROFILE, s.data_dir / "screenshots")
    db.update("manual:gh", status="filled", plan_json=plan, report_json=r.as_dict(), screenshot=r.screenshot)
    return db, client(s, db), plan


def test_page_shows_held_consent(tmp_path, base_url, pdfs):
    _, c, _ = setup(tmp_path, base_url, pdfs)
    html = c.get("/job/manual:gh").text
    assert "Check these" in html and "Privacy Notice" in html and "needs you" in html
    assert c.get("/shot/manual:gh").status_code == 200


def test_submit_needs_tick_box(tmp_path, base_url, pdfs):
    db, c, plan = setup(tmp_path, base_url, pdfs)
    c.post("/job/manual:gh", data={"action": "submit", "plan": json.dumps(plan), f"held::{CONSENT}": "yes"})
    assert db.get("manual:gh")["status"] == "filled"


def test_json_box_cannot_smuggle_approval(tmp_path, base_url, pdfs):
    db, c, plan = setup(tmp_path, base_url, pdfs)
    sneaky = {**plan, "approved": {CONSENT: "yes"}}
    c.post("/job/manual:gh", data={"action": "submit", "approve": "yes", "plan": json.dumps(sneaky)})
    job = db.get("manual:gh")
    assert job["status"] == "filled" and "required" in job["error"].lower()


def test_submit_with_consent_and_tick(tmp_path, base_url, pdfs):
    db, c, plan = setup(tmp_path, base_url, pdfs)
    c.post("/job/manual:gh", data={"action": "submit", "approve": "yes", "plan": json.dumps(plan),
                                    f"held::{CONSENT}": "yes", "held::Gender": "Decline to self-identify"})
    job = db.get("manual:gh")
    assert job["status"] == "submitted", job["error"]
    assert json.loads(job["plan_json"])["approved_by_user"] is False


def test_documents_served_only_from_data_dir(tmp_path, base_url, pdfs):
    db, c, plan = setup(tmp_path, base_url, pdfs)  # pdfs live in tmp_path, outside data/
    assert c.get("/file/resume/manual:gh").status_code == 404
    inside = tmp_path / "data" / "applications" / "acme"
    inside.mkdir(parents=True)
    (inside / "r.pdf").write_bytes(b"%PDF-1.4")
    db.update("manual:gh", plan_json={**plan, "files": {"resume": str(inside / "r.pdf"), "cover_letter": "/etc/passwd"}})
    assert c.get("/file/resume/manual:gh").content == b"%PDF-1.4"
    assert c.get("/file/cover_letter/manual:gh").status_code == 404
    assert "r.pdf" in c.get("/job/manual:gh").text


def test_dua_page_and_zip_after_submit(tmp_path, base_url, pdfs):
    import io, zipfile
    db, c, plan = setup(tmp_path, base_url, pdfs)
    c.post("/job/manual:gh", data={"action": "submit", "approve": "yes", "plan": json.dumps(plan),
                                    f"held::{CONSENT}": "yes", "held::Gender": "Decline to self-identify"})
    ev = [e for e in db.events() if e["kind"] == "applied"]
    assert ev and ev[0]["proof"].endswith("_applied.png")
    html = c.get("/dua").text
    assert "Job application" in html and "screenshot" in html
    week = ev[0]["proof"].split("/")[-2]
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/dua/{week}.zip").content))
    names = z.namelist()
    assert f"work-search-{week}.csv" in names and any(n.startswith("proof/") and n.endswith(".png") for n in names)
    assert c.get("/proof/../../etc/passwd").status_code == 404


def test_second_submit_needs_explicit_resubmit(tmp_path, base_url, pdfs):
    db, c, plan = setup(tmp_path, base_url, pdfs)
    rep = json.loads(db.get("manual:gh")["report_json"])
    db.update("manual:gh", report_json={**rep, "submit_clicked": True, "submitted": False})
    c.post("/job/manual:gh", data={"action": "submit", "approve": "yes", "plan": json.dumps(plan),
                                    f"held::{CONSENT}": "yes", "held::Gender": "Decline to self-identify"})
    job = db.get("manual:gh")
    assert job["status"] == "filled" and "already pressed" in job["error"]
    assert "submit again" in c.get("/job/manual:gh").text


def test_captcha_shows_finish_yourself_card(tmp_path, base_url, pdfs):
    db, c, _ = setup(tmp_path, base_url, pdfs)
    assert "Finish this one yourself" not in c.get("/job/manual:gh").text
    rep = json.loads(db.get("manual:gh")["report_json"])
    errs = rep["errors"] + [{"label": "(submit)", "error": "a captcha challenge appeared; finish this one from the posting link"}]
    db.update("manual:gh", report_json={**rep, "errors": errs, "submit_clicked": True})
    html = c.get("/job/manual:gh").text
    assert "Finish this one yourself" in html and "captcha" in html and "Copy" in html


def test_bundle_for_finish_on_mac(tmp_path, base_url, pdfs):
    _, c, _ = setup(tmp_path, base_url, pdfs)
    b = c.get("/bundle/manual:gh").json()
    assert b["job"]["company"] == "Acme" and b["plan"]["approved_by_user"] is False
    assert b["profile"] and "resume" not in b["files"]  # test PDFs sit outside data/, so they aren't served


def test_finish_fills_without_submitting(tmp_path, base_url, pdfs):
    import os
    import pytest
    from autoapply.fillers import handoff
    if not os.environ.get("DISPLAY"):
        pytest.skip("needs a display (run under xvfb-run)")
    plan = {"url": f"{base_url}/gh/", "ats": "greenhouse", "files": pdfs, "answers": {"Why do you want to work here?": "x"}}
    r = handoff(plan, PROFILE, wait=False)
    assert r.filled and not r.submit_clicked and not r.submitted


def test_emails_page_sets_category_and_job(tmp_path, base_url, pdfs):
    from datetime import datetime
    from autoapply import emailsync
    db, c, plan = setup(tmp_path, base_url, pdfs)
    db.update("manual:gh", status="submitted", submitted_at="2026-10-28 10:00")
    emailsync.apply_event(db, db.by_status("submitted"), "<m1>", "Acme", "no-reply@greenhouse.io", "Your application",
                          datetime(2026, 10, 29, 9), "Thanks <b>for applying</b>.")
    html = c.get("/emails").text
    assert "Your application" in html and "Not sorted" in html and "&lt;b&gt;" in html  # escaped body
    r = c.post("/emails/<m1>", data={"kind": "interview", "job": "manual:gh", "show": "waiting"}, follow_redirects=False)
    assert r.status_code == 303
    ev = db.get_event("<m1>")
    assert ev["kind"] == "interview" and ev["manual"] == 1 and db.get("manual:gh")["outcome"] == "interview"
    assert c.post("/emails/<m1>", data={"kind": "bogus"}).status_code == 400
    assert c.post("/emails/<nope>", data={"kind": "ignored"}).status_code == 404


def test_settings_page_order_enable_test_and_key(tmp_path, base_url, pdfs, monkeypatch):
    from autoapply import classify
    from autoapply.prefs import Prefs
    db, c, plan = setup(tmp_path, base_url, pdfs)
    monkeypatch.setattr(classify, "openrouter_models", lambda cache: [{"id": "cheap/model", "name": "Cheap", "in": 0.1, "out": 0.4, "ctx": 1}])
    monkeypatch.setattr(classify, "ollama_models", lambda url: None)
    html = c.get("/settings").text
    assert "Claude subscription" in html and "OpenAI subscription" in html and "Jev" in html and "Ollama" in html
    data = {"on::claude": "1", "on::openrouter": "1", "model::claude": "sonnet", "model::openrouter": "cheap/model",
            "min_confidence": "0.8", "daily_model": "opus", "ollama_url": "http://localhost:11434",
            "openrouter_key": "sk-or-abcd9999", "action": "up:openrouter"}
    assert c.post("/settings", data=data, follow_redirects=False).status_code == 303
    pr = Prefs(tmp_path / "data")
    assert pr.chain() == ["claude", "openrouter"] and pr.data["order"].index("openrouter") == 2
    assert pr.model("claude") == "sonnet" and pr.data["daily_model"] == "opus" and pr.data["min_confidence"] == 0.8
    html = c.get("/settings").text
    assert "sk-or-abcd9999" not in html and "ends 9999" in html and "Cheap · $0.1 in / $0.4 out per M" in html
    monkeypatch.setattr(classify, "_ask_claude", lambda prompt, model: '[{"id": "sample-1", "kind": "interview", "job": "sample:acme"}]')
    c.post("/settings", data={**data, "openrouter_key": "", "action": "test:claude"})
    assert "sorted the sample interview email correctly" in c.get("/settings").text
    c.post("/settings", data={"daily_model": "rm -rf", "action": "save"})
    # a save from another tab leaves the sorting sources alone
    assert Prefs(tmp_path / "data").data["daily_model"] == "opus" and Prefs(tmp_path / "data").chain() == ["claude", "openrouter"]


def test_daily_agent_setting(tmp_path, base_url, pdfs, capsys):
    import yaml as _y
    from autoapply import cli
    from autoapply.prefs import Prefs
    db, c, plan = setup(tmp_path, base_url, pdfs)
    assert "Codex CLI (ChatGPT subscription)" in c.get("/settings?tab=daily").text
    assert "Codex CLI (ChatGPT subscription)" not in c.get("/settings").text  # other tabs don't show it
    c.post("/settings", data={"daily_agent": "codex", "daily_codex_model": "gpt-5; rm -rf ~", "action": "save"})
    assert Prefs(tmp_path / "data").data["daily_agent"] == "codex" and Prefs(tmp_path / "data").data["daily_codex_model"] == ""
    c.post("/settings", data={"daily_agent": "codex", "daily_codex_model": "gpt-5-mini", "action": "save"})
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_y.safe_dump({"data_dir": str(tmp_path / "data")}))
    cli.main(["--config", str(cfg), "daily-agent"])
    assert capsys.readouterr().out.strip() == "codex gpt-5-mini subscription"
    c.post("/settings", data={"daily_agent": "claude", "daily_model": "sonnet", "action": "save"})
    cli.main(["--config", str(cfg), "daily-agent"])
    assert capsys.readouterr().out.strip() == "claude sonnet subscription"


def test_prep_page_and_dashboard_card(tmp_path, base_url, pdfs):
    from autoapply import prep
    db, c, plan = setup(tmp_path, base_url, pdfs)
    db.update("manual:gh", status="submitted", submitted_at="2026-10-28 10:00")
    db.add_event({"id": "i1", "job_id": "manual:gh", "kind": "interview", "at": "2026-10-30 09:00", "sender": "Acme",
                  "subject": "Schedule your recruiter screen", "body": "Pick a time"})
    assert "prep next run" in c.get("/").text
    assert "No prep pack yet" in c.get("/prep/manual:gh").text
    p = prep.prep_path(tmp_path / "data", db.get("manual:gh"))
    p.parent.mkdir(parents=True)
    p.write_text("## What candidates report\n- Asked about dbt tests ([Reddit](https://reddit.com/r/x))\n<img src=x onerror=alert(1)>")
    html = c.get("/prep/manual:gh").text
    assert "<h3>What candidates report</h3>" in html and 'href="https://reddit.com/r/x"' in html and "<img" not in html
    assert "Prep pack" in c.get("/").text
    assert c.get("/prep/nope").status_code == 404


def test_cost_limits_budget_and_daily_log(tmp_path, base_url, pdfs, capsys, monkeypatch):
    import io
    import yaml as _y
    from autoapply import cli
    from autoapply.prefs import Prefs
    db, c, plan = setup(tmp_path, base_url, pdfs)
    c.post("/settings", data={"limits_form": "1", "picks_per_day": "1", "prep_enabled": "1", "prep_per_day": "9",
                              "drafts_per_day": "3", "monthly_api_budget": "2.5", "action": "save"})
    pr = Prefs(tmp_path / "data")
    assert pr.limits() == {"picks_per_day": 1, "prep_per_day": 5, "drafts_per_day": 0}  # capped; drafts switched off
    pr.data["enabled"] = ["claude", "jev", "openrouter"]
    assert pr.chain(spent=1.0) == ["claude", "jev", "openrouter"] and pr.chain(spent=2.5) == ["claude"]
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_y.safe_dump({"data_dir": str(tmp_path / "data")}))
    out = ('{"type":"result","is_error":false,"result":"Wrote the summary.\\nReady to review: Acme (Sr AE)",'
           '"total_cost_usd":1.25,"usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":20000}}')
    monkeypatch.setattr("sys.stdin", io.StringIO(out))
    cli.main(["--config", str(cfg), "log-daily", "claude", "opus"])
    assert capsys.readouterr().out.strip() == "Ready to review: Acme (Sr AE)"
    from autoapply.db import DB as _DB
    u = _DB(tmp_path / "data" / "autoapply.db").usage_summary()["daily"]
    db.log_usage("daily", "claude:opus", 0, 0, 0.0, 0, None, 1.25, 21500)  # the dashboard's own db in this test
    assert u["calls"] == 1 and u["tokens"] == 21500 and abs(u["est"] - 1.25) < 1e-9 and (u["cost"] or 0) == 0
    html = c.get("/settings?tab=costs").text
    assert "Costs and limits" in html and "$1.25" in html and "21,500 tokens" in html
    cli.main(["--config", str(cfg), "list", "--limits"])
    assert '"picks_per_day": 1' in capsys.readouterr().out


def test_todo_card_done_and_snooze(tmp_path, base_url, pdfs):
    from datetime import datetime, timedelta
    db, c, plan = setup(tmp_path, base_url, pdfs)
    at = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
    db.add_event({"id": "r1", "job_id": None, "kind": "recruiter", "at": at, "sender": "Dana Lee <dana@talentco.example>",
                  "subject": "Analytics role", "body": "Free to chat?"})
    html = c.get("/").text
    assert "Reply to Dana Lee" in html and "Reply in Gmail" in html and "mail.google.com/mail/?view=cm" in html
    from autoapply import nudges
    key = nudges.compute(db)[0]["key"]
    assert c.post(f"/nudge/{key}", data={"action": "snooze", "days": "3"}, follow_redirects=False).status_code == 303
    assert "Reply to Dana Lee" not in c.get("/").text
    c.post(f"/nudge/{key}", data={"action": "reopen"})
    assert "Reply to Dana Lee" in c.get("/").text
    c.post(f"/nudge/{key}", data={"action": "done"})
    assert "Reply to Dana Lee" not in c.get("/").text
    assert c.post(f"/nudge/{key}", data={"action": "send"}).status_code == 400


def test_daily_run_on_openrouter(tmp_path, base_url, pdfs, capsys, monkeypatch):
    import io
    import yaml as _y
    from autoapply import classify, cli
    from autoapply.prefs import Prefs
    db, c, plan = setup(tmp_path, base_url, pdfs)
    monkeypatch.setattr(classify, "openrouter_models", lambda cache: [
        {"id": "anthropic/claude-sonnet-4.6", "name": "Sonnet", "in": 3, "out": 15, "ctx": 1},
        {"id": "openai/gpt-5.6-luna", "name": "Luna", "in": 0.2, "out": 0.8, "ctx": 1}])
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_y.safe_dump({"data_dir": str(tmp_path / "data")}))

    c.post("/settings", data={"tab": "daily", "daily_agent": "claude", "daily_via": "openrouter", "action": "save"})
    cli.main(["--config", str(cfg), "daily-agent"])
    assert capsys.readouterr().out.strip() == "claude ~anthropic/claude-sonnet-latest blocked"  # no key yet
    html = c.get("/settings?tab=daily").text
    assert "no OpenRouter key" in html and 'value="anthropic/claude-sonnet-4.6"' in html and "gpt-5.6-luna" not in html.split('id="or-daily"')[1].split("</datalist>")[0]
    assert "gpt-5.6-luna" in html.split('id="or-quick"')[1].split("</datalist>")[0]  # quick pick takes any model

    Prefs(tmp_path / "data").set_key("OPENROUTER_API_KEY", "sk-or-test-1234")
    c.post("/settings", data={"tab": "daily", "daily_or_model": "anthropic/claude-sonnet-4.6; rm -rf ~", "action": "save"})
    assert Prefs(tmp_path / "data").data["daily_or_model"] == ""  # rejected
    c.post("/settings", data={"tab": "daily", "daily_or_model": "anthropic/claude-sonnet-4.6", "action": "save"})
    spent = iter([10.0, 11.75])
    monkeypatch.setattr(classify, "openrouter_spent", lambda key: next(spent))
    cli.main(["--config", str(cfg), "daily-agent"])
    assert capsys.readouterr().out.strip() == "claude anthropic/claude-sonnet-4.6 openrouter"
    cli.main(["--config", str(cfg), "daily-env"])
    env = capsys.readouterr().out
    assert "export ANTHROPIC_BASE_URL=https://openrouter.ai/api" in env and "export ANTHROPIC_API_KEY=''" in env
    assert "ANTHROPIC_AUTH_TOKEN=sk-or-test-1234" in env

    out = '{"type":"result","is_error":false,"result":"Done.","total_cost_usd":1.5,"usage":{"input_tokens":10,"output_tokens":5}}'
    monkeypatch.setattr("sys.stdin", io.StringIO(out))
    cli.main(["--config", str(cfg), "log-daily", "claude", "anthropic/claude-sonnet-4.6", "openrouter"])
    capsys.readouterr()
    from autoapply.db import DB as _DB
    d = _DB(tmp_path / "data" / "autoapply.db")
    assert abs(d.spend_this_month() - 1.75) < 1e-9  # the key's real usage delta, not the estimate

    p = Prefs(tmp_path / "data"); p.data["monthly_api_budget"] = 1.5; p.save()
    cli.main(["--config", str(cfg), "daily-agent"])
    o = capsys.readouterr()
    assert o.out.strip().endswith("blocked") and "budget" in o.err

    c.post("/settings", data={"tab": "daily", "daily_via": "subscription", "action": "save"})
    cli.main(["--config", str(cfg), "daily-agent"])
    assert capsys.readouterr().out.strip() == "claude - subscription"
    cli.main(["--config", str(cfg), "daily-env"])
    assert capsys.readouterr().out == ""


def test_failed_check_keeps_submit_locked(tmp_path, base_url, pdfs):
    import os, time
    db, c, plan = setup(tmp_path, base_url, pdfs)
    resume = Path(next(p for k, p in plan["files"].items() if "resume" in k))
    twin = resume.with_suffix(".docx")
    twin.write_bytes(b"x")
    os.utime(twin, (time.time() + 60, time.time() + 60))  # Word file changed after the PDF was made
    html = c.get("/job/manual:gh").text
    assert "Fix before you submit" in html and "PDF is up to date" in html and "data-blocked" in html
    c.post("/job/manual:gh", data={"action": "submit", "approve": "yes", "plan": json.dumps(plan),
                                    f"held::{CONSENT}": "yes", "held::Gender": "Decline to self-identify"})
    job = db.get("manual:gh")
    assert job["status"] == "filled" and "Fix these first" in job["error"]


def test_run_now_starts_one_run(tmp_path, base_url, pdfs, monkeypatch):
    import fcntl, subprocess
    db, c, _ = setup(tmp_path, base_url, pdfs)
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append((args, kw["env"])))
    assert "Run now" in c.get("/").text
    c.post("/run", data={"picks": "3"})
    assert len(started) == 1 and started[0][0][-1].endswith("scripts/daily.sh")
    assert started[0][1]["AUTOAPPLY_TRIGGER"] == "manual" and started[0][1]["AUTOAPPLY_PICKS"] == "3"
    d = tmp_path / "data" / "daily"
    d.mkdir(exist_ok=True)
    (d / ".running").write_text("2026-11-03T14:10:00-05:00\tmanual\tapply gh:warp:1\n")
    with open(d / ".lock", "w") as f:  # a run holds the lock: the page says so and a second click starts nothing
        fcntl.flock(f, fcntl.LOCK_EX)
        html = c.get("/").text
        assert "Running since 2:10 pm" in html and "apply gh:warp:1" in html
        c.post("/run", data={"picks": "1"})
    assert len(started) == 1


def test_decline_and_prepare_from_dashboard(tmp_path, base_url, pdfs, monkeypatch):
    import subprocess
    from autoapply import leads
    db, c, plan = setup(tmp_path, base_url, pdfs)
    db.upsert_job({"id": "gh:globex:2", "ats": "greenhouse", "company": "Globex", "title": "Data Eng", "location": "Remote",
                   "url": "u", "apply_url": "u", "description": ""})
    leads.ensure(db)
    db.conn.execute("insert into leads (key, title, company, status, job_id) values ('acme|ae', 'AE', 'Acme', 'tracked', 'manual:gh')")
    db.conn.commit()
    html = c.get("/").text
    assert "Review" in html and "Decline" in html and "Prepare" in html and "Shortlist" in html and "Globex" in html and "already applied" in html
    c.post("/decline/manual:gh", data={"reason": "location"})
    job = db.get("manual:gh")
    assert job["status"] == "skipped" and job["error"] == "Declined (location)" and json.loads(job["plan_json"])["answers"]
    assert leads.get(db, "acme|ae")["status"] == "dismissed"
    assert "/job/manual:gh" not in c.get("/").text
    c.post("/decline/gh:globex:2", data={"reason": "bogus"})
    assert db.get("gh:globex:2")["error"] == "Declined (other)"
    db.update("gh:globex:2", status="new", error=None)
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append(kw["env"]))
    c.post("/prepare/gh:globex:2")
    assert len(started) == 1 and started[0]["AUTOAPPLY_JOB"] == "gh:globex:2" and started[0]["AUTOAPPLY_TRIGGER"] == "manual"
    db.update("gh:globex:2", status="filled")
    c.post("/prepare/gh:globex:2")  # already prepared: nothing starts
    assert len(started) == 1


def test_state_work_search_rule(tmp_path, base_url, pdfs):
    """11/4: pick your state on Setup; the work-search log shows its rule and counts toward its weekly number."""
    from autoapply.web import state_rules
    rules = state_rules()
    assert len(rules) == 53 and rules["MA"]["weekly_minimum"] == 3 and {"PR", "VI"} <= set(rules)
    assert all(r["url"].startswith("https://") and r["rule"] and r["checked"] for r in rules.values())
    db, c, _ = setup(tmp_path, base_url, pdfs)
    assert "Pick your state" in c.get("/dua").text
    html = c.get("/setup").text
    assert 'value="MA"' in html and 'id="ws_rules"' in html
