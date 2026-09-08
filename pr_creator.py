import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json"
}

def get_default_branch_sha(repo: str, branch: str = "main") -> str:
    """Gets the latest commit SHA of the given branch."""
    url = f"https://api.github.com/repos/{repo}/git/ref/heads/{branch}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()["object"]["sha"]

def create_branch(repo: str, new_branch: str, base_sha: str) -> dict:
    """Creates a new branch pointing at base_sha."""
    url = f"https://api.github.com/repos/{repo}/git/refs"
    payload = {
        "ref": f"refs/heads/{new_branch}",
        "sha": base_sha
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()

import base64

def commit_file(repo: str, branch: str, file_path: str, content: str, commit_message: str) -> dict:
    """Creates or updates a file on the given branch."""
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    encoded_content = base64.b64encode(content.encode()).decode()

    payload = {
        "message": commit_message,
        "content": encoded_content,
        "branch": branch
    }
    response = requests.put(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()

def create_pull_request(repo: str, branch: str, base: str, title: str, body: str) -> dict:
    """Opens a PR from branch into base."""
    url = f"https://api.github.com/repos/{repo}/pulls"
    payload = {
        "title": title,
        "head": branch,
        "base": base,
        "body": body
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()

def create_issue(repo: str, title: str, body: str) -> dict:
    """Opens a GitHub issue with the agent's diagnosis and suggested fix."""
    url = f"https://api.github.com/repos/{repo}/issues"
    payload = {
        "title": title,
        "body": body
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    repo = "govindturkar69-crypto/NexusCode"
    sha = get_default_branch_sha(repo)
    print(f"Latest commit SHA on main: {sha}")

    branch_name = "selfhealci-test-branch"
    result = create_branch(repo, branch_name, sha)
    print(f"\nCreated branch: {result['ref']}")

    commit_result = commit_file(
        repo,
        branch_name,
        "selfhealci_test.md",
        "# SelfHealCI test\n\nThis file was committed automatically by SelfHealCI to test PR creation.\n",
        "Test commit from SelfHealCI"
    )
    print(f"\nCommitted file: {commit_result['content']['path']}")

    pr_result = create_pull_request(
        repo,
        branch_name,
        "main",
        "SelfHealCI: automated test PR",
        "This PR was opened automatically by SelfHealCI to validate the PR-creation pipeline."
    )
    print(f"\nPull request created: {pr_result['html_url']}")