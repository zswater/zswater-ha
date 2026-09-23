"""Static check: no module may reference a constant it neither defines nor imports.

This exists because of a real failure. ``CONF_AUTH_TOKEN`` was used twice in
``config_flow.py`` but dropped from its import list during an unrelated cleanup.
Python only notices at the moment the line runs, so the 户号-selection step
rendered fine and then raised ``NameError`` on submit — which Home Assistant
surfaces as a bare "Unknown error occurred" with nothing in the UI to point at
the cause. A purely static check catches it at test time instead.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

PACKAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "zswater"
)

#: Module-level names a module may legitimately use without defining them.
ALLOWED = {"__name__", "__file__", "__doc__"}


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name the module binds: imports, assignments, defs, args, loop vars."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            bound.update(node.names)
    return bound


def _loaded_constants(tree: ast.Module) -> set[str]:
    """SCREAMING_CASE names the module reads — i.e. constants, not locals."""
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id.isupper()
    }


def test_no_module_uses_an_undefined_constant() -> None:
    problems: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        known = _bound_names(tree) | set(dir(builtins)) | ALLOWED
        missing = sorted(_loaded_constants(tree) - known)
        if missing:
            problems.append(f"{path.relative_to(PACKAGE_DIR)}: {missing}")

    assert not problems, "undefined constant(s) referenced:\n" + "\n".join(problems)
