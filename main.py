import os
import requests as http_requests
from memory_store import get_connection
from fastapi import FastAPI
from memory_store import get_unconfirmed_incidents, get_connection
from orchestrator import run_agent
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from fastapi import HTTPException
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

app = FastAPI(title="SelfHealCI")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET"))

GITHUB_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:8080/auth/github/callback"

def scheduled_check():
    """Runs periodically: checks every watched repo for each user who owns it."""
    print("\n[Scheduler] Running scheduled check of all watched repos...")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT watched_repos.repo, watched_repos.user_id, users.github_access_token
        FROM watched_repos
        JOIN users ON users.id = watched_repos.user_id
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    for repo, user_id, token in rows:
        try:
            print(f"[Scheduler] Checking {repo} for user {user_id}...")
            run_agent(repo, token=token, user_id=user_id)
        except Exception as e:
            print(f"[Scheduler] Error checking {repo}: {e}")

    print("[Scheduler] Done.\n")


scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_check, "interval", minutes=30)
scheduler.start()


@app.get("/auth/github/login")
def github_login():
    """Redirects the user to GitHub to authorize SelfHealCI."""
    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=repo"
    )
    return RedirectResponse(github_url)


@app.get("/auth/github/callback")
def github_callback(request: Request, code: str):
    """GitHub redirects here after the user authorizes. Exchange the code for an access token."""
    token_response = http_requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
    )
    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return {"error": "Failed to get access token", "details": token_data}

    # Fetch the user's GitHub profile using their new token
    user_response = http_requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    user_data = user_response.json()

        # Save or update this user in the database
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (github_id, github_username, github_access_token)
        VALUES (%s, %s, %s)
        ON CONFLICT (github_id) DO UPDATE
        SET github_access_token = EXCLUDED.github_access_token,
            github_username = EXCLUDED.github_username
        RETURNING id
        """,
        (user_data["id"], user_data["login"], access_token)
    )
    user_row_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    # Store the internal user id + username in the session (not the raw token)
    request.session["user_id"] = user_row_id
    request.session["github_username"] = user_data["login"]

    return RedirectResponse("/dashboard")


@app.get("/")
def root():
    return {"status": "SelfHealCI is running"}


@app.get("/incidents")
def list_incidents(request: Request):
    """Returns the logged-in user's own incidents, most recent first."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, category, error_message, fix_text, success, repo, created_at
        FROM incidents
        WHERE user_id = %s
        ORDER BY created_at DESC
        """,
        (user_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "id": r[0], "category": r[1], "error_message": r[2],
            "fix_text": r[3], "success": r[4], "repo": r[5],
            "created_at": r[6].isoformat()
        }
        for r in rows
    ]

@app.get("/incidents/unconfirmed")
def list_unconfirmed(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, category, error_message, fix_text, repo, created_at
        FROM incidents
        WHERE success IS NULL AND user_id = %s
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (user_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"id": r[0], "category": r[1], "error_message": r[2], "fix_text": r[3], "repo": r[4], "created_at": r[5].isoformat()}
        for r in rows
    ]

@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")

@app.post("/run-agent")
def trigger_agent(repo: str, request: Request):
    """Triggers the agent to check a repo, using the logged-in user's own GitHub token."""
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT github_access_token FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="User not found. Please log in again.")

    token = row[0]
    result = run_agent(repo, token=token, user_id=user_id)
    return {"repo": repo, **result}

@app.get("/me")
def me(request: Request):
    return {
        "logged_in": "user_id" in request.session,
        "username": request.session.get("github_username")
    }

@app.get("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/dashboard")

@app.post("/incidents/{incident_id}/confirm")
def confirm_incident(incident_id: int, success: bool, request: Request):
    """Marks an incident (owned by the logged-in user) as fixed or not fixed."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE incidents SET success = %s WHERE id = %s AND user_id = %s",
        (success, incident_id, user_id)
    )
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    if updated == 0:
        raise HTTPException(status_code=404, detail="Incident not found or not yours.")

    return {"status": "updated", "incident_id": incident_id, "success": success}


@app.get("/my-repos")
def my_repos(request: Request):
    """Returns the logged-in user's own GitHub repos."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT github_access_token FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="User not found.")

    token = row[0]
    response = http_requests.get(
        "https://api.github.com/user/repos",
        headers={"Authorization": f"Bearer {token}"},
        params={"sort": "updated", "per_page": 50}
    )
    repos = response.json()

    return [{"full_name": r["full_name"], "private": r["private"]} for r in repos]

@app.get("/analytics")
def analytics(request: Request):
    """Returns summary stats for the logged-in user's incidents."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM incidents WHERE user_id = %s", (user_id,))
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM incidents WHERE user_id = %s AND success = TRUE", (user_id,))
    fixed = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM incidents WHERE user_id = %s AND success = FALSE", (user_id,))
    not_fixed = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM incidents WHERE user_id = %s AND success IS NULL", (user_id,))
    pending = cur.fetchone()[0]

    cur.execute(
        """
        SELECT category, COUNT(*) FROM incidents
        WHERE user_id = %s
        GROUP BY category
        ORDER BY COUNT(*) DESC
        """,
        (user_id,)
    )
    by_category = [{"category": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.execute(
        """
        SELECT repo, COUNT(*) FROM incidents
        WHERE user_id = %s
        GROUP BY repo
        ORDER BY COUNT(*) DESC
        """,
        (user_id,)
    )
    by_repo = [{"repo": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.close()
    conn.close()

    success_rate = round((fixed / (fixed + not_fixed) * 100), 1) if (fixed + not_fixed) > 0 else None

    return {
        "total": total,
        "fixed": fixed,
        "not_fixed": not_fixed,
        "pending": pending,
        "success_rate": success_rate,
        "by_category": by_category,
        "by_repo": by_repo,
    }
@app.post("/watched-repos")
def add_watched_repo(repo: str, request: Request):
    """Adds a repo to the logged-in user's auto-check list."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO watched_repos (user_id, repo) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (user_id, repo)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "watching", "repo": repo}


@app.delete("/watched-repos")
def remove_watched_repo(repo: str, request: Request):
    """Removes a repo from the logged-in user's auto-check list."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM watched_repos WHERE user_id = %s AND repo = %s", (user_id, repo))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "unwatched", "repo": repo}


@app.get("/watched-repos")
def list_watched_repos(request: Request):
    """Lists the logged-in user's auto-checked repos."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT repo FROM watched_repos WHERE user_id = %s", (user_id,))
    repos = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return repos

@app.post("/settings/notifications")
def update_notification_settings(request: Request, email: str = None, slack_webhook_url: str = None):
    """Lets the logged-in user set their notification email and/or Slack webhook."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET notification_email = %s, slack_webhook_url = %s WHERE id = %s",
        (email, slack_webhook_url, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "updated"}


@app.get("/settings/notifications")
def get_notification_settings(request: Request):
    """Returns the logged-in user's current notification settings."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="You must connect your GitHub account first.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT notification_email, slack_webhook_url FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    return {"email": row[0], "slack_webhook_url": row[1]}