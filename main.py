from fastapi import FastAPI
from memory_store import get_unconfirmed_incidents, get_connection
from orchestrator import run_agent
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="SelfHealCI")


@app.get("/")
def root():
    return {"status": "SelfHealCI is running"}


@app.get("/incidents")
def list_incidents():
    """Returns all stored incidents, most recent first."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, category, error_message, fix_text, success, repo, created_at
        FROM incidents
        ORDER BY created_at DESC
        """
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
def list_unconfirmed():
    return get_unconfirmed_incidents(limit=50)

@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")

@app.post("/run-agent")
def trigger_agent(repo: str):
    """Manually triggers the agent to check a repo for the latest failed run."""
    run_agent(repo)
    return {"status": "completed", "repo": repo}