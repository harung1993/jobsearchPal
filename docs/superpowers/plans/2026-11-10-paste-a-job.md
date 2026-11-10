# Paste a Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Paste any job post into Leads, get one page per job that grows from the post to tailored files, notes and
form, with a Prep only mode for applying by hand.

**Architecture:** A plain-Python parser (`autoapply/paste.py`) turns pasted text into lead fields; leads gain a
description. A lead with no job shows on `/lead/<key>`; once a job exists, `/lead/<key>` redirects to `/job/<id>`,
which is the grown page for every job, lead or not. Prep only is the apply stage with `AUTOAPPLY_PREP_ONLY=1`; it ends
with `autoapply fill <plan> --job <id> --prep-only`, which stores the plan (files + answers) and sets the new job
status `prepped` without opening a browser.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite, bash (`scripts/daily.sh`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-paste-a-job-design.md`

## Global Constraints

- Never submit; never write `approved`/`approved_by_user`; never answer consents or self-ID (AGENTS.md hard rules).
- Stored links are http(s) only (`history._web`). Pasted text is untrusted: rendered escaped (Jinja autoescape), never `|safe`.
- No new agent permissions: the agent may only run commands already in `.claude/settings.json` (`autoapply fill:*` covers `--prep-only`); `tests/test_daily.py::test_every_command_the_prompts_use_is_allowed` must keep passing.
- In-app dialogs only: forms use `data-confirm*`; read actions with `getAttribute("action")` (base.html already does).
- No emojis in copy. Copy is plain, second person, short.
- Work in worktree `../.wt/paste-a-job` on branch `feat/paste-a-job`; stage named paths only; no Claude attribution in commits or PRs.

## Review Focus

1. A paste of a role already applied to → no new lead or job; the person sees "You applied ... on <date>" (Task 2 test).
2. A LinkedIn paste whose sidebar "More jobs" lists other titles/companies → none of them leak into title, company or description (Task 1 test).
3. A paste with no recognisable pay or location → saves with blanks, no crash (Task 1 test).
4. Auto apply on a pasted lead not on the company site → prepped from the paste, not "couldn't find" (Task 4 test on `leads from-paste`).
5. A prepped job → not in "Ready for you", not counted as applied by the no-repeat rule, and Auto apply still allowed on it (Task 3 test).

---

### Task 1: Paste parser

**Files:**
- Create: `autoapply/paste.py`
- Create: `tests/fixtures/paste_linkedin.txt` (the Liberty Mutual LinkedIn paste from the brainstorm, verbatim), `tests/fixtures/paste_careers.txt` (a short plain careers-page paste: title line, company line, "Location: Remote (US)", "Salary: $150,000 - $180,000", body)
- Test: `tests/test_paste.py`

**Interfaces:**
- Produces: `paste.read(text: str) -> dict` with keys `company, title, location, work_setting, pay, url, description` (all `str`, `""` when unknown). `work_setting` is one of `"on-site" | "hybrid" | "remote" | ""`.
- Produces: `paste.is_link(text: str) -> bool` (the whole paste is one http(s) URL).

- [ ] **Step 1: Write the failing tests**

```python
def test_linkedin_paste():
    r = paste.read(FIX("paste_linkedin.txt"))
    assert r["company"] == "Liberty Mutual Insurance"
    assert r["title"] == "Director I, Data Science- AI Products"
    assert r["location"] == "Boston, MA" and r["work_setting"] == "on-site"
    assert r["pay"] == "$137K/yr - $257K/yr"
    d = r["description"]
    assert d.startswith("Description") or d.startswith("We are transforming")
    assert "LangChain/LangGraph" in d and "Fair Chance Notices" not in d
    for junk in ("Reactivate Premium", "More jobs", "Ahold Delhaize", "Harun", "Messaging", "people clicked apply"):
        assert junk not in d and junk not in r["title"] and junk not in r["company"]

def test_careers_paste():
    r = paste.read(FIX("paste_careers.txt"))
    assert r["title"] and r["company"] and r["work_setting"] == "remote" and r["pay"].startswith("$150,000")

def test_blank_fields_never_crash():
    r = paste.read("Just some words about a job\nwith no pay or place")
    assert set(r) == {"company", "title", "location", "work_setting", "pay", "url", "description"}
    assert r["pay"] == "" and r["location"] == ""

def test_is_link():
    assert paste.is_link("  https://boards.greenhouse.io/acme/jobs/1 ")
    assert not paste.is_link("javascript:alert(1)") and not paste.is_link("Title\nhttps://x.io")
```

- [ ] **Step 2: Run `pytest tests/test_paste.py -v`** → FAIL (no module `autoapply.paste`).
- [ ] **Step 3: Implement `read` and `is_link`.** LinkedIn layout: company from `^Company, (.+?)\.$`; title is the line after that one (strip the trailing duplicate LinkedIn repeats, e.g. "X (Verified job)X" → first non-empty line under the company line that isn't "Liberty Mutual Insurance • ..."); location/work setting from `^(.+?) \((On-site|Hybrid|Remote)\)$` or the `•` line; pay from `\$[\d.,]+K?(?:/yr|/hr)?\s*-\s*\$[\d.,]+K?(?:/yr|/hr)?` or `Salary:`; description = text from "About the job" (exclusive) up to the first of `Fair Chance Notices|Set alert for similar jobs|About the company|More jobs|Show more`. Generic fallback when no LinkedIn markers: first non-empty line = title, next = company (unless it looks like location/pay), whole text = description; work setting by keyword. `url` = first http(s) URL in the text that isn't linkedin.com/feed noise (via `history._web`), else `""`. Cap description at 20000 chars.
- [ ] **Step 4: Run `pytest tests/test_paste.py -v`** → PASS.
- [ ] **Step 5: Commit** `git add autoapply/paste.py tests/test_paste.py tests/fixtures/paste_linkedin.txt tests/fixtures/paste_careers.txt && git commit -m "feat: read a pasted job post into lead fields"`

### Task 2: Pasted leads in the database (with the no-repeat check)

**Files:**
- Modify: `autoapply/leads.py` (`ensure`, `set_status`, `TRACKED`, new functions)
- Modify: `autoapply/db.py:52` (`STATUSES` gains `"prepped"`)
- Test: `tests/test_leads.py`

**Interfaces:**
- Consumes: `paste.read` output dict.
- Produces: `leads.add_pasted(db, settings, fields: dict, now: datetime | None = None) -> dict` returning `{"key": str, "result": "added" | "updated" | "applied", "why": str}`. `applied` = `rank.Applied(...).same_role` hit (why = its message, e.g. "already applied for this role on 2026-10-30"); nothing written then. `updated` = lead key exists: fill `description`/`work_setting`/`salary`/`location` where blank, add `"pasted"` to `source`. `added` = new row, `source="pasted"`, scored like `save` does.
- Produces: `leads.set_description(db, key: str, text: str)`.
- Produces: `leads.from_paste(db, key: str) -> str | None`: creates (or reuses) job `"manual:" + sha1(key)[:10]` with `ats="manual"`, company/title/location/description/url/apply_url from the lead (url via `history._web`), `pay` = lead salary; links the lead (`job_id`); returns the id, or `None` when the lead has no description.
- Produces: columns `leads.description`, `leads.work_setting` (ALTERed in `ensure`); `db.STATUSES` includes `prepped`; `TRACKED["prepped"] = "prepped"`.

- [ ] **Step 1: Write the failing tests** (`make` from `test_daily`):

```python
def test_paste_adds_then_updates(tmp_path):
    s, db, _ = make(tmp_path)
    f = {"company": "Hooli", "title": "Senior Analytics Engineer", "location": "", "work_setting": "remote",
         "pay": "$150K", "url": "", "description": "dbt and Snowflake"}
    assert leads.add_pasted(db, s, f)["result"] == "added"
    r = leads.add_pasted(db, s, {**f, "description": "longer text"})
    assert r["result"] == "updated"
    row = leads.get(db, r["key"])
    assert row["description"] == "dbt and Snowflake" and "pasted" in row["source"] and row["work_setting"] == "remote"

def test_paste_of_applied_role_adds_nothing(tmp_path):
    s, db, _ = make(tmp_path)
    db.update("gh:a:1", status="submitted", submitted_at="2026-10-30 10:00")
    r = leads.add_pasted(db, s, {"company": "Acme", "title": "Senior Analytics Engineer", "location": "", "work_setting": "",
                                 "pay": "", "url": "", "description": "x"})
    assert r["result"] == "applied" and "2026-10-30" in r["why"] and leads.get(db, r["key"]) is None

def test_from_paste_makes_a_job(tmp_path):
    s, db, _ = make(tmp_path)
    k = leads.add_pasted(db, s, {"company": "Hooli", "title": "Data Lead", "location": "Boston, MA", "work_setting": "",
                                 "pay": "$1", "url": "javascript:x", "description": "the post"})["key"]
    jid = leads.from_paste(db, k)
    j = db.get(jid)
    assert jid.startswith("manual:") and j["description"] == "the post" and j["url"] == "" and j["pay"] == "$1"
    assert leads.get(db, k)["job_id"] == jid and leads.from_paste(db, k) == jid

def test_prepped_is_not_applied_or_ready(tmp_path):
    s, db, _ = make(tmp_path)
    db.update("gh:a:1", status="prepped")
    from autoapply import rank, stats
    assert not rank.Applied(db, 90).same_role("Acme", "Senior Analytics Engineer", "u")
    assert "gh:a:1" not in [j["id"] for j in stats.compute(db)["ready"]]
```

- [ ] **Step 2: Run `pytest tests/test_leads.py -v -k "paste or prepped"`** → FAIL.
- [ ] **Step 3: Implement** the functions and columns above. Use `rank.Applied(db, reapply_days)` with `reapply_after_days` from `Prefs(settings.data_dir, settings.raw)` as `leads_page` does; `same_role(company, title, url)` decides `applied`.
- [ ] **Step 4: Run `pytest tests/test_leads.py -v`** → PASS (old lead tests too).
- [ ] **Step 5: Commit** `git add autoapply/leads.py autoapply/db.py tests/test_leads.py && git commit -m "feat: pasted leads keep the post, skip roles already applied to"`

### Task 3: Prep only in the CLI and the apply prompt

**Files:**
- Modify: `autoapply/cli.py` (`fill` parser and handler ~line 133 and 500; `daily-prompt` ~278; `leads` choices ~125 and handler ~439)
- Modify: `prompts/stages/apply.md` (steps 3 and 7; new `{{PREP_ONLY}}` line)
- Test: `tests/test_daily.py`

**Interfaces:**
- Consumes: `leads.from_paste`, `STATUSES` with `prepped`.
- Produces: `autoapply fill <plan> --job <id> --prep-only`: strips approvals, keeps the same-role guard, sets `plan["url"]` like fill does, then `db.update(id, status="prepped", plan_json=plan, error=None)` and prints `{"prepped": id, "files": [...], "answers": n}`; never calls `fill()`. Refuses (exit message) when the job is `filled` or `submitted`.
- Produces: `autoapply leads from-paste <key>` prints the job id or nothing.
- Produces: `autoapply leads job <key>` also returns jobs whose status is `prepped` (so Auto apply after Prep only works).
- Produces: `autoapply daily-prompt apply <id>` replaces `{{PREP_ONLY}}` with the prep-only text when env `AUTOAPPLY_PREP_ONLY=1`, else with `""`.

- [ ] **Step 1: Write the failing tests**

```python
def test_prep_only_stores_plan_without_filling(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    called = []
    monkeypatch.setattr(cli, "fill", lambda *a, **k: called.append(1))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"files": {"resume": "r.pdf"}, "answers": {"Why us?": "x"}, "approved_by_user": True}))
    cli.main(["--config", str(cfg), "fill", str(plan), "--job", "wd:c:3", "--prep-only"])
    j = db.get("wd:c:3")
    assert not called and j["status"] == "prepped" and "approved_by_user" not in json.loads(j["plan_json"])

def test_prep_only_prompt(tmp_path, capsys, monkeypatch):
    s, db, cfg = make(tmp_path)
    cli.main(["--config", str(cfg), "daily-prompt", "apply", "gh:a:1"])
    out = capsys.readouterr().out
    assert "{{PREP_ONLY}}" not in out and "--prep-only" in out   # the Workday step uses it too
    monkeypatch.setenv("AUTOAPPLY_PREP_ONLY", "1")
    cli.main(["--config", str(cfg), "daily-prompt", "apply", "gh:a:1"])
    assert "Prep only" in capsys.readouterr().out
```

(`cli.fill` must be the name the handler calls; if `fill` is imported inside the handler, monkeypatch that import site instead.)

- [ ] **Step 2: Run `pytest tests/test_daily.py -v -k prep`** → FAIL.
- [ ] **Step 3: Implement.** Prompt changes in `apply.md`:
  - Step 3 becomes: "If the posting is on Workday or another site that needs an account, don't scan it: write plan.json (step 5 shape, `url` = the posting) with answers to the usual questions (why this company, why this role, pay ask from CLAUDE.local.md, start date, notice period, years with the role's key skill), run `autoapply fill data/applications/<slug>/plan.json --job {{JOB_ID}} --prep-only`, say "apply by hand" in notes.md, and stop."
  - New line after the intro: `{{PREP_ONLY}}`, replaced in prep-only runs by: "**Prep only.** The person applies by hand. Do steps 1-2. If the form opens without an account, run step 4 and answer its questions in plan.json; otherwise answer the usual questions as in step 3. Then run `autoapply fill data/applications/<slug>/plan.json --job {{JOB_ID}} --prep-only` and stop: never run fill without --prep-only. If the job's ats is "manual", tailor against `autoapply show {{JOB_ID}}`'s description (the person pasted it); don't look for the form."
  - Step 7 gains: `"<Company>: prepped, apply by hand"`.
- [ ] **Step 4: Run `pytest tests/test_daily.py -v`** → PASS, including `test_every_command_the_prompts_use_is_allowed`.
- [ ] **Step 5: Commit** `git add autoapply/cli.py prompts/stages/apply.md tests/test_daily.py && git commit -m "feat: prep only: tailor and save answers without filling the form"`

### Task 4: daily.sh: prep-only runs and the pasted-post fallback

**Files:**
- Modify: `scripts/daily.sh:80-106`
- Test: `tests/test_daily.py` (static check of the script text, like the allowed-commands test)

**Interfaces:**
- Consumes: env `AUTOAPPLY_LEAD`, `AUTOAPPLY_JOB`, `AUTOAPPLY_PREP_ONLY`; `autoapply leads job|from-paste|note`.

- [ ] **Step 1: Write the failing test** `test_daily_falls_back_to_the_paste`: reads `scripts/daily.sh` and asserts it contains `autoapply leads from-paste "$AUTOAPPLY_LEAD"` and `export AUTOAPPLY_PREP_ONLY=1`, and that the "couldn't find" note text now includes `paste the post`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** In the `AUTOAPPLY_LEAD` block: when `leads job` prints nothing, try `job=$(autoapply leads from-paste "$AUTOAPPLY_LEAD")`; if set, `export AUTOAPPLY_PREP_ONLY=1`, `run_stage apply "$job"`, note "Not on the company's own site, so it was prepped from the post you pasted: apply by hand. ${line}". If still nothing, keep today's note plus " Paste the post on this lead's page to prep from it." When `AUTOAPPLY_PREP_ONLY=1` came in from the dashboard, the done note says "Prepped: resume, cover letter and answers are on the page. ${line}". `AUTOAPPLY_PREP_ONLY` passes through to `autoapply daily-prompt` via the environment (no code needed beyond not unsetting it).
- [ ] **Step 4: Run `pytest tests/test_daily.py -v` and `bash -n scripts/daily.sh`** → PASS, no syntax error.
- [ ] **Step 5: Commit** `git add scripts/daily.sh tests/test_daily.py && git commit -m "feat: daily run: prep only, and prep from the pasted post when the company page isn't found"`

### Task 5: Web routes

**Files:**
- Modify: `autoapply/web.py` (near `/leads` ~565 and `/prepare` ~380)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `paste.read`, `paste.is_link`, `leads.add_pasted`, `leads.set_description`, `finder` fetchers, `start_run`.
- Produces routes:
  - `POST /leads/paste` (`text`) → renders `lead.html` in confirm mode with the parsed fields (editable inputs) and the description. A bare link: for a host in `finder.FETCHERS`' ATSs, fetch via `scan`-free board fetch if cheap, else show the message "This site needs the post's text: open it, copy the whole page and paste it here." (LinkedIn and Workday links always get that message.)
  - `POST /leads/add` (`company, title, location, work_setting, pay, url, description`) → `add_pasted`; `applied` → back to `/leads` with the in-app message `why`; else 303 to `/lead/<key>`.
  - `GET /lead/{key:path}` → 404 unknown; 303 to `/job/<job_id>` when the lead has a job; else `lead.html` (view mode).
  - `POST /lead/{key:path}/run` (`mode` = `prep` | `apply`) → `leads.set_status(starred)` and `start_run(AUTOAPPLY_LEAD=key, AUTOAPPLY_PICKS="1", **({"AUTOAPPLY_PREP_ONLY": "1"} if mode == "prep" else {}))`; 303 to `/lead/<key>`.
  - `POST /lead/{key:path}/description` (`text`) → `set_description`; 303 back.
  - `POST /prepare/{job_id:path}` gains `mode: str = Form("apply")`; allowed when status is `new` or `prepped`; `mode == "prep"` adds `AUTOAPPLY_PREP_ONLY="1"`; redirects back to `Referer`-free target `back` form field if it starts with `/` (default `/`).
  - `GET /job/{id}` passes `lead` (the lead row whose `job_id` is this id, or `None`) and `answers` (`plan.get("answers", {})`) to the template.

- [ ] **Step 1: Write the failing tests** (`client` from `web_client`, `make` from `test_daily`, `FIX` reading `tests/fixtures`):

```python
def test_paste_confirm_then_save(tmp_path):
    s, db, _ = make(tmp_path); c = client(s, db)
    r = c.post("/leads/paste", data={"text": FIX("paste_linkedin.txt")})
    assert r.status_code == 200 and 'value="Liberty Mutual Insurance"' in r.text and "$137K/yr" in r.text
    r = c.post("/leads/add", data={"company": "Liberty Mutual Insurance", "title": "Director I, Data Science- AI Products",
               "location": "Boston, MA", "work_setting": "on-site", "pay": "$137K/yr - $257K/yr", "url": "", "description": "post"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/lead/")
    page = c.get(r.headers["location"])
    assert "Prep only" in page.text and "Auto apply" in page.text and "post" in page.text

def test_linkedin_link_asks_for_text(tmp_path):
    s, db, _ = make(tmp_path); c = client(s, db)
    assert "copy the whole page" in c.post("/leads/paste", data={"text": "https://www.linkedin.com/jobs/view/1"}).text

def test_pasted_html_is_escaped(tmp_path):
    s, db, _ = make(tmp_path); c = client(s, db)
    r = c.post("/leads/add", data={"company": "X", "title": "<script>x</script>", "location": "", "work_setting": "", "pay": "",
               "url": "", "description": "<img src=x onerror=1>"})
    assert "<script>x</script>" not in r.text and "<img src=x" not in r.text

def test_lead_with_job_redirects_and_prep_mode(tmp_path, monkeypatch):
    s, db, _ = make(tmp_path); c = client(s, db)
    # start_run is a closure: patch subprocess.Popen and assert the env it got
    seen = {}
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: seen.update(k.get("env", {})))
    c.post("/prepare/wd:c:3", data={"mode": "prep"})
    assert seen.get("AUTOAPPLY_PREP_ONLY") == "1" and seen.get("AUTOAPPLY_JOB") == "wd:c:3"
```

- [ ] **Step 2: Run `pytest tests/test_web.py -v -k "paste or lead_with"`** → FAIL.
- [ ] **Step 3: Implement** the routes. Reuse `history._web` for `url`. Messages to `/leads` use the existing `done=` query pattern used by `/applications/log`.
- [ ] **Step 4: Run `pytest tests/test_web.py -v`** → PASS.
- [ ] **Step 5: Commit** `git add autoapply/web.py tests/test_web.py && git commit -m "feat: paste a job: confirm, save, lead page and prep-only runs"`

### Task 6: Templates: paste box, lead page, grown job page, dashboard button

**Files:**
- Create: `autoapply/templates/lead.html` (confirm mode and view mode)
- Modify: `autoapply/templates/leads.html` (paste box above the tabs; title links to `/lead/<key>`, external link kept beside it)
- Modify: `autoapply/templates/job.html` (top: description card when `job.description`; actions for `new`/`prepped`; kit for `prepped`)
- Modify: `autoapply/templates/index.html` (Prep only button next to each shortlist "Prepare" button)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: template vars from Task 5 (`lead`, `answers`, `fields`, `mode`, `running`).

Behaviour to build (copy is fixed here):
- Leads paste box: `<details open>` when there are no leads, else closed; summary "Add a job"; textarea placeholder "Paste the whole job post (a LinkedIn page, a careers page, an email) or a link"; button "Read it".
- `lead.html` confirm mode: heading "Check the details", inputs for the six fields, description in a textarea (editable), buttons "Save" and "Cancel". View mode: header (company · title, location · work setting · pay · source, links), the run note if any (`lead.note`), buttons "Prep only" (`mode=prep`, `data-confirm-title="Prep only: <company>"`, `data-confirm` text "Tailors your resume and cover letter and writes your answers. You apply by hand. Uses AI credit.") and "Auto apply" (as today's Leads confirm), Star, Dismiss; while running, the existing running notice instead of the buttons. Description card, collapsible. No description: a small paste form ("Paste the post to prep from it") posting to `/lead/<key>/description`.
- `job.html`, status `new` or `prepped`: in the bar, show "Prep only" (status `new` only) and "Auto apply" (`/prepare/<id>` with `mode`, `back=/job/<id>`), plus "I applied by hand" and "Not applying" (existing `manual`/`skip` actions). Hide Submit, approve tick and "Save and refill" unless status is `filled`.
- `job.html`, status `prepped`: a "Your kit" card first: download links for each file (pdf and the sibling .docx when it exists), "Apply on the company's site" link (`job.apply_url or job.url`, only if http(s)), and a table of `answers` with a Copy button per row (same markup as the handoff table). If `notes` says "apply by hand", show that line.
- `job.html`: "The job description" card (`<details>`, open when there are no files yet) for every job with a description.

- [ ] **Step 1: Write the failing tests**

```python
def test_prepped_job_shows_kit_not_submit(tmp_path):
    s, db, _ = make(tmp_path); c = client(s, db)
    pdf = s.data_dir / "applications" / "initech" / "Doe Resume - Initech.pdf"; pdf.parent.mkdir(parents=True); pdf.write_bytes(b"%PDF")
    db.update("wd:c:3", status="prepped", plan_json={"files": {"resume": str(pdf)}, "answers": {"Why Initech?": "Because dbt."}})
    t = c.get("/job/wd:c:3").text
    assert "Your kit" in t and "Because dbt." in t and "Doe Resume - Initech.pdf" in t and "I applied by hand" in t
    assert 'value="submit"' not in t

def test_leads_page_has_paste_box_and_lead_links(tmp_path):
    s, db, _ = make(tmp_path); c = client(s, db)
    leads.add_pasted(db, s, {"company": "Hooli", "title": "Data Lead", "location": "", "work_setting": "", "pay": "", "url": "", "description": "d"})
    t = c.get("/leads").text
    assert "Add a job" in t and 'href="/lead/hooli%7Cdata%20lead"' in t

def test_dashboard_offers_prep_only(tmp_path):
    s, db, _ = make(tmp_path); c = client(s, db)
    assert 'name="mode" value="prep"' in c.get("/").text
```

(Adjust the lead href assertion to whatever `|urlencode` produces for `hooli|data lead`; the key point is the title links to `/lead/`.)

- [ ] **Step 2: Run `pytest tests/test_web.py -v -k "kit or paste_box or prep_only"`** → FAIL.
- [ ] **Step 3: Implement** the templates within `base.html`/`macros.html` styles; mobile width must not scroll sideways.
- [ ] **Step 4: Run the whole suite `pytest -q`** → all PASS.
- [ ] **Step 5: Commit** `git add autoapply/templates/lead.html autoapply/templates/leads.html autoapply/templates/job.html autoapply/templates/index.html tests/test_web.py && git commit -m "feat: lead page, prep-only kit on the job page, paste box on Leads"`

### Task 7: Docs, review, deploy

**Files:**
- Modify: `README.md` (a short "Add a job by pasting it" section; Prep only vs Auto apply)
- Modify: `AGENTS.md` only if the prep-only contract needs a line (it says "Workday: prep materials only" already; add "Prep only runs end with `autoapply fill ... --prep-only`")

- [ ] **Step 1:** Update docs; `pytest -q` passes.
- [ ] **Step 2:** Run the app locally (`autoapply serve` against a scratch data dir) and walk: paste the LinkedIn fixture → confirm → lead page → (stub run) → a hand-made prepped job page shows the kit. Screenshot.
- [ ] **Step 3:** Push `feat/paste-a-job`, open the PR (no Claude attribution), code review, merge after review.
- [ ] **Step 4:** Deploy on ubuntu per the deploy notes: check `data/daily/.running` is absent, back up `data/autoapply.db`, `git pull --ff-only`, `systemctl --user restart autoapply-review.service`, 401 on the Tailscale IP `:8787` means up; open `/leads` signed in and paste the Liberty Mutual post for real.
- [ ] **Step 5:** Docmost change log entry (jobsearchPal space), brainPal overlay + rescan + live copy (a new feature counts as major), memory note.

## Amendments from review (apply inside the named tasks)

- **Before Task 1:** in the worktree, `python -c "import autoapply; print(autoapply.__file__)"` must print the worktree path; always run `python -m pytest` from the worktree root and `python -m autoapply.cli` (or PYTHONPATH) for serve. Baseline on main: `test_greenhouse_react_selects` and `test_follow_up_reminders` already fail; not fixed here.
- **Task 5, kit can be wiped:** in `POST /job/<id>`, when the `plan` form field is absent or blank, start from `old_plan`, not `{}`. Test: prepped job, POST `action=manual` with no `plan` field → `plan_json` still has `files`.
- **Task 5, lead follows the job:** `manual` sets `leads.status='applied'`, `skip` sets `'dismissed'` `where job_id = ?`. Test it.
- **Task 6, prepped jobs show on the dashboard:** "Ready for you" includes `prepped` jobs (stats `ready` = filled + prepped), labelled "Prepped: apply by hand" and linking to `/job/<id>`. Check `brief.compose` and `todo-line` read the same list. Test: prepped job appears on `/`.
- **Task 3, no redo after Prep only:** apply.md line: "If data/applications/<slug>/ already has the PDFs and plan.json from a prep-only run, reuse them: skip step 2 and go to scan and fill."
- **Task 4:** every read is `${AUTOAPPLY_PREP_ONLY:-}` (`set -u`).
- **Task 5, bare links:** a URL on a known ATS host (`fillers.base.detect(url).name` in `finder.FETCHERS`): slug from the URL path, `finder.FETCHERS[ats](slug)`, match the job whose `url`/`apply_url` equals the pasted URL (ignoring query/fragment); found → confirm mode with its fields; else the "copy the whole page" message. Test with a monkeypatched Greenhouse fetcher.
- **Optional (Task 2):** `classify._apps` and emailsync's confirmed→submitted transition also accept `prepped`, so a "thanks for applying" email marks a by-hand application applied.
