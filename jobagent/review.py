"""Review session: one browser window, one filled application per tab, waiting for you.

- Opens a tab for every tailored, unapplied Greenhouse job and fills it (never clicks Submit).
- Checks for newly tailored jobs every minute and opens tabs for them too.
- When you submit a tab, the application is recorded (resume + job link) on the dashboard.
- When you close a tab without submitting, that job is marked 'skipped' so it isn't reopened.
- Closing the whole window ends the session; unreviewed jobs reopen next time.
"""

import json
import os
import re
import time
from pathlib import Path

from . import db
from .apply import APP_DIR, BROWSER_PROFILE, _confirmed, _fields, _greenhouse_ids, fill_form, plan_answers
from .fetcher import PoliteFetcher
from .pipeline import REVIEW_PID, log

POLL_SECONDS = 60


def _queue(open_ids: set[str]):
    rows = db.conn().execute(
        "SELECT * FROM jobs WHERE status = 'tailored' AND source = 'greenhouse' ORDER BY first_seen").fetchall()
    return [r for r in rows if r["id"] not in open_ids]


def _open(ctx, fetcher, job) -> dict | None:
    version = db.latest_resume(job["id"])
    if version is None:
        return None
    resume_pdf = Path(version["markdown_path"])
    slug, ext = _greenhouse_ids(job["id"])
    data = fetcher.get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{ext}?questions=true")
    plan = plan_answers(job, _fields(data), resume_pdf)
    page = ctx.new_page()
    page.goto(f"https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={ext}",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#first_name", timeout=30000)
    fill_form(page, plan, resume_pdf.name)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", job["id"])
    APP_DIR.mkdir(parents=True, exist_ok=True)
    (APP_DIR / f"{stem}.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    todo = [i["label"][:60] for i in plan if (i["required"] or i["answer"]) and (i["needs_user"] or not i["filled"])]
    log(f"review: opened {job['company']} - {job['title']}" + (f"; check: {'; '.join(todo)}" if todo else ""))
    return {"page": page, "job": job, "version": version, "stem": stem}


def run() -> None:
    from playwright.sync_api import sync_playwright

    REVIEW_PID.write_text(str(os.getpid()))
    fetcher = PoliteFetcher()
    tabs: dict[str, dict] = {}
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=False,
                                                       viewport={"width": 1280, "height": 900})
            blanks = [pg for pg in ctx.pages if pg.url == "about:blank"]
            next_poll = 0.0
            while True:
                if time.time() >= next_poll:
                    for job in _queue(set(tabs)):
                        try:
                            tab = _open(ctx, fetcher, job)
                            if tab:
                                tabs[job["id"]] = tab
                        except Exception as e:
                            log(f"review: could not open {job['id']}: {type(e).__name__}: {str(e)[:150]}")
                    next_poll = time.time() + POLL_SECONDS
                    for blank in blanks:  # drop the starting empty tab once real ones exist
                        if tabs and not blank.is_closed():
                            blank.close()

                try:
                    live = [pg for pg in ctx.pages if not pg.is_closed()]
                except Exception:
                    break
                if not tabs or not live:
                    break  # nothing to review, or you closed the window: unreviewed jobs reopen next time

                for job_id, tab in list(tabs.items()):
                    page = tab["page"]
                    if page.is_closed():  # one tab closed while the window stays open = skip this job
                        db.conn().execute("UPDATE jobs SET status = 'skipped' WHERE id = ?", (job_id,))
                        db.conn().commit()
                        log(f"review: you closed {tab['job']['company']} - {tab['job']['title']}; marked skipped")
                        del tabs[job_id]
                    elif _confirmed(page):
                        db.record_application(job_id, tab["version"]["id"])  # record first: the window may close
                        try:
                            page.screenshot(path=str(APP_DIR / f"{tab['stem']}_confirmation.png"), full_page=True)
                        except Exception:
                            pass
                        log(f"review: SUBMITTED {tab['job']['company']} - {tab['job']['title']}; recorded")
                        del tabs[job_id]
                time.sleep(3)
            try:
                ctx.close()
            except Exception:
                pass
    finally:
        REVIEW_PID.unlink(missing_ok=True)
        log("review session closed")
