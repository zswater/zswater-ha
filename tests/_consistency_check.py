"""One-off consistency check: config-flow steps/errors/aborts vs strings.json.

Run with ``python tests/_consistency_check.py``. Not part of the pytest suite
because it inspects source text rather than behaviour.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "zswater"

src = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
const = (COMPONENT / "const.py").read_text(encoding="utf-8")
strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

values = dict(re.findall(r'^([A-Z][A-Z0-9_]*)\s*=\s*"([^"]*)"', const, re.M))

problems: list[str] = []


def resolve(token: str) -> str:
    token = token.strip()
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", token):
        return values.get(token, f"<UNRESOLVED:{token}>")
    return token.strip('"')


step_ids = {
    resolve(m.group(1))
    for m in re.finditer(r'step_id=([A-Za-z_][A-Za-z0-9_]*|"[a-z_0-9]+")', src)
}
declared = set(strings["config"]["step"]) | set(strings["options"]["step"])
for step in sorted(step_ids):
    if step not in declared:
        problems.append(f"step_id {step!r} has no strings.json entry")
for step in sorted(declared - step_ids):
    if step not in ("reauth", "reconfigure"):
        problems.append(f"strings.json declares unused step {step!r}")

err_keys = {
    resolve(m.group(1))
    for m in re.finditer(r'errors\["base"\]\s*=\s*([A-Za-z_][A-Za-z0-9_]*|"[a-z_0-9]+")', src)
}
err_keys |= {
    m.group(1)
    for m in re.finditer(r'errors\[\s*CONF_[A-Z_]+\s*\]\s*=\s*"([a-z_0-9]+)"', src)
}
for key in sorted(err_keys):
    if key not in set(strings["config"]["error"]):
        problems.append(f"error key {key!r} has no strings.json entry")

aborts = {
    resolve(m.group(1))
    for m in re.finditer(r'async_abort\(reason=([A-Za-z_][A-Za-z0-9_]*|"[a-z_0-9]+")', src)
}
abort_declared = set(strings["config"]["abort"]) | set(strings["options"]["abort"])
for reason in sorted(aborts):
    if reason not in abort_declared:
        problems.append(f"abort reason {reason!r} has no strings.json entry")

for name in sorted(
    set(re.findall(r"(?:step_id|reason)=([A-Z][A-Z0-9_]*)", src))
    | set(re.findall(r'errors\["base"\]\s*=\s*([A-Z][A-Z0-9_]*)', src))
):
    if name not in values:
        problems.append(f"constant {name} used but not defined in const.py")

print(f"steps checked: {len(step_ids)}")
print(f"error keys checked: {len(err_keys)}")
print(f"abort reasons checked: {len(aborts)}")
if problems:
    print("PROBLEMS:")
    for problem in problems:
        print("  -", problem)
    sys.exit(1)
print("OK: flow steps, error keys and abort reasons all match strings.json")
