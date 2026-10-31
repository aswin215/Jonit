from . import Job


def fetch_jobs(fetcher, slug: str, company: str) -> list[Job]:
    data = fetcher.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        location = j.get("location") or ""
        jobs.append(
            Job(
                id=f"ashby:{slug}:{j['id']}",
                company=company,
                title=j["title"],
                location=location,
                remote=bool(j.get("isRemote")) or "remote" in location.lower(),
                description=j.get("descriptionPlain", ""),
                apply_url=j.get("applyUrl") or j["jobUrl"],
                source="ashby",
                posted_at=j.get("publishedAt", ""),
            )
        )
    return jobs
