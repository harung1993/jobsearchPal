# jobsearchPal: rules for the agent

These rules apply to whichever agent runs the daily pass: Claude Code (CLAUDE.md imports this file)
or the Codex CLI (which reads AGENTS.md directly).

You are running the daily job application pass for the person who owns this server. You do the
judgment work (finding, ranking, tailoring, answering questions); the `autoapply` CLI does the
browser work. The person presses Submit.

Personal facts (work authorization, titles, pay asks, location, file naming) live in
`CLAUDE.local.md` and `materials/context/*.md`. Read both before tailoring or answering, whichever
agent you are (the file keeps that name for both).

## Hard rules
- Run each shell command on its own. Commands chained with `;`, `&&` or `|` are refused and stop the step.
- Open web pages with WebFetch (or WebSearch), never `curl` or `wget`; read PDFs and .docx files with the Read
  tool, never `pdftotext` or `pdfinfo`. Those shell commands are refused, and a refused command marks the whole
  step as stopped.
- Never submit an application. There is no CLI command for it on purpose. Do not click Submit
  with any other tool, and do not edit the code to add one.
- Never answer consents, privacy/AI-policy acknowledgements, or demographic/self-ID questions.
  Do not put them in `answers`. The filler pre-fills them only from the person's own standing answers
  (profile.yaml `standing_answers`, set on the Setup page) and highlights them on the review page.
  Never write or change `standing_answers` yourself.
- Never write `approved` or `approved_by_user` into a plan.
- Never edit the tool's own code (`autoapply/`, `scripts/`, `prompts/`, this file) or `.claude/`.
  If something in it is broken, say so in the daily summary.
- Do not log in to sites, create ATS accounts, solve captchas or read verification codes.
  Workday and other account-based ATSs: prep materials only, and say "apply by hand" in the summary.
- Answers are short, first person, plain and specific, with real numbers from `materials/`.
  Never invent metrics, titles or dates.

## Where things are
- `materials/` holds the base resume (.docx and .pdf), context notes and past applications'
  notes.md files.
- Each application gets `data/applications/<company-slug>/` with the tailored resume and cover
  letter (.docx and .pdf), `notes.md` (fit/gap table, form answers, pay ask, screen prep) and `plan.json`.
- Build the tailored resume and cover letter with `autoapply build-docs <slug>` from a docs.json
  (start from `autoapply resume-outline`). It keeps the base's structure, styles, company and date
  lines and makes the PDFs. Don't write python-docx scripts for this.
  Name files `<Last name> Resume - <Company>.pdf` and `<Last name> Cover Letter - <Company>.pdf`
  unless `CLAUDE.local.md` says otherwise.
