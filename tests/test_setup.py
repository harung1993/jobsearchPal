"""Setup page: a fresh install writes the same files you'd edit by hand, and never runs on the example."""
import io
import json
import os
import shutil
from pathlib import Path

import pytest
import yaml
from docx import Document
from fastapi.testclient import TestClient

from autoapply import config, setup
from autoapply.db import DB
from autoapply.web import make_app
from web_client import client

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    for f in ("config.example.yaml", "profile.example.yaml"):
        shutil.copy(REPO / f, tmp_path / f)
    for k in config.SECRET_KEYS:
        monkeypatch.delenv(k, raising=False)
    config.FROM_SECRETS.clear()
    s = config.load(str(tmp_path / "config.yaml"), allow_example=True)
    db = DB(s.data_dir / "t.db")
    yield s, client(s, db)
    for k in list(config.FROM_SECRETS):
        os.environ.pop(k, None)
    config.FROM_SECRETS.clear()


def _resume() -> bytes:
    d = Document()
    d.add_paragraph("Ada Lovelace")
    d.add_paragraph("ada@example.org | (555) 123-4567 | linkedin.com/in/ada-l")
    d.add_paragraph("Experience")
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def test_fresh_install_goes_to_setup_and_nothing_runs(fresh, tmp_path):
    s, c = fresh
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    assert "Base resume" in c.get("/setup").text
    with pytest.raises(SystemExit):
        config.load(str(tmp_path / "config.yaml"))  # every other command refuses to run on the example


def test_walkthrough_writes_the_files(fresh, tmp_path, monkeypatch):
    s, c = fresh
    monkeypatch.setattr(setup.shutil, "which", lambda n: None)  # no LibreOffice in the test
    r = c.post("/setup/resume", files={"docx": ("cv.docx", _resume())})
    assert r.status_code == 200
    assert (tmp_path / "materials" / "Lovelace Resume - Base.docx").exists()
    page = c.get("/setup").text
    assert 'value="ada@example.org"' in page and 'value="Ada"' in page  # prefilled from the resume
    assert "Jane" not in page

    c.post("/setup/profile", data={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.org",
                                   "requires_sponsorship": "No", "salary_expectation": "$180,000"})
    prof = yaml.safe_load((tmp_path / "profile.yaml").read_text())
    assert prof["first_name"] == "Ada" and prof["salary_expectation"] == "180000"
    assert any(r.get("value") == "Ada Lovelace" for r in prof["rules"])
    assert prof["hold_for_review"]  # consent rules kept

    r = c.post("/setup/interests", data={"titles": "Data Engineer, analytics engineer", "exclude": "intern",
                                         "us_only": "1", "feed::remotive": "1",
                                         "companies": "https://job-boards.greenhouse.io/gitlab\njobs.lever.co/netflix/\nashby ramp\nworkday acme"})
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert cfg["search"]["title_keywords"] == ["data engineer", "analytics engineer"]
    assert cfg["boards"] == [{"ats": "greenhouse", "slug": "gitlab"}, {"ats": "lever", "slug": "netflix"},
                             {"ats": "ashby", "slug": "ramp"}]
    assert cfg["feeds"] == ["remotive"] and "_from_example" not in cfg
    assert "workday acme" in r.text  # told what it couldn't read

    c.post("/setup/about", data={"roles": "Staff data engineer", "pay": "$180K"})
    md = (tmp_path / "materials" / "context" / "setup.md").read_text()
    assert "Staff data engineer" in md and "## Pay ask" in md

    st = setup.status(s, os.environ)
    assert not set(st["left"]) - {"agent"}
    assert c.get("/", follow_redirects=False).status_code == 200  # dashboard opens now


def test_rejects_non_docx(fresh):
    _, c = fresh
    r = c.post("/setup/resume", files={"docx": ("cv.docx", b"not a zip")})
    assert "a Word .docx file" in r.text


def test_account_comes_first_and_then_sign_in_is_required(fresh):
    s, signed_in = fresh
    (s.data_dir / "account.json").unlink()  # back to a brand-new install
    c = TestClient(make_app(s, DB(s.data_dir / "t.db")))
    html = {"accept": "text/html"}
    for path in ("/", "/setup", "/leads"):  # every page sends a new install to "Create your account"
        assert c.get(path, headers=html, follow_redirects=False).headers["location"] == "/account"
    assert "Create your account" in c.get("/account").text and "Setup" not in c.get("/account").text
    r = c.post("/account", data={"email": "me@example.org", "password": "long enough 1", "again": "long enough 1"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert oct((s.data_dir / "account.json").stat().st_mode)[-3:] == "600"
    assert "long enough" not in (s.data_dir / "account.json").read_text()
    saved = json.loads((s.data_dir / "secrets.json").read_text())  # the finish key, made silently
    assert saved["AUTOAPPLY_TOKEN"] == os.environ["AUTOAPPLY_TOKEN"]
    assert c.get("/setup").status_code == 200  # this browser is signed in
    assert "Dashboard password" not in c.get("/setup").text and c.post("/setup/token").status_code in (404, 405)
    assert TestClient(c.app).get("/setup", headers=html, follow_redirects=False).headers["location"] == "/login?next=/setup"
    assert c.get("/account", follow_redirects=False).headers["location"] == "/"  # only one account, ever


def test_gmail_saved_only_after_login_works(fresh, monkeypatch):
    s, c = fresh
    monkeypatch.setattr(setup, "test_gmail", lambda u, p: "Gmail refused the login.")
    assert "Not saved" in c.post("/setup/gmail", data={"gmail_user": "a@gmail.com", "gmail_password": "abcd efgh"}).text
    assert not (s.data_dir / "secrets.json").exists()
    seen = {}
    monkeypatch.setattr(setup, "test_gmail", lambda u, p: seen.update(u=u, p=p) or "")
    c.post("/setup/gmail", data={"gmail_user": "a@gmail.com", "gmail_password": "abcd efgh ijkl mnop"})
    assert seen["p"] == "abcdefghijklmnop" and os.environ["GMAIL_APP_PASSWORD"] == "abcdefghijklmnop"
    assert "abcdefghijklmnop" not in c.get("/setup").text  # never shown again


def test_board_urls():
    assert setup.parse_board("https://boards.greenhouse.io/airbnb/jobs/123") == ("greenhouse", "airbnb")
    assert setup.parse_board("https://jobs.ashbyhq.com/ramp?x=1") == ("ashby", "ramp")
    assert setup.parse_board("smartrecruiters:Visa") == ("smartrecruiters", "Visa")
    assert setup.parse_board("acme careers") is None


def test_job_sites_feeds_and_keys(fresh, tmp_path, monkeypatch):
    s, c = fresh
    for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "USAJOBS_API_KEY", "USAJOBS_EMAIL"):
        monkeypatch.delenv(k, raising=False)
    r = c.post("/setup/interests", data={
        "titles": "data engineer", "feed::himalayas": "1", "feed::usajobs": "1", "feed::adzuna": "1",
        "ADZUNA_APP_ID": "abc", "ADZUNA_APP_KEY": "secretkey123",
        "rss": "HigherEdJobs: IR | https://www.higheredjobs.com/search/rss.cfm?JobCat=31\nhttps://weworkremotely.com/x.rss\nnot a url"})
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert cfg["feeds"] == ["himalayas", "adzuna", "usajobs"]
    assert cfg["rss_feeds"] == [{"name": "HigherEdJobs: IR", "url": "https://www.higheredjobs.com/search/rss.cfm?JobCat=31"},
                                {"url": "https://weworkremotely.com/x.rss"}]
    assert "not a url" in r.text and "USAJOBS" in r.text  # bad line and the keyless site are both reported
    assert os.environ["ADZUNA_APP_KEY"] == "secretkey123"
    page = c.get("/setup").text
    assert "HigherEdJobs: IR | https://www.higheredjobs.com" in page and "secretkey123" not in page
    # A key without its sign-up email names the empty field.
    r = c.post("/setup/interests", data={"titles": "data engineer", "feed::usajobs": "1", "USAJOBS_API_KEY": "k123"})
    assert "USAJOBS (needs its sign-up email)" in r.text and "needs its key" not in r.text


def test_settings_tabs(fresh):
    _, c = fresh
    html = c.get("/setup").text
    for label in ("Setup", "Email sorting", "Daily run", "Costs &amp; limits"):
        assert label in html
    assert 'href="/setup" aria-current="page"' in html  # the Settings menu item opens Setup
    r = c.post("/settings", data={"tab": "daily", "daily_agent": "claude", "action": "save"}, follow_redirects=False)
    assert r.headers["location"].startswith("/settings?tab=daily")
    assert c.get("/settings?tab=setup", follow_redirects=False).headers["location"] == "/setup"


def test_real_jane_can_finish_contact(tmp_path):
    import yaml as _y
    from autoapply import setup as su
    from autoapply.config import Settings
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={})
    prof = tmp_path / "profile.yaml"
    prof.write_text(_y.safe_dump({"first_name": "Jane", "last_name": "Doe", "email": "jane.doe@example.com"}))
    done = lambda: su.status(s, {})["steps"]["profile"]["done"]
    assert not done()  # the untouched example
    prof.write_text(_y.safe_dump({"first_name": "Jane", "last_name": "Smith", "email": "jane.smith@mail.example"}))
    assert done()


def test_pick_state_for_work_search(fresh, tmp_path):
    s, c = fresh
    c.post("/setup/interests", data={"titles": "data engineer", "ws_state": "ma", "ws_min": "3", "ws_label": "DUA"})
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert cfg["work_search"] == {"label": "DUA", "weekly_minimum": 3, "state": "MA"}
    html = c.get("/dua").text
    assert "Massachusetts's rule" in html and "mass.gov" in html and "3 / 3" not in html
    c.post("/setup/interests", data={"titles": "data engineer", "ws_state": "XX", "ws_min": "2"})
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert "state" not in cfg["work_search"] and cfg["work_search"]["weekly_minimum"] == 2
