"""Curated new-grad job lists on GitHub (e.g. speedyapply/2027-SWE-College-Jobs).

The list gives company, title, location, age and an apply link. Rows are filtered on that
first; only the survivors are opened, through the matching ATS adapter, to get the full
job description. Links already handled are remembered, so each one is fetched once.
"""

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from . import Job, html_to_text
from . import workday


@dataclass
class FeedRow:
    company: str
    title: str
    location: str
    url: str
    age_days: int


def parse(markdown: str) -> list[FeedRow]:
    rows = []
    for line in markdown.splitlines():
        if not line.startswith("| <a"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        hrefs = re.findall(r'href="([^"]+)"', line)
        company = re.search(r"<strong>(.*?)</strong>", cells[0])
        age = re.match(r"(\d+)d", cells[-1])
        if len(cells) < 4 or not company or len(hrefs) < 2:
            continue
        rows.append(FeedRow(
            company=html.unescape(company.group(1)),
            title=html.unescape(re.sub(r"<[^>]+>", "", cells[1])),
            location=html.unescape(re.sub(r"<[^>]+>", "", cells[2])),
            url=html.unescape(hrefs[-1]),
            age_days=int(age.group(1)) if age else 0,
        ))
    return rows


def _posted(row: FeedRow) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=row.age_days)).date().isoformat()


def _slug_guesses(row: FeedRow) -> list[str]:
    host = urlparse(row.url).netloc.lower()
    parts = [p for p in host.split(".") if p not in ("www", "careers", "jobs", "com", "io", "co", "net", "org")]
    name = re.sub(r"[^a-z0-9]", "", row.company.lower())
    return list(dict.fromkeys([name] + parts[:1] + [name + "careers"]))


def _greenhouse(fetcher, row: FeedRow) -> Job | None:
    u = urlparse(row.url)
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?]+)/jobs/(\d+)", row.url)
    if m:
        slugs, job_id = [m.group(1)], m.group(2)
    else:
        job_id = (parse_qs(u.query).get("gh_jid") or parse_qs(u.query).get("token") or [None])[0]
        slugs = _slug_guesses(row)
    if not job_id:
        return None
    for slug in slugs:
        try:
            j = fetcher.get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}")
        except Exception:
            continue
        location = (j.get("location") or {}).get("name", "") or row.location
        return Job(id=f"greenhouse:{slug}:{job_id}", company=row.company, title=j.get("title") or row.title,
                   location=location, remote="remote" in location.lower(),
                   description=html_to_text(j.get("content", "")), apply_url=row.url, source="greenhouse",
                   posted_at=j.get("first_published") or j.get("updated_at") or _posted(row))
    return None


def _lever(fetcher, row: FeedRow) -> Job | None:
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", row.url)
    if not m:
        return None
    j = fetcher.get_json(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}?mode=json")
    parts = [j.get("descriptionPlain", "")] + [
        f"{s.get('text', '')}\n{html_to_text(s.get('content', ''))}" for s in j.get("lists", [])
    ] + [j.get("additionalPlain", "")]
    location = (j.get("categories") or {}).get("location") or row.location
    return Job(id=f"lever:{m.group(1)}:{m.group(2)}", company=row.company, title=j.get("text") or row.title,
               location=location, remote=j.get("workplaceType") == "remote",
               description="\n\n".join(p for p in parts if p).strip(), apply_url=row.url, source="lever",
               posted_at=_posted(row))


_ashby_boards: dict[str, dict] = {}


def _ashby(fetcher, row: FeedRow) -> Job | None:
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", row.url)
    if not m:
        return None
    slug, job_id = m.groups()
    if slug not in _ashby_boards:  # one request per company board, shared by all its rows
        board = fetcher.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        _ashby_boards[slug] = {j["id"]: j for j in board.get("jobs", [])}
    j = _ashby_boards[slug].get(job_id)
    if not j:
        return None
    return Job(id=f"ashby:{slug}:{job_id}", company=row.company, title=j["title"],
               location=j.get("location") or row.location, remote=bool(j.get("isRemote")),
               description=j.get("descriptionPlain", ""), apply_url=row.url, source="ashby",
               posted_at=j.get("publishedAt") or _posted(row))


def _json_ld(fetcher, row: FeedRow) -> Job | None:
    """Most other career sites embed a schema.org JobPosting; use its description when present."""
    page = fetcher.get_text(row.url, accept="text/html")
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting" and item.get("description"):
                return Job(id=f"link:{row.url}", company=row.company, title=item.get("title") or row.title,
                           location=row.location, remote=False, description=html_to_text(item["description"]),
                           apply_url=row.url, source="link", posted_at=item.get("datePosted") or _posted(row))
    return None


def resolve(fetcher, row: FeedRow) -> Job:
    """Full job for a feed row. Falls back to the list's own fields when the page can't be read."""
    url = row.url
    job = None
    try:
        if "greenhouse" in url or "gh_jid=" in url:
            job = _greenhouse(fetcher, row)
        elif "jobs.lever.co" in url:
            job = _lever(fetcher, row)
        elif "jobs.ashbyhq.com" in url:
            job = _ashby(fetcher, row)
        elif "myworkdayjobs.com" in url:
            job = workday.fetch_job(fetcher, url, row.company)
        else:
            job = _json_ld(fetcher, row)
    except Exception:
        job = None
    return job or Job(
        id=f"link:{url}", company=row.company, title=row.title, location=row.location, remote=False,
        description=f"(Full description unavailable. From a new-grad job list: {row.title}, {row.location}.)",
        apply_url=url, source="link", posted_at=_posted(row),
    )
