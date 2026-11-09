#!/usr/bin/env bash
# Sets up `autoapply-finish` on your laptop (macOS or Linux). Run from a permanent copy of the repo:
#   bash scripts/mac-setup.sh <ssh-host-of-your-server>
# It reads the review URL and token from the server's .env over ssh, so nothing is pasted.
set -euo pipefail
host="${1:?usage: bash scripts/mac-setup.sh <ssh-host>   (the name you use with ssh, e.g. myserver)}"
cd "$(dirname "$0")/.."
python3 -m venv ~/.autoapply-venv
~/.autoapply-venv/bin/pip install -q -e .
# Uses your installed Google Chrome; this only downloads Chromium as a fallback.
[ -d "/Applications/Google Chrome.app" ] || ~/.autoapply-venv/bin/playwright install chromium
token=$(ssh "$host" 'grep -E "^AUTOAPPLY_TOKEN=" ~/auto-apply/.env | cut -d= -f2-' || true)
[ "$token" != "change-me-long-random" ] || token=""  # the old example value is ignored by the server
# Made automatically with the dashboard account when .env leaves it blank.
[ -n "$token" ] || token=$(ssh "$host" 'python3 -c "import json;print(json.load(open(\"auto-apply/data/secrets.json\")).get(\"AUTOAPPLY_TOKEN\",\"\"))" 2>/dev/null' || true)
[ -n "$token" ] || { echo "No AUTOAPPLY_TOKEN on the server yet: create your dashboard account first"; exit 1; }
url=$(ssh "$host" 'grep -E "^REVIEW_URL=" ~/auto-apply/.env | cut -d= -f2-')
[ -n "$url" ] || { echo "Set REVIEW_URL in the server's ~/auto-apply/.env first"; exit 1; }
umask 077
cat > ~/.autoapply.env <<ENV
AUTOAPPLY_SERVER=${url%/}
AUTOAPPLY_TOKEN=$token
ENV
mkdir -p ~/.local/bin
cat > ~/.local/bin/autoapply-finish <<'SH'
#!/usr/bin/env bash
set -a; source ~/.autoapply.env; set +a
exec ~/.autoapply-venv/bin/autoapply finish "$@"
SH
chmod +x ~/.local/bin/autoapply-finish
echo "Done. Try: autoapply-finish <job id from the dashboard>"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo 'Add ~/.local/bin to PATH:  echo '\''export PATH="$HOME/.local/bin:$PATH"'\'' >> ~/.zshrc';; esac
