"""Skills to learn: what matched roles ask for that you don't show yet."""
import json
from datetime import datetime


from autoapply import learn, skills
from web_client import client
from test_daily import make


def test_found_in_avoids_lookalikes():
    got = learn.found_in("Excellent communicator. Airflow, PySpark, Kubernetes; Go and Python a plus. Scalable systems.")
    assert {"Airflow", "Spark", "Kubernetes", "Python"} <= got
    assert "Excel" not in got and "Go" not in got and "Scala" not in got


def _jobs(db, descs, skills_json=None):
    db.conn.execute("delete from jobs")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for i, d in enumerate(descs):
        db.upsert_job({"id": f"gh:x:{i}", "ats": "greenhouse", "company": f"Co{i}", "title": "Data Engineer", "location": "",
                       "url": "", "apply_url": "", "description": d})
        db.update(f"gh:x:{i}", found_at=now, **({"skills_json": json.dumps(skills_json[i])} if skills_json and skills_json[i] else {}))


def test_keyword_gaps_page_and_marks(tmp_path):
    s, db, cfg = make(tmp_path)
    (tmp_path / "materials" / "context").mkdir(parents=True, exist_ok=True)
    (tmp_path / "materials" / "context" / "me.md").write_text("I work in SQL, Python and dbt.")
    _jobs(db, ["dbt, Snowflake and Airflow.", "Airflow, Databricks, Python.", "Airflow and Kubernetes; SQL.", ""])
    app = tmp_path / "data" / "applications" / "co1"
    app.mkdir(parents=True)
    (app / "notes.md").write_text("| Requirement | Fit | Evidence |\n|---|---|---|\n| Databricks / lakehouse | Gap | none |\n"
                                  "| Healthcare claims domain | Partial | adjacent |\n| Payments domain knowledge | Gap | none |\n| SQL | Good | yes |\n")
    g = learn.gaps(db, s)
    assert g["jobs"] == 3 and g["read_by_ai"] == 0
    names = [i["name"] for i in g["gaps"]]
    assert names[0] == "Airflow" and g["gaps"][0]["count"] == 3 and g["gaps"][0]["pct"] == 100
    assert next(i for i in g["gaps"] if i["name"] == "Databricks")["notes"] == 1
    assert "Healthcare data" in names
    assert {"SQL", "Python", "dbt"} <= {i["name"] for i in g["have"]}
    assert ("payments domain knowledge", 1) in g["other_notes"]
    c = client(s, db)
    assert "Skills to learn" in c.get("/skills").text
    c.post("/skills/mark", data={"skill": "Airflow", "mark": "learning"})
    c.post("/skills/mark", data={"skill": "Kubernetes", "mark": "have"})
    g = learn.gaps(db, s)
    assert [i["name"] for i in g["learning"]] == ["Airflow"] and "Kubernetes" in {i["name"] for i in g["have"]}
    assert [x["name"] for x in skills.mine(s)] == ["Kubernetes"]  # "I have this" goes into your skills list
    c.post("/skills/mark", data={"skill": "Airflow", "mark": "clear"})
    assert learn.gaps(db, s)["gaps"][0]["name"] == "Airflow"


def test_uses_skill_matching_lists_when_present(tmp_path):
    s, db, cfg = make(tmp_path)
    skills.save_mine(s, [{"name": "Power BI", "aka": ["PowerBI"]}])
    _jobs(db, ["Looker and Snowplow.", "We use Looker."],
          [{"must": ["Looker", "PySpark"], "nice": ["Snowplow", "PowerBI"], "covered": []}, None])
    g = learn.gaps(db, s)
    by = {i["name"]: i for i in g["gaps"] + g["have"]}
    assert g["read_by_ai"] == 1
    assert by["Looker / LookML"]["count"] == 2 and by["Looker / LookML"]["required"] == 1  # one model must-have, one keyword
    assert by["Spark"]["required"] == 1 and by["Snowplow"]["area"] == "Other" and by["Snowplow"]["required"] == 0
    assert "Power BI" in {i["name"] for i in g["have"]}  # "PowerBI" from the model, matched to your list
