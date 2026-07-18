#!/usr/bin/env python3
"""Validate the golden corpus against contract.json — stdlib only.

This is the self-check that keeps the published artifacts internally
consistent, and a runnable reference for the schema checks a companion's
own test suite should perform (see BUILDING-COMPANION.md). It mirrors the
validators in the reference implementation's WireGoldenConformanceTest:

- every typed node in goldens/widgets.golden and goldens/hypertext.golden
  validates against node_schema (type known, required keys present, no key
  outside the schema) and every embedded action against action_schema;
- every goldens/frames.golden line names a kind_schema-registered kind sent
  in the client direction, with payload keys satisfying the kind's
  required/optional sets.

Exit 0 = clean; exit 1 prints every problem found.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

contract = json.loads((ROOT / "contract.json").read_text(encoding="utf-8"))
NODE_TYPES = set(contract["node_types"])
NODE_SCHEMA = contract["node_schema"]
KIND_SCHEMA = contract["kind_schema"]
ACTION_HOOK_KEYS = set(contract["action_hook_keys"])
ACTION_SCHEMA = contract["action_schema"]
COMMON_NODE_KEYS = set(NODE_SCHEMA["*"]["optional"])

problems: list[str] = []


def golden_lines(rel: str):
    """Non-blank lines of a golden file with their 'NN ' index stripped."""
    for line in (ROOT / rel).read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield line.split(" ", 1)[1]


def check_action(obj: dict, path: str):
    """An embedded action against the discriminated action_schema."""
    has_action, has_builtin = "action" in obj, "builtin" in obj
    if has_action == has_builtin:
        problems.append(f"{path}: action needs exactly one of `action`/`builtin`")
        return
    if has_action:
        entry = ACTION_SCHEMA["remote"]
    else:
        entry = ACTION_SCHEMA.get(obj["builtin"])
        if entry is None:
            problems.append(f"{path}: unknown builtin `{obj['builtin']}`")
            return
    required, optional = set(entry["required"]), set(entry["optional"])
    for req in required:
        if req not in obj:
            problems.append(f"{path}: action missing required `{req}`")
    for key in obj:
        if key not in required and key not in optional:
            problems.append(f"{path}: unknown action field `{key}`")


def check_node(value, path: str):
    """Recursively validate a widget tree: node types, key schema, actions."""
    if isinstance(value, list):
        for i, child in enumerate(value):
            check_node(child, f"{path}[{i}]")
        return
    if not isinstance(value, dict):
        return  # scalars carry no schema
    if "t" in value:
        t = value["t"]
        if t not in NODE_TYPES:
            problems.append(f"{path}: unknown node type `{t}`")
            return
        row = NODE_SCHEMA[t]
        required, optional = set(row["required"]), set(row["optional"])
        for req in required:
            if req not in value:
                problems.append(f"{path}: {t} missing required `{req}`")
        for key in value:
            if key != "t" and key not in required and key not in optional \
                    and key not in COMMON_NODE_KEYS:
                problems.append(f"{path}: unknown key `{key}` on {t}")
    for key, child in value.items():
        if key in ACTION_HOOK_KEYS and isinstance(child, dict):
            check_action(child, f"{path}.{key}")
        else:
            check_node(child, f"{path}.{key}")


def check_payload(kind: str, payload: dict, path: str):
    """A frame's payload keys against the kind schema."""
    entry = KIND_SCHEMA.get(kind)
    if entry is None:
        problems.append(f"{path}: unknown frame kind `{kind}`")
        return
    if entry.get("payload") == "node":
        check_node(payload, path)
        return
    required, optional = set(entry["required"]), set(entry["optional"])
    for req in required:
        if req not in payload:
            problems.append(f"{path}: {kind} missing required `{req}`")
    for key in payload:
        if key not in required and key not in optional:
            problems.append(f"{path}: unknown payload key `{key}` on {kind}")


def main() -> int:
    for field in ("contract_format", "protocol_version", "spec_version",
                  "error_codes"):
        if field not in contract:
            problems.append(f"contract.json: missing `{field}`")

    frames = 0
    for n, line in enumerate(golden_lines("goldens/frames.golden"), 1):
        frame = json.loads(line)
        entry = KIND_SCHEMA.get(frame["kind"])
        if entry and entry["direction"] not in ("client", "both"):
            problems.append(f"frames:{n}: `{frame['kind']}` is not client-emitted")
        check_payload(frame["kind"], frame["payload"], f"frames:{n}")
        frames += 1

    widgets = 0
    for n, line in enumerate(golden_lines("goldens/widgets.golden"), 1):
        obj = json.loads(line)
        if "action" in obj or "builtin" in obj:  # the bare-action lines
            check_action(obj, f"widgets:{n}")
        else:
            check_node(obj, f"widgets:{n}")
        widgets += 1

    hyper = 0
    for n, line in enumerate(golden_lines("goldens/hypertext.golden"), 1):
        arr = json.loads(line)
        check_node(arr, f"hypertext:{n}")
        hyper += len(arr)

    # Sanity: the corpus actually parsed (mirrors the Kotlin thresholds).
    if widgets <= 30:
        problems.append(f"widgets.golden: only {widgets} lines — corpus truncated?")
    if hyper <= 8:
        problems.append(f"hypertext.golden: only {hyper} nodes — corpus truncated?")
    if frames == 0:
        problems.append("frames.golden: empty")

    if problems:
        print("\n".join(problems))
        print(f"\nFAIL: {len(problems)} problem(s)")
        return 1
    print(f"OK: {frames} frames, {widgets} widget lines, {hyper} hypertext nodes "
          f"validate against contract.json "
          f"(spec {contract['spec_version']}, format {contract['contract_format']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
