# Job Application Agent

Finds jobs on public ATS job boards, ranks them against your profile, and tailors your resume to each one.
Design: [job-application-agent-design-doc.md](job-application-agent-design-doc.md).

## Which model does what

| Task | Model | Why |
| --- | --- | --- |
| Fit scoring (every job that passes the filters) | Claude Haiku 5.5 | High volume, simple judgment |
| Parsing job requirements | Claude Haiku 5.5 | Extraction |
| Checking the tailored resume for invented claims | Claude Haiku 5.5 | Side-by-side comparison |
| Form answers (coming in phase 3) | Claude Haiku 5.5 | Short, templated |
| **Tailoring the resume** | **Claude Sonnet 5.5** | The one task where writing quality matters |
| Job discovery, keyword filters, dedupe, rule checks | No LLM | Free |

Prices per 1M tokens: Haiku 5.5 is $0.10 in / $0.50 out, Sonnet 5.5 is $2 in / $10 out.
Rough estimate: about $0.001 to score a job and about $0.05 to tailor a resume, so 100 scored jobs and
10 resumes a day comes to roughly $18 a month. Run `python -m jobagent costs` to see what you actually spent.
To change models, set `JOBAGENT_FAST_MODEL` / `JOBAGENT_QUALITY_MODEL` in `.env`.

## Get your API key

The Claude API is pay-as-you-go and separate from a Claude.ai Pro/Max subscription; there is no free tier,
so you need to add credit first.

1. Go to [platform.claude.com](https://platform.claude.com) and sign up (or log in).
2. Open **Settings → Billing** and add credit. A few dollars covers weeks of testing.
3. Open **Settings → Limits** and set a monthly spend limit (e.g. $20) so a bug can't run up a bill.
4. Open **Settings → API Keys**, click **Create Key**, name it `jobagent`, and copy it. It is shown only once.
5. In this folder: `cp .env.example .env`, then paste the key after `ANTHROPIC_API_KEY=`.
   Also set `JOBAGENT_CONTACT_EMAIL`, which goes in the scraper's User-Agent.

Never commit `.env` or paste the key into code; `.gitignore` already excludes it.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Put every version of your resume (PDF, DOCX, TXT, MD) in `resumes/`, then run
`python -m jobagent build-profile --latest <current-resume.pdf>`. It merges them into `config/profile.yaml`;
review that file, since every tailored resume uses only its facts.

Tailored resumes are written as one-page PDFs in the layout of `resumes/ScaleAI.pdf` (set `REFERENCE` in
`jobagent/tailor.py` to change it). This needs `pdflatex` (BasicTeX or MacTeX).

Profile rules:
- `exclude_for_companies` on a project keeps it off resumes for those employers.
- A skill appears in Technical Skills only when a bullet on that resume proves it; `skill_evidence` lists
  other words that count as proof (e.g. "Claude" proves "Anthropic API").

Edit `config/preferences.yaml` (titles, locations, sponsorship) and `config/companies.yaml` (boards to watch).

## Use

```bash
python -m jobagent discover          # fetch new postings (no LLM, free)
python -m jobagent rank --limit 20   # keyword filters, then Haiku fit scores
python -m jobagent jobs              # best matches with their ids
python -m jobagent tailor <job-id>   # Sonnet tailors your resume -> data/resumes/*.pdf
python -m jobagent costs             # estimated spend by model and task
```

Start with `rank --limit 20` to check the scores before scoring everything.

## Staying unbanned

Discovery reads only public JSON job-board APIs (Greenhouse, Lever, Ashby). It checks robots.txt, waits
6–9 seconds between requests to the same site, sends `If-None-Match` so unchanged boards cost nothing,
backs off on 429/503, and pauses a site for 24 hours if it keeps rate-limiting. LinkedIn and Indeed are
not scraped.
