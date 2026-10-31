from datetime import datetime, timezone

from . import Job, html_to_text


def fetch_jobs(fetcher, slug: str, company: str) -> list[Job]:
    data = fetcher.get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        location = cats.get("location") or ""
        parts = [j.get("descriptionPlain", "")]
        for section in j.get("lists", []):
            parts.append(f"{section.get('text', '')}\n{html_to_text(section.get('content', ''))}")
        parts.append(j.get("additionalPlain", ""))
        created = j.get("createdAt")
        jobs.append(
            Job(
                id=f"lever:{slug}:{j['id']}",
                company=company,
                title=j["text"],
                location=location,
                remote=j.get("workplaceType") == "remote" or "remote" in location.lower(),
                description="\n\n".join(p for p in parts if p).strip(),
                apply_url=j.get("applyUrl") or j["hostedUrl"],
                source="lever",
                posted_at=datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created else "",
            )
        )
    return jobs
