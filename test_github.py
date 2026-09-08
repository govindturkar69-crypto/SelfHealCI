import os
import requests
from dotenv import load_dotenv
from classifier import classify_error
from fix_generator import generate_fix

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json"
}

REPO = "fastapi/fastapi"

# Step 1: find a failed run
url = f"https://api.github.com/repos/{REPO}/actions/runs"
response = requests.get(url, headers=HEADERS)
data = response.json()

failed_run = None
for run in data.get("workflow_runs", []):
    if run["conclusion"] == "failure":
        failed_run = run
        break

if not failed_run:
    print("No failed run found in this page of results.")
    exit()

run_id = failed_run["id"]
print(f"Using failed run: {failed_run['name']} (id: {run_id})")

# Step 2: get jobs for that run
jobs_url = f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs"
jobs_response = requests.get(jobs_url, headers=HEADERS)
jobs_data = jobs_response.json()

failed_job = None
for job in jobs_data.get("jobs", []):
    if job["conclusion"] == "failure":
        failed_job = job
        break

if not failed_job:
    print("No failed job found in this run.")
    exit()

job_id = failed_job["id"]
print(f"Using failed job: {failed_job['name']} (id: {job_id})")

# Step 3: fetch the log text for that job
logs_url = f"https://api.github.com/repos/{REPO}/actions/jobs/{job_id}/logs"
logs_response = requests.get(logs_url, headers=HEADERS)

print("\nLog status code:", logs_response.status_code)

log_text = logs_response.text
lines = log_text.splitlines()

# Search for lines that look like errors
error_keywords = ["error", "Error", "ERROR", "failed", "Failed", "FAILED", "Traceback", "exception"]
error_lines = [line for line in lines if any(kw in line for kw in error_keywords)]

print(f"\nTotal lines in log: {len(lines)}")
print(f"Lines matching error keywords: {len(error_lines)}")

signature = classify_error(error_lines)

print("\n--- Structured Error Signature ---")
print("Category:", signature["category"])
print("Primary message:", signature["primary_message"])
print("\n--- Gemini's Suggested Fix ---\n")
fix = generate_fix(signature)
print(fix)