"""Job-board adapters. Each one reads a public, machine-readable ATS endpoint."""

import html
import re
from dataclasses import dataclass


@dataclass
class Job:
    id: str
    company: str
    title: str
    location: str
    remote: bool
    description: str
    apply_url: str
    source: str
    posted_at: str  # ISO 8601


def html_to_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


from . import ashby, greenhouse, lever  # noqa: E402

ADAPTERS = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "ashby": ashby.fetch_jobs,
}
