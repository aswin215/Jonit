"""Polite HTTP fetcher: robots.txt, per-host rate limits, caching, backoff.

Every request to a job site goes through here. The rules are what keep the
agent from being blocked: one request every 6-9 seconds per host, an honest
User-Agent, conditional requests, and a 24-hour pause for any host that keeps
returning 429/503.
"""

import json
import random
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from . import db
from .config import CONTACT_EMAIL

MIN_DELAY = 6.0
JITTER = 3.0
MAX_RETRIES = 3
PAUSE_SECONDS = 24 * 3600


class HostPaused(Exception):
    pass


class Disallowed(Exception):
    pass


class PoliteFetcher:
    def __init__(self, min_delay: float = MIN_DELAY, jitter: float = JITTER):
        contact = f"; contact: {CONTACT_EMAIL}" if CONTACT_EMAIL else ""
        self.user_agent = f"jobagent/0.1 (personal job-search bot{contact})"
        self.client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            timeout=30.0,
            follow_redirects=True,
        )
        self.min_delay = min_delay
        self.jitter = jitter
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def _wait_turn(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_delay + random.uniform(0, self.jitter) - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            self._wait_turn(parsed.netloc)
            try:
                resp = self.client.get(f"{base}/robots.txt", headers={"Accept": "text/plain"})
            except httpx.HTTPError:
                resp = None
            if resp is not None and resp.status_code < 300:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                self._robots[base] = rp
            elif resp is not None and 400 <= resp.status_code < 500:
                self._robots[base] = None  # no robots.txt: everything allowed
            else:
                rp = RobotFileParser()
                rp.disallow_all = True  # robots.txt unreachable: stay out
                self._robots[base] = rp
        rp = self._robots[base]
        return rp is None or rp.can_fetch(self.user_agent, url)

    def _check_pause(self, host: str) -> None:
        row = db.conn().execute("SELECT until, reason FROM host_pauses WHERE host = ?", (host,)).fetchone()
        if row and row["until"] > time.time():
            raise HostPaused(f"{host} paused until {time.ctime(row['until'])}: {row['reason']}")

    def _pause(self, host: str, reason: str) -> None:
        c = db.conn()
        c.execute(
            "INSERT OR REPLACE INTO host_pauses (host, until, reason) VALUES (?, ?, ?)",
            (host, time.time() + PAUSE_SECONDS, reason),
        )
        c.commit()

    def get_json(self, url: str):
        return json.loads(self.get_text(url))

    def get_text(self, url: str, accept: str = "application/json") -> str:
        host = urlparse(url).netloc
        self._check_pause(host)
        if not self._allowed(url):
            raise Disallowed(f"robots.txt disallows {url}")

        c = db.conn()
        cached = c.execute("SELECT etag, last_modified, body FROM crawl_cache WHERE url = ?", (url,)).fetchone()
        headers = {"Accept": accept}
        if cached and cached["etag"]:
            headers["If-None-Match"] = cached["etag"]
        if cached and cached["last_modified"]:
            headers["If-Modified-Since"] = cached["last_modified"]

        for attempt in range(MAX_RETRIES):
            self._wait_turn(host)
            resp = self.client.get(url, headers=headers)
            if resp.status_code == 304 and cached:
                return cached["body"]
            if resp.status_code in (429, 503):
                retry_after = resp.headers.get("Retry-After", "")
                delay = int(retry_after) if retry_after.isdigit() else 30 * 2**attempt
                time.sleep(min(delay, 600))
                continue
            resp.raise_for_status()
            c.execute(
                "INSERT OR REPLACE INTO crawl_cache (url, etag, last_modified, body, fetched_at) VALUES (?, ?, ?, ?, ?)",
                (url, resp.headers.get("ETag"), resp.headers.get("Last-Modified"), resp.text, time.time()),
            )
            c.commit()
            return resp.text

        self._pause(host, f"{MAX_RETRIES} rate-limit responses in a row")
        raise HostPaused(f"{host} rate-limited us; paused for 24 hours")
