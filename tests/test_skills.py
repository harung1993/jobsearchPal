"""Optional AI skill matching: off by default, synonyms match, tagging is batched, and token use is shown honestly."""
import json


from autoapply import rank, skills
from autoapply.prefs import Prefs
from web_client import client
from test_daily import make


def test_parse_and_match_with_synonyms():
    mine = skills.parse_lines("dbt = data build tool\nPower BI = PowerBI, BI\nSnowflake, Python\n\n- Airflow")
    assert [s["name"] for s in mine] == ["dbt", "Power BI", "Snowflake", "Python", "Airflow"]
    m = skills.match({"must": ["Data Build Tool", "Microsoft Power BI", "Looker"], "nice": ["Python", "Kafka"]}, mine)
    assert (m["met"], m["must"], m["missing"]) == (2, 3, ["Looker"]) and m["nice_met"] == 1
    assert skills.summary(m) == "2 of 3 must-haves · missing Looker"
    assert skills.to_lines(mine).splitlines()[1] == "Power BI = PowerBI, BI"


def test_off_by_default_and_tag_does_nothing(tmp_path, monkeypatch):
    s, db, _ = make(tmp_path)
    pr = Prefs(s.data_dir, s.raw)
    assert not skills.enabled(pr)
    monkeypatch.setattr(skills, "_ask", lambda *a: (_ for _ in ()).throw(AssertionError("no model call when off")))
    assert skills.tag(db, s, pr) == {"skipped": "skill matching is off"}


def test_tag_batches_logs_usage_and_boosts_score(tmp_path, monkeypatch):
    s, db, _ = make(tmp_path)
    pr = Prefs(s.data_dir, s.raw)
    pr.data.update(skills_enabled=True, skills_via="claude")
    pr.save()
    skills.save_mine(s, skills.parse_lines("dbt\nSnowflake\nAirflow"))
    calls = []

    def fake(prompt, prefs):
        calls.append(prompt)
        ids = [l.split("id: ")[1] for l in prompt.splitlines() if l.startswith("### id: ")]
        return json.dumps({i: {"must": ["dbt", "Snowflake"], "nice": ["Looker"]} for i in ids}), \
            {"model": "claude:haiku", "cost": 0.0, "est": 0.01, "tokens": 900}
    monkeypatch.setattr(skills, "_ask", fake)
    r = skills.tag(db, s, pr)
    assert r["tagged"] == 3 and len(calls) == 1  # one call for the batch
    assert tuple(db.conn.execute("select count(*), sum(tokens) from usage where source = 'skills'").fetchone()) == (1, 900)
    job = db.get("gh:b:2")
    assert skills.summary(skills.for_job(job, skills.mine(s))) == "2 of 2 must-haves"
    plain = rank.score(job, s.raw["search"], set())
    assert rank.score(job, s.raw["search"], set(), my_skills=skills.mine(s)) == plain + 5.0  # all must-haves met
    assert skills.tag(db, s, pr)["tagged"] == 0  # already tagged: no new calls
    assert len(calls) == 1


def test_estimate_is_honest_about_claude_overhead(tmp_path):
    s, db, _ = make(tmp_path)
    pr = Prefs(s.data_dir, s.raw)
    pr.data.update(skills_per_day=25, skills_via="openrouter")
    o = skills.estimate(pr)
    pr.data["skills_via"] = "claude"
    c = skills.estimate(pr)
    assert c["tokens_day"] > o["tokens_day"] and c["cash_month"] == 0 and "limits" in c["note"]
    assert o["cash_month"] is not None and o["cash_month"] < 1


def test_settings_page_toggle_and_skills_list(tmp_path):
    s, db, _ = make(tmp_path)
    c = client(s, db)
    html = c.get("/settings?tab=daily").text
    assert "Skill matching" in html and "tokens a day" in html
    c.post("/settings", data={"tab": "daily", "skills_form": "1", "skills_enabled": "1", "skills_via": "openrouter",
                              "skills_per_day": "30", "my_skills": "dbt = data build tool\nLooker"})
    pr = Prefs(s.data_dir, s.raw)
    assert pr.data["skills_enabled"] and pr.data["skills_per_day"] == 30
    assert [x["name"] for x in skills.mine(s)] == ["dbt", "Looker"]
    c.post("/settings", data={"tab": "daily", "skills_form": "1", "skills_per_day": "30"})  # box unticked
    assert not Prefs(s.data_dir, s.raw).data["skills_enabled"]
