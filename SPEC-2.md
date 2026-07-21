# EBP 2 — the Emacs Bridge Protocol on JSON-RPC 2.0 (draft)

Spec: **2.0-draft** · Protocol: **2** · Contract: **format 5**

**Status: the slop line, now self-contained.** This is the Claude-drafted
reference rebuild, living on `ebp/slop-fork` — the slop-fork
convention: an LLM-written twin, deliberately labeled,
kept as the quarry and the checking copy. **The owner's hand-written
spec is the real line and supersedes this document wherever they
diverge.** Envelope drafted 2026-07-18 from SPEC.md 1.0-rc-as-amended,
decision #2 of the rebuild decision log,
`slop-docs/JSONRPC-conversion-kit.md` (facts verified against jsonrpc.el
v1.0.29), the LSP 3.18 precedent survey, and the LiveView harvest.
Folded to a full standalone spec 2026-07-19 (SPEC-CHANGES #28): §§6–14
carry the v1 constitution — surfaces, events, queue, chrome, editor
sync, widgets, capabilities, triggers, conformance — re-homed on this
envelope, from SPEC.md as amended through #26.

**Fold ground rules.** Wire-visible names follow the format-5 contract
and the running reference (so this document, its machine artifact, and
its checking copies agree with each other); v1 amendments whose prose
outran the reference are carried in full but inventoried in §14's
*Reference status* — the #26 convention, made explicit instead of
sprinkled. The v1 document (SPEC.md, its amendment log) remains beside
this one as the protocol-1 line; nothing here edits it.

**Freeze surface and amendment policy** carry from v1: the envelope
(§2), handshake (§3), and the semantics of surfaces (§6), the
semantic-action boundary (§7), and the offline queue (§8) are frozen —
changing any is an amendment in [SPEC-CHANGES.md](SPEC-CHANGES.md), and
a breaking change bumps the protocol version. §§9–13 are negotiated or
optional and grow additively; the widget vocabulary (§11) grows through
`node_types` negotiation (§3) — a new node type is *not* a version
bump. No entry, no amendment.

## 1. Roles, transport, and the layer stack

- The **companion is the durable server**: it listens, survives Emacs
  restarts, caches the last-known UI, and queues user actions while
  Emacs is away.
- **Emacs is the client**: it dials in — the same inversion
  `emacsclient` uses on the desktop, because on Android the OS
  routinely pauses Emacs and kills its sockets. (Protocol roles and
  transport roles are distinct: whichever side dials, Emacs remains the
  EBP client — the sender of `session.hello`.)
- v0 transport: loopback TCP `127.0.0.1:8765`. The 1.0 target is a Unix
  domain socket in a shared-signature directory. Only the connection
  bootstrap changes; every layer above the socket is transport-agnostic.

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

**The frame cap.** A frame's body may not exceed **4 MiB** (this draft's
default; negotiating per-side caps at the handshake is §16 decision 6).
The cap is enforced twice, and the two halves are different rules:

- *Sender side:* a frame that would exceed the cap is refused locally —
  dropped with a local log, never sent. An implementation that can shrink
  the frame (paginate a list, elide a subtree) should; one that cannot
  must prefer a missing update to an oversized frame.
- *Receiver side:* `Content-Length` framing makes an oversized frame
  skippable — read the header, discard exactly N bytes, report
  `1400 frame-too-large` on the `log.error` channel (§2.3), and keep the
  connection. Newline framing could not skip without scanning every byte;
  this cheap refusal is one of the dividends of renting the framing.
  The discarded frame is never parsed, so nothing it contained can be
  answered: an oversized *request* dies unanswered on the receiver side,
  which is why the sender-side half is normative and not advice.

Unbounded buffering of a frame body is the resource shape of failing
open; a conforming receiver never does it (§5).

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
- **Unsolicited faults** (a receiver problem outside any request — a
  malformed notification, an oversized frame that could not be parsed,
  overload) ride a `log.error` notification whose params are an error
  object minus the id: `{code, message, data?}`. The bare error frame is
  not resurrected (kit 5.3, adopted). Primarily companion → Emacs; either
  side may send it, and a receiver must at minimum log it.
- **Cancellation.** `rpc.cancel {id}` (notification, either direction) asks
  the peer to abandon the outstanding request `id`; the peer still answers
  it, with error code `1301 request-cancelled` — a cancelled request is
  concluded, never left dangling (LSP `$/cancelRequest` + its
  cancellation-still-responds rule, adopted). The v1 `dialog.dismiss` kind
  dissolves into this: dismissing a dialog is cancelling its `dialog.show`
  request (target semantics — see §4's staging note for the first cut).

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
| 1400 | `frame-too-large` (+ `bytes`, `max`) | §2.2's receiver-side refusal; rides `log.error` (the frame was never parsed, so there is no id to answer) |
| 1401 | `overloaded` | §5's bounded-queue exhaustion; rides `log.error`, then the connection closes |

Growing this table is an ordinary amendment; the machine copy lives in the
contract (v1 amendment #25's `error_codes` — the git log's "#22" — landed
here in codes+kinds form). Draft decision, flagged: v1's three handshake
refusals map to 1200-range codes rather than staying string-only — a
clean-room companion should learn every code from the contract, not from
prose.

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

## 3. Handshake and pairing auth

Two request/response pairs replace v1's four kinds; the challenge and the
welcome become *responses*, which makes ordering structural:

```
C→  session.hello   {protocol, client, wants, features?}   →  {nonce}
C→  auth.response   {nonce, mac}                           →  the welcome
```

The welcome (the treaty) is `auth.response`'s result:
`{server_proof, granted, node_types, surfaces, queued_events,
input_state?, can_disable?, device?, protocol?, server?}`. Its optional
`protocol` (the companion's wire version) and `server` (an
implementation/version string, mirroring `hello`'s `client`) are
informational — for logging skew, never gated on.

- **Pairing token.** The companion generates a secret token shown once in
  its pairing UI; the user copies it into their Emacs init. The token
  itself never crosses the wire.
- **Mutual proof (HMAC-SHA256, lowercase hex, keyed by the token):**
  - client `mac`  = `HMAC(token, "ebp1:client:" + SNONCE + ":" + CNONCE)`
  - `server_proof` = `HMAC(token, "ebp1:server:" + CNONCE + ":" + SNONCE)`
  - Nonces need uniqueness, not secrecy. Both sides fail closed: a wrong
    client mac is refused (`1203 auth-failed`) before any state is
    trusted; a missing or wrong `server_proof` makes the client drop the
    connection (a rogue app squatting the port cannot impersonate the
    companion). The `ebp1:` domain tags carry from v1 pending §16
    decision 1.
- **The fail-closed dispatcher rule (normative, sharpened by the
  jsonrpc.el findings):** until `auth.response` succeeds, the dispatcher
  answers *every* other request with `1200 not-authenticated` and drops
  every notification — **by explicitly signalling**, because the
  library's default answers unhandled requests with success-shaped
  `null`. Fail-closed is written in your dispatcher or it is not real.
- **Capability negotiation.** `wants` is the capability set the client
  requests; the companion grants the intersection with what it supports
  (`granted` in the welcome). Unrecognised capabilities are silently not
  granted. Capability names: `surfaces.widget`, `surfaces.notification`,
  `surfaces.dialog`, `capabilities`, `triggers`, `queue.replay`,
  `theme`, `reminders.owner`.
- **Node vocabulary.** `node_types` is the flat list of widget node `t`
  discriminators (§11) this companion renders — always present, since
  serving `app:*` surfaces is core rather than a negotiated capability. A
  client SHOULD gate a node it cannot assume is universal against this
  list and render a fallback when absent, exactly as it filters triggers
  against `device.trigger_types`. A client that receives *no* `node_types`
  (an older companion) treats every node as supported — negotiation is
  positive knowledge, never a denylist. This is the companion-side half of
  the §11 forward-compat rule: unknown nodes never crash, and `node_types`
  lets the client avoid emitting an invisible one in the first place.
- **Build-feature report.** `features` is the flat list of optional
  compile-time features the client's Emacs binary actually has
  (`sqlite`, `treesit`, `native-comp`, `libxml`) — positive knowledge,
  since a version floor is not a build guarantee. Additive and purely
  informational: the companion never gates on it (like the `client`
  string, it exists so build skew shows up in logs the way version skew
  already does), and a companion that predates the field ignores it.
  Like all wire vocabulary it is negotiated by presence, not
  version-gated — mirror of the `node_types` rule.
- **Revision snapshot.** `surfaces` maps each cached surface id to the
  revision the companion holds, so a client whose revision counter was
  lost (fresh machine, deleted state) can raise it above the cache floor
  before pushing. `queued_events` is the number of offline events waiting
  for replay.
- **Input snapshot** *(v1 #19 — see Reference status, §14)*. The
  optional `input_state` maps each surface to the widget values the
  user changed while disconnected — `{surface: {id: value}}`, latest
  value only, no history (the §10 resync philosophy applied to widgets:
  after a gap, re-send current state, never a keystroke log). It rides
  the welcome so the ordering is structural: the client holds it before
  it can push anything (§8). A companion with nothing to report omits
  it; a client that predates it ignores it — exactly the pre-amendment
  behavior, where offline drafts were lost.
- **Control disabling** *(v1 #21 — see Reference status, §14)*. A
  welcome carrying `can_disable: true` declares that this companion
  honors §11's `enabled` key. The client rule is skip-don't-emit:
  toward a welcome without it, a client must omit `enabled`
  everywhere — and when the disabled state is load-bearing, omit the
  control's action instead, since an action-less control renders inert
  on every companion. This is the §7 growth rule's constraining-key
  pattern in action: `enabled` ships with its own channel because an
  old companion that ignored it would leave the control live.
- **Device report.** When `capabilities` or `triggers` is granted, the
  welcome carries a `device` object — the invocable capability names,
  the device permission map, and the trigger/state catalogs. See §12.

### Versioning

Two independent version numbers, deliberately not conflated:

- **Protocol version** (`protocol` offered in `session.hello`, this
  document's major) — the wire contract. Bumped only on a wire-breaking
  change; the JSON-RPC envelope swap is exactly such a bump (1 → 2).
  A companion refuses a mismatched hello with `1202 proto-version`.
- **API version** — the client library's Tier 1 surface (the Elisp
  constructors and seams; semver, owned by the client library — the
  contract mirrors the reference client's as the informational
  `reference_api_version`). Carried informationally in `hello`'s
  `client` string (`emacs/30.1 my-client/2.0.0`) for logging skew.
  A companion never gates on it — the API surface is a client-side
  concern.

Node-vocabulary growth is **not** a protocol bump: new node types are
additive and negotiated per-connection (§3 capability set + the
welcome's `node_types`, §11), so an old companion and a new client
interoperate by each side ignoring what it doesn't know.

## 4. The method table (all of v1's 29 kinds accounted for)

Direction: C→ = Emacs sends; K→ = companion sends.

**Requests:**

| method | dir | params → result |
|---|---|---|
| `session.hello` | C→ | see §3 |
| `auth.response` | C→ | see §3 |
| `capability.invoke` | C→ | `{cap, args?}` → `{result?}`; typed errors 1001–1003. Carries the whole §12 catalog incl. `state.get` and `trigger.fire` |
| `queue.replay` | C→ | `{}` → `{delivered, expired, duplicate_request?}` — the drain summary is the response; v1's `queue.drained` dissolves |
| `dialog.show` | C→ | node-tree spec → **the user's answer** — v1's never-specified `prompt.reply` dissolves; stacked prompts are simply multiple outstanding requests |
| `triggers.set` | C→ | `{triggers}` → `{}`; wholesale rejection = error 1101, typed at last |
| `reminders.set` | C→ | `{reminders, owner?}` → `{}` — promoted so acceptance is typed |
| `edit.complete` | K→ | `{file, session, seq, cursor}` → `{prefix, candidates}` — promoted from an event ride-along; real correlation replaces the hand-rolled `request_id` (kit 2.4, adopted) |
| `edit.resync` | C→ | `{id, session}` → the reseed (fresh full text, seq 0) — "swallow deltas until reseed" becomes "while my request is outstanding" (kit 5.1, adopted) |

**Notifications, Emacs → companion:** `surface.update` (revision-guarded
idempotence *is* the ack — deliberately not a request), `surface.remove`,
`theme.set`, `toast.show`, `pie_menu.show`, `pie_menu.dismiss`,
`diagnostics.show`, `eldoc.show`, `fontify.show`, `edit.apply` (the §10
client→editor splice — omitted from this table's first draft, restored:
it is a leg of the §10 sub-protocol), `rpc.cancel`.

**Notifications, companion → Emacs:** `event.action` (taps,
`trigger.fired`, `view.switched` — payloads of one method, not methods),
`state.changed` (`{id, value, surface?}`), `edit.open`, `edit.delta`,
`edit.caret`, `edit.close` (promoted to first-class methods from
event-riders; they are protocol, not user intents — kit 2.4), `log.error`,
`rpc.cancel`.

**Dropped without replacement:** `ping`/`pong` (no written semantics
existed; liveness, if ever needed, is a trivial self-correlating request or
transport keepalive).

### First-cut staging (reference status, 2026-07-19)

The slop reference implements the envelope swap in two cuts, and this
table is the *target*; what the first cut actually wires differs in three
deliberate places, each an upgrade above the envelope that deserves its
own change:

1. `dialog.show` ships as a **notification** (node-tree params), and
   `dialog.dismiss` survives as a notification beside `rpc.cancel`; dialog
   answers keep riding `event.action` with the v1 prompt-correlation
   vocabulary (§9). The promotion to request-with-answer lands with the
   prompt-bridge rework (§16 decision 2).
2. The `edit.*` legs stay §7 event-riders and `completions.show` stays a
   C→ notification carrying its hand-rolled `request_id` (§16 decision 4
   resolved as "after the editor katas" for the first cut).
3. `edit.resync` ships as a notification (kit 5.1's request-with-reseed
   variant waits for the same katas).

Everything else is first-cut scope and wired: the §§1–3 shapes, framing,
frame cap, dispatch rules, error objects, and two-request handshake, the
§5 overload rules, and the remaining method table as printed —
`reminders.set` and `triggers.set` included, promoted to requests.

## 5. Overload behavior

Any two programs joined by a pipe run at different speeds, and something
must absorb the difference: a buffer grows, data is dropped, or the
producer slows. TCP's flow control only defends the middle option-1
territory — it counts bytes, kicks in megabytes late, and is blind to
which frames still matter. The right overload behavior depends on the
*semantics* of the traffic, which is exactly why the spec must assign it:
undefined overload behavior always resolves to an accidental buffer or an
accidental drop at 3 a.m. This section assigns it. The wire has three
traffic classes, one rule each, plus two bounded-resource rules that
apply everywhere.

**1. Latest-wins traffic conflates.** `surface.update`, `theme.set`, and
the seq-stamped annotations (`diagnostics.show`, `eldoc.show`,
`fontify.show`) describe *current state*: a newer frame makes older ones
worthless, officially — surfaces by the §6 revision guard, annotations by
their §10 seq discard, the theme by replacement. So the overload response
is to drop obsolete frames, and it is provably harmless:

- *Sender:* at most one queued frame per conflation key (the surface id;
  the annotation's editor id; the theme). If state changes again while a
  frame waits, **replace** the queued frame — coalesce to latest, never
  queue a second.
- *Receiver:* a queued-but-unprocessed frame is discarded, unparsed where
  framing allows, when a newer frame with the same key arrives.

This is a conflated queue — obsolescence as backpressure, purchased by
the revision-guard decision. v1 §8's seq-stamped annotations used the
pattern without generalizing it; here it is doctrine.

**2. Ordered traffic never conflates.** The editor legs (`edit.open`,
`edit.delta`, `edit.caret`, `edit.close`, `edit.apply`) are
order-dependent: dropping one corrupts everything after it. Their
overload story is the one they were born with: deltas travel at human
speed, a gap or length mismatch trips the §10 seq check, and one
`edit.resync` reseeds. Conflating this class is a conformance violation.

**3. Event traffic throttles at the source and dedupes in the queue.**
`event.action` and `state.changed` carry user intent; none may be
invented or reordered, and §7's flush-before-dispatch rule stands under
any load. Rate-shaping is already in the vocabulary: `throttle_s` limits
at the source, `dedupe` collapses queued repeats, `ttl_s` expires stale
intent. Named here as the third class so no implementer mistakes events
for conflatable state.

**4. No unbounded buffering.** A conforming receiver bounds its inbound
queue. Conflation makes latest-wins traffic occupy at most one slot per
key, so a bounded queue starves only when a peer floods the classes that
may not be dropped; a receiver that exhausts its bound reports
`1401 overloaded` on `log.error` and closes the connection — outstanding
requests die with it, cleanly, per §2.3. Failing closed at the connection
level beats failing open at the process level. The frame cap (§2.2) is
the same rule at single-frame granularity.

**5. The free lag gauge.** Every `event.action` carries `revision_seen` —
designed for staleness detection, it moonlights as backpressure telemetry
at zero wire cost: when `revision_seen` persistently trails the sender's
latest pushed revision for that surface, the receiver is drowning, and
the sender SHOULD stretch its coalescing window (rule 1) until the gauge
recovers. No new field, no control frames — the wire already says how far
behind the screen is.

## 6. Surfaces

A *surface* is a named, cacheable UI target. The id namespace tells the
companion where it renders:

| id pattern       | renders as                              | capability              |
|------------------|------------------------------------------|-------------------------|
| `app:*`          | full-screen in-app UI                    | core                    |
| `notification:*` | system notification                      | `surfaces.notification` |
| `widget:*`       | home-screen widget                       | `surfaces.widget`       |

```
surface.update   {surface, revision, spec, ttl_s?, stale_spec?, current_view?}   notification
surface.remove   {surface}                                                       notification
```

- **Revisions are monotonically increasing per client** and persist across
  restarts; the companion rejects a non-newer revision for a cached
  surface. This makes updates idempotent and replay-safe — and it is why
  `surface.update` is deliberately a notification: revision-guarded
  idempotence *is* the acknowledgement (§4), and the same guard is what
  §5 rule 1 cashes in as conflation. A refused update that is malformed
  (rather than merely stale) is reported on `log.error` with
  `1201 spec-invalid`; a stale revision is a silent, benign no-op.
- The companion **persists the latest spec** per surface and renders it
  while Emacs is disconnected (that is the offline story).
- **Staleness is presentation (SHOULD).** `ttl_s` and `stale_spec` let
  the cached render admit its age: once `ttl_s` seconds have passed
  since the surface's last update, the companion SHOULD render it
  visibly stale (dimmed, marked — the treatment is the companion's
  own), and if `stale_spec` is present render it in place of the cached
  `spec` (the whole spec — a multi-view surface's `views` included).
  Actions inside a `stale_spec` are live and queue as normal: a stale
  screen that can still capture is the point of the offline story. An
  absent `ttl_s` means never mark stale. Staleness is never a
  correctness boundary — that job belongs to `revision_seen` (§7) — and
  an author must not use `stale_spec` to remove dangerous controls,
  because an old companion will not honor the removal. *(v1 #18 renames
  this field `stale_after_s` and re-bases the clock on time-disconnected
  rather than time-since-update, with persistence across process death
  and clearing at the welcome; both halves land here when the reference
  follows — Reference status, §14. Until then the name `ttl_s` is shared
  with §7's unrelated queue-expiry policy, the collision #18 exists to
  end.)*
- **Multi-view surfaces.** A spec of the shape
  `{views: {name: viewSpec, ...}, initial_view: name}` ships several named
  views at once; the companion switches between them locally via the
  `view.switch` builtin, so navigation never round-trips. `current_view`
  on the update forces the companion onto a view — used only when the push
  *is* the navigation; background refreshes must never yank the user.
- **Widget surfaces.** A `widget:*` spec (or each of its views) carries
  `title`, `items` (rows of the home-widget row schema, emitted by the
  reference client's widget-item / widget-divider constructors), and
  optional `empty` (the no-rows caption).
  One **top-level** key — a sibling of `views`/`initial_view`, since
  chrome is view-independent — is `header_action`: an ordinary §7 action
  object rendered as the widget header's "+" button. Tapping it opens
  the app with the action embedded (header actions are for flows that
  need the visible app, e.g. a capture dialog needs a keyboard); the
  object dispatches verbatim, `when_offline` included. Absent, the
  button is hidden. The companion hardcodes no header action of its own.

## 7. Events: the semantic-action boundary

User interactions reach the client as notifications:

```
event.action    {action, args?, surface?, revision_seen?, fields?, queued_at?}
state.changed   {id, value, surface?}
```

`surface` and `revision_seen` are the context the interaction happened
in (which surface, at which cached revision — and `revision_seen`
doubles as §5's lag gauge); `queued_at` (epoch ms) is
stamped onto events delivered from the offline queue (§8) and absent on
live ones; `fields` carries values a companion collected as part of the
interaction — presently only an inline-reply notification action's typed
text as `{key: text}` (§11) — and is `null` when the interaction gathered
none. The
`when_offline`/`dedupe`/`ttl_s`/`confirm` fields an author writes on an
action object (below) are author-side policy: the companion consumes
the queue trio when the event is queued, carries `confirm` without ever
interpreting it, and echoes none of them in the delivered frame.

**Action-object growth (normative).** A companion **ignores unknown
keys on an action object** and echoes none of them — whatever an
author writes there, the delivered `event.action` shape stays exactly
the contract's `event.action` params shape. (This codifies the
tolerance `confirm` already leaned on, v1 amendment #13.) The license
is deliberately narrow:
a key added this way must be *cosmetic* (ignoring it costs polish,
like §11's `badge`) or *rate-shaping* (ignoring it changes timing,
never what happens). A **constraining** key — one an old companion
would over-act by ignoring — must never ride as a plain key: it ships
only together with its own positive-knowledge report in the welcome,
at whatever granularity the field needs (as `when` shipped with
`device.state_types`, v1 amendment #5), plus the client rule to skip
emitting it toward a companion that does not report it. The §13
`when`-strip rationale is the template: a silently weakened intent is
worse than a skipped feature.

**The allowlist principle (normative).** An `action` is a *name* the
client explicitly registered a handler for; `args` are plain data the
handler validates. The wire must never carry code, command names to
funcall, file paths outside the client's own guards, or anything else
that turns the companion into a remote eval. A client receiving an action
with no registered handler logs and drops it. The single sanctioned
escape hatch is an M-x–style action whose handler runs the client's own
interactive command dispatch *with its prompts bridged to the user* — the
user, not the wire, chooses the command.

Actions are dot-namespaced `noun.verb` (`heading.todo-set`,
`files.rename`, `packages.install`). Namespaces belong to the module that
registers the handler; the core reserves `nav.*`, `view.*`,
`dialog.*`, `edit.*`, `tablist.*`, `settings.*`, `prompt.*`,
`dashboard.*`, `files.*`, `emacs.*`, `packages.*`, `customize.*`,
`transient.*`, `share.*`, `demo.*`, `witheditor.*`, `comint.*`,
`imenu.*`, `tools.*`, `trigger.*` (device-trigger fires, §13), `app.*`
(launcher app switching), `device.*` (device-effector UI: the
app-launch picker, the permissions screen). An implementation's own
modules claim their namespaces like any other module — the core
reserves no brand.

- `when_offline` is the queue policy the *spec author* chose for the
  control: `"queue"` (default — persist and replay), `"drop"` (meaningless
  later, e.g. navigation), `"wake"` (try to start Emacs, then queue).
- `dedupe`: a queued action replaces any queued action with the same
  dedupe key (e.g. repeated saves of one file collapse to the last).
- `ttl_s`: seconds after which a *queued* action expires unreplayed —
  stale intent the user would no longer recognize is dropped at replay
  time and counted in the drain summary (§8).
- `confirm` (since 1.23.0) is a prompt string gating the *client's*
  dispatch: shown as a native yes/no dialog (via the client's own
  prompt bridge) before the handler runs — declining is a clean no-op,
  and a queued tap (§8) confirms at replay. Companion-opaque and never
  echoed in `event.action`, so a client must resolve the prompt from
  its own state — the reference client indexes `confirm` by action
  name + args when it builds the descriptor — never from the
  delivered frame.
- `state.changed` carries widget state (text as typed, switch flips,
  multi-select values) keyed by widget `id`; the client mirrors these into
  a UI-state store its handlers read back. It is not an action and runs no
  handler-side effects beyond per-id subscriptions. An optional
  `surface` names the surface the widget lives on, so ids need be
  unique only per surface; when absent the client treats `id` as
  global — the shape the reference companion still emits.
- **Flush-before-dispatch (normative, since 1.25.0).** A companion that
  debounces `state.changed` publishing (typing pauses) must flush every
  diverged stateful-node value — as ordinary `state.changed` events, in
  the same delivery order — *before* it delivers any `event.action`. A
  handler that reads the UI-state store therefore never observes a value
  staler than the interaction that invoked it — and §5 rule 3 makes this
  explicitly load-invariant: no overload response may reorder the event
  channel. A companion that publishes
  un-debounced satisfies this trivially; a pre-1.25.0 companion may
  deliver an action ahead of a pending debounce, which clients tolerated
  with grace-waits.

**Companion-local builtins.** An action object with `builtin` instead of
`action` is handled on-device and works with Emacs dead:
`{"builtin": "view.switch", "view": v}` (flips a multi-view surface, then
informs the client with a drop-policy `view.switched` event),
`{"builtin": "clipboard.copy", "text": s}`,
`{"builtin": "share.send", "text": s, "title"?: t}` (the system share
sheet; `title` is the subject where the receiving app supports one),
`{"builtin": "companion.settings.open"}` (opens the companion's own
settings surface: permissions, notifications, offline state, pairing,
and diagnostics),
and `{"builtin": "trigger.fire", "id": t}` — fires the §13 `manual`
registration named `id` through the full trigger pipeline (gate,
throttle, `on_fire`, event/queue) with fire data `{source: "tap"}`.
One letter from `trigger.fired`, deliberately: the builtin is the
cause a user taps; the `trigger.fired` event is the effect the client
receives. This is what lets home-screen shortcuts, QS tiles, and
notification buttons fire automations with Emacs dead — `shortcut.pin`
(§12) is its natural partner.

## 8. Offline queue

While disconnected the companion persists queue-policy events. After the
welcome, the client sends the `queue.replay` request; the companion
streams the queued `event.action` / `state.changed` notifications in
order and concludes the request with the drain summary as its result:

```
C→  queue.replay   {}   →   {delivered, expired, duplicate_request?}
```

`expired` counts events dropped for outliving their `ttl_s` (§7);
`duplicate_request: true` marks the answer to a replay requested while
one was already in flight (that answer reports zeros and the original
request still concludes with the real summary). A connection death
mid-replay leaves the undelivered remainder queued for the next
session — the outstanding request dies with the connection (§2.3), and
each event is deleted only after its frame was written.

The client should request replay only after it has (1) absorbed the
welcome — the revision snapshot *and*, when present, `input_state`
(§3), mirrored into the UI-state store — and (2) pushed initial
surfaces, which SHOULD reflect absorbed draft values in their input
nodes' `value` keys, so a reconnect push does not wipe an on-device
draft. Replayed events then land on coherent state: a replayed action's
handler reads the store the user actually typed into. Re-push after the
drain (replayed events usually mutated state the cached views no longer
reflect).

## 9. Dialogs, toasts, pies, reminders

| method                            | class | body                                                | capability |
|-----------------------------------|-------|-----------------------------------------------------|------------|
| `dialog.show` / `dialog.dismiss`  | notification (first cut — the §4 target promotes `dialog.show` to a request whose result is the user's answer) | a UI-tree spec rendered modally | `surfaces.dialog` |
| `toast.show`                      | notification | `{text}` transient toast                     | optional |
| `pie_menu.show` / `.dismiss`      | notification | radial menu spec (curated, ≤ ~10 items)      | optional |
| `reminders.set`                   | request → `{}` | `{owner?, reminders: [{id, title, body, at_ms}]}` — **replaces** only `owner`'s set (blank/absent = the unowned bucket), so cancelled items never fire stale and coexisting apps never cancel each other; the companion persists each owner's set across reboots | `reminders.owner` for scoping |
| `theme.set`                       | notification | `{dark, colors, syntax}` to mirror the client's theme, or `{base}` (no `colors`) to force one of the companion's own schemes | `theme` |

**Theme palette roles.** `theme.set`'s `colors` maps Material scheme
role names to hex — the reference client pushes `primary`,
`on_primary`, `primary_container`, `on_primary_container`, the same
quartet for `secondary`, `tertiary`, and `error`, plus `background`,
`on_background`, `surface`, `on_surface`, `surface_variant`,
`on_surface_variant`, and `outline`. The palette may also carry
`success` and `warning`; a companion whose pushed palette lacks them
falls back to its built-in pair. These role names are the color
vocabulary §11 accepts wherever a color is authored.

A `dialog.show` spec's **root node** may carry `dialog_style`:
`"sheet"` / `"sheet_full"` render the same tree as a modal bottom sheet
(collapsed / fully expanded — the native idiom for pickers and action
menus); anything else, or its absence, keeps the centered dialog window.
Additive: an old companion ignores the key and centers the dialog. The
reference client sets it per-call (its dialog command's STYLE argument)
or globally (a client option).

**Owner-scoped reminders.** `reminders.set` carries an optional `owner` (an
app-id string). The companion partitions armed alarms by owner, so a set
replaces only that owner's previous alarms; a blank/absent `owner` is the
unowned/core bucket, and request codes are hashed with the owner so distinct
apps never collide. This lets two Tier 1 apps arm reminders without one's
set cancelling the other's — a bare owner-less set could not. A companion
advertising the `reminders.owner` capability is owner-aware: the
reference client sends the scoped set only when it is granted,
and otherwise degrades — a plain global set when only one app is registered,
else it warns and arms nothing rather than clobber another app. Additive: an
old companion ignores `owner` (treating every set as the one global set).
As a request, acceptance is the empty result and a rejection is typed —
the fire-and-forget arm that could fail silently is gone.

`theme.set` lets the client's theme win over the companion's own scheme
(Material You, or its static fallback). `colors` maps Material color-role
names — the same snake_case tokens §11 nodes use (`primary`,
`surface_variant`, `on_primary_container`, …) — to `#rrggbb` strings;
`syntax` maps editor token names (`comment`, `keyword`, `heading` /
`paren` as arrays, …) the same way; `dark` declares the theme's polarity,
which overrides the device's day/night setting while mirroring. Every key
is optional — the companion fills holes from its fallback scheme. Each
push replaces the last and is persisted like a cached surface (the phone
keeps the client's look while the client is away); `colors: null` clears
the mirror and the persisted palette. When a push carries no `colors`, an
optional `base` string instead selects which of the companion's *own*
schemes to force: `"material"` (Material You, where the device supports it)
or `"default"` (the companion's built-in scheme). This lets the client
drive a companion that isn't mirroring — the app's theme becomes a
three-way client choice (default / material / mirror-the-client) rather
than a device-only default. A companion that predates `base` sees a push
with no `colors`, treats it as the clear, and falls back to its own scheme
chain — so `base` degrades to "the companion decides."

The reference client extracts the palette from the running Emacs theme,
and its three-way theme-mode option (`default` / `material`
/ `emacs`) drives exactly the above: `emacs` mirrors, the others send the
matching `base`. Mirroring leans on the modus-themes palette API when a
modus-family theme is active and on resolved face attributes otherwise.
"modus-family" is detected through `modus-themes-get-current-theme`, so it
covers not just the `modus-*` originals but anything built on the modus 5.0
derivative API (the ef-themes, standard-themes, third-party skins); the
client reads that theme's *semantic* palette roles (`accent-0`, `err`,
`prose-todo`, `fg-heading-N`, …) with the user's palette overrides applied,
which keeps the mirror faithful across derivatives and the deuteranopia/
tritanopia color-vision variants.

The minibuffer bridge rides on dialogs: when a client action handler hits
a prompting call (`y-or-n-p`, `completing-read`, `read-passwd`,
`map-y-or-n-p`, raw event reads, …) it sends the prompt as a dialog and
blocks for the answering `prompt.reply` / `prompt.dismiss` action,
exactly as the original function would block for keyboard input. (This
`prompt_id`-correlated ride on `event.action` is the v1 vocabulary the
first cut keeps; under the §4 target it dissolves — the answer becomes
the `dialog.show` request's own result, and stacked prompts become
multiple outstanding requests.)

Editor-callback sessions (with-editor: commit messages, rebase todos)
ride on dialogs too, but asynchronously — the buffer appears after the
originating action handler has returned, so the client pushes an editor
dialog and later receives `witheditor.finish {buffer}` (splices the
edited message, runs `with-editor-finish`) or `witheditor.cancel
{buffer}`.  Both handlers validate that `buffer` names a live
with-editor session before acting — never arbitrary dispatch — and the
client should only bridge sessions plausibly initiated from the
companion (e.g. shortly after a dispatched action), so a desktop commit
never pops a dialog on the phone.

## 10. Editor sync sub-protocol (optional)

Turns the companion's text editor into a live client of Emacs — the basis
for completion, diagnostics, eldoc, and fontification. All offsets are
**Unicode code points** (= Emacs buffer positions; the companion converts
from its UTF-16 indices, so the client never does encoding math).

The companion → client legs are §7 *actions* riding `event.action`
notifications (they hit the same allowlist as every other interaction;
the §4 target promotes them to first-class methods — first-cut staging);
the client → companion legs are methods of their own, all
notifications. Offsets named `start`/`cursor` are code points; `seq`
stamps which delta state a message was computed against.

```
companion → client   event.action {action: "edit.open",     args: {file, session, text}}   seed / reseed (seq 0)
companion → client   event.action {action: "edit.delta",    args: {file, session, seq, start, del, text, len}}
companion → client   event.action {action: "edit.caret",    args: {file, session, seq, cursor, sel_start?, sel_end?}}
companion → client   event.action {action: "edit.close",    args: {file, session}}
companion → client   event.action {action: "edit.complete", args: {file, session, seq, request_id, cursor}}   pure query
companion → client   event.action {action: "edit.command",  args: {file, session, seq, cursor, sel_start?, sel_end?, command?}}
client → companion   completions.show {id, request_id, prefix, candidates: [{label, annotation?, insert?}]}
client → companion   diagnostics.show {id, session, seq, diags: [{beg, end, type, text}]}
client → companion   eldoc.show       {id, session, text}
client → companion   fontify.show     {id, session, seq, runs}
client → companion   edit.resync      {id, session}
client → companion   edit.apply       {id, session, seq, cursor, start?, del?, text?, len?, sel_start?, sel_end?}
```

In the client → companion methods `id` is the editor id (the synced
file); `seq` on `diagnostics.show`/`fontify.show` lets the companion
refuse to draw squiggles or highlights over text that has moved on —
the discard §5 rule 1 generalizes into conflation.

Deltas are `seq`-numbered and each carries the expected resulting length;
on any mismatch (dropped frame, client restart) the client marks the
session stale and sends one `edit.resync`, which the companion answers
with a fresh `edit.open`. Invariant: **wrong state can only ever cause a
missing feature, never a wrong edit** — the shadow never writes to disk,
and completion insertion happens companion-side. This channel is §5's
ordered class: nothing in it may be conflated, and this one-resync
recovery is its entire overload story.

**Point and region.** `edit.caret` may carry `sel_start`/`sel_end`
(present only when the companion's selection is non-collapsed;
`sel_start ≤ sel_end`, and `cursor` equals one of the two ends — the
client derives the mark as the other end). A matched caret report is the
client's licence to persist point/selection as *best-effort* session
context; it trails the companion's debounce, so anything that needs
exact coordinates carries them in its own frame instead.

**Commands at point (`edit.command`).** Runs a client-side command in
the session's buffer with real point and mark. The frame carries the
companion's exact `cursor` and selection; `command` names the command,
and an *omitted* `command` asks the client to prompt the user for one
through its bridged chooser (M-x scoped to the editor — the user, not
the wire, picks the command; same posture as §7's escape hatch). The
gate is `edit.complete`'s: session/seq must match the live sync state
exactly, else the client answers with one `edit.resync` and runs
nothing. Prompts raised by the command ride the client's ordinary
dialog bridge.

**Server-authored edits (`edit.apply`).** The reverse of `edit.delta`,
in two shapes distinguished by the splice keys:

- *Text-changing* — `start`/`del`/`text`/`len` present, same splice
  semantics as `edit.delta`; `seq` is the **new** sequence number (the
  client bumps its session seq when emitting, making the seq stream
  two-writer). The companion applies iff `seq` is exactly one past its
  own, **and** its current editor text still equals the last state it
  synced, **and** no IME composition is active — any failed gate drops
  the frame silently. A drop is safe by construction: the client and
  companion now disagree on seq, so the next delta round trips the
  ordinary resync recovery. A race with typing therefore loses the
  command's *result*, never corrupts text — the invariant above,
  extended to the reverse direction.
- *Move-only* — splice keys absent, `seq` unchanged (equals the
  companion's current): the command moved point or changed the region
  without editing. Same gates; `cursor`/`sel_start`/`sel_end` position
  the companion's caret and selection.

The companion should apply a text-changing frame as a single undoable
edit, so one command is one undo step — undoing it then emits an
ordinary `edit.delta` back, needing no special casing. `diagnostics.show`
and `fontify.show` frames that follow an apply are stamped with the new
seq.

A candidate's optional `insert` is what lands in the buffer when it
differs from the display `label` (a wikilink chip shows `[[Title` but
inserts `[[id:…][Title]]`). Candidates carrying `insert` were matched
by client-side rules of their own — a wikilink capf matches note
titles by **substring** — so the companion narrows them by
contains-prefix rather than the starts-with rule it applies to plain
code-completion candidates.

## 11. Widget vocabulary

Specs are trees of nodes; every node is `{"t": type, ...}` and unknown
keys must be ignored (forward compat). A node whose `t` a companion does
not recognise renders its `children` if it has any (a new container
degrades to a plain stack of its contents) or nothing if it is a leaf —
never a crash (§14). The welcome's `node_types` (§3) is the companion's
catalog of the `t` values it *does* render, so a client can gate a newer
node and emit a fallback rather than depend on this degradation. Actions embed as objects under
a node's action key — `on_tap`, `on_change`, `on_submit`, `on_save`,
`on_pick`, `on_reorder`, `on_refresh`, `nav_action`, `on_point_tap`,
`on_button`, and the rest (the full set is `action_hook_keys` in
[`contract.json`](contract.json)). Value-carrying callbacks
(`on_change`, `on_submit`, `on_save`, `on_pick`, `on_point_tap`) dispatch their
action with the widget's current value injected into `args` as `value` — a
switch's `on_change` arrives with `args.value` true/false, a text
input's `on_submit` with the text.

Declarative data-views (API 1.5.0) compile *on the client* to exactly these
nodes and actions. Their authoring grammar — `:spec` views, named sources,
closed template placeholders — is a local concern documented in the
reference client's
[BINDING.md](https://github.com/calebc42/jetpacs/blob/main/docs/BINDING.md),
**not** a wire addition; the compiled output obeys
this section and the §7 allowlist like any other node tree.

The normative, machine-checked reference for every node's wire shape is
[`goldens/widgets.golden`](goldens/widgets.golden) — one JSON line per
constructor, kept honest by the ERT suite.
[`contract.json`](contract.json) (contract_format 5) additionally
publishes the authored per-node key schema (`node_schema`: required and
optional keys per type, plus the `"*"` row of keys legal on any node)
and the JSON-RPC method table (`methods`: direction,
request/notification class, params and result keys per method, with
`error_codes` beside it) — the machine-readable form of this section
and of the method sketches in §§2–10, 12–13, consumed by all
conformance suites.

**Universal node attributes** *(the box-model set is v1 #20 — see
Reference status, §14)*. Beyond `key` (the lazy-list
reconciliation identity), `scroll_here`, and `dialog_style`, any node
may carry the box-model set: `pad` — per-side padding
`{start?, top?, end?, bottom?, horizontal?, vertical?}` in dp, a
specific side winning over its axis shorthand (the older per-node
scalar `padding` keeps its meaning; `pad` wins where both appear) —
`width`/`height`/`min_width`/`max_width`/`min_height`/`max_height`
(dp), `fill_fraction` (0–1 of the parent's width), `aspect_ratio`
(width ÷ height), `bg` (a color filled behind the node, clipped to its
corner shape), `corner` (dp, or `{tl, tr, bl, br}` per-corner — the one
shape that `bg`, `border`, and `clip` share; on `surface` a numeric
`corner` overrides the `shape` enum, whose `circle` has no corner
equivalent and survives), `border` (`{width, color}`), `alpha` (0–1
opacity), and `clip` (clip children to the corner shape). Application
order: corner → clip → bg → border. On a row/column child,
`align_self` (the parent's own `align` vocabulary) overrides
cross-axis placement, the way per-child `weight` already overrides its
share. All of these are cosmetic in the sense of §7's growth rule — a
companion that predates one renders the prior look, content intact —
with one authoring rule: never *hide* a load-bearing control with
`alpha`, because an older companion shows it at full strength.

**Color values.** Wherever this section accepts a color, the value is
a hex string (`#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`) or a **theme
role name** from the §9 palette (`primary`, `on_surface`,
`surface_variant`, `error`, `success`, `warning`, …). Roles follow the
live theme; hex is frozen ink — prefer roles. This supersedes the
older hex-only wording for `rich_text`/`table` span colors (pure
widening; hex stays valid).

Summary by family:

- **Content**: `text` (`style` — `body` (the default) / `title` /
  `headline` / `caption` / `label` / `mono`, unknown → `body`; plus
  `color`, `syntax`, `selectable`, `max_lines`), `rich_text` + styled
  `spans` (emphasis, `color`/`bg` overrides — any §11 color value; a
  span `bg` colors its own text run, distinct from the node-level
  `bg` — `mono`, tap links), `icon`, `image`, `date_stamp`, `divider`, `section_header`,
  `empty_state`, `progress` (`variant` `circular` (the default) /
  `linear`; a missing `value` renders indeterminate).
- **Layout**: `row`, `column` (both take `spacing` in dp between
  children; `align` for the cross axis — row `top`/`center`/`bottom`
  plus `baseline`, column `start`/`center`/`end` — and `arrange` for
  the main axis: `start`/`center`/`end`/`space_between`/
  `space_around`/`space_evenly`. An `arrange` other than `start`
  distributes the leftover space and takes precedence over `spacing`),
  `flow_row` (also takes `arrange`, and `align` for items within a
  wrapped run), `lazy_column` (takes `spacing` in dp between rows and
  `content_padding` — dp or a `pad` object — inside the scrollport; a
  child may
  carry `scroll_here: true` — the list scrolls to it on first show and
  whenever its index changes, e.g. a REPL input row pushed down by new
  output; an update that leaves the index unchanged never disturbs the
  user's scroll position. A child may also carry `key` — a stable
  string the companion prefers over the child's `id`, then position, as
  the child's reconciliation identity across pushes, so inserts,
  removals, and reorders preserve the row's client-side state, scroll
  anchoring, and item animation. Additive: an absent `key` and a
  companion that predates it both degrade to id/position keying),
  `box` (children stack in z-order; `alignment` places them — a
  compound of `top`/`center`/`bottom` × `start`/`center`/`end`, e.g.
  `top_start` (the default), `center`, `bottom_end`; an unknown value
  falls back to `top_start`), `surface`
  (tonal container; `shape` `rounded`/`rounded_small`/`circle`, absent
  → rectangular; author-set `color` and `elevation`), `card`, `spacer`,
  `collapsible` (folds on-device),
  `reorderable_list` (drag to reorder, reports via `on_reorder`),
  `card` additionally takes `swipe_start` / `swipe_end` — per-side swipe
  actions `{icon, label, color?, on_trigger}`: dragging reveals the
  side's icon/label, a full swipe dispatches `on_trigger` once and the
  card springs back (the server answers with the updated list); they
  supersede the legacy single-action `on_swipe`, and because an old
  companion renders no gesture, a swipe action must also be reachable
  by tap or menu. `tabs` — an intra-view tab row over swipeable pages:
  parallel `items` (`{label, icon?}`) and `children` (the pages),
  `initial` index, `scrollable` for many tabs, `pager_only` to drop the
  row for pure swipe-through content (e.g. flashcard review). Switching
  is companion-local (the `view.switch` philosophy); optional
  `on_change` dispatches with the settled page index injected as
  `value`. The user's page survives re-pushes; an optional `id` keys
  that state — a push carrying a new `id` resets to `initial` (a fresh
  flashcard lands on its question page). An additive node — negotiate
  via `node_types` (§3); a companion that predates it stacks the
  pages, so the documented fallback is a chip row plus the selected
  child.
  `table` (org-table grid: `rows` of span-bearing `cells`, plus `rule`
  rows for hlines and `header` rows rendered emphasized; per-column
  `aligns` of `start`/`center`/`end`; columns size to their widest cell
  and a wide grid pans horizontally on-device. Cells may carry
  `on_tap`/`on_long_tap`; `on_add_row`/`on_add_col` on the node make
  the client draw slim "+" append affordances below the last row /
  after the last column. All embedded actions dispatch verbatim — the
  server bakes file/position into the args, the client adds nothing).
- **Container sizing** (additive, all optional): `box`/`surface`/`card`
  accept `width`/`height` in dp, `fill_fraction` (0–1 of the parent's
  width), and `border` (`{width, color}`, stroked with the node's shape);
  `image` accepts `width`/`height`, `aspect_ratio`, and `content_scale`
  (`fit`/`crop`/`fill`). Absent keys preserve the prior behaviour. A
  fixed-column grid is composed as a `flow_row` of `width`- or
  `fill_fraction`-sized cells — there is no dedicated grid node.
- **Input**: `button` (`variant` — `filled` (the default) / `tonal` /
  `outlined` / `text`), `icon_button`, `chip`, `assist_chip`, `menu`,
  `checkbox` / `switch` (report every flip as `state.changed`; the
  optional `on_change` additionally dispatches with the new boolean
  injected as `value` — declared since format 2, dispatched by the
  reference companion since 1.25.0), `slider` (continuous value;
  `min`/`max` default 0/1, `steps` for discrete; dispatches `on_change`
  once on release with the value injected), `text_input` (optional `password` masks entry and
  requests a password keyboard — such values must not be logged or
  retained; optional `keyboard` picks the IME from the closed enum
  `number`/`decimal`/`email`/`phone`/`uri`, unknown or absent → text,
  `password` wins; optional `autofocus` — since 1.25.0 — grabs focus and
  raises the IME on first composition under a new `id`, same-id re-pushes
  never re-steal; optional `clear_on_submit` — since 1.25.0 — resets the
  field in place after the submit dispatch, preserving the composition
  and so focus and the keyboard, and reports the cleared value as
  `state.changed`), `enum_list` (single/multi select, optional free-add),
  `date_button` / `time_button` (native pickers),
  `editor` (full editor: save/undo header, optional `syntax`, gutter
  `line_numbers`, `complete` for the completion strip, `chromeless`,
  `publish_state`, optional `autofocus` — since 1.25.0, as on
  `text_input`; optional `on_enter` — since 1.25.0 — an action the IME's
  Enter dispatches with the full buffer injected as `value` INSTEAD of
  inserting a newline, the default keyboard-hide deliberately skipped so
  chained entry keeps the IME up (a literal newline still comes from a
  hardware Enter or a toolbar snippet); and a server-chosen `toolbar` — a
  string naming a host-registered native toolbar, or an array of
  data-driven toolbar items; see "Editor toolbars" below). Any node in
  this family may carry `enabled` (default true): false renders the
  platform disabled affordance and suppresses every dispatch from the
  control (`editor` keeps its own `read_only` instead). Negotiated by
  §3's `can_disable` — a client never emits it toward a companion that
  does not announce it *(v1 #21 — see Reference status, §14)*.
- **Visualization** (the ladder): `chart` — data-driven, the client emits
  `series` of `points` and picks a `kind` (`line`/`bar`/`area`/`sparkline`);
  the companion draws it animated and theme-coloured, dispatching
  `on_point_tap` with the tapped point. A closed enum on purpose — a need
  outside this shape belongs on `canvas`, not a new `chart` attribute.
  `canvas` — the escape hatch: `{width, height, ops}` where each op is a
  closed, data-only draw primitive (`line`/`rect`/`circle`/`path`/`text`)
  in the node's coordinate space. No animation, no interaction (those earn
  a curated primitive); unknown ops are skipped, never fatal.
  `month_grid` — the agenda calendar, the `chart` of time:
  `{month: "YYYY-MM", marks: {"YYYY-MM-DD": {dots, color?}, …},
  selected?, min_month?, max_month?, on_day_tap?, on_month_change?}`.
  Month navigation (chevrons, horizontal swipe) is companion-local and
  clamped to `min_month`/`max_month`; `on_month_change` dispatches with
  the newly shown month as `value` so the client can push fresh marks —
  marks for unfetched months are simply absent, never blocking.
  `on_day_tap` dispatches with the tapped ISO date as `value`; today is
  outlined, `selected` filled, up to 3 `dots` render under a day. A
  re-push with a different `month` adopts it; mark-only re-pushes leave
  the user's shown month alone. All three are additive nodes —
  negotiate via `node_types` (§3) and fall back (a `table`, or for
  `month_grid` a `flow_row` of `fill_fraction` day boxes) on a
  companion that predates them. Each may also carry `children` as the
  *authored* fallback subtree (since 1.23.0; the reference client's
  additive wrapper): by this section's opening rule an
  unrecognised `t` renders its children, so a pre-ladder companion
  shows the fallback while a current one renders the visualization
  and ignores the slot.
- **Chrome**: `scaffold` (top_bar / bottom_bar / fab / drawer / snackbar /
  pull-to-refresh), `top_bar`, `bottom_bar` + `nav_item`, `drawer` +
  `drawer_item`, `fab`. The scaffold's `snackbar` string may be
  accompanied by `snackbar_action` `{label, on_tap}` — an action button
  on the snackbar (the undo affordance) that dispatches only on a user
  tap, never on timeout; old companions show the plain message. A
  `badge` attribute on `nav_item` / `drawer_item` / `icon` /
  `icon_button` overlays a count (numbers cap at 99+ on-device; the
  empty string renders a bare attention dot) — cosmetic, never
  load-bearing, silently ignored by older companions.
- **Notification specs** add `meta` (channel, ongoing, category, priority,
  `chronometer: {base_ms}`) above a body of content nodes. `meta.actions`
  is an ordered array of action buttons rendered as the platform
  notification's own actions (the OS caps how many are shown — author the
  most important first). Each entry carries `label` (required) and
  `on_tap` (required — a §7 action object dispatched when the button is
  tapped), plus optional:
  - `icon` — a §11 icon name, best-effort. A companion maps it to a
    platform glyph; note that Android ≥ 7 does not draw action icons in
    the shade (label only), so never make the icon load-bearing. Absent
    or unresolvable → a default glyph.
  - `dismiss` — when true, tapping the button cancels the notification
    (the Done / Snooze affordance).
  - `input` — `{hint?, key?}`; turns the button into an inline text
    reply. The typed text rides back in the dispatched `event.action`'s
    `fields` as `{key: text}` (`key` defaults to `reply`), so the same
    action handler reads the reply from the payload. Pair it with
    `dismiss` to clear the notification once the reply is sent.

  `meta.actions` is additive — a companion that predates it ignores the
  unknown meta key and posts the notification with no action buttons; it
  never fails. (A `button` node placed directly in the body is still
  honored as an action when `meta.actions` is absent, the older implicit
  form.) The reference client emits these via its notification-action
  constructor / notification-spec `:actions`.

### Editor toolbars

`editor`'s `toolbar` attribute is **string | array**:

- **string** — the name of a host-registered native toolbar
  (the companion's native toolbar registry; the Kotlin-alternative path
  per the ladder doctrine, §11 visualization family). The library registers
  none; an unknown name renders nothing.
- **array of toolbar items** — the data-driven form. The companion
  interprets the items locally (`SduiToolbar`); every op is one minimal
  splice on the buffer = one undo step, no Emacs round-trip. Each item:

  | key | value |
  |---|---|
  | `icon` | icon name for the chip |
  | `label` | short chip label |
  | `snippet` | *op:* text to insert (placeholders below) |
  | `line` | *op:* builtin line op — `promote` \| `demote` \| `move-up` \| `move-down` |
  | `on_tap` | *op:* an ordinary §7 action object — the Emacs escape hatch |
  | `menu` | *op:* array of sub-items (`label` + exactly one of `snippet`/`line`/`on_tap`; menus don't nest) |
  | `placement` | optional, `snippet` only: `cursor` (default) \| `line-start` \| `block` |
  | `long_press` | optional secondary op: an object with exactly one of `snippet`/`line`/`on_tap` |

  Exactly **one** op field (`snippet`/`line`/`on_tap`/`menu`) per item
  (the reference client's linter enforces).

  **Snippet placeholders** (closed, companion-local):

  | token | behavior |
  |---|---|
  | `${selection}` | replaced by the current selection; the result stays selected. With an empty selection the cursor lands there — so `*${selection}*` reproduces both wrap-selection branches |
  | `${cursor}` | explicit final cursor position (wins over `${selection}`'s cursor rule) |
  | `${input:Prompt}` | one companion-local free-text dialog titled *Prompt*; the entry substitutes in (e.g. a src-block language). Preset choices are the app's `menu` items, not this |
  | `${date}` | `YYYY-MM-DD Day` (companion clock) |
  | `${time}` | `HH:MM` |

  Rules: unknown `${…}` tokens insert **literally** (visible, never
  fatal). `line-start` placement inserts at the start of the cursor's
  line and no-ops when the line already starts with the literal prefix
  (dedupe). `block` placement inserts the snippet on its own line(s),
  adding newlines around it as needed; without `${cursor}` the cursor
  lands after the block. A snippet without `${selection}` inserts at the
  cursor and leaves any selection's text alone.

  **Forward compat:** the array form is additive. An old companion that
  predates it treats the value as an unknown toolbar name and renders no
  toolbar; it never crashes. The reference client emits it via its
  toolbar-item constructor / editor `:toolbar` and lints it with its
  spec linter.

## 12. Device capabilities (optional)

The Emacs → device *effector* channel: the client invokes device-side
actions (open a settings panel, intents, flashlight, TTS, …).
Negotiated under the `capabilities` capability name.

```
C→  capability.invoke   {cap, args?}   →   {result?}
```

- `cap` names an entry in the welcome's `device.caps` list; `args` is a
  plain-data object whose shape belongs to the capability. On success
  the response's result is empty, or carries a `result` object for
  querying capabilities. v1's `capability.result` and its dead
  `ok: false` state dissolved: a failed or unknown invoke is a typed
  error whose `data.kind` is one of —

  | code | data.kind         | meaning                                               |
  |------|-------------------|-------------------------------------------------------|
  | 1001 | `cap-unsupported` | this companion has no such capability                 |
  | 1002 | `cap-permission`  | needs a device permission the user has not granted    |
  | 1003 | `cap-failed`      | supported and permitted, but the device action failed |

  A `cap-permission` error additionally carries, in `data`, `perm` (the
  missing `device.perms` key) and, when one exists, `settings` — a
  value the client can pass straight back as `capability.invoke {cap:
  "settings.open", args: {panel: …}}` to take the user to the right
  grant screen. The remedy rides the error; that was the pattern worth
  keeping.

- **Device report.** When `capabilities` or `triggers` is granted,
  the welcome carries a `device` object:

  ```json
  "device": {"caps": ["settings.open"],
             "perms": {"post_notifications": true, "exact_alarms": true,
                       "write_settings": false, "notification_policy": false,
                       "notification_listener": false, "fine_location": false,
                       "bluetooth_connect": false, "read_calendar": false,
                       "receive_sms": false, "read_phone_state": false,
                       "read_call_log": false},
             "trigger_types": ["airplane", "battery.level", "boot", "..."],
             "state_types": ["airplane", "battery.level", "headset", "..."],
             "trigger_unavailable": {"sms.received": "receive_sms"}}
  ```

  `caps` is the invocable capability set. `perms` reports the runtime
  and special-access permissions effectors and triggers depend on, so
  the client can degrade gracefully — grey out a control, deep-link to
  the grant screen — instead of invoking blind. The map is a snapshot
  at welcome time; the companion re-checks at invoke time, so a stale
  map can only cause a typed error, never a wrong action.
  `trigger_types` (under the `triggers` grant, §13) is this
  companion's trigger-type catalog: because `triggers.set` rejects a
  set wholesale on an unknown type, the client uses this list to skip
  a too-new registration instead of poisoning the push.
  `state_types` (also under the `triggers` grant) is the
  state-predicate catalog — what a §13 `when` gate may reference and
  `state.get` can sample; the client-side rule it drives is normative
  in §13's `when` bullet. `trigger_unavailable` (present only when
  non-empty) maps each *supported but currently unarmable* trigger
  type to the `device.perms` key blocking it — the client's
  "needs permission" affordance and grant deep-link. It never changes
  push discipline: the client still pushes such rows, and the
  companion stores them and arms them once the permission is granted
  (the existing, correct degrade).

- **Trust model.** This flows in the already-trusted direction: the
  post-handshake client drives notifications, reminders, and dialogs,
  and effectors are consistent with that. `args` are plain data,
  validated per capability. Capabilities that launch activities are
  best-effort while the companion is backgrounded (Android
  background-launch limits); they are reliable from foreground and
  notification contexts.

### Capability catalog

| cap | args | result | notes |
|---|---|---|---|
| `settings.open` | `{panel}` | — | `panel` = `wifi` \| `internet` \| `bluetooth` \| `volume` \| `nfc` \| `app` (the companion's own app-info page — runtime-permission grants live there), or any `android.settings.*` action string; anything else → `cap-failed`. The compliant "toggle" for radios apps can't flip; floating panels where the platform has them |
| `intent.start` | `{action?, data?, package?, class_name?, mime?, extras?, mode?}` | — | the universal escape hatch. `extras` values are strings/numbers/booleans only — never anything executable. `mode` = `activity` (default, adds `FLAG_ACTIVITY_NEW_TASK`) \| `broadcast` \| `service`. Activity mode is best-effort while the companion is backgrounded |
| `app.launch` | `{package}` | — | the package's launcher activity, or `cap-failed` |
| `apps.list` | — | `{apps: [{label, package}]}` | launchable packages sorted by label — feeds a client-side picker. Empty without the companion's package-visibility `<queries>` |
| `shortcut.pin` | `{id, label, action, icon_png?, long_label?}` | `{updated?}` | requests a home-screen pinned shortcut (launcher confirm dialog; the OS badges it with the companion's icon). `action` is a standard action object (§7) fired through the normal tap pipeline when the shortcut opens the companion; `icon_png` is a base64 PNG the launcher masks to its adaptive shape (square full-bleed, ≥432 px recommended), defaulting to the companion's own icon. Re-pinning an existing `id` updates it in place with no dialog → `{updated: true}`. Launcher refusal → `cap-failed` |
| `shortcuts.set` | `{shortcuts: [{id, label, action, icon_png?, long_label?}]}` | — | replace-set of the companion icon's long-press (dynamic) shortcuts, `triggers.set` discipline: empty list clears, a set above the launcher's per-activity max → `cap-failed` (never silently truncated). Entry fields as in `shortcut.pin` |
| `vibrate` | `{ms?}` or `{pattern: [off, on, … ms]}` | — | `ms` defaults to 200; `pattern` wins when both given |
| `tts.speak` | `{text, pitch?, rate?}` | — | asynchronous best-effort; engine lazy-inits (utterances queue during init) and releases after ~60 s idle |
| `volume.set` | `{stream, level}` | `{max}` | `stream` = `music` \| `ring` \| `alarm` \| `notification` \| `call` \| `system`; `level` clamps to `0..max`. DND policy can refuse → `cap-permission` |
| `ringer.mode` | `{mode}` | — | `normal` \| `vibrate` \| `silent`; silent needs DND access → `cap-permission` with the grant deep-link |
| `flashlight` | `{on}` | — | torch of the first flash-capable camera; none → `cap-failed` |
| `media.key` | `{key}` | — | `play_pause` \| `play` \| `pause` \| `next` \| `previous` \| `stop` \| `fast_forward` \| `rewind` |
| `clipboard.read` | — | `{text}` | Android 10+ exposes the clipboard only to the focused app → `cap-permission` while backgrounded. Contents must never be logged or persisted companion-side |
| `screen.keep_on` | `{on}` | — | a window flag held only while the companion's own UI is on screen — it cannot pin the device awake from the background |
| `brightness.set` | `{level}` | — | 0–255, switches to manual brightness; ungranted → `cap-permission` (`write_settings` + the grant deep-link) |
| `dnd.set` | `{mode}` | — | `on` \| `off` \| `priority`; ungranted → `cap-permission` (`notification_policy` + the grant deep-link) |
| `state.get` | `{types?, when?}` | `{states, unavailable?, holds?}` | sample the §13 state predicates. `states` maps each requested type (default: every `device.state_types` entry) to its current state object (shapes in §13 "State predicates & sampling"); a type that cannot be sampled lands in `unavailable` as its typed failure kind, never failing the batch. `when` — a §13 predicate array — adds `holds`, evaluated by the same code path that gates fires, so a gate is testable from Emacs before it ships; a malformed `when` → `cap-failed` |
| `trigger.fire` | `{id}` | — | the Emacs-initiated twin of the §7 `trigger.fire` builtin: fires the `manual` registration `id` through the full trigger pipeline with fire data `{source: "emacs"}`. An unknown id or a non-`manual` type → `cap-failed` |

## 13. Device triggers (optional)

The device → Emacs *event source* path: the companion watches device
state (time, power, screen, connectivity, …) and reports changes the
client subscribed to — durable the same way its UI serving is durable.
Negotiated under the `triggers` capability name; a companion that
cannot host triggers does not grant it, and a client must not send
`triggers.set` without the grant.

```
C→  triggers.set   {triggers: [{id, type, params?, when?, policy?, dedupe?,
                                throttle_s?, on_fire?}]}   →   {}
```

- **Replace-set semantics**, exactly like `reminders.set`: each set
  replaces the previous one in full, so a removed trigger can never
  fire stale, and re-pushing the current set on reconnect is
  idempotent. The registered set persists on the companion and is
  re-armed after reboots. Acceptance is the empty result; a wholesale
  rejection (an unknown type, a malformed gate) is the typed error
  `1101 triggers-rejected` — v1's codeless companion-side log line,
  finally audible to the set's author.
- `id` is the client's stable name for the registration; `type` names
  an entry in the trigger-type catalog below; `params` is the
  plain-data, type-specific match configuration (an SSID, a battery
  threshold, a clock time).
- **Firing is an ordinary event.** A firing trigger delivers

  ```
  event.action   {action: "trigger.fired",
                  args: {id, type, data, at_ms}}
  ```

  through the exact machinery of §§7–8: connected ⇒ delivered,
  disconnected ⇒ queued / dropped / woken per the registration's
  `policy` (the §7 `when_offline` vocabulary; default `queue`), with
  `dedupe` collapsing queued fires that share the key. There is no
  second event channel. The allowlist rule holds: the companion may
  fire only ids present in the currently registered set — names the
  client itself registered — and `data` is plain JSON shaped per
  trigger type (an SSID string, a battery percentage), never anything
  executable.
- `throttle_s` is a host-side minimum interval between fires of one
  trigger — §5 rule 3's throttle-at-the-source, in the vocabulary
  since long before the overload section named it. Threshold types
  (e.g. battery level) must fire on edge
  crossings computed host-side, never on every underlying broadcast.
- `when` — an optional state gate: a flat array of state predicates
  (see "State predicates & sampling" below), ANDed at fire time. The
  gate guards the **entire** fire: when any predicate does not hold,
  the fire never happened — no `event.action` is queued or delivered,
  no `on_fire` runs, and no `throttle_s` bookkeeping is consumed (the
  gate is checked before the throttle, so a suppressed fire cannot eat
  the slot of a real one). A predicate that cannot be evaluated — an
  ungranted permission, an unknown type — counts as **not holding**:
  fail closed, never fire garbage. There is no OR, no nesting, no
  negation: predicates are two-valued, so a complement is expressed by
  flipping the value; a rule that needs OR is two registrations, or
  logic in Emacs. Companions that support `when` validate it and
  reject the whole set on a malformed gate, like any unknown type.

  **Client rule (normative).** A client may include `when` in a
  registration only when **every** predicate's `type` appears in the
  session's `device.state_types` report (§12). Otherwise it must skip
  the whole registration (with a message) — it must **never** strip
  `when` and push the rest. Rationale: a companion that predates this
  field ignores unknown keys *inside* a trigger entry rather than
  rejecting the set, so a pushed-anyway gate would arm the trigger
  ungated — "notify below 20%" silently becomes "notify always",
  strictly worse than a skip.
- `on_fire` — the companion-local response, executed at fire time even
  with Emacs dead, **in addition to** the `trigger.fired` event (which
  still queues and delivers, so the client always learns of the fire
  and stays the source of truth). A flat list, executed in order, of:

  - `{cap, args?}` — a §12 capability invocation
    (`{"cap": "flashlight", "args": {"on": true}}`);
  - `{notify: {title?, text?}}` — post a simple notification.

  Builtin entries are reserved. This is the one place the companion
  acts on its own, so the vocabulary is deliberately closed: **no
  conditionals, no loops** — a rule that needs logic while Emacs is
  dead means "keep Emacs alive", not a rule language in the companion.
  (`when` is not a conditional in this sense: it is a declarative
  state gate — sampled device state ANDed at fire time — not control
  flow inside the response.) Unknown entries and failing capabilities
  are logged and skipped, never fatal.

  **Placeholders.** String values inside `notify` and inside a `cap`
  entry's `args` (recursively — nested objects and arrays, so
  `intent.start` extras are covered) are interpolated at fire time
  against this fire, using §11's snippet-placeholder grammar:
  `${id}` and `${type}` are the registration's id and type, and
  `${data.FIELD}` is a field of this fire's `data` (e.g.
  `${data.level}`, `${data.ssid}`). The §11 rules apply verbatim —
  substitution is a single pass (substituted text is never re-scanned),
  unknown or unresolvable `${…}` tokens (including a `data.FIELD` that
  is absent or JSON null) are left literal, and the result is always a
  string (a numeric or boolean field renders in its JSON form, `63` /
  `true`). The `cap` name itself never interpolates — capability
  selection is not data-driven. There is no escape mechanism: a literal
  `${id}` in authored text is unrepresentable, as in §11.

**Revocation while armed (normative).** Revoking a runtime permission
kills the companion process; on restart, arming skips receivers it may
no longer register (with a log) and the affected predicates fail
closed — a revoked permission can silence a rule, never fire it wrong.
The next welcome reports the type in `device.trigger_unavailable`
(§12), which is how the client learns to surface "needs permission"
against the still-registered row.

### Trigger-type catalog

An empty or absent `params` field means "match every event of the
type". Registering an unknown type is refused (the whole set is
rejected with a typed 1101, so the client never half-arms) — which is
why the welcome's `device.trigger_types` (§12) exists: the client
filters its push against that report and skips what this companion
can't host.

| type | params | data | notes |
|---|---|---|---|
| `time` | `{at_ms}` one-shot, or `{every_s}` repeating | `{}` | exact alarms (inexact when the exact-alarm permission is revoked); `every_s` clamps to ≥ 60 and re-arms after each fire; survives reboots |
| `power` | `{state?}` — `connected` \| `disconnected` | `{state, plug?}` | `plug` = `ac` \| `usb` \| `wireless` on connect |
| `battery.level` | `{above: pct}` or `{below: pct}` | `{level}` | host-side hysteresis: fires only when the level **crosses into** the configured side, never per raw reading |
| `screen` | `{state?}` — `on` \| `off` \| `unlocked` | `{state}` | `unlocked` = ACTION_USER_PRESENT |
| `headset` | `{state?}` — `plugged` \| `unplugged` | `{state, name?}` | wired audio (ACTION_HEADSET_PLUG); Bluetooth devices are the connectivity batch |
| `airplane` | `{state?}` — `on` \| `off` | `{state}` | |
| `boot` | — | `{}` | fires once per boot from the boot receiver; typically `policy: "queue"` or `"wake"` |
| `timezone.changed` | — | `{tz}` | the new zone id |
| `package` | `{event?, package?}` — `added` \| `removed` | `{event, package}` | update-replacing broadcasts are filtered out |
| `manual` | — | `{source}` | fires only via the `trigger.fire` builtin (§7) or capability (§12), never from device state; nothing is armed for it — zero standing cost. `source` = `tap` \| `emacs`. A removed row cannot fire: replace-set semantics for free |
| `state.edge` | `{when: [predicate, …], edge?}` | `{holds, edge}` | the level→edge bridge — any state conjunction becomes an event source; see **Tracked-state edges** below |
| `network` | `{event?, transport?}` — `available` \| `lost`; `wifi` \| `cellular` \| `ethernet` \| `vpn` \| `bluetooth` | `{event, transport?}` | the default-network callback (permission-free); fires once per network gain/loss |
| `wifi.enabled` | `{enabled?}` | `{enabled}` | the Wi-Fi *adapter* state — enabled/disabled edges only, transitional states are not edges. Distinct from `network` (radio on ≠ connected) and from the reserved `wifi.ssid`. Install-time `ACCESS_WIFI_STATE`, no runtime grant |
| `bluetooth.enabled` | `{enabled?}` | `{enabled}` | the Bluetooth *adapter* state, same edge discipline. Install-time legacy `BLUETOOTH` (≤ API 30) only; a device without Bluetooth simply never fires it. Distinct from the reserved `bluetooth.device` |
| `calendar.event` | `{event?, calendar?, title_contains?}` — `started` \| `ended`; exact calendar display name; case-insensitive title substring | `{event, title?, begin_ms?, end_ms?}` | a synced calendar (e.g. an org agenda) made reactive, with **zero polling**: one ContentObserver on the instances table plus one alarm per registration parked at the *next boundary* (the ongoing instance's end, else the next matching start, else a lookahead re-scan). Editing an event re-arms via the observer; reboots re-arm from the persisted set; the last ongoing side persists so a boundary alarm in a cold process still fires the flip. Runtime `READ_CALENDAR`: ungranted registrations are skipped with a log — never garbage fires |
| `sms.received` | `{from?, contains?, include_body?}` — `from`/`contains` are substrings; `include_body` defaults false | `{from, body?}` | opt-in, fail-closed privacy: `contains` reads the body to match but `body` rides only under `include_body: true`. Runtime `RECEIVE_SMS`; multipart segments are concatenated. Content is never logged; under `policy: "queue"` the `data` sits in the app-private queue DB, so `policy: "drop"` is recommended for body-carrying rules. Edge-only (no predicate) |
| `call.state` | `{state?, number?, include_number?}` — `ringing` \| `offhook` \| `idle`; `number` a substring; `include_number` defaults false | `{state, number?}` | runtime `READ_PHONE_STATE` for the state edges. **The number needs `READ_CALL_LOG` in addition** (Android 9+): without it a `number`-filtered rule never fires and `include_number` yields no field. Duplicate broadcasts (per phone account, and again with the number) are deduped to one fire. Same never-logged discipline as `sms.received` |

`wifi.ssid` and `bluetooth.device` are the remaining connectivity
batch; each will document its runtime-permission behavior here
(SSID needs fine location — degrade to `network`'s transport-only
matching when ungranted, never fire garbage).

**Tracked-state edges.** A `state.edge` registration turns any state
conjunction into an event source. `params.when` is a predicate list in
the *exact* `when` vocabulary above — same validation, same evaluation,
so the two vocabularies can never fork — and the row fires when the
ANDed conjunction's truth **flips** in the declared direction:
`edge` is `rise` (false → true, the default), `fall`, or `both`; fire
data is `{holds, edge}`. The trackable subset is `device.state_types`
minus `time.window` and `calendar.event` — exclusions that cost
nothing, since a time-window edge is a `time` trigger at the boundary
and a calendar edge is the `calendar.event` type already; a set whose
`state.edge` row references an untrackable or unknown predicate type
is rejected whole, like any malformed gate. The first evaluation at
arm time **seeds silently**: re-arming and reboots never fire, and a
flip missed while unarmed self-heals at the next driving event. A
row-level `when` remains legal on a `state.edge` row with its usual
meaning — an additional gate checked at fire time; the tracked
conjunction lives only in `params.when`, and an author using the same
predicate type in both is probably confused (clients should warn).
**Client rule (normative):** push a `state.edge` row only when every
`params.when` predicate type appears in the session's
`device.state_types`; otherwise skip the whole row — the `when`-strip
rationale, verbatim. (Named `state.edge`, never `state.changed`: that
method is §7's widget-input notification, and *edge* is the precise
word — this is a level→edge bridge.)

### State predicates & sampling

Some device signals are useful as *levels* (sample-able booleans), not
only as edges. The welcome's `device.state_types` (under the `triggers`
grant, §12) is this companion's catalog of state-predicate types — the
shared vocabulary of `when` gates (above) and `state.get` (§12). It is
negotiated separately from `trigger_types` because sample-ability and
trigger-ability differ: `boot` / `time` / `timezone.changed` /
`package` are edge-only, and `time.window` is predicate-only. Where a
signal has both views it carries the same name in both catalogs, and
sampling costs nothing standing: every sampler is a cached-system-state
read — no listeners, no polling.

A predicate is a flat object: `type` plus type-specific match fields
reusing the trigger catalog's `params` vocabulary. A predicate with no
match fields asserts the type's *natural state*, noted per row:

| type | fields | holds when |
|---|---|---|
| `power` | `{state?}` | the power state equals `state` (default `connected`) |
| `battery.level` | `{above: pct}` or `{below: pct}` | the level is strictly above / below the threshold; exactly the trigger's threshold vocabulary, one bound required |
| `screen` | `{state?}` | `on` / `off` — the screen is interactive or not (default `on`); `unlocked` — the keyguard is dismissed |
| `airplane` | `{state?}` | airplane mode equals `state` (default `on`) |
| `network` | `{transport?}` | a network is connected, and its transport matches when given |
| `headset` | `{state?}` | wired or USB audio output present (`plugged`, the default) or absent (`unplugged`) |
| `wifi.enabled` | `{enabled?}` | the Wi-Fi adapter state equals `enabled` (default `true`) |
| `bluetooth.enabled` | `{enabled?}` | the Bluetooth adapter state equals `enabled` (default `true`); no adapter → unevaluable, so never holds |
| `calendar.event` | `{calendar?, title_contains?}` | a matching calendar instance is ongoing right now; ungranted `READ_CALENDAR` → unevaluable, so never holds |
| `call.state` | `{state?}` | the telephony call state equals `state` (default `offhook`, i.e. on a call); ungranted `READ_PHONE_STATE` → unevaluable, so never holds. `sms.received` has no predicate — a message arrival is an edge, not a level |
| `time.window` | `{after?, before?, days?}` | the local clock is inside the window. `after`/`before` are `"HH:MM"` strings, half-open `[after, before)`; the window wraps midnight when `after` > `before`; an absent bound is open. `days` is an array of `mon`…`sun` filtering on the calendar day of the moment tested; absent = every day. Predicate-only: it has no edge trigger, and `state.get` reports it under `unavailable` |

Sampled state objects (`state.get`'s `states` values) are shaped like
the type's trigger `data` column above, with the level-view
substitutions: `screen` adds `locked` (boolean), `network` reports
`{connected, transport?}` instead of an event, `calendar.event`
reports `{ongoing, title?, end_ms?, next_begin_ms?}`, and `call.state`
reports `{state}` (each ungranted → `unavailable` as `cap-permission`).

## 14. Conformance

A minimal **companion** implements: the JSON-RPC envelope over
Content-Length frames with the §2.3 dispatch duties (requests answered
exactly once, `-32601` for unknown request methods, log-and-drop for
unknown notifications, direction and class enforcement, the batch
prohibition); the two-request handshake with pairing auth, failing
closed by explicit `1200` refusals before the proof;
`surface.update`/`surface.remove` with revision + cache semantics for
`app:*` surfaces; `event.action`/`state.changed` with the §7 ordering
rules; the offline queue with `queue.replay` concluded by its drain
summary; the §7 builtins; the §5 overload rules for its class of
traffic — bounded inbound buffering and the frame cap are conformance
requirements, not advice; and the widget families under §11 it can
render (unknown nodes render as their children or nothing, never as a
crash). Everything in §§9–10 and §§12–13 is negotiated or optional.

A minimal **client** implements: the envelope and the same §2.3
dispatch duties on its side; the handshake (failing closed on a bad
`server_proof`); monotonic revisions with snapshot absorption; the
sender half of §5 rule 1 (coalesce-to-latest for its snapshot pushes);
and the allowlist rule of §7.

### Reference status (the checking copy's honesty note)

The reference pair (elisp client + Android companion, `jetpacs
slop-fork`) implements this document except where inventoried here —
the #26 spec-ahead convention, consolidated. Each item re-enters the
reference (and where applicable the generated contract) by ordinary
amendment when its implementation lands:

1. **§4 staging** — `dialog.show` and the `edit.*` legs ship as
   notifications/event-riders in the first cut; the method table is the
   target. (Detailed in §4's staging note.)
2. **v1 #18** — the `ttl_s` → `stale_after_s` rename and the
   clock-from-disconnect staleness basis (§6). The reference and the
   format-5 contract still speak `ttl_s`, measured from the last
   update.
3. **v1 #19** — the welcome's `input_state` snapshot (§3, §8): the
   contract admits the key; the reference companion never emits it, so
   offline typed input still dies with the gap. `state.changed`'s
   optional `surface` is likewise admitted but not yet emitted.
4. **v1 #20** — the universal box-model attributes, `arrange`, row
   `baseline`, and lazy `content_padding` (§11): documented vocabulary,
   not yet in the reference renderer or `node_schema` (the container
   sizing subset — `width`/`height`/`fill_fraction`/`border` on
   `box`/`surface`/`card`/`image` — IS implemented and published).
   Until they land they are ordinary unknown keys under §11's
   tolerance rule.
5. **v1 #21** — `enabled` / `can_disable` (§3, §11): the contract
   admits `can_disable` in the welcome; neither side implements it, and
   the skip-don't-emit client rule keeps `enabled` off the wire —
   exactly as designed for a companion that doesn't announce it.
6. `wifi.ssid` / `bluetooth.device` (§13): reserved, unimplemented on
   every line — carried from v1 unchanged.
7. **#29 de-branding** — the `companion.settings.open` builtin (§7):
   the running reference pair still emits and handles the old
   `jetpacs.settings.open` name; the rename re-enters the reference by
   ordinary lockstep change (elisp + Kotlin emission sites and tests).

## 15. What guided what

| decision | guide |
|---|---|
| capabilities-not-versions; property-level gating for constraining fields | LSP (and v1's own amendment #5) |
| conflated queues for latest-wins traffic; obsolescence as backpressure | market-data conflation practice + v1's own §8 seq discards, promoted to doctrine |
| skippable oversize frames as a framing dividend | Content-Length framing (decision #2) — a header names the bytes to discard |
| null-result ≠ error; cancelled requests still conclude; reserved code ranges | LSP base protocol |
| client-owns-truth → welcome carries the input snapshot | LSP `didOpen` ownership + LiveView form recovery (v1 #16) |
| whole-snapshot surfaces + reserved keyed-list splice; closed effects vocabulary someday | LiveView (streams, JS commands) |
| explicit-signal fail-closed dispatcher; -32601 hand-rolled; 32000/-1 landmines; outbound-data stash | jsonrpc.el v1.0.29, read not remembered |
| manual/`state.edge`/`trigger_unavailable`; history & availability discipline | Easer + Termux harvests (v1 #19–#22) |

## 16. Owner's open decisions (the hand line decides; the slop line only drafts)

1. Domain-tag retag `ebp1:` → `ebp2:` at the envelope swap, or keep (v1 #11
   pattern either way). The first-cut reference keeps `ebp1:`.
2. `rpc.cancel` as drafted vs keeping a semantic `dialog.dismiss` alias
   (the first cut stages this — see §4's staging note).
3. The 1200-range numbering (this draft's invention — renumber freely;
   1400-range likewise, added with §5).
4. Whether `edit.*` promotion ships in the first rebuild cut or after the
   editor katas (the first cut resolves this as "after" — §4 staging note).
5. Contract shape for v2 (method table + direction + request/notification
   classification as machine artifact — contract_format 5 territory; the
   slop reference now generates a format-5 draft with `methods`,
   `result` schemas, and `error_codes` — renumber or reshape freely).
6. The frame cap: fixed 4 MiB default as drafted, or negotiated per side
   at the handshake (a `max_frame_bytes` beside `wants` in the hello and
   beside `granted` in the welcome would follow the treaty pattern).
7. The WebSocket transport profile — the browser-companion door (Emacs
   listens, the page dials; roles unchanged). Quarried in
   `slop-docs/WEBSOCKET-transport-kit.md`, prototyped-by-plan as
   `docs/PLAN-jetpacs-cloud.md`, currently parked: the §1 transport row
   gains the profile when a working companion exists, not before.

The kit's §4 learning ladder and four katas remain the hand line's entry
path; kata 4 (hello/challenge with a refuse-everything dispatcher) lands
you at exactly §3 of this draft, which is the first thing worth checking
your hand-written version against.
