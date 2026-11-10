"""The run log: what each daily run and each Run now / Auto apply / Prepare did, read back from
data/daily/YYYY-MM-DD.md (daily.sh writes one "# Daily run" or "# Run now" heading per run, then one
"- stage: last line" bullet per step). Shown on the dashboard's Run log page so nothing is only in cron.log.
"""
from __future__ import annotations

import re
from pathlib import Path

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
HEAD = re.compile(r"^#\s+(Daily run|Run now)\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})")
# "- apply greenhouse:acme:123: text": the stage, then an optional job id (no spaces, may hold colons).
ITEM = re.compile(r"^-\s+([A-Za-z][A-Za-z ()-]{0,40}?)(?:\s+(\S+:\S+?))?:(?:\s+(.*)|$)")


def parse(text: str) -> list[dict]:
    """One day's file -> its runs, newest first. Lines that aren't a heading or a "- stage: text" bullet are
    kept as text on the step before them (an agent's final message can run to a few lines)."""
    runs: list[dict] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = HEAD.match(line)
        if m:
            runs.append({"kind": m.group(1), "date": m.group(2), "at": m.group(3), "steps": []})
            continue
        if not runs:
            runs.append({"kind": "Run", "date": "", "at": "", "steps": []})
        m = ITEM.match(line)
        if m:
            runs[-1]["steps"].append({"stage": m.group(1).strip(), "job": m.group(2) or "", "text": (m.group(3) or "").strip()})
        elif line.startswith("- "):
            runs[-1]["steps"].append({"stage": "", "job": "", "text": line[2:].strip()})
        elif runs[-1]["steps"]:
            runs[-1]["steps"][-1]["text"] += "\n" + line.strip()
        else:
            runs[-1]["steps"].append({"stage": "", "job": "", "text": line.strip()})
    for r in runs:
        r["ok"] = not any(_failed(s["text"]) for s in r["steps"])
    return runs[::-1]


def _failed(text: str) -> bool:
    t = text.lower()
    return t.startswith(("stopped", "auto apply: couldn't", "failed")) or "needed permission" in t


def recent(data_dir: Path, days: int = 10) -> list[dict]:
    """The last `days` days that had a run, newest first, each with its runs newest first."""
    folder = Path(data_dir) / "daily"
    if not folder.is_dir():
        return []
    files = sorted((p for p in folder.iterdir() if DAY.match(p.name)), reverse=True)[:days]
    out = []
    for p in files:
        try:
            runs = parse(p.read_text(errors="replace"))
        except OSError:
            continue
        if runs:
            out.append({"date": p.stem, "runs": runs})
    return out
