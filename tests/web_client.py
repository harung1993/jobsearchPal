"""A dashboard test client that is already signed in (sign-in is required on every page)."""
from fastapi.testclient import TestClient

from autoapply import auth
from autoapply.web import make_app

EMAIL, PASSWORD = "me@example.org", "correct horse battery"


def client(s, db, signed_in: bool = True) -> TestClient:
    c = TestClient(make_app(s, db))
    if signed_in:
        if not auth.load(s.data_dir):
            auth.save(s.data_dir, EMAIL, PASSWORD)
        r = c.post("/login", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=False)
        assert r.status_code == 303, r.text
    return c
