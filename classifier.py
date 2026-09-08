import re

CATEGORY_PATTERNS = [
    ("dependency_error", [r"Artifact not found", r"ModuleNotFoundError", r"No matching distribution", r"npm ERR!", r"Could not find", r"pip.*not found"]),
    ("test_failure", [r"AssertionError", r"FAILED\s", r"pytest", r"\d+ failed"]),
    ("build_error", [r"CompileError", r"SyntaxError", r"error TS\d+", r"Build failed"]),
    ("lint_error", [r"flake8", r"eslint", r"pylint", r"Lint"]),
    ("timeout_error", [r"timed out", r"Timeout"]),
    ("permission_error", [r"Permission denied", r"403", r"Forbidden", r"EACCES"]),
    ("generic_exit_error", [r"Process completed with exit code \d+", r"exit code \d+", r"##\[error\]"]),
]

TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*")

def clean_line(line: str) -> str:
    return TIMESTAMP_PREFIX.sub("", line).strip()

def classify_error(error_lines: list[str]) -> dict:
    """Takes raw error-matching log lines and returns a structured signature."""
    cleaned_lines = [clean_line(line) for line in error_lines]
    joined = "\n".join(cleaned_lines)

    category = "unknown"
    matched_pattern = None

    # First pass: try specific categories only (skip generic_exit_error)
    for cat_name, patterns in CATEGORY_PATTERNS:
        if cat_name == "generic_exit_error":
            continue
        for pattern in patterns:
            if re.search(pattern, joined, re.IGNORECASE):
                category = cat_name
                matched_pattern = pattern
                break
        if category != "unknown":
            break

    # Fallback: if nothing specific matched, check for a generic exit-code error
    if category == "unknown":
        for pattern in dict(CATEGORY_PATTERNS)["generic_exit_error"]:
            if re.search(pattern, joined, re.IGNORECASE):
                category = "generic_exit_error"
                matched_pattern = pattern
                break

    primary_message = cleaned_lines[0] if cleaned_lines else "No error message found"
    if matched_pattern:
        for line in cleaned_lines:
            if re.search(matched_pattern, line, re.IGNORECASE):
                primary_message = line
                break

    return {
        "category": category,
        "primary_message": primary_message,
        "all_error_lines": cleaned_lines,
        "has_specific_diagnosis": category not in ("unknown", "generic_exit_error"),
    }