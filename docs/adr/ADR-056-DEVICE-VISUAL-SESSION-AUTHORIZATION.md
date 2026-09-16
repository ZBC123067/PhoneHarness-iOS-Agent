# ADR-056: Device Visual Session Authorization

Status: Accepted, implemented, and focused-device validated for the private
local-vision bridge on 2026-08-24.

## Context

The local Vision bridge is intentionally omitted from the public MCP tool list
and performs only a current-screen OCR observation. Before this decision, the
device accepted any identifier with the `visualsession.<32 lowercase hex>`
shape. The Mac-side temporary-session lifecycle limited normal callers, but a
well-formed fabricated identifier had no device-side authorization binding.

The bridge must not persist a screen image, OCR content, geometry, UI dump,
user input, owner identity, or replayable procedure. It must not become a
Planner, Risk, Executor, or public generic MCP capability.

## Research And Evaluation

1. Host-only identifier validation: rejected. It cannot authorize a direct or
   stale request reaching the device service.
2. Persist device session records: rejected. Recovery would create a replay
   surface and unnecessarily retain authorization state across a restart.
3. Server-issued, memory-only, short-lived, one-time capability: selected.
   OWASP session-management guidance supports server-generated identifiers,
   server-side expiry enforcement, and keeping session state separate from the
   identifier. Apple Security and Vision guidance remain compatible because
   this protocol adds no framework dependency and preserves the existing
   device-local OCR implementation.

## Decision

`create_visual_session` is an internal endpoint omitted from `tools/list`.
It accepts no caller-controlled fields and returns a safe grant:

- `session_id`
- `created_time`
- `expiration_time`
- `permission_scope` (`visual_observation`)
- `one_time_access` (`true`)
- `status` (`ACTIVE`)

The device holds an in-memory record with a separate private owner token. It
uses `SecRandomCopyBytes`, expires grants after 120 seconds, bounds concurrent
active grants to four, and atomically removes a record before OCR begins. A
consumed, expired, unknown, or malformed identifier receives the same generic
rejection. The owner token and visual contents never cross the bridge.

The host binds one in-memory `ScreenshotSessionFoundation` session to one
device grant. It claims analysis once, releases that local claim on completion
or failure, and destroys temporary material on cancellation/error. The
existing ordinary temporary-session API remains for pre-P2 host-only tests;
real bridge use must obtain a device-issued grant.

## Non-Goals

- No transport/client authentication; this endpoint remains an internal local
  service boundary and must not be externally exposed as a general capability.
- No persisted device sessions, screenshot persistence, raw OCR persistence,
  action execution, planner access, visual UI automation, or token replay.
- No RootHide, Bootstrap, package-source, or device-configuration change.

## Validation Contract

Static and unit tests cover the exact public grant schema, malformed/expired
grant rejection, one-host-session binding, concurrent local consumption,
generic MCP isolation, secure-random device registry use, no persistence calls,
and no owner token in the public return value. The focused device gate must
prove issue, one OCR observation, consumed-grant rejection, fabricated-ID
rejection, cleanup, and zero device actions. A real elapsed-expiry test remains
separate because it would require waiting through the 120-second TTL.

## Consequences

The device is now the authorization authority for the private OCR bridge,
while the host retains only temporary lifecycle coordination. The trade-off is
one additional internal read-only round trip per visual session. The boundary
is deliberately narrow and does not grant general visual or device-control
authority.

## Focused Device Evidence

On an iPhone 15 Pro running iOS 17.0 with RootHide + ElleKit, the production
bridge issued one device-owned grant, completed one local OCR observation, and
rejected both a consumed grant replay and a fabricated identifier. The host
session reached `DESTROYED` with zero active sessions. The result remained
`NEEDS_CONFIRMATION` / `UNTRUSTED_CONTENT`; no screen image, OCR text,
geometry, grant identifier, owner token, or action data was persisted or
reported. Aggregate-only measurements were 3,013,524 input pixels, 20 regions,
424 ms latency, and a 9,977,856-byte process-resident delta. The gate made zero
device actions.
