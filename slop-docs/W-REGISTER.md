# W-register resolution — the spec-weakness register, adjudicated

The spec-weakness register (W1–W9) surfaced by the poc-v1 → SPEC.md divergence
audit (`jetpacs/llm-poc/docs/AUDIT-ebp2-divergence-map.md` §5) is resolved here.
Each item was adjudicated 2026-07-22 against poc-v1 (branch `slop-fork/poc-v1`),
the governing SPEC.md, and format-6 `contract.json`. Four became additive spec
amendments; five need no change (out-of-scope or already covered). A depth
ambiguity the W1–W6 rewrite surfaced was pinned in the same pass.

## Amended (see SPEC-CHANGES.md)

| # | Item | Amendment | Change |
|---|---|---|---|
| §4.5 depth | JSON nesting-depth response class (not a W-item; surfaced by the rewrite) | **#35** §4.5, §24.6 | A body past 64 containers is a §6.2 Parse Error (`-32700`, `id:null`), rejected before parsing (bounded-stack scan), REQUIRED-for-Companion / RECOMMENDED-for-Emacs. New `goldens/wire/21-deep-nesting.bin`. |
| W1 | `theme.set.base` three-way theme choice | **#36** §18.4 | Omitting `dark` = follow the device's system polarity; with `colors` (mirror vs `null` native) this yields light / dark / follow-system / mirror-Emacs. No `base` member, no brand-on-wire naming — the mode choice is Emacs-side policy. Prose-only, no contract change. |
| W3 | Toolbar `line` / `line_ops` (promote/demote/move) — **orgseq depends on it** | **#37** §17.7 | A new `line` toolbar op (`promote`/`demote`/`move-up`/`move-down`), Companion-local and valid in every editor tier (closing the local-tier gap `command`'s READY/synchronized-only rule left). Org-flavored structural semantics; `toolbar.line_ops` projected to the linters. |
| W5 | `1400 frame-too-large` diagnostic | **#38** §6.2, §8 | A SHOULD-level pre-close `log.error` (`1400`) when a size-cap close is triggered by a synchronized, well-formed header section. Registered in §8 as a diagnostic-only code (carried in `log.error`, never a response `error.code`; §8 preamble records the category). |
| W6 | `tile:*` (Quick-Settings) surface namespace | **#39** §13.1, §10.2, §22.1 | `tile:<name>` registered as a first-class capability-gated namespace on a new `surfaces.tile` capability, parallel to notification/widget (the narrow option, not a general extension mechanism). |

## No amendment

- **W2 — Binding layer (list/board/calendar layouts, transforms, chrome): out of scope (client-side authoring).** A `:spec` compiles on device to ordinary wire nodes and actions (`jetpacs/llm-poc/docs/BINDING.md`); the compiled output crosses via ordinary `surface.update` and obeys the spec like any node tree. `:query` thunks run server-side and are never serialized; no view definition or "saved view" is persisted on the Companion or replayed (grep of both endpoints finds none). Format 6 already excludes the format-5 `binding` block, so the wire contract is clean. The authoring vocabulary belongs to the composer's own (non-wire) authoring contract.
- **W4 — `pie_menu.show.buffer`: dropped (no wire need).** poc-v1 emitted a top-level `buffer` the Companion never read (`RadialMenu.kt` consumes only `categories`/`center_label`); buffer identity already rides each descriptor's `event.action` `args`. Format 6's `pie_menu.show = {menu_id, categories, center_label?}` covers the feature; the field was never a format-6 member, so dropping it invalidates nothing.
- **W7 — `trigger.test` / `trigger.toggle`: out of scope (app-level action names).** Both are Emacs allowlisted `event.action` names (`jetpacs-triggers.el`), not protocol methods. EBP allowlists action names application-side by design and does not enumerate them; no spec home is needed.
- **W8 — Devtools / instrumentation: out of scope (client-only).** `jetpacs-devtools.el` observes two in-process seams and emits no frame ("zero wire cost"). Defines no method, member, or enum.
- **W9 — Editor `command` args: already covered.** §17.7 already REQUIRES the full `edit.command` arg set (`command`, `document`, `editor_id`, `session`, `seq`, `cursor`, `sel_start`, `sel_end`). poc-v1's leaner shape is the pre-rewrite form; the current spec is the governing one.

## Wire-compatibility

Every amendment is additive: no previously-valid format-6 frame is invalidated.
`validate.py` is green after the full set (16 wire fixtures incl. the new depth
vector; §8/§11 in sync; KAT reproduced). SPEC-CHANGES rows 35–39 carry blank
Reviewed-by cells pending Caleb's checkoff.
