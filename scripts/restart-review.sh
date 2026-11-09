#!/usr/bin/env bash
# Restarts the review page on the server (finds it by port, so it never matches itself).
#   ssh <server> 'bash ~/auto-apply/scripts/restart-review.sh'
cd "$(dirname "$0")/.."
P=$(ss -ltnpH "sport = :8787" | grep -o "pid=[0-9]*" | cut -d= -f2)
[ -n "$P" ] && kill $P && sleep 1
set -a; source .env; set +a
setsid nohup .venv/bin/autoapply serve > data/serve.log 2>&1 < /dev/null &
sleep 4
curl -s -o /dev/null -w "review page: %{http_code} (401 = up, asking you to sign in)\n" "${REVIEW_URL:-http://127.0.0.1:8787/}"
