"""Lint the full GitHub event's Python changes, preserving Git path boundaries."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.check_output(["git", *args], cwd=repo, input=data)


def _commit(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{40,64}", value) is None:
        raise ValueError("GitHub event must contain a full commit SHA")
    return value


def changed_python_files(repo: Path, event_name: str, event: dict) -> list[str]:
    """Return surviving Python paths across a push or a pull request's changes."""
    if event_name == "pull_request":
        request = event["pull_request"]
        head = _commit(request["head"]["sha"])
        base = _git(repo, "merge-base", _commit(request["base"]["sha"]), head).strip().decode()
    elif event_name == "push":
        head = _commit(event["after"])
        before = _commit(event["before"])
        if set(head) == {"0"}:
            return []  # Deleting a branch leaves no revision to lint.
        if set(before) != {"0"}:
            available = subprocess.run(
                ["git", "cat-file", "-e", f"{before}^{{commit}}"],
                cwd=repo, capture_output=True, check=False,
            )
            if available.returncode != 0:
                # A force push can make 'before' unreachable from every fetched
                # ref. Fetch that exact object; never narrow to HEAD~1 on error.
                _git(repo, "fetch", "--no-tags", "--depth=1", "origin", before)
            base = before
        else:
            # A new branch has no 'before'. Compare with the default branch's
            # common ancestor, or the empty tree for a repository's first push.
            default = event.get("repository", {}).get("default_branch")
            base = ""
            if default:
                reference = f"refs/remotes/origin/{default}^{{commit}}"
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", "--quiet", "--end-of-options", reference],
                    cwd=repo, capture_output=True, check=False,
                )
                if result.returncode == 0:
                    ancestor = result.stdout.strip().decode()
                    if event.get("ref") != f"refs/heads/{default}":
                        base = _git(repo, "merge-base", ancestor, head).strip().decode()
            if not base:
                base = _git(repo, "hash-object", "-t", "tree", "--stdin", data=b"").strip().decode()
    else:
        raise ValueError(f"Unsupported GitHub event: {event_name}")

    output = _git(
        repo, "diff", "--name-only", "-z", "--find-renames", "--diff-filter=ACMRTUXB",
        base, head, "--", "*.py",
    )
    return [os.fsdecode(path) for path in output.split(b"\0") if path.endswith(b".py")]


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    paths = changed_python_files(repo, os.environ["GITHUB_EVENT_NAME"], event)
    if not paths:
        print("No changed Python files")
        return 0
    print("Linting changed Python files: " + json.dumps(paths, ensure_ascii=True), flush=True)
    # No shell expansion: spaces, newlines, metacharacters and leading '-' stay
    # inside their filename arguments. Use the interpreter's pinned Ruff install.
    return subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--", *paths], cwd=repo, check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
