# Job Scraper — Backend/AI Engineering Jobs (Remote-Anywhere, Remote-India, Onsite-India) — 0 Years Experience

A **production-grade** Python automation that scrapes **7 job boards** every day for **backend/AI engineering roles** requiring **0 years of experience**, and saves qualifying jobs to an Excel workbook.

## What jobs are accepted?

A job is accepted **only when ALL three filters pass**:

1. **Location** — one of:
   - Remote-from-anywhere (`Remote (Worldwide)`, `Work from anywhere`, `Fully remote`, etc.)
   - Remote-from-India (`Remote (India)`, `Remote, Bangalore`, etc.)
   - Onsite-in-India (`Bengaluru`, `Mumbai`, `Hyderabad`, `Pune`, etc.)

2. **Category** — the **title** contains a backend OR AI engineering keyword:
   - Backend: `backend`, `software engineer`, `platform engineer`, `python developer`, `devops`, `SRE`, `data engineer`, etc.
   - AI: `ai engineer`, `ml engineer`, `machine learning`, `data scientist`, `llm`, `nlp`, `computer vision`, `generative ai`, etc.
   - Excludes: `frontend`, `mobile`, `designer`, `sales`, `marketing`, `product manager`, `security engineer`, etc.

3. **Experience** — entry-level (0 years):
   - Title is NOT senior/lead/principal/staff/manager/director/architect/expert
   - Description does NOT mention N+ years (catches `3+ years`, `2-4 years`, `minimum of 5 years`, `1 year of experience`, etc.)
   - Title or description contains an entry-level signal: `0 years`, `0-2 years`, `entry level`, `junior`, `new grad`, `internship`, `fresher`, `recent graduate`, `early career`, `trainee`, `apprentice`, etc.

**Strict mode by default** — bare "Remote" (without "worldwide"/"India" qualifier) is REJECTED because it's ambiguous. Jobs with no entry-level signal are REJECTED.

## Supported sources

| # | Source | URL | Notes |
|---|--------|-----|-------|
| 1 | startups.gallery | https://startups.gallery/jobs?location=remote | YC startup jobs |
| 2 | hnhiring.com | https://hnhiring.com/locations/remote | Hacker News "Who is Hiring?" |
| 3 | no-wb.org | https://www.no-wb.org/ | Companies without whiteboard interviews |
| 4 | aijobs.net | https://aijobs.net/?location=remote | AI/ML/Data Science jobs |
| 5 | wellfound.com | https://wellfound.com/jobs | ⚠️ DataDome-blocked (needs Playwright) |
| 6 | workatastartup.com | https://www.workatastartup.com/jobs | YC companies |
| 7 | grepjob.com | https://grepjob.com/?specialty=Backend,AI+%26+ML | Backend/AI aggregator |

---

## Quick start (using `uv`)

### Prerequisites
- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) — install with:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### Install

```bash
unzip job_scraper.zip
cd job_scraper
uv sync          # creates .venv and installs all deps
uv run python -m scraper.cli test    # smoke test all sources
```

### Run

```bash
# Daily scrape across all 7 sources
uv run python -m scraper.cli daily

# Scrape jobs posted in the last 7 days
uv run python -m scraper.cli range --days 7

# Scrape jobs posted in the last 30 days
uv run python -m scraper.cli range --days 30

# Scrape only one source (debugging)
uv run python -m scraper.cli source grepjob
uv run python -m scraper.cli source aijobs --days 7

# Show state stats
uv run python -m scraper.cli status

# List all configured sources
uv run python -m scraper.cli list-sources
```

Or use the convenience launcher:

```bash
./run.sh daily           # macOS / Linux
./run.bat daily          # Windows
./run.sh range 7
./run.sh source grepjob
```

---

## Excel output

The workbook `jobs_zero_experience.xlsx` has **FOUR sheets**:

### Sheet 1 — "Zero Experience Jobs" (the deliverable)
Every job that passed ALL three filters.
Columns: Date Scraped, Source, **Location Type** (remote_anywhere/remote_india/onsite_india), Posted Date, Job Title, Company, Location, **Seniority**, ATS Provider, Apply URL (hyperlinked), Category Matched, Experience Matched, Years Mentioned, Filter Reason, Description Preview.

### Sheet 2 — "All Filtered Jobs" (audit trail)
Every job that passed the location filter (remote/India) — including rejections for category or experience.
Highlighted green (accepted) / orange (rejected).

### Sheet 3 — "All Scraped Jobs" (full audit)
**EVERY scraped job** with its filter outcome — including location rejections.
Highlighted green (accepted) / blue (location match) / orange (rejected) / yellow (error).
This sheet ensures no job is hidden — you can see exactly what was scraped and why it was accepted/rejected.

### Sheet 4 — "Run Summary"
Per-run stats: timestamp, mode, sources scraped, per-source job counts, filter outcome counts, duration.

**Idempotency**: re-running never produces duplicate rows. Dedup is based on SHA-256 of the ATS URL.

---

## Filter audit logging

Every job's filter decision is logged to `data/logs/scraper.log` with the specific reason:

```
ACCEPT [grepjob] Software Engineer @ Ethos Life [Bangalore, India] | loc=onsite_india cat=Y exp=Y | all filters passed (loc=onsite_india)
reject  [aijobs] Senior Software Engineer @ M... [Bengaluru, India] | loc=onsite_india cat=Y exp=N | experience: senior-title:senior
reject  [aijobs] Junior AI Engineer @ B... [Remote] | loc=— cat=N exp=N | location: bare-remote (no anywhere/india qualifier)
reject  [workatastartup] Founding Design Engineer @ Cardboard [Bengaluru] | loc=onsite_india cat=N exp=N | category: excluded:design
```

This makes it easy to verify no qualifying jobs are being missed and no false positives slip through.

---

## Configuration

All filter rules are editable in **`config.yaml`**. Key sections:

```yaml
filters:
  category:
    backend_title_keywords: [backend, software engineer, platform engineer, ...]
    ai_title_keywords: [ai engineer, ml engineer, machine learning, ...]
    exclude_title_keywords: [frontend, mobile, designer, sales, ...]

  location:
    remote_anywhere_patterns: [remote (worldwide), work from anywhere, ...]
    remote_india_patterns: [remote (india), remote, india, ...]
    india_locations: [bangalore, mumbai, delhi, hyderabad, pune, chennai, ...]
    restricted_remote_patterns: [remote (us), remote (europe), remote (uk), ...]

  zero_experience:
    senior_keywords: [senior, lead, principal, staff, manager, director, ...]
    seniority_levels_rejected: [senior-level, mid-level]
    min_years_threshold: 1
    min_years_patterns: [...]
    entry_level_signals: [0 years, entry level, junior, new grad, internship, fresher, ...]
    include_no_mention: false     # strict mode (recommended)
```

---

## Production-grade features

| Feature | What it does |
|---|---|
| **7 pluggable source adapters** | Each source has its own parser; add new sources easily |
| **Pluggable ATS parsers** | Greenhouse, Ashby, Lever, aijobs.net, workatastartup.com, + generic fallback (specific parsers always win over the catch-all) |
| **Single ATS-provider registry** | One URL→provider map feeds every adapter and the Excel audit trail — labels can never disagree with the parser actually used |
| **Deep job-evaluation module** | Listing → deep-scrape → merge → filter happens at one tested seam (`scraper/evaluation.py`) |
| **Strict location filter** | Word-boundary matching prevents "Indonesia" matching "India" |
| **Title-focused category** | Avoids false positives from description mentions |
| **Smart experience filter** | Ignores "0-N years" ranges (entry-level); ignores form questions |
| **Full audit trail** | Every job logged with accept/reject reason; "All Scraped Jobs" sheet |
| **Honest scheduler exit codes** | 0 ok · 1 nothing parsed · 2 config error · 3 some sources failed · 4 all sources failed — cron/systemd can finally tell "quiet day" from "broken" |
| **Failure webhook hook** | Optional POST of a run report when sources fail (`notifications:` in config.yaml) |
| **Per-host rate limiting** | 2s ± 1s jitter between requests |
| **Retry + exponential backoff** | 3 retries on 429/5xx/network errors |
| **Disk cache** | ATS pages cached 24h |
| **Cross-run + within-run dedup** | Same job never written twice |
| **Atomic file writes** | Excel + state.json written to temp then renamed |
| **Concurrent ATS fetches** | Up to 4 workers |
| **83 unit/integration tests** | Filters, sources, ATS parsers, job evaluation, provider registry, CLI contract, notification hook |

---

## Scheduling

### Exit codes (what cron/systemd sees)

| Code | Meaning |
|------|---------|
| `0`  | Run OK |
| `1`  | Nothing parsed, but no source errors (a quiet day) |
| `2`  | Config / usage error |
| `3`  | Partial failure — at least one source errored |
| `4`  | Total failure — every scraped source errored |

Cron mails a job's *output* when it is not redirected — since the entries
below redirect to a log file, cron will NOT email you on failure. For failure
alerts use the optional webhook under `notifications:` in `config.yaml`, or
systemd `OnFailure=` units.

### cron (macOS / Linux)
```bash
$EDITOR crontab.example   # set PROJECT_DIR and MAILTO (edit the value lines only —
                          # cron does not support trailing comments)
crontab crontab.example
```
Default: daily 09:00, weekly Mon 10:00 (7-day backfill), monthly 1st 11:00 (30-day backfill).

### systemd timers (Linux servers)
```bash
$EDITOR systemd/job-scraper-daily.service
sudo cp systemd/job-scraper-*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now job-scraper-daily.timer
```

### Windows Task Scheduler
Program: `C:\path\to\job_scraper\.venv\Scripts\python.exe`, Arguments: `-m scraper.cli daily`, Start in: `C:\path\to\job_scraper`

---

## Wellfound (DataDome) — optional browser support

Wellfound is behind DataDome anti-bot. To enable:
```bash
uv pip install playwright
playwright install chromium
```
Then set `use_browser: true` in `config.yaml` under `sources.wellfound`.

---

## Troubleshooting

**Q: Only aijobs.net jobs appear in the output.**
A: This was a v2 bug where `accept_bare_remote: true` accepted bare "Remote" listings (which aijobs.net uses). v3 rejects bare "Remote" — only explicit "remote-anywhere" or "remote-India" patterns are accepted. All 6 accessible sources now contribute jobs.

**Q: Jobs that don't match the experience filter slip through.**
A: v3 catches more patterns: "1 year" (singular), "2 years experience" (no "of"), "mid-level" seniority tag, form-question context ("Do you have 1 year of experience?"). The "0-N years" range is correctly treated as entry-level.

**Q: Jobs that don't match the location filter slip through.**
A: v3 uses word-boundary matching — "Indonesia" no longer matches "India". Bare "Remote" is rejected. All restricted remotes (US/Europe/UK/etc.) are explicitly rejected.

**Q: No jobs qualify.**
A: Open the "All Scraped Jobs" sheet to see every job with its filter reason. Adjust `config.yaml` filters as needed. Set `include_no_mention: true` for permissive mode.

**Q: Running tests.**
A: `uv sync --extra dev` once, then `uv run pytest tests/ -v` (83 tests covering filters, sources, ATS parsers, job evaluation, the provider registry, the CLI contract, and the notification hook).

---

**Built for production. Edit `config.yaml`, set up cron or systemd, and forget about it.**
