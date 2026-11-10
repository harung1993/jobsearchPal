"""Skills to learn: what the roles you matched keep asking for that you don't show yet.

Two ways to know what a role asks for:
- when Skill matching is on (Settings > Daily run), the model's must-have and nice-to-have list for that role
  (jobs.skills_json, written by skills.tag); nothing is read twice;
- otherwise, plain keyword matching against a fixed list of about 90 skills (SKILLS below), at no cost.
What you have: your skills list from Skill matching (data/skills.json) when you have one, plus the same keyword
list run over your base resume, CLAUDE.local.md and materials/context. The tailoring notes' fit/gap tables
(data/applications/*/notes.md) add the requirements judged missing on roles you applied to.

"Learning" and "Hide" marks live in data/learning.json; "I have this" adds the skill to your skills list.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

# (name, pattern, area, where to learn). Patterns are matched case-insensitively on word edges.
# Links are each project's own docs or free course pages; nothing here is paid or affiliate.
SKILLS: list[tuple[str, str, str, str]] = [
    # Languages
    ("Python", r"python", "Languages", "https://docs.python.org/3/tutorial/"),
    ("SQL", r"sql(?! server)", "Languages", ""),
    ("R", r"\bR\b(?=\s*(?:,|/|programming|language))|rstudio", "Languages", "https://www.r-project.org/"),
    ("Java", r"java(?!script)", "Languages", "https://dev.java/learn/"),
    ("Scala", r"scala\b", "Languages", "https://docs.scala-lang.org/"),
    ("Go", r"golang|\bgo\b(?=\s*(?:/|programming|language))", "Languages", "https://go.dev/tour/"),
    ("JavaScript", r"javascript|node\.?js", "Languages", "https://developer.mozilla.org/en-US/docs/Learn"),
    ("TypeScript", r"typescript", "Languages", "https://www.typescriptlang.org/docs/"),
    ("C#", r"c#|\.net\b", "Languages", "https://learn.microsoft.com/dotnet/csharp/"),
    ("C++", r"c\+\+", "Languages", ""),
    ("Rust", r"\brust\b", "Languages", "https://doc.rust-lang.org/book/"),
    ("Bash / shell", r"bash|shell scripting", "Languages", ""),
    # Data engineering
    ("Airflow", r"airflow", "Data engineering", "https://airflow.apache.org/docs/"),
    ("Dagster", r"dagster", "Data engineering", "https://docs.dagster.io/"),
    ("Prefect", r"prefect\b", "Data engineering", "https://docs.prefect.io/"),
    ("dbt", r"\bdbt\b", "Data engineering", "https://courses.getdbt.com/"),
    ("Spark", r"spark|pyspark", "Data engineering", "https://spark.apache.org/docs/latest/"),
    ("Databricks", r"databricks", "Data engineering", "https://www.databricks.com/learn/training"),
    ("Kafka / streaming", r"kafka|kinesis|pub/?sub|stream processing|streaming data|flink", "Data engineering", "https://kafka.apache.org/documentation/"),
    ("CDC", r"change data capture|\bcdc\b|debezium", "Data engineering", "https://debezium.io/documentation/"),
    ("Fivetran / Airbyte", r"fivetran|airbyte|stitch data", "Data engineering", "https://docs.airbyte.com/"),
    ("Iceberg / Delta / lakehouse", r"iceberg|delta lake|lakehouse|hudi", "Data engineering", "https://iceberg.apache.org/docs/latest/"),
    ("Data modeling", r"data model(?:ing|ling)|dimensional model|star schema|kimball|data vault", "Data engineering", ""),
    ("Data quality", r"data quality|great expectations|monte carlo|data observability|soda\b", "Data engineering", ""),
    ("ETL / ELT", r"\betl\b|\belt\b|data pipelines?", "Data engineering", ""),
    # Warehouses and databases
    ("Snowflake", r"snowflake", "Warehouses and databases", "https://learn.snowflake.com/"),
    ("BigQuery", r"bigquery", "Warehouses and databases", "https://cloud.google.com/bigquery/docs"),
    ("Redshift", r"redshift", "Warehouses and databases", "https://docs.aws.amazon.com/redshift/"),
    ("PostgreSQL", r"postgres(?:ql)?", "Warehouses and databases", "https://www.postgresql.org/docs/"),
    ("MySQL", r"mysql", "Warehouses and databases", "https://dev.mysql.com/doc/"),
    ("SQL Server", r"sql server|t-sql|tsql|ssis", "Warehouses and databases", "https://learn.microsoft.com/sql/"),
    ("Oracle", r"oracle", "Warehouses and databases", ""),
    ("MongoDB / NoSQL", r"mongodb|nosql|dynamodb|cassandra", "Warehouses and databases", "https://learn.mongodb.com/"),
    ("Microsoft Fabric / Synapse", r"microsoft fabric|\bfabric\b(?= ?(?:,|/|and|or|lakehouse|warehouse))|synapse", "Warehouses and databases", "https://learn.microsoft.com/fabric/"),
    # BI and analytics
    ("Tableau", r"tableau", "BI and analytics", "https://www.tableau.com/learn/training"),
    ("Power BI", r"power ?bi|\bdax\b", "BI and analytics", "https://learn.microsoft.com/power-bi/"),
    ("Looker / LookML", r"looker|lookml", "BI and analytics", "https://cloud.google.com/looker/docs"),
    ("Semantic layer / metrics", r"semantic layer|metrics layer|cube\.dev|metricflow", "BI and analytics", ""),
    ("Excel", r"excel\b|spreadsheets?", "BI and analytics", ""),
    ("A/B testing / experimentation", r"a/b test|experimentation|experiment design|causal inference", "BI and analytics", ""),
    ("Statistics", r"statistic(?:s|al)|regression|hypothesis test", "BI and analytics", ""),
    ("Product analytics", r"amplitude|mixpanel|product analytics|segment\.com|heap analytics", "BI and analytics", ""),
    # ML and AI
    ("Machine learning", r"machine learning|\bml\b|scikit|sklearn|xgboost", "ML and AI", "https://scikit-learn.org/stable/getting_started.html"),
    ("Deep learning", r"deep learning|pytorch|tensorflow|keras", "ML and AI", "https://pytorch.org/tutorials/"),
    ("LLMs / generative AI", r"\bllms?\b|large language model|generative ai|genai|gpt|prompt engineering", "ML and AI", ""),
    ("RAG / vector search", r"\brag\b|retrieval.augmented|vector (?:db|database|search|store)|embeddings?|pinecone|pgvector", "ML and AI", ""),
    ("AI agents", r"ai agents?|agentic|langchain|langgraph|\bmcp\b|multi.agent", "ML and AI", ""),
    ("MLOps", r"mlops|mlflow|model deployment|feature store|sagemaker|vertex ai", "ML and AI", "https://mlflow.org/docs/latest/"),
    ("NLP", r"\bnlp\b|natural language processing", "ML and AI", ""),
    ("Computer vision", r"computer vision|image recognition|opencv", "ML and AI", ""),
    # Cloud and infrastructure
    ("AWS", r"\baws\b|amazon web services|\bs3\b|lambda\b|glue\b", "Cloud and infrastructure", "https://aws.amazon.com/training/"),
    ("Azure", r"azure", "Cloud and infrastructure", "https://learn.microsoft.com/training/azure/"),
    ("Google Cloud", r"\bgcp\b|google cloud", "Cloud and infrastructure", "https://cloud.google.com/learn/training"),
    ("Docker", r"docker|containers?\b", "Cloud and infrastructure", "https://docs.docker.com/get-started/"),
    ("Kubernetes", r"kubernetes|\bk8s\b|helm\b|\beks\b|\bgke\b|\baks\b", "Cloud and infrastructure", "https://kubernetes.io/docs/tutorials/"),
    ("Terraform / IaC", r"terraform|infrastructure as code|\biac\b|cloudformation|pulumi", "Cloud and infrastructure", "https://developer.hashicorp.com/terraform/tutorials"),
    ("CI/CD", r"ci/cd|ci ?cd|continuous integration|github actions|jenkins|gitlab ci", "Cloud and infrastructure", ""),
    ("Git", r"\bgit\b|github|gitlab|version control", "Cloud and infrastructure", "https://git-scm.com/book/en/v2"),
    ("Linux", r"linux|unix", "Cloud and infrastructure", ""),
    ("Observability", r"observability|datadog|prometheus|grafana|splunk|new relic", "Cloud and infrastructure", ""),
    ("Security / compliance", r"soc ?2|hipaa|gdpr|pci|iam\b|security best practices|data governance|ferpa", "Cloud and infrastructure", ""),
    # Software engineering
    ("REST APIs", r"rest(?:ful)? apis?|\bapis?\b(?= ?(?:,|/|and|or|design|development|integration))|graphql", "Software engineering", ""),
    ("Microservices", r"microservices?|distributed systems", "Software engineering", ""),
    ("React", r"react(?:\.js)?\b", "Software engineering", "https://react.dev/learn"),
    ("Testing", r"unit test|test automation|pytest|integration tests?|tdd\b", "Software engineering", ""),
    ("System design", r"system design|architecture design|scalab(?:le|ility)", "Software engineering", ""),
    # Business tools and domains
    ("Salesforce", r"salesforce", "Business tools and domains", "https://trailhead.salesforce.com/"),
    ("HubSpot", r"hubspot", "Business tools and domains", "https://academy.hubspot.com/"),
    ("Jira / Agile", r"\bjira\b|agile|scrum|kanban|sprint", "Business tools and domains", ""),
    ("SAP / ERP", r"\bsap\b|\berp\b|netsuite|workday financials", "Business tools and domains", ""),
    ("Google Analytics / SEO", r"google analytics|\bga4\b|\bseo\b|\bsem\b", "Business tools and domains", "https://skillshop.withgoogle.com/"),
    ("Figma / design", r"figma|sketch\b|user research|ux design|wireframes?", "Business tools and domains", "https://help.figma.com/"),
    ("Finance / accounting", r"financial (?:reporting|modeling|planning)|fp&a|gaap|revenue recognition|reconciliation|accounting", "Business tools and domains", ""),
    ("Healthcare data", r"healthcare|claims data|\bphi\b|\behr\b|\bemr\b|hl7|fhir|epic\b", "Business tools and domains", ""),
    ("Marketing analytics", r"marketing analytics|attribution|marketing mix|customer acquisition|ltv\b", "Business tools and domains", ""),
    # Ways of working
    ("People management", r"people manag|manag(?:e|ing) (?:a )?team|direct reports|hiring and (?:developing|growing)|mentor(?:ing|ship)?|coach(?:ing)?\b", "Ways of working", ""),
    ("Stakeholder management", r"stakeholder|cross.functional|business partners", "Ways of working", ""),
    ("Project management", r"project manag|program manag|roadmap|pmp\b", "Ways of working", ""),
    ("Communication / presenting", r"communicat(?:e|ion) (?:complex|technical|findings|insights)|presentation skills|data storytelling|executive presentations?", "Ways of working", ""),
    ("Consulting / client-facing", r"client.facing|consulting|pre.sales|customer.facing", "Ways of working", ""),
]
_COMPILED = [(n, re.compile(rf"(?<![a-z0-9]){p}", re.I), area, url) for n, p, area, url in SKILLS]
AREAS = list(dict.fromkeys(a for _, _, a, _ in SKILLS))


def found_in(text: str) -> set[str]:
    """Skill names mentioned in a piece of text."""
    t = text or ""
    return {n for n, rx, _, _ in _COMPILED if rx.search(t)}


# Scanning one description takes ~27 ms (80 patterns), so the Skills page took 13 s for ~470 roles (11/10).
# A role's text never changes: each one is scanned once and the result kept, keyed by a hash of the patterns and
# the text, so editing SKILLS or a description rescans just what changed.
_PATTERNS_KEY = hashlib.sha1("\n".join(p for _, p, _, _ in SKILLS).encode()).hexdigest()[:10]
HITS_SCHEMA = "create table if not exists skill_hits (job_id text primary key, h text, names text)"


def found_in_jobs(db, jobs: list[dict]) -> dict[str, set[str]]:
    """found_in(description) for each job, from the skill_hits cache where it's current."""
    db.conn.execute(HITS_SCHEMA)
    have = {r[0]: (r[1], r[2]) for r in db.conn.execute("select job_id, h, names from skill_hits")}
    out, fresh = {}, []
    for j in jobs:
        text = j.get("description") or ""
        h = hashlib.sha1((_PATTERNS_KEY + text).encode()).hexdigest()[:16]
        hit = have.get(j["id"])
        if hit and hit[0] == h:
            out[j["id"]] = set(json.loads(hit[1]))
        else:
            out[j["id"]] = found_in(text)
            fresh.append((j["id"], h, json.dumps(sorted(out[j["id"]]))))
    if fresh:
        db.conn.executemany("insert or replace into skill_hits (job_id, h, names) values (?, ?, ?)", fresh)
        db.conn.commit()
    return out


def _marks_path(data_dir: Path) -> Path:
    return Path(data_dir) / "learning.json"


def marks(data_dir: Path) -> dict:
    """{"learning": [...], "hidden": [...]} from data/learning.json."""
    try:
        m = json.loads(_marks_path(data_dir).read_text())
    except (OSError, ValueError):
        m = {}
    return {k: [s for s in m.get(k, []) if isinstance(s, str)] for k in ("learning", "hidden")}


def set_mark(settings, skill: str, mark: str):
    """mark: have (adds it to your skills list), learning, hidden, or clear."""
    from . import skills as sk
    skill = re.sub(r"\s+", " ", str(skill or "")).strip()[:60]
    if not skill:
        return
    m = marks(settings.data_dir)
    for k in m:
        m[k] = [s for s in m[k] if s.lower() != skill.lower()]
    if mark in m:
        m[mark].append(skill)
    if mark == "have":
        mine = sk.mine(settings)
        if not any(s.get("name", "").lower() == skill.lower() for s in mine):
            sk.save_mine(settings, mine + [{"name": skill, "aka": []}])
    p = _marks_path(settings.data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=1))


def canonical(name: str) -> str:
    """A model's skill name mapped onto the list above when it's one of them ("PySpark" -> "Spark")."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()[:60]
    hit = found_in(n)
    return next(iter(hit)) if len(hit) == 1 else n


def about_you(root: Path) -> str:
    """Everything you've written about yourself: the base resume, CLAUDE.local.md and materials/context."""
    from .setup import base_resume
    texts = []
    r = base_resume(root)
    if r:
        try:
            from docx import Document
            d = Document(str(r))
            texts.append("\n".join(p.text for p in d.paragraphs))
            texts += [c.text for t in d.tables for row in t.rows for c in row.cells]
        except Exception:
            pass
    for p in [root / "CLAUDE.local.md", *sorted((root / "materials" / "context").glob("*.md"))]:
        try:
            texts.append(p.read_text())
        except OSError:
            pass
    return "\n".join(texts)


GAP_ROW = re.compile(r"^\|\s*([^|]{3,160}?)\s*\|\s*\**(gap|partial|missing|no)\**\b", re.I | re.M)


def notes_gaps(data_dir: Path) -> list[tuple[str, str]]:
    """(application folder, requirement) for each Gap/Partial row in the tailoring notes' fit/gap tables."""
    out = []
    for f in sorted((Path(data_dir) / "applications").glob("*/notes.md")):
        try:
            text = f.read_text()
        except OSError:
            continue
        out += [(f.parent.name, m.group(1).strip("* ")) for m in GAP_ROW.finditer(text)]
    return out




def gaps(db, settings, days: int = 90, now: datetime | None = None) -> dict:
    """What the matched roles ask for, split into what you show and what you don't."""
    from . import skills as sk
    now = now or datetime.now()
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.conn.execute(
        "select id, company, title, description, status, skills_json from jobs where found_at >= ?"
        " and (coalesce(description, '') != '' or skills_json is not null)"
        " and not (status = 'skipped' and coalesce(error, '') like 'Declined%')", (since,)).fetchall()
    jobs = [dict(zip(("id", "company", "title", "description", "status", "skills_json"), r)) for r in rows]
    m = marks(settings.data_dir)
    mine_list = sk.mine(settings)
    forms = sk._forms(mine_list) if mine_list else {}
    text = about_you(settings.root)
    text_l = text.lower()
    from_text = found_in(text)

    def have(name: str) -> bool:
        if name in from_text or (forms and sk._has(name, forms)):
            return True
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", text_l))

    tally: dict[str, dict] = {}
    read = 0
    scanned = found_in_jobs(db, [j for j in jobs if not j["skills_json"]])
    for j in jobs:
        asked: dict[str, bool | None] = {}
        try:
            js = json.loads(j["skills_json"] or "null")
        except ValueError:
            js = None
        if js and (js.get("must") or js.get("nice")):
            read += 1
            for s in js.get("nice") or []:
                asked.setdefault(canonical(s), False)
            for s in js.get("must") or []:
                asked[canonical(s)] = True
        else:
            asked = {n: None for n in scanned.get(j["id"]) or found_in(j["description"] or "")}  # None: can't tell must from nice
        for name, must in asked.items():
            if not name:
                continue
            t = tally.setdefault(name, {"count": 0, "required": 0, "examples": [], "applied": 0})
            t["count"] += 1
            t["required"] += 1 if must else 0
            if j["status"] in ("filled", "submitted"):
                t["applied"] += 1
            if len(t["examples"]) < 4:
                t["examples"].append({"id": j["id"], "label": f"{j['company']} · {j['title']}"})
    from_notes: dict[str, set] = {}
    other_notes: dict[str, set] = {}
    for app, req in notes_gaps(settings.data_dir):
        named = found_in(req)
        for n in named:
            from_notes.setdefault(n, set()).add(app)
        if not named:
            other_notes.setdefault(re.sub(r"\s+", " ", req.lower())[:90], set()).add(app)
    meta = {n: (area, url) for n, _, area, url in SKILLS}
    total = len(jobs) or 1
    learning = {s.lower() for s in m["learning"]}
    hidden = {s.lower() for s in m["hidden"]}
    items = []
    for name in set(tally) | set(from_notes):
        t = tally.get(name, {"count": 0, "required": 0, "examples": [], "applied": 0})
        area, url = meta.get(name, ("Other", ""))
        state = ("learning" if name.lower() in learning else "hidden" if name.lower() in hidden
                 else "have" if have(name) else "gap")
        items.append({"name": name, "area": area, "url": url, "count": t["count"], "pct": round(100 * t["count"] / total),
                      "required": t["required"], "applied": t["applied"], "examples": t["examples"],
                      "notes": len(from_notes.get(name, ())), "state": state})
    # A must-have counts a little more than a mention; a gap on a role you applied to counts double.
    items.sort(key=lambda i: (-(i["count"] + 0.5 * i["required"] + 2 * i["notes"]), -i["count"], i["name"]))
    return {
        "jobs": len(jobs), "days": days, "read_by_ai": read, "has_list": bool(mine_list),
        "gaps": [i for i in items if i["state"] == "gap"],
        "learning": [i for i in items if i["state"] == "learning"],
        "have": [i for i in items if i["state"] == "have"],
        "hidden": [i for i in items if i["state"] == "hidden"],
        "other_notes": sorted(((k, len(v)) for k, v in other_notes.items()), key=lambda kv: -kv[1])[:12],
    }
