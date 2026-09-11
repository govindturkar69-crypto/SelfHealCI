# SelfHealCI

**An autonomous, self-learning, multi-tenant CI/CD healing agent.** SelfHealCI watches a GitHub repository's Actions workflows, diagnoses failures, and can autonomously generate, sandbox-test, and open a pull request with a real code fix — falling back to an advisory diagnosis when it can't safely do that. Every outcome is remembered, so its suggestions improve over time instead of guessing cold on every failure. Any user can connect their own GitHub account and run it against their own repos.

## What it does

1. Detects the latest failed GitHub Actions run on a repo the user has connected
2. Fetches the job logs and extracts the meaningful error lines out of hundreds/thousands of lines of noise
3. Classifies the error into a structured category (dependency error, test failure, build error, lint error, timeout, permission error, or a generic exit-code failure)
4. **Attempts an autonomous fix** when the error includes a specific file/line reference (e.g. a Python traceback):
   - Fetches the real, current content of that file from GitHub
   - Asks Gemini to generate a full corrected version of the file
   - Clones the repo fresh and tests the patch in an isolated Docker container, running the project's real test suite
   - If the patch passes, opens a real pull request with the verified fix
5. **Falls back to an advisory diagnosis** when no specific file could be identified, or when the generated patch fails sandbox testing — retrieving similar past incidents from memory (with confirmed outcomes) to inform the diagnosis, and opening a GitHub issue instead of a PR
6. Stores every incident in memory as "pending confirmation"
7. Lets the user confirm, directly from the dashboard, whether a suggestion actually worked — closing the feedback loop so future similar failures benefit from real, confirmed history

## Multi-user / multi-tenant

SelfHealCI is not tied to one person's GitHub account. Any user can:
- Click "Connect GitHub" and authorize via a dedicated GitHub OAuth App
- Pick from a live list of their own repos (fetched from GitHub, not typed manually)
- Run the agent using **their own** GitHub token and permissions — never a shared/personal token
- See only **their own** incident history, fully isolated from other users' data
- Confirm outcomes on their own incidents directly from the dashboard

## Architecture

```
GitHub Actions (any connected repo)
        │
        ▼
 github_client.py  ──► fetch failed run → failed job → raw logs → error lines
        │
        ▼
 classifier.py     ──► structured error signature + optional file/line reference
        │
        ├─── file/line found ──────────────────────────────┐
        │                                                    ▼
        │                                     github_client.get_file_content()
        │                                                    │
        │                                                    ▼
        │                                     fix_generator.generate_patch()
        │                                        (Gemini writes a full fixed file)
        │                                                    │
        │                                                    ▼
        │                                     sandbox.apply_patch_and_test()
        │                                        (real clone, real Docker container,
        │                                         real test suite)
        │                                                    │
        │                                      pass ─────────┼───────── fail
        │                                       │                         │
        │                                       ▼                         │
        │                          pr_creator: branch, commit, open PR    │
        │                                                                 │
        └─── no file/line found ◄────────────────────────────────────────┘
                    │
                    ▼
 memory_store.py   ──► embed error, retrieve similar past incidents (pgvector)
        │
        ▼
 fix_generator.py  ──► Gemini-generated diagnosis + advisory fix, informed by memory
        │
        ▼
 pr_creator.py     ──► opens a GitHub issue with the diagnosis
        │
        ▼
 memory_store.py   ──► stores the incident as "pending", tied to the acting user
        │
        ▼
 dashboard (or CLI) ─► human confirms fixed / not fixed → memory updated
```

All of this is orchestrated by `orchestrator.py` and exposed over HTTP by `main.py` (FastAPI), with a dashboard at `/dashboard` and GitHub OAuth login at `/auth/github/login`.

## Tech stack

- **Backend:** Python, FastAPI, Uvicorn, Starlette sessions
- **AI:** Google Gemini (`gemini-3.6-flash` for diagnosis/patch generation, `gemini-embedding-001` for memory embeddings)
- **Memory / vector store:** PostgreSQL + `pgvector`, hosted on Supabase
- **Sandbox execution:** Docker (via the `docker` Python SDK) — real repo clones, real test suites, real isolation
- **Auth:** GitHub OAuth (dedicated OAuth App, per-user tokens stored server-side)
- **GitHub integration:** GitHub REST API via `requests` (Actions runs/jobs/logs, repo contents, branches, commits, issues, pull requests)
- **Frontend:** a single static HTML/JS dashboard page, no framework

## Project structure

```
SelfHealCI/
├── main.py               # FastAPI app: auth routes, /incidents, /run-agent, /my-repos, /dashboard
├── orchestrator.py        # run_agent(): the full pipeline, including auto-patch + fallback logic
├── github_client.py        # GitHub Actions runs/jobs/logs + file content fetching, per-user tokens
├── classifier.py             # error classification + file/line extraction from logs
├── fix_generator.py           # Gemini-based advisory diagnosis AND full-file patch generation
├── memory_store.py              # embeddings, incident storage/retrieval (pgvector), per-user scoping
├── pr_creator.py                  # branch/commit/PR/issue creation via GitHub API, per-user tokens
├── confirm_outcome.py               # CLI to confirm pending incident outcomes (dashboard also supports this)
├── sandbox.py                        # Docker-based repo clone + test execution + patch verification
├── static/dashboard.html              # web dashboard: login, repo picker, incidents, confirm buttons
├── requirements.txt
└── .env                                 # GITHUB_TOKEN, GEMINI_API_KEY, DATABASE_URL,
                                          # GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET, SESSION_SECRET
```

## Setup

1. Clone the repo and create a virtual environment:
   ```
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Register a GitHub OAuth App (github.com/settings/developers → New OAuth App) with callback URL `http://127.0.0.1:8080/auth/github/callback`.
3. Create a `.env` file with:
   ```
   GITHUB_TOKEN=your_github_personal_access_token   # scopes: repo, workflow — fallback/dev use
   GEMINI_API_KEY=your_gemini_api_key
   DATABASE_URL=your_supabase_postgres_connection_string
   GITHUB_OAUTH_CLIENT_ID=your_oauth_app_client_id
   GITHUB_OAUTH_CLIENT_SECRET=your_oauth_app_client_secret
   SESSION_SECRET=any_long_random_string
   ```
4. In your Supabase project's SQL editor, run:
   ```sql
   create extension if not exists vector;

   create table users (
       id bigserial primary key,
       github_id bigint unique not null,
       github_username text not null,
       github_access_token text not null,
       created_at timestamptz default now()
   );

   create table incidents (
       id bigserial primary key,
       category text not null,
       error_message text not null,
       fix_text text not null,
       embedding vector(768),
       success boolean,
       repo text,
       user_id bigint references users(id),
       created_at timestamptz default now()
   );
   ```
5. Start the server (note: port 8000 may be blocked on some Windows setups — use 8080):
   ```
   uvicorn main:app --reload --port 8080
   ```
6. Open `http://127.0.0.1:8080/dashboard`, click "Connect GitHub," and authorize.

## Usage

- **Dashboard:** connect your GitHub account, pick one of your own repos from the dropdown, and click "Run Agent."
- **Outcome confirmation:** click "✓ Mark Fixed" or "✗ Mark Not Fixed" directly on any pending incident card.
- **API docs:** `http://127.0.0.1:8080/docs` (Swagger UI).
- **CLI confirmation (alternative):** `python confirm_outcome.py` for interactive review from the terminal.

## Design decisions

**Auto-patch with a safe fallback, not auto-patch-or-nothing.** The system only attempts to generate and apply a real code patch when it has strong signal (a specific file and line number from a real stack trace). Even then, the patch is never trusted blindly — it's tested against the real test suite in an isolated Docker container before a PR is even opened, and if that test fails, the system cleanly falls back to the original advisory-issue behavior rather than committing something unverified or doing nothing at all.

**Per-user tokens, not a shared credential.** Every GitHub API call the agent makes on a user's behalf uses that specific user's own OAuth token, fetched fresh from the database per-request. There is no fallback to a shared/personal token once a user is authenticated — an unauthenticated request is refused outright (401), not silently run under someone else's identity.

**The "thin memory" problem.** Early testing surfaced a real failure mode in the advisory path: when the memory store had very little data, retrieving "similar" past incidents could pull in *irrelevant* context, and the fix-generation prompt would lean on it too heavily — producing confident-sounding but wrong diagnoses. The fix was to have the classifier flag when it only has a generic, non-specific error via a `has_specific_diagnosis` flag, and have `fix_generator.py` skip memory context entirely in that case, honestly telling the user to investigate further rather than guessing.

## Known limitations

- Auto-patch currently only triggers on errors that include a `file.py:line:`-style reference (Python tracebacks); other languages/formats fall back to advisory mode.
- The classifier uses regex-based pattern matching, not a learned model.
- Memory quality depends on volume and diversity of confirmed outcomes; it improves as more incidents are confirmed over time.
- Currently runs locally (`127.0.0.1`); not yet deployed to a public host.

## Future work

- Extend file/line extraction to other languages (JS/TS stack traces, Go, etc.)
- Scheduled/periodic checking instead of manual triggering
- Multi-repo dashboard view with success-rate analytics over time
- Notifications (email/Slack) when a new diagnosis or PR is ready