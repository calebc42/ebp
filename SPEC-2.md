# EBP 2 — the Emacs Bridge Protocol on JSON-RPC 2.0 (draft)

**Status: the slop line.** This is the Claude-drafted reference rebuild, living
on `ebp/slop-fork` by the same convention that names `jetpacs/slop-fork`: an
LLM-written twin, deliberately labeled, kept as the quarry and the checking
copy. **The owner's hand-written spec is the real line and supersedes this
document wherever they diverge.** Drafted 2026-07-18 from: SPEC.md 1.0-rc as
amended through #22 (this branch's parent), decision #2 of the rebuild
decision log, `slop-docs/JSONRPC-conversion-kit.md` (facts verified against
jsonrpc.el v1.0.29), the LSP 3.18 precedent survey, and the LiveView harvest.
Lineage note: the point/region vocabulary (the other lineage's amendment #14,
`bbe835f`) is **not yet folded in** — it joins at the two-#14 reconciliation.

Sketch policy: this draft rewrites only what the envelope swap touches
(§§1–3 and the method table). Everything payload-level — surfaces, events,
queue policy, widgets, capabilities, triggers, the growth rule — **carries
unchanged** from 1.0-rc-as-amended and is incorporated by reference (§5),
because that was the point of the layer stack: the constitution above the
envelope survives the envelope's replacement.

## 1. The layer stack

```
vocabulary      methods, payload schemas, direction rules, handshake,
 (this spec)    surfaces, queue, editor sync, capabilities, triggers
────────────────────────────────────────────────────────────────────
message shape   JSON-RPC 2.0 — frozen 2010 spec (jsonrpc.org), rented
────────────────────────────────────────────────────────────────────
framing         Content-Length: N \r\n \r\n {json}          (rented)
────────────────────────────────────────────────────────────────────
transport       loopback TCP (v0) → Unix domain socket (1.0 target)
```

Renting the two middle layers buys, on the Emacs side, core `jsonrpc.el`
unmodified — its framing, id bookkeeping, connection lifecycle, and events
buffer (every frame in/out, timestamped: the debugging story). The one
documented seam it needs is §2.5's outbound-error-data pattern.

## 2. Envelope

### 2.1 Message shapes

```json
request        {"jsonrpc":"2.0", "id": 7, "method": "capability.invoke", "params": {...}}
notification   {"jsonrpc":"2.0", "method": "surface.update", "params": {...}}
result         {"jsonrpc":"2.0", "id": 7, "result": {...}}
error          {"jsonrpc":"2.0", "id": 7, "error": {"code": 1002, "message": "...", "data": {...}}}
```

A request carries `id` and is answered exactly once — with `result` XOR
`error`, never both, and a `null` result means "success, nothing to say",
never failure (LSP's rule, adopted verbatim). A notification carries no `id`
and is never answered. The old envelope's `ack`, bare `error` kind,
`capability.result`, `queue.drained`, `completions.show`, and the two
handshake reply kinds all dissolve into this structure — seven kinds gone,
each replaced by something structurally better (see the method table, §4).

### 2.2 Framing

`Content-Length: <bytes>\r\n\r\n<json>`, byte-accurate, UTF-8. No
`Content-Type` is sent; readers tolerate and ignore extra header lines
(jsonrpc.el does both, :653-656, :823-831). One frame, one message:
**JSON-RPC batch arrays are prohibited** — a batch complicates every
dispatcher for zero benefit on a local socket (kit decision 5.4, adopted).

### 2.3 Dispatch rules (normative)

- **Ids are per-connection**, and every outstanding request dies with the
  connection — the caller receives a local error, never silence
  (jsonrpc.el already does both: ids :97-100, death-with-connection
  :760-785). State it; never rely on it silently (kit 5.2, adopted).
- **Direction enforcement.** Every method in §4 has a direction. Receiving a
  method from the wrong side is a protocol error (`-32600`-class), not a
  dispatch (kit 5.5, adopted).
- **Unknown method:** a request is answered `-32601` method-not-found; a
  notification is logged and dropped. The connection lives — the
  forward-compat rule, unchanged in spirit from v1. **Implementation warning
  (verified):** stock `jsonrpc.el` does *neither* — its default dispatchers
  are `#'ignore`, so an unhandled request returns a success-shaped `null`,
  which is fail-*open*. Both halves of this rule are the dispatcher author's
  job.
- **Unsolicited faults** (a companion problem outside any request) ride a
  `log.error` notification — the bare error frame is not resurrected
  (kit 5.3, adopted).
- **Cancellation.** `rpc.cancel {id}` (notification, either direction) asks
  the peer to abandon the outstanding request `id`; the peer still answers
  it, with error code `1301 request-cancelled` — a cancelled request is
  concluded, never left dangling (LSP `$/cancelRequest` + its
  cancellation-still-responds rule, adopted). The v1 `dialog.dismiss` kind
  dissolves into this: dismissing a dialog is cancelling its `dialog.show`
  request.

### 2.4 Error codes

Numeric `code` for machines; the readable string vocabulary of v1 moves into
`data.kind` (the remedy pattern survives: `cap-permission` still carries
`perm` and `settings` in `data`). Reserved ranges respected: `-32768..-32000`
is JSON-RPC's; `-32899..-32800` is LSP's and other implementers stay out by
the base spec's own rule — courtesy adopted. Two landmines from the actual
library, normative to avoid: **never use code `32000`** (a jsonrpc.el
sentinel meaning "no error" — it transmutes an error into a result,
:352-355) and **`-1` is taken** (jsonrpc.el's local "Server died").

| code | data.kind | context |
|---|---|---|
| -32700 / -32600 / -32601 / -32602 / -32603 | — | JSON-RPC standard set |
| 1001 | `cap-unsupported` | capability.invoke |
| 1002 | `cap-permission` (+ `perm`, `settings`) | capability.invoke; the remedy rides `data` |
| 1003 | `cap-failed` | capability.invoke |
| 1101 | `triggers-rejected` (+ `type`) | triggers.set wholesale rejection — typed at last |
| 1200 | `not-authenticated` | any method before the proof completes (§3) |
| 1201 | `spec-invalid` | malformed params on a handshake request |
| 1202 | `proto-version` | protocol mismatch at hello |
| 1203 | `auth-failed` | bad MAC |
| 1301 | `request-cancelled` | the answer to a cancelled request |

Growing this table is an ordinary amendment; the machine copy lives in the
contract (v1 amendment #22's `error_codes`, renumbered to codes+kinds here).
Draft decision, flagged: v1's three handshake refusals map to 1200-range
codes rather than staying string-only — a clean-room companion should learn
every code from the contract, not from prose.

### 2.5 The jsonrpc.el outbound-data seam (implementation note, verified)

When an Emacs-side handler signals `jsonrpc-error`, the library's reply path
emits only `code` and `message` — `data` is stripped in the dispatch loop
before any overridable generic runs (:347-358). Since `data.kind` is this
spec's error vocabulary, Emacs-as-responder needs the documented pattern:
stash the data in a dynamic variable or connection slot before signalling
(safe — the reply is emitted synchronously within the dispatch extent) and
re-attach it in a `jsonrpc-convert-to-endpoint` override (:170-188). A
supported subclass seam, not a fork. Inbound data is untouched (:486-491),
so companion-emitted errors — the common case — need nothing.

## 3. Handshake

Two request/response pairs replace v1's four kinds; the challenge and the
welcome become *responses*, which makes ordering structural:

```
C→  session.hello   {protocol, client, wants, features?}   →  {nonce}
C→  auth.response   {nonce, mac}                           →  the welcome
```

The welcome (the treaty) carries exactly v1-as-amended's fields:
`{server_proof, granted, node_types, surfaces, queued_events, input_state?,
can_disable?, device?, protocol?, server?}` — including the offline typed-
input snapshot (amendment #16), the `can_disable` report (#18), and
`device.trigger_unavailable` (#21). HMAC construction, token handling, and
mutual fail-closed verification carry from v1 §3 unchanged (`ebp1:` domain
tags — pending the owner's decision on whether the rebuild retags to
`ebp2:`, which amendment #11's lockstep pattern would govern).

**The fail-closed dispatcher rule (normative, sharpened by the jsonrpc.el
findings):** until `auth.response` succeeds, the dispatcher answers *every*
other request with `1200 not-authenticated` and drops every notification —
**by explicitly signalling**, because the library's default answers
unhandled requests with success-shaped `null`. Fail-closed is written in
your dispatcher or it is not real.

## 4. The method table (all of v1's 29 kinds accounted for)

Direction: C→ = Emacs sends; K→ = companion sends.

**Requests:**

| method | dir | params → result |
|---|---|---|
| `session.hello` | C→ | see §3 |
| `auth.response` | C→ | see §3 |
| `capability.invoke` | C→ | `{cap, args?}` → `{result?}`; typed errors 1001–1003. Carries the whole §10 catalog incl. `state.get` and `trigger.fire` |
| `queue.replay` | C→ | `{}` → `{delivered, expired, duplicate_request?}` — the drain summary is the response; v1's `queue.drained` dissolves |
| `dialog.show` | C→ | node-tree spec → **the user's answer** — v1's never-specified `prompt.reply` dissolves; stacked prompts are simply multiple outstanding requests |
| `triggers.set` | C→ | `{triggers}` → `{}`; wholesale rejection = error 1101, typed at last |
| `reminders.set` | C→ | `{reminders, owner?}` → `{}` — promoted so acceptance is typed |
| `edit.complete` | K→ | `{file, session, seq, cursor}` → `{prefix, candidates}` — promoted from an event ride-along; real correlation replaces the hand-rolled `request_id` (kit 2.4, adopted) |
| `edit.resync` | C→ | `{id, session}` → the reseed (fresh full text, seq 0) — "swallow deltas until reseed" becomes "while my request is outstanding" (kit 5.1, adopted) |

**Notifications, Emacs → companion:** `surface.update` (revision-guarded
idempotence *is* the ack — deliberately not a request), `surface.remove`,
`theme.set`, `toast.show`, `pie_menu.show`, `pie_menu.dismiss`,
`diagnostics.show`, `eldoc.show`, `fontify.show`, `rpc.cancel`.

**Notifications, companion → Emacs:** `event.action` (taps,
`trigger.fired`, `view.switched` — payloads of one method, not methods),
`state.changed` (`{id, value, surface?}`), `edit.open`, `edit.delta`,
`edit.caret`, `edit.close` (promoted to first-class methods from
event-riders; they are protocol, not user intents — kit 2.4), `log.error`,
`rpc.cancel`.

**Dropped without replacement:** `ping`/`pong` (no written semantics
existed; liveness, if ever needed, is a trivial self-correlating request or
transport keepalive).

## 5. Carried unchanged (incorporated by reference)

From SPEC.md 1.0-rc as amended through #22, everything below the envelope:
§4 surfaces (revisions, multi-view, `stale_after_s`/`stale_spec` semantics),
§5 events (allowlist, builtins incl. `trigger.fire`, the action-object
growth rule and its cosmetic/rate-shaping/constraining law), §6 queue
(policies, dedupe, `ttl_s`, absorb→push→replay ordering), §7 chrome (with
the palette roles), §8 editor sync semantics (offsets, seq, the
missing-feature-never-wrong-edit invariant — legs re-homed per §4 above),
§9 widget vocabulary (the full grammar incl. the box-model universals),
§10 capabilities, §11 triggers (`when` gates, `on_fire`, `state.edge`,
`manual`, `trigger_unavailable`, revocation-while-armed). The negotiation
model is untouched: capability sets by request/grant, vocabularies by
announced presence, never a version handshake — the model LSP converged on
when it deleted its own (initialize.md:729-732).

## 6. What guided what

| decision | guide |
|---|---|
| capabilities-not-versions; property-level gating for constraining fields | LSP (and v1's own amendment #5) |
| null-result ≠ error; cancelled requests still conclude; reserved code ranges | LSP base protocol |
| client-owns-truth → welcome carries the input snapshot | LSP `didOpen` ownership + LiveView form recovery (v1 #16) |
| whole-snapshot surfaces + reserved keyed-list splice; closed effects vocabulary someday | LiveView (streams, JS commands) |
| explicit-signal fail-closed dispatcher; -32601 hand-rolled; 32000/-1 landmines; outbound-data stash | jsonrpc.el v1.0.29, read not remembered |
| manual/`state.edge`/`trigger_unavailable`; history & availability discipline | Easer + Termux harvests (v1 #19–#22) |

## 7. Owner's open decisions (the hand line decides; the slop line only drafts)

1. Domain-tag retag `ebp1:` → `ebp2:` at the envelope swap, or keep (v1 #11
   pattern either way).
2. `rpc.cancel` as drafted vs keeping a semantic `dialog.dismiss` alias.
3. The 1200-range numbering (this draft's invention — renumber freely).
4. Whether `edit.*` promotion ships in the first rebuild cut or after the
   §8 katas.
5. Contract shape for v2 (method table + direction + request/notification
   classification as machine artifact — contract_format 5 territory).

The kit's §4 learning ladder and four katas remain the hand line's entry
path; kata 4 (hello/challenge with a refuse-everything dispatcher) lands
you at exactly §3 of this draft, which is the first thing worth checking
your hand-written version against.
