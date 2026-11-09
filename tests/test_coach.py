"""What helps a search: the weekly plan, people you know, related titles, setback preparation, the values
reflection, a gentle return, and fit-first ranking."""
from datetime import date, datetime, timedelta

import pytest

from autoapply import coach, pal, stats
from autoapply.config import Settings
from autoapply.db import DB

TODAY = date(2026, 11, 10)  # a Tuesday


@pytest.fixture
def db(tmp_path):
    return DB(tmp_path / "t.db")


def _settings(tmp_path, titles=("analytics engineer",), avoid=()):
    return Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data"),
                                        "search": {"title_keywords": list(titles), "exclude_keywords": list(avoid)}},
                    profile={"first_name": "Alex"})


def _job(db, i, title, company="acme", sent=None, outcome=None):
    db.upsert_job({"id": f"gh:{company}:{i}", "ats": "greenhouse", "company": company, "title": title, "location": "",
                   "url": "u", "apply_url": "u", "description": ""})
    if sent:
        db.update(f"gh:{company}:{i}", status="submitted", submitted_at=sent, outcome=outcome)


# ---- the plan --------------------------------------------------------------------------------------

def test_plan_is_kept_in_the_persons_words_and_empty_removes_it(db):
    wk = stats.week_start(TODAY)
    p = coach.save_plan(db, wk, "  analytics   roles ", ["Wed", "Mon", "Funday"], "Sam")
    assert p == {"roles": "analytics roles", "days": ["Mon", "Wed"], "contact": "Sam"}
    assert coach.plan_line(coach.plan(db, wk)) == "analytics roles · Mon, Wed · get in touch with Sam"
    assert coach.weeks_planned(db) == 1
    assert coach.save_plan(db, wk, "", [], "") is None and coach.plan(db, wk) is None


def test_brief_carries_the_plan_only_when_written(tmp_path, db):
    from autoapply import brief
    _, text, _ = brief.compose(db, today=TODAY)
    assert "Your plan this week" not in text
    coach.save_plan(db, stats.week_start(TODAY), "data roles", ["Mon"], "")
    subject, text, html = brief.compose(db, today=TODAY)
    assert "Your plan this week: data roles · Mon" in text and "data roles" in html
    assert subject.startswith("Job search brief")


# ---- people you know -------------------------------------------------------------------------------

def test_contacts_go_in_the_log_and_the_switch_is_honest(db):
    coach.add_contact(db, "Sam Rivera", "Globex", "Coffee or video chat", "asked about the team", TODAY.isoformat())
    assert coach.add_contact(db, "   ", "x") is None  # a name is needed
    wk = next(w for w in stats.dua_weeks(db, TODAY) if w["current"])
    row = next(r for r in wk["rows"] if r["type"] == "Networking contact")
    assert row["contact"] == "Sam Rivera" and row["company"] == "Globex"
    assert not row["counts"] and wk["count"] == 0  # listed, not counted until the person says their state accepts it
    coach.set_note(db, "ws:count_contacts", True)
    wk = next(w for w in stats.dua_weeks(db, TODAY) if w["current"])
    assert wk["count"] == 1


def test_interviews_at_companies_where_you_know_someone(db):
    _job(db, 1, "Analyst", "globex", sent="2026-10-01 09:00", outcome="interview")
    _job(db, 2, "Analyst", "initech", sent="2026-10-01 09:00", outcome="interview")
    coach.add_contact(db, "Sam", "Globex")
    assert coach.interviews_from_contacts(db) == 1


# ---- related titles --------------------------------------------------------------------------------

def test_related_titles_share_a_word_seen_twice_and_skip_avoided(tmp_path, db):
    s = _settings(tmp_path, titles=("analytics engineer",), avoid=("manager",))
    for i, t in enumerate(["Senior Data Engineer - Remote", "Data Engineer", "Analytics Engineer II", "Analytics Manager",
                           "Analytics Manager", "Product Designer", "Product Designer", "BI Analytics Lead",
                           "Analytics Developer (Contract)", "Analytics Developer"]):
        _job(db, i, t, company=f"co{i}")
    got = [r["title"] for r in coach.related_titles(db, s)]
    assert got == ["analytics developer", "data engineer"]  # already searched, avoided, unrelated and one-offs left out


def test_titles_are_offered_on_the_dashboard_only_for_a_long_narrow_search(tmp_path, db):
    s = _settings(tmp_path)
    for i in range(2):
        _job(db, 10 + i, "Analytics Developer", company=f"x{i}")
    _job(db, 1, "Analytics Engineer", sent=(TODAY - timedelta(days=30)).isoformat() + " 09:00")
    coach.set_note(db, "last_action", TODAY.isoformat())
    for k in ("pal:setback:early", "pal:setback:later", "pal:values:early"):
        db.set_nudge(k, "done")
    sc = stats.compute(db, TODAY)
    assert coach.offer(db, s, sc, TODAY, False) is None  # 4 weeks: not long yet
    db.update("gh:acme:1", submitted_at=(TODAY - timedelta(weeks=9)).isoformat() + " 09:00")
    o = coach.offer(db, s, stats.compute(db, TODAY), TODAY, False)
    assert o["kind"] == "titles" and o["titles"][0]["title"] == "analytics developer"


def test_adding_a_title_writes_the_search(tmp_path, db):
    from autoapply import setup
    s = _settings(tmp_path)
    assert setup.add_title(s, "Analytics Developer") and not setup.add_title(s, "analytics developer")
    assert "analytics developer" in (tmp_path / "config.yaml").read_text()
    assert s.raw["search"]["title_keywords"] == ["analytics engineer", "analytics developer"] and s.data_dir == tmp_path / "data"


# ---- setbacks and the reflection -------------------------------------------------------------------

def test_setback_card_early_then_around_week_eight(tmp_path, db):
    s = _settings(tmp_path)
    assert coach.setback_phase(stats.compute(db, TODAY), TODAY) is None  # nothing sent yet
    _job(db, 1, "Analytics Engineer", sent=(TODAY - timedelta(days=5)).isoformat() + " 09:00")
    sc = stats.compute(db, TODAY)
    o = coach.offer(db, s, sc, TODAY, has_interview=True)
    assert o["kind"] == "setback" and o["phase"] == "early"  # first, even with an interview waiting
    db.set_nudge(o["key"], "done")
    assert coach.offer(db, s, sc, TODAY, has_interview=True)["key"] == "pal:values:interview"
    later = TODAY + timedelta(days=55)
    assert coach.setback_phase(stats.compute(db, later), later) == "later"
    assert coach.setback_phase(stats.compute(db, TODAY + timedelta(days=30)), TODAY + timedelta(days=30)) is None


def test_reflection_keeps_at_most_three_known_values(db):
    assert not coach.save_reflection(db, [], "  ")
    assert coach.save_reflection(db, ["Family", "Craft and doing good work", "Learning", "Honesty", "made up"], "Because.")
    r = coach.reflections(db)[0]["value"]
    assert r["values"] == ["Family", "Learning", "Craft and doing good work"] and r["text"] == "Because."


# ---- a gentle return -------------------------------------------------------------------------------

def test_back_after_a_week_away_then_normal_once_you_act(db):
    _job(db, 1, "Analytics Engineer", sent="2026-10-20 09:00")
    now = datetime(2026, 11, 10, 9, 0)
    g = pal.greeting(db, stats.compute(db, now.date()), now, "Alex")
    assert g["state"] == "back" and g["title"] == "Morning, Alex. Welcome back."
    assert "catch-up" in g["line"] or "one thing" in g["line"]
    coach.set_note(db, "last_action", "2026-11-09 18:00")
    assert pal.greeting(db, stats.compute(db, now.date()), now, "Alex")["state"] == "quiet"


def test_a_new_install_is_never_away(db):
    assert coach.away_days(db, stats.compute(db, TODAY), TODAY) == 0


# ---- fit first -------------------------------------------------------------------------------------

def test_ranking_is_on_fit_never_the_weekly_number():
    from pathlib import Path
    from autoapply import rank
    assert "never a weekly quota" in rank.QUICK_PROMPT
    assert "never the weekly work-search number" in (Path(rank.__file__).parent.parent / "prompts" / "stages" / "rank.md").read_text()


# ---- the pages -------------------------------------------------------------------------------------

def _app(tmp_path, db, **raw):
    from web_client import client
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data"), **raw}, profile={"first_name": "Alex"})
    return client(s, db)


def test_dashboard_plan_people_and_reflection_flow(tmp_path, db):
    _job(db, 1, "Analytics Engineer", sent=datetime.now().strftime("%Y-%m-%d %H:%M"))
    _job(db, 2, "Data Engineer", company="globex")
    db.update("gh:globex:2", status="filled")
    c = _app(tmp_path, db)
    html = c.get("/").text
    assert "Your week, in your words" in html and "Before the hard days" in html
    assert "/dua?company=Globex#people" in html
    c.post("/plan", data={"roles": "data roles", "days": ["Mon", "Thu"], "contact": "Sam"})
    html = c.get("/").text
    assert "Your plan this week" in html and "data roles · Mon, Thu · get in touch with Sam" in html

    c.post("/setback", data={"if_then": "send one message, then walk", "key": "pal:setback:early"})
    assert coach.if_then(db) == "send one message, then walk" and "Before the hard days" not in c.get("/").text

    assert 'value="Globex"' in c.get("/dua?company=Globex").text
    c.post("/contacts", data={"action": "add", "name": "Sam Rivera", "company": "Globex", "how": "Call"})
    page = c.get("/dua").text
    assert "Sam Rivera" in page and "Networking contact" in page

    r = c.post("/reflect", data={"values": ["Family"], "text": "x", "back": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/" and coach.reflections(db)
    assert "Fifteen minutes on what matters to you" in c.get("/reflect").text


def test_rejection_note_shows_the_persons_own_plan(tmp_path, db):
    _job(db, 1, "Analytics Engineer", sent=datetime.now().strftime("%Y-%m-%d %H:%M"))
    db.add_event({"id": "r1", "job_id": None, "kind": "rejected", "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                  "sender": "Globex <no@globex.example>", "subject": "s", "reviewed": 1})
    coach.set_note(db, "setback:ifthen", "call my sister")
    assert "<q>call my sister</q>" in _app(tmp_path, db).get("/").text


def test_skills_page_offers_related_titles_and_adds_one(tmp_path, db):
    for i in range(2):
        _job(db, i, "Analytics Developer", company=f"x{i}")
    c = _app(tmp_path, db, search={"title_keywords": ["analytics engineer"]})
    assert "Titles close to yours" in c.get("/skills").text
    c.post("/titles/add", data={"title": "analytics developer"})
    assert "analytics developer" in (tmp_path / "config.yaml").read_text()


def test_offer_card_motion_is_finite_and_respects_reduced_motion(tmp_path, db):
    _job(db, 1, "Analytics Engineer", sent=datetime.now().strftime("%Y-%m-%d %H:%M"))
    html = _app(tmp_path, db).get("/").text
    assert "offer-up .5s ease-out 1" in html and "@media (prefers-reduced-motion:reduce){.offer{animation:none}}" in html
