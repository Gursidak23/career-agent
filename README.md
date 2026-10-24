# Career Agent — Resume ATS Optimizer + Recruiter Outreach

A two-part system:

1. **Resume ATS Optimizer** — upload a resume PDF, pick a target technical role
   (or paste a job description), and get an ATS-optimized resume scored against
   a transparent ATS rubric (target > 90). The output keeps the original's
   format: headline, section order, grouped skills, project/certification
   links, extra sections (e.g. Accomplishments), paper size and page count,
   rendered in a classic single-column one-page layout. Tailoring only
   rewords: employers, titles, dates, numbers and names are locked, and a
   rewrite that introduces a technology the original never mentions is
   rejected.
2. **Recruiter Outreach** — generate personalized cold emails / LinkedIn DMs and
   batch-send them through your own SMTP. Browse and filter **real, live** job
   postings aggregated from free public APIs (Remotive, RemoteOK, Arbeitnow, and
   the YC "Who is hiring?" thread), or an external Scrapy project you point it at.

LLM calls use a **fallback chain: Gemini → Groq → GitHub Copilot**. Each
provider is skipped automatically if its credential is missing, and the system
fails over on errors/rate limits. Copilot is last because it is paid (Copilot
AI credits); it runs through the official `github-copilot-sdk` with its agent
prompt replaced and all tools disabled, so it acts as a plain chat model. If every provider fails, the app still works in a degraded
mode (regex parsing, unmodified resume, template messages) and shows a warning
saying so. (GitHub Models was the third fallback until GitHub retired it on
2026-07-30.)

## Architecture

```
frontend (React + Vite + TS)  ──REST──▶  backend (FastAPI)
                                            ├── llm/      Gemini → Groq → Copilot
                                            ├── resume/   parse → tailor → ATS score → LaTeX/PDF
                                            ├── outreach/ messages → SMTP send → jobs (scraper)
                                            │              └── email_finder/ crawl → verify → rank
                                            └── SQLite (SQLAlchemy)
```

## Prerequisites

- Python 3.11–3.12 (recommended; some ML/PDF wheels may lag on 3.14)
- Node 18+
- [Tectonic](https://tectonic-typesetting.github.io) for PDF output (optional —
  without it you still get the `.tex` source)
- API keys: Gemini and/or Groq (both have free tiers); optionally a GitHub
  fine-grained PAT with the "Copilot Requests" permission for the Copilot fallback
- For sending: an SMTP account (Gmail App Password recommended)

## Backend setup

```bash
cd career-agent/backend
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
python -m pip install -e ".[dev]"
copy .env.example .env            # then fill in your keys
uvicorn app.main:app --reload
```

API runs at http://127.0.0.1:8000 (docs at `/docs`).

Run tests:

```bash
pytest
```

## Frontend setup

```bash
cd career-agent/frontend
npm install
npm run dev
```

App runs at http://127.0.0.1:5173 and proxies `/api` to the backend.

## Configuration

All settings use the `CAREER_` env prefix with `__` for nesting (see
`backend/.env.example`). Key ones:

| Variable | Purpose |
| --- | --- |
| `CAREER_LLM__GEMINI_API_KEY` | Gemini (primary LLM) |
| `CAREER_LLM__GROQ_API_KEY` | Groq (fallback) |
| `CAREER_LLM__COPILOT_GITHUB_TOKEN` | GitHub Copilot (final, paid fallback) |
| `CAREER_SMTP__USERNAME` / `__PASSWORD` | Outgoing email (App Password) |
| `CAREER_TECTONIC_BIN` | Path to the `tectonic` binary |

`CAREER_LLM__GEMINI_MODEL` defaults to `gemini-flash-lite-latest`: in testing it
answered in ~2 s versus 60–100 s+ for `gemini-flash-latest`, with comparable
output for this workload.

Real environment variables override `backend/.env`. If you change `.env`,
restart the backend from a **fresh** terminal; the Settings page warns when a
stale shell variable is shadowing a different `.env` value, and its **Test
connections** button makes a real call to each AI provider (and an SMTP login
without sending).

## Workflow

1. **Resume**: drop your PDF (re-uploading the same file reuses the saved parse
   instantly), pick a role and optionally paste a job description. The current
   score updates live; **Optimize** rewrites and re-scores. Past versions stay in
   *History*. **Review the rewrites** lists every reworded line next to your
   original: clean ones are applied, ones that add a technology the entry never
   mentions or drop a number/name are held back with the reason. Tick or untick
   each and **Apply choices** to re-score and re-render the PDF/DOCX.
2. **Jobs**: fetch live postings and rank them against your resume (**match %**,
   instant and AI-free: the share of skills a post names that your resume shows,
   scaled down for posts that name few). Sort by best match, filter by minimum
   match, see the skills you're missing, and spot **New** postings since your
   last visit. **Track**, **Tailor resume** or **Draft outreach** on any job.
3. **Outreach**: the job, your latest optimized resume (attached as
   `First_Last_Role_Resume.pdf`), your name and top quantified highlights are
   filled in. Generated emails use the job post as context and stay editable.
   Recruiters you've already emailed are skipped unless you tick *Allow
   repeats*. Do a test run first; real sending needs SMTP credentials.
4. **Tracker**: one card per job, Saved → Applied → Contacted → Replied →
   Interview → Offer (or Rejected), with notes, the resume version you used and
   emails sent. Tailoring for a job adds its card; a successful send moves it to
   Contacted (never backwards).

## ATS scoring rubric (0–100)

| Component | Weight |
| --- | --- |
| Keyword coverage vs role/JD | 35 |
| Standard sections present | 15 |
| Quantified bullets + action verbs | 15 |
| Parseability (clean single-column) | 15 |
| Contact details + links | 10 |
| Length / conciseness | 10 |

The tailoring loop rewrites the resume (truthfully — it never fabricates
employers, dates, or metrics) and re-scores until the target is reached or the
iteration cap is hit.

## Job sources (all real / live — no sample data)

Job postings come from real, free, keyless public APIs. Pick a source on the
Jobs page (default `all`) or via `POST /api/jobs/refresh` with `{"source": ...}`:

| Source | Endpoint | Notes |
| --- | --- | --- |
| `all` | — | Aggregates every source below, de-duped on (company, title). Recommended. |
| `remotive` | `remotive.com/api/remote-jobs` | Remote tech jobs, supports `search`. |
| `remoteok` | `remoteok.com/api` | Remote jobs with tags + salary. |
| `arbeitnow` | `arbeitnow.com/api/job-board-api` | EU/remote job board. |
| `hackernews` | HN "Ask HN: Who is hiring?" via the public Algolia API | Monthly YC-ecosystem thread; **many posts include a recruiter email**, parsed automatically. |
| `companies` | Greenhouse, Lever and Ashby public job-board APIs | Openings straight from company career pages (Stripe, Databricks, Anthropic, OpenAI, Notion, CRED, Meesho, …), full descriptions and apply links. Filtered to tech roles; edit the list with `CAREER_SCRAPER__COMPANY_BOARDS`. Part of `all`. |
| `apify` | Apify "New Job Posts Finder" actor | **Indian boards** — Naukri, Foundit (Monster India), Hirist, Indeed, Internshala, LinkedIn. Needs a free `CAREER_SCRAPER__APIFY_TOKEN`; not part of `all` (it's metered). |

> **Instahyre / JobFound:** Instahyre has no public/keyless API (job data is
> login- and anti-bot-gated; only paid enterprise ATS integrations exist), and
> JobFound is defunct. For Indian listings use the `apify` source above (which
> covers comparable boards) or wire a dedicated `scrapy` spider.

Job type, experience level, and role category are inferred from each posting's
title/tags/description (see `app/outreach/scraper/classify.py`). Postings without
a recruiter email can be enriched on demand via the email finder (per-row **Find
email**, or the **Find recruiter emails** toggle on refresh).

> TLS note: outbound calls trust the **OS certificate store** via `truststore`
> (`app/ssl_setup.py`), so the real APIs work behind corporate TLS-intercepting
> proxies without disabling certificate verification.

### Optional: add a custom Scrapy board (e.g. WellFound)

For boards that need a dedicated crawler, the `scrapy` source shells out to an
**external** Scrapy project (kept out of this repo because board scrapers break
often and have ToS/anti-bot constraints):

```bash
git clone <a maintained Scrapy job-board project> external/job-scraper
cd external/job-scraper && pip install -r requirements.txt
```

Then set:

```bash
CAREER_SCRAPER__PROJECT_DIR=external/job-scraper
CAREER_SCRAPER__SPIDER=<spider-name>     # e.g. wellfound / yc / instahyre
```

The adapter runs `scrapy crawl <spider> -O out.jsonl` and maps the items into
job postings (see `app/outreach/scraper/scrapy_source.py` for the field
mapping). Always respect each site's robots.txt, rate limits, and Terms of
Service.

### Scheduled fetching and a match digest

Set `CAREER_SCRAPER__AUTO_REFRESH_HOURS` (e.g. `12`) to fetch new postings in the
background while the backend runs. With `CAREER_SCRAPER__DIGEST_EMAIL` set (and
SMTP configured), each run emails you the new postings that match your latest
resume at least `CAREER_SCRAPER__DIGEST_MIN_MATCH` % (default 60).

## Email finder (recruiter/company email discovery)

When a job posting (or outreach draft) has no recruiter email, the **email
finder** discovers one through a provider chain, then verifies and ranks the
results. Each provider is tried in priority order and the chain short-circuits
as soon as a verified address is found.

| Provider | Key needed | How it works |
| --- | --- | --- |
| `crawler` | none | Bounded async `httpx` crawl of the company site (homepage + contact/about/team/careers) and the job URL, scraping `mailto:` and inline addresses. |
| `agentql` | `AGENTQL_API_KEY` | TinyFish/AgentQL REST extraction of contact emails (free tier). |
| `apify` | `APIFY_TOKEN` | Runs an Apify actor synchronously via REST and harvests emails from its output (free tier). |
| `pattern` | none | Guesses common corporate formats (`first.last@`, `flast@`, …) from the person's name + domain, then relies on verification to grade them. |

**Verification is graded** (best-effort, since outbound SMTP is often blocked and
catch-all domains accept anything):

- `verified` — SMTP accepted the RCPT and the domain is not catch-all
- `mx_only` — the domain has MX/A records (mail plausible) but RCPT unconfirmed
- `unverified` — no MX / lookup failed

Usage:

- **Jobs page** — per-row **Find email** button, plus a **Find recruiter emails**
  toggle on *Fetch from source* that enriches new postings in the background.
- **Outreach page** — **Find** button next to the recruiter email field, with a
  candidate picker showing each address's source and verification badge.
- **API** — `POST /api/email/find` (`{company, name?, domain?, job_url?, job_id?}`)
  and `POST /api/email/verify` (`{email}`).

The keyless providers (`crawler`, `pattern`) need no configuration. Configure the
optional free-tier providers and verification behavior under the
`CAREER_EMAILFINDER__*` keys (see `backend/.env.example`). Always respect each
site's robots.txt and Terms of Service, and use discovered emails responsibly.

## LinkedIn DM sending (optional, real automation)

Cold emails send via SMTP; **LinkedIn DMs can now be sent for real** through your
own logged-in session using Playwright (off by default). There is no official
LinkedIn messaging API, so this drives a real browser:

1. Install the browser: `pip install playwright && playwright install chromium`.
2. Enable it: `CAREER_LINKEDIN__ENABLED=true`.
3. On the Outreach page click **Connect LinkedIn (open login)** (or `POST
   /api/linkedin/login`), sign in once — the session is persisted to
   `CAREER_LINKEDIN__USER_DATA_DIR` and reused.
4. Generate a `linkedin` message variant, paste the recruiter's profile URL
   (`.../in/<handle>`), **Add to LinkedIn queue**, and **Send**. Delivery runs in
   the background (throttled, human-paced) with a status table you can poll.

Endpoints: `GET /api/linkedin/status`, `POST /api/linkedin/login`,
`POST /api/linkedin/send`, `GET /api/linkedin/sends`. Everything degrades
gracefully — if Playwright isn't installed the feature reports unavailable
instead of erroring.

> ⚠️ Automating LinkedIn can violate its Terms of Service. Use only for personal
> outreach, at low volume, with conservative rate limits.

## Resume attachments

Outreach emails can attach the tailored resume (`tailoring_id`). The sender
prefers the rendered **PDF**, and **falls back to the DOCX** when Tectonic isn't
installed — so attachments work even without a PDF toolchain.

## Notes

- This is a personal-use tool. Cold-emailing recruiters at scale can violate
  anti-spam rules and platform ToS — use responsibly with conservative rate
  limits (`CAREER_SMTP__PER_MINUTE`).
