"""The application notes render as a document: real headings, lists and tables, safe against HTML in the file."""
from autoapply import notesdoc
from autoapply.config import Settings
from autoapply.db import DB
from web_client import client

NOTES = """# Acme: Senior Analytics Engineer

- Posting: https://jobs.example.com/acme/123?gh_jid=9 (Remote US)
- **Pay ask: $195K base**

## Fit / gap
| They want | You have |
|---|---|
| dbt + Snowflake | 99-model dbt project |
| SaaS domain | **Gap** |

<script>alert(1)</script>
<img src=x onerror=alert(2)>
[bad](javascript:alert(3)) [good](https://acme.example)
"""


def test_render_structure_and_safety():
    h = notesdoc.render(NOTES)
    assert "<h1>Acme: Senior Analytics Engineer</h1>" in h and "<h2>Fit / gap</h2>" in h
    assert '<div class="doc-table"><table>' in h and "<th>They want</th>" in h and "<strong>Gap</strong>" in h
    assert '<a href="https://jobs.example.com/acme/123?gh_jid=9" target="_blank" rel="noopener noreferrer">' in h
    assert '<a href="https://acme.example"' in h
    assert "<script" not in h and "<img" not in h and "javascript:" not in h.replace("[bad](javascript:alert(3))", "")
    assert 'href="javascript' not in h
    assert notesdoc.render("   ") == ""


def test_bare_links_left_alone_inside_code():
    h = notesdoc.render("```\ncurl https://example.com/x\n```")
    assert "<a " not in h and "https://example.com/x" in h


def _setup(tmp_path):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={"first_name": "Alex"})
    db = DB(s.data_dir / "t.db")
    app = s.data_dir / "applications" / "acme"
    app.mkdir(parents=True)
    (app / "r.pdf").write_bytes(b"%PDF-1.4")
    (app / "notes.md").write_text(NOTES)
    db.upsert_job({"id": "greenhouse:acme:1", "ats": "greenhouse", "company": "Acme", "title": "AE", "location": "",
                   "url": "https://acme.example/job", "apply_url": "", "description": ""})
    db.update("greenhouse:acme:1", status="prepped", plan_json={"files": {"resume": str(app / "r.pdf")}, "answers": {}})
    return client(s, db)


def test_job_page_and_notes_page(tmp_path):
    c = _setup(tmp_path)
    html = c.get("/job/greenhouse:acme:1").text
    assert '<article class="notes-doc">' in html and "<th>They want</th>" in html and "Open as a page" in html
    assert "|---|" not in html and "&lt;script&gt;" in html
    page = c.get("/notes/greenhouse:acme:1")
    assert page.status_code == 200
    assert "Print or save as PDF" in page.text and "<h2>Fit / gap</h2>" in page.text
    assert c.get("/notes/greenhouse:nope:2").status_code == 404


def test_notes_page_posting_link_must_be_web(tmp_path):
    c = _setup(tmp_path)
    assert 'href="https://acme.example/job"' in c.get("/notes/greenhouse:acme:1").text
    from autoapply.db import DB
    db = DB(tmp_path / "data" / "t.db")
    db.update("greenhouse:acme:1", url="javascript:alert(1)")
    html = c.get("/notes/greenhouse:acme:1").text
    assert 'href="javascript' not in html and ">posting<" not in html
