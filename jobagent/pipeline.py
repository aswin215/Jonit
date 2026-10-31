"""The unattended run: discover -> rank -> tailor the best new matches -> open the review session.

Scheduled by launchd (see schedule.py). Everything is capped so a run can't spend much:
at most MAX_TAILOR_PER_RUN resumes per run and MAX_TAILOR_PER_DAY per day.
"""

import datetime as dt
import os
import subprocess
import sys
import time
import traceback

from . import db, discover, rank, tailor
from .config import DATA_DIR, ROOT, load_preferences

MAX_TAILOR_PER_RUN = 5
MAX_TAILOR_PER_DAY = 10
LOG_DIR = DATA_DIR / "logs"
REVIEW_PID = DATA_DIR / "review.pid"


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "pipeline.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def tailored_today() -> int:
    midnight = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
    return db.conn().execute(  # jobs, not versions: re-tailoring one job doesn't use up the cap
        "SELECT COUNT(DISTINCT job_id) FROM resume_versions WHERE created_at >= ?", (midnight,)).fetchone()[0]


def review_running() -> bool:
    try:
        os.kill(int(REVIEW_PID.read_text()), 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def start_review() -> None:
    if review_running():
        log("review session already open; it will pick up new jobs by itself")
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = open(LOG_DIR / "review.log", "a")
    subprocess.Popen([sys.executable, "-m", "jobagent", "review"], cwd=ROOT, stdout=out, stderr=out,
                     start_new_session=True)
    log("opened the review session")


def run(open_review: bool = True) -> dict:
    log("pipeline start")
    stats = discover.run()
    log(f"discover: {stats['new']} new of {stats['fetched']} fetched; {len(stats['errors'])} board errors")
    ranked = rank.run(limit=300)
    log(f"rank: {ranked['passed_filters']} passed filters, {ranked['scored']} scored")

    budget = min(MAX_TAILOR_PER_RUN, MAX_TAILOR_PER_DAY - tailored_today())
    min_score = load_preferences().get("min_fit_score", 70)
    picks = db.conn().execute(
        "SELECT j.id, j.company, j.title, m.fit_score FROM matches m JOIN jobs j ON j.id = m.job_id "
        "WHERE j.status = 'scored' AND m.fit_score >= ? ORDER BY m.fit_score DESC LIMIT ?",
        (min_score, max(budget, 0)),
    ).fetchall()
    tailored = 0
    for job in picks:
        try:
            result = tailor.run(job["id"])
            tailored += 1
            flag = "" if not result["issues"] else f" ({len(result['issues'])} issues to review)"
            log(f"tailored {job['fit_score']} {job['company']} - {job['title']}{flag}")
        except Exception:
            log(f"tailor failed for {job['id']}:\n{traceback.format_exc(limit=3)}")
    if budget <= 0:
        log(f"daily cap of {MAX_TAILOR_PER_DAY} resumes reached; tailoring resumes tomorrow")

    ready = db.conn().execute(
        "SELECT COUNT(*) FROM jobs WHERE status = 'tailored' AND source = 'greenhouse'").fetchone()[0]
    if open_review and ready:
        start_review()
    log(f"pipeline done: tailored {tailored}, {ready} Greenhouse applications ready to review")
    return {"tailored": tailored, "ready": ready}
