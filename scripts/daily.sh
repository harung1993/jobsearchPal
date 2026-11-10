#!/usr/bin/env bash
# Daily run. Cron example (weekdays 6:30am, server in ET):
#   30 6 * * 1-5  $HOME/auto-apply/scripts/daily.sh >> $HOME/auto-apply/data/cron.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
# The agent CLIs usually install to ~/.local/bin, which cron and `ssh host cmd` leave off PATH.
export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
[ -f .venv/bin/activate ] && source .venv/bin/activate  # Docker has it on PATH already
[ -f .env ] && set -a && source .env && set +a
mkdir -p data/daily
# One run at a time: the 6:30 cron run and "Run now" on the dashboard share this lock.
exec 9>data/daily/.lock
if ! flock -n 9; then echo "$(date -Is) another run is going; not starting a second"; exit 0; fi
trigger=${AUTOAPPLY_TRIGGER:-cron}
progress() { printf '%s\t%s\t%s\n' "$started" "$trigger" "$1" > data/daily/.running; }
started=$(date -Is); progress "starting"
trap 'rm -f data/daily/.running' EXIT
# A fresh install does nothing until the dashboard's Setup page has contact details and job interests.
if ! check=$(autoapply setup-check 2>&1); then
  echo "$(date -Is) $check"
  autoapply log-run daily fail "$check" 2>/dev/null || true
  exit 0
fi

# The run is split into short agent sessions so no session drags a long history along (that is where most
# tokens go). Plain steps run first without an agent: email sync and the job search.
# "Rewrite this letter" (AUTOAPPLY_LETTER with AUTOAPPLY_JOB) skips them: it only redoes one cover letter.
if [ -z "${AUTOAPPLY_LETTER:-}" ]; then
  progress "syncing email and searching job boards"
  autoapply sync-email --days 3 >/dev/null 2>&1 || autoapply log-run sync-email fail "sync failed; see data/cron.log" || true
  autoapply find >/dev/null 2>&1 || true
  # Optional AI skill matching (Settings > Daily run). Does nothing unless you turned it on.
  autoapply skills tag >/dev/null 2>&1 || true
fi

today=data/daily/$(date +%F).md
if [ "$trigger" = manual ]; then echo "
# Run now $(date '+%F %H:%M')" >> "$today"; else echo "# Daily run $(date '+%F %H:%M')" > "$today"; fi
ok=1; picked=""; blocked=""

# run_stage STAGE [JOB_ID]: sets line to the stage's last line of output, and ok=0 on failure.
# Agent, model and billing come from Settings > Daily run (light model for rank/prep/drafts).
run_stage() {
  local stage=$1 job=${2:-} agent model via turns last=data/daily/.last-message
  line=""
  progress "$stage${job:+ $job}"
  read -r agent model via < <(autoapply daily-agent --stage "$stage" 2>/dev/null || echo claude) || true
  agent=${agent:-claude}; via=${via:-subscription}; [ "$model" = - ] && model=
  if [ "$via" = blocked ]; then
    blocked=$(autoapply daily-agent --stage "$stage" 2>&1 >/dev/null | tail -1)
    return 1
  fi
  if ! command -v "$agent" >/dev/null; then
    blocked="$agent isn't installed or isn't on PATH (looked in ~/.local/bin too)"
    ok=0; return 1
  fi
  case $stage in rank) turns=40;; alerts) turns=30;; apply) turns=60;; prep) turns=40;; *) turns=20;; esac
  [ "$via" = openrouter ] && eval "$(autoapply daily-env)"
  rm -f "$last"
  if [ "$agent" = codex ]; then
    local or_args=()
    if [ "$via" = openrouter ]; then
      or_args=(-c model_provider=openrouter
               -c 'model_providers.openrouter={name="OpenRouter",base_url="https://openrouter.ai/api/v1",wire_api="responses",env_key="OPENROUTER_API_KEY"}')
    fi
    # Writes stay inside this folder; network is on so the CLI can reach job boards and ATS pages.
    autoapply daily-prompt "$stage" $job | codex exec --skip-git-repo-check --sandbox workspace-write \
      -c sandbox_workspace_write.network_access=true -c approval_policy=never "${or_args[@]}" \
      ${model:+-m "$model"} -o "$last" - || ok=0
    line=$( [ -s "$last" ] && autoapply log-daily codex "$model" "$via" --stage "$stage" < "$last" || echo "")
  else
    line=$(claude -p "$(autoapply daily-prompt "$stage" $job)" ${model:+--model "$model"} \
      --permission-mode acceptEdits --max-turns "$turns" \
      --output-format json < /dev/null | autoapply log-daily claude "$model" "$via" --stage "$stage") || ok=0
  fi
  echo "- $stage${job:+ $job}: $line" >> "$today"
}

# Leads you starred on the dashboard: a short light step finds them on the company's own site first.
# Auto apply on one lead (AUTOAPPLY_LEAD): just that role, found and then filled; no other steps.
# "Prepare this one" on the dashboard (AUTOAPPLY_JOB): just the apply step for that tracked role.
one="${AUTOAPPLY_LEAD:-}${AUTOAPPLY_JOB:-}"
if [ -z "${AUTOAPPLY_JOB:-}" ] && [ "$(autoapply leads lookup 2>/dev/null || echo 0)" -gt 0 ] 2>/dev/null; then
  run_stage alerts || true; echo "- starred leads: $line" >> "$today"
fi
if [ -n "${AUTOAPPLY_LEAD:-}" ]; then
  job=$(autoapply leads job "$AUTOAPPLY_LEAD" 2>/dev/null || true)
  if [ -n "$job" ]; then run_stage apply "$job" || true; picked="$line"
  else picked="Auto apply: couldn't find that role on the company's own site (it may be closed, or only on LinkedIn/Indeed)"; ok=0; fi
  echo "- auto apply: $picked" >> "$today"
fi
if [ -n "${AUTOAPPLY_JOB:-}" ] && [ -n "${AUTOAPPLY_LETTER:-}" ]; then
  # Rewrite one cover letter with the person's note, then refill the form from the saved plan (no agent).
  run_stage letter "$AUTOAPPLY_JOB" || true; picked="$line"
  progress "refilling $AUTOAPPLY_JOB"
  autoapply refill "$AUTOAPPLY_JOB" >/dev/null 2>>data/cron.log || { ok=0; picked="$picked (the form refill failed: press Save and refill)"; }
  echo "- letter: $picked" >> "$today"
elif [ -n "${AUTOAPPLY_JOB:-}" ]; then
  run_stage apply "$AUTOAPPLY_JOB" || true; picked="$line"
  echo "- prepare: $picked" >> "$today"
fi
for stage in $( [ -n "$one" ] || autoapply daily-stages 2>/dev/null); do
  if [ "$stage" = rank ]; then
    # Quick pick (Settings > Daily run): a cheap OpenRouter model reads the alert emails, a short light agent
    # step looks up only the roles that fit, then one cheap call picks. Exit 2 = off today, 1 = failed:
    # either way the rank agent does the whole step instead.
    rc=0; n=$(autoapply quick-pick --alerts 2>>data/cron.log) || rc=$?
    if [ "$rc" = 0 ]; then
      if [ "${n:-0}" -gt 0 ] 2>/dev/null; then run_stage alerts || true; fi
      line=$(autoapply quick-pick 2>>data/cron.log) || rc=$?
    fi
    if [ "$rc" = 0 ]; then picked="$line"; echo "- rank (quick pick): $line" >> "$today"; continue; fi
    [ "$rc" = 1 ] && echo "- rank (quick pick failed, using the agent)" >> "$today"
  fi
  run_stage "$stage" || true
  if [ "$stage" = rank ]; then picked="$line"; fi
done
if [ -z "$blocked" ] && [ -z "$one" ]; then
  for job in $(autoapply daily-picks 2>/dev/null); do
    run_stage apply "$job" || true
  done
fi
summary=${picked:-No picks today}
if [ -n "$blocked" ]; then
  autoapply log-run daily fail "skipped: $blocked (Settings > Daily run)"
  summary="Daily run skipped: $blocked"
elif [ "$ok" = 1 ]; then
  autoapply log-run daily ok "$summary"
else
  autoapply log-run daily fail "a stage exited with an error; see data/cron.log and $today"
fi

echo "$(date -Is) $summary"
# Morning brief email (today's picks + application status) for the inbox your morning brief reads.
# A "Run now" from the dashboard skips it: you're already looking.
if [ "$trigger" != manual ]; then
  autoapply brief --send || autoapply log-run brief fail "brief email failed; see data/cron.log"
fi
# Optional phone push via ntfy (set NTFY_TOPIC in .env and subscribe in the ntfy app).
if [ -n "${NTFY_TOPIC:-}" ]; then
  todo=$(autoapply todo-line 2>/dev/null || true)
  line=$(autoapply pal-line 2>/dev/null || true)
  msg=$summary; [ -n "$line" ] && msg="$line
$summary"; [ -n "$todo" ] && msg="$msg
$todo"
  curl -fsS -H "Title: jobsearchPal" -H "Click: ${REVIEW_URL:-}" -d "$msg" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null || true
fi
