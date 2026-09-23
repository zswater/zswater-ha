"""Cross-checks between the config/options flows and the translation files.

These guard a bug class that unit tests of a step's *logic* never see, because
nothing in Python raises: Home Assistant formats step titles, descriptions and
menu labels on the frontend, from ``strings.json``. A mismatch surfaces only as
an error dialog or a blank menu row in the UI.

Specifically covered:

* a step description using ``{placeholder}`` that the step never passes, which
  the frontend reports as ``MISSING_VALUE`` and renders as an empty error box;
* a menu option whose id is not the id of an ``async_step_<id>`` method —
  ``data_entry_flow`` dispatches the choice itself, so an unknown id raises and
  the user gets an error dialog with no text;
* a menu option with no ``menu_options`` label, which renders as a blank row;
* a ``step_id`` the flow shows but ``strings.json`` does not describe;
* error keys and abort reasons the flow returns but the translations lack.

Everything is read from the source, so no Home Assistant instance is needed for
the assertions themselves.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components"
PACKAGE = "zswater"

if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

SOURCE = COMPONENT_DIR / PACKAGE / "config_flow.py"
STRINGS = COMPONENT_DIR / PACKAGE / "strings.json"
TRANSLATIONS = COMPONENT_DIR / PACKAGE / "translations"

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

#: Flow class name → the ``strings.json`` section its steps are described in.
FLOW_CLASSES = {
    "ZSWaterConfigFlow": "config",
    "ZSWaterOptionsFlow": "options",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def const() -> Any:
    return importlib.import_module(f"{PACKAGE}.const")


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def strings() -> dict[str, Any]:
    return _load(STRINGS)


def _reset_value(node: ast.expr, const: Any) -> Any:
    """Resolve ``STEP_USER`` / ``"password_login"`` / ``list(LOGIN_MENU_OPTIONS)``."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return getattr(const, node.id, None)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "list" and node.args:
            return _reset_value(node.args[0], const)
    if isinstance(node, ast.List | ast.Tuple):
        return [_reset_value(element, const) for element in node.elts]
    return None


def _flow_calls(tree: ast.Module, const: Any) -> dict[str, dict[str, Any]]:
    """Collect the flow steps per class from the source.

    Returns ``{class name: {step id: {"placeholders": set, "menu": list|None}}}``.
    """
    wanted = {"async_show_form", "async_show_menu"}
    found: dict[str, dict[str, Any]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name not in FLOW_CLASSES:
            continue
        steps: dict[str, Any] = {}
        for method in node.body:
            if not isinstance(method, ast.AsyncFunctionDef):
                continue
            for call in ast.walk(method):
                if not isinstance(call, ast.Call):
                    continue
                name = getattr(call.func, "attr", None)
                if name not in wanted:
                    continue
                keywords = {kw.arg: kw.value for kw in call.keywords}
                step_id = _reset_value(keywords["step_id"], const)
                placeholders: set[str] = set()
                holder = keywords.get("description_placeholders")
                if isinstance(holder, ast.Dict):
                    placeholders = {
                        key.value
                        for key in holder.keys
                        if isinstance(key, ast.Constant)
                    }
                menu: list[str] | None = None
                unresolved_menu = False
                if name == "async_show_menu":
                    raw = _reset_value(keywords["menu_options"], const)
                    if isinstance(raw, list | tuple) and raw:
                        menu = [str(option) for option in raw]
                    else:
                        # Recorded rather than skipped: a menu the checker cannot
                        # read would silently escape every menu assertion below.
                        unresolved_menu = True
                entry = steps.setdefault(
                    step_id,
                    {
                        "placeholders": set(),
                        "menu": None,
                        "unresolved_menu": False,
                        "method": method.name,
                    },
                )
                entry["placeholders"] |= placeholders
                if menu is not None:
                    entry["menu"] = menu
                entry["unresolved_menu"] |= unresolved_menu
        found[node.name] = steps
    return found


def _described_steps(section: dict[str, Any]) -> dict[str, Any]:
    return section.get("step", {})


@pytest.fixture(scope="module")
def flows(tree: ast.Module, const: Any) -> dict[str, dict[str, Any]]:
    return _flow_calls(tree, const)


# --------------------------------------------------------------- structure


def test_every_flow_class_is_covered() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    for class_name in FLOW_CLASSES:
        assert f"class {class_name}" in source, f"{class_name} moved or was renamed"


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_described_steps_exist_in_the_flow(
    class_name: str, section: str, flows: dict[str, Any], strings: dict[str, Any]
) -> None:
    """A step described in strings.json must be reachable."""
    for step_id in _described_steps(strings[section]):
        assert hasattr(
            getattr(importlib.import_module(f"{PACKAGE}.config_flow"), class_name),
            f"async_step_{step_id}",
        ), f"{section}.step.{step_id} has no async_step_{step_id}"


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_shown_steps_are_described(
    class_name: str, section: str, flows: dict[str, Any], strings: dict[str, Any]
) -> None:
    """A step the flow renders must have translations, or the form comes out blank."""
    described = _described_steps(strings[section])
    for step_id in flows[class_name]:
        assert step_id in described, (
            f"{class_name} shows step {step_id!r} but {section}.step.{step_id} "
            f"is missing from strings.json"
        )


# ------------------------------------------------------------ placeholders


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_translated_placeholders_are_passed_by_the_step(
    class_name: str,
    section: str,
    flows: dict[str, Any],
    strings: dict[str, Any],
) -> None:
    """Every ``{placeholder}`` in a step must be supplied when the step renders.

    This is the check that would have caught ``{portal_url}`` in the network
    step, which the frontend rejected with MISSING_VALUE.
    """
    problems: list[str] = []

    for step_id, description in _described_steps(strings[section]).items():
        needed: set[str] = set()
        for field in ("title", "description"):
            value = description.get(field)
            if isinstance(value, str):
                needed |= set(PLACEHOLDER_RE.findall(value))
        for option_label in (description.get("menu_options") or {}).values():
            needed |= set(PLACEHOLDER_RE.findall(option_label))
        if not needed:
            continue

        provided = flows.get(class_name, {}).get(step_id, {}).get("placeholders", set())
        missing = sorted(needed - provided)
        if missing:
            problems.append(
                f"{section}.step.{step_id} uses {{{', '.join(missing)}}} but the "
                f"step passes only {sorted(provided) or 'nothing'}"
            )

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_steps_do_not_pass_unused_placeholders(
    class_name: str, section: str, flows: dict[str, Any], strings: dict[str, Any]
) -> None:
    """Passing a placeholder no translation mentions is dead weight."""
    problems: list[str] = []

    for step_id, entry in flows.get(class_name, {}).items():
        description = _described_steps(strings[section]).get(step_id, {})
        used: set[str] = set()
        for field in ("title", "description"):
            value = description.get(field)
            if isinstance(value, str):
                used |= set(PLACEHOLDER_RE.findall(value))
        for option_label in (description.get("menu_options") or {}).values():
            used |= set(PLACEHOLDER_RE.findall(option_label))

        unused = sorted(entry["placeholders"] - used)
        if unused:
            problems.append(
                f"{section}.step.{step_id} passes {unused} but no translation uses them"
            )

    assert not problems, "\n".join(problems)


# -------------------------------------------------------------- menu steps


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_menu_options_are_readable_by_this_checker(
    class_name: str, section: str, flows: dict[str, Any]
) -> None:
    """``menu_options`` must be a literal list or a tuple constant.

    Anything more dynamic (a comprehension, a function call) cannot be checked,
    and an unchecked menu is exactly how the blank-row bug shipped.
    """
    unreadable = [
        step_id
        for step_id, entry in flows.get(class_name, {}).items()
        if entry["unresolved_menu"]
    ]
    assert not unreadable, (
        f"{class_name} passes menu_options for {unreadable} in a form this checker "
        f"cannot resolve; use a literal list or a constant tuple of step ids"
    )


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_menu_options_dispatch_to_a_real_step(
    class_name: str, section: str, flows: dict[str, Any]
) -> None:
    """Menu option ids must be step ids: ``data_entry_flow`` calls the step itself."""
    module = importlib.import_module(f"{PACKAGE}.config_flow")
    flow_class = getattr(module, class_name)

    for step_id, entry in flows.get(class_name, {}).items():
        for option in entry["menu"] or []:
            assert hasattr(flow_class, f"async_step_{option}"), (
                f"{class_name}.async_step_{step_id} offers menu option {option!r} "
                f"but there is no async_step_{option} — Home Assistant dispatches "
                f"the choice itself and would raise an unknown step"
            )


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_menu_options_are_labelled(
    class_name: str, section: str, flows: dict[str, Any], strings: dict[str, Any]
) -> None:
    """A menu option without a ``menu_options`` label renders as a blank row."""
    problems: list[str] = []

    for step_id, entry in flows.get(class_name, {}).items():
        options = entry["menu"]
        if not options:
            continue
        labels = _described_steps(strings[section]).get(step_id, {}).get(
            "menu_options"
        )
        if not labels:
            problems.append(
                f"{section}.step.{step_id} has no menu_options, so all "
                f"{len(options)} options render blank"
            )
            continue
        missing = [option for option in options if option not in labels]
        if missing:
            problems.append(
                f"{section}.step.{step_id} has no label for {missing}"
            )

    assert not problems, "\n".join(problems)


# ------------------------------------------------------- errors and aborts


def _methods(tree: ast.Module, class_name: str) -> list[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [
                child
                for child in node.body
                if isinstance(child, ast.AsyncFunctionDef | ast.FunctionDef)
            ]
    raise AssertionError(f"{class_name} not found")


def _keyword_strings(
    methods: list[ast.AST], func_attr: str, keyword: str, const: Any
) -> set[str]:
    """Resolve ``<func_attr>(<keyword>=<expr>)`` to the string values it yields."""
    values: set[str] = set()
    for method in methods:
        for call in ast.walk(method):
            if not isinstance(call, ast.Call):
                continue
            if getattr(call.func, "attr", None) != func_attr:
                continue
            for kw in call.keywords:
                if kw.arg != keyword:
                    continue
                resolved = _reset_value(kw.value, const)
                if isinstance(resolved, str):
                    values.add(resolved)
    return values


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_error_keys_are_translated(
    class_name: str,
    section: str,
    tree: ast.Module,
    const: Any,
    strings: dict[str, Any],
) -> None:
    """``errors["base"] = ERROR_X`` needs ``<section>.error.X``.

    Scoped to this class's own methods: the two flows share constant values, so
    a repo-wide text search would ask one flow to translate the other's keys.
    """
    used: set[str] = set()
    literals: set[str] = set()

    for method in _methods(tree, class_name):
        for node in ast.walk(method):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "errors"
            ):
                continue
            if isinstance(node.value, ast.Name):
                value = getattr(const, node.value.id, None)
                if isinstance(value, str):
                    used.add(value)
            elif isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                literals.add(node.value.value)

    assert not literals, (
        f"{class_name} sets error keys from bare strings {sorted(literals)}; "
        f"use the ERROR_* constants so this check can see them"
    )
    translated = set(strings[section].get("error", {}))
    assert used <= translated, (
        f"{section}.error is missing translations for {sorted(used - translated)}"
    )


@pytest.mark.parametrize("class_name,section", sorted(FLOW_CLASSES.items()))
def test_abort_reasons_are_translated(
    class_name: str,
    section: str,
    tree: ast.Module,
    const: Any,
    strings: dict[str, Any],
) -> None:
    """Every ``async_abort(reason=...)`` needs ``<section>.abort.<reason>``."""
    used = _keyword_strings(_methods(tree, class_name), "async_abort", "reason", const)
    translated = set(strings[section].get("abort", {}))
    assert used <= translated, (
        f"{section}.abort is missing translations for {sorted(used - translated)}"
    )


# ------------------------------------------------------------ translations


def test_translations_mirror_strings_json() -> None:
    """The shipped translations must describe the same tree as strings.json."""
    def paths(node: Any, prefix: str = "") -> set[str]:
        out: set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                out.add(f"{prefix}{key}")
                out |= paths(value, f"{prefix}{key}.")
        return out

    base = paths(_load(STRINGS))
    for path in sorted(TRANSLATIONS.glob("*.json")):
        missing = base - paths(_load(path))
        assert not missing, f"{path.name} is missing {sorted(missing)[:5]}"


def test_english_translation_is_complete() -> None:
    """en.json has to exist, because GitHub and HACS render it by default."""
    assert (TRANSLATIONS / "en.json").is_file()
