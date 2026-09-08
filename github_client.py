import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json"
}


def get_latest_failed_run(repo: str) -> dict:
    """Returns the most recent failed workflow run, or None."""
    url = f"https://api.github.com/repos/{repo}/actions/runs"
    response = requests.get(url, headers=HEADERS)
    data = response.json()

    for run in data.get("workflow_runs", []):
        if run["conclusion"] == "failure":
            return run
    return None


def get_failed_job(repo: str, run_id: int) -> dict:
    """Returns the first failed job in a given run, or None."""
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
    response = requests.get(url, headers=HEADERS)
    data = response.json()

    for job in data.get("jobs", []):
        if job["conclusion"] == "failure":
            return job
    return None


def get_job_logs(repo: str, job_id: int) -> str:
    """Returns the raw log text for a job."""
    url = f"https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs"
    response = requests.get(url, headers=HEADERS)
    return response.text


def extract_error_lines(log_text: str) -> list[str]:
    """Pulls lines that look like errors out of a raw log."""
    lines = log_text.splitlines()
    error_keywords = ["error", "Error", "ERROR", "failed", "Failed", "FAILED", "Traceback", "exception"]
    return [line for line in lines if any(kw in line for kw in error_keywords)]