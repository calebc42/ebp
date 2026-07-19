#!/usr/bin/env python3
"""Validate the golden corpus against contract.json — stdlib only.

This is the self-check that keeps the published artifacts internally
consistent, and a runnable reference for the schema checks a companion's
own test suite should perform (see BUILDING-COMPANION.md). It mirrors the
validators in the reference implementation's WireGoldenConformanceTest:

- every typed node in goldens/widgets.golden and goldens/hypertext.golden
  validates against node_schema (type known, required keys present, no key
  outside the schema) and every embedded action against action_schema;
- every goldens/frames.golden line is a JSON-RPC 2.0 message (SPEC-2 §2)
  naming a methods-registered method sent in the client direction, whose
  id-ness matches the method's request/notification class and whose params
  keys satisfy the method's required/optional sets.

Exit 0 = clean; exit 1 prints every problem found.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

contract = json.loads((ROOT / "contract.json").read_text(encoding="utf-8"))
NODE_TYPES = set(contract["node_types"])
NODE_SCHEMA = contract["node_schema"]
METHODS = contract["methods"]
ERROR_CODES = contract["error_codes"]
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


def check_params(method: str, params: dict, path: str):
    """A message's params keys against the method table."""
    entry = METHODS.get(method)
    if entry is None:
        problems.append(f"{path}: unknown method `{method}`")
        return
    if entry.get("params") == "node":
        check_node(params, path)
        return
    row = entry["params"]
    required, optional = set(row["required"]), set(row["optional"])
    for req in required:
        if req not in params:
            problems.append(f"{path}: {method} missing required `{req}`")
    for key in params:
        if key not in required and key not in optional:
            problems.append(f"{path}: unknown params key `{key}` on {method}")


def check_frame(msg: dict, path: str):
    """One JSON-RPC message: envelope invariants + method-table conformance."""
    if msg.get("jsonrpc") != "2.0":
        problems.append(f"{path}: missing jsonrpc \"2.0\"")
        return
    method = msg.get("method")
    if not isinstance(method, str):
        problems.append(f"{path}: missing method")
        return
    entry = METHODS.get(method)
    if entry is None:
        problems.append(f"{path}: unknown method `{method}`")
        return
    if entry["direction"] not in ("client", "both"):
        problems.append(f"{path}: `{method}` is not client-emitted")
    # A request carries an id; a notification never does (SPEC-2 §2.1).
    is_request = entry["type"] == "request"
    if is_request != ("id" in msg):
        problems.append(f"{path}: `{method}` id presence contradicts its "
                        f"`{entry['type']}` class")
    check_params(method, msg.get("params", {}), path)


def main() -> int:
    for field in ("contract_format", "protocol_version", "spec_version",
                  "methods", "error_codes"):
        if field not in contract:
            problems.append(f"contract.json: missing `{field}`")

    # Every request method declares a result schema; notifications don't.
    for name, entry in METHODS.items():
        if (entry["type"] == "request") != ("result" in entry):
            problems.append(f"contract.json: `{name}` result presence "
                            f"contradicts its `{entry['type']}` class")

    frames = 0
    for n, line in enumerate(golden_lines("goldens/frames.golden"), 1):
        check_frame(json.loads(line), f"frames:{n}")
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
