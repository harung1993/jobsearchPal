"""Leads: every role in job-alert emails is kept, de-duplicated across sources, and can be starred."""
import json
from datetime import datetime


from autoapply import cli, leads
from web_client import client
from test_daily import make

LINKEDIN = """Your job alert for analytics engineer in Greater Boston
Senior Analytics Engineer
Hooli
Cambridge, MA

This company is actively hiring
View job: https://www.linkedin.com/comm/jobs/view/111/?trackingId=abc&refId=x

---------------------------------------------------------

Staff Data Engineer, Platform
Initech
Boston, MA

1 connection
View job: https://www.linkedin.com/comm/jobs/view/222/?trackingId=def

---------------------------------------------------------

See all jobs on LinkedIn: https://www.linkedin.com/comm/jobs/search-results/?keywords=x
"""

INDEED = """Hi Jane,

Your background as an analytics engineer could be a strong match for this Senior Analytics Engineer role at Hooli. With your expertise in Snowflake and dbt, you could excel in this position.

Senior Analytics Engineer
Hooli
Remote
Salary: $150,000 - $180,000 a year
Work setting: Remote

View job: https://cts.indeed.com/v3/abc
Apply now: https://cts.indeed.com/v3/def
"""


def test_parse_linkedin_and_indeed():
    li = leads.parse(LINKEDIN)
    assert [(j["company"], j["title"], j["location"]) for j in li] == [
        ("Hooli", "Senior Analytics Engineer", "Cambridge, MA"), ("Initech", "Staff Data Engineer, Platform", "Boston, MA")]
    assert li[0]["url"] == "https://www.linkedin.com/comm/jobs/view/111/"
    ind = leads.parse(INDEED)
    assert len(ind) == 1 and ind[0]["company"] == "Hooli" and ind[0]["salary"] == "$150,000 - $180,000 a year"


def test_save_dedupes_and_tracks(tmp_path, capsys):
    s, db, cfg = make(tmp_path)
    now = datetime(2026, 11, 3, 9)
    assert leads.save(db, leads.parse(LINKEDIN), "Linkedin", now, s.raw["search"], set()) == 2
    assert leads.save(db, leads.parse(INDEED), "Indeed", now, s.raw["search"], set()) == 0  # same Hooli role
    rows = {r["company"]: r for r in leads.rows(db)}
    assert rows["Hooli"]["seen"] == 2 and rows["Hooli"]["source"] == "Indeed, Linkedin" and rows["Hooli"]["salary"]
    assert rows["Hooli"]["score"] > 0
    leads.set_status(db, rows["Initech"]["key"], "starred")
    cli.main(["--config", str(cfg), "leads", "lookup"])
    assert capsys.readouterr().out.strip() == "1"
    picked = json.loads((s.data_dir / "daily" / "alert-roles.json").read_text())
    assert picked[0]["company"] == "Initech" and picked[0]["link"].endswith("/222/")
    db.upsert_job({"id": "gh:initech:9", "ats": "greenhouse", "company": "Initech", "title": "Staff Data Engineer, Platform",
                   "location": "Boston", "url": "u", "apply_url": "u", "description": ""})
    cli.main(["--config", str(cfg), "leads", "lookup"])
    assert capsys.readouterr().out.strip() == "0"  # tracked now: nothing left to look up
    assert {r["company"]: r for r in leads.rows(db)}["Initech"]["job_id"] == "gh:initech:9"


def test_leads_page_star_and_dismiss(tmp_path):
    s, db, cfg = make(tmp_path)
    leads.save(db, leads.parse(LINKEDIN), "Linkedin", datetime(2026, 11, 3, 9), {}, set())
    c = client(s, db)
    html = c.get("/leads").text
    assert "Hooli" in html and "Initech" in html and "To look at" in html
    k = leads.rows(db)[0]["key"]
    c.post("/leads", data={"key": k, "status": "starred"})
    assert "★" in c.get("/leads?show=starred").text
    c.post("/leads", data={"key": k, "status": "dismissed"})
    assert k not in [r["key"] for r in leads.rows(db) if r["status"] != "dismissed"]
    assert c.post("/leads", data={"key": k, "status": "approved"}).status_code == 400


INDEED_DIGEST = """Hi Jane, Your background could be a great match for this Distinguished Engineer, AI position at Hooli. Your experience could be valuable for their team. Apply now or explore other opportunities below.
Jobs are based on your preferences, profile, and activity on Indeed

Distinguished Engineer, AI
Hooli - Remote
$268,000 - $559,000 a year
Easily apply
Provide technical guidance for the end-to-end model lifecycle: define engineering standards for model training and evaluation work.

https://www.indeed.com/pagead/clk/dl?from=jobi2a&jrtk=5-abc

Analytics Engineer
Initech - Boston, MA
Easily apply

https://www.indeed.com/rc/clk?jk=123

Salaries estimated if unavailable.
"""


def test_parse_indeed_digest():
    got = [(j["company"], j["title"], j["location"], j["salary"]) for j in leads.parse(INDEED_DIGEST)]
    assert got == [("Hooli", "Distinguished Engineer, AI", "Remote", "$268,000 - $559,000 a year"),
                   ("Initech", "Analytics Engineer", "Boston, MA", "")]


def test_already_applied_companies_are_skipped(tmp_path, capsys):
    from autoapply import rank
    s, db, cfg = make(tmp_path)
    db.upsert_job({"id": "tracker:acme", "ats": "tracker", "company": "Acme", "title": "Analytics Engineer", "location": "",
                   "url": "", "apply_url": "", "description": ""})
    db.update("tracker:acme", status="submitted", submitted_at=datetime.now().strftime("%Y-%m-%d"))
    db.add_event({"id": "<c@x>", "job_id": None, "kind": "confirmed", "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                  "sender": "Initech <no-reply@ashbyhq.com>", "subject": "Thank you for applying to Initech", "reviewed": 1})
    ids = [c["id"] for c in rank.candidates(db, s)]
    assert ids == [] or all(i not in ids for i in ("gh:a:1", "wd:c:3"))
    assert "already applied at Acme" in db.get("gh:a:1")["error"] and "from your email" in db.get("wd:c:3")["error"]
    db.update("gh:a:1", status="new")  # a pick that slipped through is still stopped before an apply session
    (s.data_dir / "daily").mkdir(exist_ok=True)
    (s.data_dir / "daily" / "picks.json").write_text(json.dumps([{"id": "gh:a:1"}]))
    cli.main(["--config", str(cfg), "daily-picks"])
    assert capsys.readouterr().out.strip() == "" and db.get("gh:a:1")["status"] == "skipped"


def test_auto_apply_one_lead(tmp_path, monkeypatch, capsys):
    import subprocess
    s, db, cfg = make(tmp_path)
    leads.save(db, leads.parse(LINKEDIN), "Linkedin", datetime(2026, 11, 3, 9), {}, set())
    k = leads.key("Initech", "Staff Data Engineer, Platform")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append(kw["env"]))
    c = client(s, db)
    assert "Auto apply" in c.get("/leads").text and "uses credits" in c.get("/leads").text
    c.post("/leads/apply", data={"key": k})
    assert started and started[0]["AUTOAPPLY_LEAD"] == k and started[0]["AUTOAPPLY_TRIGGER"] == "manual"
    monkeypatch.setenv("AUTOAPPLY_LEAD", k)
    cli.main(["--config", str(cfg), "leads", "lookup"])
    assert capsys.readouterr().out.strip() == "1"
    assert json.loads((s.data_dir / "daily" / "alert-roles.json").read_text())[0]["company"] == "Initech"
    db.upsert_job({"id": "gh:initech:9", "ats": "greenhouse", "company": "Initech", "title": "Staff Data Engineer, Platform",
                   "location": "", "url": "u", "apply_url": "u", "description": ""})
    cli.main(["--config", str(cfg), "leads", "job", k])
    assert capsys.readouterr().out.strip() == "gh:initech:9"


def test_resolve_finds_lead_on_company_board(tmp_path):
    """11/4: alert leads linked only to LinkedIn. Each sync looks the best ones up on the company's own board, no AI."""
    s, db, cfg = make(tmp_path)
    now = datetime(2026, 11, 4, 9)
    leads.save(db, [{"title": "Sr. Analytics Engineer", "company": "Hooli, Inc.", "location": "Remote", "salary": "",
                     "url": "https://www.linkedin.com/comm/jobs/view/111/"},
                    {"title": "Staff Data Engineer", "company": "Initech", "location": "", "salary": "", "url": "u2"},
                    {"title": "Line Cook", "company": "Hooli, Inc.", "location": "", "salary": "", "url": "u3"}],
               "Linkedin", now, {}, set())
    calls = []

    def board(ats):
        def f(slug):
            calls.append((ats, slug))
            if ats == "ashby" and slug == "hooli":
                return [{"id": "ashby:hooli:9", "ats": "ashby", "company": "hooli", "title": "Senior Analytics Engineer",
                         "location": None, "url": "https://jobs.ashbyhq.com/hooli/9", "apply_url": "https://jobs.ashbyhq.com/hooli/9/application",
                         "description": "dbt"}]
            raise RuntimeError("404")
        return f
    fetchers = {a: board(a) for a in ("greenhouse", "lever", "ashby", "workable")}
    assert leads.slugs("Hooli, Inc.")[0] == "hooli"
    assert "rocket-money" in leads.slugs("Rocket Money")
    out = leads.resolve(db, s, fetchers=fetchers, now=now)
    assert out == {"checked": 3, "found": 1, "companies": 2}
    assert sum(1 for c in calls if c[1] == "hooli") == 3  # one board per company per run, not one per lead
    r = leads.get(db, leads.key("Hooli, Inc.", "Sr. Analytics Engineer"))
    assert r["job_id"] == "ashby:hooli:9" and r["status"] == "tracked" and r["apply_url"] == "https://jobs.ashbyhq.com/hooli/9"
    job = db.get("ashby:hooli:9")
    assert job["company"] == "Hooli, Inc." and job["status"] == "new"
    assert leads.get(db, leads.key("Hooli, Inc.", "Line Cook"))["job_id"] is None
    calls.clear()
    assert leads.resolve(db, s, fetchers=fetchers, now=now)["checked"] == 0 and not calls  # tried this week already
    html = client(s, db).get("/leads?show=all").text
    assert "company site" in html and "https://jobs.ashbyhq.com/hooli/9" in html and "company page not found yet" in html


def test_job_sources_overview(tmp_path, monkeypatch):
    """11/5: every job source in one list on Leads, so new users see LinkedIn/Indeed/HigherEdJobs alerts and the job sites."""
    from autoapply import jobsources
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    s, db, cfg = make(tmp_path)
    o = jobsources.overview(s, db)
    names = {i["name"]: i for g in o["groups"] for i in g["items"]}
    assert {"LinkedIn", "Indeed", "HigherEdJobs", "USAJOBS", "The Muse"} <= set(names)
    assert names["HigherEdJobs"]["status"] == "needs" and names["HigherEdJobs"]["href"] == "/setup#gmail"  # no Gmail yet
    assert 0 <= o["on"] <= o["total"] == len(names)
    html = client(s, db).get("/leads").text
    assert "Where your jobs come from" in html and "HigherEdJobs" in html


def test_job_sources_are_grouped_by_what_needs_doing(tmp_path, monkeypatch):
    """Working sources in a grid, ones needing a step on rows, every off source in one line; the watched
    companies can be listed."""
    from autoapply import jobsources
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    s, db, cfg = make(tmp_path)
    o = jobsources.overview(s, db)
    assert {i["status"] for i in o["working"]} <= {"on"} and {i["status"] for i in o["off"]} <= {"off"}
    assert len(o["working"]) + len(o["needs"]) + len(o["off"]) == o["total"] - 1  # minus the company boards row
    assert [c["name"] for c in o["companies"]] == sorted((c["name"] for c in o["companies"]), key=str.lower)
    html = client(s, db).get("/leads").text
    assert "Not on yet:" in html and "Needs a step" in html
    if o["companies"]:
        assert 'id="co-filter"' in html and "See list" in html


# ---------- Paste a job (11/10) ----------

PASTED = {"company": "Hooli", "title": "Senior Analytics Engineer", "location": "", "work_setting": "remote",
          "pay": "$150K", "url": "", "description": "dbt and Snowflake"}


def test_paste_adds_then_updates(tmp_path):
    s, db, _ = make(tmp_path)
    assert leads.add_pasted(db, s, PASTED)["result"] == "added"
    r = leads.add_pasted(db, s, {**PASTED, "description": "longer text"})
    assert r["result"] == "updated"
    row = leads.get(db, r["key"])
    assert row["description"] == "dbt and Snowflake" and "pasted" in row["source"] and row["work_setting"] == "remote"


def test_paste_fills_in_an_alert_lead(tmp_path):
    s, db, _ = make(tmp_path)
    leads.save(db, leads.parse(LINKEDIN), "LinkedIn", datetime(2026, 11, 3, 9), {}, set())
    r = leads.add_pasted(db, s, PASTED)
    row = leads.get(db, r["key"])
    assert r["result"] == "updated" and row["source"] == "LinkedIn, pasted" and row["description"] == "dbt and Snowflake"


def test_paste_of_applied_role_adds_nothing(tmp_path):
    s, db, _ = make(tmp_path)
    db.update("gh:a:1", status="submitted", submitted_at="2026-10-30 10:00")
    r = leads.add_pasted(db, s, {**PASTED, "company": "Acme", "title": "Senior Analytics Engineer"})
    assert r["result"] == "applied" and "2026-10-30" in r["why"] and leads.get(db, r["key"]) is None


def test_paste_needs_company_and_title(tmp_path):
    s, db, _ = make(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        leads.add_pasted(db, s, {**PASTED, "company": " "})


def test_from_paste_makes_a_job(tmp_path):
    s, db, _ = make(tmp_path)
    k = leads.add_pasted(db, s, {**PASTED, "title": "Data Lead", "location": "Boston, MA", "pay": "$1",
                                 "url": "javascript:x", "description": "the post"})["key"]
    jid = leads.from_paste(db, k)
    j = db.get(jid)
    assert jid.startswith("manual:") and j["ats"] == "manual" and j["description"] == "the post"
    assert j["url"] == "" and j["pay"] == "$1" and j["location"] == "Boston, MA"
    assert leads.get(db, k)["job_id"] == jid and leads.from_paste(db, k) == jid


def test_from_paste_needs_the_post(tmp_path):
    s, db, _ = make(tmp_path)
    k = leads.add_pasted(db, s, {**PASTED, "description": ""})["key"]
    assert leads.from_paste(db, k) is None and leads.from_paste(db, "no|such") is None


def test_prepped_is_ready_but_not_applied(tmp_path):
    s, db, _ = make(tmp_path)
    db.update("gh:a:1", status="prepped")
    from autoapply import rank, stats
    assert not rank.Applied(db, 90).same_role("Acme", "Senior Analytics Engineer", "u")
    assert "gh:a:1" in [j["id"] for j in stats.compute(db)["ready"]]
    assert "gh:a:1" not in [j["id"] for j in rank.shortlist(db, s, 5)]
