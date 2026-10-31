from datetime import datetime, timezone
from urllib.parse import urlparse

from . import Job, html_to_text


def fetch_job(fetcher, url: str, company: str | None = None) -> Job:
    """One posting from a Workday link like https://nvidia.wd5.myworkdayjobs.com/en-US/<site>/job/<path>."""
    parsed = urlparse(url)
    tenant = parsed.netloc.split(".")[0]
    parts = [p for p in parsed.path.split("/") if p]
    if "job" not in parts:
        raise ValueError(f"Not a Workday job link: {url}")
    i = parts.index("job")
    site, job_path = parts[i - 1], "/".join(parts[i + 1:])
    data = fetcher.get_json(f"https://{parsed.netloc}/wday/cxs/{tenant}/{site}/job/{job_path}")
    info = data["jobPostingInfo"]
    location = info.get("location", "")
    return Job(
        id=f"workday:{tenant}:{info.get('jobReqId') or info['id']}",
        company=company or tenant.capitalize(),
        title=info["title"],
        location=location,
        remote=(info.get("remoteType") or "").lower() == "remote",
        description=html_to_text(info.get("jobDescription", "")),
        apply_url=info.get("externalUrl") or url,
        source="workday",
        posted_at=info.get("startDate") or datetime.now(timezone.utc).date().isoformat(),
    )
