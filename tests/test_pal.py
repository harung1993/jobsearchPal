"""The pal: which morning it is, what to celebrate once, the rejection note, and an honest market line."""
from datetime import date, datetime

import pytest

from autoapply import pal, stats
from autoapply.db import DB

NOW = datetime(2026, 11, 10, 8, 30)  # a Tuesday morning


@pytest.fixture
def db(tmp_path):
    d = DB(tmp_path / "t.db")
    d.upsert_job({"id": "gh:acme:1", "ats": "greenhouse", "company": "acme", "title": "Analytics Engineer", "location": "",
                  "url": "u", "apply_url": "u", "description": ""})
    d.update("gh:acme:1", status="submitted", submitted_at="2026-10-20 09:00")
    from autoapply import coach
    coach.set_note(d, "last_action", "2026-11-09 18:00")  # active yesterday, so not a "welcome back" morning
    return d


def _ev(db, i, kind, at, job="gh:acme:1", sender="Acme <jobs@acme.example>"):
    db.add_event({"id": i, "job_id": job, "kind": kind, "at": at, "sender": sender, "subject": "s", "reviewed": 1})


def _greet(db, now=NOW):
    return pal.greeting(db, stats.compute(db, now.date()), now, "Alex")


def test_greeting_fresh_install(tmp_path):
    g = _greet(DB(tmp_path / "fresh.db"))
    assert g["state"] == "start" and g["title"].startswith("Morning, Alex") and "quiet" not in g["line"].lower()


def test_greeting_priorities(db):
    assert _greet(db)["state"] == "quiet"  # applied, nothing heard for weeks
    _ev(db, "r1", "rejected", "2026-11-09 16:00")
    g = _greet(db)
    assert g["state"] == "rejection" and "stone" in g["line"] and "Acme" in g["line"]
    _ev(db, "i1", "interview", "2026-11-09 18:00")
    g = _greet(db)
    assert g["state"] == "interview" and "Acme" in g["line"]
    _ev(db, "o1", "offer", "2026-11-05 10:00")
    assert _greet(db)["state"] == "offer"


def test_greeting_time_of_day_and_monday(tmp_path):
    d = DB(tmp_path / "t.db")
    assert _greet(d, datetime(2026, 11, 9, 8, 0))["state"] == "start"  # nothing applied yet beats Monday
    d.upsert_job({"id": "j", "ats": "x", "company": "Initech", "title": "t", "location": "", "url": "u", "apply_url": "u", "description": ""})
    d.update("j", status="submitted", submitted_at="2026-11-06 09:00")
    assert _greet(d, datetime(2026, 11, 9, 8, 0))["state"] == "monday"
    g = _greet(d, datetime(2026, 11, 10, 21, 0))
    assert g["state"] == "evening" and g["title"].startswith("Evening, Alex")


def test_lines_vary_by_day_and_follow_house_rules(db):
    lines = {_greet(db, datetime(2026, 11, d, 8, 0))["line"] for d in (10, 11, 12)}
    assert len(lines) > 1
    for v in [l for vs in pal.LINES.values() for l in vs]:
        assert v.count("!") <= 1 and "club" not in v.lower() and "%" not in v


def test_celebration_order_and_once(db):
    _ev(db, "i1", "interview", "2026-11-09 18:00")
    _ev(db, "o1", "offer", "2026-11-09 19:00")
    c = pal.celebration(db, stats.compute(db, NOW.date()), NOW.date())
    assert c["kind"] == "offer" and "Acme" in c["title"]
    db.set_nudge(c["key"], "done")
    c2 = pal.celebration(db, stats.compute(db, NOW.date()), NOW.date())
    assert c2["kind"] == "interview"
    db.set_nudge(c2["key"], "done")
    assert pal.celebration(db, stats.compute(db, NOW.date()), NOW.date()) is None


def test_celebration_ignores_old_events(db):
    _ev(db, "i0", "interview", "2026-10-01 10:00")
    assert pal.celebration(db, stats.compute(db, NOW.date()), NOW.date()) is None


def test_week_met_celebrates_once():
    s = {"this_week": 3, "dua_floor": 3, "this_week_start": date(2026, 11, 8)}
    class Fake:
        seen = {}
        def events(self): return []
        def nudge_states(self): return self.seen
        def get(self, i): return None
    f = Fake()
    c = pal.celebration(f, s, NOW.date())
    assert c["kind"] == "week" and c["key"] == "celebrate:week:2026-11-08"
    f.seen = {c["key"]: {"state": "done"}}
    assert pal.celebration(f, s, NOW.date()) is None
    assert pal.celebration(f, {**s, "this_week": 2}, NOW.date()) is None


def test_rejection_note_once_each(db):
    assert pal.rejection_note(db, NOW.date()) is None
    _ev(db, "r1", "rejected", "2026-11-09 16:00")
    n = pal.rejection_note(db, NOW.date())
    assert n["key"] == "pal:rejection:r1" and n["company"] == "Acme"
    db.set_nudge(n["key"], "done")
    assert pal.rejection_note(db, NOW.date()) is None
    _ev(db, "r2", "rejected", "2026-11-10 07:00", job=None, sender="Globex Careers <no-reply@globex.example>")
    assert pal.rejection_note(db, NOW.date())["company"] == "Globex Careers"
    assert pal.rejection_note(db, date(2026, 11, 20)) is None  # old news stays quiet


def test_market_line_stale_and_missing(tmp_path, monkeypatch):
    f = tmp_path / "market.yaml"
    monkeypatch.setattr(pal, "MARKET_FILE", f)
    assert pal.market_line(NOW.date()) is None  # no file
    f.write_text("lines:\n  - text: It's taking most people longer than usual.\n    source: BLS\n    checked: 2026-10-01\n")
    m = pal.market_line(NOW.date())
    assert m["text"].startswith("It's taking") and m["source"] == "BLS" and m["checked"] == "2026-10-01"
    assert pal.market_line(date(2027, 3, 1)) is None  # stale
    f.write_text("lines:\n  - text: No source given.\n    checked: 2026-10-01\n")
    assert pal.market_line(NOW.date()) is None
    f.write_text(": not yaml [")
    assert pal.market_line(NOW.date()) is None


def test_push_line(db):
    assert pal.push_line(db, stats.compute(db, NOW.date()), NOW)
    assert "!" not in pal.push_line(db, stats.compute(db, NOW.date()), NOW)


def _app(tmp_path, db):
    from autoapply.config import Settings
    from web_client import client
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={"first_name": "Alex"})
    return client(s, db)


def test_dashboard_celebrates_once_and_puts_rejection_away(tmp_path, db):
    today = datetime.now()
    _ev(db, "i1", "interview", today.strftime("%Y-%m-%d %H:%M"))
    _ev(db, "r1", "rejected", today.strftime("%Y-%m-%d %H:%M"), job=None, sender="Globex <no@globex.example>")
    c = _app(tmp_path, db)
    html = c.get("/").text
    assert "cel-interview\" role=\"status\"" in html and "Acme wants to talk" in html and "class=\"hz scene play-interview\"" in html and "Alex." in html
    assert "Globex said no this time" in html and "one stone in a very big ocean" in html
    assert "closed" in html and "rejected ·" not in html
    again = c.get("/").text
    assert "cel-interview\" role=\"status\"" not in again and "class=\"hz scene play-interview\"" not in again  # played once
    r = c.post("/pal/seen", data={"key": "pal:rejection:r1", "back": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    assert "Globex said no this time" not in c.get("/").text
    c.post("/pal/seen", data={"key": "anything-else", "back": "/"})
    assert "anything-else" not in db.nudge_states()


def test_dashboard_reduced_motion_contract(tmp_path, db):
    html = _app(tmp_path, db).get("/").text
    assert "prefers-reduced-motion:reduce" in html and "infinite" not in html.split("hz-rise")[0][-2000:]
    assert " forwards" not in html


def test_shipped_market_line_is_honest():
    import re
    import yaml
    data = yaml.safe_load(pal.MARKET_FILE.read_text())
    for ln in data["lines"]:
        assert ln["source"] and ln["checked"] and not re.search(r"\d", ln["text"])  # copy never quotes a figure


def test_rejection_is_never_pushed(db):
    _ev(db, "r1", "rejected", "2026-11-09 16:00")
    line = pal.push_line(db, stats.compute(db, NOW.date()), NOW)
    assert "no" not in line.lower().split() and "Acme" not in line and "stone" not in line


def test_pal_line_command(tmp_path, capsys):
    from autoapply import cli
    from test_daily import make
    _, _, cfg = make(tmp_path)
    cli.main(["--config", str(cfg), "pal-line"])
    out = capsys.readouterr().out.strip()
    assert out and "!" not in out and "\n" not in out


def test_one_interview_process_celebrates_once(db):
    _ev(db, "i1", "interview", "2026-11-09 18:00")
    _ev(db, "i2", "interview", "2026-11-10 07:00")  # the confirmation for the same job
    c = pal.celebration(db, stats.compute(db, NOW.date()), NOW.date())
    assert c["key"] == "celebrate:interview:gh:acme:1"
    db.set_nudge(c["key"], "done")
    assert pal.celebration(db, stats.compute(db, NOW.date()), NOW.date()) is None
    _ev(db, "i3", "interview", "2026-11-10 08:00", job=None, sender="Globex <hr@globex.example>")
    assert pal.celebration(db, stats.compute(db, NOW.date()), NOW.date())["key"] == "celebrate:interview:globex"


def test_rotation_never_breaks_house_rules(db):
    _ev(db, "r1", "rejected", "2026-11-09 16:00")
    for d in (10, 11):  # both rotations, while the rejection is still news
        g = _greet(db, datetime(2026, 11, d, 8, 0))
        assert "stone" in g["line"].lower() and "Acme" in g["line"] and "{" not in g["line"]
