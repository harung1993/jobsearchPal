"""Paste a job: a whole pasted job post (LinkedIn page, careers page, email) read into lead fields."""
from pathlib import Path

from autoapply import paste

FIXTURES = Path(__file__).parent / "fixtures"


def FIX(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_linkedin_paste():
    r = paste.read(FIX("paste_linkedin.txt"))
    assert r["company"] == "Liberty Mutual Insurance"
    assert r["title"] == "Director I, Data Science- AI Products"
    assert r["location"] == "Boston, MA" and r["work_setting"] == "on-site"
    assert r["pay"] == "$137K/yr - $257K/yr"
    d = r["description"]
    assert d.startswith("Description") or d.startswith("We are transforming")
    assert "LangChain/LangGraph" in d and "equal opportunity" in d
    for junk in ("Fair Chance Notices", "Reactivate Premium", "More jobs", "Ahold Delhaize", "Jane Doe", "Messaging",
                 "people clicked apply", "$156K"):
        assert junk not in d and junk not in r["title"] and junk not in r["company"]
    assert r["url"] == ""


def test_careers_paste():
    r = paste.read(FIX("paste_careers.txt"))
    assert r["title"] == "Senior Analytics Engineer" and r["company"] == "Hooli"
    assert r["work_setting"] == "remote" and r["location"] == "Remote (US)"
    assert r["pay"].startswith("$150,000")
    assert r["url"] == "https://boards.greenhouse.io/hooli/jobs/4242?gh_src=abc"
    assert "dbt models" in r["description"]


def test_blank_fields_never_crash():
    r = paste.read("Just some words about a job\nwith no pay or place")
    assert set(r) == {"company", "title", "location", "work_setting", "pay", "url", "description"}
    assert r["pay"] == "" and r["location"] == "" and r["work_setting"] == ""
    assert paste.read("")["title"] == ""


def test_is_link():
    assert paste.is_link("  https://boards.greenhouse.io/acme/jobs/1 ")
    assert not paste.is_link("javascript:alert(1)")
    assert not paste.is_link("Title\nhttps://x.io")
