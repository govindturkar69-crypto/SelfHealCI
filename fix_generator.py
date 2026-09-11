import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
def generate_fix(signature: dict, similar_incidents: list[dict] = None) -> str:
    """Takes a classified error signature (and optional past similar incidents) and asks Gemini to suggest a fix."""

    # Only include memory context if we have a specific diagnosis to match against.
    # Otherwise, irrelevant past incidents can mislead the fix (thin-memory problem).
    memory_context = ""
    if similar_incidents and signature.get("has_specific_diagnosis", True):
        memory_context = "\n\nHere are similar past incidents and what worked (or didn't):\n"
        for i, inc in enumerate(similar_incidents, 1):
            outcome = "WORKED" if inc["success"] else "DID NOT WORK" if inc["success"] is False else "UNCONFIRMED"
            memory_context += f"\n{i}. Error: {inc['error_message']}\n   Fix tried: {inc['fix_text']}\n   Outcome: {outcome}\n"

    if signature.get("has_specific_diagnosis", True):
        instruction = "Explain in 2-3 sentences what likely caused this failure, and suggest a concrete fix. If past incidents show a fix that worked for a similar error, prefer that approach. If one is marked as not working, avoid repeating it."
    else:
        instruction = "This error message is generic (just an exit code, no specific detail). Do NOT guess a specific cause. Instead, explain in 2-3 sentences what steps someone should take to find the real underlying error (e.g. checking the full job log for the first failing command), since the exit code alone isn't enough to diagnose."

    prompt = f"""You are a CI/CD debugging assistant.

A GitHub Actions workflow failed with this error:

Category: {signature['category']}
Error message: {signature['primary_message']}
{memory_context}

{instruction}
Be specific and concise. Do not add disclaimers.
"""
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )
    return response.text

def generate_patch(signature: dict, file_path: str, file_content: str) -> str:
    """Asks Gemini to return a full corrected version of the file, given the error."""
    prompt = f"""You are an expert Python developer fixing a CI failure.

The file `{file_path}` caused this test failure:

Category: {signature['category']}
Error: {signature['primary_message']}

Here is the current content of {file_path}:

```python
{file_content}
```

Return ONLY the complete corrected version of this file. Do not include explanations, markdown code fences, or any text other than the raw Python code itself. The fix should be minimal and targeted at the actual bug - do not rewrite unrelated parts of the file.
"""
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )
    return response.text.strip()