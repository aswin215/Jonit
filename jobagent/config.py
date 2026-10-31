import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "jobagent.db"
RESUME_DIR = DATA_DIR / "resumes"

load_dotenv(ROOT / ".env")

CONTACT_EMAIL = os.environ.get("JOBAGENT_CONTACT_EMAIL", "")


def load_yaml(name: str):
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_profile() -> dict:
    path = CONFIG_DIR / "profile.yaml"
    if not path.exists():
        raise SystemExit(
            "config/profile.yaml not found. Copy config/profile.example.yaml to "
            "config/profile.yaml and fill in your real details."
        )
    return load_yaml("profile.yaml")


def load_preferences() -> dict:
    return load_yaml("preferences.yaml")


def load_companies() -> list[dict]:
    return load_yaml("companies.yaml")["companies"]
