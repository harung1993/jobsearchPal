"""Sign-in for the dashboard: one account per install, stdlib only.

The account is one email and a scrypt hash in data/account.json (mode 600). A session is a signed cookie,
`<expiry>.<hmac>`, keyed from the stored hash, so resetting the password signs every browser out.
Forgot the password: `autoapply reset-password` on the server.
AUTOAPPLY_TOKEN is no longer a password: it is only the machine key `autoapply finish` sends as ?t= to
/bundle and /file. It is made silently once the account exists.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

COOKIE = "up_session"
MAX_AGE = 30 * 24 * 3600
MIN_LEN = 10
TRIES, WINDOW = 5, 300  # wrong passwords per IP, then wait WINDOW seconds
PLACEHOLDER_TOKENS = {"", "change-me-long-random"}  # the old .env.example value is public, so it never counts
_N, _R, _P = 2 ** 14, 8, 1


def path(data_dir: Path) -> Path:
    return Path(data_dir) / "account.json"


def load(data_dir: Path) -> dict | None:
    """The account, read fresh every time so a reset from the CLI takes effect without a restart."""
    try:
        a = json.loads(path(data_dir).read_text())
    except (OSError, ValueError):
        return None
    return a if a.get("email") and a.get("hash") else None


def _hash(password: str, salt: bytes, n=_N, r=_R, p=_P) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)


def check_new(email: str, password: str, again: str) -> str:
    """Why a new account or password can't be saved, or '' when it can."""
    if "@" not in (email or "") or len(email.strip()) < 3:
        return "Enter the email address you use for your job search."
    if len(password or "") < MIN_LEN:
        return f"Use at least {MIN_LEN} characters for the password."
    if password != again:
        return "The two passwords don't match."
    return ""


def save(data_dir: Path, email: str, password: str):
    """Writes (or replaces) the account. Replacing it changes the signing key, so old sessions stop working."""
    salt = secrets.token_bytes(16)
    rec = {"email": email.strip(), "hash": f"scrypt${_N}${_R}${_P}${salt.hex()}${_hash(password, salt).hex()}"}
    p = path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.touch(mode=0o600, exist_ok=True)
    os.chmod(tmp, 0o600)
    tmp.write_text(json.dumps(rec))
    os.replace(tmp, p)


def verify(account: dict, email: str, password: str) -> bool:
    try:
        _, n, r, p, salt, want = account["hash"].split("$")
        got = _hash(password or "", bytes.fromhex(salt), int(n), int(r), int(p)).hex()
    except (KeyError, ValueError):
        return False
    same_email = hmac.compare_digest((email or "").strip().lower().encode(), account["email"].strip().lower().encode())
    return hmac.compare_digest(got, want) and same_email


def _key(account: dict) -> bytes:
    return hashlib.sha256(b"unemploymentpal-session\0" + account["hash"].encode()).digest()


def make_cookie(account: dict, now: float | None = None) -> str:
    exp = int((now or time.time()) + MAX_AGE)
    return f"{exp}.{hmac.new(_key(account), str(exp).encode(), hashlib.sha256).hexdigest()}"


def valid_cookie(account: dict | None, value: str | None, now: float | None = None) -> bool:
    if not account or not value or "." not in value:
        return False
    exp, sig = value.split(".", 1)
    if not exp.isdigit() or int(exp) < (now or time.time()):
        return False
    return hmac.compare_digest(sig, hmac.new(_key(account), exp.encode(), hashlib.sha256).hexdigest())


def machine_token() -> str:
    t = os.environ.get("AUTOAPPLY_TOKEN") or ""
    return "" if t in PLACEHOLDER_TOKENS else t


def token_ok(given: str | None) -> bool:
    t = machine_token()
    return bool(t and given) and hmac.compare_digest(given.encode(), t.encode())


def ensure_token(prefs):
    """The `autoapply finish` key, made silently (in data/secrets.json) when missing."""
    if machine_token():
        return
    saved = str(prefs._read(prefs.secrets_path).get("AUTOAPPLY_TOKEN") or "")  # .env may still hold the old placeholder
    t = saved if saved not in PLACEHOLDER_TOKENS else secrets.token_urlsafe(24)
    if t != saved:
        prefs.set_key("AUTOAPPLY_TOKEN", t)
    os.environ["AUTOAPPLY_TOKEN"] = t


def safe_next(nxt: str | None) -> str:
    """Only a path on this site: starts with one '/', never '//' or '/\\' (both mean another host)."""
    n = nxt or ""
    if not n.startswith("/") or n[1:2] in ("/", "\\") or any(c in n for c in "\r\n"):
        return "/"
    return n


class Throttle:
    """Wrong passwords per IP, in memory. TRIES within WINDOW seconds, then wait."""

    def __init__(self):
        self.fails: dict[str, list[float]] = {}

    def _recent(self, ip: str, now: float) -> list[float]:
        self.fails[ip] = [t for t in self.fails.get(ip, []) if now - t < WINDOW]
        return self.fails[ip]

    def blocked(self, ip: str, now: float | None = None) -> bool:
        return len(self._recent(ip, now or time.time())) >= TRIES

    def fail(self, ip: str, now: float | None = None):
        now = now or time.time()
        self._recent(ip, now).append(now)

    def clear(self, ip: str):
        self.fails.pop(ip, None)
