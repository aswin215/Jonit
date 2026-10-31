"""Local dashboard: applications, resumes ready to send, and top matches.

Runs on http://127.0.0.1:<port> only (never exposed to the network) and reads the
same SQLite database as the CLI.
"""

import datetime as dt
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db
from .config import RESUME_DIR

STATUS_COLORS = {"applied": "accent", "interviewing": "warn", "offer": "good", "rejected": "bad", "withdrawn": "muted"}

CSS = """
:root { --bg:#f7f7f5; --card:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e4e4e0; --accent:#2f5fd0;
  --good:#1f8a4c; --warn:#b26a00; --bad:#c0392b; }
@media (prefers-color-scheme: dark) { :root { --bg:#151517; --card:#1e1e21; --ink:#ececee; --muted:#9a9aa0;
  --line:#2e2e33; --accent:#7aa2ff; --good:#4cc283; --warn:#f0a83a; --bad:#ff7b6b; } }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink);
  font:14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width:1200px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 10px; }
.sub { color:var(--muted); margin:0 0 20px; }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.stat b { display:block; font-size:26px; } .stat span { color:var(--muted); }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; overflow-x:auto; }
table { width:100%; border-collapse:collapse; } th, td { text-align:left; padding:9px 12px;
  border-bottom:1px solid var(--line); vertical-align:top; } th { color:var(--muted); font-weight:600; font-size:12px;
  text-transform:uppercase; letter-spacing:.03em; } tr:last-child td { border-bottom:0; }
a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
.pill { display:inline-block; padding:2px 8px; border-radius:99px; font-size:12px; font-weight:600;
  border:1px solid currentColor; }
.accent{color:var(--accent)} .good{color:var(--good)} .warn{color:var(--warn)} .bad{color:var(--bad)}
.muted{color:var(--muted)}
select, button { font:inherit; padding:4px 8px; border-radius:6px; border:1px solid var(--line);
  background:var(--card); color:var(--ink); } button { cursor:pointer; border-color:var(--accent); color:var(--accent); }
.empty { padding:18px; color:var(--muted); } .small { color:var(--muted); font-size:12px; }
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _date(ts) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%b %d, %Y") if ts else ""


def _resume_link(version_id, path) -> str:
    if not version_id or not path:
        return '<span class="muted">none</span>'
    return f'<a href="/resume/{int(version_id)}" target="_blank">{_e(Path(path).name)}</a>'


def render() -> str:
    c = db.conn()
    apps = c.execute(
        "SELECT a.id, a.applied_at, a.status, j.company, j.title, j.location, j.apply_url, "
        "r.id AS rid, r.markdown_path AS rpath FROM applications a JOIN jobs j ON j.id = a.job_id "
        "LEFT JOIN resume_versions r ON r.id = a.resume_version_id ORDER BY a.applied_at DESC"
    ).fetchall()
    ready = c.execute(
        "SELECT j.id, j.company, j.title, j.location, j.apply_url, m.fit_score, r.id AS rid, "
        "r.markdown_path AS rpath, r.keyword_coverage, r.verifier_passed FROM jobs j "
        "JOIN resume_versions r ON r.id = (SELECT MAX(id) FROM resume_versions WHERE job_id = j.id) "
        "LEFT JOIN matches m ON m.job_id = j.id WHERE j.status = 'tailored' ORDER BY m.fit_score DESC"
    ).fetchall()
    top = c.execute(
        "SELECT j.id, j.company, j.title, j.location, j.apply_url, m.fit_score FROM matches m "
        "JOIN jobs j ON j.id = m.job_id WHERE j.status = 'scored' ORDER BY m.fit_score DESC LIMIT 25"
    ).fetchall()

    counts = {s: sum(1 for a in apps if a["status"] == s) for s in db.APPLICATION_STATUSES}
    stats = [("Applied", len(apps)), ("Interviewing", counts["interviewing"]), ("Offers", counts["offer"]),
             ("Ready to apply", len(ready))]

    out = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
           f"content='width=device-width,initial-scale=1'><title>Job Applications</title><style>{CSS}</style>"
           "</head><body><main><h1>Job Applications</h1>"
           f"<p class='sub'>Updated {dt.datetime.now().strftime('%b %d, %Y %I:%M %p')}</p><div class='stats'>"]
    out += [f"<div class='stat'><b>{n}</b><span>{label}</span></div>" for label, n in stats]
    out.append("</div>")

    out.append("<h2>Applied</h2><div class='card'>")
    if apps:
        out.append("<table><tr><th>Applied</th><th>Company</th><th>Role</th><th>Status</th><th>Resume used</th>"
                   "<th>Job link</th></tr>")
        for a in apps:
            options = "".join(f"<option{' selected' if s == a['status'] else ''}>{s}</option>"
                              for s in db.APPLICATION_STATUSES)
            color = STATUS_COLORS.get(a["status"], "muted")
            out.append(
                f"<tr><td>{_date(a['applied_at'])}</td><td>{_e(a['company'])}</td>"
                f"<td>{_e(a['title'])}<div class='small'>{_e(a['location'])}</div></td>"
                f"<td><form method='post' action='/status'><input type='hidden' name='id' value='{a['id']}'>"
                f"<span class='pill {color}'>{_e(a['status'])}</span> "
                f"<select name='status' onchange='this.form.submit()'>{options}</select></form></td>"
                f"<td>{_resume_link(a['rid'], a['rpath'])}</td>"
                f"<td><a href='{_e(a['apply_url'])}' target='_blank' rel='noopener'>Open posting</a></td></tr>")
        out.append("</table>")
    else:
        out.append("<div class='empty'>No applications yet. Mark one as applied from the list below.</div>")
    out.append("</div>")

    out.append("<h2>Tailored, ready to apply</h2><div class='card'>")
    if ready:
        out.append("<table><tr><th>Fit</th><th>Company</th><th>Role</th><th>Resume</th><th>Checks</th>"
                   "<th>Job link</th><th></th></tr>")
        for r in ready:
            checks = (f"{(r['keyword_coverage'] or 0):.0%} keywords, "
                      + ("verified" if r["verifier_passed"] else "<span class='bad'>needs review</span>"))
            out.append(
                f"<tr><td>{_e(r['fit_score'])}</td><td>{_e(r['company'])}</td>"
                f"<td>{_e(r['title'])}<div class='small'>{_e(r['location'])}</div></td>"
                f"<td>{_resume_link(r['rid'], r['rpath'])}</td><td class='small'>{checks}</td>"
                f"<td><a href='{_e(r['apply_url'])}' target='_blank' rel='noopener'>Open posting</a></td>"
                f"<td><form method='post' action='/apply'><input type='hidden' name='job' value='{_e(r['id'])}'>"
                f"<input type='hidden' name='resume' value='{int(r['rid'])}'>"
                f"<button>Mark applied</button></form></td></tr>")
        out.append("</table>")
    else:
        out.append("<div class='empty'>Nothing tailored yet. Run <code>python -m jobagent tailor &lt;job-id&gt;</code>.</div>")
    out.append("</div>")

    out.append("<h2>Top matches, not tailored yet</h2><div class='card'>")
    if top:
        out.append("<table><tr><th>Fit</th><th>Company</th><th>Role</th><th>Job link</th><th>Tailor with</th></tr>")
        for t in top:
            out.append(
                f"<tr><td>{_e(t['fit_score'])}</td><td>{_e(t['company'])}</td>"
                f"<td>{_e(t['title'])}<div class='small'>{_e(t['location'])}</div></td>"
                f"<td><a href='{_e(t['apply_url'])}' target='_blank' rel='noopener'>Open posting</a></td>"
                f"<td class='small'><code>python -m jobagent tailor {_e(t['id'])}</code></td></tr>")
        out.append("</table>")
    else:
        out.append("<div class='empty'>No scored jobs. Run <code>python -m jobagent rank</code>.</div>")
    out.append("</div></main></body></html>")
    return "".join(out)


class Handler(BaseHTTPRequestHandler):
    def _local_only(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self.send_error(403)
            return False
        return True

    def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._local_only():
            return
        path = urlparse(self.path).path
        if path == "/":
            return self._send(render().encode())
        if path.startswith("/resume/") and path.removeprefix("/resume/").isdigit():
            row = db.conn().execute("SELECT markdown_path FROM resume_versions WHERE id = ?",
                                    (int(path.removeprefix("/resume/")),)).fetchone()
            pdf = Path(row["markdown_path"]).resolve() if row else None
            if pdf and pdf.is_file() and RESUME_DIR.resolve() in pdf.parents:
                return self._send(pdf.read_bytes(), "application/pdf")
        self.send_error(404)

    def do_POST(self):
        if not self._local_only():
            return
        length = int(self.headers.get("Content-Length") or 0)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        try:
            if self.path == "/apply":
                db.record_application(form["job"], int(form["resume"]))
            elif self.path == "/status":
                db.set_application_status(int(form["id"]), form["status"])
            else:
                return self.send_error(404)
        except (KeyError, ValueError):
            return self.send_error(400)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):
        pass


def serve(port: int = 8765, open_browser: bool = True) -> None:
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Dashboard at {url} (Ctrl+C to stop)")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
