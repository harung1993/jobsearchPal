"""Sign-in: one account, a signed cookie, a throttle, the finish key on /bundle and /file, and the CLI reset."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from autoapply import auth, cli
from autoapply.config import Settings
from autoapply.db import DB
from autoapply.web import make_app
from web_client import EMAIL, PASSWORD, client

HTML = {"accept": "text/html"}


@pytest.fixture
def app(tmp_path):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={})
    db = DB(s.data_dir / "t.db")
    plan = {"url": "u", "ats": "greenhouse", "files": {}, "answers": {}}
    db.upsert_job({"id": "manual:gh", "ats": "greenhouse", "company": "Acme", "title": "AE", "location": "",
                   "url": "u", "apply_url": "u", "description": ""})
    db.update("manual:gh", status="filled", plan_json=plan, report_json={})
    auth.save(s.data_dir, EMAIL, PASSWORD)
    return s, db


def _login(c, email=EMAIL, password=PASSWORD, nxt="/"):
    return c.post("/login", data={"email": email, "password": password, "next": nxt}, follow_redirects=False)


def test_wrong_and_right_password(app):
    s, db = app
    c = TestClient(make_app(s, db))
    assert c.get("/stats", headers=HTML, follow_redirects=False).headers["location"] == "/login?next=/stats"
    assert c.get("/stats").status_code == 401  # not a browser page load: no redirect
    page = c.get("/login").text
    assert "Sign in" in page and "Emails" not in page and "badge" not in page  # no nav, no waiting-email count
    assert _login(c, password="wrong password!").status_code == 401
    assert _login(c, email="someone@else.org").status_code == 401  # right password, wrong email
    r = _login(c, email=" ME@example.org ", nxt="/stats")
    assert r.status_code == 303 and r.headers["location"] == "/stats"
    ck = r.headers["set-cookie"].lower()
    assert "httponly" in ck and "samesite=lax" in ck and "max-age=2592000" in ck and "secure" not in ck
    assert c.get("/stats").status_code == 200
    assert c.get("/login", follow_redirects=False).headers["location"] == "/"  # already signed in


def test_tampered_and_expired_cookies(app):
    s, db = app
    c = TestClient(make_app(s, db))
    acct = auth.load(s.data_dir)
    good = auth.make_cookie(acct)
    exp, sig = good.split(".")
    for bad in (f"{int(exp) + 999}.{sig}", f"{exp}.{'0' * len(sig)}", "garbage", "",
                auth.make_cookie(acct, now=time.time() - auth.MAX_AGE - 5)):  # the last one has expired
        c.cookies.clear()
        c.cookies.set(auth.COOKIE, bad)
        assert c.get("/").status_code == 401, bad
    c.cookies.clear()
    c.cookies.set(auth.COOKIE, good)
    assert c.get("/stats").status_code == 200


def test_logout_and_reset_sign_everyone_out(app, monkeypatch):
    s, db = app
    c, other = client(s, db), client(s, db)
    assert c.get("/stats").status_code == 200
    r = c.post("/logout", follow_redirects=False)
    assert r.headers["location"] == "/login" and auth.COOKIE in r.headers["set-cookie"]
    assert c.get("/stats").status_code == 401
    assert other.get("/stats").status_code == 200
    answers = iter(["a brand new password", "a brand new password"])
    cli.reset_password(s, ask_secret=lambda _: next(answers))
    assert other.get("/stats").status_code == 401  # the key comes from the stored hash, so old cookies stop working
    assert _login(TestClient(c.app), password=PASSWORD).status_code == 401
    assert _login(TestClient(c.app), password="a brand new password").status_code == 303


def test_reset_password_checks_and_creates(tmp_path, monkeypatch):
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={})
    with pytest.raises(SystemExit, match="at least 10"):
        cli.reset_password(s, ask=lambda _: "me@example.org", ask_secret=lambda _: "short")
    pw = iter(["one password here", "another password"])
    with pytest.raises(SystemExit, match="don't match"):
        cli.reset_password(s, ask=lambda _: "me@example.org", ask_secret=lambda _: next(pw))
    assert auth.load(s.data_dir) is None
    cli.reset_password(s, ask=lambda _: "me@example.org", ask_secret=lambda _: "one password here")
    acct = auth.load(s.data_dir)
    assert acct["email"] == "me@example.org" and auth.verify(acct, "me@example.org", "one password here")
    assert json.loads((s.data_dir / "secrets.json").read_text())["AUTOAPPLY_TOKEN"]  # finish key made too


@pytest.mark.parametrize("nxt", ["//evil.example", "/\\evil.example", "https://evil.example", "evil", "/x\r\nSet-Cookie: a=b"])
def test_bad_next_goes_home(app, nxt):
    s, db = app
    c = TestClient(make_app(s, db))
    assert _login(c, nxt=nxt).headers["location"] == "/"
    assert f'value="{nxt}"' not in c.get("/login", params={"next": nxt}).text.replace("&#34;", '"')


def test_throttle_after_five_wrong_tries(app):
    s, db = app
    c = TestClient(make_app(s, db))
    for _ in range(auth.TRIES):
        assert _login(c, password="not the password").status_code == 401
    r = _login(c)  # even the right password waits
    assert r.status_code == 429 and "Wait a few minutes" in r.text
    t = auth.Throttle()
    for _ in range(auth.TRIES):
        t.fail("ip", now=1000)
    assert t.blocked("ip", now=1000 + auth.WINDOW - 1) and not t.blocked("ip", now=1000 + auth.WINDOW + 1)


def test_finish_key_still_opens_bundle_and_file_only(app, monkeypatch):
    s, db = app
    monkeypatch.setenv("AUTOAPPLY_TOKEN", "machine-key-123")
    c = TestClient(make_app(s, db))
    r = c.get("/bundle/manual:gh", params={"t": "machine-key-123"}, follow_redirects=False)
    assert r.status_code == 200 and r.json()["job"]["company"] == "Acme" and "set-cookie" not in r.headers
    assert c.get("/file/resume/manual:gh", params={"t": "machine-key-123"}).status_code == 404  # past the gate, no such file
    assert c.get("/bundle/manual:gh", params={"t": "wrong"}).status_code == 401
    assert c.get("/stats", params={"t": "machine-key-123"}).status_code == 401  # not a password for pages
    monkeypatch.setenv("AUTOAPPLY_TOKEN", "change-me-long-random")  # the old .env.example placeholder never counts
    assert c.get("/bundle/manual:gh", params={"t": "change-me-long-random"}).status_code == 401


def test_upgrade_needs_the_old_token(tmp_path, monkeypatch):
    """An install that had a dashboard password and no account: only its owner may create the account."""
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={})
    db = DB(s.data_dir / "t.db")
    monkeypatch.setenv("AUTOAPPLY_TOKEN", "old-token-abc")
    c = TestClient(make_app(s, db))
    form = {"email": "me@example.org", "password": "long enough 1", "again": "long enough 1"}
    assert c.get("/?t=old-token-abc", headers=HTML, follow_redirects=False).headers["location"] == "/account?t=old-token-abc"
    assert "already had a password" in c.get("/account").text
    assert c.post("/account", data=form).status_code == 403 and auth.load(s.data_dir) is None
    assert "Create account" in c.get("/account?t=old-token-abc").text
    c.cookies.set("aa", "old-token-abc")  # the old cookie proves it too
    r = c.post("/account", data=form, follow_redirects=False)
    assert r.status_code == 303 and auth.load(s.data_dir)
    assert c.get("/stats").status_code == 200


def test_placeholder_token_in_env_is_replaced_once(tmp_path, monkeypatch):
    """An old .env with the example token: the account still gets a real finish key, and it stays the same."""
    from autoapply.prefs import Prefs
    s = Settings(root=tmp_path, raw={"data_dir": str(tmp_path / "data")}, profile={})
    monkeypatch.setenv("AUTOAPPLY_TOKEN", "change-me-long-random")
    auth.ensure_token(Prefs(s.data_dir, s.raw))
    first = auth.machine_token()
    assert first and first == json.loads((s.data_dir / "secrets.json").read_text())["AUTOAPPLY_TOKEN"]
    monkeypatch.setenv("AUTOAPPLY_TOKEN", "change-me-long-random")  # as after a restart that reloads .env
    auth.ensure_token(Prefs(s.data_dir, s.raw))
    assert auth.machine_token() == first
