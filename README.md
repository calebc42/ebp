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
layout of a reference implementation.

## What's here

| File | What it is |
|---|---|
| [`SPEC.md`](SPEC.md) | The normative protocol — envelope, handshake, surfaces, the semantic-action boundary, offline queue, dialogs/reminders, editor sync, the widget vocabulary, device capabilities, triggers, and conformance (§12). Anything not marked **(optional)** is required. |
| [`contract.json`](contract.json) | The machine-readable vocabulary a renderer or authoring tool validates emissions against — node types, the per-node key schema, the frame-kind schema, the discriminated action schema, offline policies, the toolbar and binding vocabularies. |
| [`goldens/`](goldens/) | The conformance corpus. One JSON line per wire shape: `widgets.golden` (every node the client can emit), `frames.golden` (trigger/capability frames), `hypertext.golden` (document node arrays). Feed each line to your renderer's test suite and you are held to the same truth the reference companion is. |
| [`BUILDING-COMPANION.md`](BUILDING-COMPANION.md) | The build order — the rungs of §12 conformance unrolled, what to test at each, and where the reference Kotlin does the same job. |
| [`validate.py`](validate.py) | Stdlib-only self-check: every golden line validates against `contract.json`. Run by this repo's CI, and a runnable reference for the checks your own renderer's test suite should perform. |
| [`SPEC-CHANGES.md`](SPEC-CHANGES.md) | The amendment log. Every normative change lands with one entry here (date, section, change, fixtures regenerated, reviewer). No entry, no amendment. |

## Versioning

Three numbers, all declared in `contract.json` and `SPEC.md`:

- **`protocol_version`** (the envelope `v`) — the wire version. Bumped only on a
  *breaking* change to the frozen surface (envelope, handshake, surfaces,
  action boundary, offline queue). Currently `1`.
- **`spec_version`** — this document's revision (currently `1.0-rc`). Grows with
  additive, negotiated features (§7–§11) and the node vocabulary (§9), which do
  **not** bump `protocol_version`: a new node type is negotiated per-connection
  via `node_types` (§3), not versioned.
- **`contract_format`** — the shape of `contract.json` itself (currently `3`).

Releases are tagged off the protocol/spec numbers (e.g. `spec-1.0-rc`). The
elisp reference implementation's own API version is a *separate* number that
lives with that implementation — `contract.json` carries it only as the
informational `reference_api_version` (the reference client's Tier-1 surface
at generation time); pin `protocol_version` / `spec_version` instead.

## Consumers

- The **Jetpacs** reference implementation — an elisp client
  (`emacs/core/`) and an Android/Compose companion — generates and
  conformance-tests against this contract.
- **jetpacs-composer**, a no-code view editor, validates authored emissions
  against `contract.json`.
- Your companion or client: pin a tag of this repo and hold your renderer to
  `goldens/` and `contract.json` (`python3 validate.py` shows how). Start at
  [`BUILDING-COMPANION.md`](BUILDING-COMPANION.md).

## License

GPL — see [`LICENSE`](LICENSE).
