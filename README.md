# SelfHealCI

**An autonomous, self-learning CI/CD healing agent.** SelfHealCI watches a GitHub repository's Actions workflows, diagnoses failures, suggests fixes using Google Gemini, and remembers the outcome of every attempt — so its suggestions get better over time instead of guessing cold on every failure.

## What it does

1. Detects the latest failed GitHub Actions run on a given repo
2. Fetches the job logs and extracts the meaningful error lines out of hundreds/thousands of lines of noise
3. Classifies the error into a structured category (dependency error, test failure, build error, lint error, timeout, permission error, or a generic exit-code failure)
4. Retrieves similar past incidents from a vector-embedded memory store, including whether past suggested fixes actually worked
5. Asks Gemini to diagnose the failure and suggest a fix — informed by that history
6. Opens a GitHub issue with the diagnosis and suggested fix
7. Stores the incident in memory as "pending confirmation"
8. Once a human confirms whether the fix actually worked, the outcome is recorded — closing the feedback loop so future similar failures benefit from real, confirmed history

A Docker-based sandbox module is also included, capable of cloning a repo at a given ref and running its test suite in an isolated container — used during development to validate real failure/pass detection end-to-end (see [Design decisions](#design-decisions) for why this isn't yet wired into the live auto-fix flow).

## Architecture

```
GitHub Actions (any repo)
        │
        ▼
 github_client.py  ──► fetch failed run → failed job → raw logs → error lines
        │
        ▼
 classifier.py     ──► structured error signature (category, message, confidence)
        │
        ▼
 memory_store.py   ──► embed error, retrieve similar past incidents (pgvector)
        │
        ▼
 fix_generator.py  ──► Gemini-generated diagnosis + fix, informed by memory
        │
        ▼
 pr_creator.py     ──► opens a GitHub issue with the diagnosis
        │
        ▼
 memory_store.py   ──► stores the incident as "pending"
        │
        ▼
 confirm_outcome.py ─► (human, later) confirms fixed / not fixed → memory updated
```

All of this is orchestrated by `orchestrator.py` and exposed over HTTP by `main.py` (FastAPI), with a small dashboard at `/dashboard`.

## Tech stack

- **Backend:** Python, FastAPI, Uvicorn
- **AI:** Google Gemini (`gemini-3.6-flash` for diagnosis/fix generation, `gemini-embedding-001` for memory embeddings)
- **Memory / vector store:** PostgreSQL + `pgvector`, hosted on Supabase
- **Sandbox execution:** Docker (via the `docker` Python SDK)
- **GitHub integration:** GitHub REST API via `requests` (Actions runs/jobs/logs, branches, commits, issues, pull requests)
- **Frontend:** a single static HTML/JS dashboard page, no framework

## Project structure

```
SelfHealCI/
├── main.py              # FastAPI app: /incidents, /run-agent, /dashboard
├── orchestrator.py       # run_agent(): ties every module into one pipeline
├── github_client.py       # GitHub Actions runs/jobs/logs fetching
├── classifier.py           # error classification into structured signatures
├── fix_generator.py         # Gemini-based diagnosis + fix generation
├── memory_store.py           # embeddings, incident storage/retrieval (pgvector)
├── pr_creator.py               # branch/commit/PR/issue creation via GitHub API
├── confirm_outcome.py           # CLI to confirm pending incident outcomes
├── sandbox.py                    # Docker-based repo clone + test execution
├── static/dashboard.html          # web dashboard
├── requirements.txt
└── .env                             # GITHUB_TOKEN, GEMINI_API_KEY, DATABASE_URL
```

## Setup

1. Clone the repo and create a virtual environment:
   ```
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Create a `.env` file with:
   ```
   GITHUB_TOKEN=your_github_personal_access_token   # scopes: repo, workflow
   GEMINI_API_KEY=your_gemini_api_key
   DATABASE_URL=your_supabase_postgres_connection_string
   ```
3. In your Supabase project's SQL editor, run:
   ```sql
   create extension if not exists vector;

   create table incidents (
       id bigserial primary key,
       category text not null,
       error_message text not null,
       fix_text text not null,
       embedding vector(768),
       success boolean,
       repo text,
       created_at timestamptz default now()
   );
   ```
4. Start the server:
   ```
   uvicorn main:app --reload
   ```
5. Open `http://127.0.0.1:8000/dashboard`

## Usage

- **Dashboard:** enter a repo (`owner/repo`) and click "Run Agent" to check its latest failed workflow run.
- **API docs:** `http://127.0.0.1:8000/docs` (Swagger UI) for `GET /incidents`, `GET /incidents/unconfirmed`, `POST /run-agent`.
- **Confirming outcomes:** run `python confirm_outcome.py` to interactively review pending incidents and mark them fixed / not fixed.

## Design decisions

**Advisory, not fully autonomous.** SelfHealCI diagnoses failures and opens a GitHub issue with a suggested fix — it does not automatically generate and apply a code patch. Full auto-patching would require fetching the relevant source files, having Gemini generate an actual diff, and applying/testing it — a meaningfully larger and riskier scope. An advisory agent that a human reviews before acting is the safer and more realistic design for a first working version, and matches how most production "AI SRE" tooling operates today.

**The "thin memory" problem.** Early testing surfaced a real failure mode: when the memory store had very little data, retrieving "similar" past incidents could pull in *irrelevant* context, and the fix-generation prompt would lean on it too heavily — producing confident-sounding but wrong diagnoses. The fix was to have the classifier flag when it only has a generic, non-specific error (e.g. a bare exit code) via a `has_specific_diagnosis` flag, and have `fix_generator.py` skip memory context entirely in that case, honestly telling the user to investigate further rather than guessing. This is a general lesson for retrieval-augmented systems: sparse memory can mislead more than no memory at all.

## Known limitations

- The classifier uses regex-based pattern matching, not a learned model — it recognizes common categories but can still fall back to `generic_exit_error`/`unknown` on unfamiliar error formats.
- Memory quality depends on volume and diversity of confirmed outcomes; it improves as more incidents are confirmed over time.
- The Docker sandbox (repo clone + test execution) is built and tested standalone but not yet wired into the live pipeline, since the pipeline doesn't yet generate actual code patches to test.

## Future work

- Wire the sandbox into the pipeline once patch generation is added, to auto-verify a fix before opening a PR
- Scheduled/periodic checking instead of manual triggering
- Multi-repo dashboard view with success-rate analytics over time