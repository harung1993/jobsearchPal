"""Part of palStack on every surface, application milestones once each, and red kept for what is urgent."""
from datetime import date, datetime, timedelta

from autoapply import benefits, brief, pal, stats
from autoapply.config import Settings
from autoapply.db import DB
from web_client import client


def _app(tmp_path, db=None):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={"first_name": "Alex"})
    db = db or DB(s.data_dir / "t.db")
    return s, db, client(s, db)


def _sent(db, n, last_on: date, first_on: date | None = None):
    for i in range(n):
        jid = f"gh:co{i}:{i}"
        db.upsert_job({"id": jid, "ats": "greenhouse", "company": f"Co {i}", "title": "Analytics Engineer", "location": "",
                       "url": "", "apply_url": "", "description": ""})
        when = last_on if i == n - 1 else (first_on or last_on - timedelta(days=30))
        db.update(jid, status="submitted", submitted_at=f"{when.isoformat()} 09:00")


def test_first_application_is_a_moment_once(tmp_path):
    db, today = DB(tmp_path / "t.db"), date(2026, 11, 10)
    assert pal.milestone(db, stats.compute(db, today), today) is None
    _sent(db, 1, today - timedelta(days=1))
    m = pal.milestone(db, stats.compute(db, today), today)
    assert m["key"] == "celebrate:milestone:1" and m["title"] == "Your first application is out"
    db.set_nudge(m["key"], "done")
    assert pal.milestone(db, stats.compute(db, today), today) is None


def test_milestones_count_up_and_skip_old_ones(tmp_path):
    db, today = DB(tmp_path / "t.db"), date(2026, 11, 10)
    _sent(db, 25, today - timedelta(days=60))  # all long ago: a first deploy on a long search says nothing
    assert pal.milestone(db, stats.compute(db, today), today) is None
    _sent(db, 26, today)  # one more today doesn't land on a milestone either
    assert pal.milestone(db, stats.compute(db, today), today) is None
    db2 = DB(tmp_path / "t2.db")
    _sent(db2, 25, today - timedelta(days=2))
    m = pal.milestone(db2, stats.compute(db2, today), today)
    assert m["title"] == "25 applications sent" and "25 doors" in m["line"]
    for word in ("streak", "!", "keep it up", "goal"):
        assert word not in (m["title"] + m["line"]).lower()


def test_dashboard_plays_a_milestone_once(tmp_path):
    s, db, c = _app(tmp_path)
    _sent(db, 1, date.today())
    assert "Your first application is out" in c.get("/").text
    assert "Your first application is out" not in c.get("/").text


def test_part_of_palstack_everywhere(tmp_path):
    s, db, c = _app(tmp_path)
    for path in ("/", "/stats", "/settings", "/setup"):
        html = c.get(path).text
        # palStack.io: small p, capital S (Harun, 2026-11-09); the link is the lower-case domain.
        assert 'href="https://palstack.io"' in html and "<small>Part of</small><b>palStack.io</b>" in html, path
        assert "palstack.io</b>" not in html and "Part of <b>palStack</b>" not in html, path
    assert "a family of privacy-first tools" in c.get("/settings").text
    assert 'class="ps-foot"' in c.get("/setup").text and 'class="card mt about-ps"' not in c.get("/setup").text
    c.post("/logout")
    login = c.get("/login").text
    assert "<b>palStack.io</b>" in login and 'class="hz' in login


def test_brief_footer_and_subject(tmp_path):
    db = DB(tmp_path / "t.db")
    subject, text, html = brief.compose(db, today=date(2026, 11, 10))
    assert subject.startswith("Job search brief")
    assert text.rstrip().endswith(brief.FOOTER_TEXT) and "https://palstack.io" in html


def test_benefit_dates_are_amber_until_they_are_close(tmp_path):
    s, db, c = _app(tmp_path)
    today = datetime.now().date()
    benefits.add_task(db, "Upload ID to the claim portal", (today + timedelta(days=9)).isoformat())
    benefits.add_task(db, "RESEA review", (today + timedelta(days=1)).isoformat(), kind="resea")
    html = c.get("/").text
    i, j = html.index("Upload ID to the claim portal"), html.index("RESEA review")
    assert 'pill deadline' in html[i - 600:i] and 'pill rejected' in html[j - 600:j]


def test_warm_tokens_and_reduced_motion_still_hold(tmp_path):
    s, db, c = _app(tmp_path)
    html = c.get("/").text
    assert "--bg:#f6f2ea" in html and "--bg:#f1f4f2" not in html
    assert "prefers-reduced-motion:reduce" in html and " forwards" not in html


def test_setup_lists_finished_steps_in_one_checklist(tmp_path):
    """Finished steps are rows (what you saved, Edit), their forms folded until opened; letters is a row too."""
    s, db, c = _app(tmp_path)
    html = c.get("/setup").text
    assert 'class="card mt checklist"' in html and "Your setup" in html
    assert 'href="/letters">Open</a>' in html and 'id="letters"' not in html
    assert 'id="resume"' in html  # the form is still on the page, opened in place from Edit
