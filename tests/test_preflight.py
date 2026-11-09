"""Pre-submit checks: documents and form must pass before Submit unlocks."""
import json
import os
import time

import docx

from autoapply import preflight


def setup(tmp_path, monkeypatch, resume_text, cover_text, pages=(2, 1)):
    m = tmp_path / "materials"
    m.mkdir()
    d = docx.Document()
    d.add_paragraph("Senior Data Analyst, Example University  Mar 2019 - Sep 2026")
    d.add_paragraph("Data Analyst, Acme  Jan 2017 – Feb 2019")
    d.save(m / "Doe Resume - Base.docx")
    app = tmp_path / "data" / "applications" / "kestrel"
    app.mkdir(parents=True)
    for n in ("Doe Resume - Kestrel", "Doe Cover Letter - Kestrel"):
        (app / f"{n}.docx").write_bytes(b"x")
        time.sleep(0.01)
        (app / f"{n}.pdf").write_bytes(b"%PDF")
    texts = {"Doe Resume - Kestrel.pdf": (resume_text, pages[0]), "Doe Cover Letter - Kestrel.pdf": (cover_text, pages[1])}
    monkeypatch.setattr(preflight, "pdf_text", lambda p: texts[p.name])
    monkeypatch.setattr(preflight, "page_texts", lambda p: [])
    plan = {"files": {"resume": str(app / "Doe Resume - Kestrel.pdf"), "cover_letter": str(app / "Doe Cover Letter - Kestrel.pdf")}}
    return app, plan


PROFILE = {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com", "phone": "(555) 010-0000"}
GOOD = "Jane Doe jane@example.com\nSenior Data Analyst Mar 2019 - Sep 2026\nData Analyst Jan 2017 - Feb 2019"


def test_good_application_passes(tmp_path, monkeypatch):
    _, plan = setup(tmp_path, monkeypatch, GOOD, "Dear Kestrel team, Jane Doe jane@example.com")
    report = {"filled": [{"label": "Email", "value": "jane@example.com"}], "unanswered": [{"label": "Pronouns", "required": False}]}
    checks = preflight.check({"company": "Kestrel"}, plan, report, PROFILE, tmp_path, ["Brightline"])
    assert not [c for c in checks if not c["ok"]], [c for c in checks if not c["ok"]]


def test_problems_lock_submit(tmp_path, monkeypatch):
    app, plan = setup(tmp_path, monkeypatch, "Jane Doe jane@example.com\nSenior Data Analyst Mar 2019 - Sep 2026 [Company] TODO",
                      "Dear Brightline team, Jane Doe", pages=(3, 1))
    now = time.time()
    os.utime(app / "Doe Cover Letter - Kestrel.docx", (now + 30, now + 30))  # docx edited after the PDF
    report = {"unanswered": [{"label": "Why Kestrel?", "required": True}],
              "held": [{"label": "Gender", "required": True, "value": ""}],
              "filled": [{"label": "Email", "value": "old@example.com"}]}
    checks = preflight.check({"company": "Kestrel"}, plan, report, PROFILE, tmp_path, ["Brightline"])
    failed = {c["name"] for c in preflight.blocking(checks)}
    assert {"At most 2 pages", "No placeholder text", "Every job date from your base resume",
            "PDF is up to date with the Word file", "Names Kestrel", "Every required question answered",
            "Required consents chosen by you", "Email matches your profile"} <= failed
    assert any(c["name"] == "No other company's name" and not c["ok"] and not c["hard"] for c in checks)
    missing = next(c for c in checks if c["name"] == "Every job date from your base resume")["detail"]
    assert "jan 2017 - feb 2019" in missing


def test_phone_check_ignores_a_same_label_consent_answer(tmp_path, monkeypatch):
    # Ashby: "Phone" (the number) and "Phone" (text-message consent) both end up in the filled list.
    _, plan = setup(tmp_path, monkeypatch, GOOD, "Dear Kestrel team, Jane Doe jane@example.com")
    report = {"filled": [{"label": "Phone", "value": "(555) 010-0000"},
                         {"label": "Phone", "value": "No - I do not consent to receiving text messages"}]}
    checks = preflight.check({"company": "Kestrel"}, plan, report, PROFILE, tmp_path, [])
    assert next(c for c in checks if c["name"] == "Phone matches your profile")["ok"]
