"""Morning brief email: the pal's welcome, good news first, today's picks, and where every application stands.

Sent to yourself over Gmail SMTP with the same app password the email sync uses, so it lands in
the inbox your morning brief already reads. The subject always starts "Job search brief": the email sync
recognises its own brief by that prefix (emailsync.py), and filters can rely on it. What follows the prefix is
the best news of the day, never a rejection (VOICE.md).
"""
from __future__ import annotations

import os
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape

from . import pal, stats
from .db import DB

LABELS = {"confirmed": "received", "rejected": "closed"}  # same words as the dashboard


FOOTER_TEXT = "jobsearchPal, part of palStack.io (https://palstack.io): privacy-first tools that run on your own computer."


def _recent_events(db: DB, hours: int = 30) -> list[dict]:
    cut = datetime.now() - timedelta(hours=hours)
    out = []
    for e in db.events():
        try:
            at = datetime.strptime(e["at"][:16], "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        if at >= cut and e["kind"] != "applied":
            out.append(e)
    return out


def _co(name: str) -> str:
    # Board slugs come through lower-case ("acme"); tracker rows keep their own spelling.
    return name.title() if name and name.islower() else (name or "")


GOOD_FIRST = {"offer": 0, "interview": 1, "recruiter": 2, "confirmed": 3, "agency": 4, "rejected": 5}


def _good_first(news: list[dict]) -> list[dict]:
    return sorted(news, key=lambda e: GOOD_FIRST.get(e["kind"], 4))


def headline(db: DB, news: list[dict], ready: list[dict]) -> str:
    """The best news for the subject line: an offer, an interview, a reply, then what's ready. Never a rejection."""
    parts = []
    for kind, say in (("offer", "An offer from {co}"), ("interview", "{co} wants to talk"), ("recruiter", "{co} wrote back")):
        hit = next((e for e in news if e["kind"] == kind), None)
        if hit:
            parts.append(say.format(co=pal.company(db, hit)))
            break
    if ready:
        parts.append(f"{len(ready)} role{'' if len(ready) == 1 else 's'} ready for you")
    return ", and ".join(parts) if parts else "nothing new this morning"


def compose(db: DB, review_url: str = "", today: date | None = None, label: str = "Work search",
            floor: int = 3, data_dir=None, settings=None) -> tuple[str, str, str]:
    """Returns (subject, text, html)."""
    s = stats.compute(db, today, floor=floor)
    from . import nudges
    ready, news = s["ready"], _recent_events(db)
    todo = nudges.compute(db, data_dir, settings=settings) if data_dir else []
    left = max(0, s["dua_floor"] - s["this_week"])
    dua = f"{s['this_week']} of {s['dua_floor']} this week" + (", covered" if not left else f", {left} to go")
    now = datetime.now() if today is None else datetime.combine(today, datetime.now().time())
    first = ((getattr(settings, "profile", None) or {}).get("first_name") or "") if settings else ""
    g = pal.greeting(db, s, now, first)
    market = g["market"] or (pal.market_line(now.date()) if now.day <= 7 else None)  # once a month, in the first week
    subject = f"Job search brief: {headline(db, news, ready)} · {label} {s['this_week']}/{s['dua_floor']}" + (
        f" · {len(todo)} to do" if todo else "")
    base = review_url.rstrip("/")

    t = [g["title"], g["line"], ""]
    if market:
        t += [f"{market['text']} ({market['source']}, checked {market['checked']})", ""]
    from . import coach
    my_plan = coach.plan_line(coach.plan(db, s["this_week_start"]))  # the person's own words; no nagging when there's none
    from . import goals  # weekly goals: today's share, and on Sunday a look-back (no nagging when there's none)
    day = now.date()
    lb = goals.lookback(db, day)
    lb_line = f"Last week: {goals.summary(lb['did'])}. Plan this week: {base}/#plan" if lb and goals.summary(lb["did"]) else ""
    today_line = "" if lb else goals.today_line(goals.today_view(db, day))
    t += [f"{label}: {dua}"] + ([f"Your plan this week: {my_plan}"] if my_plan else [])
    t += ([lb_line] if lb_line else []) + ([f"Today's plan: {today_line}"] if today_line else []) + [""]
    if todo:
        t.append(f"TO DO ({len(todo)})")
        t += [f"- {n['title']} · {n['about']} · {n['why']}" for n in todo[:8]]
        t += [f"  {base}/#todo" if base else "", ""]
    t.append(f"READY FOR YOU ({len(ready)})")
    for j in ready:
        t.append(f"- {_co(j['company'])} · {j['title']}" + (f" · {j['pay']}" if j["pay"] else ""))
        t.append(f"  review: {base}/job/{j['id']}   finish on Mac: autoapply-finish {j['id']}")
    if not ready:
        t.append("- nothing new today")
    from . import prep
    recent = ((today or date.today()) - timedelta(days=30)).isoformat()
    ivs = [r for r in prep.interviews(db, data_dir) if r["latest"] >= recent][:5] if data_dir else []
    if ivs:
        t += ["", f"INTERVIEWS ({len(ivs)})"]
        for r in ivs:
            st = {"ready": f"prep pack: {base}/prep/{r['job']['id']}", "update": "prep pack updating next run",
                  "due": "prep pack next run"}[r["state"]]
            t.append(f"- {_co(r['job']['company'])} · {r['job']['title']} · {st}")
    t += ["", f"NEW REPLIES ({len(news)})"]
    t += [f"- {LABELS.get(e['kind'], e['kind'])}: {e['sender'].split(' <')[0]} · {e['subject']}" for e in _good_first(news)] or ["- none yet"]
    if any(e["kind"] == "rejected" for e in news):
        t.append("  The closed ones need nothing from you. Most applications end this way, even good ones.")
    t += ["", f"APPLICATIONS: {s['applied']} sent · {s['interviews']} interviews · {s['waiting']} still in play · "
              f"{s['rejected']} closed · {s['no_reply']} no reply yet · {s['response_rate']}% response rate"]
    for j in s["applications"][:15]:
        t.append(f"- {j['applied_label']}: {_co(j['company'])} · {j['title']} · {LABELS.get(j['state'], j['state'])}")
    stale = [r for r in s["runs"] if r["state"] in ("fail", "stale")]
    if stale:
        t += ["", "CHECK: " + "; ".join(f"{r['label']} {r['state']} ({r['when']})" for r in stale)]
    if base:
        t += ["", f"Dashboard: {base}/"]
    t += ["", "--", FOOTER_TEXT]
    text = "\n".join(t)

    def li(items):
        return "".join(f"<li>{i}</li>" for i in items)
    h = [f"<p style='font-size:18px;margin:0 0 4px'><b>{escape(g['title'])}</b></p><p style='font-size:15px;margin:0 0 12px'>{escape(g['line'])}</p>"]
    if market:
        h.append(f"<p style='font-size:14px;background:#fcefd2;padding:8px 12px;border-radius:8px'>{escape(market['text'])}<br>"
                 f"<span style='color:#666'>{escape(market['source'])}, checked {escape(market['checked'])}</span></p>")
    if my_plan:
        h.append(f"<p style='font-size:15px;margin:0 0 6px'><b>Your plan this week:</b> {escape(my_plan)}</p>")
    if lb_line:
        h.append(f"<p style='font-size:15px;margin:0 0 6px'><b>Last week:</b> {escape(goals.summary(lb['did']))}. "
                 f"<a href='{escape(base)}/#plan'>Plan this week</a></p>")
    if today_line:
        h.append(f"<p style='font-size:15px;margin:0 0 6px'><b>Today's plan:</b> {escape(today_line)}</p>")
    h += [f"<p style='font-size:15px'><b>{escape(label)}:</b> {escape(dua)}</p>",
         f"<h3>Ready for you ({len(ready)})</h3><ul>"]
    h.append(li([f"<b>{escape(_co(j['company']))}</b> · {escape(j['title'])}{' · ' + escape(j['pay']) if j['pay'] else ''}<br>"
                 f"<a href='{escape(base)}/job/{escape(j['id'])}'>Review</a> · finish on Mac: <code>autoapply-finish {escape(j['id'])}</code>"
                 for j in ready]) or "<li>Nothing new today</li>")
    if todo:
        h.append(f"</ul><h3>To do ({len(todo)})</h3><ul>")
        h.append(li([f"<b>{escape(n['title'])}</b> · {escape(n['about'])}<br><span style='color:#666'>{escape(n['why'])}</span>"
                     for n in todo[:8]]))
    if ivs:
        h.append(f"</ul><h3>Interviews ({len(ivs)})</h3><ul>")
        h.append(li([f"<b>{escape(_co(r['job']['company']))}</b> · {escape(r['job']['title'])} · " + (
            f"<a href='{escape(base)}/prep/{escape(r['job']['id'])}'>Prep pack</a>" if r["state"] == "ready" else
            ("prep pack updating next run" if r["state"] == "update" else "prep pack next run")) for r in ivs]))
    h.append(f"</ul><h3>New replies ({len(news)})</h3><ul>")
    h.append(li([f"<b>{escape(LABELS.get(e['kind'], e['kind']))}</b>: {escape(e['sender'].split(' <')[0])} · {escape(e['subject'])}"
                 for e in _good_first(news)]) or "<li>None yet</li>")
    if any(e["kind"] == "rejected" for e in news):
        h.append("</ul><p style='color:#555;font-size:14px'>The closed ones need nothing from you. Most applications end this way, even good ones.</p><ul>")
    h.append(f"</ul><h3>Applications</h3><p>{s['applied']} sent · {s['interviews']} interviews · {s['waiting']} still in play · "
             f"{s['rejected']} closed · {s['no_reply']} no reply yet · {s['response_rate']}% response rate</p>")
    h.append("<table cellpadding='4' style='border-collapse:collapse;font-size:13px'>" + "".join(
        f"<tr><td style='color:#666'>{escape(j['applied_label'])}</td><td>{escape(_co(j['company']))}</td>"
        f"<td>{escape(j['title'])}</td><td><b>{escape(LABELS.get(j['state'], j['state']))}</b></td></tr>" for j in s["applications"][:15]) + "</table>")
    if stale:
        h.append("<p style='color:#b42318'><b>Check:</b> " + escape("; ".join(f"{r['label']} {r['state']} ({r['when']})" for r in stale)) + "</p>")
    if base:
        h.append(f"<p><a href='{escape(base)}/'>Open the dashboard</a></p>")
    h.append("<p style='color:#888;font-size:12px;border-top:1px solid #eee;padding-top:10px;margin-top:20px'>jobsearchPal, part of "
             "<a href='https://palstack.io' style='color:#888'>palStack.io</a>: privacy-first tools that run on your own computer.</p>")
    html = "<div style='font:14px/1.5 -apple-system,Segoe UI,Arial,sans-serif;max-width:640px'>" + "".join(h) + "</div>"
    return subject, text, html


def send(subject: str, text: str, html: str) -> str:
    """Sends the brief from the main inbox (Gmail, iCloud or Yahoo) to BRIEF_TO, or to itself."""
    from . import mailboxes
    acct = mailboxes.main()
    if not acct:
        raise RuntimeError("set GMAIL_USER and GMAIL_APP_PASSWORD in .env, or connect your email on Setup")
    user, pw = acct["user"], acct["password"]
    to = os.environ.get("BRIEF_TO") or user
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    host, port, mode = mailboxes.PROVIDERS[acct["provider"]]["smtp"]
    if mode == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(user, pw)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, pw)
            smtp.send_message(msg)
    return to
