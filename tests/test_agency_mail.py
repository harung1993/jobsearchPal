"""Unemployment and RESEA emails: wider official senders, appointment dates, RESEA tasks."""
from datetime import date, datetime

from autoapply import benefits, emailsync
from autoapply.db import DB

AT = datetime(2026, 11, 3, 9, 0)
RESEA_MAIL = ("Your RESEA appointment is scheduled for Tuesday, November 18, 2026 at 10:00 AM at the MassHire "
              "Boston Career Center. Bring your work search log.")


def test_official_senders():
    assert benefits.is_agency("donotreply@masshire.org", "Welcome", "Welcome to the career center orientation",
                              name="MassHire Department of Career Services")
    assert benefits.is_agency("noreply@esd.wa.gov", "Your claim", "unemployment claim")
    assert benefits.is_agency("notices@worksourcega.com", "RESEA", "Your RESEA orientation")
    assert benefits.is_agency("x@dol.state.xx.us", "Notice", "work search")
    assert benefits.is_agency("x@myagency.org", "Notice", "your claim", state_domain="myagency.org")
    assert not benefits.is_agency("jobs@acme.com", "RESEA", "unemployment")       # a company is not the agency
    assert not benefits.is_agency("news@acme.us", "Orientation", "new hire orientation")  # .us alone isn't official
    assert not benefits.is_agency("noreply@mass.gov", "Fishing license", "your license renewal")  # no claim words


def test_appointment_and_due_dates():
    assert benefits.appointment(RESEA_MAIL, AT) == (date(2026, 11, 18), "10:00 AM")
    assert benefits.appointment("Attend orientation on 11/20 at 2:30 p.m.", AT) == (date(2026, 11, 20), "2:30 PM")
    assert benefits.appointment("Welcome to the career centers", AT) is None


def test_resea_letter_becomes_a_task_once(tmp_path):
    db = DB(tmp_path / "t.db")
    emailsync.apply_event(db, [], "<r@x>", "MassHire", "noreply@masshire.org", "RESEA appointment", AT, RESEA_MAIL)
    assert db.get_event("<r@x>")["kind"] == "agency"
    assert benefits.tasks_from_letters(db, days=10_000) == 1
    assert benefits.tasks_from_letters(db, days=10_000) == 0  # once per letter
    t = benefits.tasks(db)[0]
    assert t["kind"] == "resea" and t["due"] == "2026-11-18" and t["title"] == "RESEA appointment at 10:00 AM"
    l = benefits.letters(db)[0]
    assert l["resea"] and l["when"] == "appointment Wed Nov 18, 10:00 AM" or l["when"].startswith("appointment ")


def test_work_search_page_lists_letters(tmp_path):
    from test_runlog import make
    s, db, c = make(tmp_path)
    emailsync.apply_event(db, [], "<r@x>", "MassHire", "noreply@masshire.org", "RESEA appointment", AT, RESEA_MAIL)
    html = c.get("/dua").text
    assert "Unemployment and RESEA emails" in html and "RESEA appointment" in html and "appointment Wed Nov 18" in html
