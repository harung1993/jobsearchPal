# Paste a job: design

Date: 2026-11-10. Status: decisions agreed with Harun 2026-11-10; awaiting his read of this document.

## Why

Harun finds jobs on LinkedIn (and elsewhere) that never reach jobsearchPal: they weren't in an alert email or on a
watched board. Today the only ways in are alert emails (Leads) and `autoapply add <url>` on the command line, and
neither takes a pasted job post. Example: the Liberty Mutual "Director I, Data Science - AI Products" LinkedIn page,
copied whole (nav bar, Premium ads, "More jobs" list and all), whose apply button goes off LinkedIn to Workday.

The aim: paste any job post, and the system takes care of everything needed for it, on one page per job.

## Goals

1. **Paste anything.** A box at the top of the Leads page takes a whole pasted post (LinkedIn page, company careers
   page, job email) or a bare link. It pulls out company, title, location, work setting (on-site, hybrid, remote) and
   the pay range, keeps the full job description, and drops the page clutter.
2. **One page per job, start to finish (Harun picked this: "option A").** Every lead gets a detail page. It begins as
   the post (header facts plus the cleaned description) and grows in place as work is done: fit check, tailored
   resume and cover letter, notes, and when a form was filled, the review and Submit section. The separate
   application page folds into it.
3. **Two ways to use it (Harun's ask).**
   - **Auto apply:** what the Leads button does today: tailored documents and notes, then the form filled for review.
     Never submits.
   - **Prep only:** just the AI help: tailored resume, cover letter and notes, then stop. The person applies wherever
     they like. Workday and other account-based sites only offer this (the agent already stops there; see
     `prompts/stages/apply.md` step 3) and the page says "apply by hand".
4. **A kit for applying by hand.** After a prep-only run the page shows: download buttons for the resume and cover
   letter (.pdf and .docx), the form answers each with a copy button (like the "Fill it in by hand" table on today's
   job page), the company's own application link if one was found, and an **I applied** button.
5. **I applied logs it.** It records the application in the tracker (`history.log`, as the existing
   `/applications/log` does), so it counts toward the weekly work search and the no-repeat rule, and the lead moves
   to Applied.

## Non-goals

- No browser extension or LinkedIn scraping. LinkedIn needs a login; the person pastes the text.
- No new submit path. Submit stays the person's action, exactly as today.
- No multi-user or tenancy work (standing decision: keep it single-account and simple).
- No change to how alert-email leads are found or ranked.

## Anti-goals (would make this a failure even if it works)

- Inventing facts: a tailored resume or notes that state skills, metrics or titles not in `materials/`. The pasted
  description is the job's facts only, never the person's.
- Applying to the same role twice. A pasted job already in the tracker or Leads must be caught, not duplicated.
- Losing the pasted description. If the company-site lookup fails, prep must still work from the paste.
- Clutter leaking in: LinkedIn sidebar jobs, "Premium" copy or the person's own name and messaging bar ending up
  in the description the agent tailors against.

## How it should behave

### Adding a job
- Paste goes into a textarea at the top of `/leads` ("Add a job"). On submit, the server reads out the fields and
  shows them **prefilled and editable** (company, title, location, work setting, pay, link) above the cleaned
  description, with Save. *(Claude's call: a confirm step instead of saving blind, because parsing free text will
  sometimes be wrong and the person can fix it in a second; it also means no model call is needed on paste.)*
- Parsing is plain Python, tuned for the LinkedIn layout first (company line, title line, "City, ST · ...",
  "$137K/yr - $257K/yr", "About the job" through the end of the description, stopping before "Set alert for
  similar jobs" / "About the company" / "More jobs"), then a generic fallback (first lines as title/company, any
  pay range found, everything else as description). *(Claude's call.)*
- A bare link: if it's an ATS the tool already knows (`finder.FETCHERS`: Greenhouse, Lever, Ashby, Workable,
  SmartRecruiters), fetch the posting with the existing code; otherwise (LinkedIn, Workday, unknown) ask the
  person to paste the post's text too. *(Claude's call.)*
- **Duplicates:** before saving, check the no-repeat rule (`rank.Applied.same_role`, `history.find`) and the lead
  key (`leads.key(company, title)`). Already applied: say so with the date and open the existing page; nothing is
  added. Already a lead: update it (fill in the description if it had none, add "pasted" to its sources) and open
  its page. Other roles at a company applied to within `reapply_after_days`: save, but show the existing
  company warning.
- Saved as a lead with source "pasted". The lead row needs the description and the work setting; today's
  `leads` table has no description column, so add one (ALTERed in, like `db.MIGRATIONS`).

### The lead page
- New route, e.g. `/lead/<key>`. Every lead on `/leads` links its title to it (today the title goes straight to the
  external link; that link moves onto the page).
- Header: company, title, location, work setting, pay, source(s), company-site link when known, "apply by hand"
  when the site needs an account.
- Before any run: the cleaned description (collapsible once documents exist), and the buttons Auto apply, Prep only,
  Star, Dismiss. While a run is going, show it as Leads does today ("A run is going ... See what it's doing").
- After a run, on the same page: fit check (from notes.md's fit/gap table), the files, the notes (pay ask, form
  answers with copy buttons, screen prep), and if a form was filled, today's whole review section from `job.html`
  (checks, consents and self-ID, unanswered, problems, Save and refill, Submit, captcha handoff, Rewrite this
  letter). Then I applied / Not applying.
- **Every job gets this page, lead or not (Harun, 2026-11-10).** Jobs from watched boards, the dashboard's
  "Ready for you" and shortlist, and "Prepare this one" have no lead row; they get the same page, Prep only and
  I applied too. So the page is keyed on the job with an optional lead: a lead that has no job yet (no run so
  far) shows the lead-only top half, and gains a job once a run creates or finds one. `/prepare/<id>` gets a
  prep-only variant and the dashboard a Prep only button next to Prepare. `/job/<id>` keeps working (old links,
  emails). Route names and the lead-to-job mapping are the builder's call.
- Prep only can be followed by Auto apply later without redoing the documents.

### The runs
- **Auto apply** on a pasted lead uses today's path (`AUTOAPPLY_LEAD` in `scripts/daily.sh`): find it on the
  company's own site, then the apply stage. Change: if the lookup fails, don't stop with "couldn't find that role";
  create the job from the pasted description (like `autoapply add`, id `manual:<hash>`, with the description,
  location and pay filled in) and run prep only, with a note on the page saying the form couldn't be found so it's
  apply by hand.
- **Prep only** is the apply stage told to stop after step 2 (documents and notes.md): e.g. a new env var
  `AUTOAPPLY_PREP_ONLY=1` read by `daily.sh` and passed into the stage prompt. It still tries the company-site
  lookup first (cheap, and gives the apply link) but works from the paste if that fails. *(Claude's call.)*
- The apply stage must tailor against the pasted description when the job has no fetched one.
- **Prep only still writes `plan.json`**, with the files and the answers but without filling and without
  `approved`. When the form can be reached without an account, it runs `autoapply scan` and answers the form's real
  questions. Otherwise (Workday and the like) it answers the usual questions (why this company, why this role,
  pay ask, start date, notice period, years of the key skill) in the same `answers` shape. The kit's copy-button
  table reads `plan.json` either way, and the server keeps finding the files through `plan["files"]` as it does
  today. *(Claude's call: one source for the page, no new notes.md format to parse.)*
- **Leads with no description** (most alert-email leads): Auto apply and Prep only are offered as today. If the
  company-site lookup fails and there's no description, the run doesn't tailor blind. The page says so and shows
  a paste box ("paste the post to prep from it"), which stores the description on that lead. Then Prep only works.
  *(Claude's call: protects the "never invent" anti-goal.)*

## Constraints

- **The edit guard.** The repo's `.claude/settings.json` denies Edit/Write on `autoapply/**` (it guards the daily-run
  agent), and AGENTS.md forbids the agent from editing `autoapply/`, `scripts/`, `prompts/`. Harun approved
  editing the tool's code for this feature (2026-11-10). Work in a separate git worktree (e.g. `../.wt/paste-a-job`
  on a `feat/` branch), where the repo guard doesn't apply to the session, and open a PR for review; the guard
  itself stays as it is.
- Hard rules from AGENTS.md stay true: never submit, never answer consents or self-ID, never invent metrics, no
  logins or account creation, agents fetch pages with WebFetch (the server itself may use Python HTTP, as `finder`
  does).
- One run at a time (`run_state()` lock); the page must handle "a run is already going".
- Stored links are http(s) only (`history._web`); pasted text is untrusted input and must be escaped when rendered.
- Single account; no tenancy scaffolding.
- Repo docs to update when built: README (adding a job), this repo's AGENTS.md if the prep-only stage contract
  changes; Docmost change log and brainPal per the monorepo rules.

## Left to the builder

- Exact template split (one template with includes vs. extending `job.html`), route names, and how `/job/<id>` maps
  to the lead page.
- Whether a prep-only job uses a new job status (e.g. `prepped`) or is inferred from files present. Whatever is
  chosen, a prepped-but-not-filled job must not show as "Ready to submit" on the dashboard.
- The parser's internals and test fixtures (use the Liberty Mutual paste as the first fixture; add a plain
  careers-page paste and a job-email paste).
- Visual layout within the existing design system (`base.html`, `macros.html`).
