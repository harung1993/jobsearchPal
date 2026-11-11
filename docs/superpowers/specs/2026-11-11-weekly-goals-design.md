# Weekly goals: plan the week on Sunday, see each day, look back

Design, 2026-11-11. Status: agreed in conversation with Harun, awaiting approval of this document.

## Why

When you're out of work, the hardest part is often keeping the days structured. What helped Harun most on an
earlier search was setting a goal for the day, sticking to it, and being able to look back and see that it was
met. The goal wasn't only applications. It was how the hours were split between applying, reaching out to
people, interview prep and learning.

The evidence agrees (summary from the research pass, 2026-11-10):
- Writing a plan raised job offers in a field trial, and reminders added nothing (Abel et al.). Specific "when
  and where" plans turn intentions into search (van Hooft et al. 2005).
- Structured, purposeful time goes with better wellbeing while unemployed (Jahoda; Feather and Bond 1983;
  Selenko et al. 2011). This is mostly correlational.
- Effort predicts interviews, but systematic, well-fitted search predicts outcomes better (van Hooft et al. 2021;
  Kreemers et al. 2022). An application number is a plan, not a score.
- A broken streak lowers later effort (Silverman and Barasch 2023). Weekly totals soak up a bad day; day-to-day
  swings in mood and progress are normal (Wanberg, Zhu and van Hooft 2010).

## What it is

An extension of the existing "Your week, in your words" plan (`coach.py`, `/plan`, dashboard `#plan` card). It
does three things.

### 1. Sunday: set the week (option B, chosen by Harun)
- The person sets four **weekly totals**:
  - **Applications:** a count.
  - **Reaching out:** hours.
  - **Interview prep:** hours.
  - **Learning:** hours.
- They tick the **days they'll search**. The existing roles and one-contact fields stay.
- The app **spreads the totals across the chosen days**, and the person can change any single day.
- The card is offered on Sunday, and on any later day of the week that has no plan yet. "Not this week" still
  works, as it does today.
- *My call:* new weeks start from the previous week's numbers. A first-ever plan starts blank, with placeholder
  examples. Hours go in 30-minute steps. When a total doesn't divide evenly, earlier days get the remainder.

### 2. Each day: a "Today" card on the dashboard
- It shows today's share of each goal.
- **Applications count themselves:** everything submitted today, including roles logged by hand.
- **Reaching out** shows the planned time and the number of people logged today from `contacts`, which also
  count themselves.
- **Prep and learning** get a Done control. *My call:* Done credits the planned time for that block, and a small
  adjust control lets the person change the amount.
- It shows a running "this week so far" line, always counting up.
- **A day that falls short:** the card credits what was done ("1 application today, and that counts") and shows
  the week so far. There is no "missed", no red and no zero. Leftovers aren't carried over automatically.
  *My call:* an optional "Move to tomorrow" for any unfinished block; otherwise it is simply let go.
- Days the person didn't pick show as rest days ("Rest counts too").

### 3. Sunday: look back, then plan the next week
- **One card** (mocked up and approved) shows last week:
  - did next to planned for each goal (the column says "did", never "missed");
  - a short line that credits the week and names planning as what keeps a search on track, in VOICE rule 2
    style, built from the record;
  - an optional "What helped, or what got in the way?" note that only the person sees.
- **The same card flows into planning the new week**, pre-filled from last week.
- **The morning email** (`brief.py`) carries a short version on Sunday, and on other days the existing "Your
  plan this week" line grows to include today's share.
- **No push and no reminder.** The app's rule stays: reminders added nothing in the trial.
- *My call:* past weeks' plan-against-actual go in a small "Weeks" section on Stats, so the person can look
  further back.

### Look and motion (Harun: "use animations, and better graphics")
- **Real graphics, not text rows.** Each goal gets a progress graphic: a ring or a bar that fills, in the app's
  colors, working in both light and dark themes. The week shows as a 7-day strip whose days fill by how much was
  done. Rest days look restful, and an unmet day is drawn as partly filled, never as a gap or a red mark.
- **Motion:**
  - fills animate on load;
  - a small finite "done" moment when a block or a whole day is met;
  - the existing horizon "week" light-spread when the whole weekly plan is met, distinct from the work-search
    "week covered" celebration;
  - a gentle animation when the week is saved.
- **Motion rules:** every animation is finite and plays once per event. With Reduce Motion the finished picture
  shows with no movement. No loop runs longer than 5 seconds (the VOICE.md Motion rules).
- Use the `frontend-design` skill for the visual pass. The look should fit `_horizon.html` and the existing
  dashboard, not a new style.

### Rules settled after the builder check (all *my call*)
- **Reaching out** works like prep and learning: Done credits the planned time and the amount can be adjusted.
  The number of people logged from `contacts` shows alongside ("3 h · 4 people"), as in the approved mockup,
  but the ring fills by hours.
- **"Met":**
  - **A block** is met when what was done is at least that day's share.
  - **A day** is met when every block planned for it is met.
  - **The week** is met when every goal set above zero has reached its weekly total.
  - **Applications** count on the day they were sent. Extra applications fill that day past its share and count
    toward the week; they are not moved onto another day.
  - **Lowering a Done amount** below the share un-meets the block, and no animation plays.
  - Each "met" moment animates once per block, day or week, and never again on reload.
- **Changing one day changes the weekly total**, so the week always equals the sum of its days. Changing the
  totals mid-week re-spreads them over **today and later chosen days only**. Past days and anything marked Done
  are kept.
- **"Move to tomorrow"** takes the unfinished amount off today and adds it to the next chosen day. The week's
  total stays the same.
- **A plan made mid-week** spreads only over today and later chosen days. Earlier days show what was done, with
  no plan against it, so a day that already passed never shows as unmet.
- **The look-back after a week with no goals** ("Not this week", or an old-style plan) shows what was done,
  counted up, with no planned column, then goes into planning. The new week is pre-filled from the most recent
  week that had goals, or left blank if there has never been one.

## Goals
- Set the week in under two minutes on Sunday.
- Let the person see today's plan at a glance, with applications and contacts counted automatically.
- Make looking back feel like credit for the week and a fresh start, and make planning the next week one tap away.

## Non-goals
- No reminders, pushes or nags, and no streaks, comparisons or percentages as headlines (VOICE rules 7 and 10).
- The plan doesn't change the daily run. The agent ranks and prepares roles by fit, never to hit the plan's
  number (VOICE "fit before volume").
- It doesn't change the work-search count or the state minimum, which stay as they are (rule 11).
- No calendar sync and no hour-by-hour time blocking in this version.
- No multi-account work (one account, per the standing decision).

## Anti-goals: it fails if
- a short day reads as failure: red, "missed", "behind", "0/5" as the headline, or a catch-up list;
- it pushes volume over fit;
- it nags.

## Constraints
- Python and FastAPI with Jinja templates, as the app is now.
- Store the plan in `pal_notes` (`plan:<week>`), extending the JSON with `goals`, `per_day` and `note`. Old plans
  without these fields must still read and show as they do today.
- Prep and learning "Done" entries need a small store, either a table or `pal_notes` keys per day. This is the
  builder's choice, using `coach.ensure` for the schema.
- Weeks run Sunday to Saturday (`stats.week_start`).
- All new copy goes into the VOICE.md phrase bank first, then into the code. No emojis, and no research
  figures in copy.
- Works at phone width.
- Tests go in `tests/` next to the existing coach and stats tests.
- Documentation per the monorepo CLAUDE.md:
  - a Docmost change log entry and a feature page;
  - README, VOICE.md and `docs/` screenshots where they show the plan card;
  - a brainPal overlay update and rescan.

## Left to the builder
- The exact routes: extend `/plan`, and add something like `/plan/day` for Done, adjust and "Move to tomorrow".
- How the spread is stored. Store the spread itself, rather than recomputing it, once the person edits a day.
- The exact graphic forms (ring versus bar) and the animation timings, within the rules above.
- How the brief's Sunday line is worded, through the phrase bank.
