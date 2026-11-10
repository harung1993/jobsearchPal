"""Finder parsing and filtering, with the ATS APIs stubbed out."""
from autoapply import finder
from autoapply.config import Settings
from autoapply.db import DB


class Resp:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


GH = {"jobs": [
    {"id": 1, "title": "Senior Analytics Engineer", "location": {"name": "Remote - US"},
     "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "content": "&lt;p&gt;dbt &amp; Snowflake&lt;/p&gt;"},
    {"id": 2, "title": "Analytics Engineer Intern", "location": {"name": "Remote"}, "absolute_url": "u", "content": ""},
    {"id": 3, "title": "Staff Data Engineer", "location": {"name": "London, UK"}, "absolute_url": "u", "content": ""},
]}


def test_greenhouse_parse_filter_and_dedupe(monkeypatch, tmp_path):
    monkeypatch.setattr(finder.httpx, "get", lambda *a, **k: Resp(GH))
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path), "boards": [{"ats": "greenhouse", "slug": "acme"}],
                                     "search": {"title_keywords": ["analytics engineer", "data engineer"],
                                                "exclude_keywords": ["intern"], "locations_ok": ["remote", "boston"]}},
                 profile={})
    db = DB(tmp_path / "t.db")
    new = finder.run(s, db)
    assert [j["id"] for j in new] == ["greenhouse:acme:1"]
    assert new[0]["description"] == "dbt & Snowflake"
    assert new[0]["apply_url"].endswith("for=acme&token=1")
    assert finder.run(s, db) == []  # already seen


def test_feeds_and_boards_file(monkeypatch, tmp_path):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if "remoteok" in url:
            return Resp([{"legal": "notice"}, {"id": "9", "position": "Senior Analytics Engineer", "company": "Acme",
                                               "location": "USA", "url": "https://remoteok.com/9", "apply_url": "https://x/apply"}])
        if "workable" in url:
            return Resp({"jobs": [{"shortcode": "AB1", "title": "Data Engineer", "telecommuting": True, "country": "United States",
                                   "url": "https://apply.workable.com/w/j/AB1", "application_url": "https://apply.workable.com/w/j/AB1/apply"}]})
        return Resp({"jobs": []})

    monkeypatch.setattr(finder.httpx, "get", fake_get)
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path), "feeds": ["remoteok"],
                                     "search": {"title_keywords": ["analytics engineer", "data engineer"], "locations_ok": ["remote"]}},
                 profile={})
    assert finder.add_board(s, "workable", "w") == 1
    finder.add_board(s, "workable", "W")  # same board, different case: not added twice
    assert finder.boards(s) == [{"ats": "workable", "slug": "w"}]
    ids = sorted(j["id"] for j in finder.run(s, DB(tmp_path / "t.db")))
    assert ids == ["remoteok:9", "workable:w:AB1"]


def test_location_filter_is_us_only():
    ok = finder.location_ok
    for loc in ["Remote - US", "Remote, USA", "Boston, MA", "Remote", "Remote (US/Canada)", "United States", "", None, "New York, NY"]:
        assert ok(loc, {}), loc
    for loc in ["Remote Poland", "Remote - Spain", "Remote São Paulo", "London, UK", "Remote, EMEA", "Toronto, Canada", "Bengaluru"]:
        assert not ok(loc, {}), loc


def test_null_location_does_not_crash(monkeypatch, tmp_path):
    data = {"jobs": [{"id": 5, "title": "Analytics Engineer", "location": None, "absolute_url": "u", "content": None}]}
    monkeypatch.setattr(finder.httpx, "get", lambda *a, **k: Resp(data))
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path), "boards": [{"ats": "greenhouse", "slug": "a"}],
                                     "search": {"title_keywords": ["analytics engineer"]}}, profile={})
    assert [j["id"] for j in finder.run(s, DB(tmp_path / "t.db"))] == ["greenhouse:a:5"]


RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>HigherEdJobs</title>
<item><title>Data Engineer, Institutional Research</title><link>https://www.higheredjobs.com/admin/details.cfm?JobCode=1</link>
<description>&lt;p&gt;Riverside State University - Boston, MA&lt;/p&gt;</description><guid>1</guid><dc:creator>Riverside State University</dc:creator></item>
<item><title>Professor of History</title><link>https://www.higheredjobs.com/faculty/details.cfm?JobCode=2</link><guid>2</guid></item>
</channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>Jobs</title><entry><title>Senior Data Engineer</title>
<link href="https://example.org/j/9"/><id>tag:9</id><summary>Remote (US)</summary></entry></feed>"""


def test_rss_and_atom_feeds(monkeypatch, tmp_path):
    from autoapply import sources

    class R(Resp):
        def __init__(self, body): self.content = body

    monkeypatch.setattr(sources.httpx, "get", lambda url, **k: R(ATOM if "atom" in url else RSS))
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path), "feeds": [],
                                     "rss_feeds": [{"name": "HEJ", "url": "https://www.higheredjobs.com/search/rss.cfm?JobCat=31"},
                                                   "https://example.org/atom.xml"],
                                     "search": {"title_keywords": ["data engineer"]}}, profile={})
    stats = {}
    new = finder.run(s, DB(tmp_path / "t.db"), stats)
    assert sorted(j["title"] for j in new) == ["Data Engineer, Institutional Research", "Senior Data Engineer"]
    hej = next(j for j in new if "higheredjobs" in j["url"])
    assert hej["company"] == "Riverside State University" and "Boston, MA" in hej["description"]
    assert stats["rss:HEJ"] == {"fetched": 2, "matched": 1, "new": 1, "error": ""}


def test_api_sources_and_missing_keys(monkeypatch, tmp_path):
    from autoapply import sources
    data = {
        "themuse": {"results": [{"id": 5, "name": "Analytics Engineer", "company": {"name": "Acme"},
                                 "locations": [{"name": "Boston, MA"}], "refs": {"landing_page": "https://themuse.com/j/5"},
                                 "contents": "<p>dbt</p>"}]},
        "himalayas": {"jobs": [{"title": "Data Engineer", "companyName": "Beta", "locationRestrictions": ["United States"],
                                "applicationLink": "https://beta.example/apply", "guid": "https://himalayas.app/j/1"}]},
        "jobicy": {"jobs": [{"id": 7, "jobTitle": "Staff Data Engineer", "companyName": "Gamma", "jobGeo": "USA",
                             "url": "https://jobicy.com/j/7"}]},
    }
    monkeypatch.setattr(sources.httpx, "get", lambda url, **k: Resp(next(v for key, v in data.items() if key in url)))
    for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path), "feeds": ["themuse", "himalayas", "jobicy", "adzuna"],
                                     "search": {"title_keywords": ["data engineer", "analytics engineer"]}}, profile={})
    stats = {}
    new = finder.run(s, DB(tmp_path / "t.db"), stats)
    assert {j["company"] for j in new} == {"Acme", "Beta", "Gamma"}
    assert "ADZUNA_APP_ID" in stats["adzuna"]["error"]  # turned on without a key: reported, not fatal


def test_state_codes_count_as_us():
    assert finder.location_ok("Columbus, OH", {"us_only": True})
    assert not finder.location_ok("Remote, Berlin, Germany", {"us_only": True})


def test_rss_bot_check_page_is_a_clear_error(monkeypatch):
    import pytest
    from autoapply import sources

    class R(Resp):
        content = b"<html><head><meta name='ROBOTS' content='NOINDEX, NOFOLLOW'></head><body><script></script></body></html>"

    monkeypatch.setattr(sources.httpx, "get", lambda url, **k: R(None))
    with pytest.raises(RuntimeError, match="job-alert emails"):
        sources.rss("https://example.org/feed")


def test_levels_you_pick_shape_the_ranking():
    """Mid-level titles (no level word) can rank with senior ones once you pick both; nothing picked keeps the old lean."""
    from autoapply.rank import level_of, score
    assert [level_of(t) for t in ("Data Engineer", "Analytics Engineer II", "Senior Data Engineer", "Staff Analytics Engineer",
                                  "Lead Data Architect", "Head of Data", "Junior Data Analyst", "Data Solutions Architect")] == \
        ["mid", "mid", "senior", "senior", "lead", "manager", "entry", "mid"]
    base = {"title_keywords": ["data engineer"]}
    mid, sr = {"title": "Data Engineer", "found_at": "x"}, {"title": "Senior Data Engineer", "found_at": "x"}
    assert score(sr, base, set()) > score(mid, base, set())
    both = {**base, "levels": ["mid", "senior"]}
    assert score(sr, both, set()) == score(mid, both, set())
    assert score({"title": "Data Engineering Manager", "found_at": "x"}, both, set()) < score(mid, both, set())
