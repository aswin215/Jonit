"""Install the pipeline as a macOS launchd job (the Mac's built-in scheduler, like cron)."""

import plistlib
import subprocess
import sys
from pathlib import Path

from .config import ROOT
from .pipeline import LOG_DIR

LABEL = "com.jobagent.pipeline"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
EVERY_HOURS = 6


def install(every_hours: int = EVERY_HOURS) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "jobagent", "pipeline"],
        "WorkingDirectory": str(ROOT),
        "StartInterval": every_hours * 3600,  # a run missed while asleep happens on wake
        "RunAtLoad": False,
        # launchd starts with a bare PATH; pdflatex lives in /Library/TeX/texbin
        "EnvironmentVariables": {"PATH": "/Library/TeX/texbin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": str(LOG_DIR / "launchd.out.log"),
        "StandardErrorPath": str(LOG_DIR / "launchd.err.log"),
    }
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    PLIST.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "load", str(PLIST)], check=True)
    return PLIST


def uninstall() -> None:
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    PLIST.unlink(missing_ok=True)


def status() -> str:
    loaded = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True).returncode == 0
    if not PLIST.exists():
        return "not installed"
    hours = plistlib.loads(PLIST.read_bytes())["StartInterval"] // 3600
    return f"{'loaded' if loaded else 'installed but not loaded'}, runs every {hours} h; logs in {LOG_DIR}"


def run_now() -> None:
    subprocess.run(["launchctl", "kickstart", f"gui/{__import__('os').getuid()}/{LABEL}"], check=True)
