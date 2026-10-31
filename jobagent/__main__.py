import argparse

from . import db


def cmd_discover(args):
    from . import discover

    print("Discovering jobs (polite mode: one request every 6-9 s per site)...")
    stats = discover.run()
    print(f"Fetched {stats['fetched']}, new {stats['new']}, skipped as too old {stats['old']}")
    for err in stats["errors"]:
        print(f"  ! {err}")


def cmd_add_job(args):
    from . import discover

    job = discover.add_job(args.url, args.company)
    print(f"Added {job.company} - {job.title} ({job.location})\n  id: {job.id}")


def cmd_rank(args):
    from . import rank

    stats = rank.run(limit=args.limit)
    print(f"New {stats['new']}, passed filters {stats['passed_filters']}, scored {stats['scored']}")


def cmd_jobs(args):
    from . import rank

    for r in rank.top(args.min_score, args.n):
        print(f"{r['fit_score']:3d}  [{r['status']}]  {r['company']} - {r['title']} ({r['location']})")
        print(f"     id: {r['id']}\n     {r['apply_url']}")


def cmd_tailor(args):
    from . import tailor

    result = tailor.run(args.job_id)
    print(f"Resume: {result['path']} ({result['pages']} page)")
    print(f"Page filled to {result['fill']:.0%}")
    if result["added_bullets"]:
        print(f"Added {result['added_bullets']} more bullet(s) from your profile to fill the page")
    if result["trimmed_bullets"]:
        print(f"Trimmed {result['trimmed_bullets']} bullet(s) to fit one page")
    if result["removed_skills"]:
        print("Left off skills no bullet proves: " + ", ".join(result["removed_skills"]))
    print(f"ATS keyword coverage: {result['keyword_coverage']:.0%}")
    for fix in result["summary_fixes"]:
        print(f"Fixed in summary: {fix}")
    if result["revised"]:
        print("Ran a second pass to work in more of the job's keywords")
    if result["missing_in_profile"]:
        print("Backed by your profile but still not on the page: " + ", ".join(result["missing_in_profile"]))
    if result["missing_gaps"]:
        print("Job asks for, not in your profile (add a bullet only if true): " + ", ".join(result["missing_gaps"]))
    if result["issues"]:
        print("Verifier flagged these; fix before sending:")
        for i in result["issues"]:
            print(f"  ! {i}")
    else:
        print("Verifier: every claim traces back to your profile.")


def cmd_build_profile(args):
    from . import profile_builder

    r = profile_builder.run(args.latest)
    print(f"Read {len(r['files'])} resumes (latest: {r['latest']})")
    if r["unreadable"]:
        print("  ! No text found in: " + ", ".join(r["unreadable"]) + " (scanned PDF? export as DOCX)")
    print(f"Merged into {r['experience']} experiences, {r['projects']} projects, {r['bullets']} bullets")
    print(f"Wrote {r['path']} - review it before tailoring")
    for c in r["conflicts"]:
        print(f"  conflict: {c}")


def cmd_apply(args):
    from . import apply

    r = apply.run(args.job_id, dry_run=args.dry_run)
    filled = sum(1 for i in r["plan"] if i.get("filled"))
    print(f"Filled and verified {filled} of {len(r['plan'])} fields. Screenshot: {r['screenshot']}")
    for item in r["todo"]:
        why = item.get("error") or (
            f"left blank; suggested: {item['suggestion']}" if item.get("suggestion")
            else "left blank for you" if item["needs_user"] and not item["answer"]
            else "review the drafted answer" if item["needs_user"] else "not filled")
        print(f"  ! {item['label'][:80]} ({why})")
    if args.dry_run:
        print("Dry run: the form was filled in a hidden browser and closed. Nothing was submitted.")
    else:
        print("Submitted and recorded on the dashboard." if r["submitted"]
              else "Not submitted (browser closed or timed out); nothing was recorded.")


def cmd_pipeline(args):
    from . import pipeline

    pipeline.run(open_review=not args.no_review)


def cmd_review(args):
    from . import review

    review.run()


def cmd_schedule(args):
    from . import schedule

    if args.action == "install":
        print(f"Installed {schedule.install(args.every)}")
    elif args.action == "uninstall":
        schedule.uninstall()
        print("Removed the schedule.")
    elif args.action == "run-now":
        schedule.run_now()
        print("Started a pipeline run in the background; see data/logs/pipeline.log")
    print("Schedule:", schedule.status())


def cmd_applied(args):
    version = db.latest_resume(args.job_id)
    if db.conn().execute("SELECT 1 FROM jobs WHERE id = ?", (args.job_id,)).fetchone() is None:
        raise SystemExit(f"No job with id {args.job_id}")
    db.record_application(args.job_id, version["id"] if version else None)
    print("Recorded" + (f" with resume {version['markdown_path']}" if version else " (no tailored resume found)"))


def cmd_dashboard(args):
    from . import dashboard

    dashboard.serve(args.port)


def cmd_costs(args):
    rows = db.conn().execute(
        "SELECT model, task, COUNT(*) n, SUM(input_tokens) i, SUM(output_tokens) o, SUM(cost) c "
        "FROM llm_usage GROUP BY model, task ORDER BY c DESC"
    ).fetchall()
    total = 0.0
    for r in rows:
        total += r["c"]
        print(f"{r['model']:<20} {r['task']:<12} calls {r['n']:>4}  in {r['i']:>8}  out {r['o']:>8}  ${r['c']:.4f}")
    print(f"Estimated total: ${total:.4f}")


def main():
    p = argparse.ArgumentParser(prog="jobagent")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("build-profile", help="Merge resumes/ into config/profile.yaml")
    s.add_argument("--latest", help="File name of your current resume (default: most recently modified)")
    s.set_defaults(fn=cmd_build_profile)

    sub.add_parser("discover", help="Fetch new postings from companies.yaml").set_defaults(fn=cmd_discover)

    s = sub.add_parser("add-job", help="Add one job from its link (Workday)")
    s.add_argument("url")
    s.add_argument("--company", help="Company name as it should appear (default: from the link)")
    s.set_defaults(fn=cmd_add_job)

    s = sub.add_parser("rank", help="Filter new jobs and score them with Haiku")
    s.add_argument("--limit", type=int, default=100, help="Max jobs to score this run")
    s.set_defaults(fn=cmd_rank)

    s = sub.add_parser("jobs", help="List the best matches")
    s.add_argument("--min-score", type=int, default=None)
    s.add_argument("-n", type=int, default=20)
    s.set_defaults(fn=cmd_jobs)

    s = sub.add_parser("tailor", help="Tailor your resume to one job with Sonnet")
    s.add_argument("job_id")
    s.set_defaults(fn=cmd_tailor)

    s = sub.add_parser("apply", help="Fill a Greenhouse application in a browser; you review and click Submit")
    s.add_argument("job_id")
    s.add_argument("--dry-run", action="store_true", help="Fill in a hidden browser, screenshot, close; never submit")
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("pipeline", help="Discover, rank, tailor the best matches, open the review session")
    s.add_argument("--no-review", action="store_true", help="Don't open the browser afterwards")
    s.set_defaults(fn=cmd_pipeline)

    sub.add_parser("review", help="Open every ready application in browser tabs, filled").set_defaults(fn=cmd_review)

    s = sub.add_parser("schedule", help="Run the pipeline automatically with macOS launchd")
    s.add_argument("action", choices=["install", "uninstall", "status", "run-now"])
    s.add_argument("--every", type=int, default=6, help="Hours between runs (install)")
    s.set_defaults(fn=cmd_schedule)

    s = sub.add_parser("applied", help="Record that you applied to a job (uses its latest tailored resume)")
    s.add_argument("job_id")
    s.set_defaults(fn=cmd_applied)

    s = sub.add_parser("dashboard", help="Open the applications dashboard in your browser")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_dashboard)

    sub.add_parser("costs", help="Show estimated API spend").set_defaults(fn=cmd_costs)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
