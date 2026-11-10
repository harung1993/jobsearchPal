"""Loads config.yaml and profile.yaml; paths resolve relative to the config file."""
from __future__ import annotations

import json
import os

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Settings:
    root: Path
    raw: dict
    profile: dict

    @property
    def data_dir(self) -> Path:
        p = self.path(self.raw.get("data_dir", "./data"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    def path(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.root / p).resolve()


# Saved from the dashboard (Setup and Settings pages) into data/secrets.json. The environment wins.
SECRET_KEYS = ("AUTOAPPLY_TOKEN", "GMAIL_USER", "GMAIL_APP_PASSWORD", "BRIEF_TO", "OPENROUTER_API_KEY", "NTFY_TOPIC",
               "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "USAJOBS_API_KEY", "USAJOBS_EMAIL",
               "EMAIL_PROVIDER", "EXTRA_INBOXES", "OWN_ADDRESSES")
FROM_SECRETS: set[str] = set()


def apply_secrets(data_dir: Path):
    try:
        saved = json.loads((data_dir / "secrets.json").read_text())
    except (OSError, ValueError):
        return
    for k in SECRET_KEYS:
        if saved.get(k) and (not os.environ.get(k) or k in FROM_SECRETS):
            os.environ[k] = saved[k]
            FROM_SECRETS.add(k)


def apply_dotenv(root: Path):
    """The folder's .env, for commands run by hand (daily.sh and the service load it themselves). Set values win."""
    try:
        lines = (root / ".env").read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if k and k not in os.environ:
            os.environ[k] = v


def load(config_path: str = "config.yaml", profile_path: str | None = None, allow_example: bool = False) -> Settings:
    """allow_example: with no config.yaml yet (a fresh install), start from config.example.yaml so the
    dashboard can open its Setup page. Nothing else runs on the example."""
    cfg = Path(config_path).resolve()
    if not cfg.exists() and allow_example and cfg.with_name("config.example.yaml").exists():
        raw = yaml.safe_load(cfg.with_name("config.example.yaml").read_text()) or {}
        raw["_from_example"] = True
    else:
        if not cfg.exists():
            raise SystemExit(f"{cfg.name} not found. Open the dashboard (autoapply serve) and use its Setup page, "
                             "or copy config.example.yaml to config.yaml.")
        raw = yaml.safe_load(cfg.read_text()) or {}
    prof = Path(profile_path).resolve() if profile_path else cfg.parent / "profile.yaml"
    profile = (yaml.safe_load(prof.read_text()) or {}) if prof.exists() else {}
    s = Settings(root=cfg.parent, raw=raw, profile=profile)
    apply_dotenv(s.root)
    apply_secrets(s.data_dir)
    return s
