"""More than one email address, and Gmail, iCloud or Yahoo as the main inbox."""
import json

from autoapply import alerts, brief, emailsync, mailboxes

MSG = (b"Message-ID: <%s@x>\r\nFrom: LinkedIn <jobalerts-noreply@linkedin.com>\r\nSubject: New jobs\r\n"
       b"Date: Tue, 3 Nov 2026 08:00:00 -0500\r\n\r\nAnalytics Engineer at Hooli")


class FakeIMAP:
    log = []

    def __init__(self, host):
        self.host = host
        FakeIMAP.log.append(("connect", host))
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def login(self, u, p): FakeIMAP.log.append(("login", u))

    def list(self):
        if self.host == "imap.gmail.com":
            return "OK", [b'(\\All) "/" "[Gmail]/All Mail"', b'(\\Junk) "/" "[Gmail]/Spam"', b'(\\Trash) "/" "[Gmail]/Trash"']
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Archive) "/" "Archive"',
                      b'(\\HasNoChildren \\Junk) "/" "Junk"', b'(\\HasNoChildren \\Trash) "/" "Deleted Messages"',
                      b'(\\HasNoChildren \\Sent) "/" "Sent Messages"']

    def select(self, box, readonly=False):
        assert readonly
        FakeIMAP.log.append(("select", self.host, box))
        return "OK", [b"1"]

    def search(self, *a):
        FakeIMAP.log.append(("search", self.host, a))
        return "OK", [b"1"]

    def fetch(self, i, what):
        assert "PEEK" in what
        mid = b"same" if self.host == "imap.gmail.com" else b"icloud-only"
        return "OK", [(b"1", MSG % mid)]


def env(monkeypatch, **kv):
    for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "EMAIL_PROVIDER", "EXTRA_INBOXES", "OWN_ADDRESSES"):
        monkeypatch.delenv(k, raising=False)
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def test_accounts_main_first_extras_and_own_addresses(monkeypatch):
    env(monkeypatch, GMAIL_USER="me@gmail.com", GMAIL_APP_PASSWORD="x", OWN_ADDRESSES="Me@Outlook.com, junk",
        EXTRA_INBOXES=json.dumps([{"provider": "icloud", "user": "me@icloud.com", "password": "y"},
                                  {"provider": "outlook", "user": "bad@outlook.com", "password": "z"},
                                  {"provider": "gmail", "user": "ME@gmail.com", "password": "dup"}]))
    acc = mailboxes.accounts()
    assert [a["user"] for a in acc] == ["me@gmail.com", "me@icloud.com"]  # unknown provider and duplicate dropped
    assert mailboxes.own_addresses() == {"me@gmail.com", "me@icloud.com", "ME@gmail.com".lower(), "me@outlook.com"}
    assert emailsync.is_own("ME@OUTLOOK.COM") and not emailsync.is_own("recruiter@acme.com")
    assert mailboxes.provider_for("x@hotmail.com") == "outlook" and mailboxes.provider_for("x@me.com") == "icloud"


def test_reads_every_inbox_and_uses_plain_search_off_gmail(monkeypatch):
    env(monkeypatch, GMAIL_USER="me@gmail.com", GMAIL_APP_PASSWORD="x",
        EXTRA_INBOXES=json.dumps([{"provider": "icloud", "user": "me@icloud.com", "password": "y"}]))
    monkeypatch.setattr(alerts.imaplib, "IMAP4_SSL", FakeIMAP)
    FakeIMAP.log = []
    got = list(alerts.messages(3, ["linkedin.com"], gmail_queries=["recruiter"], words=["recruiter"]))
    assert {g[0] for g in got} == {"<same@x>", "<icloud-only@x>"}
    selects = [e[2] for e in FakeIMAP.log if e[0] == "select" and e[1] == "imap.mail.me.com"]
    assert selects == ["INBOX", '"Archive"', '"Junk"', '"Deleted Messages"']
    icloud = [e[2] for e in FakeIMAP.log if e[0] == "search" and e[1] == "imap.mail.me.com"]
    assert not any("X-GM-RAW" in a for a in icloud) and any("TEXT" in a for a in icloud)
    gmail = [e[2] for e in FakeIMAP.log if e[0] == "search" and e[1] == "imap.gmail.com"]
    assert any("X-GM-RAW" in a for a in gmail) and not any("TEXT" in a for a in gmail)


def test_icloud_main_inbox_sent_mail_and_brief(monkeypatch):
    env(monkeypatch, GMAIL_USER="me@icloud.com", GMAIL_APP_PASSWORD="x", EMAIL_PROVIDER="icloud")
    monkeypatch.setattr(alerts.imaplib, "IMAP4_SSL", FakeIMAP)
    FakeIMAP.log = []
    list(alerts.sent_mail(5))
    assert ("select", "imap.mail.me.com", '"Sent Messages"') in FakeIMAP.log
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=0): sent["at"] = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): sent["tls"] = True
        def login(self, u, p): sent["user"] = u
        def send_message(self, m): sent["to"] = m["To"]
    monkeypatch.setattr(brief.smtplib, "SMTP", FakeSMTP)
    assert brief.send("s", "t", "<p>h</p>") == "me@icloud.com"
    assert sent == {"at": ("smtp.mail.me.com", 587), "tls": True, "user": "me@icloud.com", "to": "me@icloud.com"}


def test_setup_forwarded_and_extra_inbox(tmp_path, monkeypatch):
    from test_runlog import make
    env(monkeypatch, GMAIL_USER="me@gmail.com", GMAIL_APP_PASSWORD="x")
    s, db, c = make(tmp_path)
    html = c.get("/setup").text
    assert "Other addresses you apply from" in html and "iCloud Mail" in html and "One email" not in html
    c.post("/setup/email/forwarded", data={"addresses": "me@outlook.com\nme@gmail.com, Old@Yahoo.com"})
    assert mailboxes.forwarded() == ["me@outlook.com", "old@yahoo.com"]
    html = c.get("/setup").text
    assert "Keep a copy of forwarded messages" in html and "Mailboxes, pick the address" in html
    r = c.post("/setup/email/forwarded", data={"addresses": "nope"}, headers={"x-in-page": "1"})
    assert r.status_code == 400
    from autoapply import setup as setup_mod
    monkeypatch.setattr(setup_mod, "test_gmail", lambda u, p, prov="gmail": "" if p == "good" else "refused")
    r = c.post("/setup/email/inbox", data={"provider": "yahoo", "user": "old@yahoo.com", "password": "bad"}, headers={"x-in-page": "1"})
    assert r.status_code == 400 and "refused" in r.json()["detail"]
    r = c.post("/setup/email/inbox", data={"provider": "gmail", "user": "x@hotmail.com", "password": "good"}, headers={"x-in-page": "1"})
    assert r.status_code == 400 and "Forward" in r.json()["detail"]
    c.post("/setup/email/inbox", data={"provider": "yahoo", "user": "old@yahoo.com", "password": "good"})
    assert [x["user"] for x in mailboxes.extras()] == ["old@yahoo.com"] and mailboxes.forwarded() == ["me@outlook.com"]
    assert json.loads((s.data_dir / "secrets.json").read_text())["EXTRA_INBOXES"]
    c.post("/setup/email/inbox", data={"action": "remove", "user": "old@yahoo.com"})
    assert mailboxes.extras() == []
