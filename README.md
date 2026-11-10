# jobsearchPal

Your job search, and the unemployment paperwork that comes with it.

A self-hosted assistant for people looking for work, especially while collecting unemployment. It runs on a
small always-on computer you own and does two jobs:

- **The job search.** Every weekday morning an AI agent on your own subscription
  ([Claude Code](https://claude.com/claude-code) or OpenAI's [Codex CLI](https://github.com/openai/codex)) finds new
  roles, picks the best fits, tailors your resume and cover letter, and fills in the real application form, PDFs
  included. **It never presses Submit.** You review each application on a private dashboard and send it yourself.
- **The unemployment paperwork.** It keeps your state's work-search log as you go (every application, recruiter
  contact and interview, with the original emails and submit screenshots as proof), knows your state's weekly
  rule, and reminds you about claim day, RESEA meetings and other deadlines. Rules for all 50 states, DC,
  Puerto Rico and the US Virgin Islands are built in.

It reads your job email (read-only), files every reply, reminds you who to follow up with and drafts the reply,
and writes an interview prep pack when an interview comes in.

jobsearchPal is part of [palStack.io](https://palstack.io), a family of privacy-first tools built to make everyday
life a little easier. Like the other pals, it runs on your own computer: no tracking, no ads, nothing sold.

![Dashboard](docs/dashboard.png)

<details><summary>Work-search log, job sources, stats, emails, settings and the phone layout</summary>

![Work-search log](docs/work-search.png)
![Leads and job sources](docs/leads.png)
![Skills to learn](docs/skills.png)
![Stats](docs/stats-dark.png)
![Emails](docs/emails.png)
![Settings](docs/settings.png)
<img src="docs/dashboard-phone.png" width="300" alt="Dashboard on a phone">
</details>

The screenshots use fictional demo data (`scripts/demo-data.py`; regenerate them with `scripts/screenshots.py`).

## At a glance

- **Runs on its own.** Cron (or the Docker scheduler) starts the run at 6:30am on weekdays on your server.
  Your laptop, Claude desktop and any chat app can be closed; they're only for setup and fixes.
- **Prepares, never sends.** Each morning a few applications are tailored and filled in, follow-up replies
  are drafted, and a brief arrives by email. You read them on the dashboard and press Submit yourself.
- **Sounds like you.** Pick how your cover letters read (tone, opening, length, words to avoid), and rewrite
  any one letter with a short note.
- **Your AI, your order.** Pick the models on the Settings page: your Claude or ChatGPT subscription first,
  then pay-per-token sources (Jev, any OpenRouter model) or a local Ollama model as backups.
- **Your data stays with you.** Everything lives in one folder on your server, behind your own sign-in.
  Nothing is sent anywhere except to the models you turn on.

## How it works

```
6:30am weekdays (cron or the Docker scheduler) ─► scripts/daily.sh, in short steps:
  no AI:     autoapply sync-email (a small model sorts the emails) · autoapply find (boards, job sites)
  light model, one fresh session each (prompts/stages/):
    ├─ prep      interviews ─► prep pack: reported questions with sources, your stories
    ├─ drafts    follow-up reminders ─► drafted replies
    └─ rank      autoapply candidates (pre-ranked in Python) + alert emails ─► today's picks
  main model, one fresh session per pick:
    └─ apply     tailor resume + cover letter ─► autoapply scan ─► plan.json ─► autoapply fill (stops before Submit)
  ─► autoapply brief --send      morning email: what's ready, new replies, where everything stands
you ─► dashboard ─► check answers, decide consents ─► Submit
   or: autoapply-finish <job> on your laptop ─► a real Chrome window, filled in, you submit
```

### A morning, step by step

1. **Email first.** New mail from application systems and recruiters is gathered over read-only
   IMAP. Keyword rules only pick the candidates. A model then reads each one and files it as a
   confirmation, interview, rejection, offer, recruiter contact or not job-related, and matches it to
   the application it's about (see [Email sorting](#email-sorting)).
2. **Interview prep and follow-ups.** Any application with a new interview email gets a prep pack, and
   each [follow-up reminder](#follow-up-reminders) gets a drafted reply (see [Interview prep](#interview-prep)).
3. **Find roles** from the sources below. Anything already tracked or applied to is skipped.
4. **Rank and pick** the best one or two, and skip the clear misses with a reason (the Stats page
   shows why roles were skipped).
5. **Tailor** a resume and cover letter from your base resume and `CLAUDE.local.md`, plus a
   `notes.md` with the fit/gap table, form answers and pay ask. Letters follow **How your letters sound**
   (Settings, then Letters): tone, how a letter opens, length, words to never use, your own notes and letters you
   liked, each choice shown with a sample line first. It's saved to `materials/context/voice.md`.
6. **Fill the real form.** Playwright answers the questions, uploads both PDFs, takes a screenshot
   and stops before Submit. Consent and self-ID questions get only your own standing answers, highlighted for you to check.
7. **Brief.** One email (sent to yourself over Gmail SMTP) with what's ready, interview prep
   packs, new replies, your work-search count for the week, and the status of every application.
8. **You decide.** Open the dashboard, read the answers, tick the review box and press Submit, or
   finish on your laptop when a site wants a code. Then the confirmation email arrives and the next
   morning's sync files it.

### The pal

A job search is hard work, and jobsearchPal talks like a friend who knows it. It is honest about the market
and on your side, and it never promises an outcome. The rules and the phrase bank are in [VOICE.md](VOICE.md). They
draw on research about unemployment and job searching, kept in the palStack research library.

- **The morning.** The welcome fits how the search is going: someone wrote back, an interview, a quiet stretch, a
  Monday, the evening. Good news and roles ready to send come first. When it can, the welcome names what you
  actually did ("Yesterday you sent 3, and that counts").
- **Rejections.** When one comes in, the pal says so once and kindly ("one stone in a very big ocean"), then
  points to what's ready. Lists say "closed", and the count stays exact. A rejection is never sent as a phone
  push; the brief lists them together with "the closed ones need nothing from you".
- **The weekly minimum.** A quiet tracker that speaks only when you're short: "One more by Saturday covers this week."
- **The look.** Warm paper colours rather than clinical grey, a little morning light on the sidebar, and red kept for
  what is urgent: a benefits step due within two days (or overdue), or an appeal. Other dates, claim day included
  (a routine weekly step), are sunrise amber.
- **Celebrations.** The logo's sunrise grows into a horizon across the top of the dashboard. Each celebration
  plays once, and with Reduce Motion on you see the finished picture with no movement:
  - covering the week's minimum: light across the water
  - a new interview: the sun lifts with a ring of light
  - an offer: the full sunrise
  - your first application, then 10, 25, 50 and so on: a small note on what that took. Counted up, never a target
    or a streak, and only when the one that reached it went out this week.
- **The market, honestly.** On a quiet stretch, after a rejection, on a long search and once a month in the brief,
  one dated line about the market with its source. There are no figures in the copy. It comes from
  `autoapply/market.yaml`, which maintainers refresh after each monthly jobs report, and it hides itself after
  45 days.

### What helps a search

Beyond the tone, the pal offers a few things that research on job searching supports. Each one is optional, can
be put away for good, and sends no reminders. Nothing here counts visits or opens; the Stats page shows only counts
of what you did.

- **Your plan for the week.** A short card on the dashboard: which kinds of roles, which days, and one person to
  get in touch with. You write it; the dashboard and the morning brief show it back. "Not this week" is a fine answer.
- **People you know.** Every ready role has an *Anyone you know there?* link. People you get in touch with go on
  the Work search page and are listed in your log as networking contacts. They count toward your weekly number
  only if you turn that on, because not every state accepts networking.
- **Fit first.** The daily run ranks roles on fit, never on reaching the weekly number. Fewer, better
  applications go further, and contacts and workshops can cover the week.
- **Titles close to yours.** Skills lists job titles that keep showing up in the roles found for you and share
  words with your search. After eight weeks on three titles or fewer, the dashboard offers them too. One click adds
  a title to the search.
- **Before the hard days.** In the first weeks of a search, and again around week eight, a card says honestly what
  a long search looks like and what helps on a bad day. You can write your own "When a hard day comes, I will…",
  and the pal shows it back the next time a rejection arrives.
- **Fifteen minutes on what matters to you.** Early in a search and before a first interview, the pal offers a
  short private reflection: pick up to three values and write a few lines about one. Prep packs link to it too.
- **A gentle return.** After a week or more with nothing done, the dashboard says "Welcome back" and shows what's
  ready and one to-do. The rest stays folded away until you want it.

The dashboard shows at most one of these cards at a time, so the page never piles up.

### Where jobs come from

- **Company job boards you watch** (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) through
  their public APIs: the freshest source, and apply-ready. The run adds good companies as it finds
  them (`autoapply board add`), and on Mondays it looks for about 10 new ones.
- **Job sites with open APIs:** RemoteOK, Remotive, Hacker News "Who is hiring?", The Muse, Himalayas
  and Jobicy. No key needed.
- **Job sites with a free key:** Adzuna (a large US aggregator) and USAJOBS (federal jobs). Add the keys on
  the Setup page or in `.env`.
- **Any RSS or Atom job feed** (`rss_feeds` in `config.yaml`, or the Setup page): We Work Remotely, jobs.ac.uk and
  many others have them. Sites that answer automated requests with a bot check (HigherEdJobs does) are
  left to their job-alert emails; jobsearchPal doesn't try to get around those checks.
- **Job-alert emails** from LinkedIn, Indeed (including its job-match emails), HigherEdJobs (Job Agent emails), Built In,
  Glassdoor, Wellfound, ZipRecruiter and Dice. Every role in them is saved on the **Leads** page with its location,
  salary when given, source and a rough fit score. After each email sync the top leads are looked up on the
  company's own job board (no AI) and join the roles the daily run can tailor; star others and the next run
  searches the web for them. Parsing is plain Python, from the "View job" blocks these emails use.

**See every source in one place.** The Leads page opens with *Where your jobs come from*: the sources finding
jobs now (with how many roles each brought in), the ones that need a step (a missing key, Gmail not connected),
and everything not on yet in one line. **See list** shows every company you watch, with a filter. The dashboard
nudges you when fewer than half are on.

Each run saves what every source returned to `data/sources.json`; the Setup page shows the counts, and a
source that failed, next to its name.

**LinkedIn** is covered only through its alert emails. LinkedIn has no public jobs API, and
scraping it or signing in as you breaks its terms and risks your account. To widen what the run
sees, set up several daily alerts with tight filters in LinkedIn (Jobs → set alert), for example
"analytics engineer · Remote · United States · past 24 hours" or "staff data engineer · Boston ·
Hybrid". Send them to the inbox the sync reads. Each alert you add shows up in the next morning's run.

How LinkedIn roles flow through a run:

1. The run reads the alert emails (from `jobalerts-noreply@linkedin.com` and `jobs-noreply@linkedin.com`)
   in the inbox the sync uses.
2. It lists the roles in them that fit your interests.
3. For each good one it looks up the same posting on the company's own careers page (Greenhouse, Lever,
   Ashby and so on) and prepares the application there. Roles it couldn't match to a company page yet
   are listed in the brief as runners-up "from LinkedIn alerts (need ATS links)".

### Email sorting

**What each status means.** Every job email is filed as one of these, and the application takes the
latest one:

| Status | Means | Example |
|---|---|---|
| Received | the company got your application; you're still waiting | "Thank you for applying to …" auto-replies |
| Interview | a person asked to schedule a call or interview | a scheduling link, "are you free Tuesday?" |
| Closed | they said no, including "the position has been filled" | "we've decided to move forward with other candidates" |
| Offer | an offer | |
| Recruiter | a real person reaching out about a role | an agency or in-house recruiter's email |
| Unemployment agency | mail from your state's unemployment office | a RESEA appointment, a claim notice |
| Not job-related | alerts, newsletters, account and bank email | job-alert digests, sign-in links, statements |

An application with no reply beyond the automatic one for 30 days shows as **No reply yet**.

**A good order on the Settings page.** Sources are tried top to bottom, so put what you already pay for
first and pay-per-token last:

1. **Claude subscription** (Haiku is plenty for sorting) or **ChatGPT subscription** (Codex CLI). No extra cost.
2. **Jev** (needs an OpenRouter key): a classifier that returns a label with a probability. Anything below
   the minimum confidence moves on.
3. **OpenRouter**, any cheap chat model (for example `google/gemini-2.5-flash-lite`), for what's left.
4. **Ollama** if you run one, so nothing leaves the server.

Whatever no source is sure about waits for you on the Emails page.


- **Sources, in your order.** On the Settings page, turn on any of: your **Claude subscription**
  (Claude Code, run with no tools), your **ChatGPT subscription** (Codex CLI, read-only sandbox),
  **Jev** (TypeSafe's decision model on OpenRouter, which returns a label with a probability),
  any **OpenRouter** chat model, or a local **Ollama** model. Each email goes to the first source.
  If that source fails, or Jev is below your confidence threshold, the email goes to the next.
- **Only labels come back.** Email text is treated as data. Answers that aren't a known category or
  a known application are dropped.
- **Nothing counts until it's sorted.** Stats, outcomes, the brief and the work-search log use sorted
  emails only. Anything no source could sort waits on the **Emails** page.
- **You have the last word.** The Emails page lists every job email by tab (Not sorted, Replies,
  Recruiters, Not job-related, All), with the text, the keyword guess and who sorted it. Change the
  category or the application from a dropdown. Your choice survives rescans and later model runs.

### Interview prep

When an email is sorted as an interview, the next morning's run writes a prep pack for that company
and stage (recruiter screen, hiring manager, technical, onsite). It's shown on the dashboard's
**Interviews** card and in the morning brief, and you can print it.

- **What candidates report:** the interview process and questions others have shared for that company
  and role, from public pages only (Glassdoor and Indeed pages readable without signing in, Reddit,
  Blind, levels.fyi, the company's own blog and handbook). Every item links its source, and the pack
  says so when little is public instead of making questions up.
- **Likely questions** drawn from the posting, labeled as such.
- **Your stories:** STAR answers built only from your materials, with your real numbers.
- **About them**, **questions to ask**, and **pay** (your ask and the posted range).

When a later interview email arrives (the next stage), the pack is updated for it.
`autoapply list --prep` shows what's due.

### Follow-up reminders

The dashboard's **To do** card and the morning brief remind you when:

- a recruiter wrote and you haven't replied (after a day),
- you wrote last and a recruiter has gone quiet (after 5 days): check in,
- an interview invite is waiting for your answer, or a booking link for your time,
- an application has had no answer beyond the confirmation for two weeks: a short follow-up note, or let it go.

"Replied" is read from your Sent mail (headers only, read-only). The daily run drafts a short reply for
each one, from your materials only. **Reply in Gmail** opens a compose window with the draft filled in, and you
send it yourself. Each reminder has **Done** and **Snooze 3 days**. `autoapply list --nudges` shows what
needs a draft.

### Costs and limits

Everything runs on what you already pay for, plus optional pay-per-token sources, and the Settings
page shows both:

- **Daily caps:** roles to tailor per day (the heaviest step), interview prep packs per day and follow-up
  drafts per day, each of which can be switched off. The daily run reads them first (`autoapply list --limits`).
- **Monthly budget for paid APIs:** once Jev and OpenRouter have billed that much this month (sorting and,
  if it runs on OpenRouter, the daily run), sorting uses only your subscriptions and local models and a
  daily run on OpenRouter is skipped until the 1st.
- **Usage, last 30 days:** daily runs and tokens, what that would cost at API prices (a gauge of how heavy
  each step is, since your subscription covers it), and what OpenRouter actually billed, by day.

**Why the run is split into steps.** An agent session re-reads its whole conversation on every turn, so one
long morning session gets heavier with each step (one run used about 6.8M tokens, mostly these re-reads).
Each step now starts fresh, roles are pre-ranked in Python so the agent reads only the top 12 with trimmed
descriptions, and the light steps use a lighter model. Costs & limits shows tokens per step.

**Quick pick.** With an OpenRouter key, set *Quick pick* on Settings > Daily run to any cheap model
(e.g. `google/gemini-2.5-flash`). The day's roles are then picked in one chat call, usually well under a cent,
instead of an agent session. The same model reads yesterday's job-alert emails (LinkedIn, Indeed, HigherEdJobs)
and lists the roles that fit; a short light-model agent step then looks up only those on the company's own site.
It picks only among tracked roles, and falls back to the agent if a reply is bad or on the weekly discovery day. Tailoring and form
filling stay with the agent and its main model, since they need many tool turns and good writing.

To spend less: choose Sonnet or Haiku for the daily run, tailor one role a day, and keep email sorting on
Haiku or a local model.

**Skill matching (optional, off by default).** The built-in ranking only counts words your resume shares with a
posting, so "Looker" and "LookML" or "BI" and "business intelligence" never meet. Turn on skill matching
(Settings > Daily run) and a model reads each new role's must-have and nice-to-have skills and checks them against
your own editable skills list (with synonyms; it can draft the list from your resume once). Roles that need what you
have rank higher, and the dashboard shows "4 of 5 must-haves · missing Looker". It costs tokens on every role it
reads, and the Settings page says how many before you turn it on. Measured: 8 roles in one call took about 26,000
tokens through Claude Code (most of it Claude Code's own overhead); a small OpenRouter model reads 25 roles a day for
roughly 10 cents a month.

### Settings page

Four tabs. The menu's Settings item opens **Setup** first, with a badge while a required step is missing.

| Tab | What you set |
|---|---|
| Setup | resume, contact details, job interests and job sites, notes about you, how your letters sound (the Letters page), agent sign-in, Gmail (see Docker below). |
| Email sorting | which sources are on, their order (↑ ↓), the model for each (OpenRouter's list comes with live prices), Jev's minimum confidence, the Ollama address. Each source has a **Test** button that sorts a sample email and shows the answer, time and cost, plus 30-day counts of emails sorted, cost and failures. |
| Email sorting: OpenRouter key | for Jev and OpenRouter. It's stored in `data/secrets.json` (owner-only) and never shown again. A key in `.env` wins. |
| Costs and limits | daily caps for tailoring, prep packs and drafts; the monthly budget for paid APIs; 30-day usage and cost by day. |
| Daily run | the agent (Claude Code or Codex CLI, with what's installed and signed in), what pays for its model (your subscription, or an OpenRouter key billed per token), and the model. Opus writes the best cover letters; Sonnet or Haiku go easier on usage limits. |

Choices are saved in `data/settings.json`. Nothing on the page needs a restart.

### Dashboard pages

- **Dashboard:** what's **ready to submit** and a **shortlist** of today's best untailored matches (Prepare or
  Decline, with a reason), your work-search count for the week, a to-do list (replies owed, follow-ups, claim day,
  RESEA and other deadlines), interviews with their prep packs, latest replies, recruiters, applications per week
  and the full application list. **Run now** starts another batch any time.
- **Your applications** (bottom of the Dashboard) are the tracker, kept in the local database: no spreadsheet or
  Google account needed. **Log one you sent elsewhere** adds an application you made on LinkedIn, a company site or
  by email, so it counts toward your week and is never offered again. **Bring in your old tracker** imports a CSV
  (Google Sheets: File, Download, CSV; Excel: Save As CSV), finding columns by name. **Download CSV** gives you the
  whole list back, and it imports cleanly again. The same role is only ever kept once, however it arrives.
- **Leads:** every role from your job-alert emails, plus *Where your jobs come from* (see above).
- **Review page:** the filled answers, your tailored documents and a screenshot of the form. Pre-submit checks
  (documents present and current, required answers filled, consents confirmed) keep Submit locked until they pass.
  **Rewrite this letter** on the Cover letter tab takes a note ("warmer and shorter"), rewrites only that letter
  in the background, and fills the form again; it uses AI credit and never submits. Tick *Keep this for every letter*
  to add the note to how all your letters sound.
- **Stats:** response and interview rates, median time to reply, funnels, results by application
  platform, reply-time buckets, weeks at your work-search minimum, and pipeline trends. *Beyond applications*
  counts the weeks you wrote a plan, the people you got in touch with (and interviews at their companies), and
  your reflections.
- **Skills:** what the roles you matched keep asking for that you don't show yet, most asked first, with the
  roles that ask and a link to each skill's own docs or free course. With Skill matching on, it uses the model's
  must-have and nice-to-have list for each role it read (nothing is read twice); otherwise a fixed list of about 80
  skills matched against the descriptions, at no cost. Gaps in the tailoring notes' fit/gap tables count double.
  Mark a skill **I have this** (it joins your skills list), **Learning**, or **Hide**. It also points to free WIOA
  training through your state's career center.
- **Emails:** see above.
- **Settings:** Setup, Email sorting, Daily run, and Costs & limits tabs (above).
- **Work search:** see [Unemployment help](#unemployment-help). It also holds *People you've been in touch with*.
- **Reflection** (`/reflect`): the fifteen-minute values reflection, and what you wrote before.

Light and dark mode, and it works on a phone.

## FAQ

**Does it apply to jobs for me?** It finds roles, tailors your resume and cover letter, and fills in the
real form, then stops. You press Submit on the dashboard, or with `autoapply-finish` on your laptop when
the site shows a captcha or sends a verification code.

**Does my computer, or Claude desktop, need to be on?** No. The daily run is started by cron (or the
Docker scheduler) on the server and runs the agent CLI there, headless. Your laptop is only needed for
`autoapply-finish`.

**Does it watch LinkedIn?** Through your LinkedIn job-alert emails only (see
[Where jobs come from](#where-jobs-come-from)). Add more alerts with tight filters to widen it.

**Which AI does it use, and what does it cost?** Whatever you turn on in Settings: your Claude or ChatGPT
subscription covers the daily run and email sorting at no extra cost (it does count toward your plan's
usage limits). Jev, OpenRouter models and a monthly budget cap are optional.

**How do I make the cover letters sound more like me?** Settings, then **How your letters sound**: pick a
tone, an opening and a length (each shows an example), list words to never use, and paste a letter you liked.
**Show these with my resume** writes the examples once from your own resume, for your latest application (one
small AI call, saved; only facts from your resume), so you see each style with your own work.
To fix one letter, open the application and use **Rewrite this letter** on its Cover letter tab.

**Submit is greyed out.** Something in *Fix before you submit* needs you: usually a required question, a
consent, or a document check. Answer it and press **Save and refill**. Optional questions can stay blank.

**Will it apply to the same job twice?** No. A role you applied to, or filled a form for, is never offered again,
whether the run found it, you logged it by hand, or it came in from your old tracker. The same role is matched by
company and title (so "Sigma Computing, Inc." and a job board's "sigmacomputing" are one company) or by the posting
link. Other roles at a company you applied to come back after 90 days (`reapply_after_days` in `data/settings.json`;
0 keeps the whole company off for good).

**Do I still need my Google Sheet?** No. Import it once with **Bring in your old tracker** on the Dashboard, then log
anything you send outside the tool with **Log one you sent elsewhere**. **Download CSV** gives you a spreadsheet
copy whenever you want one.

**A reply was filed wrong.** Change it on the Emails page. Your choice is kept through later syncs and
`sync-email --rebuild`.

**How do I update?** `git pull`, then restart the dashboard (see Setup or Docker below). Your
`config.yaml`, `profile.yaml`, `.env`, `CLAUDE.local.md`, `materials/` and `data/` are gitignored, so an update
never touches them.

## Unemployment help

Pick your state on the Setup page and the **Work search** page becomes your unemployment desk:

- **This week at a glance:** activities so far against your state's weekly minimum, days left until Saturday,
  your next deadline, and a one-click download of the week's proof.
- **Your state's rule, in plain English:** the weekly number and what counts, how it's reported, required job-bank
  registration, how long to keep records, common exemptions, the waiting week, how much part-time pay is allowed,
  and the weekly benefit range and maximum weeks. Each of the 53 entries in
  [`autoapply/work_search_states.yaml`](autoapply/work_search_states.yaml) was checked against the state agency's
  own site and links to it, with the date it was checked and a confidence level. Rules change: the notice your
  state sends you always wins, and corrections are welcome as pull requests.
- **The log itself:** applications, recruiter contacts, interviews and RESEA meetings grouped by Sunday-to-Saturday
  week, in a work-search log's columns, with the original emails and submit screenshots saved as proof. Each week
  downloads as a zip with a CSV.
- **Your claim:** enter the start date, weekly benefit and weeks allowed from your monetary determination letter to
  see the weeks and money left, and get a claim-day reminder.
- **RESEA and deadlines:** if you're selected for RESEA (Reemployment Services and Eligibility Assessment), add its
  steps in one click and put in the dates from your notice; they show on the dashboard's To do with a countdown,
  next to any other deadline you add. Letters from your state's agency are filed separately so you don't miss them.
- **Good to know:** the things people learn too late (benefits are taxable, keep filing during the waiting week,
  severance can delay benefits) and help people often miss (health coverage, SNAP, 211, your career center, free
  legal help).

## What it will not do

- **Submit for you.** The CLI has no submit command. The only Submit button is on the dashboard,
  behind a review tick box, and each approval covers one click.
- **Answer consents or self-ID questions.** Privacy acknowledgements, AI-policy consents and
  demographic questions are never answered by the agent (`hold_for_review` in `profile.yaml`). You can
  save your own standing answers on Settings > Setup; the filler pre-fills those, and the review page shows
  them in a highlighted **Check these** box so you confirm them on every application.
- **Get past bot checks.** No captcha solving, no reading verification codes, no logins, no
  account creation. When a site asks for a code, use `autoapply-finish` and enter it yourself.
- **Workday and other account-based sites.** Materials are prepared and the role is flagged
  "apply by hand".

`AGENTS.md` gives the agent these rules (Codex reads it directly; `CLAUDE.md` imports it). With Claude
Code, `.claude/settings.json` also blocks edits to the tool's own code; Codex runs with writes limited to
this folder, so for it that rule is an instruction only. Either way these are guardrails, not a sandbox:
the review step is the real safety net.

## Permissions: what you hand over

Know what each piece can reach before you turn it on.

**The daily agent (Claude Code).** It runs unattended with `--permission-mode acceptEdits`, so it can
create and edit files in this folder without asking. Commands it may run come from the `allow` list in
`.claude/settings.json`: the `autoapply` steps it needs, `soffice` for PDFs, `python3` (used to build the
tailored .docx), `mkdir`, `ls` and `cat`, plus web search and fetch for company research. Anything
else stops the step, and the dashboard shows that step as failed. The `deny` list blocks
`autoapply serve`, `sqlite3`, and edits to `autoapply/` and `.claude/`. Be aware that `python3:*` is broad: Python
can do whatever your user account can. If that's too much for you, run it in Docker or as a separate
low-privilege user.

**The daily agent (Codex).** Runs with `--sandbox workspace-write`, network on and no approval prompts:
writes are limited to this folder, but there is no command allow list.

**Gmail (app password, optional).** An app password grants full IMAP and SMTP access to the mailbox,
the same as your password, minus the 2-step check. jobsearchPal uses it to read job emails in All Mail, Spam and Trash (each opened read-only,
messages fetched with `BODY.PEEK` so they stay unread) and to send you the morning brief. It never
sends anything else, never deletes and never marks as read. It is stored in `.env` or `data/secrets.json`
(owner-only). It also reads the headers (not bodies) of mail you sent, to tell when you've replied. A separate
job-search Gmail limits what the password can reach. To cut it off, revoke it at myaccount.google.com/apppasswords.

**OpenRouter key (optional).** Pay per token. Email sorting and Quick pick stop for the month at
the budget on Settings > Costs & limits; set a credit limit on the key itself too.

**The dashboard.** It shows your applications, emails and answers. It listens on `127.0.0.1` unless you
set `BIND`. Sign-in is always on: the first page of a new install is **Create your account** (the email for
your job search and a password of at least 10 characters), and every page after that needs it. The password is
kept as a salted scrypt hash in `data/account.json` (owner-only); a sign-in lasts 30 days in a signed cookie.
Five wrong tries from one address make it wait a few minutes. Forgot it: run `autoapply reset-password` on the
server (Docker: `docker compose exec web autoapply reset-password`), which also signs every browser out. There
is no password-change screen. The cookie isn't marked Secure because the setup is plain http, so prefer a
private network such as Tailscale before you open it to your phone. `AUTOAPPLY_TOKEN` is now only the machine
key `autoapply finish` uses to fetch a filled form (`/bundle` and `/file`); it is made in `data/secrets.json`
when you create the account.

**What leaves your server.** Job emails, your resume and notes go to the model you pick (your Claude or
ChatGPT subscription, or OpenRouter/Jev if you turn them on); Ollama stays local. Postings are fetched from
public job boards. The form filler types your real name, email and files into the company's own form, and
nothing is sent until you press Submit.

**What stays on disk, unencrypted.** Resumes, tailored documents, answers, copies of job emails and form
screenshots live in `materials/` and `data/`. Keep the folder private and back it up.

**Adding a step?** If a prompt uses a new `autoapply` command, add it to the `allow` list. A test
(`tests/test_daily.py`) fails if a prompt uses a command the agent isn't allowed to run.

## Setup (about 30 minutes)

You need an always-on Linux box (Ubuntu 24.04 tested), **either** a Claude subscription (Pro or Max,
for Claude Code) **or** a ChatGPT subscription (Plus or Pro, for the Codex CLI), and ideally
[Tailscale](https://tailscale.com) so the dashboard is reachable only from your devices. Email sorting
can also use an OpenRouter key or a local Ollama model.

| You have | Daily run | Email sorting |
|---|---|---|
| Claude subscription | Claude Code | Claude (Haiku) |
| ChatGPT subscription | Codex CLI | Codex |
| Either, plus an OpenRouter key | as above | Jev or any OpenRouter model first, the subscription as backup |
| Either, plus a GPU or spare CPU | as above | a local Ollama model, nothing leaves the server |
| Only an OpenRouter key | Claude Code (Anthropic models) or Codex CLI (most models) on the key | Jev or any OpenRouter model |

The OpenRouter route for the daily run follows OpenRouter's own guides: Claude Code talks to its
Anthropic-compatible endpoint, and Codex uses it as a custom provider. Each run's real cost is read from
the key's usage before and after, and the run is skipped once the month's budget is reached.

1. Clone this repo to `~/auto-apply` on the server and run `bash scripts/install.sh`
   (`AGENT=codex bash scripts/install.sh` for Codex).
2. Start the dashboard (`autoapply serve`) and use its **Setup** page (see Docker below for the steps), or
   copy the examples and fill them in:
   - `config.example.yaml` → `config.yaml` (boards to watch, title keywords, dashboard host,
     work-search label and weekly minimum)
   - `profile.example.yaml` → `profile.yaml` (your contact details and standard answers)
   - `.env.example` → `.env` (`REVIEW_URL`, Gmail app password)
3. Put your files in `materials/` (see `materials/README.md`), and write `CLAUDE.local.md` with
   personal facts the agent should use (the same file works for Codex): work authorization, titles and dates, pay asks, location
   preferences, how to name files. Both are gitignored.
4. Sign in once: `claude` in the folder (sign in and trust it), or `codex login`.
5. `pytest` to check the form filler, then `bash scripts/daily.sh` for a first run.
6. Start the dashboard as a service and schedule the daily run:
   ```
   cp scripts/autoapply-review.service ~/.config/systemd/user/
   systemctl --user enable --now autoapply-review
   sudo loginctl enable-linger $USER
   crontab -e   # add the line from the top of scripts/daily.sh
   ```
7. Open `REVIEW_URL`, create your account (email and password), and sign in on each device. On the **Settings**
   page, pick the daily-run agent and model and the email-sorting order.
8. Optional, on your laptop: `bash scripts/mac-setup.sh <ssh-host>` installs `autoapply-finish`.

Updating later: `git pull && .venv/bin/pip install -e . && systemctl --user restart autoapply-review`.

## Docker (alternative to steps 1, 4 and 6)

One image has Python, Playwright's Chromium, LibreOffice and both agent CLIs, so nothing else gets
installed on the host. Your files stay in the repo folder, which is mounted into the containers.

```
git clone https://github.com/harung1993/jobsearchPal.git ~/auto-apply && cd ~/auto-apply
docker compose up -d --build                # dashboard + the daily scheduler
docker compose run --rm web claude          # sign in to Claude Code and trust /app (or: codex login)
```

Then open `http://localhost:8787/` (or `http://<server>:8787/` with `BIND` set, below). A fresh install opens
**Create your account** (email and password; sign-in is required from then on), then the **Setup** page,
which walks through everything in a browser:

1. **Base resume**: upload your .docx (a PDF is made for you). Tailored resumes are built from it.
2. **Contact details and standard answers** (prefilled from the resume), saved to `profile.yaml`.
3. **Job interests**: titles to look for and skip, US-only, the levels you want (entry, mid, senior, lead,
   manager: read from the title, so "Data Engineer" is mid-level), companies to watch (paste careers-page URLs from
   Greenhouse, Lever, Ashby, Workable or SmartRecruiters) and job sites, saved to `config.yaml`.
4. **About you** (optional, recommended): roles and level, pay ask, where you'll work, work authorization,
   what to emphasize and avoid, saved to `materials/context/setup.md`.
5. **Agent sign-in**: the command above; the page shows when it worked.
6. **Gmail** (optional): an app password, tested before it's saved, for job alerts, replies and the brief.

![Setup](docs/setup.png)

Until steps 2 and 3 are done, the daily run does nothing. The Setup page writes the same files you could edit
by hand, so either way works; keys it saves go to `data/secrets.json` (owner-only), and `.env` wins over them.

- **Dashboard:** port 8787 on `127.0.0.1` by default. Add `BIND=<your Tailscale IP>` to `.env` to
  reach it from your phone.
- **Schedule:** `DAILY_AT=06:30`, `DAILY_DAYS=1-5` and `TZ=America/New_York` in `.env` (these are
  the defaults). Output goes to `data/cron.log` as before.
- **Your user id:** the containers run as uid 1000 so files in the folder stay yours. If `id -u`
  says otherwise, add `APP_UID` and `APP_GID` to `.env`.
- **Logins** live in the `agent-home` volume, so a rebuild keeps them.
- **Updating:** `git pull && docker compose restart`. Code runs from the mounted folder; rebuild
  (`docker compose up -d --build`) only when dependencies change.
- Codex sign-in on a headless box: sign in on a laptop and copy `~/.codex/auth.json` in with
  `docker compose cp ~/.codex/auth.json web:/home/app/.codex/auth.json`.

## Commands

```
autoapply find                         new matching roles from boards and feeds
autoapply board add ATS SLUG           watch another company's board (checked first)
autoapply alerts [--days N]            job-alert emails as text
autoapply sync-email [--days N] [--rebuild]   replies and recruiter emails → sorted → dashboard and proof
autoapply review-emails                sort emails still waiting, through the Settings page's sources
autoapply emails [--pending]           filed emails as JSON;  emails set ID KIND  settles one by hand
autoapply import-history FILE          load past applications from your old tracker (.csv or JSON rows)
autoapply export-applications          every application as CSV
autoapply add URL / list / show ID / skip ID
autoapply list --prep                  interviews that need a prep pack
autoapply list --nudges / --limits     follow-ups that need a draft; today's caps
autoapply scan URL                     a form's questions as JSON
autoapply fill PLAN.json [--job ID]    fill, upload, screenshot, stop before Submit
autoapply brief [--send]               the morning summary
autoapply daily-agent                  the agent and model the daily run will use
autoapply serve                        the dashboard
autoapply finish JOB_ID                (laptop) open the filled form in Chrome for you to submit
autoapply reset-password [--email E]   forgot the dashboard password: set a new one (signs every browser out)
autoapply pal-line                     the pal's one line for the phone push
```

## Layout

```
autoapply/cli.py         the commands the agent calls
autoapply/fillers/       scan.js reads any form; base.py fills and submits per ATS
autoapply/finder.py      job-board APIs and feeds
autoapply/emailsync.py   gathers candidate emails, proof copies, applies a settled kind
autoapply/classify.py    model review of waiting emails (Claude Code, Codex, Jev, OpenRouter, Ollama)
autoapply/prefs.py       Settings page choices (data/settings.json) and saved API keys
autoapply/prep.py        interview prep packs: what's due, where they live, safe rendering
autoapply/nudges.py      follow-up reminders from sorted emails and your Sent mail
autoapply/stats.py       dashboard and stats numbers
autoapply/pal.py         the pal's voice: greeting, celebrations, rejection note, market line
autoapply/coach.py       what helps a search: weekly plan, contacts, related titles, setback card, reflection, return
autoapply/voice.py       how your cover letters sound: the Letters page choices, samples, voice.md, recent letters
autoapply/web.py         dashboard, review page, work-search log
autoapply/templates/     HTML (no build step, no JavaScript framework)
prompts/stages/          the daily run's steps (rank, apply, prep, drafts, letter), one agent session each
AGENTS.md                standing rules for the agent (CLAUDE.md imports it; personal facts go in CLAUDE.local.md)
tests/                   local fixture forms and tests
```

## Development

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/playwright install chromium
.venv/bin/pytest
python3 scripts/demo-data.py /tmp/demo && cd /tmp/demo && autoapply serve   # http://127.0.0.1:8799
python3 scripts/screenshots.py                                              # refresh docs/*.png
```

The filler is tested against local copies of each ATS's form layout (`tests/fixtures/`). Real
forms change, so expect to tweak labels and selectors in `autoapply/fillers/`. Issues and pull
requests are welcome, especially new ATS fillers and better reply classification.

## Status and limits

jobsearchPal is young: it's used daily by its author and has been tested from a clean Docker install, but expect
rough edges. Known limits today:

- **You need a small always-on computer** (a home server, a mini PC, a cheap cloud VM) and are comfortable running a
  few terminal commands once. Day to day, everything happens in the browser.
- **Email is Gmail only** (an app password, read-only). Other providers are on the list.
- **US-focused.** Job filters lean US, and the unemployment rules cover US states and territories.
- **Some sites need you.** Workday and other account-based sites get materials prepared and are marked "apply by
  hand"; captchas and emailed codes are finished by you (`autoapply-finish` opens the filled form in Chrome).
- **AI usage is real.** A full morning run is roughly 1-2 million tokens on your subscription; caps and a monthly
  budget for paid APIs are on Settings > Costs & limits.

## Contributing

Issues and pull requests are welcome, especially: corrections to a state's rules (with the agency link), new ATS
form fillers, other email providers, and reply-sorting mistakes (share the subject and sender, never the body).
Please keep personal data out of issues, tests and screenshots; use `scripts/demo-data.py`.

## License

MIT. See [LICENSE](LICENSE).
