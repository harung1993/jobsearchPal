"""Weekly goals: totals the person sets on Sunday, spread over their chosen days, counted up each day, and a
look-back that flows into the next week. A short day is credit, never a failure."""
from datetime import date

import pytest

from autoapply import coach, goals, stats
from autoapply.db import DB

TODAY = date(2026, 11, 11)   # a Wednesday
WK = date(2026, 11, 8)       # its Sunday
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


@pytest.fixture
def db(tmp_path):
    return DB(tmp_path / "t.db")


def _sent(db, i, day, company="acme"):
    db.upsert_job({"id": f"gh:{company}:{i}", "ats": "greenhouse", "company": company, "title": f"Role {i}",
                   "location": "", "url": "u", "apply_url": "u", "description": ""})
    db.update(f"gh:{company}:{i}", status="submitted", submitted_at=f"{day} 10:00")


def _t(apps=0, reach=0, prep=0, learn=0):
    return {"apps": apps, "reach": reach, "prep": prep, "learn": learn}


def _blk(v, goal):
    return next(b for b in v["blocks"] if b["goal"] == goal)


# ---- setting the week ----------------------------------------------------------------------------

def test_totals_clamp():
    assert goals.parse_totals({"apps": "-3", "reach_h": "abc", "prep_h": "1:30", "learn_h": "99"}) == _t(0, 0, 90, 2400)
    assert goals.parse_totals({"apps": "999", "reach_h": "1.2"})["apps"] == 200
    assert goals.parse_totals({"reach_h": "1.2"})["reach"] == 60   # rounds to 30-minute steps
    assert goals.parse_totals({}) == _t()


def test_spread_puts_remainder_early():
    d = goals.spread(_t(18, 180, 0, 210), WEEKDAYS, WK, WK)
    assert [d[x]["apps"] for x in WEEKDAYS] == [4, 4, 4, 3, 3]
    assert [d[x]["learn"] for x in WEEKDAYS] == [60, 60, 30, 30, 30]
    assert sum(v["reach"] for v in d.values()) == 180


def test_no_days_means_weekdays():
    assert sorted(goals.spread(_t(5), [], WK, WK)) == sorted(WEEKDAYS)


def test_mid_week_plan_starts_today(db):
    p = goals.save_week(db, WK, _t(9), ["Mon", "Wed", "Thu", "Fri"], "", "", TODAY)
    assert "Mon" not in p["per_day"] and [p["per_day"][d]["apps"] for d in ["Wed", "Thu", "Fri"]] == [3, 3, 3]
    assert p["days"] == ["Mon", "Wed", "Thu", "Fri"]


def test_retotal_keeps_past_days(db):
    goals.save_week(db, WK, _t(10), WEEKDAYS, "", "", WK)
    p = goals.save_week(db, WK, _t(14), WEEKDAYS, "", "", TODAY)
    assert p["per_day"]["Mon"]["apps"] == 2 and p["per_day"]["Tue"]["apps"] == 2
    assert sum(p["per_day"][d]["apps"] for d in ["Wed", "Thu", "Fri"]) == 10 and p["goals"]["apps"] == 14


def test_save_after_last_chosen_day_lands_today(db):
    p = goals.save_week(db, WK, _t(4), ["Mon", "Tue"], "", "", TODAY)
    assert p["per_day"]["Wed"]["apps"] == 4 and p["goals"]["apps"] == 4


def test_lowering_total_keeps_goals_equal_to_days(db):
    goals.save_week(db, WK, _t(10), WEEKDAYS, "", "", WK)
    p = goals.save_week(db, WK, _t(2), WEEKDAYS, "", "", TODAY)
    assert p["goals"]["apps"] == sum(v["apps"] for v in p["per_day"].values()) == 4


def test_set_day_changes_week_total(db):
    goals.save_week(db, WK, _t(10), WEEKDAYS, "", "", WK)
    p = goals.set_day(db, WK, "Wed", "apps", 5)
    assert p["goals"]["apps"] == 13 and goals.week_goals(p)["apps"] == 13


def test_old_plan_reads_as_before(db):
    coach.save_plan(db, WK, "data roles", ["Mon"], "Sam")
    assert goals.week_goals(coach.plan(db, WK)) is None and goals.today_view(db, TODAY) is None
    assert coach.plan_line(coach.plan(db, WK)) == "data roles · Mon · get in touch with Sam"


def test_roles_and_contact_kept_with_goals(db):
    goals.save_week(db, WK, _t(5), WEEKDAYS, "analytics roles", "Sam", WK)
    assert coach.plan_line(coach.plan(db, WK)) == "analytics roles · Mon, Tue, Wed, Thu, Fri · get in touch with Sam"


# ---- each day ------------------------------------------------------------------------------------

def test_actuals_count_apps_contacts_and_done(db):
    _sent(db, 1, "2026-11-11")
    _sent(db, 2, "2026-11-11")
    _sent(db, 3, "2026-11-10")
    coach.add_contact(db, "Sam", "Globex", "Call", "", TODAY.isoformat())
    goals.save_week(db, WK, _t(learn=150), WEEKDAYS, "", "", WK)
    assert goals.mark_done(db, TODAY, "learn", None) == 30   # the planned 30 credited
    a = goals.actuals(db, TODAY)
    assert (a["apps"], a["people"], a["learn"], a["prep"]) == (2, 1, 30, 0)


def test_short_day_is_credit_not_failure(db):
    goals.save_week(db, WK, _t(apps=15), WEEKDAYS, "", "", WK)   # 3 a day
    goals.set_day(db, WK, "Wed", "apps", 5)
    _sent(db, 1, "2026-11-11")
    v = goals.today_view(db, TODAY)
    blk = _blk(v, "apps")
    assert (blk["done"], blk["planned"], blk["met"], blk["can_move"]) == (1, 5, False, True)
    assert blk["frac"] == pytest.approx(0.2) and not v["rest"]
    assert v["week_so_far"]["apps"] == 1
    assert [d["day"] for d in v["strip"]] == coach.DAYS and next(d for d in v["strip"] if d["today"])["day"] == "Wed"


def test_rest_day(db):
    goals.save_week(db, WK, _t(apps=4), ["Mon", "Tue"], "", "", WK)
    v = goals.today_view(db, TODAY)
    assert v["rest"] and v["blocks"] == []


def test_move_to_tomorrow_keeps_week_total(db):
    goals.save_week(db, WK, _t(learn=120), ["Wed", "Fri"], "", "", TODAY)
    assert goals.move_to_tomorrow(db, TODAY, "learn") is True
    p = coach.plan(db, WK)
    assert (p["per_day"]["Wed"]["learn"], p["per_day"]["Fri"]["learn"], p["goals"]["learn"]) == (0, 120, 120)


def test_move_only_the_unfinished_part(db):
    goals.save_week(db, WK, _t(apps=6), ["Wed", "Thu"], "", "", TODAY)
    _sent(db, 1, "2026-11-11")
    assert goals.move_to_tomorrow(db, TODAY, "apps") is True
    p = coach.plan(db, WK)
    assert (p["per_day"]["Wed"]["apps"], p["per_day"]["Thu"]["apps"]) == (1, 5)


def test_move_on_last_day_is_noop(db):
    goals.save_week(db, WK, _t(2), ["Wed"], "", "", TODAY)
    assert goals.move_to_tomorrow(db, TODAY, "apps") is False
    assert coach.plan(db, WK)["per_day"]["Wed"]["apps"] == 2
    assert _blk(goals.today_view(db, TODAY), "apps")["can_move"] is False


def test_lowering_done_unmeets(db):
    goals.save_week(db, WK, _t(prep=60), ["Wed"], "", "", TODAY)
    goals.mark_done(db, TODAY, "prep", None)
    assert _blk(goals.today_view(db, TODAY), "prep")["met"]
    goals.mark_done(db, TODAY, "prep", 30)
    assert not _blk(goals.today_view(db, TODAY), "prep")["met"]
    assert goals.mark_done(db, TODAY, "prep", 99999) == 960


def test_mark_done_rejects_apps(db):
    with pytest.raises(ValueError):
        goals.mark_done(db, TODAY, "apps", None)


def test_week_met_counts_only_goals_above_zero(db):
    goals.save_week(db, WK, _t(learn=60), ["Wed"], "", "", TODAY)
    goals.mark_done(db, TODAY, "learn", None)
    met = goals.new_met(db, TODAY)
    keys = {m["key"] for m in met}
    assert {"goals:met:2026-11-11:learn", "goals:met:2026-11-11", "goals:met:week:2026-11-08"} <= keys
    for k in keys:
        db.set_nudge(k, "done")
    assert goals.new_met(db, TODAY) == []


def test_extra_apps_stay_on_their_day(db):
    goals.save_week(db, WK, _t(apps=4), ["Tue", "Wed"], "", "", WK)
    for i in range(4):
        _sent(db, i, "2026-11-10")
    assert _blk(goals.today_view(db, TODAY), "apps")["done"] == 0   # Tuesday's extra don't fill Wednesday
    assert goals.today_view(db, TODAY)["week_so_far"]["apps"] == 4


# ---- looking back --------------------------------------------------------------------------------

def test_saturday_counts_in_lookback(db):
    goals.save_week(db, WK, _t(learn=60), ["Sat"], "", "", WK)
    goals.mark_done(db, date(2026, 11, 14), "learn", None)
    lb = goals.lookback(db, date(2026, 11, 15))   # Sunday
    assert lb["week"] == WK and lb["planned"] is True
    row = next(r for r in lb["rows"] if r["goal"] == "learn")
    assert (row["did"], row["planned"]) == (60, 60)


def test_lookback_without_goals_shows_did_only(db):
    _sent(db, 1, "2026-11-10")
    lb = goals.lookback(db, date(2026, 11, 15))
    assert lb["planned"] is False and next(r for r in lb["rows"] if r["goal"] == "apps")["did"] == 1


def test_lookback_hides_once_this_week_is_planned_or_skipped(db):
    _sent(db, 1, "2026-11-10")
    sun = date(2026, 11, 15)
    assert goals.lookback(db, sun)
    db.set_nudge(f"pal:plan-skip:{sun.isoformat()}", "done")
    assert goals.lookback(db, sun) is None


def test_lookback_none_for_an_empty_week(db):
    assert goals.lookback(db, date(2026, 11, 15)) is None


def test_note_saves_and_clears(db):
    goals.save_note(db, WK, "  mornings worked better  ")
    assert goals.week_view(db, WK)["note"] == "mornings worked better"
    goals.save_note(db, WK, "")
    assert goals.week_view(db, WK)["note"] == ""


def test_prefill_uses_latest_week_with_goals(db):
    goals.save_week(db, WK, _t(18, 180, 120, 210), ["Mon"], "", "", WK)
    assert goals.prefill(db, date(2026, 11, 22)) == _t(18, 180, 120, 210)
    assert goals.prefill(db, WK) is None


def test_history_lists_past_planned_weeks(db):
    goals.save_week(db, date(2026, 11, 1), _t(apps=5), WEEKDAYS, "", "", date(2026, 11, 1))
    goals.save_week(db, WK, _t(apps=8), WEEKDAYS, "", "", WK)
    h = goals.history(db, date(2026, 11, 18))
    assert [w["week"] for w in h] == [WK, date(2026, 11, 1)]
    assert next(r for r in h[0]["rows"] if r["goal"] == "apps")["planned"] == 8


def test_summary_counts_up_and_skips_zeros():
    assert goals.summary({"apps": 14, "reach": 180, "prep": 0, "learn": 90, "people": 4}) == \
        "14 applications, 3 h reaching out (4 people), 1.5 h learning"
    assert goals.summary({"apps": 1, "reach": 0, "prep": 30, "learn": 0, "people": 0}) == \
        "1 application, 30 m interview prep"
    assert goals.summary({"apps": 0, "reach": 0, "prep": 0, "learn": 0, "people": 0}) == ""


# ---- the morning email and Stats -----------------------------------------------------------------

def test_brief_sunday_lookback(db):
    from autoapply import brief
    goals.save_week(db, WK, _t(apps=5, learn=60), WEEKDAYS, "", "", WK)
    _sent(db, 1, "2026-11-10")
    _, text, html = brief.compose(db, review_url="http://x", today=date(2026, 11, 15))
    assert "Last week: 1 application. Plan this week: http://x/#plan" in text and "Last week:" in html
    assert "Today's plan" not in text


def test_brief_planned_day(db):
    from autoapply import brief
    goals.save_week(db, WK, _t(apps=3, learn=90), ["Wed", "Thu", "Fri"], "", "", WK)
    _, text, html = brief.compose(db, today=TODAY)
    assert "Today's plan: 1 application · Learning 30 m" in text and "Today's plan" in html
    assert "Last week" not in text


def test_stats_lists_planned_weeks(db):
    goals.save_week(db, date(2026, 11, 1), _t(apps=5), WEEKDAYS, "", "", date(2026, 11, 1))
    goals.save_week(db, WK, _t(apps=8), WEEKDAYS, "", "", WK)
    d = stats.detail(db, today=date(2026, 11, 18))
    assert [w["week"] for w in d["goal_weeks"]] == [WK, date(2026, 11, 1)]
    assert {"did", "planned"} <= set(d["goal_weeks"][0]["rows"][0])


def test_hours_never_raise():
    assert goals.parse_totals({"reach_h": "inf", "prep_h": "nan", "learn_h": "1e400"}) == _t()


def test_lookback_stops_once_this_week_has_any_plan(db):
    goals.save_week(db, WK, _t(apps=5), WEEKDAYS, "", "", WK)
    sun = date(2026, 11, 15)
    assert goals.lookback(db, sun)
    coach.save_plan(db, sun, "data roles", ["Mon"], "")   # roles and days only, no totals
    assert goals.lookback(db, sun) is None


def test_lookback_of_a_planned_week_with_nothing_done(db):
    goals.save_week(db, WK, _t(apps=5), WEEKDAYS, "", "", WK)
    lb = goals.lookback(db, date(2026, 11, 15))
    assert lb["planned"] and goals.summary(lb["did"]) == ""
