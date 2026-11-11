# Weekly Goals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the weekly plan with four weekly totals that are spread across the person's chosen days. A Today
card shows the day's share, and a look-back on Sunday flows into planning the next week. It uses real graphics and
finite animations.

**Architecture:**
- A new `autoapply/goals.py` holds the logic. It stores data in the existing `pal_notes` table through
  `coach.note` and `coach.set_note`.
- `web.py` extends `/plan` and adds `/plan/day`.
- A new template partial `templates/_goals.html` renders the three cards and the graphics.
- `brief.py` and the Stats page read from `goals.py`.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite, pytest. Inline SVG and CSS only, with no new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-11-weekly-goals-design.md`

## Global Constraints
- **Weeks** run Sunday to Saturday (`stats.week_start`). Day names come from `coach.DAYS` (`"Sun".."Sat"`).
- **The four goals**, in this order: `apps` (a count), then `reach`, `prep` and `learn` (minutes, stored as ints,
  entered in 30-minute steps).
- **Limits:** `apps` 0..200 a week; each time goal 0..2400 minutes (40 h) a week. Bad input clamps to these
  limits or is read as 0; it never raises.
- **Old plans keep working.** A `plan:<week>` value with only `roles`, `days` and `contact` reads and shows
  exactly as it does today.
- **Copy rules:**
  - No emojis.
  - Never the words "missed", "behind" or "streak".
  - No red for a short day, and no "0/5" headline.
  - Counts go up.
  - No research figures in copy.
  - Every new line goes into the VOICE.md phrase bank first.
- **No reminders and no push.** The plan never changes the daily run or the work-search count.
- **Motion:** every animation is finite and plays once per event. Under `prefers-reduced-motion: reduce` there is
  no animation and the finished state shows. Nothing runs longer than 5 s.
- **Layout:** it works at phone width (360 px) in light and dark themes, using the existing CSS variables
  (`--accent`, `--accent-soft`, `--accent-ink`, `--sun`, `--sun-soft`, `--ink-2`, `--line-2`, `--surface`).
- **No commits during the build** (Harun: no git unless asked). At the end, ask whether to branch, commit and
  open a PR. If yes: named paths only, and no Claude attribution line (monorepo rule).
- **The `autoapply/**` guard:** `.claude/settings.json` denies Edit and Write there (a guard for the daily-run
  agent). Write those files from a shell, and only with Harun's OK for this feature.
- **Lazy imports:** import `goals` inside functions in `stats.py`, `brief.py` and `web.py`, as `coach` is
  imported. `goals` imports `stats` at module level.
- **Web tests must not depend on the real weekday:** tick all seven days.

## Review Focus
1. **A plan saved before this feature** (no `goals` key) must show the old card unchanged. The test goes in Task 1
   (`test_old_plan_reads_as_before`) and Task 3 (`test_dashboard_old_plan_unchanged`).
2. **Blank, negative, non-numeric or huge totals** clamp and never raise. The test goes in Task 1
   (`test_totals_clamp`).
3. **Totals with no days ticked** spread over Mon to Fri. The test goes in Task 1 (`test_no_days_means_weekdays`).
4. **Reloading the dashboard after a "met" animation** must not play it again. The test goes in Task 3
   (`test_met_animation_plays_once`).
5. **Sunday is the first day of a new week.** Saturday's Done entries belong to the week that just ended and
   appear in Sunday's look-back. "Move to tomorrow" on the last chosen day of the week is offered nowhere and is a
   no-op if posted. The tests go in Task 1 (`test_saturday_counts_in_lookback`, `test_move_on_last_day_is_noop`).

---

### Task 1: `goals.py`: plan, spread, done, actuals and views

**Files:**
- Create: `autoapply/goals.py`
- Test: `tests/test_goals.py`

**Interfaces:**
- **Consumes:**
  - `coach.note(db, key)`, `coach.set_note(db, key, value)`, `coach.touch(db)`, `coach.DAYS`;
  - `coach.contacts(db)` (rows with `at` as `YYYY-MM-DD`);
  - `stats.week_start(d)`;
  - `db.all()` (jobs with `status`, `submitted_at`);
  - `db.nudge_states()`, `db.set_nudge(key, "done")`.
- **Produces:**
  - `GOALS: tuple[str, ...] = ("apps", "reach", "prep", "learn")`
  - `LABELS = {"apps": "Applications", "reach": "Reaching out", "prep": "Interview prep", "learn": "Learning"}`
  - `parse_totals(form: Mapping) -> dict[str, int]`. It reads `apps` as an int, and `reach_h`, `prep_h` and
    `learn_h` as hours (floats, "1.5" or "1:30"), rounded to 30-minute steps and returned as minutes. It clamps
    to the limits.
  - `spread(totals: dict, days: list[str], week: date, start: date) -> dict[str, dict[str, int]]`. It returns a
    per-day map for the chosen days on or after `start`. When `days` is empty it uses `["Mon".."Fri"]`. Counts
    divide as integers. Minutes divide in 30-minute units. The remainder goes to the earliest days.
  - `save_week(db, week: date, totals: dict, days: list[str], roles: str, contact: str, today: date) -> dict`.
    It keeps the existing `roles`, `days` and `contact` behaviour. It keeps `per_day` entries for days before
    `today`. It re-spreads `totals` minus what those past days planned (never below 0) over today and the later
    chosen days. If no chosen day remains from `today` on, the remainder goes on `today`. It writes `per_day`,
    sets `goals` to the sum of `per_day`, then calls `coach.touch`.
  - `set_day(db, week: date, day: str, goal: str, value: int) -> dict`. It changes one day's planned amount (a
    count or minutes), then sets `goals[goal]` to the sum over `per_day`.
  - `week_goals(plan: dict | None) -> dict[str, int] | None`. It returns the sum of `per_day`, or None for a plan
    with no `goals`.
  - `mark_done(db, day: date, goal: str, minutes: int | None) -> int`. With None it credits that day's planned
    minutes. Otherwise it sets the value to `minutes`, clamped to 0..960. It stores the value under
    `done:<iso day>` as `{goal: minutes}` and returns the stored value. `goal` must be `reach`, `prep` or `learn`.
  - `move_to_tomorrow(db, day: date, goal: str) -> bool`. It takes the unfinished amount off `day` and adds it
    to the next chosen day in the same week. It returns False, changing nothing, when there is no such day.
  - `actuals(db, day: date) -> dict`. It returns
    `{"apps": n, "reach": m, "prep": m, "learn": m, "people": n}`. `apps` counts the submitted jobs whose
    `submitted_at` falls on `day`. `people` counts the contacts whose `at` is `day`. The minutes come from
    `done:<day>`.
  - `today_view(db, today: date) -> dict | None`. It returns None when this week's plan has no `goals`. Otherwise
    it returns:
    - `{"rest": bool, "blocks": [ {goal, label, planned, done, frac, met, can_move} ], "week_so_far": {goal: n},`
    - `"strip": [ {day, date, planned: bool, frac, rest, today} x7 ]}`.
    - `frac` is done ÷ planned, capped at 1, and is 0 when planned is 0.
    - `can_move` is False on the last chosen day or when the block is met.
  - `week_view(db, week: date) -> dict`. It returns
    `{"rows": [ {goal, label, did, planned} ], "people": n, "planned": bool, "strip": [...], "note": str}`.
    `planned` is False when that week had no goals; the rows still carry `did`.
  - `lookback(db, today: date) -> dict | None`. It returns `week_view` of the previous week, plus `week` (its
    Sunday). It is shown only when this week has no `goals`, this week's plan wasn't skipped
    (`pal:plan-skip:<week>`), and the previous week has some activity or goals.
  - `save_note(db, week: date, text: str) -> None`. It stores `lookback:<week>` with the text trimmed to 300
    characters; empty text removes it.
  - `prefill(db, week: date) -> dict[str, int] | None`. It returns the goals of the most recent earlier week
    that had goals, or None.
  - `new_met(db, today: date) -> list[dict]`. It returns `{key, scope: "block"|"day"|"week", goal?}` for each
    met moment whose key isn't in `db.nudge_states()`. The keys are `goals:met:<iso day>:<goal>`,
    `goals:met:<iso day>`, and `goals:met:week:<iso week>`. The caller marks them `"done"`.
  - `history(db, today: date, weeks: int = 12) -> list[dict]`. It returns `week_view` rows for past weeks that
    had goals, newest first.

- [ ] **Step 1: Write the failing tests** in `tests/test_goals.py`. Use the `db` fixture pattern from
  `tests/test_coach.py`; `TODAY = date(2026, 11, 11)` is a Wednesday and `WK = date(2026, 11, 8)`.

```python
def test_totals_clamp():
    assert goals.parse_totals({"apps": "-3", "reach_h": "abc", "prep_h": "1:30", "learn_h": "99"}) == \
        {"apps": 0, "reach": 0, "prep": 90, "learn": 2400}
    assert goals.parse_totals({"apps": "999", "reach_h": "1.2"})["apps"] == 200
    assert goals.parse_totals({"reach_h": "1.2"})["reach"] == 60   # rounds to 30-minute steps

def test_spread_puts_remainder_early():
    d = goals.spread({"apps": 18, "reach": 180, "prep": 0, "learn": 210}, ["Mon","Tue","Wed","Thu","Fri"], WK, WK)
    assert [d[x]["apps"] for x in ["Mon","Tue","Wed","Thu","Fri"]] == [4, 4, 4, 3, 3]
    assert [d[x]["learn"] for x in ["Mon","Tue","Wed","Thu","Fri"]] == [60, 60, 30, 30, 30]
    assert sum(v["reach"] for v in d.values()) == 180

def test_no_days_means_weekdays():
    assert sorted(goals.spread({"apps": 5, "reach": 0, "prep": 0, "learn": 0}, [], WK, WK)) == \
        sorted(["Mon","Tue","Wed","Thu","Fri"])

def test_mid_week_plan_starts_today(db):
    p = goals.save_week(db, WK, {"apps": 9, "reach": 0, "prep": 0, "learn": 0}, ["Mon","Wed","Thu","Fri"], "", "", TODAY)
    assert "Mon" not in p["per_day"] and [p["per_day"][d]["apps"] for d in ["Wed","Thu","Fri"]] == [3, 3, 3]

def test_retotal_keeps_past_days(db):
    goals.save_week(db, WK, {"apps": 10, "reach": 0, "prep": 0, "learn": 0}, ["Mon","Tue","Wed","Thu","Fri"], "", "", WK)
    p = goals.save_week(db, WK, {"apps": 14, "reach": 0, "prep": 0, "learn": 0}, ["Mon","Tue","Wed","Thu","Fri"], "", "", TODAY)
    assert p["per_day"]["Mon"]["apps"] == 2 and p["per_day"]["Tue"]["apps"] == 2
    assert sum(p["per_day"][d]["apps"] for d in ["Wed","Thu","Fri"]) == 10

def test_set_day_changes_week_total(db):
    goals.save_week(db, WK, {"apps": 10, "reach": 0, "prep": 0, "learn": 0}, ["Mon","Tue","Wed","Thu","Fri"], "", "", WK)
    p = goals.set_day(db, WK, "Wed", "apps", 5)
    assert p["goals"]["apps"] == 13 and goals.week_goals(p)["apps"] == 13

def test_old_plan_reads_as_before(db):
    coach.save_plan(db, WK, "data roles", ["Mon"], "Sam")
    assert goals.week_goals(coach.plan(db, WK)) is None and goals.today_view(db, TODAY) is None
    assert coach.plan_line(coach.plan(db, WK)) == "data roles · Mon · get in touch with Sam"

def test_actuals_count_apps_contacts_and_done(db):   # build with _job/add_contact as in test_coach.py
    ...  # two jobs submitted 2026-11-11, one 2026-11-10, one contact today, mark_done(TODAY, "learn", None)
    a = goals.actuals(db, TODAY)
    assert a["apps"] == 2 and a["people"] == 1 and a["learn"] == 30   # the planned 30 credited

def test_short_day_is_credit_not_failure(db):
    # plan 5 apps today, send 1: block not met, frac 0.2, can_move True; nothing in the view says "missed"
    ...
    v = goals.today_view(db, TODAY)
    blk = next(b for b in v["blocks"] if b["goal"] == "apps")
    assert (blk["done"], blk["met"], blk["can_move"]) == (1, False, True) and blk["frac"] == pytest.approx(0.2)

def test_move_to_tomorrow_keeps_week_total(db):
    goals.save_week(db, WK, {"apps": 0, "reach": 0, "prep": 0, "learn": 120}, ["Wed","Fri"], "", "", TODAY)
    assert goals.move_to_tomorrow(db, TODAY, "learn") is True
    p = coach.plan(db, WK)
    assert (p["per_day"]["Wed"]["learn"], p["per_day"]["Fri"]["learn"], p["goals"]["learn"]) == (0, 120, 120)

def test_move_on_last_day_is_noop(db):
    goals.save_week(db, WK, {"apps": 2, "reach": 0, "prep": 0, "learn": 0}, ["Wed"], "", "", TODAY)
    assert goals.move_to_tomorrow(db, TODAY, "apps") is False
    assert coach.plan(db, WK)["per_day"]["Wed"]["apps"] == 2

def test_lowering_done_unmeets(db):
    goals.save_week(db, WK, {"apps": 0, "reach": 0, "prep": 60, "learn": 0}, ["Wed"], "", "", TODAY)
    goals.mark_done(db, TODAY, "prep", None)
    assert next(b for b in goals.today_view(db, TODAY)["blocks"] if b["goal"] == "prep")["met"]
    goals.mark_done(db, TODAY, "prep", 30)
    assert not next(b for b in goals.today_view(db, TODAY)["blocks"] if b["goal"] == "prep")["met"]

def test_week_met_counts_only_goals_above_zero(db):
    goals.save_week(db, WK, {"apps": 0, "reach": 0, "prep": 0, "learn": 60}, ["Wed"], "", "", TODAY)
    goals.mark_done(db, TODAY, "learn", None)
    keys = {m["key"] for m in goals.new_met(db, TODAY)}
    assert {"goals:met:2026-11-11:learn", "goals:met:2026-11-11", "goals:met:week:2026-11-08"} <= keys

def test_saturday_counts_in_lookback(db):
    goals.save_week(db, WK, {"apps": 0, "reach": 0, "prep": 0, "learn": 60}, ["Sat"], "", "", WK)
    goals.mark_done(db, date(2026, 11, 14), "learn", None)
    lb = goals.lookback(db, date(2026, 11, 15))   # Sunday
    assert lb["week"] == WK and next(r for r in lb["rows"] if r["goal"] == "learn")["did"] == 60

def test_lookback_without_goals_shows_did_only(db):
    ...  # one app sent 2026-11-10, no plan; lookback on 2026-11-15
    lb = goals.lookback(db, date(2026, 11, 15))
    assert lb["planned"] is False and next(r for r in lb["rows"] if r["goal"] == "apps")["did"] == 1

def test_save_after_last_chosen_day_lands_today(db):
    p = goals.save_week(db, WK, {"apps": 4, "reach": 0, "prep": 0, "learn": 0}, ["Mon","Tue"], "", "", TODAY)
    assert p["per_day"]["Wed"]["apps"] == 4 and p["goals"]["apps"] == 4

def test_lowering_total_keeps_goals_equal_to_days(db):
    goals.save_week(db, WK, {"apps": 10, "reach": 0, "prep": 0, "learn": 0}, ["Mon","Tue","Wed","Thu","Fri"], "", "", WK)
    p = goals.save_week(db, WK, {"apps": 2, "reach": 0, "prep": 0, "learn": 0}, ["Mon","Tue","Wed","Thu","Fri"], "", "", TODAY)
    assert p["goals"]["apps"] == sum(v["apps"] for v in p["per_day"].values()) == 4

def test_prefill_uses_latest_week_with_goals(db):
    goals.save_week(db, WK, {"apps": 18, "reach": 180, "prep": 120, "learn": 210}, ["Mon"], "", "", WK)
    assert goals.prefill(db, date(2026, 11, 22)) == {"apps": 18, "reach": 180, "prep": 120, "learn": 210}
    assert goals.prefill(db, WK) is None
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_goals.py -q`. Expected: it fails at collection with
  `ModuleNotFoundError: autoapply.goals`.
- [ ] **Step 3: Implement `autoapply/goals.py`** to the interfaces above. The module docstring names the
  sources, in the style of `coach.py`.
  - **Storage:**
    - the plan stays at `plan:<week>`;
    - Done entries go at `done:<iso day>`;
    - the look-back note goes at `lookback:<iso week>`.
  - **Spread algorithm:** for a count `n` over `k` days, `base, extra = divmod(n, k)`, and the first `extra`
    days get `base + 1`. For minutes, the same is done on `n // 30` units, then multiplied by 30.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_goals.py tests/test_coach.py -q`. Expected: all pass.

### Task 2: Copy into the VOICE.md phrase bank

**Files:**
- Modify: `VOICE.md` (phrase bank table and the "What helps a search" list)

**Interfaces:**
- **Produces:** the exact strings that Tasks 3 to 5 render. They are fixed here.

- [ ] **Step 1: Add these phrase-bank rows**, verbatim:

| Moment | Line |
|---|---|
| Weekly goals, setting | "Your week, in your words. Set a few totals and pick your days; we'll spread them out. Change any day." |
| Today card, a day with a plan | "Today" / "This week so far: {summary}." |
| Today card, a day that falls short | "{n} {thing} today, and that counts." |
| Today card, rest day | "A rest day in your plan. Rest counts too." |
| Block met | "Done for today." |
| Day met | "That's today's plan done. The rest of the day is yours." |
| Week plan met | "Your plan for the week, done. You set it on Sunday and you followed through." |
| Look-back, with a plan | "You had a plan and you worked to it: {summary}. Planning your week is one of the things that helps a search stay on track. Next week builds on this one." |
| Look-back, no plan | "Last week: {summary}. That all counts. A short plan for this week can help keep the days steady." |
| Look-back, nothing done | "A quiet week. That happens, and this one is a fresh start." |
| Look-back note prompt | "What helped, or what got in the way? (optional, just for you)" |
| Morning email, Sunday | "Last week: {summary}. Plan this week: {url}/#plan" |
| Morning email, a planned day | "Today's plan: {today_line}" |

- [ ] **Step 2:** Under "What helps a search", extend the plan bullet: "**Weekly goals** (Abel et al.; van Hooft
  et al. 2005; Jahoda): weekly totals the person sets, spread across chosen days; counted up, a short day is credit,
  no reminders; the weekly total absorbs a bad day (Wanberg, Zhu and van Hooft 2010)." Add Wanberg, Zhu and
  van Hooft (2010) and Feather and Bond (1983) to Main sources.

### Task 3: Dashboard: the Sunday card, the Today card, the look-back, graphics and motion

**Files:**
- Create: `autoapply/templates/_goals.html`, holding the macros `ring(frac, met)`, `strip(days)`,
  `goals_form(totals, days, roles, contact, saved)`, `today_card(v)` and `lookback_card(lb, totals)`, plus a
  `goals_css()` that contains every style and keyframe.
- Modify: `autoapply/templates/index.html:112-125` (the `#plan` section) and its `<style>` block.
- Modify: `autoapply/web.py`: `index()` at about lines 237-283, and `plan_save()` at about lines 460-470. Add
  `POST /plan/day` and `POST /plan/note`.
- Test: `tests/test_goals_web.py`

**Interfaces:**
- **Consumes:** everything Task 1 produces, the Task 2 strings, `coach.plan_line`, and
  `web_client.client(settings, db)`.
- **Produces:**
  - `POST /plan` takes `roles`, `contact`, `days[]`, `apps`, `reach_h`, `prep_h`, `learn_h` and `action`
    (`skip`). When any total is above 0 it calls `goals.save_week`; otherwise it calls `coach.save_plan`, as
    today. It redirects to `/?planned=1#plan`.
  - `POST /plan/day` takes `action` (`done`, `adjust`, `move` or `set`), `goal`, `day` (ISO date), `minutes` and
    `value`. It redirects to `/#today`, and returns 400 for an unknown goal or action.
  - `POST /plan/note` takes `week` (ISO) and `text`. It redirects to `/#plan`.
  - `index()` passes the template these extra values:
    - `today_goals=goals.today_view(...)`, `lookback=goals.lookback(...)`;
    - `prefill=goals.prefill(...)` or the current goals;
    - `just_met` (the set of keys from `goals.new_met`), which is marked `"done"` after rendering, following the
      `cel` pattern;
    - `planned=request "planned"`.
  - When `new_met` contains a week key and there is no other `celebrate`, the horizon plays `"week"` with the
    "Week plan met" line.

- [ ] **Step 1: Write the failing tests.** Build settings the way `_settings` in `tests/test_coach.py` does,
  with `client` from `web_client`, and `ALL_DAYS = coach.DAYS`.

```python
def test_save_week_with_totals_and_today_card(tmp_path, db):
    c = _client(tmp_path, db)
    r = c.post("/plan", data={"apps": "18", "reach_h": "3", "prep_h": "2", "learn_h": "3.5",
                              "days": ALL_DAYS, "roles": "", "contact": ""}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?planned=1")
    html = c.get("/").text
    assert 'id="today"' in html and "Applications" in html and "This week so far" in html
    visible = re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.S).lower()
    for word in ("missed", "behind", "streak"):
        assert word not in visible

def test_dashboard_old_plan_unchanged(tmp_path, db):
    coach.save_plan(db, stats.week_start(date.today()), "data roles", ["Mon"], "Sam")
    html = _client(tmp_path, db).get("/").text
    assert "Your plan this week" in html and "data roles · Mon · get in touch with Sam" in html and 'id="today"' not in html

def test_done_and_bad_inputs(tmp_path, db):
    c = _client(tmp_path, db)
    c.post("/plan", data={"learn_h": "7", "days": ALL_DAYS})
    assert c.post("/plan/day", data={"action": "done", "goal": "learn", "day": date.today().isoformat()},
                  follow_redirects=False).status_code == 303
    assert c.post("/plan/day", data={"action": "done", "goal": "nap", "day": date.today().isoformat()}).status_code == 400

def test_met_animation_plays_once(tmp_path, db):
    c = _client(tmp_path, db)
    c.post("/plan", data={"learn_h": "7", "days": ALL_DAYS})   # >= 30 min on every remaining day incl. today
    c.post("/plan/day", data={"action": "done", "goal": "learn", "day": date.today().isoformat()})
    assert 'data-met="goals:met:' in c.get("/").text
    assert 'data-met="goals:met:' not in c.get("/").text

def test_note_saves(tmp_path, db):
    ...  # POST /plan/note for last week, then goals.week_view(db, last_week)["note"] == text
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_goals_web.py -q`. Expected: it fails (no `id="today"`, and
  `/plan/day` returns 404).
- [ ] **Step 3: Implement the routes and the `index()` additions** to the interfaces above. `plan_save` stays
  async, as it is today, and reads `f.getlist("days")`.
- [ ] **Step 4: Build `_goals.html`.** Use the `frontend-design` skill for this step only, with the brief "fit
  `_horizon.html` and the current dashboard; no new style." The fixed decisions:
  - **`ring(frac, met)`:** a 44 px SVG ring with the track in `--line-2` and the fill in `--accent`, drawn with
    `stroke-dasharray`. When met, the fill turns `--sun` with a small check.
  - **`strip(days)`:** seven columns (Sun to Sat), each a rounded bar that fills from the bottom by `frac`.
    - A rest day is a short soft wave in `--accent-soft`, never empty.
    - A past day with no plan shows its activity as a small dot.
    - Today is outlined.
    - There is no red anywhere.
  - **Today card (`id="today"`):** one row per block with goal-above-zero today, laid out as ring, label,
    "done of planned", and the controls:
    - Done, with a small adjust input in 30-minute steps, for `reach`, `prep` and `learn`;
    - "Move to tomorrow" only when `can_move`;
    - for apps, "counted from what you sent";
    - for reach, "· N people" when there are any.
    The week-so-far line and the strip sit below the rows.
  - **Sunday card:** four total inputs (apps as a number; hours with `step="0.5"`), the existing day chips, roles
    and contact, and an "Adjust a day" `<details>` with a small per-day table that posts `action=set`. It is
    pre-filled from `prefill`.
  - **Look-back card:** a did/planned table and rings, the look-back line, the note input, and then the Sunday
    card inline, all in one `<section id="plan">`.
  - **Motion:**
    - rings and strip bars animate from 0 to their value on load (600 ms ease-out, once);
    - the met element carries `data-met="<key>"` and the class `just-met`, which adds a 900 ms glow and scale pulse on that ring, or on the whole Today card for a day key;
    - `?planned=1` slides the Sunday card up (`offer-up`, 500 ms), which the existing keyframe already does;
    - all of it is wrapped by a `@media (prefers-reduced-motion: reduce){...animation:none}` rule.
- [ ] **Step 5: Run** `.venv/bin/pytest tests/test_goals_web.py tests/test_goals.py tests/test_coach.py tests/test_pal.py -q`.
  Expected: all pass.
- [ ] **Step 6: Visual check.** Start the app locally (`run` skill) with a seeded week. Take screenshots at
  1280 px and 375 px in light and dark: a full day, a short day, a rest day, the look-back, and Reduce Motion on.
  Expected: no horizontal scroll, no red, and the rings and strip readable in both themes.

### Task 4: Morning email lines

**Files:**
- Modify: `autoapply/brief.py:84-85` (text) and `:127-128` (html)
- Test: `tests/test_goals.py` (append)

**Interfaces:**
- **Consumes:** `goals.today_view` and `goals.lookback` (Task 1), and the Task 2 strings.
- **Produces:** the text and html lines of the brief only.

- [ ] **Step 1: Write the failing tests.**
  - `test_brief_sunday_lookback`: with a week of goals ending 2026-11-14, calling `brief.compose(db,
    today=date(2026, 11, 15))` gives text containing `"Last week: "` and `"/#plan"`, and no `"Today's plan"`.
  - `test_brief_planned_day`: on `TODAY`, with a plan that has learning today, the text contains
    `"Today's plan: "` and `"Learning"`.
  - `test_brief_old_plan_line_unchanged`: the existing `test_brief_carries_the_plan_only_when_written` still
    passes.
- [ ] **Step 2: Run** them. Expected: the new ones fail.
- [ ] **Step 3: Implement.**
  - **The Sunday line:** when `lookback` is set, add the "Morning email, Sunday" line. `{summary}` is built from
    the did counts, for example "14 applications, 3 h reaching out, 2 h prep, 2 h learning", skipping zeros.
  - **A planned day:** add "Today's plan: …", listing today's blocks as "5 applications · Learning 30 m".
  - The existing "Your plan this week" line is kept.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_goals.py tests/test_coach.py -q`. Expected: all pass.

### Task 5: Stats "Weeks" section

**Files:**
- Modify: `autoapply/stats.py` (`detail()`: add `"goal_weeks": goals.history(db, today)`)
- Modify: `autoapply/templates/stats.html` (a new section after "Beyond applications")
- Test: `tests/test_goals.py` (append)

**Interfaces:**
- **Consumes:** `goals.history` and the `ring` and `strip` macros from `_goals.html`.

- [ ] **Step 1: Write the failing test** `test_stats_lists_planned_weeks`. With two past weeks of goals,
  `stats.detail(db, today=...)["goal_weeks"]` has length 2, newest first, and each entry has `rows` with `did`
  and `planned`.
- [ ] **Step 2: Run** it. Expected: it fails with `KeyError: 'goal_weeks'`.
- [ ] **Step 3: Implement.** Add the "Your planned weeks" section: one compact row per week, with the week date
  ("Nov 8"), four small rings showing did ÷ planned, and the numbers. It is hidden when the list is empty.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: the full suite passes.

### Task 6: Docs and publishing (monorepo rule)

**Files:**
- Modify: `README.md` (the features list: weekly goals); `AGENTS.md` only if it states dashboard features (it
  doesn't today, so check and leave it).
- Modify: the brainPal overlay (`../brainPal/graph/overlay.json`, the jobsearchPal node blurb), then
  `node brainPal/scanner/scan.js` and the live-copy commands from the monorepo `CLAUDE.md`.
- Docmost: a "Change log" entry under the jobsearchPal space, and a "Weekly goals" feature page (design,
  behaviour, rollout, rollback = revert the branch; the stored `plan:` JSON stays readable by old code because
  the extra keys are ignored).

- [ ] **Step 1:** Update the README features list in one paragraph.
- [ ] **Step 2:** Update the brainPal overlay and run the rescan. Verify:
  `curl -s http://100.115.254.75:9110/graph/data.js | grep -c "Weekly goals"` returns 1 or more.
- [ ] **Step 3:** Publish to Docmost with the `docmost-publish` skill. If llm or Docmost can't be reached, write
  `docs/changelog/2026-11-11-weekly-goals.md` and say so.
- [ ] **Step 4:** Ask Harun whether to branch, commit and open a PR.
