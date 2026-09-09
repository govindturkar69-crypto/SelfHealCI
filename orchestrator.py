from github_client import get_latest_failed_run, get_failed_job, get_job_logs, extract_error_lines
from classifier import classify_error
from fix_generator import generate_fix
from memory_store import find_similar_incidents, store_incident
from pr_creator import create_issue


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

    # Step 6: generate a fix, informed by memory
    fix_text = generate_fix(signature, similar_incidents=similar)
    print("\n--- Suggested Fix ---")
    print(fix_text)

    # Step 7: open a GitHub issue with the diagnosis
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

    # Step 8: store this incident in memory as unconfirmed (success=None), tagged to the user
    store_incident(
        category=signature["category"],
        error_message=signature["primary_message"],
        fix_text=fix_text,
        success=None,
        repo=repo,
        user_id=user_id
    )
    print("\nStored incident in memory (pending confirmation).")

    return {"status": "completed", "issue_url": issue["html_url"]}


if __name__ == "__main__":
    run_agent("govindturkar69-crypto/NexusCode")