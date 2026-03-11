# dspatch Wire Protocol Specification

## Overview

dspatch is a protocol for running AI agent instances inside isolated containers and connecting them to a host application over WebSocket. Agents communicate with the host by exchanging typed **packages**. The Host Router routes packages between instances, persists output, surfaces inquiries to users, and manages instance lifecycle.

This document specifies the package type system, routing model, serialisation rules, agent state machine, and communication flows.

---

## Core Concepts

### Agent Instance

An agent instance is a single running conversation context inside an agent process. An agent process may host multiple instances simultaneously (e.g. one per open conversation). Each instance has a unique `instance_id` that serves as its network address for all routing purposes.

### Package

A package is the atomic unit of communication on the wire. Every package has a `type` string that identifies it. The `type` string is hierarchically scoped — the prefix determines the package category:

| Prefix | Category | Has `instance_id` |
|---|---|---|
| `agent.output.*` | Observable output (persisted, displayed) | yes |
| `agent.event.*` | Conversational protocol signals | yes |
| `agent.signal.*` | Lifecycle control signals | yes |
| `connection.*` | Connection management | no |

This means `packet_type` is not carried on the wire — the package category is fully determined by its `type` prefix.

### Routing Address

`instance_id` is the sole routing key for all agent-scoped packages. Every package addressed to or from a specific instance carries it. There is no broadcast, no "first available" fallback, and no host-level addressing — everything is instance-scoped.

### Routing Layers

The protocol defines three routing layers, each with a distinct responsibility:

**Host Router** — The central authority. Manages all WebSocket connections, routes packages between agent types, tracks conversation chains for `talk_to` routing, enforces the pre-configured supervision hierarchy for inquiry routing, prevents cyclic calls, and serves as the intermediary between agents and users. The Host Router is authoritative on all routing decisions — agents express intent, the Host Router decides policy.

**Agent Host Router** — One per agent type. Owns the single WebSocket connection for its agent type. Dispatches inbound packages from the Host Router to the correct instance by `instance_id`. Handles connection-level packages (auth, heartbeat, spawn) directly. Multiplexes multiple instances over a single connection.

**Agent Instance Router** — One per agent instance. Routes inbound packages to the agent based on instance state (idle, generating, waiting). Tags outbound output packages with `turn_id`. Manages the turn ID stack for interrupt/resume.

### Conversation Chain

A conversation chain is a directed sequence of agent instances linked by `talk_to` calls. When instance A calls `talk_to("B")`, the Host Router creates a link `A → B_instance`. If B then calls `talk_to("C")`, the chain extends to `A → B_instance → C_instance`.

The Host Router is the sole owner of chain state. Agents have no visibility into chains — they only know about their own `talk_to` calls. Chains are used for:

- **Routing**: When `continue_conversation=True`, the Host Router looks up the existing chain to reuse a target instance.
- **Cycle detection**: Before routing a `talk_to.request`, the Host Router checks whether the target agent type already appears in the caller's chain and rejects the call with an error message if so.

Conversation chains are purely about `talk_to` routing. They do not define supervisory relationships (see Supervision & Authority).

### Supervision & Authority

Agents operate within a pre-configured supervision hierarchy that defines clear authority boundaries. The hierarchy is declared at workspace configuration time, independent of any runtime conversation chains.

Each agent type may have a designated **supervisor** — another agent type that is responsible for decisions that exceed the agent's authority. When an agent encounters a question or decision it cannot handle autonomously, it escalates via `inquiry.request`. The Host Router uses the supervision hierarchy (not the conversation chain) to determine where to route that inquiry.

```
Example hierarchy:    lead (no supervisor — escalates to user)
    ├── coder (supervisor: lead)
    └── reviewer (supervisor: lead)
```

If `coder` sends an inquiry, the Host Router routes it to `lead`. If `lead` cannot answer, it escalates further — and since `lead` has no supervisor, the inquiry surfaces to the user.

Supervision is defined on **agent types**, not instances. The Host Router resolves which specific instance of the supervisor to deliver the inquiry to — preferring an instance that is already in the same conversation chain (and thus already waiting on the inquiring agent's response), or spawning a new instance if needed.

---

## Transport

### WebSocket Endpoint

```
ws://<host>/ws/<runId>/<agentName>
```

Each agent process opens exactly one WebSocket connection per agent type. Multiple instances share this single connection; multiplexing is done via `instance_id`.

### Framing

Each WebSocket message carries exactly one package serialised as a UTF-8 JSON string. Binary frames are not used.

### Authentication Handshake

Every new connection must complete authentication before any other packages are exchanged. The sequence is:

```
Agent Host Router                       Host Router
  |                                       |
  |-- connection.auth(api_key) ---------->|
  |                                       |-- validate key
  |<-- connection.auth_ack() -------------|  (success)
  |                                       |
  |-- connection.register(name, ...) ---->|
  |                                       |
  |  ... normal operation ...             |
```

If authentication fails:

```
Agent Host Router                       Host Router
  |                                       |
  |-- connection.auth(api_key) ---------->|
  |<-- connection.auth_error(message) ----|
  |                                       |-- close connection
```

`connection.auth_error` is always followed by connection closure on the Host Router side. The agent should not retry the same key.

### Heartbeat

Every 5 seconds the Agent Host Router sends a `connection.heartbeat` carrying a snapshot of all live instances and their current states. The Host Router uses successive heartbeats to detect:

- A new `instance_id` appearing → instance came alive
- A state change on an existing `instance_id` → state transition
- An `instance_id` disappearing → instance is gone

The heartbeat is the only mechanism for the host to learn about instance lifecycle changes other than `signal.instance_spawned`. Agents must maintain accurate state in the heartbeat map.

### Reconnection

If the WebSocket connection drops, the agent process is responsible for reconnecting and re-authenticating. The Host Router does not buffer packages across connection gaps. In-flight requests (pending `talk_to` or `inquiry` waits) that are unresolved at reconnect time will be failed by the Host Router.

---

## Package Hierarchy

```
Package
├── AgentPackage                  instance_id (required)
│   ├── OutputPackage             + turn_id, ts
│   │   ├── MessagePackage             agent.output.message
│   │   ├── ActivityPackage            agent.output.activity
│   │   ├── LogPackage                 agent.output.log
│   │   ├── UsagePackage               agent.output.usage
│   │   ├── FilesPackage               agent.output.files
│   │   └── PromptReceivedPackage      agent.output.prompt_received
│   ├── EventPackage
│   │   ├── UserInputPackage           agent.event.user_input
│   │   ├── TalkToRequestPackage       agent.event.talk_to.request
│   │   ├── TalkToResponsePackage      agent.event.talk_to.response
│   │   ├── RequestAlivePackage        agent.event.request.alive
│   │   ├── RequestFailedPackage       agent.event.request.failed
│   │   ├── InquiryRequestPackage      agent.event.inquiry.request
│   │   ├── InquiryResponsePackage     agent.event.inquiry.response
│   │   ├── InquiryAlivePackage        agent.event.inquiry.alive
│   │   └── InquiryFailedPackage       agent.event.inquiry.failed
│   └── SignalPackage
│       ├── DrainPackage               agent.signal.drain
│       ├── TerminatePackage           agent.signal.terminate
│       ├── InterruptPackage           agent.signal.interrupt
│       ├── StateQueryPackage          agent.signal.state_query
│       ├── StateReportPackage         agent.signal.state_report
│       └── InstanceSpawnedPackage     agent.signal.instance_spawned
└── ConnectionPackage              (no instance_id)
    ├── AuthPackage                    connection.auth
    ├── AuthAckPackage                 connection.auth_ack
    ├── AuthErrorPackage               connection.auth_error
    ├── RegisterPackage                connection.register
    ├── HeartbeatPackage               connection.heartbeat
    └── SpawnInstancePackage           connection.spawn_instance
```

### OutputPackage

Observable side-effects produced by a running instance. These are persisted to the database, displayed in the UI, and grouped by `turn_id`.

`turn_id` is a short string that groups output packages into a meaningful topic. When an agent is interrupted mid-turn (e.g. an inquiry arrives while it is generating), a new sub-turn begins with a different `turn_id`. This lets the UI distinguish output that belongs to the original topic from output that belongs to the interrupt. `turn_id` is meaningful only on output — protocol signals and lifecycle commands have no concept of a turn.

`ts` is a Unix epoch millisecond timestamp generated by the SDK at emission time, used to preserve ordering relative to generation rather than receipt.

### EventPackage

Conversational protocol signals that drive the state machine of an instance. Most event packages carry no `turn_id`. Response packages (`TalkToResponsePackage`, `InquiryResponsePackage`) include `turn_id` so the Host Router can associate the response with the conversation turn that produced it.

### SignalPackage

Lifecycle control signals directed at a specific instance. Like `EventPackage`, they carry no `turn_id`. They are always instance-scoped: if the Host Router wants to drain an entire agent process, it sends one `agent.signal.drain` per instance.

### ConnectionPackage

Physical connection management packets. These have no `instance_id` — they operate at the WebSocket connection level, before any instance exists or is known.

---

## Package Reference

### Common Fields

All `AgentPackage` types include:

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `string` | yes | Hierarchically scoped package type. Class constant; never a constructor parameter. |
| `instance_id` | `string` | yes | The instance this package addresses. Sole routing key. |

All `OutputPackage` types additionally include:

| Field | Type | Required | Description |
|---|---|---|---|
| `turn_id` | `string \| null` | no | Groups output packages by conversational topic. Assigned by the Agent Instance Router. |
| `ts` | `int \| null` | no | Unix epoch milliseconds at emission time. Used for ordering. |

`ConnectionPackage` types carry only `type`.

---

### Output Packets (agent → Host Router)

#### MessagePackage — `agent.output.message`

A chat message emitted by the agent. Streaming chunks share the same `id`; each chunk with `is_delta=True` is appended to the stored content, while `is_delta=False` (default) replaces it.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `content` | `string` | yes | — | Text content of the message. |
| `role` | `MessageRole` | no | `"assistant"` | Message role. One of `"assistant"`, `"user"`, `"tool"`. |
| `id` | `string` | no | auto-generated UUID7 hex | Stable identifier for this message. Streaming chunks must share the same `id`. |
| `is_delta` | `bool` | no | `False` | If `True`, `content` is *appended* to the existing message with the same `id`. If `False`, `content` *replaces* the stored value (or creates a new row). |
| `model` | `string \| null` | no | `null` | The model that produced this message. |
| `input_tokens` | `int \| null` | no | `null` | Prompt tokens consumed (if available at message time). |
| `output_tokens` | `int \| null` | no | `null` | Completion tokens produced (if available at message time). |
| `sender_name` | `string \| null` | no | `null` | Display name of the agent that produced this message. Used when a sub-agent's output is surfaced. |

---

#### ActivityPackage — `agent.output.activity`

A named activity record with support for delta streaming. Used to show tool invocations, thinking tokens, and other agent actions in the UI.

When `is_delta=true`, non-null fields are *appended* to the existing activity row with the same `id`. When `is_delta=false` (default), non-null fields *replace* the stored values (or create a new row). `data` and `content` are updated independently — if either is `null`, that DB column is left untouched.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | `string \| null` | no | auto UUID7 | Activity ID. Auto-generated by SDK when absent. Used for delta append/replace targeting. |
| `event_type` | `string` | yes | — | Name of the activity, e.g. `"tool_call"`, `"thinking"`. |
| `data` | `dict \| null` | no | `null` | Structured payload for the activity. Schema is `event_type`-specific. `null` = don't touch DB column. |
| `content` | `string \| null` | no | `null` | Text content (e.g. thinking tokens). `null` = don't touch DB column. |
| `is_delta` | `bool` | no | `false` | When `true`, non-null `data`/`content` are appended to the existing row. |

---

#### LogPackage — `agent.output.log`

A structured log entry from the agent process. Surfaced in the developer console, not in the user-facing chat.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `level` | `LogLevel` | yes | — | Severity. One of `"debug"`, `"info"`, `"warn"`, `"error"`. |
| `message` | `string` | yes | — | Human-readable log line. |

---

#### UsagePackage — `agent.output.usage`

LLM token and cost accounting for a completed inference call. Used for billing and observability dashboards.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model` | `string` | yes | — | Model identifier. |
| `input_tokens` | `int` | yes | — | Prompt tokens consumed. |
| `output_tokens` | `int` | yes | — | Completion tokens produced. |
| `cache_read_tokens` | `int \| null` | no | `null` | Tokens served from the prompt cache (reads). |
| `cache_write_tokens` | `int \| null` | no | `null` | Tokens written to the prompt cache. |
| `cost_usd` | `float \| null` | no | `null` | Computed cost in US dollars, if available. |

---

#### FilesPackage — `agent.output.files`

A record of file system operations performed during a turn. Allows the UI to surface diffs and file change summaries.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `files` | `list[dict]` | yes | — | List of file operation records. Schema of each record is implementation-specific. |

---

#### PromptReceivedPackage — `agent.output.prompt_received`

Emitted immediately before the agent begins processing a new prompt. Signals the UI to show a processing/typing indicator.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `content` | `string` | yes | — | The prompt text that was received. |
| `sender_name` | `string \| null` | no | `null` | Set when the prompt came from another agent (e.g. a `talk_to` request); `null` for user messages. |

---

### Event Packets (bidirectional)

#### UserInputPackage — `agent.event.user_input` (Host Router → instance)

A message typed by the user and delivered to a specific instance. The user has an explicit instance open in the UI; this package is addressed directly to that instance's `instance_id`.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `content` | `string` | yes | — | The user's message text. |

---

#### TalkToRequestPackage — `agent.event.talk_to.request`

An agent requests a conversation with another agent type. The same package is relayed via the Host Router to the target instance — the Host Router resolves the target and upgrades `instance_id` from the caller's instance to the resolved target instance when forwarding.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `target_agent` | `string` | yes | — | Name of the agent type to call. Preserved when forwarded; the Host Router upgrades `instance_id` to the resolved target. |
| `text` | `string` | yes | — | The message to deliver to the target agent. |
| `request_id` | `string` | yes | — | Correlation ID. Used to match the eventual `agent.event.talk_to.response`. |
| `caller_agent` | `string` | no | `null` | Name of the calling agent. Injected by the Host Router when forwarding to the target instance so the target can identify the sender. |
| `continue_conversation` | `bool` | no | `False` | Caller's intent: `True` means "keep using the same instance I talked to before"; `False` means "start fresh". The Host Router respects this as a routing hint but is authoritative on actual instance selection. |

---

#### TalkToResponsePackage — `agent.event.talk_to.response` (instance → Host Router → caller)

The target instance's reply to a `talk_to.request`. The Host Router relays this back to the original caller instance. The `turn_id` identifies the target instance's turn, allowing the Host Router to assemble the transcript of what the target produced during that turn.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `request_id` | `string` | yes | — | Must match the `request_id` from the originating request. |
| `turn_id` | `string \| null` | no | `null` | The target instance's turn ID. Injected by the Agent Instance Router. Allows the Host Router to assemble the transcript from that turn. |
| `response` | `string \| null` | no | `null` | The response text. `null` if the call failed. |
| `error` | `string \| null` | no | `null` | Error description if the target agent could not produce a response. |

---

#### RequestAlivePackage — `agent.event.request.alive` (Host Router → instance)

A keepalive sent to the **caller** instance while it is blocked waiting for a `talk_to.response`. The caller uses this to confirm the Host Router is still processing the request.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `request_id` | `string` | yes | — | The `request_id` of the pending request this keepalive refers to. |

---

#### RequestFailedPackage — `agent.event.request.failed` (Host Router → instance)

Sent to the caller instance when the target agent has disconnected, cannot respond, or the call was rejected (e.g. due to a cyclic chain). The caller must unblock immediately and treat the call as failed.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `request_id` | `string` | yes | — | The `request_id` of the failed request. |
| `reason` | `string` | yes | — | Human-readable failure description. |

---

#### InquiryRequestPackage — `agent.event.inquiry.request` (instance → Host Router)

The agent blocks its current turn and asks a question. The Host Router routes this to the agent's supervisor (see [Inquiry Bubbling](#3-agent--supervisor-chain-inquiry-bubbling)). The instance will not process further input until an `inquiry.response` or `inquiry.failed` arrives with the matching `inquiry_id`.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `inquiry_id` | `string` | yes | — | Unique ID for this inquiry. Correlation key for all subsequent inquiry packets. |
| `content_markdown` | `string` | yes | — | The question, in Markdown. Rendered in the UI if surfaced to the user. |
| `priority` | `InquiryPriority` | no | `"normal"` | Display priority. One of `"normal"`, `"high"`, `"urgent"`. |
| `suggestions` | `list[string]` | yes | `[]` | Pre-filled answer suggestions. Must have at least 2. |
| `file_paths` | `list[string] \| null` | no | `null` | Paths to files the agent considers relevant to the question. |

---

#### InquiryResponsePackage — `agent.event.inquiry.response` (supervisor/Host Router → instance)

The answer to an open inquiry. Sent by the supervisor agent instance (via `tag_outbound`, which injects `turn_id`) or by the Host Router when a human answers directly. The waiting instance unblocks and resumes.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `inquiry_id` | `string` | yes | — | Must match the `inquiry_id` from the original request. |
| `turn_id` | `string \| null` | no | `null` | The supervisor instance's turn ID. Injected by the Agent Instance Router when the response originates from a supervisor agent. `null` when the response comes directly from a human user. |
| `response_text` | `string \| null` | no | `null` | Free-text answer. |
| `response_suggestion_index` | `int \| null` | no | `null` | Index into the `suggestions` list if a suggestion was selected; `null` otherwise. |

---

#### InquiryAlivePackage — `agent.event.inquiry.alive` (Host Router → instance)

A keepalive sent to the waiting instance while the inquiry is open and unanswered.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `inquiry_id` | `string` | yes | — | The `inquiry_id` of the pending inquiry. |

---

#### InquiryFailedPackage — `agent.event.inquiry.failed` (Host Router → instance)

Sent when the inquiry is cancelled or expires before being answered. The waiting instance must unblock and treat the inquiry as failed.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `inquiry_id` | `string` | yes | — | The `inquiry_id` of the failed inquiry. |
| `reason` | `string` | yes | — | Human-readable cancellation or expiry reason. |

---

### Signal Packets

Signal packets are lifecycle control signals sent to a specific instance. They carry no `turn_id`. They are always instance-scoped.

#### DrainPackage — `agent.signal.drain` (Host Router → instance)

Graceful stop: the instance should finish its current turn and then terminate. No new input will be delivered after this point.

*(No additional fields beyond `instance_id`.)*

---

#### TerminatePackage — `agent.signal.terminate` (Host Router → instance)

Hard stop: the instance task is cancelled immediately, without waiting for the current turn to complete.

*(No additional fields beyond `instance_id`.)*

---

#### InterruptPackage — `agent.signal.interrupt` (Host Router → instance)

Interrupts the current generation: the running agent function is cancelled, the instance transitions back to `idle`, and the instance remains alive and ready for new input. Unlike `drain` and `terminate`, the instance is not destroyed.

Used to implement a "stop generating" action in the UI.

*(No additional fields beyond `instance_id`.)*

---

#### StateQueryPackage — `agent.signal.state_query` (Host Router → instance)

Request the instance to report its current state. Correlated by `instance_id` — no separate request ID is needed because only one outstanding query per instance is expected.

*(No additional fields beyond `instance_id`.)*

---

#### StateReportPackage — `agent.signal.state_report` (instance → Host Router)

Reports the current state of an instance, either in response to a `state_query` or proactively (e.g. at startup).

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `state` | `AgentState` | yes | — | Current state of this instance. |
| `instances` | `dict[str, AgentState] \| null` | no | `null` | Optional full snapshot of all instances this agent process is hosting. |

---

#### InstanceSpawnedPackage — `agent.signal.instance_spawned` (instance → Host Router)

Acknowledgement that the `instance_id` named in a `connection.spawn_instance` has been successfully created and is ready to receive input.

*(No additional fields beyond `instance_id`.)*

---

### Connection Packets

Connection packets have no `instance_id`. They operate at the WebSocket level, between the Agent Host Router and the Host Router.

#### AuthPackage — `connection.auth` (Agent Host Router → Host Router)

The first message sent on every new WebSocket connection.

| Field | Type | Required | Description |
|---|---|---|---|
| `api_key` | `string` | yes | API key for the agent process. |

---

#### AuthAckPackage — `connection.auth_ack` (Host Router → Agent Host Router)

Authentication accepted. The agent may now send `connection.register`.

*(No additional fields.)*

---

#### AuthErrorPackage — `connection.auth_error` (Host Router → Agent Host Router)

Authentication rejected. The connection will close immediately after this message.

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | `string` | yes | Human-readable rejection reason. |

---

#### RegisterPackage — `connection.register` (Agent Host Router → Host Router)

Sent after a successful `connection.auth_ack`. Declares the agent's identity to the Host Router.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | `string` | yes | — | Agent type name. Must match the agent name in the WebSocket URL path. |
| `role` | `string \| null` | no | `null` | Optional role descriptor, e.g. `"primary"`, `"sub-agent"`. |
| `capabilities` | `list[string] \| null` | no | `null` | Optional list of capability tags the Host Router can use for routing decisions. |

---

#### HeartbeatPackage — `connection.heartbeat` (Agent Host Router → Host Router)

Periodic liveness signal sent every 5 seconds. Carries a complete snapshot of all currently live instances and their states.

| Field | Type | Required | Description |
|---|---|---|---|
| `instances` | `dict[str, AgentState]` | yes | Map of `instance_id → state` for every live instance. |

---

#### SpawnInstancePackage — `connection.spawn_instance` (Host Router → Agent Host Router)

Requests creation of a new instance. This is a `ConnectionPackage` (no `instance_id`) because the instance does not yet exist at delivery time.

The Host Router sends only the `instance_id` to assign. After the Agent Host Router confirms with `agent.signal.instance_spawned`, the Host Router delivers any pending work (e.g. a `talk_to.request`) as a separate package.

| Field | Type | Required | Description |
|---|---|---|---|
| `instance_id` | `string` | yes | The `instance_id` the agent must assign to the new instance. |

---

### Fallback

#### UnknownPackage

Used when a `type` value is not recognised by the receiving SDK version. Rather than raising an error, unrecognised packages deserialise to `UnknownPackage`. This allows older SDK versions to survive newer protocol extensions gracefully.

| Field | Type | Description |
|---|---|---|
| `raw` | `dict` | The original deserialised JSON, preserved verbatim. |

`UnknownPackage` has no `TYPE` constant registered in the dispatch table.

---

## Strong Types

```python
LogLevel         = Literal["debug", "info", "warn", "error"]
AgentState       = Literal["idle", "generating", "waiting_for_agent", "waiting_for_inquiry"]
MessageRole      = Literal["assistant", "user", "tool"]
InquiryPriority  = Literal["normal", "high", "urgent"]
```

| Type | Used in |
|---|---|
| `LogLevel` | `LogPackage.level` |
| `AgentState` | `HeartbeatPackage.instances`, `StateReportPackage.state`, `StateReportPackage.instances` |
| `MessageRole` | `MessagePackage.role` |
| `InquiryPriority` | `InquiryRequestPackage.priority` |

### Package Type Registry

All valid `type` strings:

| Type string | Package |
|---|---|
| `agent.output.message` | MessagePackage |
| `agent.output.activity` | ActivityPackage |
| `agent.output.log` | LogPackage |
| `agent.output.usage` | UsagePackage |
| `agent.output.files` | FilesPackage |
| `agent.output.prompt_received` | PromptReceivedPackage |
| `agent.event.user_input` | UserInputPackage |
| `agent.event.talk_to.request` | TalkToRequestPackage |
| `agent.event.talk_to.response` | TalkToResponsePackage |
| `agent.event.request.alive` | RequestAlivePackage |
| `agent.event.request.failed` | RequestFailedPackage |
| `agent.event.inquiry.request` | InquiryRequestPackage |
| `agent.event.inquiry.response` | InquiryResponsePackage |
| `agent.event.inquiry.alive` | InquiryAlivePackage |
| `agent.event.inquiry.failed` | InquiryFailedPackage |
| `agent.signal.drain` | DrainPackage |
| `agent.signal.terminate` | TerminatePackage |
| `agent.signal.interrupt` | InterruptPackage |
| `agent.signal.state_query` | StateQueryPackage |
| `agent.signal.state_report` | StateReportPackage |
| `agent.signal.instance_spawned` | InstanceSpawnedPackage |
| `connection.auth` | AuthPackage |
| `connection.auth_ack` | AuthAckPackage |
| `connection.auth_error` | AuthErrorPackage |
| `connection.register` | RegisterPackage |
| `connection.heartbeat` | HeartbeatPackage |
| `connection.spawn_instance` | SpawnInstancePackage |

---

## Serialisation

- All packages serialise to JSON via `to_dict()` / `to_json()`.
- All packages deserialise from JSON via `Package.from_dict(dict)` / `Package.from_json(str)`.
- `type` is a class-level constant, not an instance field; it is injected by `to_dict()` and never appears as a constructor parameter.
- `None` fields are omitted from the wire dict. Falsy non-`None` values (`False`, `0`, `[]`, `{}`) are always included.
- Unknown `type` values deserialise to `UnknownPackage` rather than raising. This ensures older SDK versions survive newer protocol extensions gracefully.

---

## Routing Stack

A package travels through three routing layers between an agent instance and the user:

```
[Agent Instance]
      │
      ▼
Agent Instance Router   Per-instance
                        Routes inbound packages to the agent based on
                        instance state. Tags outbound output packages with
                        turn_id. Manages a turn ID stack for interrupt/resume.
      │
      ▼
Agent Host Router       Per agent-type
                        Owns the single WebSocket connection for its agent
                        type. Dispatches inbound packages to the correct
                        Agent Instance Router by instance_id. Handles
                        connection-level packages (auth, heartbeat, spawn)
                        directly.
      │
      │  JSON over WebSocket
      │  ws://<host>/ws/<runId>/<agentName>
      ▼
Host Router             Central authority
                        Manages all agent connections. Routes talk_to
                        requests between agent types. Tracks conversation
                        chains. Enforces supervisor hierarchies for inquiry
                        bubbling. Detects and rejects cyclic talk_to calls.
                        Persists output and surfaces inquiries to the user.
```

---

## Conversation Chains

A conversation chain is a directed graph of instance links created by `talk_to` calls. The Host Router is the sole owner of chain state — agents have no visibility into chains.

### Chain Formation

When instance A sends `talk_to.request(target_agent="B")`:

1. The Host Router creates a link: `A → B_instance`.
2. If B then sends `talk_to.request(target_agent="C")`, the chain extends: `A → B_instance → C_instance`.
3. Links are keyed by `(caller_instance_id, target_agent_type)`.

### Chain Routing with continue_conversation

The `continue_conversation` field determines how the Host Router uses existing chains:

| `continue_conversation` | Existing chain link | Host Router action |
|---|---|---|
| `True` | `A → B_instance` alive | Route to `B_instance` directly |
| `True` | `A → B_instance` dead | Spawn new B instance, update link |
| `False` | `A → B_instance` alive | Drain `B_instance`, spawn new, update link |
| `False` | No link | Spawn new B instance, create link |
| Either | No link | Spawn new B instance, create link |

### Chain Teardown

Links are removed when:
- The target instance terminates (drain, terminate, or crash).
- The caller instance terminates (cascading cleanup).
- A new `talk_to.request` with `continue_conversation=False` replaces the link.
- The Host Router detects an instance has disappeared from a heartbeat (connection lost or process crash). The Host Router cleans up all chain links involving that instance.

### Cycle Detection

Before routing a `talk_to.request`, the Host Router walks the caller's chain to check whether the `target_agent` type already appears in the path. If it does, the request is rejected immediately:

```
Example: A(lead) → B(coder) → C(reviewer)

C sends talk_to.request(target_agent="lead"):
  Host Router detects: lead already in chain (A is lead)
  → agent.event.request.failed(instance_id=C, request_id=R,
       reason="Cyclic talk_to rejected: lead → coder → reviewer → lead")
  C unblocks with error.
```

Cycle detection operates on **agent type names**, not instance IDs. Even if the target would be a different instance of the same agent type, the call is rejected. This prevents unbounded chain growth and ensures every chain is a simple path with no repeated agent types.

---

## Agent Instance State Machine

Each instance is always in exactly one of the following states:

```
AgentState = "idle" | "generating" | "waiting_for_agent" | "waiting_for_inquiry"
```

### States

| State | Description |
|---|---|
| `idle` | No active turn. Instance is ready to accept new input. |
| `generating` | Agent function is running. A turn is active. |
| `waiting_for_agent` | Agent called `talk_to`; blocked waiting for `talk_to.response`. |
| `waiting_for_inquiry` | Agent called `inquire`; blocked waiting for `inquiry.response`. |

### Transitions

```
                 ┌──────────────────────────────────────────────┐
                 │          user_input / talk_to.request         │
                 │                                               ▼
            ┌────┴─────┐                         ┌──────────────────────┐
            │   idle   │────────────────────────▶│     generating       │
            └──────────┘                         └──────────────────────┘
                 ▲                                  │          │
                 │   turn complete                  │          │
                 └──────────────────────────────────┘          │
                                                               │
                                               inquire()       │ talk_to()
                                                  │            │
                                                  ▼            ▼
                                     ┌─────────────────┐ ┌────────────────────┐
                                     │ waiting_for_    │ │  waiting_for_agent │
                                     │ inquiry         │ │                    │
                                     └─────────────────┘ └────────────────────┘
                                           │       │           │       │
                                           │       │           │       │
                                    response│  interrupt  response│  interrupt
                                    /failed │  (inquiry)  /failed │  (inquiry)
                                           │       │           │       │
                                           ▼       ▼           ▼       ▼
                                         ┌──────────────────────────────┐
                                         │     generating (resume)      │
                                         └──────────────────────────────┘
```

- `idle → generating`: triggered by any incoming input (user message, talk_to request, or forwarded inquiry arriving while idle).
- `generating → idle`: turn completed normally.
- `generating → waiting_for_agent`: agent called `talk_to(...)`.
- `generating → waiting_for_inquiry`: agent called `inquire(...)`.
- `waiting_for_agent → generating`: `talk_to.response` or `request.failed` received; agent resumes.
- `waiting_for_inquiry → generating`: `inquiry.response` or `inquiry.failed` received; agent resumes.

### Inquiry Interrupts During a Wait

While an instance is in `waiting_for_agent` or `waiting_for_inquiry`, a forwarded `inquiry.request` from a sub-agent may arrive. This triggers an interrupt:

1. The pending wait (request ID and context) is pushed onto a stack.
2. A new `turn_id` is pushed for the sub-turn.
3. State transitions to `generating` — the agent processes the inquiry.
4. After the sub-turn completes, the `turn_id` is popped (restoring the original).
5. The pending wait is popped and the instance resumes waiting.

This allows nested interrupts: an agent waiting on agent B can be interrupted by an inquiry from agent B's sub-agent, handle it, and then resume waiting for B's response. The turn ID stack ensures output from the interrupt sub-turn is visually grouped separately from the main turn.

### Inbound Routing Rules (Agent Instance Router)

The Agent Instance Router decides where to deliver each inbound package based on the instance's current state:

| Current state | Inbound package | Action |
|---|---|---|
| `idle` | `agent.event.user_input` | Deliver to agent as new input |
| `idle` | `agent.event.talk_to.request` | Deliver to agent as new input |
| `idle` | `agent.event.inquiry.request` (forwarded) | Deliver to agent as new input |
| `generating` | Any | Buffer; deliver after current turn completes |
| `waiting_for_agent` | `agent.event.talk_to.response` (matching `request_id`) | Deliver to agent; unblock `talk_to` |
| `waiting_for_agent` | `agent.event.request.alive` (matching `request_id`) | Reset keepalive timer |
| `waiting_for_agent` | `agent.event.request.failed` (matching `request_id`) | Deliver to agent; unblock with error |
| `waiting_for_agent` | `agent.event.inquiry.request` (forwarded) | Interrupt: push wait, deliver inquiry |
| `waiting_for_inquiry` | `agent.event.inquiry.response` (matching `inquiry_id`) | Deliver to agent; unblock `inquire` |
| `waiting_for_inquiry` | `agent.event.inquiry.alive` (matching `inquiry_id`) | Reset keepalive timer |
| `waiting_for_inquiry` | `agent.event.inquiry.failed` (matching `inquiry_id`) | Deliver to agent; unblock with error |
| `waiting_for_inquiry` | `agent.event.inquiry.request` (forwarded) | Interrupt: push wait, deliver inquiry |
| Any | `agent.signal.drain` | Finish current turn then terminate |
| Any | `agent.signal.terminate` | Cancel immediately |
| Any | `agent.signal.interrupt` | Cancel current generation, return to idle (instance stays alive) |
| Any | `agent.signal.state_query` | Reply with `agent.signal.state_report` |

Packages that do not match any routing rule for the current state are dropped with a warning log.

### Turn ID Stack

The Agent Instance Router manages a turn ID stack to support nested sub-turns triggered by inquiry interrupts:

- `push_turn()` → generates a new `turn_id`, pushes it, returns it.
- `pop_turn()` → removes the top entry; restores the previous `turn_id`.
- `current_turn_id` → the top of the stack; used to tag outbound `OutputPackage` instances.

When a generating instance is interrupted by an inquiry from a sub-agent, a new turn ID is pushed for the sub-turn, the interrupt is handled, then the turn ID is popped to continue the original turn.

---

## Communication Flows

### 1. User → Instance (user message)

The user has a specific instance open in the UI. The message is addressed directly to that instance.

```
User types in UI
  → Host Router resolves the instance's agent connection
  → Host Router sends agent.event.user_input(instance_id=I, content=...)
    over the agent's WebSocket connection
  → Agent Host Router dispatches to instance I by instance_id
  → Agent Instance Router delivers to agent when idle
  → Agent processes input, emits agent.output.*(instance_id=I, turn_id=T, ...)
  → Agent Instance Router tags with turn_id
  → Agent Host Router sends over WebSocket
  → Host Router receives output, persists it, surfaces in UI
```

### 2. Agent → Agent (talk_to)

An agent may call another agent by name. The Host Router resolves which instance to use, enforces cycle detection, and manages the conversation chain.

```
ctx.talk_to("coder", text, continue_conversation=True|False)
  → agent.event.talk_to.request(instance_id=A, target_agent="coder",
                                 request_id=R, continue_conversation=...)
  → Agent Instance Router tags outbound
  → Agent Host Router sends over WebSocket
  → Host Router receives request from instance A

Host Router cycle check:
  Walk chain from A: lead → ...
  If "coder" already in chain → reject with request.failed
  Otherwise → proceed

Host Router chain routing:
  continue_conversation=True  → route to existing chain instance if alive
  continue_conversation=False → drain existing chain instance (if any),
                                 spawn fresh, route to new instance
  no chain instance exists    → spawn new instance, route to it

If spawning:
  → connection.spawn_instance(instance_id=NEW) to coder's Agent Host Router
  ← agent.signal.instance_spawned(instance_id=NEW)
  → Host Router creates chain link: A → NEW

Host Router forwards to target (same package, instance_id upgraded):
  → agent.event.talk_to.request(instance_id=NEW, target_agent="coder",
                                 request_id=R, text=...)

While caller A waits, Host Router sends periodically:
  → agent.event.request.alive(instance_id=A, request_id=R)

Target responds:
  ← agent.event.talk_to.response(instance_id=NEW, request_id=R, response=...)

Host Router relays to caller:
  → agent.event.talk_to.response(instance_id=A, request_id=R, response=...)
```

If the target agent disconnects before responding:
```
  → agent.event.request.failed(instance_id=A, request_id=R, reason=...)
    Caller unblocks immediately with an error.
```

### 3. Inquiry Bubbling (supervision hierarchy)

When an agent sends an inquiry, it does **not** go directly to the user. The Host Router uses the pre-configured supervision hierarchy to route it to the agent's supervisor. The inquiry only surfaces to the user if no supervisor in the hierarchy handles it.

```
Example supervision hierarchy:
  lead (no supervisor — escalates to user)
  ├── coder (supervisor: lead)
  └── reviewer (supervisor: lead)

Agent "coder" sends:
  ← agent.event.inquiry.request(instance_id=C, inquiry_id=Q,
                                 content_markdown=..., ...)

Host Router looks up supervisor of "coder" → "lead"

Host Router resolves which instance of "lead" to deliver to:
  If a "lead" instance is in the same conversation chain
    (e.g. lead called talk_to("coder") and is waiting for C):
    → Forward inquiry.request to that lead instance
    → Lead is interrupted (see "Inquiry Interrupts During a Wait")

  If "lead" is connected but no instance is waiting on C:
    → Spawn a new "lead" instance for this inquiry
    → Deliver inquiry.request to the new instance

Supervisor "lead" receives the inquiry and decides:
  Option A — Reply directly:
    → agent.event.inquiry.response(inquiry_id=Q, response_text=...)
    → Host Router relays response back to agent C
    → C unblocks and continues

  Option B — Escalate (bubble up):
    → "lead" sends its own inquiry.request
    → Host Router looks up supervisor of "lead" → none
    → No supervisor: inquiry surfaces to the user in the UI

User responds:
  → Host Router sends inquiry.response back down to the originating agent

While the inquiry is open, Host Router sends periodically:
  → agent.event.inquiry.alive(instance_id=C, inquiry_id=Q)
```

If the inquiry expires or is cancelled:
```
  → agent.event.inquiry.failed(instance_id=C, inquiry_id=Q, reason=...)
    Instance unblocks with failure.
```

### 4. Inquiry Interrupt (inquiry arrives during a wait)

A delegate agent that is answering a `talk_to` request from instance A may need to ask a question. The Host Router looks up the delegate's supervisor in the hierarchy, finds that A's agent type is the supervisor, and forwards the inquiry to A — interrupting A's wait.

```
Delegate agent sends:
  ← agent.event.inquiry.request(instance_id=SUB, inquiry_id=Q, ...)

Host Router looks up supervisor of SUB's agent type → A's agent type
Host Router finds A is in the same chain and waiting → delivers to A
Host Router forwards to A's Agent Host Router:
  → agent.event.inquiry.request forwarded to instance A

Agent Instance Router on A (state: waiting_for_agent):
  → Push pending wait onto stack
  → Push new turn_id T2 for interrupt sub-turn
  → State transitions to generating
  → Agent processes the inquiry (may reply or escalate)

After sub-turn completes:
  → Pop turn_id (restore T1)
  → Pop pending wait (resume waiting for talk_to.response from SUB)
  → State returns to waiting_for_agent
```

### 5. Instance Lifecycle

**Spawning** (new conversation opened in UI, or triggered by talk_to):
```
Host Router → connection.spawn_instance(instance_id=NEW) → Agent Host Router
  Agent Host Router creates instance, starts Agent Instance Router
← agent.signal.instance_spawned(instance_id=NEW) → Host Router
  Host Router may now deliver pending work to instance NEW
```

**Graceful shutdown** (finish current turn, then stop):
```
Host Router → agent.signal.drain(instance_id=I) → Agent Host Router → Agent Instance Router
  Agent Instance Router finishes the current turn, then terminates.
  Host Router removes any chain links involving instance I.
```

**Hard stop** (cancel immediately):
```
Host Router → agent.signal.terminate(instance_id=I) → Agent Host Router → Agent Instance Router
  Agent Instance Router cancels the instance task without waiting.
  Host Router removes any chain links involving instance I.
```

**State polling**:
```
Host Router → agent.signal.state_query(instance_id=I)
← agent.signal.state_report(instance_id=I, state="generating")
  Correlated by instance_id — no separate request_id needed.
```

### 6. Heartbeat (connection liveness)

Every 5 seconds the Agent Host Router sends a heartbeat carrying a snapshot of all live instances and their states:

```
← connection.heartbeat(instances={"abc": "idle", "def": "generating"})
```

The Host Router diffs successive heartbeats to detect:
- New `instance_id` appearing → instance came alive
- State change on existing `instance_id` → state transition
- `instance_id` disappearing → instance gone; Host Router cleans up chain links

---

## Design Decisions

### instance_id as universal routing key

There is no broadcast addressing, no "first available" dispatch, and no host-level identity. Every agent-scoped package carries exactly one `instance_id`. The Host Router routes based solely on this field. This means `agent.event.user_input`, despite conceptually being "from the user", must carry the `instance_id` of the specific instance the user has open in the UI.

### Three-layer routing architecture

The routing stack separates concerns into three layers: the Host Router (central authority, cross-agent routing, chain management), the Agent Host Router (per-type connection multiplexing), and the Agent Instance Router (per-instance state-aware delivery). This separation means the Host Router never needs to understand instance-level state, and agent-side routers never need to understand cross-agent topology.

### Hierarchically scoped type strings

Package types use dot-separated hierarchical names (`agent.output.message`, `agent.event.inquiry.request`). This eliminates the need for a separate `packet_type` discriminator — the category is embedded in the type string. It also makes it trivial to match on package categories (e.g. all inquiry-related packages match `agent.event.inquiry.*`).

### turn_id belongs to output and response packages

`turn_id` is a grouping primitive for observable content and response correlation. All output packages carry `turn_id` to group content by conversation turn. Among event packages, response packages (`TalkToResponsePackage` and `InquiryResponsePackage`) carry `turn_id` — the Host Router needs it to associate the response with the responding instance's turn. All other event and signal packages have no concept of a turn.

### continue_conversation is the agent's intent, not a routing command

The `continue_conversation` field on `talk_to.request` expresses what the calling agent wants — "reuse my prior conversation" or "start fresh". The Host Router is authoritative on routing policy. It may honour or override this intent (e.g. if the target instance is no longer alive). Agents must not assume that `continue_conversation=True` guarantees they will reach the same instance.

### Conversation chains are Host Router-private state

Agents have no visibility into chains. There is no `conversation_id` or `chain_id` on the wire. The Host Router tracks all chain links internally and uses them for `talk_to` routing and cycle detection. This keeps agents simple — they only know about their own `talk_to` calls.

### Cycle detection on agent type, not instance

Cycles are detected by agent type name, not by instance ID. If agent types `A → B → C` form a chain and C tries to call A, it is rejected even if A would be a fresh instance. This prevents unbounded chain growth and ensures every chain is a simple directed path with no repeated agent types.

### Supervision hierarchy is independent of conversation chains

The supervision hierarchy is pre-configured at workspace level, not derived from runtime `talk_to` calls. An agent's supervisor is always the same agent type regardless of which chain the instance is in. This separation means chains can be freely formed and torn down without affecting inquiry routing, and supervision relationships are stable and predictable.

### Inquiry bubbling through supervision hierarchy

Inquiries are not routed directly to the user. The Host Router looks up the inquiring agent's supervisor from the pre-configured hierarchy and forwards the inquiry there. Each supervisor can answer directly or escalate further. The inquiry only reaches the user if no supervisor in the hierarchy handles it. When routing to a supervisor, the Host Router prefers an instance that is already in the same conversation chain (and thus already waiting), but will spawn a new instance if needed.

### StateQuery does not need a request_id

At most one `state_query` is expected per instance at a time. `instance_id` is a sufficient correlation key.

### DrainPackage and TerminatePackage are always instance-scoped

There is no "drain entire process" broadcast signal. If the Host Router wants to drain all instances on an agent process, it sends one `agent.signal.drain` per live instance. This keeps the protocol instance-scoped and avoids special-casing process-level vs. instance-level signals.

### SpawnInstancePackage lives under ConnectionPackage

`connection.spawn_instance` has no `instance_id` in the package hierarchy because the instance does not exist yet at delivery time. The Host Router sends only the `instance_id` to assign; any pending work (e.g. a forwarded `talk_to.request`) is delivered separately after the Agent Host Router confirms with `agent.signal.instance_spawned`.

### UnknownPackage for forward compatibility

Unrecognised `type` values on the wire deserialise to `UnknownPackage` rather than raising an exception. This ensures older SDK versions can coexist with newer protocol extensions without crashing.

---

## Remarks

The following are implementation notes and future refactoring considerations. They are not part of the protocol specification.

### Feed item abstraction

The current Python SDK wraps inbound packages in typed feed items (`InputItem`, `ResponseItem`, `InquiryInterruptItem`, `TerminationItem`) before delivering them to the agent worker. These are thin semantic wrappers over raw package dicts. A future refactoring should eliminate this indirection and relay packages directly to the agent, using the `type` string for dispatch instead of wrapper class identity.
