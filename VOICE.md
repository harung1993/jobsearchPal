# jobsearchPal voice

**How jobsearchPal talks, for every string: the dashboard, the morning email, phone pushes and every page.** Written 2026-11-08.
The rules come from a graded review of the research on unemployment and job searching (A is the strongest evidence, D the weakest),
done for palStack; the main sources are listed at the end. New copy goes into the phrase bank below first, then into the code. Most
lines live in `autoapply/pal.py`.

## The stance

**A pal who knows a job search is hard work, tells you honestly how the market is, and is on your side.** A long search tends to wear
people down rather than getting easier. Hiring is slow right now even though unemployment is low. Encouragement only helps when it
rests on what the person has actually done. So jobsearchPal:
- names the difficulty
- credits the effort
- points to one next thing
- never promises an outcome

**Ethics line:** we use a psychological lever only if the person would approve of it once it was explained.

## The rules

| # | Rule | Why (grade) | Say | Don't say |
|---|---|---|---|---|
| 1 | **Say it is hard, and that it is the situation.** | Unemployment wears on mental health and it doesn't fade with time (A, B); the market data (A) | "Quiet weeks are common right now; it says more about the market than about you." | "You'll get used to it." |
| 2 | **Encourage from the record, never the future.** | Expectations built on your record went with more offers; positive fantasies with fewer (B/C) | "Yesterday you sent 3, and that counts." / "You've had 4 interviews from this search, so employers do pick you out." | "Your dream job is out there." / "You'll land something soon." |
| 3 | **A no is one stone in the ocean.** It's not personal, not permanent, and comes with one thing in their control. | Callbacks are mostly screening (B); "it's never you" is untested and sometimes false | "It's one stone in a very big ocean: most no's come down to numbers and screening." | "It's not you, it's them." |
| 4 | **Good news and open doors first.** | The product's brief; looking should feel safe | "Good news first: Harbor AI wrote back about an interview." | A subject line that opens with a rejection |
| 5 | **Name what they did, specifically.** | Feedback aimed at the self can lower performance (B) | "Sent. That's one more door you knocked on." | "You're amazing!" |
| 6 | **Let a bad day be a bad day.** Rest is allowed. | Pressure to feel positive goes with more sadness (B) | "You've done enough for today. Everything here will still be waiting in the morning." | "Stay positive!" / "Look on the bright side." |
| 7 | **Count up.** No streaks, no comparisons, counts before percentages. | A broken streak lowers effort (B); comparison hurts (B); counts are read better than rates | "3 replies from 41 sent" | "Don't break your streak." / "People like you get..." / "Response rate 7%" as the headline |
| 8 | **The weekly minimum is a checklist, never a threat.** The state's notice wins. | Benefit rules frighten even people who comply (B) | "One more by Saturday covers this week." | "You'll lose your benefits." / "Only 1 more needed!" |
| 9 | **Market lines carry a source and a date, and no figures.** "Right now" must be true this month. | Official data (A); house rule | "Searches are taking longer for most people right now than a few years ago, and hiring has been slow this year." | "It takes 12 weeks to find a job." / "The market is terrible." |
| 10 | **Few messages; bad news batched.** A rejection is never a push. | Frequent bad-news contact harms (graded in the debt doc) | The brief: "The closed ones need nothing from you." | A push per rejection |
| 11 | **Honest numbers stay honest.** "Closed" is the real rejected count; work-search counts are never softened. | finPal rule 9 | "12 still in play · 5 closed" | Hiding a count |
| 12 | **Errors are ours, and kind, with a next step.** | House rule | "We couldn't save that. Try again in a moment." | "Failed." |

House rules: no emojis, one exclamation mark at most, "group" never "club", absolute dates in anything that is kept. "Research
suggests", never "science proves", and copy never quotes a research figure.

## Phrase bank

| Moment | Line |
|---|---|
| Morning, someone wrote back | "{Company} wrote back. Let's look at that first." |
| Morning, interview | "Good news first: {Company} wrote back about an interview." |
| Morning, after a rejection | "{Company} said no this time. Rejections sting, even when you expect them. It's one stone in a very big ocean: most no's come down to numbers and screening, and one doesn't decide the rest of your search." |
| Morning, quiet stretch | "No news is the hardest part of a search. What you've sent is still out there." |
| Monday | "New week. Last week's effort still counts." |
| Evening | "Searching is real work. It's fine to stop for today." |
| First run | "Starting a search is a lot. We'll take it one morning at a time." |
| Celebration, week covered | "That's this week covered. {n} activities logged for your {label}. The rest of the week is yours." |
| Celebration, interview | "{Company} wants to talk. You got their attention. A prep pack with likely questions and your best stories is on its way." |
| Celebration, offer | "An offer from {Company}. You did this. Every application, every follow-up and every hard morning led here. Take a breath before you decide." |
| After Submit | "Sent. That's one more door you knocked on." |
| Logged by hand | "Added {role} at {Company}. That's one more door you knocked on. It counts toward your week, and the daily run won't offer that role again." |
| First application | "Your first application is out. Starting is often the hardest part, and you've started." |
| Milestone (10, 25, 50...) | "{n} applications sent. Each one took reading, tailoring and deciding. That's {n} doors you knocked on." |
| A run didn't finish | "{Run} didn't finish {when}. That's on us, not you." |
| Empty: recruiters | "No recruiters yet. When one gets in touch, they show up here." |
| Create account | "Welcome. Let's set you up. Starting a search is a lot. We'll take it one morning at a time." |
| Credit | "Part of palStack.io" (small p, capital S), the palStack mark with "Part of" over "palStack.io": sidebar, sign-in, the footer of Settings and Setup, the brief's footer. Links to https://palstack.io. |
| Follow-up | "Applied 14 days ago · no reply yet. Following up is normal." |
| Empty: emails | "All sorted. Nothing needs you right now." |
| Empty: ready | "You're all caught up. The next daily run looks for more. Resting counts too." |
| Push, nothing new | "Nothing new to send today. Rest counts too." |
| Sign in | "Welcome back. Your search is right where you left it." |
| Back after a week away | "Welcome back. No catch-up list today: just what's ready, and one place to start." |
| Weekly plan | "Your week, in your words." / "No plan this week. That's fine." |
| Weekly goals, setting | "Your week, in your words. Set a few totals and pick your days; we'll spread them out. Change any day." |
| Today card | "Today" / "This week so far: {summary}." |
| Today card, a short day | "{n} {thing} today, and that counts." |
| Today card, rest day | "A rest day in your plan. Rest counts too." |
| Block met | "Done for today." |
| Day met | "That's today's plan done. The rest of the day is yours." |
| Week plan met | "Your plan for the week, done." / "You set it and you followed through." |
| Look-back, with a plan | "You had a plan and you worked to it: {summary}. Planning your week is one of the things that helps a search stay on track. Next week builds on this one." |
| Look-back, no plan | "Last week: {summary}. That all counts. A short plan for this week can help keep the days steady." |
| Look-back, nothing done | "A quiet week. That happens, and this one is a fresh start." |
| Look-back note | "What helped, or what got in the way?" (optional, just for you) |
| Morning email, Sunday | "Last week: {summary}. Plan this week: {url}/#plan" |
| Morning email, a planned day | "Today's plan: {today_line}" |
| People you know | "Anyone you know there?" / "One message this week is a good start." |
| Setback card, early | "Searches are long right now, and much of the time is quiet. That's the usual shape of a search, not a sign you're doing it wrong." |
| Setback card, week 8 | "Around now, a lot of searches start to feel long. That's common, and it isn't a verdict on you." |
| Rejection, with their plan | "You wrote this for a day like today: ..." |
| Values reflection | "Fifteen minutes on what matters to you. Some people find it steadying." |
| Related titles | "Looking a little wider can open more doors." |

## Motion

The logo's sunrise grown into a horizon (`templates/_horizon.html`):
- The sun's height follows the time of day.
- Three celebrations, each scaled to its size and played once per event:
  - **Week covered:** light spreads across the water.
  - **Interview:** the sun lifts with a ring of light.
  - **Offer:** the full sunrise.
- With Reduce Motion, the finished picture shows with no movement. No loop runs longer than 5 seconds, and every animation is finite.

## What helps a search (`autoapply/coach.py`)

The evidence on what moves outcomes, turned into optional features. None sends a reminder; each can be put away.
- **A plan the person writes** (Abel et al., B): roles, days, one contact. Reminders added nothing in the trial, so there are none.
- **Weekly goals** (Abel et al.; van Hooft et al. 2005; Jahoda, B/C): totals the person sets on Sunday (applications, and hours
  for reaching out, interview prep and learning), spread across the days they pick, counted up each day, and a Sunday look-back that
  flows into the next week. The week is the goal, so a short day is credit; mood and progress swing day to day (Wanberg, Zhu and
  van Hooft 2010). No streaks, no reminders, no red; the plan never changes the daily run or the work-search count (`autoapply/goals.py`).
- **People you know** (Granovetter; referral studies, B): contacts are logged and can count as work search.
- **Fit before volume** (van Hooft et al. 2021, A): the ranking prompts say fit decides, never the weekly number.
- **Related titles** for a narrow, long search (Belot, Kircher and Muller, B).
- **Setback preparation** early and around week 8 (the JOBS programme, A inside a workshop; untested alone).
- **A short values reflection** early and before a first interview (Pfrombeck et al. 2023, B; the effect faded by 8 weeks,
  so copy never promises it helps you get hired).
- **A gentle return** after time away: no catch-up list. "Away" is judged from what the person did, never from visits.

## Keeping it honest
- `autoapply/market.yaml` is refreshed monthly, after the jobs report and JOLTS. A line older than 45 days hides itself.
- Do not claim (the evidence doesn't support it): "people adapt to unemployment", "any job fixes it", "it takes N weeks",
  "N% of applications get a reply", "gaps don't matter right now", "more applications get you a better job", "telling people a
  rejection isn't personal helps them".

## Main sources

- Paul and Moser (2009), Journal of Vocational Behavior.
- Paul (2005), a meta-analysis of how distress changes with time out of work.
- Liu, Huang and Wang (2014), Psychological Bulletin.
- Vinokur et al. (2000), the JOBS programme follow-up, Journal of Occupational Health Psychology.
- van Hooft et al. (2021), Journal of Applied Psychology.
- Oettingen and Mayer (2002), Journal of Personality and Social Psychology.
- Kroft, Lange and Notowidigdo (2013), Quarterly Journal of Economics.
- Silverman and Barasch (2023), on broken streaks and later effort, Journal of Consumer Research.
- Kluger and DeNisi (1996), Psychological Bulletin.
- Ford et al. (2018) and Dejonckheere et al. (2017, 2022), on pressure to feel positive.
- Wright and Patrick (2019), on how benefit conditions are experienced.
- Granovetter (1973), American Journal of Sociology.
- Abel, Burger, Carranza and Piraino, on written job-search plans (working paper).
- van Hooft, Born, Taris, van der Flier and Blonk (2005), on implementation intentions in job search, Journal of Vocational Behavior.
- Wanberg, Zhu and van Hooft (2010), on day-to-day job search, Academy of Management Journal.
- Feather and Bond (1983), on time structure and purposeful activity out of work.
- Belot, Kircher and Muller, on suggesting related occupations, Review of Economic Studies.
- Pfrombeck et al. (2023), on self-affirmation and reemployment, PNAS.
- Market data: U.S. Bureau of Labor Statistics (Current Population Survey; Job Openings and Labor Turnover Survey).
