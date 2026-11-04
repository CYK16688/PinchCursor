"""Pin the dependency direction and the window-engine boundary.

No other test would fail if `core/` imported Qt again, if `utils/` imported
`core/`, or if the window reintroduced an engine alias. These checks turn that
silent regression into a red build.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

QT = "PySide6"


def _sources(package):
    return sorted((ROOT / package).rglob("*.py"))


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def test_core_imports_no_qt():
    offenders = []
    for path in _sources("core"):
        for module, lineno in _imports(_tree(path)):
            if module == QT or module.startswith(QT + "."):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno} -> {module}")
    assert not offenders, "core/ must stay Qt-free:\n" + "\n".join(offenders)


def test_utils_imports_no_core():
    offenders = []
    for path in _sources("utils"):
        for module, lineno in _imports(_tree(path)):
            if module == "core" or module.startswith("core."):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno} -> {module}")
    assert not offenders, "utils/ must stay a leaf:\n" + "\n".join(offenders)


def test_window_binds_no_engine_attribute_aliases():
    tree = _tree(ROOT / "gui" / "main_window.py")
    aliases = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Attribute):
            continue
        if isinstance(value.value, ast.Name) and value.value.id == "ControlEngine":
            aliases.append(f"{target.id} (line {node.lineno})")
    assert not aliases, "the window must call the engine explicitly: " + ", ".join(aliases)
