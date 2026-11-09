"""Unemployment help: the claim's runway, claim-day and work-search to-dos, RESEA steps and agency letters."""
from datetime import date, datetime

import yaml

from autoapply import benefits, emailsync, nudges
from autoapply.web import my_state
from web_client import client
from test_daily import make


def _settings(tmp_path, **ws):
    s, db, cfg = make(tmp_path)
    s.raw["work_search"] = {"label": "DUA", "weekly_minimum": 3, "state": "MA", **ws}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(s.raw))
    return s, db


def test_runway_counts_the_waiting_week(tmp_path):
    s, db = _settings(tmp_path, claim_start="2026-10-05", weeks_allowed=26, weekly_benefit="1,015")
    r = benefits.runway(s, {**my_state(s), "waiting_week": True}, today=date(2026, 11, 4))
    # Filed 10/5: 4 weeks behind (10/5..11/1), one of them the unpaid waiting week, so 3 paid and 23 left.
    assert r["week_no"] == 5 and r["left"] == 23 and r["waiting"] and r["remaining_money"] == 23 * 1015
    assert benefits.runway(s, {"waiting_week": False}, today=date(2026, 11, 4))["left"] == 22
    s.raw["work_search"]["weeks_allowed"] = ""
    assert benefits.runway(s, None) is None


def test_claim_day_work_search_and_resea_todos(tmp_path):
    s, db = _settings(tmp_path, certify_day="Thursday")
    now = datetime(2026, 11, 5, 9)  # a Thursday
    assert benefits.add_resea(db, "MA") == 3 and benefits.add_resea(db, "MA") == 0
    t = benefits.tasks(db)[0]
    db.conn.execute("update ui_tasks set due = '2026-11-20' where id = ?", (t["id"],))
    benefits.add_task(db, "Send ID to DUA", "2027-01-30")  # far off: not yet a to-do
    todos = nudges.compute(db, now=now, settings=s)
    kinds = [n["kind"] for n in todos]
    assert kinds[0] == "claim" and "worksearch" in kinds and kinds.count("resea") == 3
    claim = todos[0]
    assert "0 of 3" in claim["why"]
    seminar = next(n for n in todos if n["title"].startswith("Career Center Seminar"))
    assert "Nov 20, in 15 days" in seminar["about"]
    assert not any("Send ID" in n["title"] for n in todos)
    c = client(s, db)
    c.post(f"/nudge/{seminar['key']}", data={"action": "done"})
    assert {t["title"]: t["done"] for t in benefits.tasks(db, include_done=True)}[seminar["title"]] == 1
    assert not nudges.for_agent(db, tmp_path / "data")  # no drafts for these


def test_agency_letters(tmp_path):
    s, db = _settings(tmp_path)
    assert benefits.is_agency("noreply@detma.mass.gov", "New correspondence in your UI Online inbox", "")
    assert benefits.is_agency("info@masshire-bostoncareers.org", "RESEA appointment", "")
    assert not benefits.is_agency("jobs@acme.com", "Unemployment rate report", "")
    assert not benefits.is_agency("news@census.gov", "Population estimates", "")
    at = datetime(2026, 11, 3, 10)
    assert benefits.due_date("Complete a Career Center Seminar by November 20, 2026.", at) == date(2026, 11, 20)
    assert benefits.due_date("second review no later than 12/4", at) == date(2026, 12, 4)
    assert benefits.due_date("nothing here", at) is None
    emailsync.apply_event(db, [], "<m1@x>", "MassHire", "resea@masshire-boston.org", "You have been selected for RESEA",
                          at, "You must complete a Career Center Seminar by November 20.")
    emailsync.apply_event(db, [], "<m2@x>", "DUA", "noreply@detma.mass.gov", "Notice of disqualification",
                          at, "Your claim has been denied for the week ending 11/1.")
    ev = {e["id"]: e for e in db.events()}
    assert ev["<m1@x>"]["kind"] == "agency" and ev["<m1@x>"]["reviewed"] == 1
    todos = nudges.compute(db, now=datetime(2026, 11, 4, 9), settings=s)
    letter = next(n for n in todos if n["kind"] == "agency")
    assert "due Nov 20" in letter["about"]
    appeal = next(n for n in todos if n["kind"] == "appeal")
    assert "appeal" in appeal["why"].lower() and appeal["key"].startswith("appeal-") and "<" not in appeal["key"]


def test_work_search_page_claim_and_tasks(tmp_path):
    s, db = _settings(tmp_path)
    c = client(s, db)
    assert "Add your claim's details" in c.get("/dua").text
    c.post("/dua/claim", data={"claim_start": "2026-10-05", "weekly_benefit": "$1,015", "weeks_allowed": "26", "certify_day": "Sunday"})
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())["work_search"]
    assert cfg["claim_start"] == "2026-10-05" and cfg["weekly_benefit"] == "1015" and cfg["weeks_allowed"] == 26
    assert cfg["state"] == "MA" and cfg["certify_day"] == "Sunday"
    c.post("/dua/task", data={"action": "resea"})
    c.post("/dua/task", data={"action": "add", "title": "Upload ID", "due": "2026-11-10"})
    html = c.get("/dua").text
    assert "weeks left" in html and "Initial RESEA review" in html and "Upload ID" in html
    assert "healthcare.gov" in html and "Asked to do RESEA" not in html
    tid = benefits.tasks(db)[-1]["id"]
    c.post("/dua/task", data={"action": "delete", "task_id": str(tid)})
    assert all(t["id"] != tid for t in benefits.tasks(db, include_done=True))


def test_done_resea_meeting_counts_in_the_log(tmp_path):
    from autoapply import stats
    s, db = _settings(tmp_path)
    benefits.add_resea(db, "MA")
    t = benefits.tasks(db)[0]
    db.conn.execute("update ui_tasks set due = '2026-11-03' where id = ?", (t["id"],))
    benefits.set_task(db, t["id"], done=True)
    weeks = stats.dua_weeks(db, date(2026, 11, 4))
    row = weeks[0]["rows"][0]
    assert row["type"].startswith("Reemployment appointment") and row["date"] == date(2026, 11, 3) and weeks[0]["count"] == 1
    benefits.set_task(db, t["id"], done=False)
    assert stats.dua_weeks(db, date(2026, 11, 4)) == []
