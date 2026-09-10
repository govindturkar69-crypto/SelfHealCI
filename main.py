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

load_dotenv()

app = FastAPI(title="SelfHealCI")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET"))

GITHUB_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:8080/auth/github/callback"


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