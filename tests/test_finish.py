"""autoapply-finish: each run is counted, "I sent it with the command" logs how it went out, and Stats splits
applications by how they were sent. Copy buttons use the helper that works on a plain http address."""
import json

from autoapply import finish, stats
from autoapply.config import Settings
from autoapply.db import DB
from web_client import client


def _setup(tmp_path):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={"first_name": "Alex"})
    db = DB(s.data_dir / "t.db")
    for jid, co in (("greenhouse:acme:1", "Acme"), ("greenhouse:beta:2", "Beta")):
        db.upsert_job({"id": jid, "ats": "greenhouse", "company": co, "title": "AE", "location": "",
                       "url": "https://x.example/" + jid, "apply_url": "", "description": ""})
        db.update(jid, status="filled", plan_json={"answers": {"Why?": "x"}}, report_json={"filled": [], "errors": []})
    return s, db, client(s, db)


def test_bundle_counts_a_run_and_page_offers_the_command_button(tmp_path):
    _, db, c = _setup(tmp_path)
    html = c.get("/job/greenhouse:acme:1").text
    assert 'value="command"' not in html
    assert c.get("/bundle/greenhouse:acme:1").status_code == 200
    c.get("/bundle/greenhouse:acme:1")
    assert finish.run_count(db) == 2 and finish.ran(db, "greenhouse:acme:1") and not finish.ran(db, "greenhouse:beta:2")
    html = c.get("/job/greenhouse:acme:1").text
    assert "I sent it with the command" in html and 'value="command"' in html
    assert 'value="manual"' in html  # by hand stays available


def test_command_action_submits_and_counts_as_command(tmp_path):
    _, db, c = _setup(tmp_path)
    c.get("/bundle/greenhouse:acme:1")
    r = c.post("/job/greenhouse:acme:1", data={"action": "command"}, follow_redirects=False)
    assert r.status_code == 303
    job = db.get("greenhouse:acme:1")
    assert job["status"] == "submitted" and job["submitted_at"]
    assert any(e["kind"] == "applied" and e["job_id"] == job["id"] for e in db.events())
    assert finish.how_sent(db, job) == "command"


def test_how_sent_rules(tmp_path):
    _, db, _ = _setup(tmp_path)
    j = lambda jid, rep=None: {"id": jid, "report_json": json.dumps(rep or {})}
    assert finish.how_sent(db, j("greenhouse:x:1")) == "hand"
    assert finish.how_sent(db, j("greenhouse:x:2", {"submitted": True})) == "app"
    assert finish.how_sent(db, j("tracker:abc")) == "elsewhere"
    assert finish.how_sent(db, j("manual:abc")) == "elsewhere"
    finish.record_run(db, "greenhouse:x:3")                 # ran, then the confirmation email marked it
    assert finish.how_sent(db, j("greenhouse:x:3")) == "command"
    finish.mark(db, "greenhouse:x:3", "hand")                # you said otherwise: your word wins
    assert finish.how_sent(db, j("greenhouse:x:3")) == "hand"


def test_manual_action_counts_as_by_hand(tmp_path):
    _, db, c = _setup(tmp_path)
    c.get("/bundle/greenhouse:beta:2")
    c.post("/job/greenhouse:beta:2", data={"action": "manual"}, follow_redirects=False)
    assert finish.how_sent(db, db.get("greenhouse:beta:2")) == "hand"


def test_stats_split_and_run_count(tmp_path):
    _, db, c = _setup(tmp_path)
    c.get("/bundle/greenhouse:acme:1")
    c.post("/job/greenhouse:acme:1", data={"action": "command"})
    c.post("/job/greenhouse:beta:2", data={"action": "manual"})
    d = stats.detail(db)
    assert dict(d["sent_how"]) == {"Sent by the app": 0, "With the command": 1, "By hand": 1, "Logged from elsewhere": 0}
    assert d["finish_runs"] == 1
    html = c.get("/stats").text
    assert "How applications went out" in html and "autoapply-finish ran 1 time." in html


def test_copy_buttons_use_the_http_safe_helper(tmp_path):
    _, db, c = _setup(tmp_path)
    html = c.get("/job/greenhouse:acme:1").text
    assert "window.copyText" in html and "execCommand" in html
    assert "navigator.clipboard.writeText(this" not in html
