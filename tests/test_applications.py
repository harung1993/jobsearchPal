"""Your applications, kept in the local database: one row per role however it arrives (found by the run, logged by hand,
imported from an old tracker), the same role never offered twice, and a CSV out that imports back in unchanged."""
from datetime import datetime

from autoapply import history
from autoapply.config import Settings
from autoapply.db import DB
from autoapply.rank import Applied, company_key
from web_client import client

SHEET = (
    "﻿Company,Position,Date Applied,Salary,Applied via,Notes,Link\r\n"  # Google Sheets order differs; BOM from Excel
    "Brightline,\"Manager, Data Engineering\",10/5/2026,$122K,Greenhouse,Rejected 10/13,\r\n"
    "\"Sigma Computing, Inc.\",Data Engineer,10/12/2026,,Ashby,,https://jobs.ashbyhq.com/sigma/123?utm_source=li\r\n"
    "TalentCo,Recruiter lead,,,,call 10/7,\r\n"  # no applied date: a lead, not an application
)


def _db(tmp_path):
    return DB(tmp_path / "t.db")


def _found(db, jid, company, title, url="", status="new"):
    db.upsert_job({"id": jid, "ats": "greenhouse", "company": company, "title": title, "location": "", "url": url,
                   "apply_url": url, "description": ""})
    if status != "new":
        db.update(jid, status=status, submitted_at="2026-06-01 09:00")


def test_company_key_matches_board_slugs_and_legal_names():
    assert company_key("Sigma Computing, Inc.") == company_key("sigmacomputing") == "sigmacomputing"
    assert company_key("nichecom") == company_key("Niche") == "niche"
    assert company_key("Acme HQ") == company_key("acmehq") == "acme"
    assert company_key("Costco") == "costco" and company_key("Co") == "co"  # short names keep their letters
    assert company_key("Harbor AI") != company_key("Harbor")


def test_same_role_is_never_offered_again_but_the_company_returns(tmp_path):
    db = _db(tmp_path)
    _found(db, "gh:1", "Acme", "Data Engineer", "https://boards.greenhouse.io/acme/jobs/1", status="submitted")
    later = Applied(db, days=90, now=datetime(2026, 11, 9))  # June is outside the 90-day window
    assert "for this role" in later.why("acme", "Data Engineer")
    assert "for this role" in later.why("Acme Inc", "Platform Engineer", "https://boards.greenhouse.io/acme/jobs/1/")
    assert later.why("Acme", "Analytics Engineer") == ""  # another role at the company: fine after the window
    inside = Applied(db, days=90, now=datetime(2026, 7, 1))
    assert inside.why("Acme", "Analytics Engineer").startswith("already applied at Acme")


def test_query_ids_keep_postings_apart(tmp_path):
    db = _db(tmp_path)
    _found(db, "x:1", "Acme", "Data Engineer", "https://acme.example/apply?gh_jid=1", status="submitted")
    a = Applied(db, days=0)
    assert a.why("Other Co", "Different", "https://acme.example/apply?gh_jid=1&utm_source=x")
    assert not Applied(db, days=1, now=datetime(2027, 1, 1)).why("Other Co", "Different", "https://acme.example/apply?gh_jid=2")


def test_log_by_hand_once_and_marks_a_found_role(tmp_path):
    db = _db(tmp_path)
    r = history.log(db, "Globex", "Analytics Engineer", applied_on="2026-11-03", via="LinkedIn Easy Apply")
    assert r["status"] == "added" and r["job"]["status"] == "submitted" and r["job"]["submitted_at"] == "2026-11-03 12:00"
    assert r["job"]["ats"] == "linkedin"
    assert history.log(db, "globex", "analytics engineer")["status"] == "already"
    _found(db, "gh:9", "Initech", "Staff Data Engineer")  # the run found it; you applied on their site
    r = history.log(db, "Initech, Inc.", "Staff Data Engineer", applied_on="11/4/2026")
    assert r["status"] == "marked" and r["id"] == "gh:9" and db.get("gh:9")["status"] == "submitted"
    assert len(db.by_status("submitted")) == 2


def test_log_needs_company_title_and_a_readable_date(tmp_path):
    db = _db(tmp_path)
    for args in (("", "Role"), ("Co", "")):
        try:
            history.log(db, *args)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    try:
        history.log(db, "Acme", "AE", applied_on="next tuesday")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "next tuesday" in str(e)
    assert db.all() == []


def test_csv_import_by_header_name_is_idempotent_and_meets_hand_logs(tmp_path):
    db = _db(tmp_path)
    history.log(db, "Brightline", "Manager, Data Engineering", applied_on="2026-10-05")
    assert history.import_csv(db, SHEET) == 1  # Brightline was already logged; TalentCo has no date
    assert history.import_csv(db, SHEET) == 0
    jobs = {j["company"]: j for j in db.by_status("submitted")}
    assert set(jobs) == {"Brightline", "Sigma Computing, Inc."}
    assert jobs["Brightline"]["outcome"] == "rejected" and jobs["Brightline"]["pay"] == "$122K"
    _found(db, "ashby:sigma", "sigmacomputing", "Data Engineer")  # the board finds it later
    assert "for this role" in Applied(db).why("sigmacomputing", "Data Engineer")


def test_export_round_trips(tmp_path):
    db = _db(tmp_path)
    history.import_csv(db, SHEET)
    history.log(db, "Globex", "AE", url="https://globex.example/jobs/7", pay="$90K")
    out = history.export_csv(db)
    assert out.splitlines()[0].startswith("Position,Company,Location,Date Applied")
    fresh = DB(tmp_path / "fresh.db")
    assert history.import_csv(fresh, out) == 3
    assert history.import_csv(db, out) == 0
    assert {j["apply_url"] for j in fresh.all()} >= {"https://globex.example/jobs/7"}


def test_old_json_rows_still_import(tmp_path):
    db = _db(tmp_path)
    rows = [["Position", "Company", "Location", "Date Applied", "Salary Range", "Found on", "Applied via", "Notes"],
            ["Head of Data", "Cobalt Labs", "remote", "10/12/2026", "$195K", "LinkedIn", "Greenhouse", "Applied 10/12"]]
    assert history.import_rows(db, rows) == 1 and db.all()[0]["ats"] == "greenhouse"


def test_dashboard_log_import_and_export(tmp_path):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={"first_name": "Alex"})
    db = DB(s.data_dir / "t.db")
    c = client(s, db)
    html = c.get("/").text
    assert "Log one you sent elsewhere" in html and "Bring in your old tracker" in html
    r = c.post("/applications/log", data={"company": "Globex", "title": "Analytics Engineer", "applied_on": "2026-11-03"},
               follow_redirects=False)
    assert r.status_code == 303 and "Added" in r.headers["location"]
    again = c.post("/applications/log", data={"company": "Globex", "title": "Analytics Engineer"}, follow_redirects=True)
    assert "already have Analytics Engineer at Globex" in again.text
    bad = c.post("/applications/log", data={"company": "", "title": "x"}, follow_redirects=True)
    assert "A company and a role title are needed." in bad.text
    up = c.post("/applications/import", files={"file": ("tracker.csv", SHEET.encode(), "text/csv")}, follow_redirects=True)
    assert "Imported 2 applications" in up.text
    csv_out = c.get("/applications.csv")
    assert csv_out.status_code == 200 and csv_out.headers["content-type"].startswith("text/csv")
    assert "Globex" in csv_out.text and "Sigma Computing, Inc." in csv_out.text
    assert len(db.by_status("submitted")) == 3



def test_fill_refuses_a_role_already_applied_to(tmp_path):
    """A role you applied to by hand that later reaches the run as a new job (an alert, a lead, `add`) is never filled."""
    import json
    import pytest
    import yaml
    from autoapply import cli
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"data_dir": str(tmp_path / "data")}))
    (tmp_path / "data").mkdir()
    db = DB(tmp_path / "data" / "autoapply.db")
    history.log(db, "Globex", "Analytics Engineer", applied_on="2026-11-03")
    _found(db, "gh:globex:5", "globex", "Analytics Engineer", "https://boards.greenhouse.io/globex/jobs/5")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"answers": {}}))
    with pytest.raises(SystemExit) as e:
        cli.main(["--config", str(cfg), "fill", str(plan), "--job", "gh:globex:5"])
    assert "for this role" in str(e.value)
    assert db.get("gh:globex:5")["status"] == "skipped"


def test_hand_logged_rows_are_a_record_not_a_review_page(tmp_path):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={"first_name": "Alex"})
    db = DB(s.data_dir / "t.db")
    c = client(s, db)
    a = history.log(db, "Globex", "Analytics Engineer")
    b = history.log(db, "Initech", "Data Lead", url="https://initech.example/jobs/3")
    html = c.get("/").text
    assert f'/job/{a["id"]}' not in html and f'/job/{b["id"]}' not in html
    assert 'href="https://initech.example/jobs/3"' in html
