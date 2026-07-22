# ebp — the Emacs Bridge Protocol

A wire contract for connecting a live Emacs to a **companion** that renders
server-driven UI. Emacs is the source of truth; the companion is a thin pane of
glass — it renders the specs it is sent, caches them for offline display, and
reports user interactions back as semantic events. Nothing here is Android's:
the reference companion is Android/Compose, but a desktop tray app, an e-ink
dashboard, a terminal TUI, or a web view is just as conformant — anything that
can hold a TCP socket and draw boxes.

This repo is the **contract**, not an implementation. It exists so that any
client or companion can pin a stable, versioned surface without depending on the
layout of a reference implementation. The contract is **authored here**:
`contract.json` and `goldens/` are this repo's hand-owned truth, and nothing in
this repo requires any implementation to exist or build (`validate.py` is
stdlib-only). Reference implementations keep themselves conformant with their
own tooling — an intended wire change lands here first, by amendment, and the
implementations follow.

## What's here

| File | What it is |
|---|---|
| [`SPEC.md`](SPEC.md) | **The governing spec** (protocol 2, document 2.0.0-draft) — the normalized rewrite: JSON data model, Content-Length framing, JSON-RPC conventions, pairing with a normative HMAC known-answer vector, session lifecycle, surfaces and input-state reconciliation, the semantic-action boundary, durable queue, the widget vocabulary, presentation/editor/capability/trigger modules, and conformance (§24) with the required adversarial tests (§24.6). |
| [`SPEC-2.md`](SPEC-2.md) | Historical: the previous v2 draft (the envelope-swap fold). Superseded by `SPEC.md` (amendment #32); kept for amendment-log provenance. |
| [`contract.json`](contract.json) | The machine-readable projection (format 6) a renderer or authoring tool validates emissions against — node registry and per-node key schema with universal attributes, field types and enums, the full method table (sender, class, legal states, capability gate, params, result, errors), the error-code registry, limits, the discriminated action schema, and the capability/trigger/state registries. |
| [`goldens/`](goldens/) | The conformance corpus. JSON-line files: `widgets.golden` (every node type plus bare actions), `frames.golden` (one message per registry method, both directions), `hypertext.golden` (document node arrays). `goldens/wire/` holds byte-exact framed fixtures per §24.5 — positive vectors (the §9.3 known-answer handshake, a UTF-8 byte-count body, back-to-back frames) and negative vectors (§24.6 items 1–3) — described by `goldens/wire/manifest.json`. |
| [`BUILDING-COMPANION.md`](BUILDING-COMPANION.md) | The build order — conformance unrolled rung by rung, what to test at each, and where the reference Kotlin does the same job. |
| [`validate.py`](validate.py) | Stdlib-only self-check and reference conformance harness: goldens against `contract.json`, `contract.json` against SPEC §8/§11, wire fixtures through a reference decoder at varied chunk sizes (including one octet at a time), and the §9.3 HMAC known-answer vector. Run by this repo's CI. |
| [`SPEC-CHANGES.md`](SPEC-CHANGES.md) | The amendment log. Every normative change lands with one entry here (date, section, change, fixtures regenerated, reviewer). No entry, no amendment. |
| [`slop-docs/`](slop-docs/) | The slop line's drafting kits and precedent surveys (JSON-RPC conversion, WebSocket transport, the LiveView harvest) — the provenance documents SPEC-2's status block and §16 cite. Informative only — not part of the contract surface. |

## Versioning

Three numbers, all declared in `contract.json` and the governing spec's
header (SPEC.md):

- **`protocol_version`** (offered in `session.hello`) — the wire version.
  Bumped only on a *breaking* change per SPEC §25. Currently `2`:
  the JSON-RPC envelope line (amendment #27); `1` is the retired NDJSON
  line, pinned by its last format-3 tag.
- **`spec_version`** — the governing spec's revision (currently
  `2.0.0-draft`). Grows with additive, negotiated features and the node
  vocabulary, which do **not** bump `protocol_version`: a new node type is
  negotiated per-connection via `surface_profiles` (SPEC §10.2), not
  versioned.
- **`contract_format`** — the shape of `contract.json` itself (currently
  `6`: typed method table with states/gates, universal node attributes,
  field types and enums, and the module registries).

Releases are tagged off the protocol/spec numbers (e.g. `spec-1.0-rc`). The
elisp reference implementation's own API version is a *separate* number that
lives with that implementation — `contract.json` carries it only as the
informational `reference_api_version` (the reference client's Tier-1 surface
as of the last reference sync); pin `protocol_version` / `spec_version` instead.

## Consumers

- The **Jetpacs** reference implementation — an elisp client and an
  Android/Compose companion — conformance-tests against this contract
  (its suite regenerates its own projection of `contract.json` and the
  goldens, and byte-compares against the committed files here).
- **jetpacs-composer**, a no-code view editor, validates authored emissions
  against `contract.json`.
- Your companion or client: pin a tag of this repo and hold your renderer to
  `goldens/` and `contract.json` (`python3 validate.py` shows how). Start at
  [`BUILDING-COMPANION.md`](BUILDING-COMPANION.md).

## License

GPL — see [`LICENSE`](LICENSE).
