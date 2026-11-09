Today's job search, one application: {{JOB_ID}}. Follow AGENTS.md (read CLAUDE.local.md and materials/context/*.md
first). Work only on this role.

1. `autoapply show {{JOB_ID}}` for the posting. If its ats is "feed", find the same role on the company's own careers
   page (ATS URL) and work from that; if it's gone there, print "<Company>: posting gone" and stop.
   `autoapply resume-outline` prints the base resume (headline, summary, skills, each experience block's bullets).
   Work from that; don't open the .docx or PDFs with python, `pdftotext` or `pdfinfo`.
2. Tailor the resume and write a cover letter: write data/applications/<company-slug>/docs.json, then run
   `autoapply build-docs <company-slug>`. It makes both .docx and .pdf files and prints their page counts.
   docs.json (leave out any part to keep the base as is):
   {"company": "<Company>",
    "resume": {"headline": "...", "summary": "...",
               "skills": [{"label": "...", "text": "..."}, ...],
               "experience": {"<heading from the outline>": ["bullet", ...], ...}},
    "cover_letter": {"to": "Hiring Team", "greeting": "Dear Hiring Team,", "paragraphs": ["...", ...]}}
   "skills" is the full list in order. Each "experience" list replaces that block's bullets ([] drops a group);
   role, company and date lines never change. If it prints "problems" (resume over 2 pages, cover letter over 1),
   shorten docs.json and run it again. Don't write a python script to build the documents.
   Write the cover letter the way materials/context/voice.md asks when it's there (tone, length, opening, words to
   avoid, the person's own notes; sample letters set the voice only, never the facts).
   Also write notes.md (fit/gap table, pay ask, form answers, short screen prep). Keep it to what's true in materials/.
3. If the posting is on Workday or another site that needs an account, stop here: say "apply by hand" in notes.md.
4. `autoapply scan <apply url>` for the form's questions.
5. Write data/applications/<slug>/plan.json:
   {"url": "<apply url>", "ats": "<greenhouse|lever|ashby|...>",
    "files": {"resume": "<abs path to resume pdf>", "cover_letter": "<abs path to cover pdf>"},
    "answers": {"<question label exactly as scanned>": "<answer>", ...}}
   Answer every question the profile doesn't already cover, short and specific. Leave out consents and
   self-ID questions: the filler handles those from the person's own standing answers.
   Use the PDF paths `autoapply build-docs` printed.
6. `autoapply fill data/applications/<slug>/plan.json --job {{JOB_ID}}`. Its output ends with "checks_failed": the
   pre-submit checks (stale or over-long PDFs, missing job dates, placeholders, unanswered required questions).
   Fix what you can (edit docs.json and rerun build-docs, answer a question) and fill again (max 2 more tries).
   Consent and self-ID checks are the person's to settle: leave those.
7. Print one line, naming any check still failing: "<Company> (<title>): ready to review" or "<Company>: apply by hand" or what went wrong.
