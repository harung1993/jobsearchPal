"""Weekly goals on the dashboard: the Sunday card, the Today card, Done and Move to tomorrow, the once-only met
moments, and the look-back note. Plans tick all seven days so the tests don't depend on today's weekday."""
import re
from datetime import date, timedelta

import pytest

from autoapply import coach, goals, stats
from autoapply.config import Settings
from autoapply.db import DB

ALL_DAYS = list(coach.DAYS)


@pytest.fixture
def db(tmp_path):
    (tmp_path / "data").mkdir()
    return DB(tmp_path / "data" / "autoapply.db")


def _client(tmp_path, db):
    from web_client import client
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={"first_name": "Alex"})
    return client(s, db)


def _visible(html: str) -> str:
    return re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.S).lower()


def test_save_week_with_totals_and_today_card(tmp_path, db):
    c = _client(tmp_path, db)
    r = c.post("/plan", data={"apps": "18", "reach_h": "3", "prep_h": "2", "learn_h": "3.5",
                              "days": ALL_DAYS, "roles": "data roles", "contact": "Sam"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?planned=1")
    p = coach.plan(db, stats.week_start(date.today()))
    assert p["goals"]["apps"] <= 18 and p["roles"] == "data roles"
    html = c.get("/?planned=1").text
    assert 'id="today"' in html and "Applications" in html and 'class="g-strip"' in html
    assert "This week so far" not in html   # nothing done yet: no line rather than a zero
    vis = _visible(html)
    for word in ("missed", "behind", "streak"):
        assert word not in vis


def test_plan_without_totals_is_the_old_plan(tmp_path, db):
    c = _client(tmp_path, db)
    c.post("/plan", data={"roles": "data roles", "days": ["Mon"], "contact": "Sam", "apps": "", "reach_h": ""})
    assert "goals" not in coach.plan(db, stats.week_start(date.today()))


def test_dashboard_old_plan_unchanged(tmp_path, db):
    coach.save_plan(db, stats.week_start(date.today()), "data roles", ["Mon"], "Sam")
    html = _client(tmp_path, db).get("/").text
    assert "Your plan this week" in html and "data roles · Mon · get in touch with Sam" in html
    assert 'id="today"' not in html


def test_done_move_set_and_bad_inputs(tmp_path, db):
    c = _client(tmp_path, db)
    c.post("/plan", data={"learn_h": "7", "apps": "14", "days": ALL_DAYS})
    today = date.today().isoformat()
    r = c.post("/plan/day", data={"action": "done", "goal": "learn", "day": today}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("#today")
    assert goals.actuals(db, date.today())["learn"] >= 30
    c.post("/plan/day", data={"action": "adjust", "goal": "learn", "day": today, "minutes": "90"})
    assert goals.actuals(db, date.today())["learn"] == 90
    assert c.post("/plan/day", data={"action": "done", "goal": "nap", "day": today}).status_code == 400
    assert c.post("/plan/day", data={"action": "dance", "goal": "learn", "day": today}).status_code == 400
    assert c.post("/plan/day", data={"action": "done", "goal": "learn", "day": "not-a-date"}).status_code == 400
    wk = stats.week_start(date.today())
    c.post("/plan/day", data={"action": "set", "day": "Sat", "v_apps": "6", "v_learn": "1.5", "week": wk.isoformat()})
    assert (coach.plan(db, wk)["per_day"]["Sat"]["apps"], coach.plan(db, wk)["per_day"]["Sat"]["learn"]) == (6, 90)
    assert c.post("/plan/day", data={"action": "adjust", "goal": "learn", "day": today, "hours": "nan"}).status_code < 500
    assert c.post("/plan", data={"reach_h": "inf", "days": ALL_DAYS}).status_code < 500


def test_met_animation_plays_once(tmp_path, db):
    c = _client(tmp_path, db)
    c.post("/plan", data={"learn_h": "7", "days": ALL_DAYS})   # at least 30 min on every day left, today too
    c.post("/plan/day", data={"action": "done", "goal": "learn", "day": date.today().isoformat()}, follow_redirects=False)
    html = c.get("/").text
    assert 'data-met="goals:met:' in html and "This week so far: " in html
    assert 'data-met="goals:met:' not in c.get("/").text


def test_lookback_and_note(tmp_path, db):
    last = stats.week_start(date.today()) - timedelta(days=7)
    goals.save_week(db, last, {"apps": 5, "reach": 60, "prep": 0, "learn": 0}, ALL_DAYS, "", "", last)
    c = _client(tmp_path, db)
    html = c.get("/").text
    assert "Your week, looking back" in html and "did" in _visible(html)
    r = c.post("/plan/note", data={"week": last.isoformat(), "text": "mornings worked better"}, follow_redirects=False)
    assert r.status_code == 303
    assert goals.week_view(db, last)["note"] == "mornings worked better"
    assert c.post("/plan/note", data={"week": "nope", "text": "x"}).status_code == 400


def test_stats_shows_planned_weeks(tmp_path, db):
    last = stats.week_start(date.today()) - timedelta(days=7)
    goals.save_week(db, last, {"apps": 5, "reach": 0, "prep": 0, "learn": 0}, ALL_DAYS, "", "", last)
    html = _client(tmp_path, db).get("/stats").text
    assert "Your planned weeks" in html


def test_in_page_post_keeps_the_met_moment_for_the_real_page(tmp_path, db):
    """base.html posts forms with fetch (X-In-Page) and follows the redirect; that hidden render must not use up the
    animation the person is about to see."""
    c = _client(tmp_path, db)
    c.post("/plan", data={"learn_h": "7", "days": ALL_DAYS})
    c.post("/plan/day", data={"action": "done", "goal": "learn", "day": date.today().isoformat(), "back": "/#today"},
           headers={"X-In-Page": "1"})   # follows the redirect with the header, as fetch does
    assert 'data-met="goals:met:' in c.get("/").text
