# Personal JobPilot

> A fully local, autonomous job-search agent. Scrapes ATS boards every 30 minutes, classifies each role into one of 10 career archetypes across three tracks (data/quant, AI-engineering, and hourly behavioral-technician work), scores it across 10 weighted dimensions with a local LLM, generates an ATS-clean tailored resume + cover letter, drafts interview-prep and networking outreach on demand, and queues high-fit roles for one-click submission — all on a single laptop, $0/month.

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00)](https://www.sqlalchemy.org/)
[![Ollama](https://img.shields.io/badge/Ollama-Gemma--4_27B-000000)](https://ollama.com/)
[![Playwright](https://img.shields.io/badge/Playwright-Auto--apply-2EAD33?logo=playwright)](https://playwright.dev/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Why I built this

I'm a Bay Area data scientist (MS Quantitative Economics) pivoting toward AI-engineering roles. Applying to jobs is a slow, manual, soul-crushing loop: scroll boards, read JDs, decide if it's worth the effort, hand-tailor a resume, paste 30 form fields, repeat. It scales like O(n) human-hours.

So I built the system I wished existed — one that runs on my own hardware, uses no paid APIs, respects my data, and turns the job hunt into a `cron`-scheduled background process I can supervise from a single dashboard. The same engineering patterns I'd use to ship a production ML pipeline at work, applied to my own problem.

This repo is the result. It's been running 24/7 for weeks and now:

- Scans **Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, EdJoin, and 45+ company career pages** (including fully custom ones via Playwright) every 30 minutes — ATS-API-first, zero-ToS-risk; deliberately no Indeed/LinkedIn scraping
- Classifies each role into **10 archetypes across three tracks** — data/quant, AI-engineering (AI Engineer / Solutions Engineer / AI Analyst), and hourly Behavioral-Technician (ABA/RBT) work
- Scores every one on a **10-dimension archetype-weighted rubric** via local Gemma-4 27B, with AI-intensity and hourly-pay signals baked in
- Generates **ATS-clean tailored resumes + cover letters** as ready-to-send `.docx` files (résumé auto-routed by track), then **audits them against the JD** with an evidence-based optimizer (scoring approach adapted from [HackerRank's hiring-agent](https://github.com/interviewstreet/hiring-agent)) — keyword coverage, requirement alignment, impact quantification — and regenerates once with concrete feedback when the audit scores below threshold
- Drafts a **role-specific interview-prep pack** and **networking outreach** for any job, locally, on demand
- Auto-submits high-fit applications via Playwright behind strict guardrails — never CAPTCHAs, never paid jobs

---

## Architecture

```
                         ┌──────────────────────────────┐
                         │   APScheduler (cron loop)    │
                         └──────────────┬───────────────┘
                                        │
            ┌───────────────┬───────────┼───────────┬───────────────┐
            ▼               ▼           ▼           ▼               ▼
        Greenhouse        Lever       Ashby       EdJoin      Career pages
            │               │           │           │               │
            └───────────────┴─────┬─────┴───────────┴───────────────┘
                                  │ dedup hash
                                  ▼
                        ┌──────────────────┐
                        │   SQLite (jobs)  │  ◄── single source of truth
                        └────────┬─────────┘
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
     ┌──────────────────┐ ┌────────────┐ ┌────────────────┐
     │ Stage 1: classify│ │ Stage 2:   │ │ Stage 3: write │
     │   archetype      │ │ score 10   │ │ 6-block eval   │
     │   + confidence   │ │ dimensions │ │ report (.md)   │
     └────────┬─────────┘ └─────┬──────┘ └────────┬───────┘
              └──────────┬──────┴─────────────────┘
                         ▼
                   Gemma-4 27B (Ollama, local, ~50 tok/s)
                         │
                         ▼
              ┌─────────────────────┐
              │  Resume Tailor      │  ──►  output/resumes/*.docx
              │  Cover Letter Gen   │  ──►  output/cover_letters/*.docx
              │  Interview Prep     │  ──►  output/interview_prep/*.json
              │  Outreach Drafter   │  ──►  output/outreach/*.json
              └─────────┬───────────┘
                        ▼
              ┌────────────────────┐         ┌──────────────────┐
              │  FastAPI dashboard │ ◄────►  │ Playwright       │
              │  + SSE live feed   │         │ auto-applier     │
              └────────────────────┘         └──────────────────┘
                http://127.0.0.1:7777
```

**Single SQLite database** is the source of truth. Every component reads/writes it independently — scanner, ranker, tailor, dashboard, auto-applier, and the interview-prep/outreach copilots — so nothing is coupled and any one piece can be restarted in isolation.

---

## Engineering highlights

### 3-stage LLM pipeline (not one mega-prompt)

Most job-scoring projects throw the entire job description + resume into one massive prompt and ask the model for a JSON blob. That works in demos but in practice: hallucinations, inconsistent dimensions, and no way to debug why a job scored 67 vs 72.

I broke it into three focused LLM calls, each with a narrow contract:

| Stage | Input | Output | Why split |
|---|---|---|---|
| **1. Classify** | Title + JD | `{archetype, confidence, reasoning}` | One decision. Model isn't distracted. Lets us route to a tailored scoring rubric. |
| **2. Score dimensions** | JD + archetype + resume summary | `{10 dim scores, matches, gaps, ats_keywords, ai_intensity, ai_tools}` | Constrained schema. Each dim gets full attention. |
| **3. Write evaluation** | All of the above | 6-block markdown audit | Generates a human-readable report stored on disk — full audit trail. |

The weighted overall score is computed **in deterministic Python** from the dim scores, not by the LLM. This makes scoring reproducible, auditable, and instantly tunable by editing one yaml file.

### Archetype-routed scoring (one rubric per role type)

`config/archetypes.yaml` defines **10 archetypes** — plus an `unknown` fallback — grouped into three tracks:

- **Data / quant:** `data_analyst`, `data_scientist`, `quantitative_analyst`, `ml_engineer`, `business_analyst`, `product_analyst`
- **AI-engineering:** `ai_engineer` (LLM/GenAI/agentic apps), `ai_solutions_engineer` (forward-deployed / solutions / sales engineering), `ai_analyst` (AI-augmented analytics)
- **Hourly:** `behavioral_technician` (ABA/RBT — 1:1 sessions, hourly pay, part-time)

Each archetype ships with:

- A **dimension-weight vector** (10 weights summing to 1.0) so the same dim scores produce different overall fit depending on role type. A `comp_range` miss matters far more for a Behavioral Technician (weight `0.20`, an hourly-rate floor) than for a Quant Analyst.
- An **auto-apply threshold** (`auto_apply_min_score`) — e.g. ML Engineer roles need 80+ before the bot will auto-submit; AI Engineer is 76+, Data Analyst 72+. Tuned per archetype because the cost of a bad application differs by role.

```yaml
behavioral_technician:
  label: "Behavioral Technician (ABA)"
  weights:
    comp_range:      0.20   # highest — hourly rate is the dominant driver
    location_remote: 0.16   # must be SF/Bay, on-site
    archetype_fit:   0.16
    skills_overlap:  0.14
    technical_fit:   0.06   # de-emphasized — this isn't a coding role
    ...
  auto_apply_min_score: 70
```

Adding a new archetype means editing one yaml file. No code change, no migration, no model retraining.

### AI-forward and hourly-pay signals

Two role-shape signals extend the rubric beyond a single fit number:

- **AI intensity** (`migration 004`) — every `JobScore` now carries `ai_intensity` (how central AI/LLM work is to the role) and `ai_tools` (the concrete AI stack named in the JD). The dashboard exposes an **AI-forward filter** so I can surface the roles that actually match the pivot, not just anything with "AI" in the title.
- **Hourly compensation** (`migration 005`) — the scanner parses `$/hr` pay at scan time, comp-aware scoring folds it into `comp_range`, and hourly roles get a **$/hr auto-apply floor** so a sub-threshold rate is filtered before it ever reaches the queue. This is what makes the Behavioral-Technician track work alongside salaried tech roles in the same pipeline.

### ATS-clean .docx generation that actually passes the parser

The resume is generated with `python-docx` using design choices borrowed from Jake Gutierrez's LaTeX template, then verified against the major ATS parsers (Greenhouse, Workday, Lever):

- Single-column layout — no tables, no text boxes, no headers/footers (all three break ATS parsers)
- Small-caps section headers via the raw `<w:smallCaps val="1"/>` XML element (python-docx doesn't expose this)
- Two-column tab stops at 7.6" so dates right-align to the same pixel on every line
- Garamond at 10pt body, 1.08 line spacing — hits one page for any reasonable amount of experience
- Hanging indents on bullets so wrapped lines don't break visual hierarchy

The tailor is **track-aware**: tech/AI roles pull from the primary résumé, while behavioral-technician roles are routed to a separate ABA-focused résumé (`config/base_resume_bt.yaml`, gitignored) — so the same job feed produces the right document for each track. The same module renders a matching cover letter from a tailored prompt — same fonts, same margins, same brand.

### Live dashboard — Indeed-style, dark mode, Kanban board

The dashboard at `http://127.0.0.1:7777` is a single-file static HTML + vanilla JS app served by FastAPI. No build step, no React, no bundle — but it gets live updates via SSE: scan completions, new scores, and application-status changes all stream into the UI in real time.

The UI is an **Indeed-reference rebuild**: a two-field search, a faceted filter rail (archetype, source, AI-forward, hourly pay), and a list + detail pane so I can triage the feed fast. It ships with a **persisted dark mode** (respects `prefers-color-scheme` on first load, toggle to override) and a **Kanban pipeline board** where dragging a card between stages (Queued → Applied → Response → Interview) saves the status instantly.

Each job's detail pane shows:
- The full 10-dimension score grid with color-coded bars
- An archetype badge + threshold banner ("Below 73 — won't auto-apply") and AI-intensity / hourly-pay chips
- Collapsible evaluation report rendered from the markdown the LLM wrote
- One-click links to the tailored resume `.docx`, cover letter, and apply URL — plus on-demand **Tailor**, **Interview Prep**, and **Outreach** actions

### Per-job AI copilots — interview prep & outreach

Two local-only copilots turn a scored job into next actions, each one Ollama call, cached to disk so re-opening a job is instant:

- **Interview-prep simulator** (`agents/interview_prep.py`, `GET /api/application/{id}/interview`) — generates a role-specific mock-interview pack: likely questions (behavioral / technical / role-specific), how *this* candidate should answer each using their real background, points to lead with, gaps to reframe, and smart questions to ask the interviewer. Cached to `output/interview_prep/`.
- **Networking outreach drafter** (`agents/outreach.py`, `GET /api/application/{id}/outreach`) — drafts a LinkedIn connection note (hard-capped at 300 chars in code), a recruiter email, a hiring-manager email, résumé-grounded talking points, and generic role titles worth contacting. **It drafts text only** — it never sends anything, never looks up real people, and never invents names or contact details. Cached to `output/outreach/`.

### Auto-applier with hard guardrails

The Playwright bot will *only* submit applications when **all** of these hold:

1. Overall fit score ≥ the archetype's `auto_apply_min_score` (and, for hourly roles, `$/hr` ≥ the comp floor)
2. ATS is on the allowlist (Greenhouse, Lever, Ashby — never Workday)
3. No CAPTCHA detected on the page
4. No "salary requirements" or "cover letter (required)" fields the LLM hasn't already filled
5. The dedup table confirms we haven't applied to this company in the last 90 days

Every action is logged to `auto_apply_log` (JSON) on the Application row so I can audit exactly what the bot did. If any check fails, the application gets routed to the human review queue instead.

---

## Tech stack

| Layer | Stack | Why |
|---|---|---|
| **Language** | Python 3.14 | Type hints, `dataclass`, `match` statements |
| **Database** | SQLite + SQLAlchemy 2.0 | Zero-ops, single-file, plenty fast for this scale |
| **LLM** | Gemma-4 27B via [Ollama](https://ollama.com); opt-in cloud providers (OpenAI, Claude Fable 5.1 via the Anthropic SDK) behind `settings.yaml → llm` | Local, free, no rate limits, ~50 tok/s on consumer GPU — cloud only when explicitly selected and keyed via env vars |
| **Scheduler** | APScheduler (BlockingScheduler) | Cron-like jobs in pure Python |
| **Web framework** | FastAPI + Uvicorn | Async, SSE-friendly, OpenAPI for free |
| **Scraping** | requests + BeautifulSoup4 (Greenhouse/Lever/Ashby JSON APIs) + Playwright (EdJoin + JS-rendered pages) | Right tool per source |
| **Document gen** | python-docx | Direct XML access for ATS-clean output |
| **Auto-apply** | Playwright (Chromium) | Stable selectors, native form-fill, screenshot on failure |
| **Frontend** | Vanilla HTML/JS + SSE | No build step, ships instantly; dark mode + Kanban with zero dependencies |
| **Tests** | pytest | Deterministic surfaces (math, config, persistence) — LLM calls covered by integration |

Total monthly infra cost: **$0**.

---

## Setup

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com/) installed and a Gemma 4 model pulled:
  ```bash
  ollama pull gemma4:e4b   # default — 9.6GB, ~25 tok/s on an M4 Mac mini (24GB)
  ollama pull gemma4:12b   # optional quality mode — ~11 tok/s on the same hardware
  ```
  On 24GB machines, skip `gemma4:26b`/`31b` — their weights alone (18-20GB)
  exceed what macOS lets the GPU wire. Set the model in `config/settings.yaml`
  (`ollama.model`).
- ~20GB free disk
- A GPU helps but is not required — runs on CPU at ~15 tok/s

### Install

```bash
git clone https://github.com/TheCromazone/Personal-JobPilot.git
cd Personal-JobPilot

python -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Install Playwright browsers (for the auto-applier + EdJoin scanner)
playwright install chromium
```

### Configure

Copy the example files and fill in your details:

```bash
cp config/applicant_profile.example.yaml config/applicant_profile.yaml
cp config/base_resume.example.yaml       config/base_resume.yaml
# optional — the hourly Behavioral-Technician track uses a second résumé:
cp config/base_resume.example.yaml       config/base_resume_bt.yaml
```

Then tune `config/settings.yaml` for the roles you want — search keywords, target locations, excluded keywords, scoring thresholds, and the hourly-pay floor.

`applicant_profile.yaml`, `base_resume.yaml`, and `base_resume_bt.yaml` are all **gitignored** — your personal data stays on your machine.

### Run

**Recommended — let the watchdog run everything.** One process supervises Ollama, the dashboard, and the scheduler, restarting any that die:

```bash
python watchdog.py
```

On macOS, double-click `start_jobpilot.command` (launches the watchdog and opens
the dashboard), or run `./install_autostart_mac.sh` once to install a LaunchAgent
that starts it at every login (`./uninstall_autostart_mac.sh` removes it).

On Windows, double-click `start_jobpilot.bat` (launches the watchdog and opens the dashboard), or run `register_autostart.bat` once to have it start automatically at every login — see [Reliability](#reliability--it-stays-up-on-its-own).

**Manual — run the pieces yourself** (useful for development):

```bash
# Terminal 1 — scheduler
python scheduler.py

# Terminal 2 — dashboard
python -m uvicorn server.dashboard:app --host 127.0.0.1 --port 7777
```

### Use

Open http://127.0.0.1:7777 and:

1. **Watch** new jobs appear as scanners find them
2. **Filter** the feed — by archetype, source, AI-forward, or hourly pay — and open a role to see the 10-dim breakdown + LLM-written evaluation
3. **Act** on the high-fit ones — auto-applier submits via Playwright; for the rest, generate a tailored resume + cover letter, an interview-prep pack, or networking outreach in one click
4. **Track** status by dragging cards across the Kanban board (Queued → Applied → Response → Interview) — changes save instantly

---

## Browser autofill extension

`browser-extension/` is a separate **Manifest V3** Chrome/Edge extension that autofills
job-application forms from your résumé — on any site you open yourself. It scans the page,
asks the local JobPilot backend for a fill-plan (deterministic mapping for the standard
fields, Gemma-drafted answers for essays, résumé **auto-routed** AI vs BT), and fills the
fields. **It never clicks Apply** — you review the highlighted fields and submit yourself,
so it stays within site ToS.

**Install (load unpacked):**

1. Make sure the JobPilot backend is running (it auto-starts at login) — the extension
   talks to `http://127.0.0.1:7777`.
2. Open `chrome://extensions` (or `edge://extensions`) and enable **Developer mode**.
3. Click **Load unpacked** and select the `browser-extension/` folder.
4. On any application page a floating **⚡ Autofill** button appears bottom-right —
   it auto-detects application forms (Simplify / JobWright style; the **⌄** opens the
   résumé selector + status). Click it to fill. You can also use the **JobPilot Autofill**
   toolbar icon → **Autofill this application**. Filled fields are outlined green; anything
   needing review is amber, and a toast reports the count.

The in-page button is a content script (`content/widget.js`) injected on all sites but
only shown when the page looks like a job application; it reuses the same scan → plan →
fill pipeline as the popup via the service worker.

It attaches your résumé to Resume/CV upload fields automatically (DataTransfer — the same
mechanism Simplify/JobRight use): a company-matched tailored .docx when one exists, else the
PDF configured in `applicant_profile.yaml` (`resume_files:`), else the rendered base résumé.
The widget panel shows **which résumé file will be attached** (name + upload date) with a
**Replace** button — upload a newer PDF there any time you iterate your résumé and every
autofill from then on uses it. Dates fill in every shape ATSes serve: month/year dropdowns
(native or react-select "January…" lists), split month + year boxes, or one MM/YYYY field.
Education sections (school / degree / discipline / GPA / end dates) fill from the profile's
`education:` list and **work-experience sections** (company / title / dates / "I currently
work here") fill from your résumé's work history — on Greenhouse both click "Add another"
for extra entries. EEO / voluntary self-identification questions answer from your `eeoc:`
presets across each ATS's option vocabulary; compliance screeners (18+, previously
employed here, government-official, conflict-of-interest, insider referral, AI-tools
usage) answer from `preferences:` — including nonstandard consent vocabularies like a
lone "Confirmed" option — and the in-page panel lists any fields that still **need your
review** — click one to jump straight to it. **Open-ended questions** ("Why do you want to
work here?", "What's your biggest accomplishment?") are drafted by the local LLM from the
page's job description, your résumé, and the `essay_facts:` block in
`applicant_profile.yaml` — drafts are always flagged for your review, never trusted
blindly. Availability questions answer from `preferences.earliest_start_date`. On Workday
it works the wizard **page by page**: fill the step, click Save and Continue, fill the
next — stopping at the review step. It NEVER clicks Submit.

If the backend is offline it still fills standard fields from a cached copy of your profile
(no AI essays, no résumé attach).

Backed by `server/autofill.py` (`/api/autofill/profile|plan|history|resume_file|health`) and
the pure `agents/autofill_mapper.py`. Verify with `python -m pytest
tests/test_autofill_mapper.py tests/test_autofill_mapper_profile_sync.py
tests/test_autofill_api.py -q` and, with the dashboard up, `python -m pytest
tests/e2e/test_extension_autofill.py tests/e2e/test_extension_autofill_greenhouse.py
tests/e2e/test_extension_autofill_workday_multipage.py -q -m live` (manual QA fixtures:
`/static/qa_greenhouse.html`, `/static/qa_workday.html`).

---

## Companies & Advisor — target-account tracking

Beyond the per-job Kanban board, the dashboard tracks the search at the **company**
level — target accounts, the full pipeline history within each one, and a
since-date report for advisor/mentor conversations.

**Companies tab** — one card per target company (tailored profile teaser +
pipeline counts across `watching / applied / in_play / closed`), opening into a
detail view: the full profile (`overview_md`, `why_fit_md`, `hiring_bar_md`,
plus a free-text `notes_md`) and a **pipeline tree** grouping every job at that
company into the same four stages. Companies are seeded from a gitignored
`config/companies_seed.yaml` (copy `config/companies_seed.example.yaml` to
start) via `venv/bin/python scripts/seed_companies.py` — an idempotent upsert
keyed on the normalized company name that never overwrites a row you've hand-
edited (`profile_source: manual`) or one still mid-draft. Jobs already in the
DB link to their company automatically by normalized name on every read
(`db/company_linking.py`), so scanner finds from *before* a company was added
still show up in its tree.

**LLM company profiler** (`agents/company_profiler.py`) — drafts
`overview_md` / `why_fit_md` / `hiring_bar_md` for a company from its careers
page + your résumé summary, locally via Ollama, as a background task (Create
and Refresh both trigger a draft). It never invents facts the page doesn't
support — a thin careers page yields a thin, honest profile rather than
hallucinated detail — and a Refresh snapshots the prior profile first so one
click undoes a bad redraft.

**Advisor report tab** — pick a since-date and get a stakeholder-ready report:
headline stats (applied / responses / interviews / closed, each a *distinct*
application count so re-entering a status never double-counts) plus a
per-company timeline of every application that hit a real milestone in the
window. Pipeline churn (found/scored/materials-ready noise) is filtered out so
the report stays readable. **Print to PDF** from the browser's print dialog for
a clean, dark-mode-legible printout to bring to a meeting.

**External-apply capture** — for applications made outside JobPilot (a direct
company-site apply, a referral), record them without losing pipeline history:
the extension's **✓ Mark applied** button (in the autofill widget) or the
dashboard's **+ Log apply** modal both POST to `/api/applied/record`, which
matches an existing Job by URL (exact, then tracking-param-stripped canonical
URL), falls back to normalized title+company, or creates a minimal Job+
Application if nothing matches. Idempotent — recording an already-applied (or
further-along) application is a no-op rather than a regression.

**Status history (`application_events`)** — every `Application.status` write
in the codebase now goes through one function, `record_status_change`
(`db/database.py`) — the single write-path that appends an immutable
`ApplicationEvent` (from/to status, source, timestamp) alongside the status
change, and stamps `date_applied` / `response_date` / `interview_date` the
*first* time each is reached. This is what the Advisor report and each
company's pipeline tree render as a timeline. Migration 006
(`db/migrations/006_add_companies_and_events.py`) added the `companies` and
`application_events` tables plus `applications.lead_source`,
`applications.next_action`, and `jobs.company_id`, and backfilled approximate
events (`source="backfill"`) for pre-migration applications that had none.

Backed by `server/companies.py` (`/api/companies`, `/api/company/{id}`,
`/api/company/{id}/refresh`), `server/advisor.py` (`/api/advisor/report`), and
`server/applied.py` (`/api/applied/record`). Verify with `python -m pytest
tests/test_companies_api.py tests/test_company_names.py
tests/test_company_page_extraction.py tests/test_company_profiler.py
tests/test_models_companies.py tests/test_seed_companies.py
tests/test_advisor_report.py tests/test_applied_record.py -q` and, with the
dashboard up, `python -m pytest
tests/e2e/test_companies_advisor_contracts.py -q -m live`.

---

## Google Sheet tracker sync

The dashboard can sync the jobs you've applied to into your own Google Sheet —
**compare** what's already logged, then **add** the rest, never duplicating. Click
**Sync to Sheet** in the results toolbar: it reads your sheet, tags each applied job
**✓ In sheet** or **+ New** (new pre-selected), and appends only the ones you pick. It
only ever appends — existing rows are never edited or deleted.

It adapts to *your* sheet's columns: JobPilot maps its fields (Company, Role/Title, Date
Applied, Status, Link, Location, Pay, Source, Fit, Notes) onto whatever headers you
already have; an empty sheet gets a clean header row written for it. Matching is by job
URL first, then company + title, so re-syncing is idempotent.

**One-time setup (service account):**

1. In the [Google Cloud Console](https://console.cloud.google.com/), pick/create a
   project and enable the **Google Sheets API**.
2. Create a **Service account**, then **Keys → Add key → JSON**, and save the file as
   `config/google_credentials.json` (gitignored).
3. Open that JSON, copy the `client_email`, and **share your sheet with that address as
   Editor**.
4. Point `config/settings.yaml` `google_sheets:` at your sheet (`spreadsheet_id`,
   optional `worksheet`), then reopen the Tracker modal.

Until creds are present the feature degrades gracefully — the modal shows these exact
steps instead of erroring. Backed by `server/sheets.py`
(`/api/sheet/health|compare|sync`) and the pure `agents/sheet_sync.py`. Verify with
`python -m pytest tests/test_sheet_sync.py tests/test_sheets_api.py -q`.

---

## Project structure

```
Personal-JobPilot/
├── agents/
│   ├── scanner/                 # One file per source
│   │   ├── career_pages.py      #   Greenhouse + Lever board scanners
│   │   ├── ashby.py             #   Ashby board scanner
│   │   └── edjoin.py            #   EdJoin (Playwright, Bay-Area school-district BT roles)
│   ├── ranker.py                # 3-stage LLM scoring pipeline (+ AI-intensity, hourly comp)
│   ├── tailor.py                # Resume + cover letter .docx generation (track-aware)
│   ├── interview_prep.py        # Local mock-interview prep-pack generator
│   ├── outreach.py              # Local networking-outreach drafter (drafts only)
│   ├── autofill_mapper.py       # Deterministic form-field mapper for the extension
│   ├── auto_applier/            # Playwright submission bot
│   ├── company_profiler.py      # LLM-drafted tailored company profiles (local Ollama)
│   └── sheet_sync.py            # Pure match/row logic for the Google Sheet tracker
├── config/
│   ├── settings.yaml            # Search keywords, schedule, thresholds, hourly floor
│   ├── archetypes.yaml          # 10 archetypes × 10 dimensions × weights + thresholds
│   ├── target_companies.yaml    # Career pages to monitor
│   ├── base_resume.example.yaml         # ← copy to base_resume.yaml (+ base_resume_bt.yaml)
│   ├── applicant_profile.example.yaml   # ← copy to applicant_profile.yaml
│   └── companies_seed.example.yaml      # ← copy to companies_seed.yaml (Companies tab)
├── db/
│   ├── models.py                # SQLAlchemy models
│   ├── database.py              # Session management + record_status_change (single write-path)
│   ├── company_linking.py       # Shared job↔company matching (seeder + dashboard reads)
│   └── migrations/              # Schema migrations (004 ai-intensity, 005 hourly comp,
│                                 #   006 companies + application_events)
├── server/
│   ├── dashboard.py             # FastAPI app + SSE + interview/outreach/tailor routes
│   ├── static/index.html        # Single-file UI (Indeed-style, dark mode, Kanban board)
│   ├── autofill.py              # Autofill API for the browser extension
│   ├── companies.py             # Companies tab API (profiles + pipeline trees)
│   ├── advisor.py               # Advisor report API (since-date event aggregation)
│   ├── applied.py               # External-apply capture API (/api/applied/record)
│   └── sheets.py                # Google Sheet tracker-sync API
├── scripts/
│   └── seed_companies.py        # Idempotent Companies-tab seeder from companies_seed.yaml
├── browser-extension/          # MV3 autofill extension (popup, service worker, scan/fill)
├── utils/
│   ├── ollama_client.py         # Ollama wrapper with JSON-mode + retries
│   ├── dedup.py                 # Fuzzy job dedup
│   ├── company_names.py         # Canonical company-name normalization
│   └── notifications.py         # Windows toast for high-fit jobs
├── tests/                       # pytest suite for deterministic surfaces
├── scheduler.py                 # Entry point — starts APScheduler
├── watchdog.py                  # Supervisor — keeps all 3 services alive
├── start_jobpilot.bat           # Windows one-click launcher (runs the watchdog)
└── register_autostart.bat       # Install/remove login auto-start (no admin)
```

---

## Reliability — it stays up on its own

Running three long-lived processes on a laptop means they eventually die — a reboot, an OOM, a flaky scan. Babysitting them by hand is exactly the toil this project exists to kill, so the supervision is automated too:

- **`watchdog.py`** is a single supervisor that starts Ollama, the dashboard, and the scheduler, then health-checks them on a 30-second loop. Ollama and the dashboard are checked over HTTP (so a wedged-but-alive process still gets recovered); the scheduler is checked by process liveness. Anything down gets restarted, with a boot grace window so a service that's merely starting up is never thrashed. Already-healthy services are left untouched — no duplicate processes.
- **`register_autostart.bat`** drops a hidden launcher in the per-user Startup folder (no admin rights required) so the watchdog — and therefore the whole pipeline — comes back automatically on every login. After a reboot you do nothing; the dashboard is already live at `http://127.0.0.1:7777`.

Net effect: the system is genuinely fire-and-forget. Reboot your machine and the job hunt picks itself back up.

---

## What's next

- [x] ~~Browser extension for one-click autofill from any application page~~ — **shipped** (see above)
- [x] ~~Email auto-tracking~~ — **shipped** as a review queue: read-only Gmail IMAP (`config/gmail.example.yaml`) reads confirmation / rejection / interview mail and proposes board updates you approve in "Sync from email"; it also fetches ATS verification codes for the extension
- [ ] Bayesian fit-score calibration — re-weight dims based on which past applications got responses
- [ ] Anonymized weekly digest export for accountability buddies
- [ ] Multi-applicant mode (turn it into a service for friends who are job searching)

---

## About me

I'm **Matthew Cromaz** — MS Quantitative Economics, Cal Poly SLO. Currently looking for **AI Engineer / Data Scientist / Data Analyst / Quantitative Analyst** roles in the Bay Area.

- 🌐 [LinkedIn](https://www.linkedin.com/in/matthew-cromaz)
- 💻 [GitHub](https://github.com/TheCromazone)
- 📧 Reach out if you're hiring — happy to walk through this codebase or any of my other projects.

---

## License

MIT — see [LICENSE](LICENSE). Built for personal use; share-alike encouraged. PRs welcome if you've extended it for your own search.
