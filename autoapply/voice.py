"""How your cover letters sound: a few choices, words to avoid, your own notes and letters you liked.

Saved on the Letters page and written to materials/context/voice.md, which the agent reads before every letter
(the apply step and "Rewrite this letter" on an application). The examples on the page are fixed sample lines so
you can see what each choice means before any credits are spent.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

# (key, label, what the agent is told, a sample line shown on the page)
TONES = [
    ("plain", "Plain and direct", "Plain and direct: short sentences, no warm-up, say what I did and what I'd do.",
     "Short sentences. Says what you did and what you'd do, then stops."),
    ("warm", "Warm and personable", "Warm and personable: friendly and human, still specific, never gushing.",
     "Friendly and human, still specific. Sounds like a person, not a form."),
    ("formal", "Formal and polished", "Formal and polished: complete sentences, a traditional business letter, no slang.",
     "A traditional business letter. Careful, complete sentences."),
]
LENGTHS = [
    ("short", "Short", "Short: three short paragraphs, about 200 words.", "Three short paragraphs, about 200 words."),
    ("standard", "Standard", "Standard: four paragraphs, about 300 words.", "Four paragraphs, about 300 words."),
    ("full", "Full page", "Full page: up to five paragraphs, never over one page.", "Up to five paragraphs, never over a page."),
]
OPENINGS = [
    ("role", "Name the role, then get to it", "Open by naming the role in one plain line, then go straight to why I fit.",
     "One plain line naming the role, then straight to why you fit."),
    ("result", "Lead with a result", "Open with one concrete result from my work that matters for this role.",
     "Your strongest relevant result comes first."),
    ("why", "Lead with why them", "Open with what draws me to this company or its work, said specifically.",
     "What draws you to this company, said specifically."),
    ("story", "Lead with a short story", "Open with a two-sentence moment from my work that shows how I work.",
     "A two-sentence moment from your work that shows how you work."),
]

# A sample opening for each tone and opening, about one made-up role (an operations analyst at "Northwind"), so you
# can see the difference before a real letter is written. Never sent anywhere.
SAMPLES = {
    ("plain", "role"): "I'm applying for the Operations Analyst role at Northwind. I've spent four years turning messy shipment data into reports the floor team actually uses.",
    ("plain", "result"): "Last year I cut our weekly reporting from two days to two hours by rebuilding it on one clean data model. I'd like to do the same for Northwind.",
    ("plain", "why"): "Northwind ships to every store from three warehouses, and your posting says the numbers don't agree yet. That's the problem I like most.",
    ("plain", "story"): "Our warehouse manager once asked why two reports showed different stock counts. I traced it to one late file, fixed it, and wrote a check so it can't happen again.",
    ("warm", "role"): "I was glad to see the Operations Analyst role at Northwind. It's close to the work I've enjoyed most: helping a busy team trust its numbers.",
    ("warm", "result"): "One of my favorite projects cut our weekly reporting from two days to two hours, and gave the team their Monday mornings back. I'd love to bring that to Northwind.",
    ("warm", "why"): "I've shopped at Northwind for years, and reading how your warehouses work made me want to help from the inside.",
    ("warm", "story"): "A warehouse manager once stopped me in the hall to ask why two reports disagreed. Finding the answer together is still one of my favorite days at work.",
    ("formal", "role"): "I am writing to apply for the Operations Analyst position at Northwind. I bring four years of experience in supply chain reporting and analysis.",
    ("formal", "result"): "In my current role, I reduced the time required for weekly reporting from two days to two hours. I would welcome the opportunity to contribute similar improvements at Northwind.",
    ("formal", "why"): "Northwind's commitment to dependable delivery across its warehouse network is what draws me to this position.",
    ("formal", "story"): "When our warehouse manager asked why two reports disagreed, I traced the difference to a delayed file and introduced a check to prevent it. That approach guides all of my work.",
}

# Phrases people often want gone. Offered as one-tap suggestions; nothing is avoided until you add it.
COMMON_AVOID = ["I am excited to apply", "passionate", "I believe I would be a great fit", "leverage", "synergy",
                "fast-paced environment", "team player", "To whom it may concern", "I am confident that"]

DEFAULTS = {"tone": "plain", "length": "standard", "opening": "role", "avoid": [], "notes": "", "samples": ["", ""]}
SAMPLE_CHARS = 5000


def _keys(rows):
    return [r[0] for r in rows]


def load(db) -> dict:
    from . import coach
    v = coach.note(db, "voice") or {}
    out = {**DEFAULTS, **{k: v[k] for k in DEFAULTS if k in v}}
    out["samples"] = (list(out["samples"]) + ["", ""])[:2]
    return out


def is_set(db) -> bool:
    from . import coach
    return coach.note(db, "voice") is not None


def save(db, root: Path, tone: str, length: str, opening: str, avoid: str, notes: str, samples: list[str]) -> dict:
    """Keeps only known choices; avoid is one phrase per line (or comma separated). Writes voice.md for the agent."""
    from . import coach
    phrases, seen = [], set()
    for p in re.split(r"[\n,]", avoid or ""):
        p = re.sub(r"\s+", " ", p).strip().strip('"')[:80]
        if p and p.lower() not in seen:
            seen.add(p.lower())
            phrases.append(p)
    v = {"tone": tone if tone in _keys(TONES) else DEFAULTS["tone"],
         "length": length if length in _keys(LENGTHS) else DEFAULTS["length"],
         "opening": opening if opening in _keys(OPENINGS) else DEFAULTS["opening"],
         "avoid": phrases[:30], "notes": str(notes or "").strip()[:2000],
         "samples": [str(s or "").strip()[:SAMPLE_CHARS] for s in (list(samples) + ["", ""])[:2]]}
    coach.set_note(db, "voice", v)
    write(root, v)
    return v


def add_note(db, root: Path, text: str) -> None:
    """'Keep this for every letter' on a rewrite: the note joins your own notes."""
    v = load(db)
    text = re.sub(r"\s+", " ", text or "").strip()[:300]
    if not text or text in v["notes"]:
        return
    notes = (v["notes"] + "\n" if v["notes"] else "") + "- " + text
    save(db, root, v["tone"], v["length"], v["opening"], "\n".join(v["avoid"]), notes, v["samples"])


def path(root: Path) -> Path:
    return root / "materials" / "context" / "voice.md"


def render(v: dict) -> str:
    pick = lambda rows, k: next(r[2] for r in rows if r[0] == k)  # noqa: E731
    lines = ["# How my cover letters should sound", "",
             "Written by the Letters page in the dashboard (Settings, then Letters). Change it there: edits here are replaced.",
             "", f"- Tone: {pick(TONES, v['tone'])}", f"- Length: {pick(LENGTHS, v['length'])}",
             f"- Opening: {pick(OPENINGS, v['opening'])}"]
    if v["avoid"]:
        lines.append("- Never use these words or phrases: " + "; ".join(f'"{p}"' for p in v["avoid"]))
    if v["notes"]:
        lines += ["", "## My own notes", "", v["notes"]]
    samples = [s for s in v["samples"] if s]
    if samples:
        lines += ["", "## Letters I wrote and liked",
                  "", "Match their voice and rhythm only. Never copy their facts, numbers, companies or sentences."]
        for i, s in enumerate(samples, 1):
            lines += ["", f"### Sample {i}", "", s]
    lines += ["", "Facts still come only from my resume and materials/: style never adds a claim, metric, title or date."]
    return "\n".join(lines) + "\n"


def write(root: Path, v: dict) -> None:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(v))


def recent(data_dir: Path, n: int = 3) -> list[dict]:
    """Your latest letters' openings and lengths, newest first, so the page shows what letters look like now."""
    out = []
    docs = sorted((data_dir / "applications").glob("*/docs.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in docs:
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        paras = [str(x) for x in (d.get("cover_letter") or {}).get("paragraphs") or [] if str(x).strip()]
        if not paras:
            continue
        out.append({"company": d.get("company") or p.parent.name, "opening": paras[0],
                    "words": sum(len(x.split()) for x in paras), "paragraphs": len(paras),
                    "at": datetime.fromtimestamp(p.stat().st_mtime).strftime("%b %-d")})
        if len(out) >= n:
            break
    return out


def letter_slug(plan: dict, data_dir: Path) -> str | None:
    """The application folder for a job's cover letter (data/applications/<slug>/), when it has a docs.json."""
    for slot, p in (plan.get("files") or {}).items():
        if "cover" in slot:
            folder = Path(p).parent
            try:
                if folder.resolve().parent == (data_dir / "applications").resolve() and (folder / "docs.json").is_file():
                    return folder.name
            except OSError:
                return None
    return None
