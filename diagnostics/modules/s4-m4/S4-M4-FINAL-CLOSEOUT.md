# S4-M4 Final Closeout

Status: `FROZEN_PROVEN`

Date: 2026-09-27

## Scope

S4-M4 freezes the Clipboard, Text, App, URL/Resource, and System capability
contract foundation. It preserves the existing RiskController, governed
binding, executor authority, freshness, semantic verification, app launch,
and governed input owners. No second authority, freshness, capability
registry, app launcher, or text-input runtime was introduced.

The B-stage made no production-symbol change and performed no device action.
It consolidates accepted A1/A2 Host evidence and A3/R1/R2/R3 real-device
evidence without turning an unavailable proof into a pass.

## Scoped Text Contract

S4-M4 owns the typed `TextOperationDescriptor`, capability classification,
ownership preservation, registry integration, and the non-authority boundary.
Text observation, text transformation, and text entry remain distinct. An
`ENTER` operation continues to require the existing
`GovernedInputTextRuntime`; a descriptor is not authorization.

Device text-entry end to end remains unproven. The repository-owned fixture
was not established as a launched target in A3-R2. In A3-R3, Settings was
launched through the existing governed app path and observed frontmost, but
its Search control was not exposed with the required editable, non-secure,
focus, snapshot, and direct same-leaf semantic evidence. Both attempts failed
closed before provider selection or device input dispatch. They do not prove
an input-provider defect.

The compatibility item `TEXT_INPUT_REAL_DEVICE_COMPAT_GATE` is therefore
frozen as `OPEN_DEFERRED`. It may close only when a fresh deterministic
editable semantic target completes this full chain:

`target -> legal operation -> RiskController -> governed binding -> existing provider -> device dispatch -> text delivered -> fresh post-dispatch observation -> semantic value verification`

Authorized, bound, provider-selected, dispatched, delivered, and verified
remain separate states. While the gate is open, missing semantic target
evidence fails closed. Raw input, BKS, broadcast, ASCII, blind-coordinate, and
authority bypasses remain disabled.

## Clipboard Contract

- `ClipboardVersion` is observation-scoped change evidence, not global
  identity or authorization.
- Equal `changeCount` does not establish equal content, especially across
  device sessions.
- Metadata reads remain separate from explicit content reads and return no
  plaintext.
- Continuous plaintext polling is not implemented.
- Clipboard writes remain mutations.
- Unstable TOCTOU reads fail closed and require reobservation.
- Real-device metadata and `changeCount` behavior are proven for the accepted
  target environment.

## URL And App Contracts

Typed URL validation, capability-specific scheme policy, control-character
rejection, and secret-safe diagnostics are frozen. A successful open transport
is not semantic success. The accepted real-device URL handoff includes a fresh
post-dispatch observation and persists no raw secret-bearing URL.

Existing governed app ownership remains authoritative. The accepted
real-device evidence proves governed app launch and frontmost verification.
S4-M4 added no second app launcher, binding, or frontmost verifier.

## System Contract

`SystemStateEvidence` is observation evidence only.
`SystemOperationDescriptor` is typed classification only. Neither grants
authorization; RiskController remains the sole action authorization authority.
System mutation operations not exercised on the device remain unproven and
are not reported as pass.

Private system-path presence does not prove universal reliability. The
`BOOTSTRAP_2_2_1_COMPAT_GATE` remains applicable to future
injection-dependent proof.

## Privacy And Ownership

No plaintext clipboard content, secret, raw secret-bearing URL, authority
object, or chain-of-thought was added to durable evidence. S4-M4 adds no
generic shell, process/service runtime, package manager, software manager, or
ownership from S4-M5 through S4-M9.

Frozen S4-M0, S4-M1, S4-M2, S4-M3, Stage-3, and Stage-2 contracts remain
compatible and unchanged.

## Validation

- S4-M4 focused tests: **51/51 PASS**.
- S4-M3 compatibility: **50/50 PASS**.
- S4-M2 compatibility: **45/45 PASS**.
- S4-M1 compatibility: **49/49 PASS**.
- S4-M0 compatibility: **38/38 PASS**.
- Complete offline Host regression: **115/115 files PASS**.
- Python compile/static check: **PASS**.
- Scoped documentation/evidence diff check: **PASS**.
- Frozen dependency integrity: **PASS**.
- S4-M4 blocking implementation debt: **0**.
- Open compatibility debt: **1**,
  `TEXT_INPUT_REAL_DEVICE_COMPAT_GATE = OPEN_DEFERRED`.

`S4_M4_STATUS = FROZEN_PROVEN`

The next legal module is `S4-M5 File / Log / Crash`; it was not started by this
closeout.
