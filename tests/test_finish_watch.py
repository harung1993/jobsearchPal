"""autoapply-finish watches for the site's confirmation page, the server marks the job sent with the command, and
Undo puts it back. The watcher never clicks; here the page "submits itself" on a timer to stand in for you."""
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from autoapply import finish
from autoapply.config import Settings
from autoapply.db import DB
from autoapply.fillers.base import GENERIC, _sent_now, detect, watch_for_sent
from web_client import client

from test_fillers import base_url  # noqa: F401  (fixture)


def _watch(url: str, ats: str) -> list[str]:
    seen = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(url)
        # Stand in for you pressing Submit a moment after the form is ready.
        page.evaluate("setTimeout(() => document.querySelector('form').dispatchEvent("
                      "new Event('submit', {cancelable: true})), 600)")
        got = watch_for_sent(page, detect(url, ats), on_sent=lambda c: (seen.append(c), page.close()), poll_ms=200, max_s=15)
        b.close()
    assert got == (seen[0] if seen else "")
    return seen


def test_watch_sees_thank_you_text(base_url):
    assert _watch(f"{base_url}/gh/", "greenhouse") == ["Thank you for applying"]


def test_watch_sees_confirmation_address(base_url):
    seen = _watch(f"{base_url}/gh-redirect/", "greenhouse")
    assert len(seen) == 1 and seen[0].endswith("confirmation.html")


def test_no_false_alarm_while_the_form_is_open():
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.set_content("<p>Thank you for your interest in Acme!</p><form><input name=q><button type=submit>Submit</button></form>")
        before = bool(__import__("re").search(GENERIC.success, page.inner_text("body"), 2))
        assert _sent_now(page, GENERIC, page.url, before) == ""          # already-there text, Submit still visible
        page.set_content("<form><p>Application received soon after you press</p><button type=submit>Submit</button></form>")
        assert _sent_now(page, GENERIC, page.url, False) == ""           # new text but the form's Submit is still there
        page.set_content("<h2>We have received your application</h2>")
        assert _sent_now(page, GENERIC, page.url, False) == "received"
        b.close()


def test_watch_returns_quietly_when_closed_without_sending(base_url):
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(f"{base_url}/gh/")
        page.evaluate("setTimeout(() => window.__closed = true, 10)")
        page.close()
        assert watch_for_sent(page, detect(page.url, "greenhouse"), poll_ms=50, max_s=5) == ""
        b.close()


def _setup(tmp_path, monkeypatch, status="filled"):
    monkeypatch.setenv("AUTOAPPLY_TOKEN", "finish-key-123")
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={"first_name": "Alex"})
    db = DB(s.data_dir / "t.db")
    db.upsert_job({"id": "greenhouse:acme:1", "ats": "greenhouse", "company": "Acme", "title": "AE", "location": "",
                   "url": "https://x.example/1", "apply_url": "", "description": ""})
    db.update("greenhouse:acme:1", status=status, plan_json={"answers": {"Why?": "x"}}, report_json={"filled": [], "errors": []})
    return s, db, client(s, db)


def test_finished_marks_sent_and_undo_puts_it_back(tmp_path, monkeypatch):
    s, db, c = _setup(tmp_path, monkeypatch)
    anon = TestClient(c.app)
    assert anon.post("/finished/greenhouse:acme:1", json={"confirmation": "x"}).status_code == 401   # needs the key
    anon.get("/bundle/greenhouse:acme:1?t=finish-key-123")
    html = c.get("/job/greenhouse:acme:1").text
    assert "Filled with the command" in html
    r = anon.post("/finished/greenhouse:acme:1?t=finish-key-123", json={"confirmation": "Thank you for applying"})
    assert r.status_code == 200 and r.json()["ok"]
    job = db.get("greenhouse:acme:1")
    assert job["status"] == "submitted" and job["submitted_at"]
    assert any(e["id"] == "applied:greenhouse:acme:1" for e in db.events())
    assert finish.how_sent(db, job) == "command"
    html = c.get("/job/greenhouse:acme:1").text
    assert "Sent with the command." in html and "Thank you for applying" in html and "Not sent? Undo" in html
    assert anon.post("/finished/greenhouse:acme:1?t=finish-key-123", json={}).json().get("already")  # said twice: no change

    c.post("/job/greenhouse:acme:1", data={"action": "unsend"}, follow_redirects=False)
    job = db.get("greenhouse:acme:1")
    assert job["status"] == "filled" and not job["submitted_at"]
    assert not any(e["id"] == "applied:greenhouse:acme:1" for e in db.events())
    assert finish.last_mark(db, "greenhouse:acme:1") is None
    html = c.get("/job/greenhouse:acme:1").text
    assert "Not sent? Undo" not in html and "Filled with the command" in html


def test_undo_after_the_button_goes_back_to_prepped(tmp_path, monkeypatch):
    _, db, c = _setup(tmp_path, monkeypatch, status="prepped")
    c.get("/bundle/greenhouse:acme:1")
    c.post("/job/greenhouse:acme:1", data={"action": "command"})
    assert "You marked it at" in c.get("/job/greenhouse:acme:1").text
    c.post("/job/greenhouse:acme:1", data={"action": "unsend"})
    assert db.get("greenhouse:acme:1")["status"] == "prepped"


def test_by_hand_has_no_undo(tmp_path, monkeypatch):
    _, db, c = _setup(tmp_path, monkeypatch)
    c.post("/job/greenhouse:acme:1", data={"action": "manual"})
    assert "Not sent? Undo" not in c.get("/job/greenhouse:acme:1").text
    c.post("/job/greenhouse:acme:1", data={"action": "unsend"})
    assert db.get("greenhouse:acme:1")["status"] == "submitted"


def test_old_finish_log_table_gets_the_detail_column(tmp_path):
    db = DB(tmp_path / "t.db")
    db.conn.execute("create table finish_log (job_id text not null, at text not null, kind text not null)")
    db.conn.execute("insert into finish_log values ('j', '2026-11-11 10:00', 'run')")
    finish.mark(db, "j", "auto", {"status": "filled"}, "Thanks")
    assert finish.ran(db, "j") and finish.last_mark(db, "j")["detail"]["confirmation"] == "Thanks"


def test_job_page_sees_the_mark_and_drops_old_submit_warnings(tmp_path, monkeypatch):
    s, db, c = _setup(tmp_path, monkeypatch)
    db.update("greenhouse:acme:1", report_json={"filled": [], "submit_clicked": True, "errors": [
        {"label": "(submit)", "error": "Submit was pressed but not confirmed."}, {"label": "Phone", "error": "bad format"}]})
    assert TestClient(c.app).get("/job-status/greenhouse:acme:1").status_code == 401   # signed in only
    assert c.get("/job-status/greenhouse:acme:1").json()["status"] == "filled"
    html = c.get("/job/greenhouse:acme:1").text
    assert "/job-status/" in html and "pressed but not confirmed" in html               # the page polls; warning still matters
    TestClient(c.app).post("/finished/greenhouse:acme:1?t=finish-key-123", json={})
    assert c.get("/job-status/greenhouse:acme:1").json()["status"] == "submitted"
    html = c.get("/job/greenhouse:acme:1").text
    assert "pressed but not confirmed" not in html and "bad format" in html               # sent: only the stale one goes
