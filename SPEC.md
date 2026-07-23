# EBP — the Emacs Bridge Protocol

Status: **Greenfield Draft**

Protocol version: **2**

Document version: **2.0.0-draft**

## 1. Purpose and scope

EBP is a bidirectional wire protocol through which Emacs declares user
interfaces and bounded platform operations to a Companion, and the Companion
reports semantic user actions and platform events to Emacs. Emacs remains the
authority for application state and application policy. The Companion owns
native presentation, platform integration, cached presentation state, and
durable delivery records.

EBP carries declarative data and named actions. It MUST NOT carry executable
host-language code. A Companion MUST NOT invent application behavior and MUST
execute only operations defined by the negotiated EBP vocabulary.

EBP is implementation-language and UI-toolkit agnostic. Conformance is
determined by observable protocol behavior, not by internal architecture. An
implementation MAY use Jetpack Compose, Android Views, SwiftUI, Flutter, a web
toolkit, or any other technology capable of implementing this contract.

This document defines:

- the JSON data model and JSON-RPC 2.0 conventions used by EBP;
- the `android-loopback-tcp` transport profile and its framing;
- session authentication, negotiation, synchronization, and reconnection;
- surface snapshots, semantic actions, input state, and durable replay;
- the core widget vocabulary and optional presentation modules;
- optional editor, device-capability, and device-trigger modules; and
- conformance and security requirements.

## 2. Conventions and specification authority

### 2.1 Requirement language

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD",
"SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be
interpreted as described in BCP 14 [RFC2119] [RFC8174] when, and only when, they
appear in all capitals.

Unless expressly marked informative, prose and tables in this document are
normative. Examples are informative unless an accompanying sentence states
otherwise.

### 2.2 Artifact precedence

This document is the normative authority for EBP 2. `contract.json` is a
machine-readable projection of the types and registries defined here. Goldens
are conformance fixtures that witness particular normative rules.

The generator of `contract.json` MUST derive it from this specification's
authored definitions. A mismatch among this document, `contract.json`, and a
Golden is a specification or tooling defect. An implementation MUST NOT imitate
a conflicting derived artifact. The conflicting artifact MUST instead be
corrected and recaptured.

An exact byte comparison is normative only for a Golden that tests transport
framing or another explicitly byte-exact rule. Tests of JSON message semantics
MUST compare parsed JSON values unless this document expressly requires a
canonical serialization.

### 2.3 Terminology

| Term | Definition |
|---|---|
| **Emacs endpoint** | The endpoint that owns application state and MUST initiate every EBP session by sending `session.hello`. |
| **Companion endpoint** | The endpoint that renders declared surfaces, performs negotiated platform operations, persists presentation and delivery state, and reports events. |
| **JSON-RPC caller** | The endpoint that sends a particular JSON-RPC request. This role is per request. |
| **JSON-RPC responder** | The endpoint that answers a particular JSON-RPC request. This role is per request. |
| **transport profile** | A named, complete set of connection, framing, addressing, and minimum-authentication rules. A profile is not an operating system or programming language. |
| **session** | One authenticated EBP association over one transport connection. |
| **surface** | A named, revisioned, cacheable user-interface target. |
| **node** | One element of a declarative surface tree. |
| **action descriptor** | Data attached to an interactive node that declares either a remote semantic action or a bounded Companion-local operation. |
| **event** | One occurrence of a semantic action or subscribed platform trigger. |
| **revision** | A non-negative safe integer that orders snapshots and tombstones for one surface. |
| **capability** | A positively advertised optional protocol or platform feature. |
| **Golden** | A version-controlled binary fixture containing one or more complete wire messages and an identified expected outcome. |

Generic words such as “client” and “server” MUST NOT be used to identify the
two EBP endpoints. They MAY be used when discussing the roles of one specific
JSON-RPC exchange or a transport API.

## 3. Architectural invariants

1. Emacs MUST remain authoritative for derived application state and
   application-specific decisions.
2. The Companion MAY retain presentation state, input drafts, platform state,
   and delivery records required by this specification.
3. The Companion MUST NOT parse Emacs application data files to reconstruct
   application state unless a separately negotiated capability explicitly
   defines that operation.
4. The Companion MUST NOT evaluate Elisp, JavaScript, shell text, host-language
   function names, or other transmitted executable code.
5. A transmitted operation name, document identifier, package name, URI, or
   platform intent MUST be treated as untrusted data and MUST be validated
   against the applicable method, capability, or application allowlist.
6. Every Companion-side language defined by EBP—node trees, predicates,
   substitutions, response lists, and drawing operations—MUST have a finite
   vocabulary, MUST terminate, and MUST perform no ambient I/O except where an
   enumerated capability expressly permits it.
7. Partial understanding MUST fail safely. A receiver MUST NOT silently weaken
   an unrecognized constraint into permission to perform a broader action.

The boundary is therefore not “code versus no computation.” The boundary is
application-defined executable behavior versus finite operations selected and
parameterized by Emacs.

## 4. JSON data model

### 4.1 Encoding and values

JSON bodies MUST conform to [RFC8259] and MUST be encoded as UTF-8 without a
byte-order mark. A sender MUST NOT emit ill-formed Unicode. A receiver MUST
reject a body containing invalid UTF-8. After JSON escape decoding, every
string and member name MUST be a sequence of Unicode scalar values; an unpaired
surrogate escape is invalid and MUST be rejected rather than preserved or
replaced.

Object member order is insignificant. A sender MUST NOT emit duplicate member
names. A receiver MUST reject an object containing duplicate member names as an
invalid request or invalid notification. Strings, member names, method names,
identifiers, enum values, and capability names are case-sensitive and MUST be
compared without Unicode normalization.

An absent member and a member whose value is `null` are distinct. A sender MUST
omit an optional member when it has no value unless the member's definition
explicitly permits `null`. A receiver MUST NOT coerce among strings, numbers,
booleans, arrays, objects, and `null`.

### 4.2 Numeric rules

An EBP integer MUST be mathematically integral and MUST be in the inclusive
range `-9007199254740991` through `9007199254740991`. Fields declared
non-negative MUST be in the inclusive range `0` through `9007199254740991`.
Revisions, sequence numbers, timestamps, and counts MUST NOT exceed this range.
EBP request IDs are strings; Section 7.2 prohibits numeric request IDs.

A JSON number used where this document says `number` MUST convert under
round-to-nearest, ties-to-even to a finite IEEE-754 binary64 value. A sender
MUST NOT emit a literal that overflows to infinity or whose nonzero exact value
underflows to zero. Receivers MUST NOT preserve implementation-specific extra
decimal precision as a distinct EBP value. `NaN`, positive infinity, and
negative infinity are not JSON values and MUST NOT be transmitted.

Epoch timestamps named `*_at_ms` or `*_ms` are non-negative integer
milliseconds since `1970-01-01T00:00:00Z`. Durations named `*_s` are
non-negative integer seconds unless stated otherwise.

### 4.3 JSON equality

Where this specification compares JSON values, equality is structural:

- strings and booleans are equal only to the same type and value;
- JSON numbers are equal by their Section 4.2 binary64 value, so `1`, `1.0`,
  and `1e0` are equal and `-0` equals `0`;
- arrays are equal when they have equal length and pairwise-equal values in the
  same order;
- objects are equal when they have the same member names and equal values,
  independent of member order; and
- `null` equals only `null`.

### 4.4 Identifiers

Unless a narrower grammar is stated, an EBP identifier MUST:

- contain 1 through 128 ASCII characters;
- begin with an ASCII letter or digit; and
- contain only ASCII letters, digits, `.`, `_`, `-`, `:`, and `/`.

Identifiers are opaque. A receiver MUST NOT interpret an identifier as a file
path, URI, or command unless its field definition expressly gives it that type.

An `EventId`, nonce, or proof is lowercase hexadecimal. An `EventId` and each
nonce MUST encode exactly 16 octets and therefore contain exactly 32
hexadecimal characters. An HMAC-SHA256 proof MUST contain exactly 64 lowercase
hexadecimal characters.

### 4.5 Resource limits

A receiver MUST enforce all of the following limits:

| Resource | Limit |
|---|---:|
| Framing header section | 8,192 octets from the first header octet through and including the complete final `\r\n\r\n` |
| JSON body | 4,194,304 octets |
| JSON nesting depth | 64 containers |
| Nodes in one surface snapshot | 10,000 |
| Children of one node | 10,000 |
| Identifier | 128 UTF-8 octets and the ASCII grammar above |

Every core endpoint MUST accept otherwise valid core messages within these
limits. Module-specific storage and content limits MUST be reported in the
authenticated welcome's `limits` object. A sender MUST respect reported limits
and MUST NOT rely on receiver truncation.

A body that nests JSON containers past the 64-container limit above MUST be
rejected as a JSON-RPC Parse Error under Section 6.2 — `error.code` `-32700`
with `id: null` when a response can still be sent safely — and the receiver MAY
continue the connection. Because such a body can exhaust a recursive JSON
parser's stack before any structural error is reported, the rejection MUST be
made before the body is otherwise parsed, in bounded stack: for example, by a
single linear scan of the decoded body that increments on each `{` or `[` and
decrements on each `}` or `]` outside a JSON string literal. Per Section 6.2's
receiver-strictness scoping, this bounded-stack determination is REQUIRED for
the Companion and RECOMMENDED for the Emacs endpoint, which MAY delegate
decoding to a host JSON-RPC library that bounds recursion by its own means.

The `limits` object uses these members. All byte counts refer to UTF-8 or stored
payload octets as applicable, not characters. For `max_field_bytes` and
`max_input_state_bytes`, encoded size means the UTF-8 length of the logical
value serialized by the JSON Canonicalization Scheme [RFC8785]. This use is
only a deterministic sizing rule; ordinary EBP wire bodies are not otherwise
required to use canonical JSON. When serializing a value governed by either
limit, the Companion MUST use a representation no longer than that value's JCS
representation, so optional escaping or whitespace cannot defeat the budget.

| Member | Requirement |
|---|---|
| `max_frame_bytes` | REQUIRED and MUST equal `4194304`; maximum JSON body bytes |
| `max_queued_events` | REQUIRED, at least `256` |
| `max_queued_bytes` | REQUIRED, at least `8388608` |
| `max_event_bytes` | REQUIRED, at least `262144`, and no greater than `max_frame_bytes - 256` |
| `max_surfaces` | REQUIRED, at least `16` simultaneously present surfaces |
| `max_surface_ids` | REQUIRED, at least `1024` distinct present or tombstoned surface histories per pairing identity |
| `max_field_bytes` | REQUIRED, at least `65536` and no greater than `max_frame_bytes - 2048`; maximum encoded bytes per input value, including a volatile password value |
| `max_input_state_bytes` | REQUIRED, at least `262144`; maximum encoded bytes in the complete welcome `input_state` object |
| `max_capture_fields` | REQUIRED, at least `64` IDs in one ActionDescriptor |
| `max_triggers` | REQUIRED when `triggers` is granted |
| `max_trigger_responses` | REQUIRED when `triggers` is granted; maximum `on_fire` entries per trigger |
| `max_reminders` | REQUIRED when `reminders.owner` is granted |
| `max_editor_sessions` | REQUIRED when `editor.sync` is granted |
| `max_dialogs` | REQUIRED when `surfaces.dialog` is granted |
| `max_pie_menus` | REQUIRED when `presentation.pie-menu` is granted; at least `1` |
| `max_device_report_bytes` | REQUIRED when `capabilities` or `triggers` is granted; maximum canonical bytes of the complete device report |
| `max_image_bytes`, `max_decoded_image_bytes`, `max_image_pixels`, `max_canvas_ops`, `max_chart_points` | REQUIRED when the corresponding node type or feature is advertised |
| `max_rich_spans`, `max_table_cells` | REQUIRED when `rich_text` or `table`, respectively, is advertised |
| `max_shortcut_icon_bytes` | REQUIRED when `shortcut.pin` or `shortcuts.set` is advertised; decoded PNG octets |
| `max_shortcuts` | REQUIRED when `shortcuts.set` is advertised |

A receiver MUST enforce these limits before durable admission or expensive
decoding. A module MAY advertise a larger value but MUST NOT advertise a value
it cannot sustain.

`max_event_bytes` measures the exact UTF-8 JSON encoding of the complete
`event.action.params` object chosen for persistence and transmission and does
not include the JSON-RPC envelope or storage-engine overhead. An
`event.action` sender MUST encode the fixed envelope outside `params` in no more
than 256 UTF-8 octets. Together with the upper bound above, this guarantees that
an allowed event also fits `max_frame_bytes`. `max_queued_bytes` is an internal
durable capacity and MAY conservatively include payloads, indexes, transaction
records, and storage overhead. `max_image_bytes`, `max_decoded_image_bytes`, and
`max_image_pixels` apply per image. Unless a row states otherwise,
`max_canvas_ops`, `max_chart_points`, `max_rich_spans`, and `max_table_cells`
are aggregate counts across one SurfaceSpec or dialog document.

The Companion MUST reserve enough authenticated-welcome headroom for a full
`input_state` and every reportable surface history it promises to retain. Let
`B` be the UTF-8 byte length of a prospective complete JSON-RPC welcome response
body using the longest legal request ID and `input_state: {}`. Every fixed
member MUST use its maximum legal encoded size, including the bounded
`server.name` and `server.version` strings. Every other variable member MUST
use its largest state the implementation can report: a
worst-case `surfaces` object with `max_surface_ids` distinct maximum-length IDs,
maximum revisions, and the longer encoded `present` value;
`queued_events: max_queued_events`; and the maximal union of grants, profiles,
conditional limits, and device entries that any supported `wants` and platform
permission state can produce. At startup and before enlarging that supported
maximum, it MUST ensure:

```text
B + limits.max_input_state_bytes - 2 <= limits.max_frame_bytes
```

The subtraction replaces the two encoded bytes of `{}` already counted in
`B`. `max_surfaces` MUST NOT exceed `max_surface_ids`. This reservation covers
surface histories, profiles, limits, and the complete device report, counted at
`max_device_report_bytes`, before any surface is admitted. The Companion MUST advertise a bounded supported subset of
optional registry and device entries when necessary; it MUST NOT produce a
welcome that depends on truncation. Queue admission up to
`max_queued_events`, any supported negotiation result, and any permission-state
change MUST remain inside the reservation. If a later platform change would
otherwise break it, the Companion MUST reduce only optional advertised entries
to its already reserved supported maximum; it MUST NOT discard surfaces,
drafts, or durable events.

Every `limits` value MUST be a positive safe integer under Section 4.2.
`max_triggers` is the size of the complete trigger replace-set;
`max_reminders` is the total across all owners for the pairing identity;
`max_editor_sessions` is the number of distinct synchronized-editor
presentation identities currently present in accepted surface or dialog
documents on one connection, including identities whose `edit.open` is pending
until `READY`;
`max_dialogs` is the number of concurrently outstanding dialog requests;
`max_pie_menus` is the number of distinct simultaneously open menu IDs;
and `max_shortcuts` is the size of one identity-owned dynamic shortcut set. A
replace-set operation MUST account for retained entries outside the owner being
replaced before accepting a total-limit result.

## 5. Transport profiles

### 5.1 Profile invariance

Transport facts do not change endpoint authority or method direction. Emacs
MUST send `session.hello` after a transport connection is established,
regardless of which endpoint bound or dialed the underlying transport.

Only `android-loopback-tcp` is defined by this document. A future WebSocket,
Unix-domain-socket, or other profile MUST completely define its addressing,
framing, authentication floor, connection initiator, and failure behavior
before an implementation advertises that profile.

### 5.2 `android-loopback-tcp`

| Property | Requirement |
|---|---|
| Binder | Companion endpoint |
| Dialer | Emacs endpoint |
| Default address | `127.0.0.1` |
| Default port | `8765` |
| Framing | Section 6 Content-Length framing |
| Authentication floor | Section 9 mutual HMAC authentication |

The Companion MUST bind only to an IP loopback interface. It MUST NOT bind an
EBP listener to `0.0.0.0`, a LAN address, or another externally reachable
address under this profile. An implementation MAY make the port configurable;
if it does, endpoint discovery is an out-of-band profile parameter and MUST be
shown in the Companion's pairing UI.

The `android-loopback-tcp` core profile permits exactly one paired Emacs
authority and one authenticated authoritative session at a time. Creating a new
pairing MUST first revoke the old pairing under Section 9.1. When a new session
authenticates successfully, the Companion MUST terminate the older session
before the new session enters `SYNCING`. A future multi-authority profile MUST
define active-identity selection, visible-surface and theme ownership, trigger
execution, and platform-artifact namespacing; this profile does not.

This profile authenticates endpoints but does not encrypt messages. An
implementation requiring confidentiality against privileged local software
MUST use a transport profile that provides it.

### 5.3 `android-loopback-tcp` wake

The Companion MUST grant `offline.wake` only when the user has configured an
OS-local, explicit wake target for the paired Emacs host. The target MUST name
an exact application component or comparably narrow platform endpoint; an
implicit broadcast, shell command, URI handler, or network destination MUST NOT
be used. The wake signal MAY identify the non-secret pairing ID but MUST NOT
contain the token, event payload, captured fields, or authentication proof.

After durably admitting a `wake` event, the Companion MAY signal that target to
ask Emacs to dial the loopback listener. It MUST coalesce signals for the same
pairing identity, MUST NOT signal more than once in 60 seconds, and MUST stop
waiting after 10 seconds. Failure to reach `READY` is not event rejection: the
record remains in normal FIFO order for later replay. Granting `offline.wake`
promises only this bounded attempt, not background-execution privileges or a
successful connection.

Immediately before each signal, the Companion MUST re-check that the exact
user-approved target is still configured for the current pairing identity. If
authorization was removed after a descriptor was cached, the Companion MUST
NOT signal the former target; it MUST retain the already admitted event as an
ordinary `queue` event and SHOULD show a non-sensitive local diagnostic.

## 6. Content-Length framing

### 6.1 Sender syntax

A sender MUST emit exactly this mandatory header line followed by an empty
line and the JSON body:

```text
Content-Length: <decimal-octet-count>\r\n
\r\n
<UTF-8 JSON body>
```

The sender MUST use the ASCII spelling `Content-Length`, one ASCII space after
the colon, an unsigned decimal integer with no leading zeroes except the value
`0`, and CRLF line endings. The sender MUST NOT emit more than one
`Content-Length` field. It SHOULD NOT emit any additional header field.

`Content-Length` MUST equal the number of octets in the UTF-8-encoded JSON body.
It excludes every header octet and both terminating CRLF pairs. A sender MUST
compute the length after UTF-8 encoding, not from characters, UTF-16 code units,
or display columns.

### 6.2 Receiver behavior

A receiver MUST parse header field names case-insensitively. It MAY accept
optional horizontal whitespace around a header value. It MUST reject a signed,
fractional, empty, non-decimal, or overflowing `Content-Length` value.

A receiver MAY ignore an unknown syntactically valid ASCII header field. It
MUST close the transport connection when the header section:

- lacks `Content-Length`;
- contains more than one `Content-Length`;
- exceeds 8,192 octets;
- contains a malformed header line; or
- declares a body larger than 4,194,304 octets.

On an oversized declaration, the receiver SHOULD close immediately instead of
reading and discarding the declared body. This prevents an attacker from
holding the connection open with an unbounded discard.

When such a close is triggered by a complete, well-formed header section — a
single valid `Content-Length` declaring a body above the body cap, or a
well-formed header section that exceeds the 8,192-octet header cap — the
receiver knows the exact framing fault and its send direction is unaffected.
Where the session permits `log.error` (the `SYNCING` or `READY` states of
Section 11), the receiver SHOULD emit one diagnostic naming the fault
immediately before it closes, using the shape and rate limit of Section 22.3:

```json
{"jsonrpc":"2.0","method":"log.error","params":{
  "code":1400,
  "message":"Frame exceeds size cap",
  "data":{"kind":"frame-too-large"}}}
```

The `data` object MAY also carry `bytes` (the declared or observed octet count)
and `max` (the exceeded cap). The receiver MUST still close immediately; this
`log.error` MUST NOT delay the close, resume reading or discarding an oversized
body, or otherwise weaken the close obligations above. The receiver MUST NOT
emit the diagnostic when the fault leaves the stream desynchronized or its cause
ambiguous — a missing or duplicate `Content-Length`, a malformed header line, an
unterminated header section, or EOF within a frame — nor before authentication;
in each of those cases it closes silently. Code `1400` is diagnostic-only: the
oversized body is never parsed, so no request id exists to answer, and `1400`
MUST appear only as a `log.error` param and MUST NOT be returned as a JSON-RPC
`error` response.

The receiver MUST read exactly the declared number of body octets. It MUST
retain incomplete header and body data across ordinary transport reads. EOF in
the middle of a frame terminates the session; the receiver MUST NOT attempt to
resynchronize by scanning arbitrary body bytes.

One frame contains exactly one JSON-RPC Message object. Top-level arrays are
prohibited, including JSON-RPC batches. After reading a complete body:

- invalid UTF-8 or invalid JSON MUST produce a JSON-RPC Parse Error with
  `id: null` when a response can still be sent safely;
- a top-level array or non-object JSON value MUST produce one Invalid Request
  response with `id: null`; and
- the receiver MAY continue the connection after either error.

The receiver obligations of this section, together with Section 4.1's
duplicate-member and encoding rejections, are REQUIRED for the Companion: it
accepts connections and faces Section 24.6's adversarial vectors. For the
Emacs endpoint they are RECOMMENDED: Emacs dials only its authenticated
Companion and MAY delegate framing and message decoding to a host-platform
JSON-RPC library — such as core Emacs `jsonrpc.el` — accepting that
library's tolerances. No sender obligation in Section 6.1 is relaxed by this
paragraph.

## 7. JSON-RPC 2.0 conventions

### 7.1 Message classes

EBP uses JSON-RPC 2.0 bidirectionally. A request contains `jsonrpc`, `id`,
`method`, and `params`. A notification omits `id`. A successful response
contains `jsonrpc`, `id`, and `result`. An error response contains `jsonrpc`,
`id`, and `error`.

Every EBP request MUST receive exactly one response unless the connection dies
first. The response MUST contain exactly one of `result` or `error`. A
successful operation with no return data MUST use `result: {}`. `null` MUST NOT
be used as a generic success result.

A notification MUST NOT receive a JSON-RPC response. A method's request or
notification class is fixed by the method registry in Section 11.

`params` MUST be a JSON object. A method with no parameters MUST send
`params: {}`. Positional parameter arrays are prohibited.

### 7.2 Request IDs

A request ID MUST be either a JSON string or a JSON integer. A string ID MUST
be an identifier under Section 4.4 of at most 64 ASCII octets and MUST NOT be
empty. An integer ID MUST be a safe integer under Section 4.2. `null` and
fractional numbers MUST NOT be used. A request ID MUST be unique among that
sender's outstanding requests on the connection and MAY be reused after its
request has concluded. A host JSON-RPC library that allocates sequential
integer IDs per connection — such as core Emacs `jsonrpc.el` — therefore
conforms without adaptation.

Request IDs are connection-scoped and are not durable delivery identifiers.
Every outstanding request fails locally when the connection closes. A durable
event MUST retain its `event_id` across reconnections even though its JSON-RPC
request ID changes.

### 7.3 Dispatch, direction, and unknown methods

A receiver MUST verify the method's sender, class, allowed session state, and
parameters before invoking a handler.

- An unknown request MUST receive `-32601 Method not found`.
- An unknown notification MUST be logged and ignored.
- A request sent by the wrong endpoint or in the wrong class MUST receive
  `-32600 Invalid Request`.
- A notification sent by the wrong endpoint or in the wrong class MUST be
  logged and ignored. Repeated violations MAY cause the receiver to close the
  connection.
- Structurally invalid request parameters MUST receive `-32602 invalid-params`.
- Structurally invalid notification parameters MUST be reported through
  `log.error` when authenticated and otherwise MUST be logged and dropped.

### 7.4 Ordering and concurrency

Each endpoint MUST parse frames in wire order. Each endpoint MUST dispatch
session-state transitions, surface mutations, `state.changed`, durable events,
and editor-stream operations in receive order within their applicable ordered
channel.

Independent requests MAY execute concurrently. Responses MAY be returned in an
order different from their requests. A method that mutates an ordered channel
MUST NOT be made observable out of order merely because its internal work ran
concurrently.

TCP byte ordering does not by itself satisfy these application-order rules.

### 7.5 Cancellation

After authentication, either endpoint MAY send `rpc.cancel` for an outstanding
request it originated.
Its params MUST be `{id}` where `id` is the exact string request ID being
cancelled. A malformed cancellation notification MUST be logged and ignored.
The receiver SHOULD stop work when cancellation is safe. If cancellation takes
effect, the original request MUST conclude with error `1301 request-cancelled`.
If the request already completed, the cancellation MUST be ignored. Cancellation
of an unknown ID MUST be ignored. Cancellation does not roll back side effects
already committed.

## 8. Error model

An EBP-defined error MUST use a numeric JSON-RPC `error.code`, a concise
human-readable `error.message`, and an `error.data` object containing the stable
string member `kind`. Additional `data` members MAY supply a remedy or context.
One code below is diagnostic-only: it is carried in a `log.error` param
(Section 22.3) and is never returned as a response `error.code`.

| Code | `data.kind` | Meaning |
|---:|---|---|
| `-32700` | `parse-error` | JSON-RPC Parse Error |
| `-32600` | `invalid-request` | JSON-RPC Invalid Request |
| `-32601` | `method-not-found` | JSON-RPC Method not found |
| `-32602` | `invalid-params` | JSON-RPC Invalid params |
| `-32603` | `internal-error` | JSON-RPC Internal error |
| `1001` | `cap-unsupported` | Capability was not advertised or is unavailable |
| `1002` | `cap-permission` | User or platform permission is required |
| `1003` | `cap-failed` | Advertised capability failed |
| `1101` | `triggers-rejected` | Trigger replace-set was rejected atomically |
| `1200` | `not-authenticated` | Method is not legal before authentication |
| `1201` | `content-invalid` | Structurally valid params contain an invalid surface, node, action, or module object |
| `1202` | `protocol-version` | No compatible protocol major version exists |
| `1203` | `auth-failed` | Authentication proof failed |
| `1204` | `session-state` | Method is not legal in the current session state |
| `1301` | `request-cancelled` | Request was cancelled |
| `1400` | `frame-too-large` | Frame exceeds the header or body size cap; diagnostic-only, see Section 6.2 |
| `1401` | `overloaded` | Bounded processing capacity was exhausted |
| `1500` | `event-retry` | Event could not be accepted yet and remains eligible for retry |
| `1600` | `queue-busy` | A queue replay is already active |
| `1601` | `queue-full` | Durable queue capacity is exhausted |

Error `1002` SHOULD include `data.permission` and MAY include
`data.settings`, which the caller can pass to an advertised settings-opening
capability. Error `1201` SHOULD include the rejected object path. An
implementation MUST NOT include secrets, password values, clipboard contents,
SMS bodies, or other sensitive values in an error.

Framing failures that force connection closure are transport errors and do not
require a JSON-RPC response. A receiver MAY name a size-cap framing failure to
its peer with the diagnostic-only code `1400 frame-too-large` on `log.error`
before closing, as Section 6.2 specifies. An endpoint MUST NOT recursively
answer a malformed `log.error` with another `log.error`.

## 9. Pairing and mutual authentication

### 9.1 Pairing token

The Companion MUST generate two independent values with a cryptographically
secure random number generator:

- a 16-octet secret pairing token; and
- a 16-octet non-secret pairing ID.

The pairing token MUST be displayed as the 22-character [RFC4648] base64url
encoding of those 16 octets with `=` padding omitted. Both endpoints MUST decode
that exact representation to the original 16 raw octets and MUST use those raw
octets as the HMAC key. The pairing ID MUST be displayed and transmitted as 32
lowercase hexadecimal characters.

The token MUST be stored in storage private to each endpoint, MUST NOT cross the
EBP wire, and MUST NOT appear in logs, errors, Goldens, or crash reports. The
pairing ID is not secret and selects the correct token and persistent state
partition without trial-HMAC against unrelated tokens.

The Companion MUST provide explicit pairing revocation. Revocation MUST
atomically fence the identity from new authentication, close its active
sessions, erase its token, queued payloads, input drafts, cached surfaces,
tombstones, themes, reminders, triggers, and
identity-scoped shortcuts, and withdraw identity-scoped visible artifacts where
the platform permits. Re-pairing creates a new pairing ID and an empty state
partition.

The Emacs endpoint MUST likewise provide local removal of a pairing and erase
its token and EventId receipt records when the user invokes it. Revocation at
one endpoint closes or prevents future authentication but cannot erase storage
on a disconnected peer; user interfaces SHOULD make that limitation explicit.

The Companion MUST rate-limit failed proofs per pairing ID and source process
or connection. It MUST NOT reveal whether an unknown pairing ID or an incorrect
proof caused authentication failure.

### 9.2 Handshake messages

After transport establishment, Emacs MUST send `session.hello` as the first EBP
request:

```json
{
  "protocol": 2,
  "client": {"name": "example-emacs-client", "version": "1.0.0"},
  "pairing_id": "89abcdef0123456789abcdef01234567",
  "client_nonce": "0123456789abcdef0123456789abcdef",
  "wants": ["surfaces.dialog", "theme"]
}
```

The params schema is:

| Member | Type | Required | Constraint |
|---|---|---:|---|
| `protocol` | integer | yes | MUST equal `2` |
| `client` | object | yes | Exactly `name` and `version`, each a non-empty string of at most 128 UTF-8 octets |
| `pairing_id` | 32 lowercase hex characters | yes | Selects the pairing identity |
| `client_nonce` | 32 lowercase hex characters | yes | Fresh CSPRNG nonce |
| `wants` | array of capability identifiers | yes | Distinct values, at most 128 entries |

Unknown optional hello members MUST be ignored under Section 12. Duplicate
capability names make the params invalid. A protocol mismatch MUST receive
`1202 protocol-version`; another invalid hello field MUST receive `-32602`.

The Companion MUST create a fresh server nonce and return:

```json
{"server_nonce":"fedcba9876543210fedcba9876543210"}
```

Emacs MUST then send `auth.response` with both nonces and its proof. Each nonce
MUST encode 16 cryptographically random octets as 32 lowercase hexadecimal
characters and MUST be used for only one transport connection.

### 9.3 Proof construction

Let `TOKEN` be the 16 decoded raw pairing-token octets, `PAIRING_ID` the
32-character pairing ID, `CNONCE` the 32-character client nonce, and `SNONCE`
the 32-character server nonce. Concatenation below contains ASCII bytes exactly
as printed and no trailing NUL or newline.

```text
client_proof = lowercase-hex(
  HMAC-SHA256(TOKEN, "EBP/2 client:" + PAIRING_ID + ":" + CNONCE + ":" + SNONCE))

server_proof = lowercase-hex(
  HMAC-SHA256(TOKEN, "EBP/2 companion:" + PAIRING_ID + ":" + SNONCE + ":" + CNONCE))
```

The following known-answer vector is normative:

```text
pairing_token = AAECAwQFBgcICQoLDA0ODw
PAIRING_ID    = 101112131415161718191a1b1c1d1e1f
CNONCE        = 202122232425262728292a2b2c2d2e2f
SNONCE        = 303132333435363738393a3b3c3d3e3f
client_proof  = 03e270fd0af4566336283444b641a722b5828c190ebdbe3dc50c5be2c9c9fb43
server_proof  = e9333d48cfc2780d708db4a9782705c5e1c988c7eedc2d1734051f2fb9be58ec
```

A conforming proof implementation MUST reproduce both proof values exactly.

`auth.response` params are:

```json
{
  "pairing_id": "89abcdef0123456789abcdef01234567",
  "client_nonce": "0123456789abcdef0123456789abcdef",
  "server_nonce": "fedcba9876543210fedcba9876543210",
  "client_proof": "<64 lowercase hexadecimal characters>"
}
```

Every member is REQUIRED. The echoed pairing ID and both nonces MUST exactly
match this connection's pending challenge. Extra optional members MUST be
ignored. A request that fails the declared JSON type, length, or character
grammar MUST receive `-32602` followed by connection close. A well-formed but
reused, mismatched, or incorrect proof or nonce MUST receive `1203` followed by
connection close.

Both endpoints MUST compare well-formed proofs in constant time. The Companion
MUST reject an absent or malformed proof as invalid params and a well-formed
reused, mismatched, or incorrect proof as `1203 auth-failed`; it MUST then close
the connection. Emacs MUST verify
`server_proof` before trusting any welcome data and MUST close the connection
if verification fails.

This handshake proves knowledge of the selected token and binds the pairing ID,
both endpoint nonces, and protocol major. It does not encrypt later traffic or
authenticate each individual message against an active privileged local
man-in-the-middle. That attacker is outside the threat model of
`android-loopback-tcp`; a deployment that includes it MUST use a stronger
transport profile.

## 10. Session lifecycle and negotiation

### 10.1 States

Each open connection has exactly one non-terminal state:

```text
CONNECTED -> CHALLENGED -> SYNCING -> READY
     \             \           \         \
      +-------------+-----------+-----------> CLOSED
```

| State | Legal traffic |
|---|---|
| `CONNECTED` | Emacs MAY send only `session.hello`. |
| `CHALLENGED` | Emacs MAY send only `auth.response`. |
| `SYNCING` | Emacs reconciles cached surfaces and input state, requests queue replay, then sends `session.ready`. The Companion MUST withhold newly generated remote events. |
| `READY` | All negotiated methods are legal according to the method registry. |
| `CLOSED` | No EBP message is legal. |

Framing and the basic JSON-RPC object shape MUST be validated before session
state. In `CONNECTED`, a structurally valid request other than `session.hello`
MUST receive `1200 not-authenticated`, even when its method is unknown or its
direction would later be invalid. In `CHALLENGED`, the same rule applies to a
request other than `auth.response`. A legal handshake method with malformed
params MUST receive `-32602`. Before authentication, all notifications MUST be
logged locally and dropped without `log.error`.

After authentication, a method illegal in the current state MUST receive
`1204 session-state` when it is a request and MUST be logged and dropped when it is a
notification. Authentication failure, timeout, framing failure, transport loss,
explicit replacement by a newer authenticated session, and local shutdown MAY
transition directly from any state to `CLOSED`. A failed handshake MUST NOT be
retried on the same connection.

The handshake SHOULD complete within 10 seconds of transport establishment.
Either endpoint MAY close an incomplete handshake after a finite local timeout,
but MUST NOT use a timeout shorter than 10 seconds. A 30-second close deadline
is RECOMMENDED.

### 10.2 Welcome

On successful `auth.response`, the Companion returns:

```json
{
  "server_proof": "<64 lowercase hexadecimal characters>",
  "server": {"name": "example-companion", "version": "1.0.0"},
  "protocol": 2,
  "granted": ["surfaces.dialog", "theme"],
  "surface_profiles": {
    "app": {
      "node_types": ["text", "row", "column", "box", "spacer", "divider", "button", "text_input"],
      "builtins": ["view.switch", "companion.settings.open"],
      "features": []
    },
    "dialog": {
      "node_types": ["text", "row", "column", "button", "text_input"],
      "builtins": ["dialog.submit", "dialog.dismiss"],
      "features": []
    }
  },
  "surfaces": {
    "app:main": {"revision": 41, "present": true},
    "app:old": {"revision": 9, "present": false}
  },
  "queued_events": 2,
  "input_state": {"app:main": {"title": "offline draft"}},
  "limits": {
    "max_frame_bytes": 4194304,
    "max_queued_events": 1024,
    "max_queued_bytes": 8388608,
    "max_event_bytes": 262144,
    "max_surfaces": 64,
    "max_surface_ids": 4096,
    "max_field_bytes": 65536,
    "max_input_state_bytes": 1048576,
    "max_capture_fields": 64,
    "max_dialogs": 4
  }
}
```

The result MUST contain `server_proof`, `protocol`, `server`, `granted`,
`surface_profiles`, `surfaces`, `queued_events`, and `limits`.
`input_state` MUST be omitted when empty. `device` MUST be omitted unless
`capabilities` or `triggers` was granted.

The welcome members have these schemas:

| Member | Normative shape |
|---|---|
| `server_proof` | 64 lowercase hexadecimal HMAC-SHA256 proof |
| `protocol` | integer `2` |
| `server` | object containing exactly `name` and `version`, each a non-empty string of at most 128 UTF-8 octets |
| `granted` | array of distinct capability identifiers |
| `surface_profiles` | target-profile map defined below |
| `surfaces` | object mapping Surface IDs to `{revision, present}`, where `revision` is a non-negative integer and `present` is boolean |
| `queued_events` | non-negative integer count of retained durable events for this pairing identity |
| `input_state` | object mapping present Surface IDs to objects mapping stateful node IDs to their latest non-password JSON values |
| `limits` | limits object defined in Section 4.5 |
| `device` | device report defined in Section 20.1 |

Every `input_state` value MUST have the JSON type required by its node type and
MUST fit `max_field_bytes`, and the complete object MUST fit
`max_input_state_bytes` under Section 4.5's limit encoding. Before accepting a
non-password user change that would enlarge retained input state beyond that
aggregate limit, the Companion MUST refuse the change, preserve the preceding
logical and native value, and show a local validation diagnostic. A
size-reducing change remains legal. It MUST NOT silently discard another
field's newer draft to make room. Passwords MUST be absent. A surface tombstone MUST
NOT have input state. `queued_events` MUST equal the count visible to the next
`queue.replay`; it MUST NOT include expired records that the Companion has
already identified for deletion.

`wants` is the set of optional capabilities requested by Emacs. `granted` MUST
be its intersection with the Companion's supported capability set. Unknown
requested capabilities MUST be omitted from `granted`. Emacs MUST NOT invoke a
capability-gated method or emit capability-gated content unless the capability
was granted.

`surface_profiles` maps presentation targets to positive-knowledge profiles.
`app` is REQUIRED. `notification`, `widget`, `tile`, and `dialog` are REQUIRED
only when the corresponding surface capability was granted. Each profile MUST contain
distinct `node_types`, `builtins`, and `features` arrays and MUST list exactly
what the Companion will honor on that target during this session. Emacs MUST
gate every emitted node, builtin, and constraining feature against the target
profile and MUST NOT interpret a missing profile or list as support for
everything.

The applicable target is `app` for `app:*`, `notification` for
`notification:*`, `widget` for `widget:*`, `tile` for `tile:*`, and `dialog` for
`dialog.show`.

The `app` profile MUST contain the Core Node Set, `view.switch`, and
`companion.settings.open`. The `dialog` profile MUST contain `dialog.submit`
and `dialog.dismiss`. A notification or home-widget profile MAY expose a much
smaller node and action vocabulary than `app`; support in one profile MUST NOT
be inferred in another.

### 10.3 Synchronization barrier

After verifying the welcome, Emacs MUST perform these steps in order:

1. absorb the surface revision and tombstone floors;
2. merge `input_state` into its UI-state store;
3. send required surface updates or removals using revisions above the reported
   floors, reflecting retained input drafts where applicable;
4. call `queue.replay` and wait for it to conclude; and
5. call `session.ready`.

A replay that returns with `remaining > 0` because of a well-formed transient
error has concluded for purposes of this barrier. Emacs MAY proceed to
`session.ready`, but MUST preserve the backlog's FIFO priority and SHOULD retry
replay in `READY` as required by Section 15.3.

The Companion MUST enter `READY` only after `session.ready` succeeds. While in
`SYNCING`, it MUST NOT deliver newly generated remote events ahead of replayed
events. It MUST apply each action's offline policy and retain eligible events
behind the replay barrier.

`session.ready` params and result are both `{}`. On entering `READY`, the
Companion MUST serialize the successful `{}` response ahead of every frame
whose method is legal only in `READY`. Emacs MUST enter `READY` when it receives
that successful response; the Companion MAY enter `READY` once the response is
committed to an outbound order that guarantees those bytes come first. The
Companion MUST then clear the surface-disconnection staleness timer and MUST
immediately flush as ordered `state.changed` notifications every divergent
non-password value changed after the welcome snapshot or during `SYNCING`,
using the accepted revision currently shown, even when no event is pending.
Only after that flush MAY it release newly generated events under Section
15.3's durable-backlog
ordering rules.

### 10.4 Reconnection

Every transport reconnection MUST perform a fresh handshake with fresh nonces.
Request IDs and negotiated grants do not survive a connection. A grant controls
what the current session may send; its absence does not by itself erase a
previously accepted persistent surface, theme, reminder, or trigger. Emacs MAY
always send a revisioned `surface.remove` for a surface reported in the welcome,
even when it did not request that surface's presentation capability. To modify
or recreate other persistent module state, Emacs MUST negotiate that module.

Cached surfaces,
surface revision floors, tombstones, eligible input drafts, trigger and reminder
registrations, queued events, and event-delivery IDs MUST survive according to
their module rules.

When a `READY` connection closes, the Companion MUST persist the disconnection
time before accepting new offline interactions. If the Companion itself
restarts while disconnected, it MUST restore that time or conservatively use
the earliest time it can prove.

## 11. Method registry

“Emacs” and “Companion” identify the permitted sender. `S` means `SYNCING`; `R`
means `READY`.

| Method | Sender | Class | State | Capability | Section |
|---|---|---|---|---|---|
| `session.hello` | Emacs | request | `CONNECTED` | core | 9 |
| `auth.response` | Emacs | request | `CHALLENGED` | core | 9 |
| `session.ready` | Emacs | request | `SYNCING` | core | 10 |
| `surface.update` | Emacs | request | S, R | core / surface capability | 13 |
| `surface.remove` | Emacs | request | S, R | core for reported surfaces | 13 |
| `queue.replay` | Emacs | request | S, R | core | 15 |
| `event.action` | Companion | request | S, R | core | 14–15 |
| `state.changed` | Companion | notification | R | core | 14 |
| `dialog.show` | Emacs | request | R | `surfaces.dialog` | 18 |
| `toast.show` | Emacs | notification | R | `presentation.toast` | 18 |
| `pie_menu.show` | Emacs | notification | R | `presentation.pie-menu` | 18 |
| `pie_menu.dismiss` | Emacs | notification | R | `presentation.pie-menu` | 18 |
| `theme.set` | Emacs | notification | S, R | `theme` | 18 |
| `reminders.set` | Emacs | request | S, R | `reminders.owner` | 18 |
| `edit.open` | Companion | notification | R | `editor.sync` | 19 |
| `edit.delta` | Companion | notification | R | `editor.sync` | 19 |
| `edit.caret` | Companion | notification | R | `editor.sync` | 19 |
| `edit.close` | Companion | notification | R | `editor.sync` | 19 |
| `edit.complete` | Companion | request | R | `editor.sync` | 19 |
| `edit.resync` | Emacs | request | R | `editor.sync` | 19 |
| `edit.apply` | Emacs | request | R | `editor.sync` | 19 |
| `diagnostics.show` | Emacs | notification | R | `editor.sync` | 19 |
| `eldoc.show` | Emacs | notification | R | `editor.sync` | 19 |
| `fontify.show` | Emacs | notification | R | `editor.sync` | 19 |
| `capability.invoke` | Emacs | request | R | `capabilities` | 20 |
| `triggers.set` | Emacs | request | S, R | `triggers` | 21 |
| `log.error` | Either | notification | S, R | core | 8, 22.3 |
| `rpc.cancel` | Either | notification | S, R | core | 7 |

An implementation MUST NOT add a method to this registry without specifying
its sender, class, legal states, capability gate, complete parameter/result
schema, errors, ordering, atomicity, and retry behavior.

## 12. Versioning and compatibility

`protocol` is the EBP wire major. This document defines major `2`. A Companion
MUST reject another major with `1202 protocol-version` and SHOULD include
`data.supported: [2]`. A sender MUST NOT infer wire compatibility from an
implementation version, document version, or `contract.json` format version.

Within one protocol major, compatible growth MUST use positive capability,
feature, node-type, trigger-type, state-type, or device-capability discovery.
New optional cosmetic fields MAY be added without a major bump.

Extensible objects follow these rules:

1. A receiver MUST ignore an unknown optional member unless the object's
   section requires whole-object rejection.
2. A sender MUST NOT use an unnegotiated member whose omission would permit a
   receiver to perform a broader, less safe, or semantically different action.
3. Such a constraining member MUST have a positive feature advertisement, and
   a sender MUST omit the entire dependent behavior when the feature is absent.
4. Unknown request methods receive `-32601`; unknown notifications are ignored.
5. Unknown node types degrade according to Section 16.2.
6. Unknown enum values MUST NOT be guessed. The applicable schema MUST either
   define a safe fallback or require rejection of the containing object.

Method, capability, feature, action, and extension names SHOULD use lowercase
dot-separated namespaces. Names beginning `ebp.` are reserved for this
specification. Implementations MUST NOT claim another implementation's
namespace.

## 13. Surfaces

### 13.1 Surface namespaces

A surface ID selects a presentation target:

| ID pattern | Target | Requirement |
|---|---|---|
| `app:<name>` | Full-screen in-application UI | core |
| `notification:<name>` | System notification | `surfaces.notification` |
| `widget:<name>` | Home-screen widget | `surfaces.widget` |
| `tile:<name>` | Quick-Settings tile slot | `surfaces.tile` |

`<name>` MUST be non-empty and use Section 4.4's allowed identifier characters.
The complete prefixed Surface ID MUST satisfy Section 4.4's 128-octet limit, so
the available name length is reduced by the selected prefix. An implementation
MUST support at least one `app:*` surface. Emacs MUST
select nodes, builtins, and features from the corresponding welcome
`surface_profiles` entry. `surface.update` MUST reject a namespace whose
required capability/profile was not granted; `surface.remove` remains legal for
any surface reported in the welcome so stale persistent state can be retired.

One surface is owned by the pairing identity and has one ordered history of
snapshots and tombstones. Emacs MUST assign revisions monotonically per surface
and MUST persist its next revision. Gaps are allowed. Revisions MUST NOT wrap.

`max_surfaces` counts only currently present snapshots. `max_surface_ids` counts
every distinct Surface ID with a retained snapshot or tombstone. A never-seen
Surface ID has a conceptual revision floor of `-1`, so any first non-negative
revision is newer. A Companion
MUST retain each tombstone revision floor until pairing revocation and MUST NOT
reclaim it merely to admit a reused or new ID. At either limit, an update or
remove request that would increase the corresponding count MUST receive
`1201 content-invalid` with `data.reason: "surface-limit"`; updates and removals of
already known IDs remain legal only when they do not increase the saturated
count. In particular, reactivating a tombstone is invalid at `max_surfaces`,
while updating a present snapshot or removing a known ID remains legal. Emacs
SHOULD use stable names and MUST NOT churn Surface IDs as a substitute for
revisions.

### 13.2 `surface.update`

`surface.update` atomically replaces one complete surface snapshot.

| Member | Type | Required | Meaning |
|---|---|---:|---|
| `surface` | Surface ID | yes | Target surface |
| `revision` | non-negative integer | yes | Revision of this replacement |
| `spec` | SurfaceSpec | yes | Complete declarative snapshot |
| `stale_after_s` | positive integer | no | Disconnected duration after which stale presentation begins |
| `stale_spec` | SurfaceSpec | no | Whole replacement shown after staleness begins |
| `current_view` | identifier | no | Explicit multi-view navigation request |
| `reset_input_ids` | array of widget IDs | no | Locally dirty inputs that Emacs explicitly replaces |

`reset_input_ids` values MUST be distinct and MUST name non-password stateful
nodes in the submitted `spec`; another value makes the request invalid. An
`editor` with `document` MUST NOT appear in `reset_input_ids`, even when
`publish_state` is true; its text can change only through Section 19.

The Companion MUST validate the entire request before changing persistent or
visible state. If the content is invalid, it MUST return
`1201 content-invalid`, MUST leave the previous snapshot unchanged, and SHOULD name
the failing object path in `error.data.path`.

If `revision` is greater than the stored snapshot or tombstone revision, the
Companion MUST persist and atomically present the snapshot, then return:

```json
{"status":"applied","revision":42,"present":true}
```

If `revision` is less than or equal to the stored revision, the Companion MUST
leave state unchanged and return:

```json
{"status":"stale","revision":42,"present":true}
```

A stale result is a benign idempotency result, not a JSON-RPC error. The result
revision and `present` MUST describe the Companion's current revision floor and
snapshot/tombstone state for that surface.

An applied result additionally acts as a `state.changed` barrier for the
target surface: Section 14.6's reconciliation rules require the Companion to
flush or discard pending input-state notifications before returning it.

### 13.3 `surface.remove`

`surface.remove` params are `{surface, revision}`. Removal is a revisioned
tombstone, not an unversioned deletion.

If the removal revision is newer than the stored floor, the Companion MUST
remove the visible and cached snapshot, persist a tombstone at that revision,
and return `{status:"applied", revision, present:false}`. It MUST also delete
that surface's input drafts and local presentation state. If it is not newer,
the Companion MUST return
`{status:"stale", revision:<current floor>, present:<current state>}` without
changing state.

The Companion MUST retain enough tombstone information to prevent a delayed
older update from recreating the surface. The authenticated welcome MUST report
both present snapshots and tombstones.

### 13.4 Surface specification shapes

The namespace determines the exact SurfaceSpec variant:

| Namespace | Schema |
|---|---|
| `app:*` | One root Node or the multi-view object below |
| `notification:*` | `{body: Node, meta?}` from Section 18.5; multi-view is prohibited |
| `widget:*` | `{title: string, body: Node, empty?: Node, header_action?: ActionDescriptor}`; multi-view is prohibited |

`stale_spec`, when supplied, MUST use the same variant as `spec`.
`current_view` is valid only for a multi-view `app:*` spec. Any other
combination MUST receive `1201 content-invalid`.

An app multi-view object is:

```json
{
  "views": {
    "list": {"t":"column","children":[]},
    "detail": {"t":"column","children":[]}
  },
  "initial_view": "list"
}
```

`views` MUST be a non-empty object whose keys are identifiers and whose values
are root Nodes. `initial_view` MUST name an existing view. An update's optional
`current_view` MUST name an existing view.

The Companion MUST preserve its current local view across updates while that
view still exists. It MUST change views because of an update only when:

- the current view no longer exists, in which case it selects `initial_view`;
- the surface is new, in which case it selects `initial_view`; or
- the request includes `current_view`.

Background refreshes SHOULD omit `current_view` so they do not take navigation
away from the user.

### 13.5 Cached and stale presentation

The Companion MUST persist the latest accepted snapshot for each present
surface and SHOULD render it while Emacs is disconnected.

If `stale_after_s` is absent, the snapshot never becomes stale solely because
of disconnection. If present, its clock starts when the preceding `READY`
session disconnects, MUST survive Companion process death, and ends only when a
new session reaches `READY`.

After the duration elapses, the Companion SHOULD indicate staleness visibly. If
`stale_spec` is present, it SHOULD render that complete specification instead.
Staleness is a presentation state, not authorization or correctness. Actions
inside `stale_spec` remain governed by their own offline policies and the
event's `revision_seen`.

`stale_spec` MUST NOT contain a stateful node or any `editor`, regardless of
`publish_state` or `document`. The accepted primary `spec`
remains the sole schema and storage owner for `(surface, id)` drafts while the
stale presentation is visible. This prevents an alternate document from
retyping or aliasing cached input state.

Emacs MUST NOT rely on `stale_spec` to remove a dangerous control. A Companion
that does not understand a future stale-presentation feature could otherwise
leave the original control available. Dangerous behavior MUST be constrained
by the action descriptor itself.

### 13.6 Input draft reconciliation

For each stateful node, the Companion MAY hold a locally dirty value newer than
the last value declared by Emacs. A new surface snapshot MUST NOT overwrite
that dirty value merely because the snapshot was refreshed.

The Companion MUST clear a dirty value when any of these occurs:

- a later snapshot carries the same value, acknowledging it;
- the node ID disappears from the accepted snapshot;
- the same ID is reused for a different node type or incompatible value schema;
- the ID appears in `reset_input_ids`.

Value-schema compatibility is exact:

- `text_input` requires a string, `password: false` in both snapshots, and no
  U+000A when the new node is `single_line`;
- `checkbox` and `switch` remain compatible with the same node type because
  their value is boolean;
- `enum_list` requires the same `multi_select` mode and every retained value to
  remain legal under the new `options` and `allow_add` rules;
- `slider` requires the retained number to remain inside the new continuous
  range or equal one of the new discrete `values`; and
- a local `editor` draft requires `publish_state: true` and no `document` in
  both snapshots. A synchronized editor never participates in draft
  reconciliation.

Anything else is incompatible. The Companion MUST erase an incompatible draft
and seed the node from the newly authored value or that node's default, without
emitting `state.changed` or a user action. A transition to password input MUST
use Section 14.6's secret-erasure rules.

Emacs SHOULD reflect welcome `input_state` values in its first synchronized
surface push. Emacs MAY use `reset_input_ids` when application policy
deliberately rejects a draft. A password value MUST never participate in this
reconciliation; Section 14.6 applies.

Node IDs are compared together with node type for draft reconciliation. Emacs
SHOULD NOT reuse a stateful ID for a different conceptual field. Tombstoning a
surface MUST erase every draft belonging to it.

### 13.7 Specialized surface metadata

Section 13.4 defines the notification and widget wrappers. `header_action`, when
present, is an ActionDescriptor. The Companion MUST NOT invent a default
header action. A widget `empty` Node is rendered only when `body` contains no
presentable content according to the widget profile.

## 14. Actions and input state

### 14.1 Remote action descriptors

A remote ActionDescriptor has this shape:

```json
{
  "action": "heading.todo-set",
  "args": {"state":"DONE"},
  "when_offline": "queue",
  "dedupe": "heading:123:todo",
  "ttl_s": 86400,
  "confirm": "Mark this item done?"
}
```

| Member | Type | Required | Default | Meaning |
|---|---|---:|---|---|
| `action` | namespaced identifier | yes | — | Emacs allowlisted semantic action |
| `args` | object | no | `{}` | Plain application data |
| `when_offline` | `drop` \| `queue` \| `wake` | no | `drop` | Delivery policy if no `READY` session exists |
| `dedupe` | identifier | no | — | Queue replacement key scoped to the pairing identity |
| `ttl_s` | integer `1..604800` | conditionally | — | Queue lifetime, required for `queue` and `wake` |
| `confirm` | non-empty string | no | — | Confirmation shown before an event is created |
| `capture_fields` | array of distinct widget IDs | no | `[]` | Stateful values to capture atomically in `event.action.fields` |

An action name MUST contain at least one dot and MUST be registered in an
explicit Emacs-side allowlist. `args` are untrusted data and MUST be validated
by the registered handler. An action name MUST NOT be passed directly to
`funcall`, shell execution, command lookup, or another ambient dispatcher.

The safe default is `when_offline: "drop"`. Emacs MUST opt in explicitly to
durable replay. It MUST NOT author `wake` unless `offline.wake` was granted.
`ttl_s` and `dedupe` MUST be absent when `when_offline` is `drop`; `ttl_s` MUST
be present for `queue` and `wake`.

`capture_fields` is valid only for a descriptor inside a surface or dialog
containing every named stateful node. Its length MUST NOT exceed
`max_capture_fields`. Each name MUST resolve to exactly one
stateful node in that document. The Companion MUST reject the containing
document when a name is absent, duplicated, or non-stateful. It MUST enforce
`max_field_bytes` while accepting user input and MUST NOT create an occurrence
whose captured field exceeds that limit; it SHOULD expose a local validation
diagnostic instead. At occurrence time, the Companion MUST copy all selected
current values into `event.action.fields` as one logical snapshot before any
dependent state can change. Section 14.6 adds stricter rules for passwords.

Any remote action whose meaning depends on a stateful node's current value MUST
name that node in `capture_fields`, unless the exact value is already a
hook-defined injected member under Section 14.3. The Emacs handler MUST use the
injected `args` member or corresponding `event.action.fields` value as the
occurrence-time fact; it MUST NOT substitute its newest `state.changed` or
welcome `input_state` value. This is REQUIRED even for `drop`, because state
notifications and action processing may be scheduled independently.

When `confirm` is present, the Companion MUST present the exact confirmation
before creating, persisting, or delivering the event. Declining MUST be a
clean no-op. The Companion MUST NOT defer this confirmation until replay and
MUST NOT infer confirmation text from a newer surface.

### 14.2 Companion-local builtins

A builtin ActionDescriptor contains `builtin` and MUST NOT contain `action`,
`args`, `when_offline`, `dedupe`, `ttl_s`, or `confirm`. It MAY contain
`capture_fields` only for `dialog.submit`. A remote descriptor contains
`action` and MUST NOT contain `builtin` or any builtin-specific top-level
parameter. The Companion MUST reject the containing document atomically when a
descriptor contains both variants, neither variant, a remote-only member on a
builtin, an unknown builtin, or invalid builtin parameters.
Emacs MUST NOT emit a builtin absent from the applicable target's
`surface_profiles.<target>.builtins` array.

| Builtin | Required members | Behavior |
|---|---|---|
| `view.switch` | `view` | Switch the current multi-view surface locally; if `READY`, report remote action `view.switched` with `args.view` and `when_offline: drop`. |
| `clipboard.copy` | `text` | Copy text through the platform clipboard. The descriptor is necessarily part of its cached document; the Companion MUST NOT create an additional private copy or log the text. Emacs SHOULD NOT author a secret here. |
| `share.send` | `text`; optional `title` | Open the platform share UI. |
| `companion.settings.open` | none | Open the Companion's own pairing, permissions, offline-state, and diagnostics UI. |
| `trigger.fire` | `id` | Fire the named `manual` trigger through Section 21's normal pipeline. |
| `dialog.submit` | optional `value` and `capture_fields` | Complete the containing `dialog.show` request as submitted. `capture_fields` obeys Sections 14.1 and 14.6. |
| `dialog.dismiss` | none | Complete the containing `dialog.show` request as dismissed. |

Builtin parameter objects are closed and use these exact types. `view` and `id`
are identifiers; `text`, `title`, and string-valued `value` are strings;
`capture_fields` is the ID array from Section 14.1; and
`dialog.submit.value`, when not a string, MAY be any non-secret JSON value that
fits the frame limits. `view.switch` is valid only inside a multi-view `app:*`
surface and `view` MUST name one of that snapshot's views. `dialog.submit` and
`dialog.dismiss` are valid only inside their containing outstanding dialog.
Every other builtin is valid only in a target profile that advertises it. An
unexpected parameter or invalid context MUST reject the containing document.

`view.switch` and `companion.settings.open` are REQUIRED in the `app` profile.
`dialog.submit` and `dialog.dismiss` are REQUIRED in the `dialog` profile.
`clipboard.copy`, `share.send`, and `trigger.fire` are OPTIONAL and MUST be
positively advertised in each profile where they are usable; `trigger.fire`
additionally requires the `triggers` capability and a registered `manual`
trigger. Builtins are the entire Companion-local control-flow vocabulary. A
Companion MUST NOT interpret arbitrary builtin names as platform commands.
Emacs core conformance includes the generated `view.switched` action and MUST
allowlist its `{view}` arguments and surface context.

### 14.3 Value injection

When an action hook produces a value, the Companion MUST inject it into a copy
of `args` under the hook's defined member. Emacs MUST NOT author a conflicting
member in the descriptor. A conflicting authored member makes the containing
surface invalid.

The injection table applies to remote ActionDescriptors. Every hook listed in
the table MUST use a remote descriptor, except that `on_submit` inside a dialog
MAY use the `dialog.submit` builtin. That exception performs no implicit value
injection; it MUST use the builtin's authored `value` or `capture_fields` when
the submitted value is required. A builtin on any other value-producing hook
is invalid.

| Hook | Injected members |
|---|---|
| `on_change`, `on_submit`, `on_save`, `on_enter`, `on_pick` | `value`, except that a password submission uses `fields` as specified below |
| `on_reorder` | `from`, `to` and, when every item has a stable authored identity, `order` |
| `swipe_start.on_trigger`, `swipe_end.on_trigger` | `direction` as `start` or `end` |
| `on_add_row`, `on_add_col` | `index` |
| `on_day_tap` | `value` as `YYYY-MM-DD` |
| `on_month_change` | `value` as `YYYY-MM` |
| `on_point_tap` | `value` as the authored point object |

Hooks without an entry in this table inject nothing.

`from`, `to`, and `index` are non-negative zero-based integers. For
`on_reorder`, `from` is the item's index before the move and `to` is that same
item's final index after removal and insertion. `order`, when present, is the
complete post-move sequence of direct-child identity objects. Each identity
object is closed and contains exactly one of `{key: identifier}` or
`{id: identifier}`, choosing `key` when the child has both. The Companion MUST
omit `order` if any reordered child lacks both authored members. For
`on_add_row` and `on_add_col`, `index` is the requested insertion slot in the
current axis: it is before the existing item at that index, and an index equal
to the current count appends.

When `capture_fields` is non-empty, the Companion MUST include exactly those
captured members in `fields`; it MUST NOT copy arbitrary form contents. A
password `text_input` MUST NOT place its value in `args.value`. Its submitting
descriptor MUST name the password node in `capture_fields`, and the value MUST
appear only as `fields.<id>` under the rules in Section 14.6.

### 14.4 `event.action`

Every remote user action and trigger occurrence is delivered as an
`event.action` request:

```json
{
  "event_id": "00112233445566778899aabbccddeeff",
  "action": "heading.todo-set",
  "args": {"state":"DONE"},
  "surface": "app:agenda",
  "revision_seen": 42,
  "fields": {"note":"call Alice"},
  "occurred_at_ms": 1784700000000,
  "queued_at_ms": 1784700000100
}
```

| Member | Type | Required | Rule |
|---|---|---:|---|
| `event_id` | EventId | yes | Stable across every retry |
| `action` | namespaced identifier | yes | Copied from the descriptor or defined trigger event |
| `args` | object | no | Defaults to `{}` |
| `surface` | Surface ID | for surface actions | Surface in which the action occurred |
| `revision_seen` | non-negative integer | for surface actions | Accepted surface revision visible at occurrence |
| `dialog_id` | identifier | for dialog actions | Outstanding dialog in which the action occurred |
| `fields` | object | no | Values captured atomically with the occurrence |
| `occurred_at_ms` | timestamp | yes | Creation time |
| `queued_at_ms` | timestamp | queued delivery only | Time first persisted for offline/retry delivery |

`fields` MUST be omitted when empty. It MUST NOT be sent as `null`. A surface
event MUST contain `surface` and `revision_seen` and MUST omit `dialog_id`. A
dialog event MUST contain `dialog_id` and MUST omit `surface` and
`revision_seen`. A trigger, reminder, shortcut, or pie-menu event MUST omit all
three context members; its source identity belongs in validated `args`.

Before persistence or transmission, the Companion MUST serialize the complete
`event.action.params` object and verify that it does not exceed
`max_event_bytes`. This applies to
live `drop` events as well as durable events. If the constructed request is too
large, it MUST NOT be persisted or sent, the Companion MUST show a local
validation diagnostic, and any volatile password copy MUST be erased.

The Companion MUST generate an EventId from 16 CSPRNG octets before the event's
first persistence or transmission. It MUST scope uniqueness to the pairing
identity and MUST NOT reuse an EventId within 604800 seconds, including across
process restart. Every retry of one logical occurrence MUST reuse that ID; a
dedupe replacement is a different occurrence and therefore has a new ID.

Emacs MUST validate the action allowlist, arguments, surface context, revision,
and durable ID before invoking application behavior. It MUST return exactly one
of:

| Result status | Meaning | Companion disposition |
|---|---|---|
| `accepted` | New event durably accepted for processing | Delete durable record |
| `duplicate` | This `event_id` was already accepted | Delete durable record |
| `stale` | Context is permanently too old | Delete durable record and surface a diagnostic |
| `rejected` | Action or arguments are permanently invalid/unregistered | Delete durable record and surface a diagnostic |

Where this document says an occurrence is **safely admitted**, it means that a
`queue` or `wake` event's complete durable record has been committed locally,
or that a live `drop` event has received `accepted` or `duplicate` from Emacs.
An offline `drop`, admission failure, `stale` or `rejected` result, transient
error, cancellation, timeout, or transport loss is not safe admission.

The result shape is `{status}` with optional human-readable `message`. A
temporary inability to accept an otherwise valid event MUST use error
`1500 event-retry`. For a durable `queue` or `wake` event, the Companion MUST retain
the record. A `drop` event MUST NOT be promoted to durable storage: it MAY be
retried only while the same authenticated `READY` session remains usable and
otherwise MUST be discarded with a local diagnostic. An event containing a
password MUST NOT take even that in-session retry path: any result, error,
cancellation, timeout, or transport loss concludes the attempt and requires
immediate local erasure.

Before returning `accepted`, Emacs MUST durably commit the EventId together with
either the completed application effect or a durable work item that owns that
effect. If it cannot make that commitment, it MUST return `1500 event-retry`.
Returning `accepted` merely because a volatile callback was scheduled is not
conforming. This commitment makes later delivery return `duplicate`; it does
not make arbitrary external side effects exactly once.

Emacs MUST retain a durable record of accepted event IDs for at least 604800
seconds. On a repeated ID, it MUST return `duplicate` and MUST NOT deliberately
repeat the application effect. Application handlers SHOULD be idempotent or
SHOULD commit their effect and event ID transactionally when possible.

EBP provides at-least-once delivery of eligible queued events and durable
deduplication identifiers. It does not promise exactly-once external side
effects across arbitrary crashes.

### 14.5 Revision validation

`revision_seen` is a correctness boundary, not merely telemetry. Emacs MUST
decide whether the named action remains meaningful at that revision. It MAY
accept an intentionally replayable action against newer state; it MUST return
`stale` when the old context makes the action unsafe or ambiguous.

A Companion MUST include `surface` and `revision_seen` for every event
originating from a surface. It MUST NOT fabricate the latest revision after the
fact; the field records what the user actually saw.

### 14.6 `state.changed`

`state.changed` params are:

```json
{"surface":"app:main","revision_seen":42,"id":"title","value":"draft"}
```

`surface`, `revision_seen`, `id`, and `value` are REQUIRED. Stateful nodes are
`text_input`, `checkbox`, `switch`, `enum_list`, and `slider`, plus an `editor`
whose `publish_state` is `true`. Widget IDs MUST be unique among stateful nodes
in one surface snapshot. A Companion MUST send state changes in user-observed
order while `READY`.

A `text_input` MUST publish after each user edit, subject to a debounce no
longer than 500 milliseconds.
A checkbox or switch MUST publish after each flip; an `enum_list` after each
settled selection; and a slider after the user commits a gesture. An editor
MUST publish after each user text change only when `publish_state` is `true`.
When a node also has an `on_change` action, its `state.changed` notification
MUST precede that action and both MUST carry the same logical value.

If the Companion debounces state publication, it MUST flush every divergent
stateful value as ordered `state.changed` notifications before sending an
`event.action` whose handler could observe those values. This rule applies
under load as well as during normal operation. The flush updates general UI
state; it does not replace `capture_fields` for an action that depends on the
occurrence-time value.

A `state.changed` notification and a `surface.update` or `surface.remove`
request travel in opposite directions and can race. Reconciliation is exact on
both sides:

- `revision_seen` MUST equal the revision of the accepted snapshot presented
  to the user when the edit was made. The Companion MUST NOT rewrite a pending
  notification's `revision_seen` after accepting a newer snapshot.
- Before returning the result of a `surface.update` or `surface.remove` that
  changes a surface's revision floor, the Companion MUST flush that surface's
  pending debounced `state.changed` notifications, in user-observed order,
  onto the same stream — except a pending value whose ID the accepted request
  names in `reset_input_ids`, which MUST be discarded unsent. The update
  result is therefore a barrier: once Emacs has observed it, no
  `state.changed` for that surface with an older `revision_seen` can arrive.
- Emacs MUST NOT discard a `state.changed` merely because `revision_seen` is
  older than its newest pushed revision. It MUST reconcile the reported value
  against its newest accepted snapshot using exactly the Section 13.6 rules.
  When the ID survives with a compatible value schema and no accepted snapshot
  with a revision greater than `revision_seen` named that ID in
  `reset_input_ids`, the reported value is the node's live draft and Emacs
  SHOULD adopt it. When the ID was reset, removed, or is incompatible under
  Section 13.6, the Companion has already erased or reseeded that draft;
  Emacs MUST discard the reported value without treating the notification as
  an error.
- After accepting a newer snapshot that retains a compatible dirty value, the
  Companion MUST NOT re-publish the unchanged value at the new revision;
  survival is derivable from Section 13.6. The next user edit publishes with
  the newly accepted snapshot's revision.

While disconnected, the Companion MUST retain only the latest value per
surface and widget ID for welcome `input_state`; it MUST NOT retain a keystroke
history. It SHOULD persist that latest-value map atomically with any queued
action that depends on it.

A node with `password: true` MUST NOT emit `state.changed`. Its value MUST NOT
be written to disk, included in `input_state`, logged, or retained after the
containing interaction ends. A remote descriptor that captures a password MUST
use `when_offline: "drop"`, MUST NOT use `dedupe` or `ttl_s`, and MUST NOT create
an event unless an authenticated `READY` session exists. A `dialog.submit`
builtin that captures a password is legal only because its containing request
already exists in `READY`; it MUST NOT outlive or be retried beyond that
request. The Companion MUST hold the value only in volatile memory, place it
only in the explicitly submitted action's or dialog result's `fields`, transmit
it without durable admission, and erase its local copy as soon as the request
concludes or the interaction is cancelled. A password value MUST NOT appear in
`args`, a builtin parameter value, a retry queue, diagnostics, or crash
recovery.

A password-bearing submission has a hard 30-second monotonic deadline beginning
when the user commits it. Within that deadline, its `event.action` MUST receive
a result or its dialog response MUST be completely handed to the transport. On
expiry, the Companion MUST close the transport, abandon the attempt, and MUST
NOT retry it. Closing is REQUIRED whether the secret-bearing frame is queued,
partially written, or fully written without its required result; the Companion
MUST NOT append a cancellation frame to a stream that may end in a partial
frame. A fully written action has an indeterminate remote outcome. Erasure MUST
remove every locally controlled copy,
including the native widget and composition buffer, captured `fields`, encoded
request buffers, and correlation state; overwriting immutable runtime or kernel
buffers is required only where the implementation can control it.

## 15. Durable queue and replay

### 15.1 Queue admission

If no `READY` session exists when a remote action occurs, the Companion MUST:

- discard it without creating an event when `when_offline` is `drop`;
- persist it when `when_offline` is `queue`; or
- persist it and only then attempt the profile's wake mechanism when
  `when_offline` is `wake`.

The persisted record MUST include the complete delivery payload, its immutable
`event_id`, queue policy, dedupe key if any, creation time, queue time,
expiration time, and a per-pairing `queue_seq`. `queue_seq` MUST be assigned
from a durable strictly increasing counter and MUST define FIFO order
independently of wall-clock changes. Captured fields MUST be inside that same
event record. The Companion MUST also commit its latest non-sensitive
`input_state` map no later than any event created from that interaction, but
that map is for reconnection reconciliation and is not the event's historical
snapshot.
For `queue` or `wake`, persistence MUST precede every wake or delivery attempt,
including when a `READY` session already exists.

If storage fails, the Companion MUST NOT claim that the interaction was queued.
It MUST notify the user of the failure. If queue capacity is exhausted, it MUST
reject admission with a visible diagnostic equivalent to `1601 queue-full`.

### 15.2 Expiry and dedupe

An event expires when the effective wall-clock time is greater than or equal to
`occurred_at_ms + ttl_s*1000`. The effective wall clock is the greater of the
current wall clock and a durably stored per-pairing high-water mark. The
Companion MUST advance that mark when time moves forward; clock rollback MUST
NOT extend an event's lifetime. It MUST delete expired records before delivery
and MUST count them in the next replay summary.

When a newly queued event has a `dedupe` key, the Companion MUST atomically
remove every older queued, non-in-flight event with the same key and pairing
identity. It MUST NOT remove or replace an event whose `event.action` request is
in flight without a permanent result. The new event keeps its own ID and
creation time and receives the next `queue_seq`. Dedupe admission, counter
advance, replacement, and record insertion MUST be one durable transaction.
Dedupe is queue compaction; it is not delivery acknowledgement or receiver
idempotence.

### 15.3 `queue.replay`

The Companion MUST maintain one single-file durable delivery pump. At most one
durable `event.action` request may be in flight. While `READY`, admission of a
new head event MUST start or wake that pump unless it is paused by a prior
transient error. A permanent result deletes the head and advances the pump; a
JSON-RPC error retains the head and pauses it. Admission of a later event MUST
NOT clear that pause or bypass the head. During `SYNCING`, only the explicit
replay request starts the pump.

`queue.replay` params are `{}`. Only one replay may be active. A concurrent
request MUST receive `1600 queue-busy`.

`queue.replay` resumes the pump and asks it to run to a stable stop. If a
durable event request was already in flight when replay arrived, the replay
MUST join that operation rather than send a duplicate concurrently, and its
summary MUST include the joined disposition. Emacs SHOULD call `queue.replay`
with bounded backoff after it returns a transient error for an automatically
delivered durable event.

The Companion MUST process retained events in ascending `queue_seq`. For each event it
MUST:

1. discard and count it if expired;
2. send it as an `event.action` request using the stored `event_id`;
3. wait for the corresponding result before advancing; and
4. delete it only after `accepted`, `duplicate`, `stale`, or `rejected`.

Any well-formed JSON-RPC error response, including `1500 event-retry` and
`1301 request-cancelled`, MUST stop replay and retain that event and every later
event. A result with an unknown status or invalid result shape is a protocol
violation: the Companion MUST retain the event, send at most one safe
`log.error`, and close the connection. If the connection closes, all events
without a permanent result MUST remain queued.

When replay reaches a stable stopping point, the Companion returns:

```json
{"delivered":2,"rejected":0,"expired":1,"remaining":0,"blocked_by":null}
```

`delivered` counts `accepted` and `duplicate`; `rejected` counts `stale` and
`rejected`; `expired` counts expiry deletions; and `remaining` is the number of
records still retained. `blocked_by` is `null` after normal exhaustion, or the
received error's `data.kind` when a well-formed error stopped replay. If error
data has no valid `kind`, it is `json-rpc-error`.

The Companion MUST keep newly generated events behind the synchronization
barrier until this request concludes and `session.ready` succeeds. A stopped
replay does not permit a later durable event to overtake the retained head.
After entering `READY`, Emacs SHOULD retry `queue.replay` with bounded backoff
while `remaining` is nonzero. Newly admitted durable events MUST remain behind
the backlog. A live `drop` event MAY be delivered outside durable FIFO because
it is never admitted to that queue, but it MUST still obey state-before-action
ordering.

### 15.4 Queue limits

The Companion MUST enforce `max_event_bytes` before every live or durable
attempt and MUST enforce `max_queued_events` and `max_queued_bytes` atomically at
durable admission. The aggregate byte check MUST count stored payload,
metadata, captured fields, and implementation storage overhead conservatively.
It MUST store the exact serialized event or otherwise guarantee that replay
remains within `max_event_bytes`. Emacs SHOULD use dedupe keys for high-frequency
replaceable intent and SHOULD avoid authoring queue policies for navigation,
transient gestures, or actions unsafe to replay.

## 16. UI document model

### 16.1 Node structure

Every node MUST be a JSON object containing the required string discriminator
`t`. A node's remaining members are defined by its type and by the universal
attributes below. A surface tree MUST be acyclic when represented in memory and
MUST fit the resource limits in Section 4.5.

A node's presentation identity is its `key` when present, otherwise its `id`
when present, otherwise its structural tree path. A `key` MUST be unique among
siblings. Every authored node `id` MUST be unique across the complete surface
or dialog document, including input-stateful, collapsible, tabs, and editor
nodes. The discriminator `t` is part of the identity: reusing a key
or ID with a different node type creates a new identity and MUST clear retained
presentation state. Tree-path identity is unstable under insertion;
Emacs SHOULD supply a `key` or `id` for any node whose local presentation state
should survive a snapshot replacement.

Presentation identity controls focus, expansion, selection, scroll anchors,
and similar rendering state. Input drafts are the deliberate exception because
their wire address is a node ID: their identity consists of surface, ID, node
type, and value schema under Section 13.6. Changing only a universal `key` MUST NOT
erase a compatible draft; changing or removing the input ID, type, or value
schema MUST erase it as Section 13.6 requires.

The Companion MUST validate an entire SurfaceSpec before accepting its surface
revision. A malformed node, invalid required field, invalid action descriptor,
duplicate stateful-node ID, or resource-limit violation MUST reject the entire
update with `1201 content-invalid`.

### 16.2 Required core and unknown nodes

Every conforming Companion MUST implement and advertise this Core Node Set:

`text`, `row`, `column`, `box`, `spacer`, `divider`, `button`, and `text_input`.

All other node types are OPTIONAL and MUST appear in the applicable
`surface_profiles.<target>.node_types` array before Emacs emits them. Emacs MUST
NOT emit an unadvertised type merely because it authored fallback children.

When a Companion nevertheless receives an unknown node type, it MUST:

- render the node's `children` as a neutral vertical sequence when `children`
  is an array of valid nodes; or
- render nothing when no valid `children` fallback exists.

It MUST NOT crash, dispatch actions from an unknown node, or guess the node's
semantics. This fallback is defensive behavior for a nonconforming or
version-skewed sender; it is not feature negotiation and does not relax the
sender gate above.

### 16.3 Unknown fields

A Companion MUST ignore an unknown optional node field. Emacs MUST obey the
constraining-field rule in Section 12 and MUST NOT depend on an unknown field
to disable, hide, authorize, or limit an action.

### 16.4 Rendering fidelity

“Render” means preserve the declared semantic structure, content, enabled
state, interaction hooks, and accessibility meaning. It does not require pixel
identity among toolkits or platforms. A Companion MAY use native platform
appearance, typography, animation, and input idioms where the declared
semantics remain observable.

Interactive nodes MUST expose an accessible label. Text MUST be treated as
plain text unless its field explicitly defines structured rich text. A
Companion MUST NOT interpret ordinary text as HTML, Markdown, Elisp, or another
executable or markup language.

### 16.5 Universal node attributes

The following members MAY appear on any node unless its meaning is nonsensical
for that node. Numeric layout values are finite, non-negative logical
density-independent units (`dp`) unless stated otherwise.

| Member | Type | Default | Meaning |
|---|---|---|---|
| `key` | identifier | — | Stable sibling-unique presentation identity; preferred over `id`, then tree path |
| `scroll_here` | boolean | `false` | Request first-show/index-change scroll anchoring |
| `padding` | number | `0` | Uniform padding |
| `pad` | Pad object | — | Per-side padding; overrides `padding` on supplied sides |
| `width`, `height` | number | intrinsic | Requested size |
| `min_width`, `max_width`, `min_height`, `max_height` | number | platform bounds | Size constraints |
| `fill_fraction` | number `0..1` | — | Fraction of available parent width |
| `aspect_ratio` | number `>0` | — | Width divided by height |
| `weight` | number `>0` | — | Share of remaining main-axis space |
| `bg` | Color | transparent | Background fill |
| `corner` | number or Corner object | `0` | Shared corner shape |
| `border` | Border object | — | `{width, color}` |
| `alpha` | number `0..1` | `1` | Opacity; MUST NOT be used to hide a load-bearing control |
| `clip` | boolean | `false` | Clip descendants to the corner shape |
| `align_self` | `start` \| `center` \| `end` \| `stretch` | — | Override parent cross-axis alignment |

A Pad object MAY contain `start`, `top`, `end`, `bottom`, `horizontal`, and
`vertical`. A side-specific value wins over its axis shorthand. A Corner object
MAY contain `top_start`, `top_end`, `bottom_start`, and `bottom_end`.

The Companion SHOULD apply visual operations in this order: corner shape,
clipping, background, then border.

### 16.6 Colors

A Color is either a theme-role identifier or one of `#rgb`, `#rgba`,
`#rrggbb`, or `#rrggbbaa`. Hex digits are case-insensitive. Theme-role names are
resolved from the active theme. A Companion receiving an unknown role MUST use
a legible platform fallback and MUST NOT make content transparent.

## 17. Widget vocabulary

The tables in this section are normative schemas. Every listed required member
MUST be present and have the listed type. Every listed optional member MAY be
omitted and then has the stated default or behavior. A node type not in the
applicable `surface_profiles.<target>.node_types` array MUST be treated as
unsupported even if it appears in this section.

### 17.1 Common schema rules

Unless a row states a narrower rule, fields named `text`, `label`, `title`,
`caption`, `hint`, `content_description`, `annotation`, and `summary` are plain
JSON strings; fields named `icon` and `syntax` are identifiers; fields named
`children` are arrays of Nodes; and fields beginning `on_` are
ActionDescriptors. Optional booleans default to `false` unless stated
otherwise. Numeric values MUST be finite; layout numbers MUST also be
non-negative. Arrays and strings MUST fit Section 4.5 and the advertised module
limits.

Fields named `id` and `key` are identifiers; `color` and `bg` are Colors;
`width`, `height`, `size`, `radius`, and coordinate fields are finite numbers;
and `scroll`, `selectable`, `selected`, and boolean-valued `fill` are booleans.
Where a table lists a member without an inline type, these common types or the
member-specific prose immediately after the table supplies its type. These
definitions are cumulative and MUST be projected together into `contract.json`;
a receiver MUST NOT apply type coercion omitted by them.

`font_weight` is `normal`, `bold`, or an integer multiple of 100 from 100
through 900. `selectable`, `italic`, `underline`, and `mono` are booleans.
`size`, `spacing`, `run_spacing`, `content_padding`, `elevation`, and
`thickness` are non-negative `dp`. An action-valued field MUST contain a valid
descriptor even when the platform cannot expose that interaction; a sender
MUST NOT rely on a hidden action as the only path to load-bearing behavior.

### 17.2 Content nodes

| `t` | Required members | Optional members and semantics |
|---|---|---|
| `text` | `text: string` | `style`, `font_weight`, `color`, `selectable`, `max_lines`, `syntax`. `style` is `body` (default), `title`, `headline`, `caption`, `label`, or `mono`; unknown values fall back to `body`. `max_lines` MUST be a positive integer. |
| `rich_text` | `spans: RichSpan[]` | `style` uses the same enum and default as `text.style`. Spans render in order. |
| `icon` | `name: string` | `size`, `color`, `badge`, `content_description`. An unresolved name MUST render a harmless placeholder or nothing; an icon MUST NOT be the sole carrier of load-bearing meaning without `content_description`. |
| `image` | `url: string` | `content_description`, `width`, `height`, `aspect_ratio`, `content_scale`. `content_scale` is `fit` (default), `crop`, or `fill`. |
| `date_stamp` | — | `day`, `month`, `month_index`, `year`, `time`. At least one SHOULD be present. This is presentation data, not a clock instruction. |
| `section_header` | `title: string` | `trailing: Node` |
| `empty_state` | — | `icon`, `title`, `caption`, `action_label`, `on_tap` |
| `progress` | — | `variant`, `value`. `variant` is `circular` (default) or `linear`. Omitted `value` is indeterminate; supplied `value` MUST be `0..1`. |
| `badge` | `label: string` | `icon`, `color`, `children`. An empty label MAY render as an attention dot. A decimal-integer string MAY be visually capped, but its exact accessible value MUST remain available. |

A `RichSpan` MUST contain `text: string` and MAY contain `font_weight`, `italic`,
`underline`, `color`, `bg`, `mono`, and `on_tap`. The Companion MUST treat span
text as plain text. A span action MUST obey Section 14.

For `date_stamp`, `day` is an integer `1..31`, `month` is a display string,
`month_index` is an integer `1..12`, `year` is a non-negative integer, and
`time` is a display string. `section_header.trailing` is a Node. In an
`empty_state`, `action_label` and `on_tap` MUST appear together or both be
absent. `badge.children`, when present, is a Node array.

For an `image`, no URI form is implicit. A Companion advertising `image` in a
target profile MUST advertise at least one of `image.https` or `image.data` in
that same profile's `features`. Emacs MUST use only an advertised form. The
`image.data` feature permits base64 `data:image/*` URLs; the Companion MUST
validate the media type and decoded bytes, enforce the three advertised image
limits, and reject active or unsupported formats.

For `image.https`, the Companion MUST use HTTPS, MUST NOT attach ambient
cookies, credentials, client certificates, or authorization headers, and MUST
follow at most five redirects, stop after 15 seconds total, and enforce
`max_image_bytes`, `max_decoded_image_bytes`, and `max_image_pixels`. Before
each connection and after every redirect or DNS resolution, it
MUST reject loopback, private, link-local, multicast, unspecified, and other
non-public destination addresses. It MUST NOT follow a redirect to another URI
scheme. On any failure it MUST render `content_description` or a neutral
placeholder and MUST NOT expose response content as an executable format.

### 17.3 Layout nodes

| `t` | Required members | Optional members and semantics |
|---|---|---|
| `row` | `children: Node[]` | `spacing`, `align`, `arrange`, `scroll`, `fill`. `align`: `top`, `center`, `bottom`, `baseline`; default `center`. |
| `column` | `children: Node[]` | `spacing`, `align`, `arrange`, `scroll`, `fill`. `align`: `start`, `center`, `end`; default `start`. |
| `flow_row` | `children: Node[]` | `spacing`, `run_spacing`, `align`, `arrange`. Children wrap to later runs. |
| `box` | `children: Node[]` | `alignment`, `on_tap`. Children stack in array order from back to front. |
| `surface` | `children: Node[]` | `color`, `shape`, `elevation`. This node is a visual container and is distinct from a protocol Surface. |
| `lazy_column` | `children: Node[]` | `spacing`, `content_padding`. The Companion MAY compose only visible children but MUST preserve array order. |
| `spacer` | — | `width`, `height`, `weight` |
| `divider` | — | `color`, `thickness` |
| `card` | `children: Node[]` | `on_tap`, `on_long_tap`, `swipe_start`, `swipe_end`. |
| `collapsible` | `id: identifier`, `header: Node`, `children: Node[]` | `collapsed`, `on_long_tap`, `swipe_start`, `swipe_end`. Expansion state is Companion-local presentation state. |
| `reorderable_list` | `items: Node[]` | `on_reorder`. Every item MUST have a unique `key` or `id`; otherwise the node is invalid. |
| `tabs` | `items: TabItem[]`, `children: Node[]` | `initial`, `scrollable`, `pager_only`, `on_change`, `id`. Arrays MUST have equal non-zero length. |
| `table` | `rows: TableRow[]` | `aligns`, `on_add_row`, `on_add_col`. Wide tables MAY scroll horizontally. |

`spacing`, `run_spacing`, `content_padding`, `elevation`, and `thickness` are
non-negative `dp` values. For `row`, `column`, and `flow_row`, `arrange` is one
of `start`, `center`, `end`, `space_between`, `space_around`, or `space_evenly`.
An arrangement other than `start` distributes available space and takes
precedence over `spacing`.

`scroll` and layout `fill` are booleans. `flow_row.align` is `top`, `center`, or
`bottom`, default `top`. `content_padding` is a non-negative `dp` value.

`box.alignment` is one of `top_start`, `top_center`, `top_end`, `center_start`,
`center`, `center_end`, `bottom_start`, `bottom_center`, or `bottom_end`; the
default is `top_start`. `surface.shape` is `rounded`, `rounded_small`, or
`circle`; omission is rectangular. A numeric universal `corner` overrides
`shape` except that `circle` remains circular.

`collapsible.collapsed` is boolean and defaults to `false`. It seeds only the
first snapshot for a new presentation identity. The Companion MUST preserve
the user's current expansion state across later snapshots with the same
Section 16.1 presentation identity, regardless of a repeated authored
`collapsed` value. Removal, type change, or a new presentation identity
discards that local state and seeds it again from `collapsed`.

A `TabItem` MUST contain `label: string` and MAY contain `icon`. `initial` is a
zero-based index and defaults to `0`. The Companion MUST preserve the selected
index across snapshots with the same Section 16.1 presentation identity; a new
identity resets to `initial`. If a later same-identity snapshot has fewer items
and the retained index is no longer valid, the Companion MUST select that
snapshot's valid `initial` without emitting `on_change`.
`on_change` receives the settled zero-based index as `args.value`.

For `tabs`, `id` is an identifier; `scrollable` and `pager_only` are booleans;
and `initial` MUST be less than the common non-zero item count. Omitting `id`
does not create a special rule: `key` and then tree path supply presentation
identity under Section 16.1.

A `TableRow` is one of:

```json
[
  {"kind":"data","cells":[{"spans":[{"text":"value"}]}]},
  {"kind":"header","cells":[{"spans":[{"text":"Heading"}]}]},
  {"kind":"rule"}
]
```

A cell MUST contain `spans: RichSpan[]` and MAY contain `on_tap` and
`on_long_tap`. `aligns`, when present, is an array of `start`, `center`, or
`end`. An unknown row kind makes the table invalid.

A swipe side is `{icon?, label, color?, on_trigger}`. A Companion MUST dispatch
`on_trigger` at most once per completed gesture and MUST return the item to its
resting position. Emacs SHOULD provide a non-swipe path to the same action for
accessibility and for Companions without swipe support.

### 17.4 Input nodes

Every advertised input node MUST implement `enabled`. An omitted value means
`true`. When `enabled` is `false`, the Companion MUST present the platform's
disabled affordance and MUST suppress every action and state dispatch from the
node. `editor` uses `read_only` for editing permission in addition to
`enabled`.

| `t` | Required members | Optional members and semantics |
|---|---|---|
| `button` | `label: string`, `on_tap: ActionDescriptor` | `icon`, `variant`, `enabled`. `variant`: `filled` (default), `tonal`, `outlined`, or `text`. |
| `icon_button` | `icon: string`, `on_tap: ActionDescriptor` | `content_description`, `badge`, `enabled` |
| `chip` | `label: string` | `on_tap`, `selected`, `icon`, `enabled` |
| `assist_chip` | `label: string` | `on_tap`, `icon`, `enabled` |
| `menu` | `items: MenuItem[]` | `icon`, `enabled` |
| `text_input` | `id: identifier` | `value`, `hint`, `label`, `on_change`, `on_submit`, `single_line`, `min_lines`, `max_lines`, `monospace`, `syntax`, `password`, `keyboard`, `autofocus`, `clear_on_submit`, `enabled` |
| `editor` | `id: identifier` | `document`, `value`, `on_save`, `on_enter`, `read_only`, `syntax`, `line_numbers`, `complete`, `chromeless`, `publish_state`, `autofocus`, `toolbar`, `enabled` |
| `checkbox` | `id: identifier` | `checked`, `label`, `on_change`, `enabled` |
| `switch` | `id: identifier` | `checked`, `label`, `on_change`, `enabled` |
| `enum_list` | `id: identifier`, `options: EnumOption[]` | `value`, `multi_select`, `allow_add`, `on_change`, `enabled` |
| `date_button` | `label: string`, `on_pick: ActionDescriptor` | `value`, `enabled` |
| `time_button` | `label: string`, `on_pick: ActionDescriptor` | `value`, `enabled` |
| `slider` | `id: identifier`, `on_change: ActionDescriptor` | `value`, `min`, `max`, `values`, `enabled` |

A `MenuItem` MUST contain `label` and `on_tap` and MAY contain `icon` and
`enabled`; `enabled` defaults to `true`. An `EnumOption` MUST contain `label`
and `value`; `value` MUST be a
string, number, or boolean. Option values MUST be distinct under Section 4.3.

For input nodes, every listed `on_*` member is an ActionDescriptor. `value`,
`hint`, and `label` on `text_input` and `editor.value` are strings;
`single_line`, `monospace`, `password`, `autofocus`, `clear_on_submit`,
`read_only`, `line_numbers`, `complete`, `chromeless`, and `publish_state` are
booleans. `document` is an identifier. Checkbox and switch `checked` values are
booleans. An `enum_list.value` is one option's scalar value, or an array of
distinct option values when `multi_select` is true. Slider `value`, `min`, and
`max` are finite numbers and `values` is an array of finite numbers. Date and time values use the
formats stated below. `enabled` is boolean and defaults to `true` for every
input node.

`text_input.value` and `editor.value` default to the empty string.
`single_line`, `monospace`, `password`, `autofocus`, `clear_on_submit`,
`line_numbers`, `complete`, `chromeless`, `publish_state`, and `read_only`
default to `false`. `min_lines` and `max_lines` MUST be positive integers, and
`min_lines` MUST NOT exceed `max_lines`. `min_lines` defaults to `1`;
`max_lines` defaults to `1` when `single_line` is true and otherwise defaults to
`min_lines`. `single_line: true` requires both line counts to equal `1`.

`single_line: true` prohibits U+000A in the node's value entirely. An authored
`value` containing U+000A is invalid content and MUST be rejected with
`1201 content-invalid`. The Companion MUST NOT let locally entered text
introduce U+000A: keyboard entry, paste, drop, autofill, and input-method
composition MUST have every U+000A code point deleted before the value is
committed, so no `state.changed` value, captured field, welcome `input_state`
entry, or retained draft for a `single_line` node ever contains U+000A.
Section 13.6 accordingly treats a retained draft containing U+000A as
incompatible with a new `single_line` node.

`keyboard` is `text` (default), `number`, `decimal`, `email`, `phone`, or `uri`.
`password: true` overrides it with a platform-appropriate secret-entry method.
When `password` is `true`, `value` MUST be absent or the empty string and
`on_change` MUST be absent; `clear_on_submit` MUST be absent or `false` because
Section 14.6 governs unconditional secret erasure. The Companion MUST reject a
snapshot that attempts to seed a password. A password MAY be captured only by
that node's `on_submit`
or by a `dialog.submit` descriptor in the same active interaction. Password
handling MUST obey Section 14.6, and `max_field_bytes` applies while the value
is held in volatile memory.

`autofocus: true` MAY acquire focus only when the first accepted snapshot
containing a new presentation identity is presented. A snapshot with the same
identity MUST NOT repeatedly steal focus. For a non-password text input whose
`on_submit` is remote, `clear_on_submit: true` MUST clear the value only after
that occurrence is safely admitted under Section 14.4. The Companion MUST
retain the value after an offline `drop`, admission failure, `stale` or
`rejected` result, transient error, cancellation, timeout, or transport loss.
After clearing, it MUST retain focus where the platform permits and MUST update
its latest input-state value. While `READY`, it MUST send the cleared value in
`state.changed` after safe admission and before a later action from that node;
while disconnected, the cleared value appears in the next welcome
`input_state`. `clear_on_submit: true` is invalid when `on_submit` is a builtin.

`on_enter` causes the software-input Enter action to dispatch the full editor
value rather than insert a newline. A hardware newline or an explicit toolbar
snippet MAY still insert a newline.

An `editor` without `document` is a local input node and does not participate
in Section 19. An `editor` with `document` MUST be emitted only when
`editor.sync` was granted. `complete: true` and a toolbar `command` additionally
require `document`; otherwise the node is invalid. For a synchronized editor,
`value` seeds only a new editor session. A later snapshot with the same
presentation identity and `document` MUST NOT replace live text; Emacs MUST use
Section 19 synchronization methods.

`checkbox.checked` and `switch.checked` default to `false`. Every flip MUST
produce `state.changed`; when `on_change` is present it MUST also produce an
action with the boolean in `args.value`, after the state notification.

For `enum_list`, `multi_select` and `allow_add` default to `false`. A
single-select value is one option value; a multi-select value is an array of
distinct option values. Unless `allow_add` is true, every selected value MUST
appear in `options`. When `allow_add` is true, the Companion MAY accept a new
non-empty string value through a local text affordance and MUST publish it like
another selection; it does not mutate the authored option list.
When `value` is omitted, a single-select list has no selection and its logical
captured value is `null`; a multi-select list starts with `[]`. The Companion
MUST NOT select the first option implicitly.
`date_button.value` is `YYYY-MM-DD`; `time_button.value`
is `HH:MM` in local civil time.

For a continuous `slider`, `min` defaults to `0`, `max` to `1`, and `value` to
`min`; `min` MUST be less than `max` and `value` MUST be in the closed range. A
discrete slider supplies `values` as two or more strictly increasing, distinct
JSON numbers; it MUST omit `min` and `max`, and `value` MUST equal one listed
number under Section 4.3 or defaults to the first. The Companion MUST return the
exact selected authored number, avoiding toolkit-specific step arithmetic. It
SHOULD dispatch
`on_change` once when the user commits a gesture, not for every intermediate
pixel.

### 17.5 Visualization nodes

| `t` | Required members | Optional members and semantics |
|---|---|---|
| `chart` | `series: ChartSeries[]` | `kind`, `height`, `y_range`, `summary`, `on_point_tap`, `children` fallback |
| `canvas` | `width`, `height`, `ops: CanvasOp[]` | `children` fallback |
| `month_grid` | `month: YYYY-MM` | `marks`, `selected`, `min_month`, `max_month`, `on_day_tap`, `on_month_change`, `children` fallback |

`chart.kind` is `line` (default), `bar`, `area`, or `sparkline`. A ChartSeries
MUST contain `points: ChartPoint[]`, MAY contain `name: string` and
`color: Color`, and each ChartPoint MUST contain finite numeric `x` and `y` and
MAY contain `meta: object` whose descendants are JSON data only.
If `on_point_tap` is present, the Companion MUST return the complete authored
point object in `args.value`. `summary` SHOULD provide an accessible textual
equivalent.

A canvas operation MUST have `op` and one of these closed shapes:

| `op` | Required members | Optional members |
|---|---|---|
| `line` | `x1`, `y1`, `x2`, `y2` | `color`, `width` |
| `rect` | `x`, `y`, `width`, `height` | `color`, `fill`, `stroke_width` |
| `circle` | `cx`, `cy`, `radius` | `color`, `fill`, `stroke_width` |
| `path` | `points: CanvasPoint[]` | `color`, `fill`, `stroke_width`, `closed` |
| `text` | `x`, `y`, `text` | `color`, `size` |

Coordinates are finite numbers in the canvas coordinate space. A Companion
MUST skip an unknown canvas operation, MUST NOT treat it as executable code,
and MUST continue rendering known operations. Canvas has no implicit
interaction or animation.

A `CanvasPoint` is exactly `{x, y}` with finite numeric coordinates. Canvas
`width` and `height` MUST be positive. `stroke_width` is non-negative and
`closed` is boolean. `CanvasOp.fill` is a Color and omission means no interior
fill. A line operation's `width` is a non-negative stroke width. Rect widths,
rect heights, and circle radii MUST be non-negative. `chart.height` is positive
`dp`; `chart.y_range`, when
present, is a two-number array `[min, max]` with `min < max`.

`month_grid.marks` maps `YYYY-MM-DD` dates to `{dots, color?}`; `dots` MUST be an
integer `0..3` and `color` is a Color. `selected` is one `YYYY-MM-DD` date;
`min_month` and `max_month` are `YYYY-MM`, and the minimum MUST NOT follow the
maximum.
Local month navigation MUST respect the bounds. A snapshot that changes only
marks MUST preserve the month the user is viewing; a changed authored `month`
MUST adopt that month.

The optional `children` on visualization nodes is the authored fallback. A
Companion that supports the visualization SHOULD ignore the fallback; an
unknown-node Companion renders it through Section 16.2.

### 17.6 Scaffold and application chrome

A `scaffold` node has no required members and MAY contain `top_bar`, `body`,
`bottom_bar`, `fab`, `floating_toolbar`, and `drawer` as Nodes;
`snackbar: string`; `snackbar_action: {label, on_tap}`; and
`on_refresh: ActionDescriptor`.

The Companion MUST dispatch a snackbar action only on a user tap, never on
timeout. It MUST dispatch `on_refresh` only after a user refresh gesture. A
drawer or bar is structural content and MUST NOT acquire hidden navigation
behavior not declared by its nodes.

The `badge` member MAY appear on an icon or navigation control as either a
string or number. A number above the platform's visual limit MAY display as
`99+`, but accessibility output SHOULD retain the exact authored value.

### 17.7 Editor toolbars

`editor.toolbar` is either a registered toolbar identifier or an array of
ToolbarItem objects. A registered identifier MUST appear as
`toolbar.<identifier>` in the applicable profile's `features`; an unknown or
unadvertised identifier makes the node invalid.

A ToolbarItem MUST contain `label` or `icon` and exactly one operation:

| Operation member | Value |
|---|---|
| `snippet` | String inserted locally |
| `on_tap` | ActionDescriptor |
| `menu` | Array of non-menu ToolbarItems |
| `command` | Identifier registered in the Emacs editor-command allowlist |
| `line` | One of `promote`, `demote`, `move-up`, `move-down` |

It MAY contain `placement` (`cursor`, `line-start`, or `block`) and
`long_press`, which contains exactly one non-menu operation. A Companion MUST
reject an item with zero or multiple primary operations.

The finite snippet placeholders are:

| Token | Substitution |
|---|---|
| `${selection}` | Current selection; substituted text remains selected |
| `${cursor}` | Final cursor position marker |
| `${input:Prompt}` | One local free-text prompt titled `Prompt` |
| `${date}` | Local `YYYY-MM-DD Day` |
| `${time}` | Local `HH:MM` |

Substitution MUST be single-pass. An unknown `${...}` token MUST remain literal.
`$${` MUST produce a literal `${` without beginning a placeholder. Substituted
text MUST NOT be scanned again. A Companion MUST NOT interpolate an operation
or command name.

Each local edit operation SHOULD be one undo step. `line-start` MUST no-op when
the line already starts with the exact literal inserted prefix. `block` MUST
place the snippet on its own line or lines. A `command` operation is valid only
for a synchronized editor in `READY`. It MUST create a non-durable
`event.action` with action `edit.command`, the containing surface or dialog
context, and args containing `command`, `document`, `editor_id`, `session`,
`seq`, `cursor`, `sel_start`, and `sel_end`. Emacs MUST explicitly allowlist
`edit.command` and then the nested
`command`; it MUST NOT pass either string directly to a host-language evaluator
or ambient command dispatcher. Connection loss or a transient error abandons
the command without replay.

A `line` operation is a Companion-local structural edit of the line containing
the cursor. Unlike `command`, it never contacts Emacs and is valid in every
editor tier, including a local `editor` with no `document`; it MUST produce one
local edit and SHOULD be a single undo step, exactly as a `snippet` does. In a
synchronized editor the resulting change flows to Emacs through Section 19 like
any other local edit; an app that needs a semantic Emacs operation rather than
this literal text transform MUST use `command` instead. The four values act on
the cursor's line as follows. `promote` reduces its outline depth by one step: a
line beginning with two or more `*` heading markers loses one leading `*`;
otherwise a line beginning with two or more leading spaces loses two of them; a
line already at minimum depth is unchanged. `demote` raises it by one step: a
line beginning with `*` gains one leading `*`; otherwise a line whose first
non-space character opens a bullet (`-`) or ordered (`N.` or `N)`) list item
gains two leading spaces; any other line is unchanged. `move-up` exchanges the
cursor's line with the line above it, keeping the cursor at the same column of
that line, and MUST be a no-op on the first line; `move-down` exchanges it with
the line below under the same rule and MUST be a no-op on the last line. An
unrecognized `line` value MUST be a no-op, never an error.

## 18. Optional presentation modules

### 18.1 Dialogs

`dialog.show` params are:

```json
{"dialog_id":"rename","spec":{"t":"column","children":[]},"style":"dialog"}
```

`dialog_id` and `spec` are REQUIRED. `style` is OPTIONAL and is `dialog`
(default), `sheet`, or `sheet_full`. An unrecognized `style` value MUST fall
back to `dialog` (Section 12 rule 6); a Companion MUST NOT reject a dialog for
an unknown `style` alone. Every node, builtin, and feature in `spec`
MUST be advertised by the `dialog` surface profile, and stateful IDs MUST be
unique within the dialog. A second outstanding request with the same
`dialog_id` MUST receive `1201 content-invalid`; the Companion MUST NOT replace
or alias the first. A distinct request that would exceed
`limits.max_dialogs` MUST receive `1401 overloaded`; the Companion MUST NOT
display or retain that dialog, and existing requests remain outstanding. The
Companion MUST display the node tree modally and keep
the request outstanding until one of these occurs:

- `dialog.submit` completes it with `{status:"submitted", value?, fields?}`;
- `dialog.dismiss` or a platform dismissal completes it with
  `{status:"dismissed"}`; or
- the caller sends `rpc.cancel`, which concludes it with error `1301`.

For `dialog.submit`, `fields` MUST be omitted when `capture_fields` is absent or
empty and otherwise MUST contain exactly the named current values keyed by node
ID. It MAY include a password only when that password ID was explicitly named;
Section 14.6 then applies. Stateful dialog nodes MUST NOT emit `state.changed`
or enter persistent `input_state`; they are local to the outstanding request.

Before completing `dialog.submit`, the Companion MUST serialize the prospective
complete JSON-RPC success response, including the original request ID,
`status`, optional authored `value`, and every captured field. If its body would
exceed `max_frame_bytes`, it MUST NOT write any part of the response or complete
the dialog. It MUST keep the non-password values and dialog outstanding and
show a local validation diagnostic so the user can reduce the input. If the
prospective result contained a password, this local failure concludes that
password attempt and the Companion MUST erase that value immediately under
Section 14.6.

A remote action inside a dialog uses `event.action.dialog_id` and MAY use its
own `capture_fields`. Every such remote ActionDescriptor MUST set or default
`when_offline` to `drop`; `queue` and `wake` are invalid because a dialog has no
durable instance identity.

Multiple outstanding dialogs MAY be serialized by the Companion, but request
correlation MUST remain intact. A Companion MUST NOT answer one dialog with
another dialog's values. Cancellation, transport loss, or dialog completion
MUST erase every volatile password value belonging to that dialog. Completion,
dismissal, or cancellation makes every node in that dialog absent; any
synchronized editor session in it MUST be closed under Section 19 before the
response is sent while the connection remains `READY`. On transport loss or
session replacement, the Companion MUST dismiss every outstanding dialog,
discard its local state, and close its editor sessions locally. Those dialog
requests fail with the lost session and MUST NOT be resumed after reconnection.

### 18.2 Toasts

`toast.show` params are `{text, duration_s?}`. `text` is REQUIRED and MUST be
plain text. `duration_s` MUST be `1..10`; omission selects a platform default.
A toast is best-effort presentation and MUST NOT contain an action or be used
as the sole report of a durable failure.

### 18.3 Pie menus

`pie_menu.show` params are `{menu_id, categories, center_label?}`. `menu_id` is
an identifier, `center_label` is a string, and `categories` MUST be an array of
one through ten objects containing `label: string`, optional `icon: identifier`,
and exactly one of `items` or `on_tap: remote ActionDescriptor`. `items` is a
non-empty array of objects containing `label: string`, a remote ActionDescriptor
named `on_tap`, and optional
`icon: identifier`. Every action obeys Section 14.

On selection, the Companion MUST inject `menu_id`, zero-based
`category_index`, and, for a nested item, zero-based `item_index` into a copy of
the descriptor's `args`. Any authored conflict makes the menu invalid.

`pie_menu.dismiss` params are `{menu_id}`. Showing a menu with an existing ID
replaces it. Dismissing an unknown ID is a no-op.

If a new `menu_id` would exceed `limits.max_pie_menus`, the Companion MUST keep
all existing menus unchanged, MUST drop that `pie_menu.show`, and SHOULD send a
rate-limited `log.error` with code `1201`, `data.kind: "content-invalid"`, and
`data.reason: "pie-menu-limit"`. Replacing an existing ID remains legal while
at the limit.

Pie menus are ephemeral to the authenticated session. The Companion MUST NOT
persist or restore them and MUST dismiss all open pie menus on transport loss,
session replacement, or process shutdown. Every pie-menu descriptor MUST use
`when_offline: "drop"`; queued or wake-backed menu actions are invalid.

### 18.4 Themes

`theme.set` params MAY contain:

| Member | Type | Meaning |
|---|---|---|
| `dark` | boolean | Theme polarity |
| `colors` | object or `null` | Theme-role to Color map; `null` clears a persisted mirror |
| `syntax` | object or `null` | Syntax-role to SyntaxStyle map; `null` clears it |

Every field is optional. The Companion MUST merge missing roles with a legible
platform fallback, MUST persist the latest accepted theme, and MUST treat each
notification as a complete replacement of the previously pushed values.

When `dark` is present it forces that polarity; when `dark` is omitted the
Companion follows the device's system light/dark setting. Emacs thus selects
forced-light (`dark: false`), forced-dark (`dark: true`), or follow-system (omit
`dark`). Combined with `colors` — a role map that mirrors the Emacs theme, or
`null` to select the Companion's native scheme — this expresses the light, dark,
follow-system, and mirror-Emacs choices without EBP naming a platform theme
system. The choice among these modes is Emacs-side policy; the wire carries only
the resulting `theme.set`.

A `SyntaxStyle` MAY contain `fg: Color`, `bg: Color`, `font_weight`, `italic`,
and `underline`, with the types from Section 17.1. Empty or missing color and
syntax maps select the Companion's native platform defaults. EBP does not name
or require a particular UI toolkit's theme system.

Standard roles include `primary`, `on_primary`, `primary_container`,
`on_primary_container`, parallel `secondary`, `tertiary`, and `error` roles,
plus `background`, `on_background`, `surface`, `on_surface`,
`surface_variant`, `on_surface_variant`, `outline`, `success`, and `warning`.
Unknown roles MUST be ignored.

### 18.5 Notification metadata and actions

A `notification:*` surface metadata object MAY contain `channel: identifier`,
`ongoing: boolean`, `category: identifier`, `priority`, `chronometer`, and
`actions`. `ongoing` defaults to `false`. `priority` is `min`, `low`, `default`,
`high`, or `max`, default `default`. `chronometer` is
`{base_ms, count_down?}`; `base_ms` is an epoch timestamp and `count_down`
defaults to `false`.

`actions` is an ordered array. Each entry MUST contain `label` and `on_tap`, and
MAY contain `icon`, `dismiss`, and `input`. The platform MAY display fewer
actions, so Emacs MUST author the most important first and MUST NOT rely on an
icon as the only label.

`input` is `{hint?, key?}` and turns the action into an inline text reply.
`hint` is a string and `key` is an identifier defaulting to `reply`. The remote
`on_tap` MUST NOT contain `capture_fields`. The Companion MUST place the submitted text in the
resulting `event.action.fields` under that key. `dismiss: true` dismisses the
notification only after the action occurrence is safely admitted under its
offline policy.

Safe admission has the exact meaning defined in Section 14.4.

When `input` or `dismiss: true` is present, `on_tap` MUST be a remote
ActionDescriptor. An inline reply MUST be bounded by `max_field_bytes`, MUST be
captured only after explicit submission, and MUST NOT be injected into
`args.value`.

### 18.6 Owner-scoped reminders

`reminders.set` params are:

```json
{
  "owner":"org.example.agenda",
  "reminders":[
    {"id":"meeting-1","title":"Meeting","body":"Room 3","at_ms":1784700000000}
  ]
}
```

`owner` MUST be a non-empty identifier. `reminders` MUST be an array with
unique reminder IDs. Each reminder is a closed object with this schema:

| Member | Type | Required | Meaning |
|---|---|---:|---|
| `id` | identifier | yes | Unique within this owner's set |
| `title` | non-empty string | yes | User-visible title |
| `body` | string | no | User-visible supporting text |
| `at_ms` | timestamp | yes | Earliest presentation time |
| `on_tap` | remote ActionDescriptor | no | Action dispatched for an explicit tap |

The Companion MUST inject
`owner` and `reminder_id` into a copy of `on_tap.args`; authored conflicting
members make the set invalid.

The Companion MUST validate the entire set, atomically replace only that
owner's prior set, persist the accepted set across process and device restarts,
cancel removed reminders, and return `{count}`. It MUST NOT silently truncate a
set or replace another owner's reminders. An empty array clears the owner's
set. If the replacement plus reminders retained for other owners would exceed
`limits.max_reminders`, the Companion MUST reject the request with
`1201 content-invalid` and `data.reason: "reminder-limit"`; the prior sets MUST
remain unchanged. The returned `count` MUST be a non-negative integer equal to
the accepted number of reminders for this owner after replacement, not the
global total.

Note (non-normative): on a platform that clears scheduled alarms across a
reboot, persisting the accepted set is not sufficient by itself — the Companion
must also re-arm the platform alarms for unfired reminders from the persisted
set after a device restart, or the surviving registrations will never fire.

At or after `at_ms`, the Companion MUST present the reminder at most once for
that accepted `(owner, id, at_ms)` tuple and MUST persist fired state before or
atomically with presentation so a restart does not deliberately re-fire it.
Replacing an unchanged tuple preserves fired state; changing `at_ms` creates a
new schedule. Removing a reminder MUST delete its fired receipt; re-adding the
same tuple later creates a new schedule and MAY present again. User dismissal
without tapping MUST NOT dispatch an action. A tap
MUST enter Section 14's normal action pipeline using the authored offline
policy. The same safe-admission definition as Section 18.5 applies; the
Companion MAY dismiss the reminder only after safe admission under Section
14.4. It MUST NOT
fabricate a tap when merely displaying or dismissing a reminder.

## 19. Editor synchronization module

The editor module is OPTIONAL and is negotiated as `editor.sync`. It turns an
advertised `editor` node into a synchronized shadow of an Emacs-authorized
document. This module is session-scoped and non-durable: editor messages MUST
NOT enter the offline action queue.

A synchronized editor MUST become read-only whenever the connection is not
`READY`. It MUST NOT create an offline input draft, delta, save, completion, or
editor command. After transport loss, a surviving process MAY keep the last
shadow text only in volatile memory for display; process death discards it and
falls back to the cached snapshot's authored `value`. An accepted update during
the next `SYNCING` phase replaces that volatile text and explicitly seeds the
forthcoming session. If no such update arrives, the fresh session uses the
currently displayed volatile shadow or cached authored value. `edit.open.text`
MUST equal that selected seed exactly.

When a synchronized editor first becomes present in `READY`, the Companion MUST
create a fresh session and send `edit.open` before sending any delta, caret,
completion, annotation-related request, or editor command for it. If the node
was accepted during `SYNCING`, opening waits until `READY`. The same presentation
identity and `document` preserve the session across surface replacements; its
later authored `value` is not a second seed. Node removal, surface tombstoning,
document change, or presentation-identity change MUST close the old session and
MUST send `edit.close` when the connection is still `READY`. Transport loss
closes all editor sessions locally; both endpoints MUST treat their session IDs
as dead and create new sessions after reconnection.

Before accepting a surface or dialog mutation, the Companion MUST compute the
resulting number of distinct synchronized-editor presentation identities,
including identities not yet opened during `SYNCING`. It MUST reject the whole
mutation with `1201 content-invalid` and
`data.reason: "editor-session-limit"` if the result would exceed
`limits.max_editor_sessions`. Consequently, transition to `READY` MUST NOT
discover more pending editor sessions than can be opened.

### 19.1 Identifiers, positions, and sessions

`document` is an opaque identifier assigned and allowlisted by Emacs. It MUST
NOT be a raw path supplied by the Companion. Emacs MAY internally map it to a
file or buffer only after authorization.

`editor_id` is the node's authored `id`; the tuple
`(document, editor_id, session)` identifies one editor globally within a connection. The Companion
MUST generate `session` from exactly 16 CSPRNG octets and encode it as exactly
32 lowercase hexadecimal characters. It MUST NOT reuse that string while an
older incarnation can still have in-flight messages. `seq` is a
non-negative integer beginning at `0` and
increasing by exactly one for each accepted text-changing operation from
either endpoint.

All text positions and lengths are zero-based counts of Unicode scalar values.
Ranges are half-open. A Companion whose native editor uses UTF-16 code units or
grapheme indices MUST convert before sending and after receiving. Newlines are
represented by U+000A. An endpoint MUST reject a range that splits an invalid
encoding unit, lies outside the synchronized text, or has a negative length.

### 19.2 Session state machine

Each endpoint tracks an editor session as `OPEN`, `STALE`, or `CLOSED`. The two
endpoints can temporarily disagree about that state after message loss, which
is why resynchronization is explicit.

- `edit.open` creates an `OPEN` session at `seq: 0`.
- A valid next delta or apply keeps it `OPEN` and increments `seq`.
- A notification or accepted result that cannot be reconciled because of a
  sequence, splice, resulting-length, or shadow mismatch makes the receiver's
  local view `STALE`.
- A conditional request rejected with a typed stale result leaves the
  receiver's otherwise intact session `OPEN`; the caller MUST reconcile the
  winning operation or request resynchronization.
- An accepted `edit.resync` closes the prior session, returns the Companion's
  complete current state under a fresh session ID at `seq: 0`, and opens that
  new session.
- `edit.close` makes it `CLOSED`.

Later notifications for a closed session MUST be ignored, but a later request
MUST receive `1201 content-invalid` with
`data.reason: "editor-stale"`. Wrong synchronization state MUST result in a
typed stale outcome or resynchronization, never a wrong edit. A Companion
shadow MUST NOT write an Emacs document directly.

### 19.3 Companion-to-Emacs methods

`edit.open` is a notification:

```json
{
  "document":"doc:notes/123",
  "editor_id":"body",
  "session":"00112233445566778899aabbccddeeff",
  "seq":0,
  "text":"initial text",
  "cursor":0,
  "sel_start":0,
  "sel_end":0
}
```

`document`, `editor_id`, `session`, `seq`, `text`, and `cursor` are REQUIRED.
For a new seed, `seq` MUST be `0`. Selection members are OPTIONAL but MUST
satisfy `sel_start <= sel_end`; they MUST appear together or both be omitted.
When omitted, both default to `cursor`. `cursor` MUST equal one end when the
selection is non-collapsed. This paired-or-omitted rule applies to every editor
message carrying selection members.

`edit.delta` is an ordered notification:

```json
{
  "document":"doc:notes/123",
  "editor_id":"body",
  "session":"00112233445566778899aabbccddeeff",
  "seq":1,
  "start":3,
  "del":2,
  "text":"abc",
  "len":13
}
```

`seq` MUST be exactly one greater than the receiver's current sequence.
`start` is the splice start, `del` the number of scalar values removed, `text`
the inserted string, and `len` the required resulting scalar length. The
receiver MUST verify:

```text
len = old_length - del + scalar_length(text)
```

It MUST apply a valid splice atomically. On any failure it MUST mark the
session stale and MUST request resynchronization once; it MUST ignore further
deltas until the resynchronization completes.

A delta's granularity is the Companion's choice. Local editing is applied to
the shadow immediately and never waits for Emacs; the Companion MAY coalesce
a rapid sequence of local edits into one composite splice before assigning
`seq`, and SHOULD do so when edits arrive faster than mirroring them is
useful, provided the composite splice satisfies the length equation and
respects platform composition atomicity. Coalescing widens the window in
which a concurrent `edit.apply` receives a `stale` result; the Companion
SHOULD bound its coalescing interval so that window stays short.

`edit.caret` contains `document`, `editor_id`, `session`, `seq`, `cursor`, and
optional paired `sel_start` and `sel_end`. It is accepted only when `session` and `seq` match. It is
best-effort presentation context and MUST NOT change document text. The
Companion SHOULD throttle caret reporting at the source; an intermediate
position it never emits is not conflation under Section 22.2, which governs
only messages already emitted.

`edit.close` is `{document, editor_id, session}`. It MUST release session
resources. Unsaved-document policy belongs to Emacs and MUST be represented by
explicit actions, not inferred by the Companion.

`edit.complete` is a request containing `document`, `editor_id`, `session`,
`seq`, and `cursor`. Emacs MUST answer only when the session and sequence match. Its result
is:

```json
{
  "prefix":"pri",
  "candidates":[
    {"label":"print","annotation":"function","insert":"print()"}
  ]
}
```

The result and each candidate are closed objects. `prefix` MUST be a string and
`candidates` MUST be an array. Each candidate MUST contain a non-empty string
`label` and MAY contain string `annotation` and string `insert`; `insert`
defaults to `label` and MAY be empty. A stale query MUST receive
`1201 content-invalid` with `data.kind: "content-invalid"` and
`data.reason: "editor-stale"` and SHOULD trigger a resync.

The returned `prefix` MUST equal the Unicode-scalar substring immediately
before the requested cursor that the candidate will replace; an empty prefix is
allowed. On candidate selection, the Companion MUST first verify that the
session, sequence, cursor, and prefix still match. If they do, it MUST replace
that prefix with `insert` as one local edit, advance the sequence, and send the
corresponding `edit.delta`. If they do not, it MUST discard the result without
changing text and MAY issue a new completion request.

### 19.4 Emacs-to-Companion methods

`edit.resync` is a request with `{document, editor_id, session}` naming any
matching session the Companion still knows as non-`CLOSED`. This permits Emacs
to recover when only its own view is stale. The Companion MUST atomically close
that prior session, mint a fresh session ID, and return its current full state:

```json
{
  "document":"doc:notes/123",
  "editor_id":"body",
  "session":"ffeeddccbbaa99887766554433221100",
  "seq":0,
  "text":"complete current text",
  "cursor":4,
  "sel_start":4,
  "sel_end":4
}
```

The new sequence MUST be `0`; both endpoints MUST discard the prior sequence
history after accepting it. A delayed message carrying the old session ID MUST
NOT be accepted into the new epoch. An unknown or `CLOSED` tuple MUST receive
`1201 content-invalid` with `data.reason: "editor-stale"` and MUST NOT create a
new session.

`edit.apply` is a request. A text-changing form contains `document`,
`editor_id`, `session`, `seq`, `start`, `del`, `text`, `len`, `cursor`, and
optional paired `sel_start` and `sel_end`.
A move-only form omits all of `start`, `del`, `text`, and `len`, retains the
current `seq`, and changes only caret/selection.

The Companion is the serialization point for local edits and inbound
`edit.apply` requests. It MUST process them in one total order. Whichever valid
text-changing operation first claims `seq + 1` wins; a competing operation
based on the old sequence MUST receive or cause a stale outcome and MUST NOT be
merged implicitly. Emacs MUST treat an incoming delta as authoritative when an
outstanding apply for that same next sequence later returns stale.

The Companion MUST apply a text-changing form only when:

- `seq` is exactly one greater than its current sequence;
- the current editor text still equals its synchronized shadow;
- the splice and resulting length are valid; and
- no platform text-composition transaction would be corrupted.

It MUST return `{status:"applied", seq}` on success or
`{status:"stale", seq:<current>}` without changing text when a gate fails. A
text-changing apply SHOULD be one native undo step. A move-only form succeeds
only at the current sequence.

### 19.5 Annotations

`diagnostics.show` params are `{editor_id, session, seq, diagnostics}`. Each
diagnostic is `{start, end, severity, message}` where severity is `error`,
`warning`, `info`, or `hint`.

`fontify.show` params are `{editor_id, session, seq, runs}`. Each run is
`{start, end, role}` where `role` is a syntax theme role. Runs MUST be sorted,
MUST NOT overlap, and MUST fit the synchronized text.

`eldoc.show` params are `{editor_id, session, seq, text}`. `text` is plain
documentation text.

The Companion MUST discard an annotation whose session or sequence does not
match its current state. These methods are latest-wins per editor and sequence;
they MUST NOT delay text synchronization.

## 20. Device capability module

The device-capability module is OPTIONAL and is negotiated as `capabilities`.
It allows Emacs to invoke finite Companion-advertised platform operations.

### 20.1 Device report

When `capabilities` or `triggers` is granted, the welcome MUST include a device
report. This example assumes both are granted:

```json
{
  "device": {
    "caps": ["vibrate", "state.get"],
    "trigger_caps": ["vibrate"],
    "permissions": {"post_notifications":true},
    "settings_panels": [],
    "intent_allowlist": [],
    "launchable_packages": [],
    "trigger_types": ["battery.level"],
    "state_types": ["battery.level", "screen"],
    "trackable_state_types": ["battery.level", "screen"],
    "trigger_unavailable": {}
  }
}
```

The device report members have these exact types:

| Member | Type and requirement |
|---|---|
| `caps` | REQUIRED array of distinct capability identifiers |
| `trigger_caps` | REQUIRED array of distinct capability identifiers; MUST be empty unless `triggers` is granted |
| `permissions` | REQUIRED object mapping permission identifiers to booleans |
| `settings_panels` | array of distinct panel identifiers; REQUIRED when `settings.open` is in `caps` |
| `intent_allowlist` | array of distinct closed allowlist entries; REQUIRED when `intent.start` is in `caps` |
| `launchable_packages` | array of distinct package-name strings; REQUIRED when `app.launch` is in `caps` |
| `trigger_types` | array of distinct trigger-type identifiers; REQUIRED when `triggers` is granted |
| `state_types` | array of distinct state-type identifiers; REQUIRED when `triggers` is granted or `state.get` is in `caps` |
| `trackable_state_types` | array of distinct values from `state_types`; REQUIRED when `triggers` is granted |
| `trigger_unavailable` | object mapping values from `trigger_types` to non-empty arrays of distinct blocking permission identifiers; REQUIRED when `triggers` is granted |

`caps` is the exact Section 20 capability catalog supported by the Companion;
`capability.invoke` remains unavailable unless `capabilities` was granted.
`trigger_caps` is the exact subset permitted inside unattended `on_fire`
responses and MUST be a subset of `caps`. `permissions` is a snapshot of named
platform grants. `settings_panels` is REQUIRED when `settings.open` appears in
`caps`, `intent_allowlist` is REQUIRED when `intent.start` appears, and
`launchable_packages` is REQUIRED when `app.launch` appears. Each is a
positive-knowledge list; omission MUST NOT mean unrestricted access.
`trigger_types`, `trackable_state_types`, and `trigger_unavailable` are REQUIRED
when `triggers` is granted and otherwise MAY be empty. `state_types` is REQUIRED
when either `triggers` is granted or `state.get` appears in `caps`.

The complete device report's canonical size under Section 4.5 MUST NOT exceed
`limits.max_device_report_bytes`. A Companion whose full catalog would exceed
that bound MUST advertise a bounded subset that fits; it MUST NOT emit a device
report that depends on truncation.

The Companion MUST re-check authorization at invocation or trigger-arm time. A
stale permission snapshot may produce a typed refusal but MUST NOT permit an
unauthorized operation.

### 20.2 `capability.invoke`

Params are `{cap, args?}`. `cap` MUST appear in `device.caps`; `args` defaults to
`{}`. On success, the JSON-RPC result MUST be exactly the object shown in the
catalog row and MUST NOT be wrapped in another `result` member; operations
without output return `{}`. An unsupported name MUST receive `1001`; a missing
permission MUST receive `1002`; and an attempted operation that fails MUST
receive `1003`. An invalid argument shape or range MUST receive `-32602` before
any side effect begins.

The Companion MUST validate all arguments before beginning side effects. It
MUST NOT treat a string argument as executable code. A capability advertised
by name MUST implement the schema and observable semantics in its registry.

Capability invocations are session-scoped and non-durable. If a timeout or
transport loss occurs before a response, the caller MUST treat the outcome as
indeterminate and MUST NOT automatically retry the invocation, because a side
effect may already have occurred. A later invocation requires an explicit
application or user decision and a new request ID. No catalog entry in this
version defines an idempotency key.

### 20.3 Capability catalog

The following catalog is OPTIONAL per entry. Android-specific entries are
identified as such; a non-Android Companion MAY omit them. Advertising an entry
makes its row normative.

Every Args and Result object shown in the catalog is closed. A member suffixed
with `?` is optional; every other shown member is REQUIRED. Invalid Args MUST
receive `-32602` before side effects. Success results MUST NOT add
implementation-private members. An invalid Result is a protocol violation: the
caller MUST fail its local invocation, SHOULD send one safe `log.error`, and
MUST NOT answer the response with another response.

| Capability | Args | Result | Requirements |
|---|---|---|---|
| `settings.open` | `{panel}` | `{}` | `panel` MUST appear in `device.settings_panels`. Standard names are `app-details`, `notifications`, `battery-optimization`, `accessibility`, `wireless`, `bluetooth`, `location`, `sound`, and `dnd`; the Companion MAY advertise a subset. |
| `intent.start` | `{action, data?, package?, class_name?, mime?, extras?, mode?}` | `{}` | Android-specific and governed by the exact allowlist below. `mode` defaults to `activity`. |
| `app.launch` | `{package}` | `{}` | Launch only a package in `device.launchable_packages`; Android-specific. |
| `apps.list` | `{cursor?,limit?}` | `{apps:[{label,package}],next_cursor?}` | Page through packages visible and launchable to the Companion. |
| `shortcut.pin` | `{id,label,action,icon_png?,long_label?}` | `{updated:boolean}` | Request a pinned launcher shortcut. `action` is a remote ActionDescriptor. `icon_png` is base64 PNG whose decoded form MUST NOT exceed `max_shortcut_icon_bytes` and MUST be decoded safely. |
| `shortcuts.set` | `{shortcuts: Shortcut[]}` | `{count}` | Atomically replace dynamic shortcuts. The array MUST NOT exceed `max_shortcuts`; the Companion MUST reject, not truncate, an over-limit set. |
| `vibrate` | exactly one of `{ms}` or `{pattern}` | `{}` | `ms` is an integer `1..60000`. `pattern` contains `1..64` integers `0..60000`, alternates off/on durations beginning with off, and MUST total at most 60000 ms. |
| `tts.speak` | `{text,pitch?,rate?}` | `{}` | `pitch` and `rate` are finite numbers `0.5..2.0`, default `1.0`. Queue best-effort plain speech; success means accepted by the engine, not audibly completed. |
| `volume.set` | `{stream,level}` | `{max}` | Stream is `music`, `ring`, `alarm`, `notification`, `call`, or `system`; `level` and returned `max` are non-negative integers, and level is clamped to `0..max`. |
| `ringer.mode` | `{mode}` | `{}` | Mode is `normal`, `vibrate`, or `silent`; platform policy access MAY be required. |
| `flashlight` | `{on:boolean}` | `{}` | Operate one advertised flash-capable camera. |
| `media.key` | `{key}` | `{}` | Key is `play_pause`, `play`, `pause`, `next`, `previous`, `stop`, `fast_forward`, or `rewind`. |
| `clipboard.read` | `{}` | `{text}` | MUST NOT log or persist clipboard content; platform foreground restrictions and the size rule below apply. |
| `screen.keep_on` | `{on:boolean}` | `{}` | Applies only while the Companion UI is visible; MUST NOT claim to keep a background process alive. |
| `brightness.set` | `{level}` | `{}` | Android-specific integer `0..255`; special permission MAY be required. |
| `dnd.set` | `{mode}` | `{}` | Mode is `on`, `off`, or `priority`; policy permission is REQUIRED where the platform requires it. |
| `state.get` | `{types?, when?}` | `{states, unavailable?, holds?}` | Sample Section 21 state predicates. |
| `trigger.fire` | `{id}` | `{}` | Fire one registered `manual` trigger with source `emacs`; unknown or non-manual IDs fail. |

Unless a row gives a narrower type, `text`, `label`, `long_label`, `package`,
`class_name`, `mime`, and app labels are strings; capability and object `id`
values are identifiers; boolean-shaped members are booleans; and `count` is a
non-negative integer. `intent.start.action` is a non-empty string and `data` is
an absolute URI string. `icon_png` is standard padded [RFC4648] base64 of a PNG,
not a data URL. `apps.list.apps` is an array of closed
`{label: string, package: string}` objects. Each label MUST be non-empty and at
most 1024 JCS-encoded bytes; each package MUST be non-empty and at most 512
JCS-encoded bytes. `clipboard.read.text` is a string.
`state.get.types` is an array of distinct state-type identifiers and
`state.get.when` is a state-predicate array.

For `apps.list`, `limit` is an integer `1..256` and defaults to `100`.
`cursor` is a package string previously returned as `next_cursor`; omission
starts at the beginning. The Companion MUST sort its current distinct package
set by case-sensitive Unicode code-point order and return the first at most
`limit` entries whose package is strictly greater than `cursor`. It MUST return
every such entry in that page, not an arbitrary subset. `next_cursor` MUST be
the final returned package when more entries remain and otherwise MUST be
omitted. A package added or removed between calls MAY affect later pages, so a
caller needing a coherent refresh SHOULD restart without a cursor.

For `clipboard.read`, the canonical encoded size of `text` under Section 4.5
MUST NOT exceed `limits.max_field_bytes`. Oversized or non-scalar clipboard
text MUST receive `1003 cap-failed` with
`data.reason: "clipboard-too-large"`; it MUST NOT be truncated.

An activity-launching operation is best-effort when platform policy forbids a
background launch. Returning success MUST mean that the Companion handed a
valid request to the platform, not that another application completed it.

A `Shortcut` MUST contain `id`, `label`, and `action: remote ActionDescriptor`; it MAY
contain `icon_png` and `long_label` under the same validation rules as
`shortcut.pin`. Shortcut IDs MUST be distinct in one set.

When a shortcut is invoked, the Companion MUST inject `shortcut_id` into a copy
of the descriptor's `args` and enter the normal Section 14 pipeline without a
surface, dialog, or revision context. An authored conflicting `shortcut_id`
makes the shortcut invalid.

Pinned and dynamic shortcut ownership is scoped to the pairing identity.
`shortcuts.set` atomically replaces only that identity's dynamic set, and
`shortcut.pin` MUST derive or reserve a platform-visible identity that cannot
overwrite another pairing's shortcut with the same authored `id`. A Companion
MUST merge identity-owned sets when presenting them to a global platform API
and MUST report a platform capacity failure rather than delete another
identity's entries.

Each `device.intent_allowlist` entry is a closed object containing `action` and
`mode`, and MAY contain `package`, `class_name`, `schemes`, `authorities`,
`mime_types`, `extra_keys`, and `trigger`. `mode` is `activity`, `broadcast`, or
`service`; the four plural members are arrays of distinct exact strings;
`trigger` defaults to `false`. There are no wildcards. A request matches only
when `action`, effective `mode`, `package`, and `class_name` exactly equal the
entry, including matching absence; any data URI has a listed scheme and, when
present, a listed authority; any MIME type is listed; and every extras key is
listed. `class_name` requires `package`. URI user-information is prohibited.

The Companion MUST reject an `intent.start` request that matches no entry with
error `1003 cap-failed` and `data.reason: "intent-denied"`. It MUST NOT fall back
to implicit intent resolution after a failed explicit match. Broadcast,
service, and explicit-class requests are forbidden unless their exact tuple is
listed. Extras values MUST be strings, finite numbers, booleans, or arrays of
those scalars; serialized objects and platform object types are forbidden. The
Companion MUST validate the tuple immediately before handing it to the
platform. An allowlist entry with `trigger: true` MUST use `broadcast` or
`service`, never `activity`. An `on_fire` use additionally requires
`intent.start` in `trigger_caps` and a matching entry whose `trigger` is `true`.

## 21. Device trigger module

The trigger module is OPTIONAL and is negotiated as `triggers`. It gives Emacs
a closed declarative way to register device event sources and bounded offline
responses without transferring general control flow.

### 21.1 Trigger replace-set

`triggers.set` params are:

```json
{
  "triggers":[
    {
      "id":"battery-low",
      "type":"battery.level",
      "params":{"below":20},
      "when":[{"type":"screen","state":"off"}],
      "policy":"queue",
      "ttl_s":86400,
      "dedupe":"battery-low",
      "throttle_s":3600,
      "on_fire":[{"notify":{"text":"Battery ${data.level}%"}}]
    }
  ]
}
```

Trigger IDs MUST be unique in the set. A trigger entry is a closed object with
this schema:

| Member | Type | Required | Default or constraint |
|---|---|---:|---|
| `id` | identifier | yes | Unique in the set |
| `type` | trigger-type identifier | yes | MUST appear in `device.trigger_types` |
| `params` | object | no | `{}`; exact type-specific closed schema from Section 21.5 |
| `when` | array of state predicates | no | `[]`; flat logical AND |
| `policy` | `drop` \| `queue` \| `wake` | no | `drop` |
| `ttl_s` | integer `1..604800` | conditional | REQUIRED for `queue` and `wake`; forbidden for `drop` |
| `dedupe` | identifier | no | Valid only for `queue` and `wake` |
| `throttle_s` | integer `1..604800` | no | Omission means no throttle |
| `on_fire` | array of local response objects | no | `[]`; at most `limits.max_trigger_responses` entries |

The Companion MUST validate the complete set, including every type, predicate,
offline policy, local response, resource limit, and required permission
descriptor, before changing registrations. Acceptance MUST atomically replace
the previous set for the pairing identity and return `{count}`, where `count`
is a non-negative integer equal to the accepted array length. Rejection MUST
use `1101 triggers-rejected`, MUST identify the failing trigger where safe, and
MUST leave the prior set armed unchanged. An empty set clears all registrations.

Accepted registrations MUST persist across Companion and device restarts.
Removed IDs MUST NOT fire. The Companion MUST NOT silently truncate the set.

Before comparing registrations, the Companion MUST apply every documented
default. An ID whose resulting complete entry is equal under Section 4.3 is
unchanged. For an unchanged ID, accepting the set MUST be observationally
equivalent to never having replaced it: the Companion MUST carry forward,
unmodified, every runtime record attached to that registration — its throttle
floor, its one-shot completed marker, a repeating schedule's acceptance anchor
and last-fire floor, its recorded boot-generation receipt, and every silent
baseline and stored edge level from Sections 21.5 and 21.6. The Companion MUST
NOT re-baseline, re-anchor, or re-arm an unchanged ID, and a transition or
threshold crossing in progress across the replacement MUST fire exactly as it
would have fired had the set not been replaced. A changed or removed ID MUST
discard every such registration-state record; re-adding it later is a fresh
registration and establishes a new silent baseline, schedule anchor, and boot
generation. Event records admitted before a trigger is changed or removed are
immutable historical occurrences and MUST remain eligible for normal replay,
expiry, and dedupe disposition.

### 21.2 Firing and delivery

A trigger occurrence MUST enter the normal event pipeline as:

```json
{
  "action":"trigger.fired",
  "args":{"id":"battery-low","type":"battery.level","data":{"level":19}}
}
```

When a remote event is created, the complete `event.action` request MUST also
include its generated `event_id`, `occurred_at_ms`, and queue timestamp when
applicable. A trigger event has no surface, revision, or dialog context.

The Companion MUST process one admitted occurrence in this order:

1. evaluate the state gate and throttle eligibility;
2. freeze its immutable fire data and, for `queue`, `wake`, or a `drop`
   occurrence while `READY`, generate its EventId;
3. durably commit the new throttle state, any one-shot completion or
   boot-generation receipt, and, for `queue` or `wake`, the complete event
   record and `queue_seq` in one transaction;
4. execute local `on_fire` entries in authored order; and
5. make the remote event eligible for FIFO delivery, or deliver a live `drop`
   event only when `READY`.

The `drop` rule in Section 15.1 applies to the remote portion of a trigger. If
no `READY` session exists, an admitted `drop` trigger MUST NOT create an
EventId or remote-delivery record, but it MUST still commit throttle state and
MUST attempt its best-effort local `on_fire` entries in authored order. This local occurrence is
not an `event.action` and MUST NOT be replayed after process death.

A failed gate or throttle check MUST NOT consume throttle state, execute local
responses, or create an event. If the durable transaction fails, the Companion
MUST NOT execute local responses or claim remote admission. For `wake`, the wake
attempt occurs only after that transaction. A durable record MAY carry a
`pending-local` marker so remote delivery cannot race ahead of Step 4.

`throttle_s` is the minimum elapsed time between admitted occurrences of one
trigger ID. The Companion MUST persist enough throttle state to prevent a
restart from producing an immediate duplicate. Wall-clock rollback MUST NOT
permit an earlier-than-allowed fire; an implementation SHOULD use monotonic
elapsed time while running and conservative persisted wall time across restart.

### 21.3 State gates

`when` is a flat array of predicates and means logical AND. There is no nested
expression, OR, or arbitrary negation. An empty array holds. A predicate that
cannot be evaluated because of an unknown type, unavailable permission, or
platform failure MUST count as not holding.

Emacs MUST include a gate only when every predicate type appears in
`device.state_types`. If any type is absent, Emacs MUST omit the entire trigger;
it MUST NOT remove the unsupported predicate and install a weaker trigger.

The Companion MUST reject a malformed gate atomically. Evaluation MUST
terminate and MUST perform no polling or unbounded work.

### 21.4 Companion-local `on_fire`

`on_fire` is an ordered array containing only:

- `{cap, args?}`, invoking a capability in `device.trigger_caps`; or
- `{notify:{title?, text}}`, posting a simple local notification.

There are no branches, loops, recursion, dynamic operation names, or arbitrary
method calls. The Companion MUST validate every entry when installing the set.
An unavailable permission MAY leave the trigger registered but unarmed; an
unknown operation MUST reject the entire set.

`device.trigger_caps` MUST contain only operations the Companion can execute
unattended, in bounded time, whose catalog result is `{}`, and that do not
require an interactive UI. It MUST NOT contain `settings.open`, `apps.list`,
`clipboard.read`, `shortcut.pin`, `shortcuts.set`, or `trigger.fire`. A capability's normal
permission and consent checks still apply at fire time. A runtime failure of
one local entry MUST be recorded safely and MUST NOT stop later entries or
cancel an already admitted remote event.

For a durable occurrence, the Companion SHOULD persist progress through the
local list and resume incomplete entries after restart. Because a crash can
occur after a platform side effect but before its progress marker, local
effects MAY repeat at that boundary. Implementations SHOULD choose idempotent
trigger capabilities or key their platform work by EventId. For a `drop`
occurrence, local responses are best effort and MUST NOT be replayed after
process death. Recovery MUST eventually clear `pending-local` and make an
admitted remote event eligible: it MUST NOT strand the remote event because a
local effect cannot be proven. A resumed or skipped local entry MUST be recorded
as a diagnostic without sensitive arguments.

String values inside `args` and `notify`, recursively through objects and
arrays, MAY use these fire-time substitutions:

- `${id}` — trigger ID;
- `${type}` — trigger type; and
- `${data.FIELD}` — a direct member of the fire data object.

Substitution MUST be single-pass and MUST always produce a string. Numbers and
booleans use their JSON spelling. Missing or null values leave the token
literal. `$${` produces literal `${`. The `cap` name and JSON member names MUST
NOT be interpolated.

Substituting data from `sms.received`, `call.state`, or `calendar.event` into a
notification, TTS, intent, sharing target, or other user-visible or external
sink requires explicit user approval of that source-to-sink combination at
install time. Without approval, the Companion MUST reject the trigger set. This approval is
per (sensitive source type, sink kind) combination and defaults to deny:
approving one combination MUST NOT approve another, and a single blanket
allowance covering all sources or all sinks is non-conformant.
Sensitive substituted data MUST NOT appear on a lock screen unless the user
separately allowed that exposure.

### 21.5 Trigger catalog

An omitted `params` object means “match every occurrence” where that concept is
defined. Registering a type absent from `device.trigger_types` MUST be rejected.
Every trigger params object and predicate is closed: an unknown member or enum
value MUST reject the complete replace-set rather than broaden a filter.

| Type | Params | Fire data | Normative behavior |
|---|---|---|---|
| `time` | exactly one of `{at_ms}` or `{every_s}` | `{precision}` | One-shot or repeating. `every_s` MUST be at least 60. `precision` is `exact` or `inexact`; the Companion MUST NOT claim exactness it lacks. |
| `power` | `{state?}` | `{state,plug?}` | State is `connected` or `disconnected`; plug MAY be `ac`, `usb`, or `wireless`. |
| `battery.level` | exactly one of `{above}` or `{below}` | `{level}` | Percentage is `0..100`; fire only on crossing into the configured side, not every reading. |
| `screen` | `{state?}` | `{state}` | State is `on`, `off`, or `unlocked`. |
| `headset` | `{state?}` | `{state,name?}` | State is `plugged` or `unplugged`. |
| `airplane` | `{state?}` | `{state}` | State is `on` or `off`. |
| `boot` | `{}` | `{}` | Fire once for a device boot after registrations are restored. |
| `timezone.changed` | `{}` | `{tz}` | `tz` is the new time-zone identifier. |
| `package` | `{event?,package?}` | `{event,package}` | Event is `added` or `removed`; update replacements MUST NOT appear as a removal/add pair. |
| `manual` | `{}` | `{source}` | Fires only through the builtin or capability; source is `tap` or `emacs`. |
| `state.edge` | `{when,edge?}` | `{holds,edge}` | Convert an advertised trackable-state conjunction into `rise`, `fall`, or `both` edges. |
| `network` | `{event?,transport?}` | `{event,transport?}` | Event is `available` or `lost`; transport is `wifi`, `cellular`, `ethernet`, `vpn`, or `bluetooth`. |
| `wifi.enabled` | `{enabled?}` | `{enabled}` | Fire only on stable adapter enabled/disabled edges. |
| `bluetooth.enabled` | `{enabled?}` | `{enabled}` | Fire only on stable adapter enabled/disabled edges. |
| `calendar.event` | `{event?,calendar?,title_contains?}` | `{event,title?,begin_ms?,end_ms?}` | Event is `started` or `ended`; requires calendar permission and MUST avoid duplicate boundary fires. |
| `sms.received` | `{from?,contains?,include_body?}` | `{from,body?}` | Requires SMS permission. Body is returned only when `include_body:true`; content MUST NOT be logged. |
| `call.state` | `{state?,number?,include_number?}` | `{state,number?}` | State is `ringing`, `offhook`, or `idle`; number matching/reporting requires the applicable call-log permission. Duplicate platform reports MUST be deduplicated. |

A threshold, percentage, or duration is an integer in its stated range.
`include_body` and `include_number` are booleans defaulting to `false`.
`enabled`, when present in trigger params, is boolean; when absent it imposes no
filter. Package names, calendar identifiers, SMS sender strings, and call
number strings use exact case-sensitive code-point comparison with no
normalization. Fields named `contains` or `title_contains` are non-empty strings
and match a contiguous, case-sensitive code-point substring. Optional `event`,
`state`, and `transport` fields accept only the enum values shown in their row.
Omitting one of those filter fields matches every otherwise eligible value; it
MUST NOT select an undocumented platform default. `state.edge.edge` has the
separate default in Section 21.6.

For `power`, `battery.level`, `screen`, `headset`, `airplane`, `state.edge`,
`network`, `wifi.enabled`, `bluetooth.enabled`, `calendar.event`, and
`call.state`, the Companion MUST establish the current state or level silently
when first arming a new or changed registration and when restoring
registrations after a Companion or device restart; an unchanged ID in an
accepted replace-set retains its existing baseline under Section 21.1. A sticky
platform report that merely supplies that baseline MUST NOT fire. The first
eligible occurrence requires a later observed transition, threshold crossing,
or calendar boundary. This rule does not suppress a new external occurrence
for `package`, `sms.received`, or the explicit time, boot, time-zone, and manual
sources.

The `screen` states are mutually exclusive: `off` means the display is not
interactive, `on` means it is interactive while keyguard is locked, and
`unlocked` means it is interactive with keyguard unlocked. A relock while the
display remains interactive is a transition from `unlocked` to `on`. A
`screen` trigger's `state` filter matches that exact reported state. In a state
predicate, `state: "on"` holds for either `on` or `unlocked`, while
`state: "unlocked"` holds only for `unlocked`.

For a newly added or changed one-shot entry, `time.at_ms` MUST be later than the
wall clock at set acceptance. An unchanged entry remains valid after that time,
including when already completed. On admission of its first eligible
occurrence, the Companion MUST commit a completed marker in Section 21.2's
transaction even for `drop`; it MUST NOT create another occurrence while that
unchanged entry remains registered. Completed entries remain in the set and in
the returned `count` until replaced or removed. Repeating `time.every_s`
schedules its first occurrence one interval after the acceptance that first
introduced or last changed the entry, and preserves its acceptance anchor and
last-fire floor across restart and across replace-sets in which the entry is
unchanged (Section 21.1). Missed intervals MUST be coalesced into at most
one occurrence; a restart or set replacement MUST NOT produce a catch-up burst.

For `boot`, the Companion MUST obtain a stable platform boot generation or
maintain an equivalent durable boot marker. Installing a new or changed
registration MUST record the current generation silently and arm it for the
next device boot; an unchanged registration keeps its recorded generation and
receipt under Section 21.1. After a boot, the restored registration MUST admit at most
one occurrence for that generation and MUST commit its generation receipt in
Section 21.2's transaction. Companion process restarts during the same device
boot MUST NOT create additional occurrences.

For privacy-sensitive `sms.received` and `call.state`, `policy: "drop"` is
RECOMMENDED. If queued, payloads MUST remain in app-private encrypted storage
where the platform provides a keystore-backed facility and MUST be deleted
immediately after permanent disposition or expiry.

### 21.6 `state.edge`

`state.edge.params.when` uses the exact predicate grammar below. Every type
MUST appear in `device.trackable_state_types`. `edge` defaults to `rise` and is
`rise`, `fall`, or `both`.

The Companion MUST evaluate and store the initial level silently when arming a
new or changed registration; an unchanged registration keeps its stored level
across a replace-set (Section 21.1). Arming, replacement, and reboot MUST NOT
themselves fire an edge. Later truth transitions fire in the selected
direction. A row-level `when` remains an
additional gate evaluated after the tracked edge is detected.

### 21.7 State predicates and sampling

A predicate is an object containing `type` plus the fields in this table:

| Type | Fields | Holds when |
|---|---|---|
| `power` | `state?` | Power equals `connected` (default) or `disconnected`. |
| `battery.level` | exactly one of `above`, `below` | Current percentage is strictly above or below the bound. |
| `screen` | `state?` | `on` (default) includes logical `on` and `unlocked`; `off` and `unlocked` match exactly. |
| `airplane` | `state?` | Airplane mode equals `on` (default) or `off`. |
| `network` | `transport?` | A network is connected and transport matches when supplied. |
| `headset` | `state?` | Wired/USB output is `plugged` (default) or `unplugged`. |
| `wifi.enabled` | `enabled?` | Adapter enabled state equals the boolean, default `true`. |
| `bluetooth.enabled` | `enabled?` | Adapter enabled state equals the boolean, default `true`; no adapter is unevaluable. |
| `calendar.event` | `calendar?`, `title_contains?` | A matching event is ongoing now. |
| `call.state` | `state?` | Call state equals `offhook` (default), `ringing`, or `idle`. |
| `time.window` | `after?`, `before?`, `days?` | Local civil time is in the half-open window. |

When sampled through `state.get`, each state type has this exact current-object
shape:

| State type | Sample object |
|---|---|
| `power` | `{state, plug?}` using the power enums above |
| `battery.level` | `{level}` with integer `0..100` |
| `screen` | `{state}` where state is `on`, `off`, or `unlocked` |
| `airplane` | `{state}` where state is `on` or `off` |
| `network` | `{connected, transports}` where `connected` is boolean and `transports` is an array of distinct advertised transport enums |
| `headset` | `{state, name?}` where state is `plugged` or `unplugged` and name is a string |
| `wifi.enabled` | `{enabled}` with boolean value |
| `bluetooth.enabled` | `{enabled}` with boolean value |
| `calendar.event` | `{ongoing}` with boolean value for whether any authorized event is ongoing |
| `call.state` | `{state, number?}` using the call enums; number MUST be omitted without the applicable permission and user policy |

`time.window.after` and `before` are `HH:MM`. The interval wraps midnight when
`after` is later than `before`; an omitted bound is open. Equal present bounds
define an empty window. `days` is an array of distinct values from `mon`
through `sun` and defaults to every day. For a wrapping window, `days` selects
the civil day on which the `after` portion begins, so Tuesday 01:00 belongs to
Monday's `23:00`–`02:00` window. For a non-wrapping window or one with an omitted
bound, `days` selects the current civil day.

`state.get.types` is an array of distinct advertised state-type names other
than `time.window`; omission selects every advertised sampleable type other
than `time.window`. Its `states` maps each successfully sampled type to a
sample object from the table above. `states` is REQUIRED, even when empty.
`unavailable`, when non-empty, maps each requested but unsampled type to a stable
identifier string and otherwise MUST be omitted. Parameterized `time.window`
predicates are valid only inside `when`
and do not create a `states` entry. When `when` is supplied, `holds` MUST be the
boolean result of the same evaluator used for trigger gates, including any such
time window; otherwise `holds` MUST be omitted.

### 21.8 Permission revocation

If a required permission is revoked, the Companion MUST stop or skip affected
registrations and MUST make affected predicates fail closed. It MUST NOT emit a
fabricated or partially authorized fire. The next welcome MUST map each
supported-but-unarmable trigger type to a non-empty array of its blocking permission identifiers in
`device.trigger_unavailable`. Registrations MAY remain stored and MAY arm after
permission is restored.

## 22. Capability registry and load management

### 22.1 Protocol capability registry

This document defines these session capability names:

| Capability | Meaning |
|---|---|
| `surfaces.notification` | `notification:*` surfaces and Section 18.5 metadata |
| `surfaces.widget` | `widget:*` surfaces |
| `surfaces.tile` | `tile:*` surfaces (host Quick-Settings tile slots) |
| `surfaces.dialog` | `dialog.show` |
| `presentation.toast` | `toast.show` |
| `presentation.pie-menu` | `pie_menu.show` and `pie_menu.dismiss` |
| `theme` | `theme.set` |
| `reminders.owner` | Owner-scoped `reminders.set` |
| `editor.sync` | Section 19 editor methods |
| `capabilities` | `capability.invoke` and `device.caps` |
| `triggers` | `triggers.set`, trigger reports, and predicate reports |
| `offline.wake` | The Companion can attempt the `wake` offline policy |

Core session, `app:*` surfaces, state reporting, durable replay, and the Core
Node Set are not negotiated capabilities. A Companion claiming EBP core
conformance MUST implement them.

Adding a capability to this registry MUST define all associated methods,
objects, limits, failure behavior, and security properties. A capability name
MUST NOT be granted as a promise of unspecified best effort.

### 22.2 Traffic classes

EBP has three load-management classes:

1. **Latest-wins state.** Surface snapshots waiting locally to be sent, theme
   replacements, and editor annotations MAY be conflated by key. A sender
   SHOULD retain at most one unsent snapshot per surface and one unsent
   annotation per editor and sequence. It MUST NOT discard a request already
   transmitted without concluding its local caller.
2. **Ordered streams.** Editor opens, deltas, applies, carets, closes, and
   resynchronizations MUST NOT be reordered or conflated. A gap MUST make the
   stream stale and invoke its resync rule. This governs emitted messages;
   Section 19.3 controls what the Companion chooses to emit — pre-`seq`
   coalescing of local edits and source-throttled caret reporting are not
   conflation.
3. **Intent events.** `state.changed` and `event.action` MUST preserve required
   state-before-action and event ordering. Unsent `state.changed` values MAY be
   debounced or conflated latest-wins per `(surface, id)` only under Section
   14.6's mandatory flush rule. Once transmitted, they MUST NOT be discarded or
   reordered. `event.action` MUST NOT be conflated except by the explicit
   durable-queue `dedupe` rule before delivery.

A receiver MUST NOT claim to discard an obsolete frame “without parsing” when
the conflation key exists only inside that frame. It MAY discard an already
parsed, queued operation after safely identifying its class and key.

### 22.3 Bounded processing

Every endpoint MUST bound its inbound frame queue, parsed-message queue,
outstanding request count, and module-specific work queues. It MUST apply
transport backpressure before unbounded memory growth.

When authenticated processing capacity is exhausted and the endpoint cannot
apply a method's defined safe conflation or retry behavior, it SHOULD send:

```json
{"jsonrpc":"2.0","method":"log.error","params":{
  "code":1401,
  "message":"Inbound processing capacity exhausted",
  "data":{"kind":"overloaded"}
}}
```

It MUST then close the connection. Outstanding requests fail locally and
durable events without permanent results remain eligible for replay. An
endpoint MUST rate-limit `log.error` and MUST NOT allow diagnostic reporting to
become an additional overload source.

`log.error` params are `{code, message, data?}`. It is diagnostic and MUST NOT
be treated as a response, acknowledgement, or authorization decision.

For an action using `queue` or `wake`, the Companion MUST durably admit the
event before its first `event.action` attempt even when a `READY` session is
currently available. This ensures that connection loss between transmission
and response does not silently lose eligible intent. An action using `drop`
MAY be delivered without persistence and is allowed to be lost if its request
does not conclude.

## 23. Security and privacy considerations

### 23.1 Trust boundary

Successful pairing authorizes the Emacs endpoint to declare UI and invoke only
the capabilities advertised by the Companion. It does not authorize arbitrary
platform API access. The Companion MUST validate every capability call and
MUST continue to enforce platform permission and user-consent boundaries.

The Companion reports untrusted user and device data to Emacs. Emacs MUST
validate action arguments, text fields, URIs, document IDs, package names,
trigger data, and every other received value before use.

### 23.2 No remote evaluation

An implementation MUST NOT:

- evaluate an action name as Elisp or another language expression;
- execute text obtained from QR, NFC, clipboard, notification, editor, or
  sensor input without a separate explicit trust decision;
- pass unvalidated action or command names to an ambient command dispatcher;
- treat an EBP string as a shell command; or
- deserialize arbitrary platform objects from JSON.

A barcode, QR code, or NFC tag MAY be reported as plain action data. Automatic
execution of its contents is outside EBP and MUST require an explicit,
separately specified user trust policy.

### 23.3 Sensitive values

Pairing tokens, authentication proofs, password values, clipboard contents,
SMS bodies, call numbers, and private editor content MUST NOT appear in normal
logs, metrics, diagnostics, Goldens, or crash reports. Implementations SHOULD
redact all user-supplied strings by default and enable detailed payload logging
only through an explicit developer setting.

Persistent queues and input snapshots MUST use app-private storage. Where a
platform provides keystore-backed encrypted storage, sensitive queued trigger
data MUST use it. Durable event payloads and captured input snapshots MUST be
deleted after permanent disposition, expiry, pairing revocation, or explicit
queue clearing. This deletion rule does not remove the minimal EventId receipt
that Emacs MUST retain for the deduplication period in Section 14.4; that receipt
MUST NOT retain the event payload or captured fields.

### 23.4 Replay and stale state

Authentication nonces prevent reuse of an old handshake proof on a new
connection. Durable event IDs prevent deliberate repeated processing of an
acknowledged event. Surface revisions and tombstones prevent delayed snapshots
and removals from overwriting newer presentation state.

These mechanisms do not make stale user intent safe automatically. Emacs MUST
validate `revision_seen` and action semantics before accepting an event.

### 23.5 Resource exhaustion

Implementations MUST enforce Section 4 limits before allocating proportional
resources. They MUST bound decoded images, base64 payloads, canvas operations,
rich-text spans, table cells, chart points, trigger registrations, reminders,
editor sessions, and outstanding dialogs. They MUST reject excessive content
atomically and MUST NOT partially execute a rejected object.

### 23.6 Local transport limitations

Loopback addressing prevents remote network access but does not authenticate a
local process. The HMAC handshake supplies that authentication. It does not
provide confidentiality or per-message integrity against a privileged local
attacker. A deployment with a stronger threat model SHOULD use an authenticated
and encrypted transport profile.

## 24. Conformance

### 24.1 Companion core conformance

A conforming EBP 2 Companion MUST implement:

- the JSON and safe-integer rules in Section 4;
- at least one complete transport profile, including Section 6 framing for
  `android-loopback-tcp`;
- JSON-RPC request, notification, result, error, direction, class, ordering,
  cancellation, and unknown-method behavior;
- the pairing handshake and fail-closed session state machine;
- capability, per-target surface-profile, revision, tombstone, input-state, and
  limit reports in the welcome;
- `session.ready`, `surface.update`, `surface.remove`, `queue.replay`,
  `event.action`, `state.changed`, `log.error`, and `rpc.cancel`;
- atomic cached `app:*` surfaces and disconnected staleness semantics;
- durable event IDs, admission, replay, acknowledgement, expiry, and queue
  bounds;
- the Core Node Set in the `app` profile, unknown-node defensive fallback,
  action descriptors, `view.switch`, `companion.settings.open`, and `enabled`;
- `dialog.submit` and `dialog.dismiss` when `surfaces.dialog` is granted, while
  treating clipboard, sharing, and trigger builtins as optional per-profile
  advertisements; and
- the bounded-processing and security rules applicable to core behavior.

A Companion MUST NOT claim an optional capability, node type, feature,
trigger type, state type, or device capability it does not implement according
to this document.

### 24.2 Emacs core conformance

A conforming EBP 2 Emacs endpoint MUST implement:

- the corresponding JSON-RPC, framing, authentication, and session rules,
  with Section 6.2's receiver strictness scoped as that section states;
- `session.hello`, proof and welcome verification, synchronization ordering,
  queue replay, and `session.ready`;
- persistent monotonic per-surface revisions and absorption of Companion
  revision/tombstone floors;
- input-state reconciliation;
- explicit capability and per-target node, builtin, and feature gating;
- the semantic-action allowlist, argument validation, revision validation,
  durable event-ID retention, and permanent event results;
- safe surface and event retry behavior; and
- sender-side resource limits and load management.

### 24.3 Optional module conformance

An implementation claiming an optional module MUST implement every REQUIRED
method, state transition, type, and failure rule in that module. It MAY
advertise a subset of an entry-by-entry catalog, such as node types, device
capabilities, trigger types, or state types, only where the containing module
expressly permits subsets.

An implementation MUST NOT advertise `editor.sync` while implementing only
completion or only annotations; the editor state machine is one negotiated
unit. It MUST NOT advertise `triggers` without atomic replace-set behavior,
fail-closed gates, and durable trigger-event delivery.

### 24.4 Contract projection

`contract.json` SHOULD use a typed schema capable of expressing:

- reusable definitions for IDs, revisions, timestamps, Nodes, actions, and
  errors;
- discriminated unions with literal `t`, `action`, and `builtin` constraints;
- complete field types, required sets, enums, ranges, and defaults;
- each method's sender, class, legal states, capability gate, params, result,
  and permitted errors; and
- each registry defined by this document.

A property-name inventory without JSON types is not a sufficient contract
projection. The projection format MAY evolve independently, but changing its
format MUST NOT change the EBP wire contract implicitly.

### 24.5 Goldens

A Golden MUST be stored as a binary fixture containing one or more complete
wire messages exactly as transmitted, including ASCII framing headers and
UTF-8-encoded JSON bodies. Tools MUST read and write Goldens without newline,
encoding, BOM, or other byte transformations. Repositories SHOULD mark them
non-text, for example:

```gitattributes
goldens/** -text
```

Each Golden MUST identify:

- its transport profile;
- whether it is a positive or negative vector;
- the messages expected after decoding, or the expected transport/protocol
  error; and
- the normative rule it witnesses.

A decoder conformance test MUST feed the Golden bytes in varied transport-read
chunk sizes, including one octet at a time and multiple frames in one read. An
encoder conformance test MUST verify the exact framing syntax and byte count,
then compare the parsed JSON body semantically. It MUST NOT require arbitrary
JSON object-member order or escaping choices unless canonical JSON is added as
a separate normative rule.

### 24.6 Required adversarial tests

A core conformance suite MUST include at least:

1. a non-ASCII UTF-8 body whose `Content-Length` differs from its character
   count;
2. two frames with no delimiter between the first body and next header;
3. partial headers, partial bodies, invalid lengths, duplicate lengths,
   oversized declarations, invalid UTF-8, invalid JSON, over-deep JSON nesting,
   duplicate members, and prohibited batch arrays;
4. wrong-direction, wrong-class, unknown-request, and unknown-notification
   dispatch;
5. pre-auth request and notification refusal;
6. the Section 9.3 HMAC known-answer vector plus bad, replayed, and mismatched
   authentication proofs;
7. an update/remove/update race using revisions and tombstones;
8. connection loss before and after an `event.action` request is written and
   before and after its response is received;
9. duplicate event delivery after Emacs restart;
10. queued-event expiry, dedupe replacement, queue capacity exhaustion, and
    replay interruption;
11. an offline input draft followed by surface synchronization and replay;
12. password-state exclusion from persistence and logs;
13. unknown node, field, enum, builtin, capability, trigger, and predicate
    behavior; and
14. bounded overload behavior for each traffic class.

An optional-module suite MUST add failure and crash-boundary cases specific to
that module.

## 25. Registry evolution

Every normative change MUST be classified before publication:

- A change that invalidates a previously valid core message, changes required
  observable behavior, reinterprets an existing field, or weakens a security
  boundary MUST increment the protocol major.
- A new OPTIONAL capability, node type, trigger type, state type, or
  non-constraining field MAY be added within the major when positive discovery
  and safe fallback are complete.
- A new constraining feature MUST include a positive advertisement and a
  sender-side skip rule.

An amendment record SHOULD identify affected sections, artifacts, Goldens, and
human review. Editorial history and reference-implementation status are
repository process and MUST NOT alter the meaning of the current normative
document.

## 26. Normative references

- [RFC2119], *Key words for use in RFCs to Indicate Requirement Levels*.
- [RFC8174], *Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words*.
- [RFC8259], *The JavaScript Object Notation (JSON) Data Interchange Format*.
- [RFC8785], *JSON Canonicalization Scheme (JCS)*.
- JSON-RPC Working Group, *JSON-RPC 2.0 Specification*.
- [RFC2104], *HMAC: Keyed-Hashing for Message Authentication*.
- [RFC4648], *The Base16, Base32, and Base64 Data Encodings*.

[RFC2104]: https://www.rfc-editor.org/rfc/rfc2104
[RFC2119]: https://www.rfc-editor.org/rfc/rfc2119
[RFC4648]: https://www.rfc-editor.org/rfc/rfc4648
[RFC8174]: https://www.rfc-editor.org/rfc/rfc8174
[RFC8259]: https://www.rfc-editor.org/rfc/rfc8259
[RFC8785]: https://www.rfc-editor.org/rfc/rfc8785
