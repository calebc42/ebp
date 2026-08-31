#!/usr/bin/env python3
"""Generate the deterministic EBP text-input conformance corpus.

The 32 rotating families deliberately separate receiver validity from strict
public-author validity.  Seed 20260828 and the row count are part of the test
contract; the generated JSONL belongs in a temporary/build directory.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SEED = 20260828
COUNT = 10_000
FAMILIES = 32
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def normalize(text: str, single_line: bool, filter_name: str | None,
              maximum: int | None) -> str:
    """Apply SPEC 17.4's single-line, filter, maximum order."""
    if single_line:
        text = text.replace("\n", "")
    if filter_name == "digits":
        text = "".join(c for c in text if "0" <= c <= "9")
    elif filter_name == "alnum":
        text = "".join(c for c in text if
                       "0" <= c <= "9" or
                       "A" <= c <= "Z" or
                       "a" <= c <= "z")
    if maximum is not None:
        text = text[:maximum]
    return text


def action(name: str, capture: list[str] | None = None, **members):
    out = {"action": name}
    if capture is not None:
        out["capture_fields"] = capture
    out.update(members)
    return out


def make_case(index: int, rng: random.Random) -> dict:
    family = index % FAMILIES
    node_id = f"field-{index}"
    node: dict = {"t": "text_input", "id": node_id}
    receiver_valid = True
    author_valid = True

    astral = rng.choice(["😀", "🧪", "𝄞", "𐐷"])
    ascii_text = "".join(rng.choice("Az09xy12") for _ in range(3 + index % 5))

    if family == 0:
        node.update(value=f"1{astral}2", selection=[1, 2], max_length=3)
    elif family == 1:
        node["selection"] = "0:0"
        receiver_valid = author_valid = False
    elif family == 2:
        node["selection"] = [0]
        receiver_valid = author_valid = False
    elif family == 3:
        node.update(value="ab", selection=[0,
                    1.5 if index % 64 == 3 else MAX_SAFE_INTEGER + 1])
        receiver_valid = author_valid = False
    elif family == 4:
        node["selection"] = [-1, 0]
        receiver_valid = author_valid = False
    elif family == 5:
        node.update(value="ab", selection=[2, 1])
        receiver_valid = author_valid = False
    elif family == 6:
        node.update(value=astral, selection=[0, 2])
        receiver_valid = author_valid = False
    elif family == 7:
        node.update(value=f"a{astral}b", max_length=3)
    elif family == 8:
        node["max_length"] = 0 if index % 64 == 8 else MAX_SAFE_INTEGER + 1
        receiver_valid = author_valid = False
    elif family == 9:
        node["max_length"] = 2.5
        receiver_valid = author_valid = False
    elif family == 10:
        node.update(value=f"a{astral}b", max_length=2)
        receiver_valid = author_valid = False
    elif family == 11:
        node.update(value="".join(rng.choice("0123456789") for _ in range(6)),
                    filter="digits")
    elif family == 12:
        node.update(value="12a", filter="digits")
        receiver_valid = author_valid = False
    elif family == 13:
        node.update(value=ascii_text, filter="alnum")
    elif family == 14:
        node.update(value="café", filter="alnum")
        receiver_valid = author_valid = False
    elif family == 15:
        node.update(value=f"é + {astral}", filter="future-filter")
        author_valid = False
    elif family == 16:
        node.update(value=ascii_text, variant="future-variant")
        author_valid = False
    elif family == 17:
        node.update(value=f"1{astral}2", mask="##-#")
    elif family == 18:
        node["mask"] = "literal"
        receiver_valid = author_valid = False
    elif family == 19:
        node.update(password=True, mask="####")
        receiver_valid = author_valid = False
    elif family == 20:
        node.update(syntax="elisp", mask="####")
        receiver_valid = author_valid = False
    elif family == 21:
        node["content_padding"] = -1
        receiver_valid = author_valid = False
    elif family == 22:
        node["hide_keyboard_on_submit"] = True
        receiver_valid = author_valid = False
    elif family == 23:
        node.update(min_lines=3, max_lines=2)
        receiver_valid = author_valid = False
    elif family == 24:
        node.update(single_line=True, max_lines=2)
        receiver_valid = author_valid = False
    elif family == 25:
        node.update(single_line=True, value="a\nb")
        receiver_valid = author_valid = False
    elif family == 26:
        node.update(password=True,
                    on_submit=action("secret.submit", [node_id]))
    elif family == 27:
        node.update(password=True, on_submit=action("secret.submit"))
        receiver_valid = author_valid = False
    elif family == 28:
        node.update(password=True, value="secret")
        receiver_valid = author_valid = False
    elif family == 29:
        node.update(password=True, on_change=action("secret.change"))
        receiver_valid = author_valid = False
    elif family == 30:
        node.update(password=True, clear_on_submit=True,
                    on_submit=action("secret.submit", [node_id]))
        receiver_valid = author_valid = False
    else:
        node.update(clear_on_submit=True,
                    on_submit={"builtin": "dialog.submit"})
        receiver_valid = author_valid = False

    edit_text = rng.choice([
        f"a1\n{astral}2Z", f"9{astral}\nB3", "café\n12", ascii_text,
    ])
    edit_single = bool((index // FAMILIES) % 2)
    edit_filter = [None, "digits", "alnum", "future-filter"][index % 4]
    edit_maximum = [None, 1, 2, 5][(index // 4) % 4]
    normalized = normalize(edit_text, edit_single, edit_filter, edit_maximum)

    return {
        "index": index,
        "family": family,
        "receiver_valid": receiver_valid,
        "author_valid": author_valid,
        "node": node,
        "canonical": json.dumps(node, ensure_ascii=False, separators=(",", ":"),
                                sort_keys=True),
        "edit": {
            "text": edit_text,
            "single_line": edit_single,
            "filter": edit_filter,
            "max_length": edit_maximum,
            "normalized": normalized,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=COUNT)
    parser.add_argument("--seed", type=int, default=SEED)
    options = parser.parse_args()
    if options.count != COUNT or options.seed != SEED:
        raise SystemExit(f"the permanent corpus is fixed at seed {SEED}, count {COUNT}")
    rng = random.Random(options.seed)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    with options.output.open("w", encoding="utf-8") as stream:
        for index in range(options.count):
            json.dump(make_case(index, rng), stream, ensure_ascii=False,
                      separators=(",", ":"), sort_keys=True, allow_nan=False)
            stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
