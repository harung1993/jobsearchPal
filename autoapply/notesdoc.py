"""An application's notes.md, shown as a document: headings, lists, a real fit/gap table, links you can click.

The notes can quote job postings, so raw HTML in them is shown as text (never run) and only http(s) links work.
"""
from __future__ import annotations

import re

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable("table")
_md.validateLink = lambda url: url.strip().lower().startswith(("http://", "https://"))

_BARE = re.compile(r"(?<![(<\[`\w])(https?://[^\s<>()|`]+[^\s<>()|`.,;:!?'\"])")


def _link_open(self, tokens, idx, options, env):
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


_md.add_render_rule("link_open", _link_open)


def render(text: str) -> str:
    """HTML for the notes. Bare web addresses become links; tables get a wrapper that scrolls on a phone."""
    if not text.strip():
        return ""
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        out.append(line if fence else _BARE.sub(r"<\1>", line))
    html = _md.render("\n".join(out))
    return html.replace("<table>", '<div class="doc-table"><table>').replace("</table>", "</table></div>")
