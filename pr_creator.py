import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_TOKEN = os.getenv("GITHUB_TOKEN")


def _headers(token: str = None) -> dict:
    return {
        "Authorization": f"Bearer {token or DEFAULT_TOKEN}",
        "Accept": "application/vnd.github+json"
    }


def get_default_branch_sha(repo: str, branch: str = "main", token: str = None) -> str:
    url = f"https://api.github.com/repos/{repo}/git/ref/heads/{branch}"
    response = requests.get(url, headers=_headers(token))
    response.raise_for_status()
    return response.json()["object"]["sha"]


def create_branch(repo: str, new_branch: str, base_sha: str, token: str = None) -> dict:
    url = f"https://api.github.com/repos/{repo}/git/refs"
    payload = {"ref": f"refs/heads/{new_branch}", "sha": base_sha}
    response = requests.post(url, headers=_headers(token), json=payload)
    response.raise_for_status()
    return response.json()


def commit_file(repo: str, branch: str, file_path: str, content: str, commit_message: str, token: str = None) -> dict:
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    encoded_content = base64.b64encode(content.encode()).decode()
    payload = {"message": commit_message, "content": encoded_content, "branch": branch}
    response = requests.put(url, headers=_headers(token), json=payload)
    response.raise_for_status()
    return response.json()


def create_pull_request(repo: str, branch: str, base: str, title: str, body: str, token: str = None) -> dict:
    url = f"https://api.github.com/repos/{repo}/pulls"
    payload = {"title": title, "head": branch, "base": base, "body": body}
    response = requests.post(url, headers=_headers(token), json=payload)
    response.raise_for_status()
    return response.json()


def create_issue(repo: str, title: str, body: str, token: str = None) -> dict:
    """Opens a GitHub issue with the agent's diagnosis and suggested fix."""
    url = f"https://api.github.com/repos/{repo}/issues"
    payload = {"title": title, "body": body}
    response = requests.post(url, headers=_headers(token), json=payload)
    response.raise_for_status()
    return response.json()