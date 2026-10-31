import hashlib
import re
import time
from datetime import datetime, timedelta, timezone

from . import db
from .config import load_companies, load_preferences
from .fetcher import Disallowed, HostPaused, PoliteFetcher
from .sources import ADAPTERS, Job


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def dedupe_hash(job: Job) -> str:
    key = f"{_norm(job.company)}|{_norm(job.title)}|{_norm(job.location)}"
    return hashlib.sha1(key.encode()).hexdigest()


def _too_old(job: Job, max_age_days: int) -> bool:
    if not job.posted_at:
        return False
    try:
        posted = datetime.fromisoformat(job.posted_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return posted < datetime.now(timezone.utc) - timedelta(days=max_age_days)


def add_job(url: str, company: str | None = None) -> Job:
    """Add one posting from its link (Workday for now)."""
    from .sources import workday

    if "myworkdayjobs.com" not in url:
        raise SystemExit("add-job supports Workday links for now; Greenhouse/Lever/Ashby boards go in companies.yaml")
    job = workday.fetch_job(PoliteFetcher(), url, company)
    c = db.conn()
    c.execute(
        "INSERT OR REPLACE INTO jobs (id, company, title, location, remote, description, apply_url, "
        "source, posted_at, dedupe_hash, first_seen, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "COALESCE((SELECT status FROM jobs WHERE id = ?), 'new'))",
        (job.id, job.company, job.title, job.location, int(job.remote), job.description, job.apply_url,
         job.source, job.posted_at, dedupe_hash(job), time.time(), job.id),
    )
    c.commit()
    return job


def _save(c, job: Job) -> int:
    cur = c.execute(
        "INSERT OR IGNORE INTO jobs (id, company, title, location, remote, description, apply_url, "
        "source, posted_at, dedupe_hash, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job.id, job.company, job.title, job.location, int(job.remote), job.description,
         job.apply_url, job.source, job.posted_at, dedupe_hash(job), time.time()),
    )
    return cur.rowcount


def run_feeds(fetcher: PoliteFetcher, prefs: dict, stats: dict) -> None:
    """Curated new-grad lists: filter on the list's own title/location, then open only the survivors."""
    from . import rank
    from .sources import feed

    c = db.conn()
    max_age = prefs.get("max_age_days", 30)
    for src in load_feeds():
        try:
            rows = feed.parse(fetcher.get_text(src["url"], accept="text/plain"))
        except Exception as e:
            stats["errors"].append(f"{src['name']}: {type(e).__name__}: {e}")
            continue
        seen = {r[0] for r in c.execute("SELECT url FROM feed_seen")}
        fresh = [r for r in rows if r.url not in seen]
        added = opened = 0
        for row in fresh:
            outcome, job_id = "filtered", None
            probe = {"company": row.company, "title": row.title, "location": row.location,
                     "remote": int("remote" in row.location.lower())}
            if row.age_days > max_age:
                outcome = "too_old"
            elif rank.passes_filters(probe, prefs):
                job = feed.resolve(fetcher, row)
                opened += 1
                job_id, outcome = job.id, "added"
                added += _save(c, job)
            c.execute("INSERT OR REPLACE INTO feed_seen (url, job_id, outcome, seen_at) VALUES (?, ?, ?, ?)",
                      (row.url, job_id, outcome, time.time()))
            c.commit()
        stats["fetched"] += len(rows)
        stats["new"] += added
        print(f"  {src['name']}: {len(rows)} listed, {len(fresh)} not seen before, "
              f"{opened} matched your filters and were opened, {added} new jobs")


def load_feeds() -> list[dict]:
    from .config import load_yaml

    return load_yaml("companies.yaml").get("feeds", [])


def run() -> dict:
    prefs = load_preferences()
    max_age = prefs.get("max_age_days", 30)
    fetcher = PoliteFetcher()
    c = db.conn()
    stats = {"fetched": 0, "new": 0, "old": 0, "errors": []}

    for company in load_companies():
        adapter = ADAPTERS.get(company["ats"])
        if adapter is None:
            stats["errors"].append(f"{company['name']}: unknown ats '{company['ats']}'")
            continue
        try:
            jobs = adapter(fetcher, company["slug"], company["name"])
        except (HostPaused, Disallowed) as e:
            stats["errors"].append(f"{company['name']}: {e}")
            continue
        except Exception as e:  # one broken board shouldn't stop the run
            stats["errors"].append(f"{company['name']}: {type(e).__name__}: {e}")
            continue

        print(f"  {company['name']}: {len(jobs)} postings")
        for job in jobs:
            stats["fetched"] += 1
            if _too_old(job, max_age):
                stats["old"] += 1
                continue
            cur = c.execute(
                "INSERT OR IGNORE INTO jobs (id, company, title, location, remote, description, apply_url, "
                "source, posted_at, dedupe_hash, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job.id, job.company, job.title, job.location, int(job.remote), job.description,
                 job.apply_url, job.source, job.posted_at, dedupe_hash(job), time.time()),
            )
            stats["new"] += cur.rowcount
        c.commit()
    run_feeds(fetcher, prefs, stats)
    return stats
