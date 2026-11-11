"""The app's own font is served without sign-in (the sign-in page uses it), and nothing outside autoapply/static is."""
from fastapi.testclient import TestClient

from autoapply import auth
from autoapply.config import Settings
from autoapply.db import DB
from autoapply.web import make_app


def test_font_served_signed_out_and_nothing_else(tmp_path):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={})
    db = DB(s.data_dir / "t.db")
    auth.save(s.data_dir, "me@example.org", "correct horse battery")
    c = TestClient(make_app(s, db))
    r = c.get("/static/fonts/figtree-latin-wght.woff2")
    assert r.status_code == 200 and r.content[:4] == b"wOF2" and "immutable" in r.headers["cache-control"]
    for bad in ("/static/../web.py", "/static/%2e%2e/web.py", "/static/fonts/%2e%2e/%2e%2e/web.py"):
        r = c.get(bad)
        assert r.status_code in (401, 404) and b"def make_app" not in r.content
    assert c.get("/static/fonts/nope.woff2").status_code == 404
    assert c.get("/", headers={"accept": "text/html"}, follow_redirects=False).status_code == 303  # the rest still needs sign-in
    assert "Your search," in c.get("/login").text
