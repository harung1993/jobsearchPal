**Prep only.** The person applies by hand; this run never fills a form. Do steps 1 and 2. If the job's ats is
"manual", the person pasted the post: tailor against the description `autoapply show {{JOB_ID}}` prints and don't
look for the form. Otherwise, if the form opens without an account, run step 4 and answer its questions in plan.json;
if not, answer the usual questions as step 3 says. Then run
`autoapply fill data/applications/<slug>/plan.json --job {{JOB_ID}} --prep-only` and stop. Never run fill without
--prep-only in this run. Print "<Company>: prepped, apply by hand".
