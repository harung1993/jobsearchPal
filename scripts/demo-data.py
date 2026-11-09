"""Builds a demo folder with fictional data, for screenshots and trying the dashboard:
    python3 scripts/demo-data.py /tmp/demo && cd /tmp/demo && autoapply serve   # http://127.0.0.1:8799
Sign in as demo@example.org with the password "demo password" (demo only).
"""
import sys, json, random
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoapply.db import DB
from autoapply import auth, history
root = Path(sys.argv[1]); (root/"data").mkdir(parents=True, exist_ok=True)
db = DB(root/"data"/"autoapply.db")
auth.save(root/"data", "demo@example.org", "demo password")  # sign-in is always on; a demo account
# Demo data only: fictional companies.
rows = [["Position","Company","Location","Date Applied","Salary","Found on","Applied via","Notes"]]
cos = ["Brightline","Cobalt Labs","Fernwood Health","Gridpoint","Harbor AI","Juniper Data","Kestrel","Lumen Works","Maple Analytics","Nimbus","Orchard","Pinecrest","Quarry","Redwood Metrics","Summit Health","Tidewater"]
plat = ["Greenhouse","Lever","Ashby","Workday","Greenhouse","Ashby"]
random.seed(4)
d0 = datetime(2026,7,20)
for i,c in enumerate(cos*2):
    d = d0 + timedelta(days=int(i*3.4))
    note = random.choice(["","",f"Rejected {(d+timedelta(days=random.randint(5,25))).month}/{(d+timedelta(days=random.randint(5,25))).day}",""])
    rows.append([random.choice(["Senior Analytics Engineer","Staff Data Engineer","Analytics Engineering Manager","Data Platform Lead"]), c+("" if i<16 else " Group"), "Remote", f"{d.month}/{d.day}/2026", "$150K–$190K", "", random.choice(plat), note])
history.import_rows(db, rows)
now = datetime.now()
descs = [  # fictional postings, so the Skills page has something to count
    "Build ELT pipelines with dbt and Snowflake, orchestrated in Airflow. Python and SQL. Looker dashboards for stakeholders.",
    "Own our lakehouse on Databricks (Spark, Delta Lake). Terraform and Kubernetes experience a plus. Mentor junior engineers.",
    "SQL, Python, dbt, BigQuery. Partner with cross-functional teams; experience with A/B testing and Looker.",
    "Data platform on AWS: Kafka streaming, Spark, Airflow, Docker and Kubernetes. Manage a team of 4 engineers.",
    "Analytics engineering with dbt, Snowflake and Tableau. Strong data modeling (Kimball). CI/CD with GitHub Actions.",
    "LLM features: RAG with vector search, Python, AWS. Experience with Databricks or Spark preferred.",
]
for k in range(40):
    jid=f"greenhouse:demo:{k}"
    db.upsert_job({"id":jid,"ats":"greenhouse","company":random.choice(cos),"title":"Analytics Engineer","location":"Remote (US)","url":"https://example.com","apply_url":"https://example.com","description":descs[k % len(descs)]})
    db.update(jid, found_at=(now-timedelta(days=random.randint(0,120))).strftime("%Y-%m-%d %H:%M"))
for k,(c,t,p) in enumerate([("Harbor AI","Senior Analytics Engineer","$170K–$200K"),("Pinecrest","Staff Data Engineer, Platform","$185K–$215K")]):
    jid=f"greenhouse:ready:{k}"
    db.upsert_job({"id":jid,"ats":"greenhouse","company":c,"title":t,"location":"Remote (US)","url":"https://example.com","apply_url":"https://example.com","description":""})
    db.update(jid,status="filled",pay=p,plan_json={"url":"https://example.com"},report_json={"filled":[],"held":[],"unanswered":[],"errors":[]})
for k in range(6):
    db.update(f"greenhouse:demo:{k}", status="skipped", error=random.choice(["onsite only","pay below range","title too junior"]))
ev=[("interview","Jordan Lee <jordan@cobaltlabs.example>","Next steps: schedule time with the hiring manager"),("rejected","Fernwood Health Talent <no-reply@greenhouse.io>","Update on your application"),("confirmed","Harbor AI <no-reply@ashbyhq.com>","Thank you for applying to Harbor AI"),("recruiter","Sam Rivera <sam@talentco.example>","Senior Analytics Engineer, remote, fintech client"),("recruiter","Priya Nair <priya@recruitpartners.example>","Data platform lead role"),("recruiter","Alex Kim <alex@staffingone.example>","Contract-to-hire analytics engineer")]
for i,(k,s,sub) in enumerate(ev):
    db.add_event({"id":f"e{i}","job_id":None,"kind":k,"at":(now-timedelta(days=i*2)).strftime("%Y-%m-%d %H:%M"),"sender":s,"subject":sub})
from autoapply import leads
demo_leads=[("Senior Analytics Engineer","Quarry Labs","Remote","$165K–$190K","Linkedin"),("Staff Analytics Engineer","Tidewater Bank","Boston, MA","","Linkedin"),
            ("Analytics Engineering Manager","Lumen Works","Remote","$180K–$210K","Indeed"),("Senior Data Engineer","Orchard Health","Cambridge, MA (Hybrid)","$150K–$175K","Indeed"),
            ("Lead Data Scientist","Summit Robotics","Waltham, MA","","Linkedin"),("Head of Data","Kestrel Finance","Remote","$200K–$240K","Built In"),
            ("Data Platform Engineer","Nimbus Retail","New York, NY","","Glassdoor"),("Senior BI Developer","Maple Insurance","Remote","$130K–$150K","Indeed")]
for i,(t,c,l,sal,src) in enumerate(demo_leads):
    leads.save(db,[{"title":t,"company":c,"location":l,"salary":sal,"url":"https://example.com"}],src,now-timedelta(days=i%4),{"title_keywords":["analytics engineer","data engineer","head of data"]},set())
leads.set_status(db,leads.key("Lumen Works","Analytics Engineering Manager"),"starred")
leads.set_status(db,leads.key("Maple Insurance","Senior BI Developer"),"dismissed")
for kind in ["daily","find","sync-email","brief"]:
    db.log_run(kind, True, "demo")
# A set-up demo user, so screenshots show the app in use rather than the first-run Setup prompts.
import yaml
start=(now-timedelta(weeks=7)).date()
(root/"config.yaml").write_text(yaml.safe_dump({"data_dir":"./data","review":{"host":"127.0.0.1","port":8799},
 "search":{"title_keywords":["analytics engineer","data engineer","head of data"],"exclude_keywords":["intern","junior"],"us_only":True},
 "boards":[{"ats":"greenhouse","slug":s} for s in ("harborai","pinecrest","cobaltlabs","gridpoint","juniperdata")]+[{"ats":"ashby","slug":s} for s in ("kestrel","nimbus","orchard")],
 "feeds":["remoteok","remotive","hn_whos_hiring","themuse","himalayas"],
 "work_search":{"label":"Work search","weekly_minimum":3,"state":"MA","claim_start":start.isoformat(),"weekly_benefit":"812","weeks_allowed":"26","certify_day":"Sunday"}},sort_keys=False))
prof=yaml.safe_load((Path(__file__).resolve().parents[1] / "profile.example.yaml").read_text())
prof.update({"first_name":"Alex","last_name":"Morgan","email":"alex.morgan@example.org"})
(root/"profile.yaml").write_text(yaml.safe_dump(prof,sort_keys=False))
(root/"materials").mkdir(exist_ok=True); (root/"materials"/"Morgan Resume - Base.docx").write_bytes(b"")
(root/"data"/"sources.json").write_text(json.dumps({"at":now.strftime("%Y-%m-%d %H:%M"),"sources":{
 "remoteok":{"fetched":96,"matched":4,"new":2,"error":""},"remotive":{"fetched":14,"matched":1,"new":0,"error":""},
 "hn_whos_hiring":{"fetched":212,"matched":6,"new":3,"error":""},"themuse":{"fetched":118,"matched":3,"new":1,"error":""},
 "himalayas":{"fetched":100,"matched":2,"new":1,"error":""}}}))
from autoapply import benefits
benefits.add_resea(db, "MA")
for n,(tid,) in enumerate(db.conn.execute("select id from ui_tasks where kind = 'resea' order by id").fetchall()):
    db.conn.execute("update ui_tasks set due = ?, done = ? where id = ?", ((now+timedelta(days=[-3,6,20][min(n,2)])).date().isoformat(), int(n == 0), tid))
db.conn.commit()
benefits.add_task(db, "Upload ID to the claim portal", (now+timedelta(days=9)).date().isoformat())

(root/"materials"/"context").mkdir(parents=True, exist_ok=True)
(root/"materials"/"context"/"about.md").write_text("Analytics engineer: SQL, Python, dbt, Snowflake, Tableau, Airflow. Data modeling and stakeholder work.\n")
