# Building your own companion

The companion is the durable server: it listens, renders what Emacs
sends, caches the last-known UI, and queues actions while Emacs is away.
The reference implementation is Android (Kotlin / Jetpack Compose), but
nothing in the contract is Android's — a desktop tray app, an e-ink
dashboard, a terminal TUI, a web view on a tablet: anything that can hold
a TCP socket and draw boxes can be a companion.

[SPEC.md](SPEC.md) is the whole contract. This guide is the *build
order* — the rungs in the order they pay off and what to test at each
one; everything here stands alone, and a map into the reference
implementation's source sits [at the end](#the-reference-implementation-in-one-place)
for when you want a worked example. §12 of the spec defines minimal
conformance; this document is that section, unrolled. (The guide tracks
the protocol-1 NDJSON wire; the v2 line, [SPEC-2.md](SPEC-2.md),
re-homes the same constitution on JSON-RPC 2.0 framing — rungs 1–4
carry over, and rung 0's envelope is §2 of that spec.)

Two facts that make this easier than it looks:

- **You don't need a phone or Emacs-on-Android.** The transport is plain
  NDJSON over loopback TCP, and the reference elisp client runs in
  desktop Emacs 28+: configure its host, port, and token to point at
  your companion and connect. Your whole development loop can run on
  one machine.
- **The conformance fixtures already exist.**
  [`goldens/widgets.golden`](goldens/widgets.golden) is one JSON line per
  node the client can emit — every wire shape, machine-checked against
  [`contract.json`](contract.json) on every CI run. Feed each line to
  your renderer in your own test suite and you are held to the same
  truth the reference companion is.
  [`goldens/frames.golden`](goldens/frames.golden) does the same for
  trigger/capability frames (§10–§11), and
  [`validate.py`](validate.py) is a runnable reference for the schema
  checks.

## The rungs

### Rung 0 — socket and envelope (SPEC §1–§2)

Listen on `127.0.0.1:8765`. One JSON object per `\n`-terminated line;
tolerate partial lines across reads and ignore blank lines. Parse the
five envelope fields; answer `ping` with `pong` (`reply_to` = the ping's
`id`). Log-and-continue on any unknown `kind` — an unknown frame must
never kill the connection.

*Test:* a `ping` from the connected client round-trips as `pong`.

### Rung 1 — handshake and pairing auth (SPEC §3)

The four-frame dance: `session.hello` → `auth.challenge` →
`auth.response` → `session.welcome`. Generate a pairing token, show it
once in your UI, never send it. Verify the client's
`HMAC-SHA256(token, "ebp1:client:" + SNONCE + ":" + CNONCE)` and
prove yourself back with the `server` variant (nonces swapped). Fail
closed on a bad mac — refuse before trusting anything.

Your welcome must carry: `granted` (the intersection of the client's
`wants` with what you actually support — never grant what you can't
host), **`node_types`** (the flat list of §9 node `t`s you render — the
negotiation that lets a newer client fall back gracefully on you),
`surfaces` (your cached surface → revision map, empty at first), and
`queued_events`.

*Test:* the client reports a completed handshake; a wrong token is
refused.

### Rung 2 — surfaces, revisions, cache (SPEC §4)

Store the latest spec per surface id; **reject any revision that is not
strictly newer** than what you hold (this is what makes pushes
idempotent and replay-safe); render `app:*` surfaces; keep rendering
the cache while Emacs is disconnected — offline display *is* the
feature. Multi-view specs (`{views, initial_view}`) switch locally via
the `view.switch` builtin, answered with a drop-policy `view.switched`
event; never yank the user's view on a background update.

### Rung 3 — the renderer (SPEC §9, §12)

Walk the node tree; render the families you support. The two iron
rules: **unknown keys are ignored**, and **an unknown node type renders
its `children` if it has any, else nothing — never a crash**. Only
advertise in `node_types` what you actually draw. Value-carrying
callbacks (`on_change`, `on_submit`, `on_save`, `on_pick`) dispatch
their action with the widget's current value injected into `args` as
`value`.

Start tiny: `text`, `column`, `card`, `button` render a legible
dashboard — enough for a first integration test against the connected
client (the reference repo ships a ~60-line hello app for exactly
this).

*Test:* every `widgets.golden` line parses and renders (or degrades)
without crashing.

### Rung 4 — actions and the offline queue (SPEC §5–§6)

Taps become `event.action {action, args}` frames. Honor the spec
author's `when_offline` policy: `queue` (persist, replay in order),
`drop`, `wake` (best-effort start Emacs, then queue). A queued action
replaces any queued action with the same `dedupe` key. Mirror widget
state into `state.changed`. After a reconnect, answer `queue.replay` by
streaming the queued events in order and finishing with
`queue.drained {delivered, expired}`.

You are now a **minimal conforming companion** per SPEC §12.

### Optional rungs — each behind its grant

- **§7 dialogs / toasts / reminders** (`surfaces.dialog`, …) — dialogs
  unlock the minibuffer bridge: Emacs prompts become your native
  dialogs.
- **§8 editor sync** — a live text editor backed by Emacs: deltas in
  code points, completion, diagnostics, eldoc. The invariant to keep:
  wrong state may cost a feature, never a wrong edit.
- **§10 device capabilities** — effectors Emacs can invoke, with typed
  errors (`cap-unsupported` / `cap-permission` / `cap-failed`).
- **§11 device triggers** — replace-set registrations, host-side
  hysteresis/throttling, and the deliberately closed `on_fire`
  vocabulary (no conditionals, no loops — logic lives in Emacs).

Don't grant a capability you can't host; the client degrades cleanly
around an absent grant, and that degradation is a *designed* path, not
an error path.

## The non-negotiables

1. **Forward compatibility** — unknown kinds, keys, node types, draw
   ops, and `on_fire` entries are logged and skipped, never fatal.
2. **Fail-closed auth** — no state is trusted before the mac verifies;
   your `server_proof` is not optional.
3. **Revision monotonicity** — a stale or replayed `surface.update`
   must be a no-op.
4. **Nothing on the wire is code** — you render data and report events
   by name. The companion never evaluates, shells out for, or
   dispatches anything the wire names (the closed `on_fire` vocabulary
   is the one, deliberately tiny exception).

## The reference implementation, in one place

Nothing above requires reading another repo. When you want a worked
example, the reference pair lives in the
[jetpacs repo](https://github.com/calebc42/jetpacs): an elisp client
(the desktop-Emacs development loop from the top of this guide) and an
Android/Compose companion. Where each rung is implemented there:

| Rung | Reference source |
|---|---|
| 0 — socket and envelope | `FrameCodec.kt`, `Envelope.kt`, `JetpacsServer.kt` |
| 1 — handshake and auth | `JetpacsAuth.kt`; the welcome builder in `JetpacsConnection.kt` |
| 2 — surfaces and cache | `SurfaceStore.kt`, `SurfaceManager.kt` |
| 3 — renderer | `SduiRenderer.kt`, `SduiContentNodes.kt`, `SduiInputNodes.kt`, `SduiScaffold.kt`; `jetpacs-hello.el` (~60 lines) as the first integration test |
| 4 — actions and queue | `ActionReceiver.kt`; the queue in `JetpacsDatabase.kt` |
| §7 dialogs / reminders | `JetpacsDialogState.kt`, `Reminders.kt` |
| §8 editor sync | `EditorSync.kt` |
| §10 device capabilities | `DeviceCapabilities.kt` |
| §11 device triggers | `TriggerHost.kt`, `BootReceiver.kt` |

The same repo's
[ARCHITECTURE.md](https://github.com/calebc42/jetpacs/blob/main/docs/ARCHITECTURE.md#kotlin-conformance-checklist-the-contract-tripwire)
maintains the table mapping every reference-companion surface to its
SPEC section. Reuse it as your own audit: for each row, either your
companion implements the section or it doesn't grant/advertise it.
There is no third state.

## License

The spec is an interface anyone may implement. A clean-room companion
written against SPEC.md carries no obligation from this repo's GPLv3 —
see the README's License section. (If you *port* the reference Kotlin,
that's a derivative work and GPLv3 applies.)
