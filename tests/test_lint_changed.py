"""Exercise event ranges and filename handling with real temporary Git history."""

import json
import subprocess
import sys

import pytest

from scripts import lint_changed


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def commit(repo, files):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, "add", "--all")
    git(repo, "commit", "-qm", "test change")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-qb", "main")
    git(tmp_path, "config", "user.name", "Lint Test")
    git(tmp_path, "config", "user.email", "lint@example.invalid")
    initial = commit(tmp_path, {"old.py": "value = 1\n", "remove.py": "gone = True\n"})
    return tmp_path, initial


def push(before, after, **extra):
    return {"before": before, "after": after, **extra}


def test_push_includes_all_57_files_across_multiple_commits(history):
    repo, initial = history
    commit(repo, {f"first_{number}.py": "x = 1\n" for number in range(28)})
    head = commit(repo, {f"second_{number}.py": "x = 2\n" for number in range(29)})
    paths = lint_changed.changed_python_files(repo, "push", push(initial, head))
    assert len(paths) == 57
    assert "first_0.py" in paths and "second_28.py" in paths


def test_deleted_files_are_excluded_and_renames_use_destination(history):
    repo, initial = history
    git(repo, "mv", "old.py", "renamed file.py")
    git(repo, "rm", "remove.py")
    head = commit(repo, {"notes.txt": "not Python\n"})
    assert lint_changed.changed_python_files(repo, "push", push(initial, head)) == [
        "renamed file.py",
    ]


def test_pull_request_uses_common_ancestor_not_latest_base_tree(history):
    repo, initial = history
    git(repo, "checkout", "-qb", "feature")
    head = commit(repo, {"feature.py": "feature = 1\n"})
    git(repo, "checkout", "-q", "main")
    base = commit(repo, {"base_only.py": "base = 2\n"})
    git(repo, "checkout", "-q", "feature")
    event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    assert lint_changed.changed_python_files(repo, "pull_request", event) == ["feature.py"]


def test_first_repository_push_lints_all_python_files(history):
    repo, head = history
    git(repo, "update-ref", "refs/remotes/origin/main", head)
    event = push(
        "0" * 40, head, ref="refs/heads/main", repository={"default_branch": "main"},
    )
    assert lint_changed.changed_python_files(repo, "push", event) == ["old.py", "remove.py"]


def test_new_feature_branch_uses_default_branch(history):
    repo, initial = history
    git(repo, "update-ref", "refs/remotes/origin/main", initial)
    head = commit(repo, {"feature.py": "feature = 1\n"})
    event = push(
        "0" * 40, head, ref="refs/heads/feature", repository={"default_branch": "main"},
    )
    assert lint_changed.changed_python_files(repo, "push", event) == ["feature.py"]


def test_new_branch_without_changes_does_not_lint_existing_debt(history):
    repo, head = history
    git(repo, "update-ref", "refs/remotes/origin/main", head)
    event = push(
        "0" * 40, head, ref="refs/heads/feature", repository={"default_branch": "main"},
    )
    assert lint_changed.changed_python_files(repo, "push", event) == []


def test_new_repository_without_remote_ref_uses_empty_tree(history):
    repo, head = history
    assert lint_changed.changed_python_files(repo, "push", push("0" * 40, head)) == [
        "old.py", "remove.py",
    ]


def test_branch_deletion_has_no_files_to_lint(history):
    repo, initial = history
    assert lint_changed.changed_python_files(repo, "push", push(initial, "0" * 40)) == []


def test_paths_preserve_spaces_newlines_options_and_shell_metacharacters(history):
    repo, initial = history
    names = ["space name.py", "line\nbreak.py", "-option.py", "$(touch unwanted).py"]
    head = commit(repo, dict.fromkeys(names, "x = 1\n"))
    assert set(lint_changed.changed_python_files(repo, "push", push(initial, head))) == set(names)


def test_main_passes_paths_as_arguments_to_the_current_interpreters_ruff(tmp_path, monkeypatch):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"after": "a" * 40, "before": "b" * 40}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    names = ["space name.py", "-option.py", "$(touch unwanted).py"]
    monkeypatch.setattr(lint_changed, "changed_python_files", lambda *_args: names)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 7)

    monkeypatch.setattr(lint_changed.subprocess, "run", run)
    assert lint_changed.main() == 7
    assert calls[0][0] == [sys.executable, "-m", "ruff", "check", "--", *names]
    assert "shell" not in calls[0][1]


def test_event_cannot_supply_git_options_as_commit_references(history):
    repo, head = history
    with pytest.raises(ValueError, match="full commit SHA"):
        lint_changed.changed_python_files(repo, "push", push("--output=unexpected", head))


def test_force_push_fetches_unreachable_previous_commit(history, tmp_path):
    source, before = history
    git(source, "checkout", "--orphan", "replacement")
    git(source, "rm", "-rf", ".")
    head = commit(source, {"replacement.py": "replacement = True\n"})
    git(source, "branch", "-D", "main")
    checkout = tmp_path / "checkout"
    git(source, "clone", "--quiet", "--single-branch", "--depth=1", source.as_uri(), str(checkout))
    missing = subprocess.run(
        ["git", "cat-file", "-e", f"{before}^{{commit}}"],
        cwd=checkout, capture_output=True, check=False,
    )
    assert missing.returncode != 0
    assert lint_changed.changed_python_files(checkout, "push", push(before, head)) == [
        "replacement.py",
    ]
