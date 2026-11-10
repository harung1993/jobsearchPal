"""The staged daily run: pre-ranking, stage list, picks, prompts, quick pick and the per-stage cost table."""
import json
from datetime import datetime

import pytest
import yaml

from autoapply import cli, rank
from autoapply.config import Settings
from autoapply.db import DB
from autoapply.prefs import Prefs


def upd(p, **kw):
    p.data.update(kw)
    p.save()


def make(tmp_path):
    (tmp_path / "materials" / "context").mkdir(parents=True)
    (tmp_path / "materials" / "context" / "me.md").write_text("Analytics engineer. dbt, Snowflake, Airflow, Python.")
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data"),
                                     "search": {"title_keywords": ["analytics engineer"]}}, profile={})
    db = DB(s.data_dir / "autoapply.db")
    jobs = [("gh:a:1", "Acme", "Senior Analytics Engineer", "dbt Snowflake Airflow models " * 50),
            ("gh:b:2", "Globex", "Line Cook", "kitchen prep grill"),
            ("wd:c:3", "Initech", "Analytics Engineer", "dbt Python")]
    for jid, co, title, desc in jobs:
        db.upsert_job({"id": jid, "ats": "workday" if jid.startswith("wd") else "greenhouse", "company": co,
                       "title": title, "location": "Remote", "url": "u", "apply_url": "u", "description": desc})
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(s.raw))
    return s, db, cfg


def test_candidates_rank_and_trim(tmp_path):
    s, db, _ = make(tmp_path)
    c = rank.candidates(db, s, limit=2, desc_chars=100)
    assert [x["id"] for x in c] == ["gh:a:1", "wd:c:3"]
    assert len(c[0]["description"]) <= 101 and c[0]["description"].endswith("…")
    assert db.get("gh:b:2")["score"] < db.get("gh:a:1")["score"]


def test_stages_picks_and_prompt(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    cli.main(["--config", str(cfg), "daily-stages"])
    assert capsys.readouterr().out.split()[-1] == "rank"
    (s.data_dir / "daily").mkdir(exist_ok=True)
    (s.data_dir / "daily" / "picks.json").write_text(json.dumps(
        [{"id": "gh:a:1"}, {"id": "nope"}, {"id": "wd:c:3"}, {"id": "gh:b:2"}, {"id": "x"}, {"id": "y"}]))
    cli.main(["--config", str(cfg), "daily-picks"])
    out = capsys.readouterr().out.split()
    assert out[:2] == ["gh:a:1", "wd:c:3"] and "nope" not in out
    cli.main(["--config", str(cfg), "daily-prompt", "apply", "gh:a:1"])
    text = capsys.readouterr().out
    assert "gh:a:1" in text and "{{JOB_ID}}" not in text
    with pytest.raises(SystemExit):
        cli.main(["--config", str(cfg), "daily-prompt", "../daily"])
    with pytest.raises(SystemExit):
        cli.main(["--config", str(cfg), "daily-prompt", "apply", "missing:job"])
    upd(Prefs(s.data_dir), discover_weekday=datetime.now().isoweekday())
    cli.main(["--config", str(cfg), "daily-prompt", "rank"])
    assert "Weekly" in capsys.readouterr().out
    upd(Prefs(s.data_dir), discover_weekday=0)
    cli.main(["--config", str(cfg), "daily-prompt", "rank"])
    out = capsys.readouterr().out
    assert "Weekly" not in out and "{{DISCOVER}}" not in out


def test_light_model_for_light_stages(tmp_path):
    p = Prefs(tmp_path)
    upd(p, daily_model="opus", daily_light_model="sonnet")
    assert p.daily(0, "apply")["model"] == "opus" and p.daily(0, "rank")["model"] == "sonnet"
    upd(p, daily_light_model="")
    assert p.daily(0, "drafts")["model"] == "opus"


def test_usage_by_stage(tmp_path):
    db = DB(tmp_path / "u.db")
    db.log_usage("daily", "claude:sonnet:rank", 0, 0, 0, 0, None, 0.5, 1000)
    db.log_usage("daily", "claude:opus:apply", 0, 0, 0, 0, None, 2.0, 5000)
    db.log_usage("daily", "claude:opus:apply", 0, 0, 0, 0, None, 2.0, 5000)
    db.log_usage("daily", "openrouter:deepseek/deepseek-chat:free:rank (openrouter)", 0, 0, 0.001, 0, None, 0.001, 300)
    by = {b["stage"]: b for b in db.usage_by_stage()}
    assert by["apply"]["n"] == 2 and by["apply"]["tokens"] == 10000
    assert by["rank"]["n"] == 2 and "deepseek/deepseek-chat:free" in by["rank"]["models"]
    assert db.usage_summary()["daily"]["calls"] == 1 and db.usage_summary()["daily"]["sessions"] == 4


def test_quick_pick(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    with pytest.raises(SystemExit) as e:  # off by default
        cli.main(["--config", str(cfg), "quick-pick"])
    assert e.value.code == 2
    p = Prefs(s.data_dir)
    upd(p, quick_pick_model="google/gemini-2.5-flash", discover_weekday=0, monthly_api_budget=5)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-123456")  # restored after the test
    sent = {}

    def fake_post(url, body, key, timeout=120):
        sent.update(body)
        reply = {"picks": [{"id": "wd:c:3", "why": "dbt"}, {"id": "made:up", "why": "x"}, {"id": "gh:a:1", "why": "fit"}]}
        return {"choices": [{"message": {"content": json.dumps(reply)}}], "usage": {"total_tokens": 4321, "cost": 0.0007}}
    monkeypatch.setattr("autoapply.classify._post", fake_post)
    cli.main(["--config", str(cfg), "quick-pick"])
    assert capsys.readouterr().out.strip() == "Picked: Initech (Analytics Engineer), Acme (Senior Analytics Engineer)"
    picks = json.loads((s.data_dir / "daily" / "picks.json").read_text())
    assert [x["id"] for x in picks] == ["wd:c:3", "gh:a:1"] and picks[0]["by_hand"] is True
    assert sent["model"] == "google/gemini-2.5-flash" and "Analytics engineer. dbt" in sent["messages"][0]["content"]
    by = {b["stage"]: b for b in db.usage_by_stage()}
    assert by["rank"]["tokens"] == 4321 and round(by["rank"]["cost"], 4) == 0.0007

    monkeypatch.setattr("autoapply.classify._post", lambda *a, **k: {"choices": [{"message": {"content": "sorry"}}]})
    with pytest.raises(SystemExit) as e:  # a bad reply falls back to the agent
        cli.main(["--config", str(cfg), "quick-pick"])
    assert e.value.code == 1
    upd(p, discover_weekday=datetime.now().isoweekday())
    with pytest.raises(SystemExit) as e:  # discovery day: the agent picks
        cli.main(["--config", str(cfg), "quick-pick"])
    assert e.value.code == 2


def test_quick_pick_reads_alert_emails(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    p = Prefs(s.data_dir)
    upd(p, quick_pick_model="google/gemini-2.5-flash", discover_weekday=0, monthly_api_budget=5)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-123456")
    monkeypatch.setenv("GMAIL_USER", "me@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "x")
    emails = [{"from": "jobalerts-noreply@linkedin.com", "subject": "New jobs", "text": "Analytics Engineer at Hooli\nhttps://linkedin.com/x"}]
    monkeypatch.setattr("autoapply.alerts.fetch", lambda *a, **k: emails)
    sent = {}

    def fake_post(url, body, key, timeout=120):
        sent.update(body)
        roles = [{"company": "Hooli", "title": "Analytics Engineer", "link": "https://linkedin.com/x", "why": "dbt"},
                 {"company": "Acme", "title": "Senior Analytics Engineer"},  # already tracked: dropped
                 {"title": "no company"}]
        return {"choices": [{"message": {"content": json.dumps({"roles": roles})}}], "usage": {"total_tokens": 900, "cost": 0.0002}}
    monkeypatch.setattr("autoapply.classify._post", fake_post)
    cli.main(["--config", str(cfg), "quick-pick", "--alerts"])
    assert capsys.readouterr().out.strip() == "1"
    roles = json.loads((s.data_dir / "daily" / "alert-roles.json").read_text())
    assert [r["company"] for r in roles] == ["Hooli"]
    assert "Analytics Engineer at Hooli" in sent["messages"][0]["content"]
    assert {b["stage"] for b in db.usage_by_stage()} == {"alerts"}
    cli.main(["--config", str(cfg), "daily-prompt", "alerts"])
    assert "alert-roles.json" in capsys.readouterr().out
    assert Prefs(s.data_dir).daily(0, "alerts")["model"] == Prefs(s.data_dir).daily(0, "rank")["model"]


def test_todo_line_for_phone_push(tmp_path, capsys):
    s, db, cfg = make(tmp_path)
    cli.main(["--config", str(cfg), "todo-line"])
    assert capsys.readouterr().out == ""  # nothing open, no line
    db.add_event({"id": "<r@x>", "job_id": None, "kind": "recruiter", "at": "2026-10-01 09:00",
                  "sender": "Pat Lee <pat@agency.example>", "subject": "Data role", "reviewed": 1})
    cli.main(["--config", str(cfg), "todo-line"])
    out = capsys.readouterr().out
    assert out.startswith("1 to do: ") and "Pat Lee" in out


def test_every_command_the_prompts_use_is_allowed():
    """A command the daily agent may not run stops its step (11/3: `autoapply candidates`)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    allow = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["allow"]
    used = set()
    for f in list((root / "prompts").rglob("*.md")) + [root / "AGENTS.md"]:
        used |= set(re.findall(r"autoapply ([a-z][a-z-]+)", f.read_text()))
    missing = [c for c in sorted(used) if not any(a.startswith(f"Bash(autoapply {c}") for a in allow)]
    assert used and not missing, missing


def test_permission_denial_fails_the_step(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    out = {"type": "result", "result": "If you allow `autoapply candidates` I'll rerun.", "usage": {}, "total_cost_usd": 0.1,
           "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "autoapply candidates --limit 12"}}]}
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(out)))
    with pytest.raises(SystemExit) as e:
        cli.main(["--config", str(cfg), "log-daily", "claude", "sonnet", "--stage", "rank"])
    assert e.value.code == 1 and "autoapply candidates" in capsys.readouterr().out


def test_manual_run_only_picks_and_applies(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    monkeypatch.setenv("AUTOAPPLY_TRIGGER", "manual")
    monkeypatch.setenv("AUTOAPPLY_PICKS", "1")
    cli.main(["--config", str(cfg), "daily-stages"])
    assert capsys.readouterr().out.split() == ["rank"]
    (s.data_dir / "daily").mkdir(exist_ok=True)
    (s.data_dir / "daily" / "picks.json").write_text(json.dumps([{"id": "gh:a:1"}, {"id": "wd:c:3"}]))
    db.update("gh:a:1", status="filled")  # filled earlier today: not again
    cli.main(["--config", str(cfg), "daily-picks"])
    assert capsys.readouterr().out.split() == ["wd:c:3"]
    upd(Prefs(s.data_dir), discover_weekday=datetime.now().isoweekday())
    cli.main(["--config", str(cfg), "daily-prompt", "rank"])
    assert "Weekly" not in capsys.readouterr().out


def test_one_pick_per_company_and_shortlist(tmp_path, capsys):
    """11/4: both of the day's picks were the same company (two roles at one company). One per company; the dashboard's
    shortlist also shows one per company and skips companies you applied to."""
    s, db, cfg = make(tmp_path)
    db.upsert_job({"id": "gh:a:9", "ats": "greenhouse", "company": "ACME", "title": "Director, Analytics Engineering",
                   "location": "Remote", "url": "u", "apply_url": "u", "description": ""})
    (s.data_dir / "daily").mkdir(exist_ok=True)
    (s.data_dir / "daily" / "picks.json").write_text(json.dumps([{"id": "gh:a:1", "why": "dbt fit"}, {"id": "gh:a:9"}, {"id": "wd:c:3"}]))
    cli.main(["--config", str(cfg), "daily-picks"])
    assert capsys.readouterr().out.split() == ["gh:a:1", "wd:c:3"]
    short = rank.shortlist(db, s, 5)
    assert [j["id"] for j in short][:2] == ["gh:a:1", "wd:c:3"] and short[0]["why"] == "dbt fit"
    assert "gh:a:9" not in [j["id"] for j in short]
    db.update("gh:a:1", status="filled")  # prepared: Acme is now in Ready for you, so not on the shortlist
    ids = [j["id"] for j in rank.shortlist(db, s, 5, skip_companies=["Acme"])]
    assert "gh:a:9" not in ids and "wd:c:3" in ids
    assert rank.shortlist(db, s, 0) == []


# ---------- Prep only (11/10): tailor and save answers, fill nothing ----------

def test_prep_only_stores_plan_without_filling(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    called = []
    monkeypatch.setattr(cli, "fill", lambda *a, **k: called.append(1))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"files": {"resume": "r.pdf"}, "answers": {"Why us?": "x"},
                                "approved_by_user": True, "approved": {"Consent": "yes"}}))
    cli.main(["--config", str(cfg), "fill", str(plan), "--job", "wd:c:3", "--prep-only"])
    j = db.get("wd:c:3")
    saved = json.loads(j["plan_json"])
    assert not called and j["status"] == "prepped" and saved["answers"] == {"Why us?": "x"} and saved["url"] == "u"
    assert "approved_by_user" not in saved and "approved" not in saved
    assert json.loads(capsys.readouterr().out)["prepped"] == "wd:c:3"


def test_prep_only_never_downgrades_a_filled_job(tmp_path, monkeypatch):
    s, db, cfg = make(tmp_path)
    monkeypatch.setattr(cli, "fill", lambda *a, **k: None)
    db.update("wd:c:3", status="filled")
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["--config", str(cfg), "fill", str(plan), "--job", "wd:c:3", "--prep-only"])
    assert db.get("wd:c:3")["status"] == "filled"


def test_prep_only_prompt(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    monkeypatch.delenv("AUTOAPPLY_PREP_ONLY", raising=False)
    cli.main(["--config", str(cfg), "daily-prompt", "apply", "gh:a:1"])
    out = capsys.readouterr().out
    assert "{{" not in out and "--prep-only" in out and "Prep only." not in out  # Workday uses it in every run
    monkeypatch.setenv("AUTOAPPLY_PREP_ONLY", "1")
    cli.main(["--config", str(cfg), "daily-prompt", "apply", "gh:a:1"])
    out = capsys.readouterr().out
    assert "Prep only." in out and "{{" not in out


def test_leads_job_returns_a_prepped_job(tmp_path, capsys):
    s, db, cfg = make(tmp_path)
    from autoapply import leads
    k = leads.add_pasted(db, s, {"company": "Hooli", "title": "Data Lead", "location": "", "work_setting": "", "pay": "",
                                 "url": "", "description": "the post"})["key"]
    cli.main(["--config", str(cfg), "leads", "from-paste", k])
    jid = capsys.readouterr().out.strip()
    assert jid.startswith("manual:")
    db.update(jid, status="prepped")
    cli.main(["--config", str(cfg), "leads", "job", k])
    assert capsys.readouterr().out.strip() == jid


def test_daily_preps_from_the_paste_when_the_company_page_is_missing():
    """daily.sh runs with set -u: every read of AUTOAPPLY_PREP_ONLY needs a default, or the whole run dies."""
    import re
    from pathlib import Path
    sh = (Path(__file__).resolve().parent.parent / "scripts" / "daily.sh").read_text()
    assert 'autoapply leads from-paste "$AUTOAPPLY_LEAD"' in sh and "export AUTOAPPLY_PREP_ONLY=1" in sh
    assert "Paste the post on this lead's page" in sh
    reads = re.findall(r"\$\{?AUTOAPPLY_PREP_ONLY[^}]*\}?", sh)
    assert reads and all(r.startswith("${AUTOAPPLY_PREP_ONLY:") for r in reads), reads


def test_no_real_fill_in_a_prep_only_run_or_on_a_pasted_job(tmp_path, monkeypatch):
    """Review 11/10: only the prompt stood between Prep only and a real browser fill."""
    import pytest
    s, db, cfg = make(tmp_path)
    monkeypatch.setattr(cli, "fill", lambda *a, **k: pytest.fail("a form was filled"))
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    monkeypatch.setenv("AUTOAPPLY_PREP_ONLY", "1")
    with pytest.raises(SystemExit, match="prep-only"):
        cli.main(["--config", str(cfg), "fill", str(plan), "--job", "gh:a:1"])
    monkeypatch.delenv("AUTOAPPLY_PREP_ONLY")
    db.upsert_job({"id": "manual:p", "ats": "manual", "company": "Hooli", "title": "Data Lead", "location": "",
                   "url": "", "apply_url": "", "description": "post"})
    with pytest.raises(SystemExit, match="prep-only"):
        cli.main(["--config", str(cfg), "fill", str(plan), "--job", "manual:p"])
    assert db.get("gh:a:1")["status"] == "new" and db.get("manual:p")["status"] == "new"


def test_letter_rewrite_on_a_prepped_job_fills_nothing(tmp_path, capsys, monkeypatch):
    import pytest
    s, db, cfg = make(tmp_path)
    monkeypatch.setattr(cli, "fill", lambda *a, **k: pytest.fail("a form was filled"))
    db.update("wd:c:3", status="prepped", plan_json={"url": "https://acme.wd1.myworkdayjobs.com/x", "files": {}})
    cli.main(["--config", str(cfg), "refill", "wd:c:3"])
    assert db.get("wd:c:3")["status"] == "prepped" and "nothing filled" in capsys.readouterr().out


def test_a_prepped_role_is_not_prepared_again(tmp_path):
    s, db, _ = make(tmp_path)
    db.update("gh:a:1", status="prepped")
    from autoapply import rank
    why = rank.Applied(db, 90).same_role("ACME", "Senior Analytics Engineer")
    assert why.startswith("already prepped an application for this role")


def test_log_daily_keeps_the_token_split(tmp_path, monkeypatch):
    import io
    s, db, cfg = make(tmp_path)
    out = json.dumps({"result": "Acme: ready to review", "total_cost_usd": 0.9, "num_turns": 23, "duration_ms": 140000,
                      "usage": {"input_tokens": 1200, "cache_read_input_tokens": 900000, "cache_creation_input_tokens": 60000,
                                "output_tokens": 9000}})
    monkeypatch.setattr("sys.stdin", io.StringIO(out))
    cli.main(["--config", str(cfg), "log-daily", "claude", "", "subscription", "--stage", "apply"])
    r = db.conn.execute("select tokens, t_in, t_cache_read, t_cache_write, t_out, turns, ms from usage").fetchone()
    assert tuple(r) == (970200, 1200, 900000, 60000, 9000, 23, 140000)


def test_show_gives_the_agent_only_what_tailoring_needs(tmp_path, capsys):
    s, db, cfg = make(tmp_path)
    db.update("gh:a:1", plan_json={"answers": {"x": "y" * 3000}}, report_json={"filled": ["z" * 3000]}, screenshot="/s.png")
    cli.main(["--config", str(cfg), "show", "gh:a:1"])
    short = json.loads(capsys.readouterr().out)
    assert "plan_json" not in short and "report_json" not in short and short["description"].startswith("dbt Snowflake")
    cli.main(["--config", str(cfg), "show", "gh:a:1", "--full"])
    assert "report_json" in json.loads(capsys.readouterr().out)


def test_daily_agent_steps_load_no_mcp_servers():
    from pathlib import Path
    sh = (Path(__file__).resolve().parent.parent / "scripts" / "daily.sh").read_text()
    assert "--max-turns \"$turns\" --strict-mcp-config" in sh
