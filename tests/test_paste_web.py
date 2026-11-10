"""Paste a job on the dashboard: confirm, save, the lead's page, Prep only, and the kit on the job page."""
import json

from autoapply import leads, paste
from test_daily import make
from test_paste import FIX
from web_client import client


def test_from_link_reads_a_greenhouse_posting():
    jobs = [{"id": "greenhouse:hooli:4242", "title": "Data Lead", "location": "Remote", "url": "https://boards.greenhouse.io/hooli/jobs/4242",
             "description": "<p>Own dbt.</p><p>Pay: $150,000 - $180,000</p>"}]
    r = paste.from_link("https://boards.greenhouse.io/hooli/jobs/4242?gh_src=x", {"greenhouse": lambda slug: jobs})
    assert r["title"] == "Data Lead" and r["company"] == "Hooli" and r["work_setting"] == "remote" and "Own dbt." in r["description"]
    assert paste.from_link("https://www.linkedin.com/jobs/view/1") is None
    assert paste.from_link("https://boards.greenhouse.io/hooli/jobs/999", {"greenhouse": lambda slug: jobs}) is None


def test_paste_confirm_then_save(tmp_path):
    s, db, _ = make(tmp_path)
    c = client(s, db)
    r = c.post("/leads/paste", data={"text": FIX("paste_linkedin.txt")})
    assert r.status_code == 200 and 'value="Liberty Mutual Insurance"' in r.text and "$137K/yr" in r.text
    assert "Check the details" in r.text
    r = c.post("/leads/add", data={"company": "Liberty Mutual Insurance", "title": "Director I, Data Science- AI Products",
                                   "location": "Boston, MA", "work_setting": "on-site", "pay": "$137K/yr - $257K/yr",
                                   "url": "", "description": "the whole post"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/lead/")
    page = c.get(r.headers["location"]).text
    assert "Prep only" in page and "Auto apply" in page and "the whole post" in page and "$137K/yr" in page


def test_linkedin_link_asks_for_text(tmp_path):
    s, db, _ = make(tmp_path)
    t = client(s, db).post("/leads/paste", data={"text": "https://www.linkedin.com/jobs/view/1"}).text
    assert "copy the whole page" in t


def test_paste_of_applied_role_says_so(tmp_path):
    s, db, _ = make(tmp_path)
    db.update("gh:a:1", status="submitted", submitted_at="2026-10-30 10:00")
    r = client(s, db).post("/leads/add", data={"company": "Acme", "title": "Senior Analytics Engineer", "description": "x"},
                           follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/leads?") and "2026-10-30" in r.headers["location"]
    assert not leads.rows(db)


def test_pasted_html_is_escaped(tmp_path):
    s, db, _ = make(tmp_path)
    c = client(s, db)
    r = c.post("/leads/add", data={"company": "X", "title": "<script>x</script>", "description": "<img src=x onerror=1>"})
    assert "<script>x</script>" not in r.text and "<img src=x" not in r.text
    r = c.post("/leads/paste", data={"text": "<script>y</script>\nAcme\n<img src=x onerror=1>"})
    assert "<script>y</script>" not in r.text and "<img src=x" not in r.text


def test_lead_with_job_goes_to_the_job_page(tmp_path):
    s, db, _ = make(tmp_path)
    k = leads.add_pasted(db, s, {"company": "Hooli", "title": "Data Lead", "description": "the post"})["key"]
    jid = leads.from_paste(db, k)
    c = client(s, db)
    r = c.get(f"/lead/{k}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/job/{jid}"
    t = c.get(r.headers["location"]).text
    assert "the post" in t and "Prep only" in t and 'value="submit"' not in t
    assert c.get("/lead/no|such").status_code == 404


def test_run_buttons_start_the_right_run(tmp_path, monkeypatch):
    s, db, _ = make(tmp_path)
    runs = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: runs.append(k["env"]))
    monkeypatch.setattr("time.sleep", lambda *_: None)
    c = client(s, db)
    c.post("/prepare/wd:c:3", data={"mode": "prep"})
    assert runs[-1].get("AUTOAPPLY_PREP_ONLY") == "1" and runs[-1]["AUTOAPPLY_JOB"] == "wd:c:3"
    c.post("/prepare/gh:a:1")
    assert "AUTOAPPLY_PREP_ONLY" not in runs[-1] or runs[-1]["AUTOAPPLY_PREP_ONLY"] != "1"
    k = leads.add_pasted(db, s, {"company": "Hooli", "title": "Data Lead", "description": "the post"})["key"]
    c.post(f"/lead/{k}/run", data={"mode": "prep"})
    assert runs[-1]["AUTOAPPLY_LEAD"] == k and runs[-1].get("AUTOAPPLY_PREP_ONLY") == "1"
    assert leads.get(db, k)["status"] == "starred"


def test_alert_lead_takes_a_pasted_post(tmp_path):
    s, db, _ = make(tmp_path)
    k = leads.add_pasted(db, s, {"company": "Hooli", "title": "Data Lead", "description": ""})["key"]
    c = client(s, db)
    assert "Paste the post to prep from it" in c.get(f"/lead/{k}").text
    c.post(f"/lead/{k}/description", data={"text": "now with text"})
    assert leads.get(db, k)["description"] == "now with text"


def _prepped(s, db):
    pdf = s.data_dir / "applications" / "initech" / "Doe Resume - Initech.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4")
    (pdf.parent / "notes.md").write_text("Fit: good. apply by hand")
    db.update("wd:c:3", status="prepped", apply_url="https://acme.wd1.myworkdayjobs.com/x",
              plan_json={"url": "https://acme.wd1.myworkdayjobs.com/x", "files": {"resume": str(pdf)},
                         "answers": {"Why Initech?": "Because dbt."}})


def test_prepped_job_shows_the_kit_not_submit(tmp_path):
    s, db, _ = make(tmp_path)
    _prepped(s, db)
    t = client(s, db).get("/job/wd:c:3").text
    assert "Your kit" in t and "Because dbt." in t and "Doe Resume - Initech.pdf" in t and "I applied by hand" in t
    assert 'value="submit"' not in t and "Save and refill" not in t and "myworkdayjobs.com/x" in t


def test_applied_by_hand_keeps_the_kit_and_moves_the_lead(tmp_path):
    s, db, _ = make(tmp_path)
    _prepped(s, db)
    leads.ensure(db)
    db.conn.execute("insert into leads (key, title, company, status, job_id) values ('initech|analytics engineer', "
                    "'Analytics Engineer', 'Initech', 'prepped', 'wd:c:3')")
    db.conn.commit()
    client(s, db).post("/job/wd:c:3", data={"action": "manual"})
    j = db.get("wd:c:3")
    assert j["status"] == "submitted" and json.loads(j["plan_json"])["files"]["resume"].endswith(".pdf")
    assert leads.get(db, "initech|analytics engineer")["status"] == "applied"


def test_dashboard_lists_prepped_and_offers_prep_only(tmp_path):
    s, db, _ = make(tmp_path)
    s.raw.pop("_from_example", None)
    _prepped(s, db)
    t = client(s, db).get("/").text
    assert "Prepped: apply by hand" in t and "/job/wd%3Ac%3A3#kit" in t
    assert 'name="mode" value="prep"' in t


def test_leads_page_has_paste_box_and_lead_links(tmp_path):
    s, db, _ = make(tmp_path)
    leads.add_pasted(db, s, {"company": "Hooli", "title": "Data Lead", "description": "d"})
    t = client(s, db).get("/leads").text
    assert "Add a job" in t and 'href="/lead/hooli%7Cdata%20lead"' in t


def test_decline_works_on_a_prepped_row(tmp_path):
    s, db, _ = make(tmp_path)
    _prepped(s, db)
    client(s, db).post("/decline/wd:c:3", data={"reason": "other"})
    assert db.get("wd:c:3")["status"] == "skipped"


def test_prepare_back_stays_on_this_site(tmp_path, monkeypatch):
    s, db, _ = make(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    r = client(s, db).post("/prepare/gh:a:1", data={"back": "/\\evil.com"}, follow_redirects=False)
    assert r.headers["location"] == "/"
