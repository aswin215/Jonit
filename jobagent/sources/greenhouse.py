from . import Job, html_to_text


def fetch_jobs(fetcher, slug: str, company: str) -> list[Job]:
    data = fetcher.get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    jobs = []
    for j in data.get("jobs", []):
        location = (j.get("location") or {}).get("name", "")
        jobs.append(
            Job(
                id=f"greenhouse:{slug}:{j['id']}",
                company=company,
                title=j["title"],
                location=location,
                remote="remote" in location.lower(),
                description=html_to_text(j.get("content", "")),
                apply_url=j["absolute_url"],
                source="greenhouse",
                posted_at=j.get("first_published") or j.get("updated_at", ""),
            )
        )
    return jobs
