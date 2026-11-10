"""Run log page, what Auto apply found on a lead, in-app confirm dialogs and app-styled error pages."""
from autoapply import leads, runlog
from autoapply.config import Settings
from autoapply.db import DB
from web_client import client

from test_fillers import PROFILE

DAY = """# Daily run 2026-11-10 06:35
- alerts: Stopped: needed permission for curl -sL https://example.org
- rank: Picked two roles.
- apply greenhouse:convene:8319158: Everything is in `data/applications/convene/`.

# Run now 2026-11-10 10:13
- starred leads: The Brooklyn posting says "this position has been filled."
- auto apply: Auto apply: couldn't find that role on the company's own site
"""


def make(tmp_path):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile=PROFILE)
    db = DB(s.data_dir / "t.db")
    return s, db, client(s, db)


def test_parse_runs_newest_first_with_job_ids():
    runs = runlog.parse(DAY)
    assert [r["kind"] for r in runs] == ["Run now", "Daily run"]
    assert not runs[0]["ok"] and not runs[1]["ok"]
    apply = runs[1]["steps"][2]
    assert apply["stage"] == "apply" and apply["job"] == "greenhouse:convene:8319158" and apply["text"].startswith("Everything")
    assert runs[0]["steps"][0]["stage"] == "starred leads"


def test_parse_keeps_continuation_lines_and_stray_bullets():
    runs = runlog.parse("# Run now 2026-11-10 10:13\n- rank (quick pick failed, using the agent)\n- rank: ok\nsecond line")
    steps = runs[0]["steps"]
    assert steps[0] == {"stage": "", "job": "", "text": "rank (quick pick failed, using the agent)"}
    assert steps[1]["text"] == "ok\nsecond line" and runs[0]["ok"]


def test_runs_page_lists_days(tmp_path):
    s, db, c = make(tmp_path)
    assert "No runs logged yet" in c.get("/runs").text
    (s.data_dir / "daily").mkdir(parents=True, exist_ok=True)
    (s.data_dir / "daily" / "2026-11-10.md").write_text(DAY)
    (s.data_dir / "daily" / "alert-roles.json").write_text("[]")  # not a day file: ignored
    html = c.get("/runs").text
    assert "Tuesday, November 10" in html and "this position has been filled" in html
    assert html.index("Run now") < html.index("Daily run") and "/job/greenhouse%3Aconvene%3A8319158" in html


def test_lead_shows_what_auto_apply_found(tmp_path):
    s, db, c = make(tmp_path)
    leads.ensure(db)
    db.conn.execute("insert into leads (key, title, company, status, ats_checked, last_seen, score) "
                    "values ('national grid|staff data engineer', 'Staff Data Engineer', 'National Grid', 'starred', '1', '2026-11-05', 6)")
    db.conn.commit()
    html = c.get("/leads?show=starred").text
    assert "company page not found yet" in html
    leads.set_note(db, "national grid|staff data engineer", "The posting says it has been filled.")
    html = c.get("/leads?show=starred").text
    assert "company page not found yet" not in html and "The posting says it has been filled." in html and 'href="/runs"' in html
    assert "confirm(" not in html and "data-confirm=" in html


def test_dashboard_has_no_browser_confirm(tmp_path):
    s, db, c = make(tmp_path)
    html = c.get("/").text
    assert "confirm(" not in html and 'id="ask"' in html and 'href="/runs"' in html


def test_errors_are_app_pages_for_browsers_json_for_fetch(tmp_path):
    s, db, c = make(tmp_path)
    r = c.get("/job/nope:1", headers={"accept": "text/html"})
    assert r.status_code == 404 and "here any more" in r.text and "Go back" in r.text
    r = c.get("/job/nope:1", headers={"accept": "application/json"})
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    r = c.post("/leads", data={"key": "x"}, headers={"accept": "text/html"})
    assert r.status_code == 422 and "Missing: status" in r.text


def test_in_page_form_errors_come_back_for_the_dialog(tmp_path):
    s, db, c = make(tmp_path)
    r = c.post("/leads", data={"key": "x"}, headers={"x-in-page": "1", "accept": "text/html"})
    assert r.status_code == 422 and r.json() == {"code": 422, "title": "Something the form needs was missing.", "detail": "Missing: status"}
    r = c.post("/leads", data={"key": "x", "status": "bogus"}, headers={"x-in-page": "1"})
    assert r.status_code == 400 and r.json()["title"].startswith("That request")
    html = c.get("/").text
    assert "X-In-Page" in html and "sendInPage" in html
