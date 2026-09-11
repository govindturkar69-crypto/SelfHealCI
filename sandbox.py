import docker
import tempfile
import subprocess
import os

client = docker.from_env()


def clone_repo(repo_url: str, ref: str = None) -> str:
    """Clones a repo into a temp directory. If ref is given, clones that specific branch/tag directly."""
    temp_dir = tempfile.mkdtemp(prefix="selfhealci_")
    print(f"Cloning into: {temp_dir}")

    if ref:
        subprocess.run(["git", "clone", "--depth", "1", "--branch", ref, repo_url, temp_dir], check=True)
    else:
        subprocess.run(["git", "clone", "--depth", "50", repo_url, temp_dir], check=True)

    return temp_dir

    subprocess.run(["git", "clone", "--depth", "50", repo_url, temp_dir], check=True)

    if commit_sha:
        subprocess.run(["git", "-C", temp_dir, "checkout", commit_sha], check=True)

    return temp_dir


def run_tests_in_container(repo_path: str, image: str = "python:3.11-slim") -> dict:
    """Mounts the repo into a container and runs its test suite, detecting how to install deps."""
    print(f"Running tests in container for: {repo_path}")

    # Detect the right install command based on what's in the repo
    if os.path.exists(os.path.join(repo_path, "requirements-tests.txt")):
        install_cmd = "pip install --quiet -r requirements-tests.txt"
    elif os.path.exists(os.path.join(repo_path, "requirements-dev.txt")):
        install_cmd = "pip install --quiet -r requirements-dev.txt"
    elif os.path.exists(os.path.join(repo_path, "requirements.txt")):
        install_cmd = "pip install --quiet -r requirements.txt pytest"
    else:
        install_cmd = "pip install --quiet -e . pytest"

    command = f"{install_cmd} && pip install --quiet -e . && pip install --quiet 'python-multipart==0.0.9' && pytest tests/ -x -q"

    container = client.containers.run(
        image,
        command=["sh", "-c", command],
        volumes={repo_path: {"bind": "/repo", "mode": "rw"}},
        working_dir="/repo",
        remove=False,
        detach=True,
    )

    result = container.wait()
    logs = container.logs().decode(errors="ignore")
    container.remove()

    return {
        "exit_code": result["StatusCode"],
        "logs": logs,
    }

    command = (
        "pip install --quiet -e .[test] && "
        "pytest tests/ -x -q --timeout=60"
    )

    container = client.containers.run(
        image,
        command=["sh", "-c", command],
        volumes={repo_path: {"bind": "/repo", "mode": "rw"}},
        working_dir="/repo",
        remove=False,
        detach=True,
    )

    result = container.wait()
    logs = container.logs().decode(errors="ignore")
    container.remove()

    return {
        "exit_code": result["StatusCode"],
        "logs": logs,
    }


if __name__ == "__main__":
    path = clone_repo("https://github.com/fastapi/fastapi.git", ref="0.115.0")
    print("Cloned to:", path)

    result = run_tests_in_container(path)
    print("\n--- Test run result ---")
    print("Exit code:", result["exit_code"])
    print("Last 1500 chars of logs:\n")
    print(result["logs"][-1500:])

import shutil

def apply_patch_and_test(repo_url: str, file_path: str, new_content: str, ref: str = "main", image: str = "python:3.11-slim") -> dict:
    """Clones a repo, overwrites one file with new content, and runs its test suite in a container."""
    local_path = clone_repo(repo_url, ref=ref)

    full_file_path = os.path.join(local_path, file_path)
    with open(full_file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Detect how to install/run: proper package vs loose scripts
    has_setup = os.path.exists(os.path.join(local_path, "setup.py")) or os.path.exists(os.path.join(local_path, "pyproject.toml"))

    if has_setup:
        install_cmd = "pip install --quiet -e . pytest"
    else:
        install_cmd = "pip install --quiet pytest"

    command = f"{install_cmd} && pytest -x -q"

    result = run_tests_in_container_raw(local_path, command, image)

    shutil.rmtree(local_path, ignore_errors=True)
    return result


def run_tests_in_container_raw(repo_path: str, command: str, image: str = "python:3.11-slim") -> dict:
    """Runs an exact shell command inside a container mounted to repo_path."""
    container = client.containers.run(
        image,
        command=["sh", "-c", command],
        volumes={repo_path: {"bind": "/repo", "mode": "rw"}},
        working_dir="/repo",
        remove=False,
        detach=True,
    )
    result = container.wait()
    logs = container.logs().decode(errors="ignore")
    container.remove()
    return {"exit_code": result["StatusCode"], "logs": logs}