# SelfHealCI — Project Explanation Guide

This document explains SelfHealCI in narrative form: what problem it solves, how it works end to end, the decisions made along the way, and how to talk about it (e.g. in a viva or project defense).

## 1. The problem

CI/CD pipelines fail constantly, for a wide range of reasons — missing artifacts, flaky dependencies, broken tests, misconfigured jobs. Diagnosing a failure usually means a developer opening the Actions log, scrolling through hundreds of lines of noise, finding the actual error, and figuring out a fix — every single time, even for failures similar to ones seen before. There's no memory of "we've hit this exact kind of error before, and here's what fixed it," and no tool that will actually attempt the fix itself when it's confident enough to do so safely.

SelfHealCI automates both halves of that loop where it safely can — diagnosis AND, when there's enough signal, an actual verified code fix — and remembers the outcome of every attempt so it improves over time rather than starting from zero every time. It's also built as a real multi-tenant tool: any developer can connect their own GitHub account and use it on their own repos, not just a fixed personal script.

## 2. What "self-learning" means here

This is not a machine-learning model being retrained — it's a **memory + feedback loop**:

1. Every diagnosed failure is embedded into a vector and stored alongside its suggested fix.
2. When a *new* failure comes in, the system embeds it too and searches for semantically similar past incidents.
3. Those past incidents — including whether their fix actually worked — are given to Gemini as context before it generates a new advisory suggestion.
4. Once a human confirms (via the dashboard or CLI) whether a given suggestion worked, that outcome is written back to memory.
5. Future similar failures now benefit from *confirmed* history, not just guesses.

This is the same principle behind retrieval-augmented generation (RAG), applied to an operational feedback loop instead of a static knowledge base.

## 3. Two paths: autonomous patch vs. advisory diagnosis

SelfHealCI doesn't treat every failure the same way — it branches based on how much real signal it has.

**Path A — Autonomous patch (when a real file/line is identifiable):**
1. The classifier scans the raw log for a pattern like `calculator.py:2:` — the kind of specific reference a real stack trace gives you.
2. If found, the agent fetches that file's *actual current content* from GitHub (not a guess — the real code).
3. Gemini is asked to return a complete, corrected version of that file.
4. The agent clones the repo fresh into a temp directory, overwrites the file with the proposed fix, and runs the project's real test suite inside an isolated Docker container.
5. Only if that test run genuinely passes does the agent create a branch, commit the fix, and open a real pull request — clearly labeled as sandbox-verified but still needing human review before merge.
6. If the test run fails, the agent does **not** open a PR with a broken fix — it falls through to Path B instead.

**Path B — Advisory diagnosis (the fallback, and the only path when no file/line is found):**
1. The classifier still produces a structured category and message, even without a specific file.
2. Memory is searched for similar past incidents (skipped if the error is too generic — see the thin-memory discussion below).
3. Gemini generates a diagnosis and a suggested fix, in plain English.
4. A GitHub issue is opened with that diagnosis, explicitly marked as unverified.
5. The incident is stored as "pending," and a human later confirms whether it turned out to be right.

The key design principle: **the system only acts autonomously when it can prove the result works.** Everywhere else, it stays advisory and defers to a human.

## 4. End-to-end walkthrough (autonomous patch path, as actually demonstrated)

Using the project's own test fixture (`selfhealci-test-fixture`, a small repo with a deliberate `ZeroDivisionError` bug):

1. **Detect** — the agent finds the latest failed run and job on the connected repo.
2. **Extract** — the raw log is scanned; a line like `calculator.py:2: ZeroDivisionError` is found.
3. **Classify** — categorized as `test_failure`, with `calculator.py` line `2` extracted as the specific file reference.
4. **Fetch real code** — the actual current content of `calculator.py` is pulled from GitHub.
5. **Generate a patch** — Gemini is given the file and the error, and returns a corrected version (e.g. guarding against division by zero).
6. **Sandbox-test it** — the repo is cloned fresh, the file is overwritten with the proposed fix, and `pytest` is run for real inside a Docker container.
7. **Verify** — the container's exit code and logs are checked. A `0` exit code means the fix genuinely resolved the failure without a human ever reviewing the code first.
8. **Ship it (carefully)** — a new branch is created, the fix is committed, and a pull request is opened — titled `[SelfHealCI] Auto-fix: test_failure`, with the PR body stating plainly that it was sandbox-verified but still needs human review before merging.
9. **Remember** — the incident is stored in memory, including a link to the PR.

This was run live and produced a real, working pull request with a genuine, tested code fix — not a mock or simulated result.

## 5. Multi-user architecture

- **Authentication:** a dedicated GitHub OAuth App (separate from any other project's OAuth app) handles login. `/auth/github/login` redirects to GitHub; `/auth/github/callback` exchanges the returned code for a real access token and fetches the user's GitHub profile.
- **Storage:** each user is upserted into a `users` table (GitHub ID, username, access token). Session cookies (signed via Starlette's `SessionMiddleware`) store only an internal user ID — never the raw token client-side.
- **Per-request token resolution:** every protected endpoint looks up the *current* user's token from the database on each request, so the agent always acts with that user's actual GitHub permissions.
- **Data isolation:** the `incidents` table has a `user_id` foreign key; every read query filters by the logged-in user's ID, so no user can see another's incident history.
- **No silent fallback:** an unauthenticated request to `/run-agent` or `/incidents` is refused with a 401, not silently run under a shared token — an important safety property once this becomes genuinely public.

## 6. Key engineering decisions and why

**Why branch between autonomous and advisory instead of always attempting a patch?**
A confident wrong patch is worse than no patch. Requiring a specific, real file/line reference before even attempting generation avoids feeding Gemini a task it has no real chance of grounding correctly (patching "something, somewhere" from a bare exit code). And even then, the sandbox test is the actual gate — generation alone is never trusted.

**Why Docker for the sandbox instead of just trusting the LLM's fix?**
Because LLM-generated code can look correct and still be wrong. Running the real test suite in a disposable, isolated container is the only way to know, with actual evidence, whether a patch works — not just whether it reads plausibly.

**Why per-user OAuth tokens instead of one shared token?**
Two reasons: correctness (the agent should act with the permissions of the person who asked it to, not the original developer) and safety (a public tool that silently used a shared personal token for every visitor's actions would be a real security problem).

**The "thin memory" problem, discovered through testing.**
Early in testing, when the memory store had only 1–2 entries, a *generic* new error retrieved an *unrelated* past incident as its "most similar" match, and Gemini's advisory fix leaned on that irrelevant context, producing a plausible-sounding but wrong diagnosis. The fix: the classifier distinguishes a *specific* diagnosis from a *generic* one, and the advisory fix-generator only uses memory context when the diagnosis is specific enough — otherwise it honestly tells the user to dig further rather than fabricate a cause. This is a real, generalizable lesson about retrieval-augmented systems: sparse or low-quality memory can actively mislead, not just fail to help.

## 7. How each file maps to the pipeline

| Stage | File | Key functions |
|---|---|---|
| Detect + extract | `github_client.py` | `get_latest_failed_run`, `get_failed_job`, `get_job_logs`, `extract_error_lines`, `get_file_content` |
| Classify + locate | `classifier.py` | `classify_error`, `extract_file_and_line` |
| Recall + remember | `memory_store.py` | `get_embedding`, `store_incident`, `find_similar_incidents`, `get_unconfirmed_incidents`, `update_incident_outcome` |
| Diagnose (advisory) | `fix_generator.py` | `generate_fix` |
| Patch (autonomous) | `fix_generator.py` | `generate_patch` |
| Verify | `sandbox.py` | `clone_repo`, `run_tests_in_container`, `apply_patch_and_test` |
| Report | `pr_creator.py` | `create_issue`, `create_branch`, `commit_file`, `create_pull_request` |
| Orchestrate | `orchestrator.py` | `run_agent`, `try_auto_patch` |
| Auth | `main.py` | `github_login`, `github_callback`, session handling |
| Serve | `main.py` | FastAPI routes: `/incidents`, `/incidents/unconfirmed`, `/my-repos`, `/run-agent`, `/incidents/{id}/confirm`, `/dashboard` |
| Confirm | `confirm_outcome.py`, dashboard UI | CLI and in-browser outcome confirmation |

## 8. What to say if asked "is this really AI" / "what's novel here"

- The novelty isn't the LLM call itself — it's **the combination of a verification gate and a feedback loop**: the system doesn't just generate a plausible-looking fix, it proves the fix works against the real test suite before ever proposing it, and every outcome (proven or advisory) feeds back into future diagnoses.
- The **thin-memory finding** is a genuine, demonstrable engineering result from testing this system, not a hypothetical.
- The system is a real, working, multi-service pipeline: live GitHub OAuth, a real vector database, a real containerized sandbox that actually runs test suites, and a served API + dashboard supporting multiple independent users — not a mock or a notebook demo.

## 9. Anticipated questions

- **"What if the LLM's patch introduces a different bug the test suite doesn't catch?"** — This is an honest limitation: sandbox verification is only as good as the test suite it runs. The PR is still opened as a human-reviewed pull request, not auto-merged, so a human is always the final gate before the fix reaches production.
- **"What happens if two errors are similar but need different fixes?"** — In the advisory path, the system ranks by similarity *and* confirmed success; conflicting historical outcomes are both shown to Gemini, which is instructed to prefer confirmed-working fixes and avoid confirmed-failing ones.
- **"Why not always try to auto-patch?"** — Because most CI failures don't come with enough signal (a specific file/line) to safely attempt one, and guessing without that signal is how you get confidently wrong patches. The advisory fallback exists specifically for that majority case.
- **"How would this scale to many users/repos?"** — The architecture already supports it: every function is parameterized by `token`, `repo`, and `user_id`; incidents and GitHub actions are all scoped per-user; the main scaling consideration left is background/scheduled checking instead of manual triggering.