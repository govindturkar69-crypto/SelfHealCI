import os
import psycopg2
from google import genai
from google.genai import types
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
DATABASE_URL = os.getenv("DATABASE_URL")


def get_embedding(text: str) -> list[float]:
    """Converts text into a 768-dim vector embedding using Gemini's embedding model."""
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=768)
    )
    return list(result.embeddings[0].values)


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def store_incident(category: str, error_message: str, fix_text: str, success: bool, repo: str = None):
    """Embeds the error and stores the incident (fix attempt + outcome) in the database."""
    embedding = get_embedding(error_message)

    conn = get_connection()
    register_vector(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO incidents (category, error_message, fix_text, embedding, success, repo)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (category, error_message, fix_text, embedding, success, repo)
    )
    conn.commit()
    cur.close()
    conn.close()
    print(f"Stored incident: {category} (success={success})")


def find_similar_incidents(error_message: str, limit: int = 3) -> list[dict]:
    """Finds the most similar past incidents to the given error, ranked by success first."""
    embedding = get_embedding(error_message)

    conn = get_connection()
    register_vector(conn)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT category, error_message, fix_text, success,
               1 - (embedding <=> %s::vector) AS similarity
        FROM incidents
        ORDER BY success DESC, embedding <=> %s::vector
        LIMIT %s
        """,
        (embedding, embedding, limit)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"category": r[0], "error_message": r[1], "fix_text": r[2], "success": r[3], "similarity": r[4]}
        for r in rows
    ]

def get_unconfirmed_incidents(limit: int = 10) -> list[dict]:
    """Returns recent incidents that haven't been confirmed as fixed or not yet."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, category, error_message, fix_text, repo, created_at
        FROM incidents
        WHERE success IS NULL
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"id": r[0], "category": r[1], "error_message": r[2], "fix_text": r[3], "repo": r[4], "created_at": r[5]}
        for r in rows
    ]


def update_incident_outcome(incident_id: int, success: bool):
    """Marks a stored incident as confirmed fixed (True) or not fixed (False)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE incidents SET success = %s WHERE id = %s",
        (success, incident_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    print(f"Updated incident {incident_id}: success={success}")


if __name__ == "__main__":
    store_incident(
        category="dependency_error",
        error_message="Artifact not found for name: coverage-html",
        fix_text="Ensure the upstream job uploads an artifact named coverage-html and add it to the needs: array.",
        success=True,
        repo="fastapi/fastapi"
    )

    results = find_similar_incidents("Unable to download artifact(s): Artifact not found for name: build-output")
    print("\n--- Similar past incidents ---")
    for r in results:
        print(f"[{r['category']}] similarity={r['similarity']:.3f} success={r['success']}")
        print(f"  Error: {r['error_message']}")
        print(f"  Fix: {r['fix_text']}\n")