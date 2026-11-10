Today's job search, step 1 of the daily run: pick the roles worth applying to. Follow AGENTS.md.
Be brief and economical: this step should take a few minutes, not an hour. Don't open files you don't need.

Already done before you started: email sync and `autoapply find` (new roles from watched boards and job sites).

1. `autoapply list --limits` gives `picks_per_day` (N). If N is 0, write `[]` to data/daily/picks.json and stop.
2. `autoapply candidates` lists the best new roles, pre-ranked by a cheap score, with trimmed descriptions.
   Work from this list. Use `autoapply show <id>` only for a close call.
3. `autoapply alerts` gives yesterday's job-alert emails (LinkedIn, Indeed, HigherEdJobs...). Pull out only roles
   that clearly fit. For each, find the same posting on the company's own careers page (ATS URL); if it's gone
   there, skip it. Track live ones with `autoapply add <ats url> --company <name> --title <title>`.
   Feed roles (ats "feed") you want to pick need the same hop to the real posting first.
{{DISCOVER}}
4. Pick the best N by fit (against materials/ and CLAUDE.local.md), then freshness, then pay; at most one role per company.
   Levels: when config.yaml lists `search.levels`, every level there is equally wanted. A mid-level title ("Data
   Engineer", no Senior) is not a weaker fit than a senior one, and a lower posted range alone is no reason to skip it.
   Fit decides, never the weekly work-search number: don't pick a weak fit to make up a count. Fewer, better applications
   go further, and the person can log other activities (contacts, workshops) for the week. Skip anything
   already applied to (`autoapply list --status submitted`, materials/applications/). `autoapply skip <id> [<id> ...]
   --reason "..."` clears misses from the candidate list in one call (one reason per call).
5. Write data/daily/picks.json: [{"id": "<job id>", "why": "<one line on fit>"}], best first.
   Workday and other account-based sites can't be filled: still pick them if they're the best fit, and add
   "by_hand": true.
6. Print one line: the picks, e.g. "Picked: Acme (Sr Analytics Eng), Globex (Data Eng Mgr)", or "No good matches today".
