import os
import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_TOKEN = os.getenv("GITHUB_TOKEN")


def _headers(token: str = None) -> dict:
    return {
        "Authorization": f"Bearer {token or DEFAULT_TOKEN}",
        "Accept": "application/vnd.github+json"
    }


def get_latest_failed_run(repo: str, token: str = None) -> dict:
    """Returns the most recent failed workflow run, or None."""
    url = f"https://api.github.com/repos/{repo}/actions/runs"
    response = requests.get(url, headers=_headers(token))
    data = response.json()

    for run in data.get("workflow_runs", []):
        if run["conclusion"] == "failure":
            return run
    return None


def get_failed_job(repo: str, run_id: int, token: str = None) -> dict:
    """Returns the first failed job in a given run, or None."""
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
    response = requests.get(url, headers=_headers(token))
    data = response.json()

    for job in data.get("jobs", []):
        if job["conclusion"] == "failure":
            return job
    return None


def get_job_logs(repo: str, job_id: int, token: str = None) -> str:
    """Returns the raw log text for a job."""
    url = f"https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs"
    response = requests.get(url, headers=_headers(token))
    return response.text


def extract_error_lines(log_text: str) -> list[str]:
    """Pulls lines that look like errors out of a raw log."""
    lines = log_text.splitlines()
    error_keywords = ["error", "Error", "ERROR", "failed", "Failed", "FAILED", "Traceback", "exception"]
    return [line for line in lines if any(kw in line for kw in error_keywords)]

import base64

def get_file_content(repo: str, file_path: str, ref: str = "main", token: str = None) -> str:
    """Fetches a file's raw text content from a repo at a given ref."""
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    response = requests.get(url, headers=_headers(token), params={"ref": ref})
    response.raise_for_status()
    data = response.json()
    return base64.b64decode(data["content"]).decode("utf-8")