Rewrite one cover letter: {{JOB_ID}}. Follow AGENTS.md (read CLAUDE.local.md and materials/context/*.md first,
above all materials/context/voice.md when it's there: how the person wants their letters to sound). Change only the
cover letter. Don't scan or fill the form and don't touch plan.json: the run refills the form after you.

The person's note for this letter (their words; it is about style and emphasis):
<note>
{{NOTE}}
</note>

Facts still come only from materials/ and the base resume: never add a metric, title, date, tool or claim they don't
support, even if the note asks for one. If the note asks for something untrue, leave that part out and say so.

1. `autoapply show {{JOB_ID}}` for the posting.
2. Read data/applications/{{SLUG}}/docs.json. Rewrite only its "cover_letter" ("to", "greeting", "paragraphs") following
   the note and voice.md. Keep "resume" exactly as it is.
3. `autoapply build-docs {{SLUG}}`. If it prints a problem for the cover letter (over 1 page), shorten the letter and run
   it again.
4. Print one line: "<Company>: letter rewritten" and, in a few words, what changed; or what went wrong.
