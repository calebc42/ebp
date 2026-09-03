#!/usr/bin/env python3
"""Validate the published EBP artifacts against each other — stdlib only.

This is the repo's self-check and a runnable reference for the conformance
checks an implementation's own test suite should perform (SPEC 24.5–24.6):

- contract.json structural self-consistency (format 12);
- SPEC.md §8 error table and §11 method registry cross-checked against
  contract.json, so spec and contract cannot drift silently;
- goldens/widgets.golden and goldens/hypertext.golden: every node validates
  against node_schema (+ universal attributes) and every embedded action
  against the discriminated action schema, including offline-policy rules;
  variant_host alternatives are all walked (including inactive alternatives),
  share one document-global ID namespace, and deferred variant.switch
  references resolve only after the complete document has been scanned;
- goldens/frames.golden: every line is a JSON-RPC 2.0 message naming a
  registered method whose id-ness matches its request/notification class and
  whose params keys satisfy the method's required/optional sets;
- goldens/editor.golden: Section 19 splice known-answers replayed by a
  reference reducer — positions and lengths are Unicode-scalar counts
  (SPEC 19.1), with astral-plane and refused-splice coverage floors so an
  implementation indexing UTF-16 code units or graphemes fails loudly;
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
import math
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
VARIANT_SCHEMA = contract.get("variant_schema", {})
SEMANTICS_SCHEMA = contract.get("semantics_schema", {})
TEXT_INPUT_SCHEMA = contract.get("text_input_schema", {})
RENDERER_PROFILE_SCHEMA = contract.get("renderer_profile_schema", {})
WIDGET_SIZE_VARIANT_SCHEMA = contract.get("widget_size_variant_schema", {})
SWIPE_SCHEMA = contract.get("swipe_schema", {})

MAX_HEADER = contract["limits"]["fixed"]["max_header_bytes"]
MAX_BODY = contract["limits"]["fixed"]["max_body_bytes"]
MAX_DEPTH = contract["limits"]["fixed"]["max_json_depth"]
MAX_NODES = contract["limits"]["fixed"]["max_nodes_per_snapshot"]
MAX_CHILDREN = contract["limits"]["fixed"]["max_children_per_node"]
MAX_VARIANTS = contract["limits"]["fixed"]["max_variants_per_host"]
MAX_SEMANTIC_ACTIONS = \
    contract["limits"]["fixed"]["max_semantic_actions_per_node"]
MIN_VARIANTS = VARIANT_SCHEMA.get("min_items", 2)

# SPEC 14.1 (amendment #168): the object-form confirm face's closed member
# set, and the SPEC 4.4 identifier grammar its `icon` member carries.
CONFIRM_MEMBERS = {"text", "title", "icon", "confirm_label", "dismiss_label"}
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*")
APP_SURFACE_ID_RE = re.compile(r"app:[A-Za-z0-9][A-Za-z0-9._:/-]*")

problems: list[str] = []


def problem(msg: str):
    problems.append(msg)


# --------------------------------------------------------------- contract ---
def check_contract():
    for field in ("contract_format", "protocol_version", "spec_version",
                  "core_node_set", "node_types", "node_schema", "methods",
                  "error_codes", "limits", "capabilities",
                  "variant_schema", "semantics_schema", "text_input_schema",
                  "renderer_profile_schema", "widget_size_variant_schema",
                  "swipe_schema"):
        if field not in contract:
            problem(f"contract.json: missing `{field}`")
    if contract.get("contract_format") != 12:
        problem("contract.json: contract_format must be 12")
    if contract.get("protocol_version") != 3:
        problem("contract.json: protocol_version must be 3")
    expected_profile_required = [
        "node_types", "builtins", "features", "extensions",
    ]
    if RENDERER_PROFILE_SCHEMA.get("required") != expected_profile_required:
        problem("contract.json: renderer profile required members drifted")
    if RENDERER_PROFILE_SCHEMA.get("optional") != ["members", "limits"]:
        problem("contract.json: renderer profile optional members drifted")
    if set(RENDERER_PROFILE_SCHEMA.get("members", {}).get("required", [])) != {
            "universal", "nodes", "semantics", "surface"}:
        problem("contract.json: renderer member support shape drifted")
    if WIDGET_SIZE_VARIANT_SCHEMA.get("required") != [
            "min_width", "min_height", "body"] or \
            WIDGET_SIZE_VARIANT_SCHEMA.get("optional") != []:
        problem("contract.json: WidgetSizeVariant must be closed and require "
                "min_width, min_height, body")
    fixed = contract.get("limits", {}).get("fixed", {})
    expected_widget_limits = {
        "max_widget_nodes": 128,
        "max_widget_lazy_items": 40,
        "max_widget_node_depth": 12,
        "max_widget_size_variants": 8,
        "max_widget_remote_views_bytes": 716800,
        "max_swipe_actions_per_side": 4,
    }
    for name, expected in expected_widget_limits.items():
        if fixed.get(name) != expected:
            problem(f"contract.json: {name} must be {expected}")
    widget_variant = contract.get("surface_spec_variants", {}).get("widget")
    if widget_variant != {
            "required": ["title", "body"],
            "optional": ["empty", "header_action", "size_variants"],
            "node_body": True,
            "multi_view": False,
    }:
        problem("contract.json: widget SurfaceSpec shape drifted")
    if SWIPE_SCHEMA.get("legacy") != {
            "required": ["label", "on_trigger"],
            "optional": ["icon", "color"],
    } or SWIPE_SCHEMA.get("action") != {
            "required": ["label", "on_trigger"],
            "optional": ["icon", "color"],
    }:
        problem("contract.json: swipe action shape drifted")
    rich_swipe = SWIPE_SCHEMA.get("rich", {})
    if rich_swipe.get("required") != ["actions"] or \
            rich_swipe.get("optional") != ["commit"] or \
            rich_swipe.get("min_actions") != 1 or \
            rich_swipe.get("max_actions_limit") != \
            "max_swipe_actions_per_side" or \
            rich_swipe.get("commit_max_actions") != 2:
        problem("contract.json: rich swipe constraints drifted")
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
    # Amendment #169: the candidate member registry and its closed kind
    # vocabulary must exist, and the gating feature must be registered.
    schema = contract.get("candidate_schema")
    if not isinstance(schema, dict) or not schema.get("kind_enum"):
        problem("contract.json: missing `candidate_schema` with `kind_enum` "
                "(amendment #169)")
    elif schema.get("kind_feature") not in contract.get("features", []):
        problem("contract.json: candidate_schema.kind_feature is not a "
                "registered feature")
    action_feature = ACTIONS.get("open_surface_feature")
    if action_feature != "action.open_surface":
        problem("contract.json: actions.open_surface_feature must register "
                "action.open_surface")
    elif action_feature not in contract.get("features", []):
        problem("contract.json: action.open_surface is not a registered feature")
    # Amendment #176: project the closed Variant object and the selector
    # builtin, rather than leaving `variant-array` as an unregistered opaque
    # field type whose receiver-specific interpretation can drift.
    if "variant_host" not in NODE_TYPES:
        problem("contract.json: amendment #176 requires `variant_host`")
    elif NODE_SCHEMA.get("variant_host") != {
            "required": ["id", "value", "variants"], "optional": []}:
        problem("contract.json: variant_host schema must be exactly "
                "{id, value, variants}")
    if contract.get("field_types", {}).get("variants") != "variant-array":
        problem("contract.json: variants field must be `variant-array`")
    if not isinstance(VARIANT_SCHEMA, dict):
        problem("contract.json: variant_schema must be an object")
    else:
        if VARIANT_SCHEMA.get("required") != ["value", "content"] or \
                VARIANT_SCHEMA.get("optional") != []:
            problem("contract.json: Variant must be the closed object "
                    "{value, content}")
        if VARIANT_SCHEMA.get("min_items") != 2:
            problem("contract.json: variant_schema.min_items must be 2")
        if VARIANT_SCHEMA.get("max_items_limit") != \
                "max_variants_per_host":
            problem("contract.json: Variant maximum must reference "
                    "max_variants_per_host")
        if VARIANT_SCHEMA.get("value_type") != "identifier" or \
                VARIANT_SCHEMA.get("content_type") != "node":
            problem("contract.json: Variant value/content types drifted")
        rules = VARIANT_SCHEMA.get("content_rules")
        expected_rules = {
            "prohibit_stateful_nodes": True,
            "prohibit_editors": True,
            "prohibit_nested_variant_hosts": True,
            "node_ids_remain_document_global": True,
        }
        if rules != expected_rules:
            problem("contract.json: Variant content restrictions drifted")
    variant_action = ACTION_SCHEMA.get("variant.switch")
    if variant_action != {"required": ["builtin", "id"],
                          "optional": ["value"]}:
        problem("contract.json: variant.switch must require id and allow "
                "only optional value")
    if MAX_VARIANTS != 8:
        problem("contract.json: max_variants_per_host must be 8")
    if "semantics" not in UNIVERSAL:
        problem("contract.json: semantics must be a universal node member")
    if contract.get("field_types", {}).get("semantics") != "semantics-object":
        problem("contract.json: semantics field must be `semantics-object`")
    expected_semantic_members = {
        "name", "description", "state_description", "error", "pane_title",
        "heading_level", "live_region", "collection", "collection_item",
        "traversal_group", "traversal_index", "actions",
    }
    if set(SEMANTICS_SCHEMA.get("optional", [])) != expected_semantic_members:
        problem("contract.json: Semantics optional member set drifted")
    if SEMANTICS_SCHEMA.get("required") != []:
        problem("contract.json: Semantics must have no required member")
    semantic_objects = SEMANTICS_SCHEMA.get("objects", {})
    for name, required in {
        "collection": {"row_count", "column_count"},
        "collection_item": {
            "row_index", "row_span", "column_index", "column_span",
        },
        "action": {"label", "on_action"},
    }.items():
        row = semantic_objects.get(name, {})
        if set(row.get("required", [])) != required or row.get("optional") != []:
            problem(f"contract.json: semantic {name} schema drifted")
    action_row = semantic_objects.get("action", {})
    if action_row.get("max_items_limit") != \
            "max_semantic_actions_per_node" or \
            action_row.get("distinct_by") != "label":
        problem("contract.json: semantic action bound/distinctness drifted")
    if MAX_SEMANTIC_ACTIONS != 8:
        problem("contract.json: max_semantic_actions_per_node must be 8")
    if SEMANTICS_SCHEMA.get("enums", {}).get("live_region") != \
            ["polite", "assertive"]:
        problem("contract.json: semantic live-region enum drifted")
    if SEMANTICS_SCHEMA.get("accessible_name_precedence") != [
            "semantics.name", "content_description", "label", "icon", "t",
            "node"]:
        problem("contract.json: accessible-name precedence drifted")
    defaults = SEMANTICS_SCHEMA.get("default_node_semantics", {})
    for node_type, row in defaults.items():
        if node_type not in NODE_TYPES:
            problem(f"contract.json: semantic default names unknown node `{node_type}`")
        role = row.get("role")
        if role is not None and role not in \
                SEMANTICS_SCHEMA.get("enums", {}).get("role", []):
            problem(f"contract.json: semantic default for `{node_type}` has unknown role")
    expected_text_input_schema = {
        "line_counts": {
            "type": "positive-integer", "order": "min<=max",
            "text_input_default_min": 1,
            "text_input_default_max": "min_lines",
            "single_line_value": 1,
            "single_line_forbids": "U+000A",
        },
        "password": {
            "authored_value": "absent-or-empty",
            "on_change": "absent",
            "clear_on_submit": "absent-or-false",
            "submit_capture": "self",
            "capture_allowed_from": ["own-on_submit", "dialog.submit"],
            "remote_policy": "drop",
            "forbidden_descriptor_members": ["dedupe", "ttl_s"],
            "requires_session_state": "READY",
            "storage": "volatile",
            "deadline_ms": 30000,
        },
        "clear_on_submit": {
            "requires": "remote-on_submit",
            "forbidden_when_on_submit": "builtin",
        },
        "selection": {
            "type": "two-number-array", "unit": "unicode-scalar",
            "minimum": 0, "order": "start<=end",
            "upper_bound": "authored-value",
            "lifecycle": "new-presentation-seed",
            "when_retained_draft_wins": "ignore",
        },
        "max_length": {
            "type": "positive-integer", "unit": "unicode-scalar",
            "behavior": "truncate-before-commit",
            "authored_value_must_fit": True,
            "retained_draft_must_fit": True,
        },
        "transform_order": ["single_line", "filter", "max_length"],
        "filter_character_sets": {
            "digits": "ascii-digit", "alnum": "ascii-alphanumeric",
        },
        "filter_unknown": "none",
        "filter_authored_value_must_match": True,
        "filter_retained_draft_must_match": True,
        "mask": {
            "slot": "#", "minimum_slots": 1, "unit": "unicode-scalar",
            "overflow": "unformatted",
            "incompatible_with": ["password", "syntax"],
        },
        "content_padding": {
            "type": "non-negative-dp",
            "applies_to": "all-interior-sides",
        },
        "variant_default": "outlined",
        "variant_unknown": "outlined",
        "hide_keyboard_on_submit_requires": "on_submit",
        "error_description_precedence": [
            "semantics.error", "supporting_text",
        ],
        "logical_value_excludes": ["prefix", "suffix", "mask-literals"],
    }
    if TEXT_INPUT_SCHEMA != expected_text_input_schema:
        problem("contract.json: text_input_schema drifted from amendment #181")


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
_NO_VARIANT_VALUE = object()


def is_identifier(value) -> bool:
    return (isinstance(value, str)
            and IDENTIFIER_RE.fullmatch(value) is not None
            and len(value.encode("utf-8")) <=
            contract["limits"]["fixed"]["max_identifier_bytes"])


class NodeDocument:
    """Whole-document facts that cannot be checked in one recursive frame."""

    def __init__(self):
        self.node_count = 0
        self.ids: dict[str, str] = {}
        self.nodes: dict[str, dict] = {}
        self.action_refs: list[tuple[str, dict, str | None, str | None]] = []
        self.variant_hosts: dict[str, tuple[set[str], str]] = {}
        self.variant_refs: list[tuple[str, str, object]] = []

    def finish(self):
        # A selector may occur before its host in tree order, or in an inactive
        # alternative before a later sibling host. Resolve only after the
        # complete document has been walked.
        for path, host_id, selected in self.variant_refs:
            host = self.variant_hosts.get(host_id)
            if host is None:
                problem(f"{path}.id: no variant_host `{host_id}` in this "
                        "document")
                continue
            values, _ = host
            if selected is not _NO_VARIANT_VALUE and selected not in values:
                problem(f"{path}.value: `{selected}` is not authored by "
                        f"variant_host `{host_id}`")

        # Section 14.6: secrecy follows the resolved captured node, never an
        # untrusted renderer flag.  Actions may precede the field they name,
        # so this relation is checked only after the complete document walk.
        password_rule = TEXT_INPUT_SCHEMA.get("password", {})
        allowed = set(password_rule.get("capture_allowed_from", []))
        for path, descriptor, hook, owner_id in self.action_refs:
            capture = descriptor.get("capture_fields")
            if not isinstance(capture, list):
                continue
            for field_id in capture:
                node = self.nodes.get(field_id)
                if not (isinstance(node, dict)
                        and node.get("t") == "text_input"
                        and node.get("password") is True):
                    continue
                own_submit = (hook == "on_submit" and owner_id == field_id
                              and "own-on_submit" in allowed)
                dialog_submit = (descriptor.get("builtin") == "dialog.submit"
                                 and "dialog.submit" in allowed)
                if not (own_submit or dialog_submit):
                    problem(f"{path}.capture_fields: password `{field_id}` "
                            "may be captured only by its own on_submit or "
                            "dialog.submit")
                if "action" in descriptor:
                    policy = descriptor.get(
                        "when_offline", ACTIONS["offline_default"])
                    if policy != password_rule.get("remote_policy"):
                        problem(f"{path}.when_offline: a password capture "
                                "must use drop")
                    for member in password_rule.get(
                            "forbidden_descriptor_members", []):
                        if member in descriptor:
                            problem(f"{path}.{member}: invalid for a password "
                                    "capture")


def check_action(obj: dict, path: str, ctx: NodeDocument | None = None,
                 hook: str | None = None, owner_id: str | None = None):
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
        # SPEC 14.1 (amendment #168): confirm is a non-empty string or the
        # object form {text, title?, icon?, confirm_label?, dismiss_label?}.
        if "confirm" in obj:
            c = obj["confirm"]
            if isinstance(c, dict):
                for k in c:
                    if k not in CONFIRM_MEMBERS:
                        problem(f"{path}: unknown confirm member `{k}`")
                if not (isinstance(c.get("text"), str) and c.get("text")):
                    problem(f"{path}: confirm.text must be a non-empty string")
                for m in ("title", "confirm_label", "dismiss_label"):
                    if m in c and not isinstance(c[m], str):
                        problem(f"{path}: confirm.{m} must be a string")
                if "icon" in c and not (
                        isinstance(c["icon"], str)
                        and IDENTIFIER_RE.fullmatch(c["icon"])):
                    problem(f"{path}: confirm.icon must be an identifier")
            elif not (isinstance(c, str) and c):
                problem(f"{path}: confirm must be a non-empty string or object")
        if "open_surface" in obj:
            target = obj["open_surface"]
            if not (isinstance(target, str)
                    and APP_SURFACE_ID_RE.fullmatch(target)
                    and len(target.encode("utf-8")) <= 128):
                problem(f"{path}.open_surface: must be an app Surface ID")
    else:
        entry = ACTION_SCHEMA.get(obj["builtin"])
        if entry is None:
            problem(f"{path}: unknown builtin `{obj['builtin']}`")
            return
        if obj["builtin"] == "surface.open" and "surface" in obj:
            target = obj["surface"]
            if not (isinstance(target, str)
                    and APP_SURFACE_ID_RE.fullmatch(target)
                    and len(target.encode("utf-8")) <= 128):
                problem(f"{path}.surface: must be an app Surface ID")
        if obj["builtin"] == "variant.switch":
            host_id = obj.get("id")
            selected = obj.get("value", _NO_VARIANT_VALUE)
            if not is_identifier(host_id):
                problem(f"{path}.id: must be an identifier")
            if selected is not _NO_VARIANT_VALUE and \
                    not is_identifier(selected):
                problem(f"{path}.value: must be an identifier")
            if ctx is not None and is_identifier(host_id) and \
                    (selected is _NO_VARIANT_VALUE or is_identifier(selected)):
                ctx.variant_refs.append((path, host_id, selected))
    required, optional = set(entry["required"]), set(entry["optional"])
    for req in required - {"builtin"}:
        if req not in obj:
            problem(f"{path}: action missing required `{req}`")
    for key in obj:
        if key not in required and key not in optional and key != "builtin":
            problem(f"{path}: unknown action field `{key}`")
    if ctx is not None:
        ctx.action_refs.append((path, obj, hook, owner_id))


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


def check_menu_items(node, path: str):
    """SPEC 17.4: a MenuItem needs a label and an on_tap, and has ONE
    trailing slot.

    Exactly one of `items` and `groups` carries the rows; an absent `items`
    belongs to the grouped form and is not an error here. A MenuItem without
    `on_tap` would draw a row that cannot do anything, so the spec requires
    it; the trailing pair is mutually exclusive because the item has a single
    trailing slot to put them in.
    """

    def check_items(items, at: str):
        if not isinstance(items, list):
            problem(f"{at}: must be an array")
            return
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                problem(f"{at}[{i}]: must be a MenuItem object")
                continue
            if not isinstance(item.get("label"), str):
                problem(f"{at}[{i}].label: MenuItem label must be a string")
            if not isinstance(item.get("on_tap"), dict):
                problem(f"{at}[{i}].on_tap: MenuItem needs an ActionDescriptor")
            if "trailing_icon" in item and "trailing_text" in item:
                problem(f"{at}[{i}]: trailing_icon and trailing_text "
                        "are mutually exclusive")

    has_items = "items" in node
    has_groups = "groups" in node
    if has_items == has_groups:
        problem(f"{path}: menu carries exactly one of items|groups")
        return
    if has_groups:
        groups = node.get("groups")
        if not isinstance(groups, list):
            problem(f"{path}.groups: must be an array")
            return
        for g, group in enumerate(groups):
            if not isinstance(group, dict):
                problem(f"{path}.groups[{g}]: must be a group object")
                continue
            items = group.get("items")
            if not isinstance(items, list) or not items:
                problem(f"{path}.groups[{g}].items: group items must be "
                        "a non-empty array")
                continue
            check_items(items, f"{path}.groups[{g}].items")
    else:
        check_items(node.get("items"), f"{path}.items")


def check_swipe_side(value, path: str, direction: str,
                     ctx: NodeDocument, owner_id: str | None):
    """Amendment #184: validate both the legacy and reveal-first shapes."""
    if not isinstance(value, dict):
        problem(f"{path}: swipe side must be an object")
        return

    action_schema = SWIPE_SCHEMA.get("action", {})
    action_allowed = set(action_schema.get("required", [])) | \
        set(action_schema.get("optional", []))

    def one(action, action_path: str):
        if not isinstance(action, dict):
            problem(f"{action_path}: SwipeAction must be an object")
            return None
        for required in action_schema.get("required", []):
            if required not in action:
                problem(f"{action_path}: missing required `{required}`")
        for member in action:
            if member not in action_allowed:
                problem(f"{action_path}: unknown SwipeAction member `{member}`")
        label = action.get("label")
        if not isinstance(label, str) or not label:
            problem(f"{action_path}.label: must be a non-empty string")
            label = None
        if "icon" in action and not is_identifier(action.get("icon")):
            problem(f"{action_path}.icon: must be an identifier")
        descriptor = action.get("on_trigger")
        if not isinstance(descriptor, dict):
            problem(f"{action_path}.on_trigger: must be an ActionDescriptor")
        else:
            if "action" not in descriptor:
                problem(f"{action_path}.on_trigger: swipe hooks require a remote action")
            check_action(descriptor, f"{action_path}.on_trigger", ctx,
                         hook=f"swipe_{direction}.on_trigger",
                         owner_id=owner_id)
        return label

    if "actions" not in value:
        legacy = SWIPE_SCHEMA.get("legacy", {})
        allowed = set(legacy.get("required", [])) | \
            set(legacy.get("optional", []))
        for member in value:
            if member not in allowed:
                problem(f"{path}: unknown legacy swipe member `{member}`")
        one(value, path)
        return

    rich = SWIPE_SCHEMA.get("rich", {})
    allowed = set(rich.get("required", [])) | set(rich.get("optional", []))
    for member in value:
        if member not in allowed:
            problem(f"{path}: unknown rich swipe member `{member}`")
    actions = value.get("actions")
    if not isinstance(actions, list):
        problem(f"{path}.actions: must be an array")
        return
    maximum = contract["limits"]["fixed"]["max_swipe_actions_per_side"]
    if not rich.get("min_actions", 1) <= len(actions) <= maximum:
        problem(f"{path}.actions: needs 1..{maximum} actions")
    commit = value.get("commit", False)
    if not isinstance(commit, bool):
        problem(f"{path}.commit: must be a boolean")
    if commit is True and len(actions) > rich.get("commit_max_actions", 2):
        problem(f"{path}.commit: deep commit supports at most two actions")
    labels = []
    for i, action in enumerate(actions):
        label = one(action, f"{path}.actions[{i}]")
        if label is not None:
            if label in labels:
                problem(f"{path}.actions[{i}].label: duplicate swipe label")
            labels.append(label)


def check_text_input(node, path: str):
    """Validate the complete amendment #181 text-input envelope."""
    value = node.get("value", "")
    if not isinstance(value, str):
        problem(f"{path}.value: must be a string")
        value = ""

    for member in ("supporting_text", "prefix", "suffix"):
        if member in node and not isinstance(node[member], str):
            problem(f"{path}.{member}: must be a string")
    for member in ("leading_icon", "trailing_icon", "syntax"):
        if member in node and not is_identifier(node[member]):
            problem(f"{path}.{member}: must be an identifier")
    for member in ("variant", "filter"):
        if member in node and not isinstance(node[member], str):
            problem(f"{path}.{member}: must be a string")
    for member in ("is_error", "hide_keyboard_on_submit"):
        if member in node and not isinstance(node[member], bool):
            problem(f"{path}.{member}: {member} must be a boolean")

    line_rule = TEXT_INPUT_SCHEMA.get("line_counts", {})
    authored_min = None
    authored_max = None
    if "min_lines" in node:
        authored_min = semantic_integer(node["min_lines"], 1)
        if authored_min is None:
            problem(f"{path}.min_lines: must be a positive integer")
    if "max_lines" in node:
        authored_max = semantic_integer(node["max_lines"], 1)
        if authored_max is None:
            problem(f"{path}.max_lines: must be a positive integer")
    minimum = authored_min or line_rule.get("text_input_default_min", 1)
    maximum_lines = authored_max or minimum
    if authored_min is not None and authored_max is not None and \
            authored_min > authored_max:
        problem(f"{path}: min_lines must not exceed max_lines")
    if node.get("single_line") is True:
        required_line_count = line_rule.get("single_line_value", 1)
        if minimum != required_line_count or maximum_lines != required_line_count:
            problem(f"{path}: single_line requires line counts of 1")
        if isinstance(value, str) and "\n" in value:
            problem(f"{path}.value: single_line value contains U+000A")

    password_rule = TEXT_INPUT_SCHEMA.get("password", {})
    if node.get("password") is True:
        if isinstance(value, str) and value:
            problem(f"{path}.value: password value must be absent or empty")
        if "on_change" in node:
            problem(f"{path}.on_change: password on_change must be absent")
        if node.get("clear_on_submit") is True:
            problem(f"{path}.clear_on_submit: password clear_on_submit must "
                    "be absent or false")
        submit = node.get("on_submit")
        if isinstance(submit, dict):
            capture = submit.get("capture_fields")
            if not isinstance(capture, list) or node.get("id") not in capture:
                problem(f"{path}.on_submit.capture_fields: password submit "
                        "must capture its own id")
            if "action" in submit and submit.get(
                    "when_offline", ACTIONS["offline_default"]) != \
                    password_rule.get("remote_policy"):
                problem(f"{path}.on_submit.when_offline: password submit "
                        "must use drop")

    if node.get("clear_on_submit") is True:
        submit = node.get("on_submit")
        clear_rule = TEXT_INPUT_SCHEMA.get("clear_on_submit", {})
        if not (isinstance(submit, dict) and "action" in submit):
            requirement = clear_rule.get("requires", "remote-on_submit")
            problem(f"{path}.clear_on_submit: requires {requirement}")

    maximum = None
    if "max_length" in node:
        maximum = semantic_integer(node["max_length"], 1)
        if maximum is None:
            problem(f"{path}.max_length: must be a positive integer")
        elif len(value) > maximum:
            problem(f"{path}.value: value exceeds max_length")

    if "content_padding" in node:
        padding = node["content_padding"]
        if isinstance(padding, bool) or not isinstance(padding, (int, float)) \
                or not math.isfinite(float(padding)):
            problem(f"{path}.content_padding: content_padding must be a finite number")
        elif padding < 0:
            problem(f"{path}.content_padding: content_padding must be non-negative")

    if "selection" in node:
        selection = node["selection"]
        if not isinstance(selection, list) or len(selection) != 2:
            problem(f"{path}.selection: must be a two-integer array")
        else:
            start = semantic_integer(selection[0], 0)
            end = semantic_integer(selection[1], 0)
            if start is None or end is None:
                if any(semantic_integer(item, -9007199254740991) is None
                       for item in selection):
                    problem(f"{path}.selection: must be a two-integer array")
                else:
                    problem(f"{path}.selection: offsets must be non-negative")
            elif start > end:
                problem(f"{path}.selection: start must not exceed end")
            elif end > len(value):
                problem(f"{path}.selection: exceeds authored value")

    filter_name = node.get("filter")
    if isinstance(filter_name, str) and filter_name in \
            TEXT_INPUT_SCHEMA.get("filter_character_sets", {}):
        if filter_name == "digits":
            matches = all("0" <= scalar <= "9" for scalar in value)
        else:
            matches = all(
                "0" <= scalar <= "9" or
                "A" <= scalar <= "Z" or
                "a" <= scalar <= "z"
                for scalar in value
            )
        if not matches:
            problem(f"{path}.value: value violates filter `{filter_name}`")

    if node.get("hide_keyboard_on_submit") is True and \
            "on_submit" not in node:
        problem(f"{path}.hide_keyboard_on_submit: requires on_submit")

    if "mask" in node:
        mask = node["mask"]
        if not isinstance(mask, str):
            problem(f"{path}.mask: must be a string")
        elif "#" not in mask:
            problem(f"{path}.mask: mask must contain at least one # slot")
        if node.get("password") is True:
            problem(f"{path}.mask: mask is incompatible with password")
        if "syntax" in node:
            problem(f"{path}.mask: mask is incompatible with syntax")


VARIANT_FORBIDDEN_STATEFUL = {
    "text_input", "checkbox", "switch", "enum_list", "slider",
    "search_bar", "dropdown", "segmented_button",
}

# Application payload members are data, not recursive Node positions.  In
# particular, a perfectly ordinary action argument or chart-point annotation
# may itself contain a member named `t`; interpreting that value as a widget
# would pollute document-global IDs and make retained-content admission depend
# on opaque application data.  Keep this aligned with endpoint walkers.
OPAQUE_NODE_WALK_MEMBERS = {"args", "meta", "value"}


def semantic_integer(value, minimum: int) -> int | None:
    """An EBP integer by value, excluding booleans and non-finite numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value != math.floor(value):
        return None
    integer = int(value)
    if integer < minimum or abs(integer) > 9007199254740991:
        return None
    return integer


def check_semantics(value, path: str, ctx: NodeDocument,
                    collection_ancestors: tuple[tuple[int, int], ...]):
    """Validate a universal Semantics object; return its collection bounds."""
    if not isinstance(value, dict):
        problem(f"{path}: must be an object")
        return None

    for member in ("name", "description", "state_description", "error",
                   "pane_title"):
        if member in value and not (
                isinstance(value[member], str) and value[member]):
            problem(f"{path}.{member}: must be a non-empty plain string")

    if "heading_level" in value and \
            semantic_integer(value["heading_level"], 1) not in range(1, 7):
        problem(f"{path}.heading_level: must be an integer 1..6")
    if "live_region" in value and value["live_region"] not in \
            SEMANTICS_SCHEMA.get("enums", {}).get("live_region", []):
        problem(f"{path}.live_region: must be polite or assertive")
    if "traversal_group" in value and not isinstance(
            value["traversal_group"], bool):
        problem(f"{path}.traversal_group: must be a boolean")
    if "traversal_index" in value:
        index = value["traversal_index"]
        if isinstance(index, bool) or not isinstance(index, (int, float)) or \
                not math.isfinite(float(index)):
            problem(f"{path}.traversal_index: must be a finite number")

    collection = None
    if "collection" in value:
        authored = value["collection"]
        if not isinstance(authored, dict):
            problem(f"{path}.collection: must be an object")
        else:
            rows = semantic_integer(authored.get("row_count"), 0)
            columns = semantic_integer(authored.get("column_count"), 1)
            if rows is None:
                problem(f"{path}.collection.row_count: must be a non-negative integer")
            if columns is None:
                problem(f"{path}.collection.column_count: must be a positive integer")
            if rows is not None and columns is not None:
                collection = (rows, columns)

    if "collection_item" in value:
        item = value["collection_item"]
        if not isinstance(item, dict):
            problem(f"{path}.collection_item: must be an object")
        else:
            row_index = semantic_integer(item.get("row_index"), 0)
            row_span = semantic_integer(item.get("row_span"), 1)
            column_index = semantic_integer(item.get("column_index"), 0)
            column_span = semantic_integer(item.get("column_span"), 1)
            for member, checked, description in (
                    ("row_index", row_index, "a non-negative integer"),
                    ("row_span", row_span, "a positive integer"),
                    ("column_index", column_index, "a non-negative integer"),
                    ("column_span", column_span, "a positive integer")):
                if checked is None:
                    problem(f"{path}.collection_item.{member}: must be {description}")
            if not collection_ancestors:
                problem(f"{path}.collection_item: requires an authored collection ancestor")
            elif None not in (row_index, row_span, column_index, column_span):
                rows, columns = collection_ancestors[-1]
                if row_index + row_span > rows:
                    problem(f"{path}.collection_item: row range exceeds ancestor collection")
                if column_index + column_span > columns:
                    problem(f"{path}.collection_item: column range exceeds ancestor collection")

    if "actions" in value:
        actions = value["actions"]
        if not isinstance(actions, list):
            problem(f"{path}.actions: must be an array")
        else:
            if len(actions) > MAX_SEMANTIC_ACTIONS:
                problem(f"{path}.actions: exceeds max_semantic_actions_per_node")
            labels: set[str] = set()
            for i, action in enumerate(actions):
                action_path = f"{path}.actions[{i}]"
                if not isinstance(action, dict):
                    problem(f"{action_path}: must be an object")
                    continue
                label = action.get("label")
                if not (isinstance(label, str) and label):
                    problem(f"{action_path}.label: must be a non-empty plain string")
                elif label in labels:
                    problem(f"{action_path}.label: duplicate semantic action label")
                else:
                    labels.add(label)
                descriptor = action.get("on_action")
                if not isinstance(descriptor, dict):
                    problem(f"{action_path}.on_action: must be an ActionDescriptor")
                else:
                    check_action(descriptor, f"{action_path}.on_action", ctx)
    # SPEC 16.5.1: receiver-forward-compatible unknown members are ignored.
    return collection


def check_variants(node: dict, path: str, depth: int, ctx: NodeDocument,
                   collection_ancestors: tuple[tuple[int, int], ...]):
    raw = node.get("variants")
    if not isinstance(raw, list):
        problem(f"{path}.variants: must be an array")
        # Continue walking a malformed container so it cannot conceal nodes or
        # actions from the complete-document validation pass.
        _check_node(raw, f"{path}.variants", depth, ctx, True,
                    collection_ancestors=collection_ancestors)
        return
    if not MIN_VARIANTS <= len(raw) <= MAX_VARIANTS:
        problem(f"{path}.variants: needs {MIN_VARIANTS}..{MAX_VARIANTS} "
                "alternatives")

    values: set[str] = set()
    required = set(VARIANT_SCHEMA.get("required", []))
    optional = set(VARIANT_SCHEMA.get("optional", []))
    for i, variant in enumerate(raw):
        vpath = f"{path}.variants[{i}]"
        if not isinstance(variant, dict):
            problem(f"{vpath}: Variant must be an object")
            _check_node(variant, vpath, depth, ctx, True,
                        collection_ancestors=collection_ancestors)
            continue
        for req in required:
            if req not in variant:
                problem(f"{vpath}: Variant missing required `{req}`")
        for key in variant:
            if key not in required and key not in optional:
                problem(f"{vpath}: unknown Variant member `{key}`")

        value = variant.get("value")
        if not is_identifier(value):
            problem(f"{vpath}.value: must be an identifier")
        elif value in values:
            problem(f"{vpath}.value: duplicate variant value `{value}`")
        else:
            values.add(value)

        content = variant.get("content")
        if not (isinstance(content, dict)
                and isinstance(content.get("t"), str)):
            problem(f"{vpath}.content: must be a Node")

        # A Variant is closed, but malformed extra members are still walked:
        # one bad member must not hide an over-budget subtree or action.
        for key, child in variant.items():
            if key == "value":
                continue
            _check_node(child, f"{vpath}.{key}", depth, ctx, True,
                        collection_ancestors=collection_ancestors)

    host_id = node.get("id")
    authored = node.get("value")
    if not is_identifier(authored):
        problem(f"{path}.value: must be an identifier")
    elif authored not in values:
        problem(f"{path}.value: `{authored}` is not an authored variant")
    if is_identifier(host_id):
        # Duplicate IDs were already rejected by the document-global ID pass;
        # retaining the first host also makes selector diagnostics stable.
        ctx.variant_hosts.setdefault(host_id, (values, path))


def _check_node(value, path: str, depth: int, ctx: NodeDocument,
                inside_variant: bool = False,
                sibling_keys: dict[str, str] | None = None,
                collection_ancestors: tuple[tuple[int, int], ...] = ()):
    if isinstance(value, list):
        # A root block sequence is one sibling set; nested arrays share the
        # nearest enclosing Node's set supplied by their caller.
        keys = sibling_keys if sibling_keys is not None else {}
        for i, child in enumerate(value):
            _check_node(child, f"{path}[{i}]", depth, ctx, inside_variant,
                        keys, collection_ancestors)
        return
    if not isinstance(value, dict):
        return  # scalars carry no schema
    node_type = None
    authored_collection = None
    if "t" in value:
        # SPEC 4.5/16.1 (amendment #108): node nesting depth. The 4.5
        # JSON-container limit is a receiver bound, not a budget a sender may
        # spend — host encoders cap well below it.
        depth += 1
        ctx.node_count += 1
        if ctx.node_count == MAX_NODES + 1:
            problem(f"{path}: document exceeds max_nodes_per_snapshot "
                    f"({MAX_NODES})")
        if depth > MAX_NODE_DEPTH:
            problem(f"{path}: node nesting exceeds max_node_depth "
                    f"({MAX_NODE_DEPTH}) — reason node-depth")
        t = value["t"]
        node_type = t
        # Universal presentation identity attributes keep their identifier
        # type even on unknown/degraded nodes. A present malformed value is
        # not equivalent to omission (SPEC 16.1/16.3).
        for member in ("id", "key"):
            if member in value and not is_identifier(value[member]):
                problem(f"{path}.{member}: must be an identifier")
        if is_identifier(value.get("key")) and sibling_keys is not None:
            node_key = value["key"]
            if node_key in sibling_keys:
                problem(f"{path}.key: duplicate sibling key `{node_key}` "
                        f"(first at {sibling_keys[node_key]})")
            else:
                sibling_keys[node_key] = path
        if is_identifier(value.get("id")):
            node_id = value["id"]
            if node_id in ctx.ids:
                problem(f"{path}.id: duplicate document-global node ID "
                        f"`{node_id}` (first at {ctx.ids[node_id]})")
            else:
                ctx.ids[node_id] = path
                ctx.nodes[node_id] = value
        if "semantics" in value:
            authored_collection = check_semantics(
                value["semantics"], f"{path}.semantics", ctx,
                collection_ancestors)
        children = value.get("children")
        if isinstance(children, list) and len(children) > MAX_CHILDREN:
            problem(f"{path}.children: exceeds max_children_per_node "
                    f"({MAX_CHILDREN})")
        if inside_variant:
            if t == "variant_host":
                problem(f"{path}: nested variant_host is prohibited in "
                        "Variant.content")
            elif t == "editor":
                problem(f"{path}: editor is prohibited in Variant.content")
            elif (isinstance(t, str) and
                  (t in VARIANT_FORBIDDEN_STATEFUL or
                   (t in {"button", "icon_button"} and
                    "checked" in value))):
                problem(f"{path}: Section 14.6 stateful node `{t}` is "
                        "prohibited in Variant.content")
        if not isinstance(t, str):
            problem(f"{path}.t: node discriminator must be a string")
        elif t not in NODE_TYPES:
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
            if t == "text_input":
                check_text_input(value, path)
            if t == "enum_list":
                check_enum_options(value, path)
            if t == "slider":
                check_slider_values(value, path)
            if t == "menu":
                check_menu_items(value, path)
            for swipe_member, direction in (
                    ("swipe_start", "start"), ("swipe_end", "end")):
                if swipe_member in value:
                    check_swipe_side(
                        value[swipe_member], f"{path}.{swipe_member}",
                        direction, ctx, value.get("id"))
            if t == "tab_selector":
                items = value.get("items")
                selected = value.get("selected")
                if not isinstance(items, list) or not items:
                    problem(f"{path}.items: must be a non-empty TabItem array")
                else:
                    for i, item in enumerate(items):
                        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                            problem(f"{path}.items[{i}].label: must be a string")
                    if (not isinstance(selected, int) or isinstance(selected, bool)
                            or selected < 0 or selected >= len(items)):
                        problem(f"{path}.selected: must index the item count")
            if t == "variant_host":
                descendants = collection_ancestors + (
                    (authored_collection,) if authored_collection else ())
                check_variants(value, path, depth, ctx, descendants)
    # Intermediate schema objects do not create a presentation parent; direct
    # descendant Nodes reached through all their members remain one sibling
    # set. A Node starts the fresh sibling set for its own descendants.
    descendant_keys = {} if node_type is not None else sibling_keys
    descendant_collections = collection_ancestors + (
        (authored_collection,) if authored_collection else ())
    for key, child in value.items():
        if node_type == "variant_host" and key == "variants":
            continue  # check_variants performed the exhaustive branch walk.
        if node_type is not None and key in {"swipe_start", "swipe_end"}:
            continue  # check_swipe_side validates and walks every descriptor.
        if node_type is not None and key == "semantics":
            continue  # recognized members/actions were checked explicitly;
                      # unknown semantics members are receiver-opaque.
        if key in OPAQUE_NODE_WALK_MEMBERS:
            continue
        if (key in HOOK_KEYS or key == "on_trigger") \
                and isinstance(child, dict):
            check_action(
                child,
                f"{path}.{key}",
                ctx,
                hook=key,
                owner_id=value.get("id") if node_type is not None else None,
            )
        else:
            _check_node(child, f"{path}.{key}", depth, ctx, inside_variant,
                        descendant_keys, descendant_collections)


def check_node(value, path: str):
    """Validate one complete node document, including deferred references."""
    ctx = NodeDocument()
    _check_node(value, path, 0, ctx)
    ctx.finish()


def check_node_documents(documents: list[tuple[object, str]]):
    """Validate several roots that together form one complete document."""
    ctx = NodeDocument()
    for value, path in documents:
        _check_node(value, path, 0, ctx)
    ctx.finish()


def check_widget_surface(spec, path: str):
    """Validate one complete widget wrapper, including every size body."""
    if not isinstance(spec, dict):
        problem(f"{path}: widget spec must be an object")
        return
    schema = contract["surface_spec_variants"]["widget"]
    required, optional = set(schema["required"]), set(schema["optional"])
    for member in required:
        if member not in spec:
            problem(f"{path}: widget spec missing `{member}`")
    for member in spec:
        if member not in required and member not in optional:
            problem(f"{path}.{member}: unknown widget member")
    if not isinstance(spec.get("title"), str):
        problem(f"{path}.title: must be a string")
    if "header_action" in spec:
        action = spec["header_action"]
        if not isinstance(action, dict):
            problem(f"{path}.header_action: must be an ActionDescriptor")
        else:
            check_action(action, f"{path}.header_action")

    documents = [(spec.get("body"), f"{path}.body")]
    if "empty" in spec:
        documents.append((spec["empty"], f"{path}.empty"))
    variants = spec.get("size_variants", [])
    if not isinstance(variants, list):
        problem(f"{path}.size_variants: must be an array")
        variants = []
    maximum = contract["limits"]["fixed"]["max_widget_size_variants"]
    if len(variants) > maximum:
        problem(f"{path}.size_variants: exceeds {maximum}")
    variant_schema = WIDGET_SIZE_VARIANT_SCHEMA
    allowed = set(variant_schema.get("required", [])) | \
        set(variant_schema.get("optional", []))
    for i, variant in enumerate(variants):
        vpath = f"{path}.size_variants[{i}]"
        if not isinstance(variant, dict):
            problem(f"{vpath}: must be an object")
            continue
        for member in variant_schema.get("required", []):
            if member not in variant:
                problem(f"{vpath}: missing `{member}`")
        for member in variant:
            if member not in allowed:
                problem(f"{vpath}.{member}: unknown WidgetSizeVariant member")
        for dimension in ("min_width", "min_height"):
            value = variant.get(dimension)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)) or value < 0:
                problem(f"{vpath}.{dimension}: must be a non-negative dp number")
        documents.append((variant.get("body"), f"{vpath}.body"))

    for document, document_path in documents:
        if not (isinstance(document, dict)
                and isinstance(document.get("t"), str)):
            problem(f"{document_path}: must be a Node")
    check_node_documents(documents)


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
    # Amendment #127: the theme payload was the only wire-rich member no
    # rail pinned — mechanically why the `meta` role drift survived three
    # rungs.  Every colors key must be a theme_role, every syntax key a
    # syntax_role, and every SyntaxStyle member a syntax_style member.
    if method == "theme.set":
        colors = params.get("colors")
        if isinstance(colors, dict):
            for k in colors:
                if k not in contract["theme_roles"]:
                    problem(f"{path}: colors key `{k}` is not a theme_role")
        syntax = params.get("syntax")
        if isinstance(syntax, dict):
            for role, style in syntax.items():
                if role not in contract["syntax_roles"]:
                    problem(f"{path}: syntax key `{role}` is not a syntax_role")
                if isinstance(style, dict):
                    for m in style:
                        if m not in contract["syntax_style"]:
                            problem(f"{path}: SyntaxStyle member `{m}` "
                                    f"on `{role}` is unregistered")
    # Structured members ride the node/action validators.
    if method in ("surface.update", "dialog.show"):
        spec = params.get("spec")
        if isinstance(spec, dict) and "views" in spec:
            views = spec["views"]
            if isinstance(views, dict):
                check_node_documents([
                    (view, f"{path}.spec.views.{name}")
                    for name, view in views.items()
                ])
        else:
            check_node(spec, f"{path}.spec")
        if "stale_spec" in params:
            check_node(params["stale_spec"], f"{path}.stale_spec")


def check_result(method: str, result, path: str):
    """Amendments #169/#172: walk a golden RESPONSE body against the
    contract's result registration.  A response fixture in frames.golden
    pairs by id with the request line immediately preceding it; this is
    the only response-body rail (scope, per #150: exactly the reply
    fixtures present in frames.golden)."""
    entry = METHODS.get(method)
    if entry is None or "result" not in entry:
        problem(f"{path}: reply pairs with `{method}`, which has no result")
        return
    if not isinstance(result, dict):
        problem(f"{path}: result must be an object")
        return
    row = entry["result"]
    required, optional = set(row["required"]), set(row["optional"])
    for req in required:
        if req not in result:
            problem(f"{path}: {method} result missing required `{req}`")
    for key in result:
        if key not in required and key not in optional:
            problem(f"{path}: unknown result key `{key}` on {method}")
    if method == "edit.complete":
        schema = contract["candidate_schema"]
        allowed = set(schema["required"]) | set(schema["optional"])
        enum = set(schema["kind_enum"])
        cands = result.get("candidates")
        if not isinstance(cands, list):
            problem(f"{path}: candidates must be an array")
            return
        for i, cand in enumerate(cands):
            cpath = f"{path}.candidates[{i}]"
            if not isinstance(cand, dict):
                problem(f"{cpath}: candidate must be an object")
                continue
            for req in schema["required"]:
                if not cand.get(req):
                    problem(f"{cpath}: missing or empty `{req}`")
            for key in cand:
                if key not in allowed:
                    problem(f"{cpath}: unknown candidate member `{key}`")
            kind = cand.get("kind")
            if kind is not None and kind not in enum:
                problem(f"{cpath}: `kind` value `{kind}` is unregistered")


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
        # `ValueError`, not `json.JSONDecodeError`: the latter is a SUBCLASS of
        # the former, so catching it does NOT catch a bare `ValueError` — and
        # CPython raises exactly that for an integer literal longer than
        # `sys.get_int_max_str_digits()` (4300 by default).  SPEC 4.5 places no
        # bound on a literal's digit count, so such a body sits well inside
        # `max_frame_bytes`, and SPEC 4.2 requires rejecting it as a Parse
        # Error.  Before this the reference validator crashed instead, which is
        # not a conforming outcome.  See docs/RESEARCH-A8-2026-07-25.md.
        except ValueError:
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
    client = hmac.new(token, f"EBP/3 client:{pid}:{cn}:{sn}".encode(),
                      hashlib.sha256).hexdigest()
    server = hmac.new(token, f"EBP/3 companion:{pid}:{sn}:{cn}".encode(),
                      hashlib.sha256).hexdigest()
    if client != ("a76f9e392582c990ef08858fe6974032"
                  "3499ab87566d9b4e6f99a246bdd024a6"):
        problem(f"hmac-kat: client_proof mismatch: {client}")
    if server != ("ca1c37bcb735442fb979127a07fc41d2"
                  "a15ea0fcf58ae1ffa4bf06edc0bdfdcc"):
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


def check_variant_semantics():
    """Amendment #176 rails for branch, identity, and deferred-ref rules."""

    def run(doc):
        saved = problems[:]
        del problems[:]
        try:
            check_node(doc, "variant-selftest")
            return problems[:]
        finally:
            del problems[:]
            problems.extend(saved)

    # The selector deliberately precedes the host: immediate lookup would
    # reject a valid document, while the complete-document pass resolves it.
    positive = {
        "t": "row",
        "children": [
            {"t": "button", "label": "All",
             "on_tap": {"builtin": "variant.switch", "id": "visibility",
                        "value": "all"}},
            {"t": "variant_host", "id": "visibility", "value": "contents",
             "variants": [
                 {"value": "contents",
                  "content": {"t": "text", "id": "contents-copy",
                              "text": "Contents"}},
                 {"value": "all",
                  "content": {"t": "text", "id": "all-copy",
                              "text": "All"}},
             ]},
        ],
    }
    found = run(positive)
    if found:
        problem("variant-selftest: valid selector-before-host document was "
                f"rejected: {found}")

    # Every fault is placed in an unselected alternative. A validator that
    # lazily validates only `value`'s branch misses all of them.
    variants = [
        {"value": "a", "content": {"t": "text", "id": "same",
                                    "text": "active"}},
        {"value": "b", "content": {"t": "text", "id": "same",
                                    "text": "duplicate ID"}},
        {"value": "c", "content": {"t": "text_input", "id": "draft"}},
        {"value": "d", "content": {
            "t": "button", "label": "bad",
            "on_tap": {"builtin": "not.registered"}}},
        {"value": "e", "content": {"t": "editor", "id": "edit"}},
        {"value": "f", "content": {
            "t": "button", "label": "bad feature value",
            "on_tap": {"action": "demo.open",
                       "open_surface": "notification:not-an-app"}}},
        {"value": "g", "content": {"t": "text", "text": "g"}},
        {"value": "h", "content": {"t": "text", "text": "h"}},
        {"value": "i", "content": {"t": "text", "text": "i"}},
    ]
    negative = {
        "t": "row",
        "children": [
            {"t": "button", "label": "Missing value",
             "on_tap": {"builtin": "variant.switch", "id": "host",
                        "value": "absent"}},
            {"t": "button", "label": "Missing host",
             "on_tap": {"builtin": "variant.switch", "id": "no-host"}},
            {"t": "variant_host", "id": "host", "value": "a",
             "variants": variants},
        ],
    }
    found = run(negative)
    expected = {
        "needs 2..8 alternatives": "inactive branches did not spend count",
        "duplicate document-global node ID": "inactive IDs were not global",
        "stateful node `text_input`": "inactive stateful node was accepted",
        "unknown builtin `not.registered`": "inactive action was not checked",
        "editor is prohibited": "inactive editor was accepted",
        "must be an app Surface ID": "inactive gated member was not checked",
        "is not authored by variant_host": "selector value was not resolved",
        "no variant_host `no-host`": "missing selector host was not resolved",
    }
    for needle, message in expected.items():
        if not any(needle in p for p in found):
            problem(f"variant-selftest: {message}")

    # Pin the complete Section 14.6 boundary rather than one representative.
    # Buttons become stateful only when `checked` is authored; plain action
    # buttons remain legal retained presentation content.
    forbidden_nodes = [
        {"t": "search_bar", "id": "search", "value": ""},
        {"t": "dropdown", "id": "drop", "value": "",
         "options": []},
        {"t": "segmented_button", "id": "segments", "options": [
            {"label": "One", "value": "one"}], "value": "one"},
        {"t": "button", "id": "toggle", "label": "Toggle",
         "checked": False},
        {"t": "icon_button", "id": "icon-toggle", "icon": "check",
         "content_description": "Toggle", "checked": False},
    ]
    for forbidden in forbidden_nodes:
        kind = forbidden["t"]
        found = run({
            "t": "variant_host", "id": "host", "value": "a",
            "variants": [
                {"value": "a", "content": {"t": "text", "text": "A"}},
                {"value": "b", "content": forbidden},
            ],
        })
        if not any(f"stateful node `{kind}`" in p for p in found):
            problem(f"variant-selftest: inactive stateful {kind} was accepted")

    found = run({
        "t": "variant_host", "id": "host", "value": "a",
        "variants": [
            {"value": "a", "content": {"t": "text", "text": "A"}},
            {"value": "b", "content": {
                "t": "button", "label": "Ordinary action",
                "on_tap": {"action": "demo.action"}}},
        ],
    })
    if any("stateful node `button`" in p for p in found):
        problem("variant-selftest: plain action button was treated as stateful")

    # Opaque application data is never a hidden Node tree.  The duplicate ID
    # deliberately appears in both payloads: neither stateful prohibition nor
    # the complete-document ID namespace may observe it.
    found = run({
        "t": "variant_host", "id": "host", "value": "a",
        "variants": [
            {"value": "a", "content": {
                "t": "button", "label": "Opaque args",
                "on_tap": {"action": "demo.action", "args": {
                    "t": "text_input", "id": "opaque"}}}},
            {"value": "b", "content": {
                "t": "chart", "series": [{"label": "One", "points": [
                    {"x": 1, "y": 2, "meta": {
                        "t": "text_input", "id": "opaque"}}]}]}},
        ],
    })
    if any("stateful node `text_input`" in p or
           "duplicate document-global node ID" in p for p in found):
        problem("variant-selftest: opaque args/meta were interpreted as nodes")

    identity_faults = run({
        "t": "variant_host", "id": "host", "value": "a",
        "variants": [
            {"value": "a", "content": {"t": "text", "text": "A"}},
            {"value": "b", "content": {
                "t": "collapsible", "id": "details",
                "header": {"t": "text", "text": "Header", "key": "same"},
                "children": [
                    {"t": "text", "text": "Body", "key": "same"},
                    {"t": "text", "text": "Wrong key type", "key": 7},
                    {"t": "text", "text": "Wrong id type", "id": {}},
                ]}},
        ],
    })
    for needle, message in {
        "duplicate sibling key": "named-slot/array duplicate key was accepted",
        ".key: must be an identifier": "malformed inactive key was accepted",
        ".id: must be an identifier": "malformed inactive id was accepted",
    }.items():
        if not any(needle in p for p in identity_faults):
            problem(f"variant-selftest: {message}")

    repeated_branch_keys = run({
        "t": "variant_host", "id": "host", "value": "a",
        "variants": [
            {"value": "a", "content": {"t": "column", "children": [
                {"t": "text", "text": "A", "key": "row"}]}},
            {"value": "b", "content": {"t": "column", "children": [
                {"t": "text", "text": "B", "key": "row"}]}},
        ],
    })
    if any("duplicate sibling key" in p for p in repeated_branch_keys):
        problem("variant-selftest: keys in separate alternatives were "
                "incorrectly treated as siblings")


# ------------------------------------------------- decode rejection self-test
def check_decode_rejections():
    """A body this data model cannot carry must REJECT, never crash (SPEC 4.2).

    The reference decoder is the thing other implementations are checked
    against, so a crash here is not merely a bug in a tool: it is the
    reference failing to demonstrate the behaviour it certifies.  The
    long-integer-literal case is the one that got through — SPEC 4.5 bounds
    the body, the nesting depth, identifiers and method names, but places no
    bound on a single literal's digit count, so a five-thousand-digit integer
    is a perfectly legal-sized frame that CPython refuses to convert.
    """
    def framed(body: bytes) -> bytes:
        return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)

    cases = [
        ("long integer literal",
         b'{"jsonrpc":"2.0","method":"probe","params":{"n":' + b"9" * 5000
         + b"}}"),
        ("long negative integer literal",
         b'{"jsonrpc":"2.0","method":"probe","params":{"n":-' + b"9" * 5000
         + b"}}"),
        ("malformed body",
         b'{"jsonrpc":"2.0","method":'),
    ]
    for label, body in cases:
        try:
            list(decode_stream([framed(body)]))
        except FrameError:
            continue
        except Exception as exc:                      # noqa: BLE001
            problem(f"decode-selftest: {label} raised "
                    f"{type(exc).__name__} instead of FrameError")
            continue
        problem(f"decode-selftest: {label} was accepted, not rejected")


# ---------------------------------------------------- editor splice replay ---
def check_editor() -> int:
    """Replay goldens/editor.golden through a reference splice reducer.

    SPEC 19.1: positions and lengths are zero-based Unicode-scalar counts.
    A Python str indexes code points, which for scalar-clean wire text IS
    the scalar domain, so the reference arithmetic is direct slicing.  The
    corpus must keep astral-plane and refused-splice coverage: those are
    the cases that expose an implementation counting UTF-16 code units
    (astral char = 2) or grapheme clusters (flag pair = 1) instead.
    """
    cases = 0
    saw_astral = False
    saw_refusal = False
    for n, line in enumerate(golden_lines("editor.golden")):
        case = json.loads(line)
        path = f"editor:{n:02d}"
        text = case["text"]
        for i, op in enumerate(case["ops"]):
            start, deleted, ins, length = (op["start"], op["del"],
                                           op["text"], op["len"])
            if any(ord(c) > 0xFFFF for c in text + ins):
                saw_astral = True
            fits = 0 <= start and 0 <= deleted and start + deleted <= len(text)
            balanced = length == len(text) - deleted + len(ins)
            if op["applies"] != (fits and balanced):
                problem(f"{path} op {i}: applies={op['applies']} but the "
                        f"scalar arithmetic says {fits and balanced}")
                break
            if not op["applies"]:
                saw_refusal = True
                continue
            text = text[:start] + ins + text[start + deleted:]
        if text != case["final"]:
            problem(f"{path}: replay produced {text!r}, "
                    f"golden says {case['final']!r}")
        if case["scalars"] != len(case["final"]):
            problem(f"{path}: scalars={case['scalars']} but final has "
                    f"{len(case['final'])} scalar values")
        cases += 1
    if not saw_astral:
        problem("editor: corpus lost its astral-plane coverage")
    if not saw_refusal:
        problem("editor: corpus lost its refused-splice coverage")
    return cases


def check_semantics_goldens() -> int:
    """Run accepted and rejected Semantics witnesses without leaking faults."""
    cases = 0
    for n, line in enumerate(golden_lines("semantics.golden")):
        case = json.loads(line)
        start = len(problems)
        check_node(case.get("node"), f"semantics:{n:02d}")
        found = problems[start:]
        del problems[start:]
        if case.get("valid") is True:
            if found:
                problem(f"semantics:{n:02d}: accepted witness rejected: {found}")
        else:
            reason = case.get("reason")
            if not isinstance(reason, str) or not any(reason in p for p in found):
                problem(f"semantics:{n:02d}: rejected witness did not report "
                        f"{reason!r}: {found}")
        cases += 1
    return cases


def check_text_input_goldens() -> int:
    """Run accepted and rejected §17.4 text-input witnesses."""
    cases = 0
    for n, line in enumerate(golden_lines("text-input.golden")):
        case = json.loads(line)
        start = len(problems)
        check_node(case.get("node"), f"text-input:{n:02d}")
        found = problems[start:]
        del problems[start:]
        if case.get("valid") is True:
            if found:
                problem(f"text-input:{n:02d}: accepted witness rejected: {found}")
        else:
            reason = case.get("reason")
            if not isinstance(reason, str) or not any(reason in p for p in found):
                problem(f"text-input:{n:02d}: rejected witness did not report "
                        f"{reason!r}: {found}")
        cases += 1
    return cases


# ------------------------------------------------------------------- main ---
def main() -> int:
    check_contract()
    check_spec_sync()
    check_hmac_kat()
    check_walk_completeness()
    check_variant_semantics()
    check_equality_semantics()
    check_decode_rejections()

    frames = 0
    last_request = None  # (method, id) of the most recent request line
    for n, line in enumerate(golden_lines("frames.golden")):
        msg = json.loads(line)
        check_frame(msg, f"frames:{n:02d}")
        if isinstance(msg, dict) and "method" not in msg and "result" in msg:
            # Amendments #169/#172: a reply fixture pairs by id with the
            # request line immediately preceding it, and its body is
            # walked against the contract's result registration.
            if last_request and msg.get("id") == last_request[1]:
                check_result(last_request[0], msg["result"],
                             f"frames:{n:02d}")
            else:
                problem(f"frames:{n:02d}: reply has no immediately "
                        f"preceding request with a matching id")
        if isinstance(msg, dict) and "method" in msg and "id" in msg:
            last_request = (msg["method"], msg["id"])
        frames += 1

    widgets = 0
    for n, line in enumerate(golden_lines("widgets.golden")):
        obj = json.loads(line)
        if "action" in obj or "builtin" in obj:
            check_action(obj, f"widgets:{n:02d}")
        else:
            check_node(obj, f"widgets:{n:02d}")
        widgets += 1

    widget_surfaces = 0
    for n, line in enumerate(golden_lines("widget-surfaces.golden")):
        check_widget_surface(json.loads(line), f"widget-surfaces:{n:02d}")
        widget_surfaces += 1

    hyper = 0
    for n, line in enumerate(golden_lines("hypertext.golden")):
        arr = json.loads(line)
        check_node(arr, f"hypertext:{n:02d}")
        hyper += len(arr)

    wire = check_wire()
    editor = check_editor()
    semantics = check_semantics_goldens()
    text_inputs = check_text_input_goldens()

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
    print(f"OK: {frames} frames, {widgets} widget lines, "
          f"{widget_surfaces} widget surfaces, {hyper} hypertext "
          f"nodes, {wire} wire fixtures x3 chunkings, "
          f"{editor} editor splice cases, {semantics} semantics witnesses, "
          f"{text_inputs} text-input witnesses validate "
          f"(spec {contract['spec_version']}, "
          f"format {contract['contract_format']}); "
          f"SPEC §8/§11 in sync; 9.3 KAT reproduced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
