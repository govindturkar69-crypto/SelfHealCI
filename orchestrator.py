from github_client import get_latest_failed_run, get_failed_job, get_job_logs, extract_error_lines, get_file_content
from classifier import classify_error, extract_file_and_line
from fix_generator import generate_fix, generate_patch
from memory_store import find_similar_incidents, store_incident
from pr_creator import create_issue, get_default_branch_sha, create_branch, commit_file, create_pull_request
from sandbox import apply_patch_and_test
import time


def run_agent(repo: str, token: str = None, user_id: int = None):
    print(f"\n=== SelfHealCI checking {repo} ===\n")

    # Step 1: find the latest failed run
    failed_run = get_latest_failed_run(repo, token=token)
    if not failed_run:
        print("No failed runs found. Nothing to do.")
        return {"status": "no_failed_runs"}

    print(f"Found failed run: {failed_run['name']} (id: {failed_run['id']})")

    # Step 2: find the failed job in that run
    failed_job = get_failed_job(repo, failed_run["id"], token=token)
    if not failed_job:
        print("No failed job found in this run.")
        return {"status": "no_failed_job"}

    print(f"Found failed job: {failed_job['name']} (id: {failed_job['id']})")

    # Step 3: fetch logs and extract error lines
    log_text = get_job_logs(repo, failed_job["id"], token=token)
    error_lines = extract_error_lines(log_text)

    if not error_lines:
        print("No error lines found in logs.")
        return {"status": "no_error_lines"}

    # Step 4: classify the error
    signature = classify_error(error_lines)
    print(f"\nClassified as: {signature['category']}")
    print(f"Primary message: {signature['primary_message']}")

    # Step 5: retrieve similar past incidents from memory
    similar = find_similar_incidents(signature["primary_message"])
    print(f"\nFound {len(similar)} similar past incident(s) in memory.")

    # Step 6: try to extract a specific file + line from the FULL log (not just the filtered error lines)
    file_ref = extract_file_and_line(log_text)

    if file_ref:
        print(f"\nFound a specific file reference: {file_ref['file_path']} (line {file_ref['line_number']})")
        patch_result = try_auto_patch(repo, file_ref, signature, token=token)
        if patch_result:
            store_incident(
                category=signature["category"],
                error_message=signature["primary_message"],
                fix_text=f"Auto-generated patch to {file_ref['file_path']}, verified passing in sandbox. PR: {patch_result['pr_url']}",
                success=None,
                repo=repo,
                user_id=user_id
            )
            return {"status": "patch_pr_opened", "pr_url": patch_result["pr_url"]}
        else:
            print("\nAuto-patch attempt did not produce a passing fix. Falling back to advisory issue.")

    # Fallback: advisory issue (no file reference found, or patch attempt failed sandbox testing)
    fix_text = generate_fix(signature, similar_incidents=similar)
    print("\n--- Suggested Fix (advisory) ---")
    print(fix_text)

    issue_title = "[SelfHealCI] " + signature["category"] + ": " + signature["primary_message"][:80]
    issue_body_lines = [
        "## Automated diagnosis by SelfHealCI",
        "",
        "**Failed run:** " + failed_run["name"] + " (#" + str(failed_run["run_number"]) + ")",
        "**Failed job:** " + failed_job["name"],
        "**Category:** " + signature["category"],
        "",
        "**Error:**",
        "```",
        signature["primary_message"],
        "```",
        "",
        "**Suggested fix:**",
        fix_text,
        "",
        "---",
        "*This issue was opened automatically. The fix above has not been applied or verified - please review before making changes.*",
    ]
    issue_body = "\n".join(issue_body_lines)

    issue = create_issue(repo, issue_title, issue_body, token=token)
    print("\nOpened issue: " + issue["html_url"])

    store_incident(
        category=signature["category"],
        error_message=signature["primary_message"],
        fix_text=fix_text,
        success=None,
        repo=repo,
        user_id=user_id
    )
    print("\nStored incident in memory (pending confirmation).")

    return {"status": "issue_opened", "issue_url": issue["html_url"]}


def try_auto_patch(repo: str, file_ref: dict, signature: dict, token: str = None):
    """Attempts to generate, test, and open a PR for a real code patch. Returns None if it doesn't pass sandbox testing."""
    file_path = file_ref["file_path"]

    try:
        file_content = get_file_content(repo, file_path, token=token)
    except Exception as e:
        print(f"Could not fetch file content for {file_path}: {e}")
        return None

    print(f"\nFetched {file_path} ({len(file_content)} chars). Asking Gemini for a patch...")
    new_content = generate_patch(signature, file_path, file_content)

    clone_url = f"https://github.com/{repo}.git" if not token else f"https://{token}@github.com/{repo}.git"

    print("Testing the patch in a sandbox...")
    test_result = apply_patch_and_test(clone_url, file_path, new_content)

    print(f"Sandbox test exit code: {test_result['exit_code']}")
    if test_result["exit_code"] != 0:
        print("Patch did NOT pass tests in sandbox.")
        print(test_result["logs"][-1000:])
        return None

    print("Patch PASSED tests in sandbox. Opening a PR...")

    branch_name = f"selfhealci-fix-{int(time.time())}"
    base_sha = get_default_branch_sha(repo, token=token)
    create_branch(repo, branch_name, base_sha, token=token)
    commit_file(
        repo, branch_name, file_path, new_content,
        f"SelfHealCI: auto-fix for {signature['category']}",
        token=token
    )
    pr = create_pull_request(
        repo, branch_name, "main",
        f"[SelfHealCI] Auto-fix: {signature['category']}",
        f"This PR was generated automatically by SelfHealCI.\n\n"
        f"**Error:** {signature['primary_message']}\n\n"
        f"The fix was tested in an isolated sandbox and the test suite passed. "
        f"Please review before merging.",
        token=token
    )
    return {"pr_url": pr["html_url"]}


if __name__ == "__main__":
    run_agent("govindturkar69-crypto/selfhealci-test-fixture")