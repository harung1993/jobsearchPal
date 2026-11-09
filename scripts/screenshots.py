"""Regenerates the README screenshots in docs/ from fictional demo data. Needs Playwright's Chromium.
    python3 scripts/screenshots.py            # writes docs/*.png
It builds a demo folder with scripts/demo-data.py, serves it on 127.0.0.1:8799 and captures each page.
"""
import os, subprocess, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright

repo = Path(__file__).resolve().parents[1]
demo = Path(tempfile.mkdtemp(prefix="upal-demo-"))
subprocess.run([sys.executable, str(repo / "scripts" / "demo-data.py"), str(demo)], check=True, cwd=repo)
env = {**os.environ, "PYTHONPATH": str(repo), "GMAIL_USER": "demo@example.org", "GMAIL_APP_PASSWORD": "demo"}
env.pop("AUTOAPPLY_TOKEN", None)
srv = subprocess.Popen([sys.executable, "-m", "autoapply.cli", "serve"], cwd=demo, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(4)
    base = "http://127.0.0.1:8799"
    shots = [  # (file, path, width, height, theme, full page)
        ("dashboard.png", "/", 1440, 900, "light", True),
        ("dashboard-phone.png", "/", 390, 844, "light", False),
        ("work-search.png", "/dua", 1440, 900, "light", True),
        ("leads.png", "/leads", 1440, 900, "light", True),
        ("skills.png", "/skills", 1440, 900, "light", True),
        ("stats-dark.png", "/stats", 1440, 900, "dark", True),
        ("emails.png", "/emails?show=all", 1440, 900, "light", False),
        ("settings.png", "/settings", 1440, 900, "light", False),
        ("setup.png", "/setup", 1440, 900, "light", False),
    ]
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        pg = ctx.new_page()  # sign in once with the demo account from demo-data.py; the cookie is shared
        pg.goto(base + "/login")
        pg.fill("input[name=email]", "demo@example.org")
        pg.fill("input[name=password]", "demo password")
        pg.click("button")
        pg.wait_for_url(base + "/")
        cookies = ctx.cookies()
        pg.close()
        for name, path, w, h, theme, full in shots:
            c = b.new_context(viewport={"width": w, "height": h}, color_scheme=theme)
            c.add_cookies(cookies)
            pg = c.new_page()
            pg.goto(base + path)
            pg.evaluate(f"localStorage.setItem('aa-theme', '{theme}')")
            pg.goto(base + path)
            pg.wait_for_timeout(700)
            pg.screenshot(path=str(repo / "docs" / name), full_page=full)
            c.close()
            print("docs/" + name)
        b.close()
finally:
    srv.terminate()
