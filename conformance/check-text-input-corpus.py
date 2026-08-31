#!/usr/bin/env python3
"""Replay the shared deterministic corpus through the Python receiver."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check-text-input-corpus.py CORPUS.jsonl")
    corpus = Path(sys.argv[1])
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "ebp_validate", root / "validate.py")
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    count = 0
    families: set[int] = set()
    with corpus.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            start = len(validator.problems)
            validator.check_node(row["node"], f"corpus:{row['index']}")
            found = validator.problems[start:]
            del validator.problems[start:]
            observed = not found
            if observed != row["receiver_valid"]:
                raise AssertionError(
                    f"row {row['index']} family {row['family']}: "
                    f"receiver_valid={row['receiver_valid']}, problems={found}")
            count += 1
            families.add(row["family"])
    if count != 10_000 or families != set(range(32)):
        raise AssertionError(f"corpus coverage changed: rows={count}, families={families}")
    print("OK: Python replayed 10000 text-input cases (seed 20260828, 32 families)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
