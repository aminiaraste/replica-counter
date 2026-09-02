import json
import sys
from pathlib import Path


BLOCK_MESSAGE = """
[TDD Guard] BLOCKED: You attempted to write a Lambda implementation file
without a passing test first.

You MUST follow this TDD workflow before writing to this file:

1. Identify the behavior required.
2. Write a test file at lambda/tests/test_<module_name>.py that covers
   the new behavior.
3. Run: python -m pytest (from lambda/) and confirm RED
   (test fails because the implementation is missing - NOT due to
   syntax/import/collection errors).
4. Only after RED is confirmed, write the implementation.
5. Run tests again and confirm GREEN.

The implementation write is BLOCKED until a test file exists at:
  lambda/tests/test_{module_name}.py

Create the test file first, then retry writing the implementation.
"""


def get_file_path(event):
    """Extract target file path from Kiro tool input."""
    tool_input = event.get("tool_input", {})
    return (
        tool_input.get("path")
        or tool_input.get("file_path")
        or tool_input.get("filePath")
        or ""
    )


def is_lambda_implementation(file_path):
    """
    Return True only for Python implementation files directly under lambda/.

    Examples:
        lambda/my_handler.py       -> True
        lambda/worker.py           -> True
        lambda/__init__.py         -> False
        lambda/tests/test_foo.py   -> False
        my_cdk/my_stack.py         -> False
    """
    if not file_path:
        return False

    normalized = file_path.replace("\\", "/")
    path = Path(normalized)

    if path.suffix.lower() != ".py":
        return False

    if path.name.startswith("__"):
        return False

    parts = normalized.split("/")

    try:
        lambda_index = parts.index("lambda")
    except ValueError:
        return False

    # File must be directly inside lambda/ (exactly one level deep)
    return len(parts) == lambda_index + 2


def test_file_exists(file_path):
    """
    Return True if a corresponding test file already exists.

    Looks for lambda/tests/test_<module_name>.py
    """
    normalized = file_path.replace("\\", "/")
    parts = normalized.split("/")

    try:
        lambda_index = parts.index("lambda")
    except ValueError:
        return False

    module_name = Path(parts[-1]).stem  # e.g. "add_numbers"
    # Reconstruct base path up to and including lambda/
    base = "/".join(parts[: lambda_index + 1])
    test_path = Path(base) / "tests" / f"test_{module_name}.py"

    return test_path.exists()


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    file_path = get_file_path(event)

    if not is_lambda_implementation(file_path):
        # Not a Lambda implementation file — let it through
        sys.exit(0)

    if test_file_exists(file_path):
        # Test file already exists — TDD prerequisite met, allow the write
        sys.exit(0)

    # No test file found — block the write
    module_name = Path(file_path).stem
    message = BLOCK_MESSAGE.replace("{module_name}", module_name)
    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
