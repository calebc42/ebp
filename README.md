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
| [`SPEC.md`](SPEC.md) | The v1 protocol — envelope, handshake, surfaces, the semantic-action boundary, offline queue, dialogs/reminders, editor sync, the widget vocabulary, device capabilities, triggers, and conformance (§12). Anything not marked **(optional)** is required. |
| [`SPEC-2.md`](SPEC-2.md) | The v2 line (draft): the same constitution on a JSON-RPC 2.0 envelope with Content-Length framing, typed error codes, the frame cap, and the overload rules. §6 incorporates everything below the envelope from SPEC.md by reference. **`contract.json` and `frames.golden` now track this line.** |
| [`contract.json`](contract.json) | The machine-readable vocabulary a renderer or authoring tool validates emissions against — node types, the per-node key schema, the JSON-RPC method table with result schemas and error codes, the discriminated action schema, offline policies, the toolbar and binding vocabularies. |
| [`goldens/`](goldens/) | The conformance corpus. One JSON line per wire shape: `widgets.golden` (every node the client can emit), `frames.golden` (trigger/capability frames), `hypertext.golden` (document node arrays). Feed each line to your renderer's test suite and you are held to the same truth the reference companion is. |
| [`BUILDING-COMPANION.md`](BUILDING-COMPANION.md) | The build order — the rungs of §12 conformance unrolled, what to test at each, and where the reference Kotlin does the same job. |
| [`validate.py`](validate.py) | Stdlib-only self-check: every golden line validates against `contract.json`. Run by this repo's CI, and a runnable reference for the checks your own renderer's test suite should perform. |
| [`SPEC-CHANGES.md`](SPEC-CHANGES.md) | The amendment log. Every normative change lands with one entry here (date, section, change, fixtures regenerated, reviewer). No entry, no amendment. |
| [`slop-docs/`](slop-docs/) | The slop line's drafting kits and precedent surveys (JSON-RPC conversion, WebSocket transport, the LiveView harvest) — the provenance documents SPEC-2's status block and §16 cite. Informative only — not part of the contract surface. |

## Versioning

Three numbers, all declared in `contract.json` and the governing spec's
header (SPEC-2.md for the current line):

- **`protocol_version`** (offered in `session.hello`) — the wire version.
  Bumped only on a *breaking* change to the frozen surface (envelope,
  handshake, surfaces, action boundary, offline queue). Currently `2`:
  the JSON-RPC envelope swap (SPEC-2, amendment #27); `1` is the SPEC.md
  NDJSON line, pinned by its last format-3 tag.
- **`spec_version`** — the governing spec's revision (currently
  `2.0-draft`). Grows with additive, negotiated features (§7–§11) and the
  node vocabulary (§9), which do **not** bump `protocol_version`: a new
  node type is negotiated per-connection via `node_types` (§3), not
  versioned.
- **`contract_format`** — the shape of `contract.json` itself (currently
  `5`: the `methods` table + `error_codes`).

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
