#!/usr/bin/env python3
"""Validate the published EBP artifacts against each other — stdlib only.

This is the repo's self-check and a runnable reference for the conformance
checks an implementation's own test suite should perform (SPEC 24.5–24.6):

- contract.json structural self-consistency (format 6);
- SPEC.md §8 error table and §11 method registry cross-checked against
  contract.json, so spec and contract cannot drift silently;
- goldens/widgets.golden and goldens/hypertext.golden: every node validates
  against node_schema (+ universal attributes) and every embedded action
  against the discriminated action schema, including offline-policy rules;
- goldens/frames.golden: every line is a JSON-RPC 2.0 message naming a
  registered method whose id-ness matches its request/notification class and
  whose params keys satisfy the method's required/optional sets;
- goldens/wire/: byte-exact framed fixtures decoded by a reference
  Content-Length parser, fed in varied chunk sizes including one octet at a
  time (SPEC 24.5); positive fixtures must decode to the manifest's expected
  messages, negative fixtures must fail with the expected error class
  (SPEC 24.6 items 1–3);
- the SPEC 9.3 HMAC-SHA256 known-answer vector recomputed from scratch.

Exit 0 = clean; exit 1 prints every problem found.
"""

import base64
import hashlib
import hmac
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GOLD = ROOT / "goldens"
WIRE = GOLD / "wire"

contract = json.loads((ROOT / "contract.json").read_text(encoding="utf-8"))
NODE_TYPES = set(contract["node_types"])
NODE_SCHEMA = contract["node_schema"]
UNIVERSAL = set(contract["universal_node_attributes"])
METHODS = contract["methods"]
ERROR_CODES = contract["error_codes"]
ACTIONS = contract["actions"]
HOOK_KEYS = set(ACTIONS["hook_keys"])
ACTION_SCHEMA = ACTIONS["schema"]
OFFLINE_POLICIES = set(ACTIONS["offline_policies"])

MAX_HEADER = contract["limits"]["fixed"]["max_header_bytes"]
MAX_BODY = contract["limits"]["fixed"]["max_body_bytes"]
MAX_DEPTH = contract["limits"]["fixed"]["max_json_depth"]

problems: list[str] = []


def problem(msg: str):
    problems.append(msg)


# --------------------------------------------------------------- contract ---
def check_contract():
    for field in ("contract_format", "protocol_version", "spec_version",
                  "core_node_set", "node_types", "node_schema", "methods",
                  "error_codes", "limits", "capabilities"):
        if field not in contract:
            problem(f"contract.json: missing `{field}`")
    if contract.get("contract_format") != 6:
        problem("contract.json: contract_format must be 6")
    for t in contract.get("core_node_set", []):
        if t not in NODE_TYPES:
            problem(f"contract.json: core node `{t}` not in node_types")
    for t in NODE_TYPES:
        if t not in NODE_SCHEMA:
            problem(f"contract.json: node `{t}` has no schema row")
    for t in NODE_SCHEMA:
        if t not in NODE_TYPES:
            problem(f"contract.json: schema row `{t}` not in node_types")
    for name, entry in METHODS.items():
        is_request = entry["class"] == "request"
        if is_request != ("result" in entry):
            problem(f"contract.json: `{name}` result presence contradicts "
                    f"its `{entry['class']}` class")
        if entry["sender"] not in ("emacs", "companion", "either"):
            problem(f"contract.json: `{name}` has invalid sender")
        for code in entry.get("errors", []):
            if str(code) not in ERROR_CODES:
                problem(f"contract.json: `{name}` names unknown error {code}")


# ------------------------------------------------------- spec cross-check ---
SENDER_MAP = {"emacs": "emacs", "companion": "companion", "either": "either"}


def check_spec_sync():
    spec_path = ROOT / "SPEC.md"
    if not spec_path.exists():
        problem("SPEC.md: missing")
        return
    spec = spec_path.read_text(encoding="utf-8")

    # §8 error table rows: | `-32700` | `parse-error` | ... |
    spec_errors = dict(re.findall(r"^\| `(-?\d+)` \| `([a-z0-9-]+)` \|",
                                  spec, re.M))
    for code, kind in spec_errors.items():
        row = ERROR_CODES.get(code)
        if row is None:
            problem(f"spec-sync: SPEC error {code} missing from contract")
        elif row["kind"] != kind:
            problem(f"spec-sync: error {code} kind `{row['kind']}` != "
                    f"SPEC `{kind}`")
    for code in ERROR_CODES:
        if code not in spec_errors:
            problem(f"spec-sync: contract error {code} missing from SPEC §8")

    # §11 registry rows: | `session.hello` | Emacs | request | ... |
    reg = re.findall(
        r"^\| `([a-z_.]+)` \| (Emacs|Companion|Either) \| "
        r"(request|notification) \|", spec, re.M)
    spec_methods = {m: (s.lower(), c) for m, s, c in reg}
    for m, (sender, cls) in spec_methods.items():
        entry = METHODS.get(m)
        if entry is None:
            problem(f"spec-sync: SPEC method `{m}` missing from contract")
            continue
        if entry["sender"] != SENDER_MAP[sender]:
            problem(f"spec-sync: `{m}` sender `{entry['sender']}` != "
                    f"SPEC `{sender}`")
        if entry["class"] != cls:
            problem(f"spec-sync: `{m}` class `{entry['class']}` != "
                    f"SPEC `{cls}`")
    for m in METHODS:
        if m not in spec_methods:
            problem(f"spec-sync: contract method `{m}` missing from SPEC §11")


# ------------------------------------------------------- nodes and actions --
def check_action(obj: dict, path: str):
    has_action, has_builtin = "action" in obj, "builtin" in obj
    if has_action == has_builtin:
        problem(f"{path}: action needs exactly one of `action`/`builtin`")
        return
    if has_action:
        entry = ACTION_SCHEMA["remote"]
        # SPEC 14.1: an action name contains at least one dot.
        if not isinstance(obj["action"], str) or "." not in obj["action"]:
            problem(f"{path}: action name must contain a dot")
        policy = obj.get("when_offline", ACTIONS["offline_default"])
        if policy not in OFFLINE_POLICIES:
            problem(f"{path}: unknown offline policy `{policy}`")
        if policy in ("queue", "wake"):
            if "ttl_s" not in obj:
                problem(f"{path}: `{policy}` requires ttl_s")
        else:
            for banned in ("ttl_s", "dedupe"):
                if banned in obj:
                    problem(f"{path}: `{banned}` is invalid for drop")
    else:
        entry = ACTION_SCHEMA.get(obj["builtin"])
        if entry is None:
            problem(f"{path}: unknown builtin `{obj['builtin']}`")
            return
    required, optional = set(entry["required"]), set(entry["optional"])
    for req in required - {"builtin"}:
        if req not in obj:
            problem(f"{path}: action missing required `{req}`")
    for key in obj:
        if key not in required and key not in optional and key != "builtin":
            problem(f"{path}: unknown action field `{key}`")


MAX_NODE_DEPTH = contract["limits"]["fixed"]["max_node_depth"]


# ------------------------------------------------------ SPEC 4.3 equality ---
_ABSENT = object()


def spec_equal(a, b) -> bool:
    """SPEC 4.3 equality: by VALUE, not by spelling or representation.

    `1`, `1.0`, and `1e0` are one value; `-0` equals `0`; object member order
    is irrelevant. The type tag gates first, because a host primitive
    generally does not: Python's `==` equates `True` and `1` (bool subclasses
    int), Emacs's `equal` separates `1` and `1.0`, and neither is §4.3.
    """
    if a is _ABSENT or b is _ABSENT:
        return a is _ABSENT and b is _ABSENT
    if a is None or b is None:          # JSON null
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        return (isinstance(a, (int, float)) and isinstance(b, (int, float))
                and float(a) == float(b))
    if isinstance(a, dict) or isinstance(b, dict):
        return (isinstance(a, dict) and isinstance(b, dict)
                and a.keys() == b.keys()
                and all(spec_equal(a[k], b[k]) for k in a))
    if isinstance(a, list) or isinstance(b, list):
        return (isinstance(a, list) and isinstance(b, list)
                and len(a) == len(b)
                and all(spec_equal(x, y) for x, y in zip(a, b)))
    return False  # not a SPEC 4.2 value kind


def check_enum_options(node, path: str):
    """SPEC 17.4: option values are distinct, and a selection names one.

    Both tests are SPEC 4.3 comparisons, so `1` and `1.0` are the SAME option
    (a duplicate) and a `value` of `2.0` selects the option authored `2`.
    """
    options = node.get("options")
    if not isinstance(options, list):
        problem(f"{path}.options: must be an array")
        return
    seen = []
    for i, opt in enumerate(options):
        if not isinstance(opt, dict) or "label" not in opt or "value" not in opt:
            problem(f"{path}.options[{i}]: needs label and value")
            continue
        if any(spec_equal(s, opt["value"]) for s in seen):
            problem(f"{path}.options[{i}]: duplicate option value (SPEC 4.3)")
        seen.append(opt["value"])
    if "value" not in node or node.get("allow_add"):
        return
    chosen = node["value"]
    members = chosen if node.get("multi_select") else [chosen]
    if not isinstance(members, list):
        problem(f"{path}.value: multi-select value must be an array")
        return
    for i, v in enumerate(members):
        if not any(spec_equal(s, v) for s in seen):
            problem(f"{path}.value[{i}]: selected value not in options")


def check_slider_values(node, path: str):
    """SPEC 17.4: a discrete slider's value equals one LISTED number under
    SPEC 4.3 — so `2.0` is the listed `2`, and `-0.0` is the listed `0`."""
    values = node.get("values")
    if values is None:
        return
    if not isinstance(values, list) or len(values) < 2:
        problem(f"{path}.values: at least two discrete values")
        return
    if "min" in node or "max" in node:
        problem(f"{path}: discrete slider must omit min and max")
    if "value" in node and not any(spec_equal(v, node["value"]) for v in values):
        problem(f"{path}.value: must equal a listed discrete value (SPEC 4.3)")


def check_node(value, path: str, depth: int = 0):
    if isinstance(value, list):
        for i, child in enumerate(value):
            check_node(child, f"{path}[{i}]", depth)
        return
    if not isinstance(value, dict):
        return  # scalars carry no schema
    if "t" in value:
        # SPEC 4.5/16.1 (amendment #108): node nesting depth. The 4.5
        # JSON-container limit is a receiver bound, not a budget a sender may
        # spend — host encoders cap well below it.
        depth += 1
        if depth > MAX_NODE_DEPTH:
            problem(f"{path}: node nesting exceeds max_node_depth "
                    f"({MAX_NODE_DEPTH}) — reason node-depth")
            return
        t = value["t"]
        if t not in NODE_TYPES:
            # An unknown type costs us THIS node's schema check and nothing
            # more: its children are still nodes and still spend the same
            # document depth. Returning here truncated the walk, so a single
            # unrecognized `t` hid every over-depth node, malformed action,
            # and unknown key underneath it — the validator reported one
            # problem and implicitly called the rest of the subtree clean.
            problem(f"{path}: unknown node type `{t}`")
        else:
            row = NODE_SCHEMA[t]
            required, optional = set(row["required"]), set(row["optional"])
            for req in required:
                if req not in value:
                    problem(f"{path}: {t} missing required `{req}`")
            for key in value:
                if key != "t" and key not in required and key not in optional \
                        and key not in UNIVERSAL:
                    problem(f"{path}: unknown key `{key}` on {t}")
            if t == "text_input" and value.get("single_line") \
                    and "\n" in value.get("value", ""):
                problem(f"{path}: single_line value contains U+000A (SPEC 17.4)")
            if t == "enum_list":
                check_enum_options(value, path)
            if t == "slider":
                check_slider_values(value, path)
    for key, child in value.items():
        if (key in HOOK_KEYS or key == "on_trigger") \
                and isinstance(child, dict):
            check_action(child, f"{path}.{key}")
        else:
            check_node(child, f"{path}.{key}", depth)


# ------------------------------------------------------------- frames -------
def check_params(method: str, params, path: str):
    entry = METHODS[method]
    if not isinstance(params, dict):
        problem(f"{path}: params must be an object (SPEC 7.1)")
        return
    row = entry["params"]
    required, optional = set(row["required"]), set(row["optional"])
    for req in required:
        if req not in params:
            problem(f"{path}: {method} missing required `{req}`")
    for key in params:
        if key not in required and key not in optional:
            problem(f"{path}: unknown params key `{key}` on {method}")
    # Structured members ride the node/action validators.
    if method in ("surface.update", "dialog.show"):
        spec = params.get("spec")
        if isinstance(spec, dict) and "views" in spec:
            for name, view in spec["views"].items():
                check_node(view, f"{path}.spec.views.{name}")
        else:
            check_node(spec, f"{path}.spec")
        if "stale_spec" in params:
            check_node(params["stale_spec"], f"{path}.stale_spec")


def check_frame(msg, path: str):
    if not isinstance(msg, dict):
        problem(f"{path}: not a JSON object")
        return
    if msg.get("jsonrpc") != "2.0":
        problem(f"{path}: missing jsonrpc \"2.0\"")
        return
    if "method" not in msg:
        # a response frame: exactly one of result/error, with id
        if "id" not in msg or (("result" in msg) == ("error" in msg)):
            problem(f"{path}: response needs id and exactly one of "
                    f"result/error")
        return
    method = msg["method"]
    entry = METHODS.get(method)
    if entry is None:
        problem(f"{path}: unknown method `{method}`")
        return
    is_request = entry["class"] == "request"
    if is_request != ("id" in msg):
        problem(f"{path}: `{method}` id presence contradicts its "
                f"`{entry['class']}` class")
    if is_request and not isinstance(msg.get("id"), (str, int)):
        problem(f"{path}: request id must be a string or integer (SPEC 7.2)")
    check_params(method, msg.get("params", {}), path)


def golden_lines(rel: str):
    for line in (GOLD / rel).read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield line.split(" ", 1)[1]


# ------------------------------------------------- wire framing reference ---
class FrameError(Exception):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


def reject_duplicates(pairs):
    seen = set()
    for k, _ in pairs:
        if k in seen:
            raise FrameError("invalid-request")
        seen.add(k)
    return dict(pairs)


MAX_SAFE_INT = 9007199254740991


def reject_bad_numbers(value):
    """SPEC 4.2 (amendment #99): reject a number this data model cannot carry.

    An integral literal outside the safe range, or a literal that overflowed
    to an infinity, is a Parse Error on the same terms as the 4.5 depth
    limit — decoding cannot represent it, so the failure precedes dispatch.
    A literal that underflowed to zero decodes AS zero and is accepted.
    """
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if value > MAX_SAFE_INT or value < -MAX_SAFE_INT:
            raise FrameError("parse-error")
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise FrameError("parse-error")
    elif isinstance(value, dict):
        for v in value.values():
            reject_bad_numbers(v)
    elif isinstance(value, list):
        for v in value:
            reject_bad_numbers(v)


def exceeds_depth(text):
    """SPEC 4.5: True when TEXT nests JSON containers past MAX_DEPTH.

    A single linear scan (string literals and their escapes skipped) so the
    check runs in bounded stack — before the recursive json.loads a body
    nested past the limit would otherwise drive to a stack overflow.
    """
    depth = 0
    in_string = False
    escaped = False
    for c in text:
        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c in "{[":
            depth += 1
            if depth > MAX_DEPTH:
                return True
        elif c in "}]":
            depth -= 1
    return False


def decode_stream(chunks):
    """Reference SPEC §6 decoder over an iterable of byte chunks.

    Returns the list of decoded messages; raises FrameError on the first
    fatal condition ('close', 'incomplete-frame', 'parse-error',
    'invalid-request' — the latter two are recoverable per 6.2 but are
    reported as the fixture's outcome).
    """
    buf = b""
    messages = []
    ended = False
    chunks = iter(chunks)
    while True:
        # fill until a complete header section or EOF
        while b"\r\n\r\n" not in buf and not ended:
            # SPEC 6.2: the header section cap binds an UNTERMINATED header
            # too — otherwise a peer that never sends CRLFCRLF makes the
            # reference decoder buffer without bound, and the published
            # algorithm would not enforce the MUST it documents. Both wire
            # twins close at exactly this threshold.
            if len(buf) > MAX_HEADER:
                raise FrameError("close")
            try:
                buf += next(chunks)
            except StopIteration:
                ended = True
        if b"\r\n\r\n" not in buf and len(buf) > MAX_HEADER:
            raise FrameError("close")
        if b"\r\n\r\n" not in buf:
            if buf:
                raise FrameError("incomplete-frame")
            return messages
        head, rest = buf.split(b"\r\n\r\n", 1)
        if len(head) + 4 > MAX_HEADER:
            raise FrameError("close")
        lengths = []
        for line in head.split(b"\r\n"):
            if not line:
                raise FrameError("close")
            if b":" not in line:
                raise FrameError("close")
            name, _, value = line.partition(b":")
            try:
                name = name.decode("ascii")
                value = value.decode("ascii").strip(" \t")
            except UnicodeDecodeError:
                raise FrameError("close")
            if name.lower() == "content-length":
                if not re.fullmatch(r"0|[1-9][0-9]*", value):
                    raise FrameError("close")
                lengths.append(int(value))
        if len(lengths) != 1:
            raise FrameError("close")
        length = lengths[0]
        if length > MAX_BODY:
            raise FrameError("close")
        while len(rest) < length and not ended:
            try:
                rest += next(chunks)
            except StopIteration:
                ended = True
        if len(rest) < length:
            raise FrameError("incomplete-frame")
        body, buf = rest[:length], rest[length:]
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            raise FrameError("parse-error")
        # SPEC 4.5: refuse an over-deep body before the recursive parser runs.
        if exceeds_depth(text):
            raise FrameError("parse-error")
        # SPEC 4.1: "an unpaired surrogate escape is invalid and MUST be
        # rejected rather than preserved or replaced" — json.loads preserves
        # it, so the reference validator has to check for itself.
        if any("\ud800" <= ch <= "\udfff" for ch in text):
            raise FrameError("parse-error")
        try:
            msg = json.loads(text, object_pairs_hook=reject_duplicates)
        except FrameError:
            raise
        except json.JSONDecodeError:
            raise FrameError("parse-error")
        if not isinstance(msg, dict):
            raise FrameError("invalid-request")
        # SPEC 4.2 (amendment #99): numbers this data model cannot carry.
        reject_bad_numbers(msg)
        messages.append(msg)


def chunkings(data: bytes):
    yield "whole", [data]
    yield "1-octet", [data[i:i + 1] for i in range(len(data))]
    yield "7-octet", [data[i:i + 7] for i in range(0, len(data), 7)]


def check_wire():
    manifest = json.loads((WIRE / "manifest.json").read_text(encoding="utf-8"))
    n = 0
    for fx in manifest["fixtures"]:
        n += 1
        # SPEC 24.5: a Golden identifies the role or roles for which its
        # expectation is normative; absent, it applies to both. §6.2 scopes
        # several receiver duties by role, so a negative expectation can be
        # unproducible by a conforming endpoint in the other role — but the
        # COMPANION is never excused (§24.1 grants it no delegation), so a
        # roles list that omits it would be describing a different protocol.
        roles = fx.get("roles")
        if roles is not None:
            if fx["kind"] != "negative":
                problem(f"wire {fx['file']}: `roles` scopes a negative "
                        f"expectation; this fixture is {fx['kind']}")
            if not isinstance(roles, list) or not roles or \
                    any(r not in ("companion", "emacs") for r in roles):
                problem(f"wire {fx['file']}: `roles` must be a non-empty "
                        f"list drawn from companion/emacs")
            elif "companion" not in roles:
                problem(f"wire {fx['file']}: the Companion role is never "
                        f"excused from a receiver duty (SPEC 24.1)")
        # This reference implements the strict receiver for BOTH roles, so it
        # is held to every expectation regardless of scoping.
        data = (WIRE / fx["file"]).read_bytes()
        for label, chunks in chunkings(data):
            try:
                got = decode_stream(chunks)
                err = None
            except FrameError as e:
                got, err = None, e.kind
            if fx["kind"] == "positive":
                if err is not None:
                    problem(f"wire {fx['file']} [{label}]: unexpected "
                            f"error `{err}`")
                elif got != fx["expect_messages"]:
                    problem(f"wire {fx['file']} [{label}]: decoded messages "
                            f"differ from manifest expectation")
                else:
                    for i, msg in enumerate(got):
                        check_frame(msg, f"wire {fx['file']}[{i}]")
            else:
                want = fx["expect_error"]
                if err != want:
                    problem(f"wire {fx['file']} [{label}]: expected "
                            f"`{want}`, got `{err or 'success'}`")
    # 24.6 item 1: the UTF-8 fixture's length really differs from char count
    utf8 = next(f for f in manifest["fixtures"]
                if f["file"] == "03-utf8-length.bin")
    body = json.dumps(utf8["expect_messages"][0], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    if len(body.encode("utf-8")) == len(body):
        problem("wire 03-utf8-length.bin: body byte count equals character "
                "count — fixture no longer witnesses SPEC 24.6 item 1")
    return n


# --------------------------------------------------------------- HMAC KAT ---
def check_hmac_kat():
    token = base64.urlsafe_b64decode("AAECAwQFBgcICQoLDA0ODw==")
    pid = "101112131415161718191a1b1c1d1e1f"
    cn = "202122232425262728292a2b2c2d2e2f"
    sn = "303132333435363738393a3b3c3d3e3f"
    client = hmac.new(token, f"EBP/2 client:{pid}:{cn}:{sn}".encode(),
                      hashlib.sha256).hexdigest()
    server = hmac.new(token, f"EBP/2 companion:{pid}:{sn}:{cn}".encode(),
                      hashlib.sha256).hexdigest()
    if client != ("03e270fd0af4566336283444b641a722"
                  "b5828c190ebdbe3dc50c5be2c9c9fb43"):
        problem(f"hmac-kat: client_proof mismatch: {client}")
    if server != ("e9333d48cfc2780d708db4a9782705c5"
                  "e1c988c7eedc2d1734051f2fb9be58ec"):
        problem(f"hmac-kat: server_proof mismatch: {server}")


# -------------------------------------------------------- equality self-test
def check_equality_semantics():
    """SPEC 4.3, stated as vectors (SPEC 24.6 item 15).

    Every host primitive within reach gets at least one of these wrong, so a
    reference that delegated to `==` would pass its own goldens while an
    endpoint built the same way silently erased a user's draft.
    """
    cases = [
        (True, 1, 1.0), (True, 1, 1e0), (True, -0.0, 0), (True, 0.0, -0),
        (True, {"a": 1, "b": 2}, {"b": 2, "a": 1}),
        (True, [1, 2.0], [1.0, 2]),
        # Python's `==` says True for the next two (bool subclasses int).
        (False, True, 1), (False, False, 0),
        # Emacs's `equal` says nil for `1` vs `1.0`; both must be one value.
        (False, 1, "1"), (False, "1", 1),
        (False, None, _ABSENT), (False, _ABSENT, None),
        (False, [1, 2], [2, 1]), (False, {"a": 1}, {"a": 1, "b": 2}),
    ]
    for want, a, b in cases:
        if spec_equal(a, b) is not want:
            problem(f"equality-selftest: spec_equal({a!r}, {b!r}) "
                    f"should be {want}")


# ------------------------------------------------------------ walk self-test
def check_walk_completeness():
    """The node walk must survive an unrecognized `t`.

    A validator that stops descending at the first thing it does not
    recognize reports one problem and leaves the reader believing the rest
    of the subtree was checked. Exercised here rather than in a golden,
    because a golden is by construction a document that validates.
    """
    deep = {"t": "text", "text": "x"}
    for _ in range(MAX_NODE_DEPTH + 2):
        deep = {"t": "column", "children": [deep]}
    doc = {"t": "no_such_type", "children": [deep]}

    saved, found = problems[:], None
    del problems[:]
    try:
        check_node(doc, "walk-selftest")
        found = problems[:]
    finally:
        del problems[:]
        problems.extend(saved)

    if not any("unknown node type" in p for p in found):
        problem("walk-selftest: an unknown node type went unreported")
    if not any("node-depth" in p for p in found):
        problem("walk-selftest: the walk stopped at the unknown node type — "
                "the over-depth subtree beneath it went unreported")


# ------------------------------------------------------------------- main ---
def main() -> int:
    check_contract()
    check_spec_sync()
    check_hmac_kat()
    check_walk_completeness()
    check_equality_semantics()

    frames = 0
    for n, line in enumerate(golden_lines("frames.golden")):
        check_frame(json.loads(line), f"frames:{n:02d}")
        frames += 1

    widgets = 0
    for n, line in enumerate(golden_lines("widgets.golden")):
        obj = json.loads(line)
        if "action" in obj or "builtin" in obj:
            check_action(obj, f"widgets:{n:02d}")
        else:
            check_node(obj, f"widgets:{n:02d}")
        widgets += 1

    hyper = 0
    for n, line in enumerate(golden_lines("hypertext.golden")):
        arr = json.loads(line)
        check_node(arr, f"hypertext:{n:02d}")
        hyper += len(arr)

    wire = check_wire()

    # Coverage floors: the corpus really covers the vocabulary.
    covered = {json.loads(line).get("t")
               for line in golden_lines("widgets.golden")}
    for t in NODE_TYPES:
        if t not in covered:
            problem(f"coverage: node type `{t}` has no widgets.golden line")
    seen_methods = {json.loads(line).get("method")
                    for line in golden_lines("frames.golden")}
    for m in METHODS:
        if m not in seen_methods:
            problem(f"coverage: method `{m}` has no frames.golden line")
    if wire < 10:
        problem(f"wire: only {wire} fixtures — adversarial set truncated?")

    if problems:
        print("\n".join(problems))
        print(f"\nFAIL: {len(problems)} problem(s)")
        return 1
    print(f"OK: {frames} frames, {widgets} widget lines, {hyper} hypertext "
          f"nodes, {wire} wire fixtures x3 chunkings validate "
          f"(spec {contract['spec_version']}, "
          f"format {contract['contract_format']}); "
          f"SPEC §8/§11 in sync; 9.3 KAT reproduced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
