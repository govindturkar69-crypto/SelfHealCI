# SelfHealCI — Project Explanation Guide

This document explains SelfHealCI in narrative form: what problem it solves, how it works end to end, the decisions made along the way, and how to talk about it (e.g. in a viva or project defense).

## 1. The problem

CI/CD pipelines fail constantly, for a wide range of reasons — missing artifacts, flaky dependencies, broken tests, misconfigured jobs. Diagnosing a failure usually means a developer opening the Actions log, scrolling through hundreds of lines of noise, finding the actual error, and figuring out a fix — every single time, even for failures that are similar to ones seen before. There's no memory of "we've hit this exact kind of error before, and here's what fixed it."

SelfHealCI automates the *diagnosis* half of that loop, and — critically — remembers the outcome of every attempt, so it gets better at diagnosing similar failures over time rather than starting from zero every time.

## 2. What "self-learning" means here

This is not a machine-learning model being retrained — it's a **memory + feedback loop**:

1. Every diagnosed failure is embedded into a vector and stored alongside its suggested fix.
2. When a *new* failure comes in, the system embeds it too and searches for semantically similar past incidents.
3. Those past incidents — including whether their fix actually worked — are given to Gemini as context before it generates a new suggestion.
4. Once a human confirms whether a given suggestion worked, that outcome is written back to memory.
5. Future similar failures now benefit from *confirmed* history, not just guesses.

This is the same principle behind retrieval-augmented generation (RAG), applied to an operational feedback loop instead of a static knowledge base.

## 3. End-to-end walkthrough (what actually happens on one run)

1. **Detect** — `github_client.py` calls the GitHub Actions API for the target repo, finds the most recent failed workflow run, then the specific failed job within it.
2. **Extract** — the job's raw log (often 1,000+ lines) is fetched and filtered down to lines containing error-indicating keywords.
3. **Classify** — `classifier.py` matches those lines against a set of category patterns (dependency error, test failure, build error, lint error, timeout, permission error) and falls back to a "generic exit-code error" category only if nothing specific matches — flagging that fallback explicitly so downstream steps know not to over-trust it.
4. **Recall** — `memory_store.py` embeds the error message (via Gemini's embedding model) and does a cosine-similarity search against every past incident stored in Postgres/pgvector, ranked by confirmed success first.
5. **Diagnose** — `fix_generator.py` builds a prompt combining the error signature and (if the diagnosis is specific enough) the retrieved similar incidents, and asks Gemini for a concise diagnosis and fix.
6. **Report** — `pr_creator.py` opens a real GitHub issue on the target repo containing the diagnosis, explicitly marked as unverified/needing human review.
7. **Remember** — the incident (error, fix, category) is stored with `success = NULL` ("pending").
8. **Confirm (later)** — a human reviews the issue, applies or rejects the fix, and runs `confirm_outcome.py` to mark the incident as fixed or not — updating memory for next time.

## 4. Key engineering decisions and why

**Why advisory (issue + suggestion) instead of fully autonomous (auto-patch)?**
Full autonomy would require giving Gemini the actual source files, having it generate a diff, applying that diff, and testing it before committing — a much larger and riskier scope (a bad autonomous patch is worse than no patch). Starting with an advisory agent that always keeps a human in the loop is both safer and a more honest first milestone. The Docker sandbox module was still built and proven (it can clone a repo and run its real test suite in an isolated container) — it's ready to be wired in once patch generation exists.

**The "thin memory" problem, discovered through testing.**
Early in testing, when the memory store had only 1–2 entries, a *generic* new error ("process exited with code 1") retrieved an *unrelated* past incident (a missing build artifact) as its "most similar" match — and Gemini's fix leaned on that irrelevant context, producing a plausible-sounding but wrong diagnosis. The fix: the classifier now distinguishes a *specific* diagnosis (a recognizable error category) from a *generic* one (just an exit code, no real signal), and the fix-generator only uses memory context when the diagnosis is specific — otherwise it honestly tells the user to dig further into the logs rather than fabricate a cause. This is a real, generalizable lesson about retrieval-augmented systems: sparse or low-quality memory can actively mislead, not just fail to help.

**Why Supabase/pgvector for memory instead of a dedicated vector DB (e.g. Pinecone)?**
Reuses infrastructure already familiar from NexusCode (Postgres via Supabase), avoids adding a new provider/dependency, and `pgvector` is more than sufficient at this project's scale.

**Why Gemini over OpenAI?**
Consistency with NexusCode's existing AI integration and API key.

## 5. How each file maps to the pipeline

| Stage | File | Key functions |
|---|---|---|
| Detect + extract | `github_client.py` | `get_latest_failed_run`, `get_failed_job`, `get_job_logs`, `extract_error_lines` |
| Classify | `classifier.py` | `classify_error` |
| Recall + remember | `memory_store.py` | `get_embedding`, `store_incident`, `find_similar_incidents`, `get_unconfirmed_incidents`, `update_incident_outcome` |
| Diagnose | `fix_generator.py` | `generate_fix` |
| Report | `pr_creator.py` | `create_issue` (also `create_branch`, `commit_file`, `create_pull_request` for the PR-creation capability proven separately) |
| Orchestrate | `orchestrator.py` | `run_agent` |
| Serve | `main.py` | FastAPI routes: `/incidents`, `/incidents/unconfirmed`, `/run-agent`, `/dashboard` |
| Sandbox (standalone) | `sandbox.py` | `clone_repo`, `run_tests_in_container` |
| Confirm | `confirm_outcome.py` | interactive CLI over `memory_store.py` |

## 6. What to say if asked "is this really AI" / "what's novel here"

- The novelty isn't the LLM call itself — it's the **feedback loop**: every suggestion's real-world outcome is captured and fed back into future suggestions, which is what "self-learning" means for an agent that isn't being retrained.
- The **thin-memory finding** is a genuine, demonstrable engineering result from testing this system, not a hypothetical — it's visible by comparing issue #3 (misled by irrelevant memory) against issue #4 (after the fix, honestly says "investigate further") on the live NexusCode repo.
- The system is a real, working, multi-service pipeline: live GitHub API integration, a real vector database, a real containerized sandbox, and a served API + dashboard — not a mock or a notebook demo.

## 7. Anticipated questions

- **"What happens if two errors are similar but need different fixes?"** — The system ranks by similarity *and* confirmed success; conflicting historical outcomes are both shown to Gemini, which is instructed to prefer confirmed-working fixes and avoid confirmed-failing ones.
- **"What if the repo has no CI failures?"** — `run_agent` checks for the latest failed run and exits cleanly with "nothing to do" if none exists.
- **"How would this scale to many repos?"** — The architecture already supports it: `repo` is a parameter on every call, and incidents are tagged by repo in storage, so cross-repo pattern matching (e.g. "this dependency error type is common across all your repos") is a natural extension.