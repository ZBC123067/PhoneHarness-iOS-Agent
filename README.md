# PhoneHarness-iOS-Agent

**A governed privileged AI agent runtime for real iOS devices.**

PhoneHarness sits between an AI planner and a jailbroken iOS device's MCP (Model
Context Protocol) tool surface. The planner proposes; PhoneHarness decides whether
an action is permitted, binds it to a capability, executes it through a provider,
observes the result, verifies it, and records it in an append-only ledger.

## Why it exists

Ordinary mobile automation is *scripted*: a fixed sequence of taps, or an LLM that
is allowed to call device tools directly. Both break in the same way — the model
becomes the authority. A confident hallucination is executed as if it were a
decision.

PhoneHarness treats the model as an *advisor*, never an authority. Every privileged
action crosses explicit boundaries that can refuse, and nothing is called
"successful" until it has been observed and verified.

### How it differs from ordinary GUI automation

| Ordinary automation | PhoneHarness |
|---|---|
| Model output is executed directly | Model output is a **proposal**, checked by Validator + RiskController |
| Tapping a capability name runs it | Capability is a **contract**; binding to a provider is a governed step |
| Tool returns `ok` → done | Tool return is an **observation**; only the Verifier may declare success |
| Learned memory/skills accumulate permission | Memory/Skills may inform planning, **never** authorize |
| Errors end the run | Recovery plane: obligation ledger, restart-safe recovery, ownership fencing |

## Architecture

```
Goal → Planner → Validator → TaskCoordinator → RiskController
     → Capability Binding → Provider → Executor → Observation → Verifier → Ledger
```

Each stage is a boundary, not a convenience call, and each one can refuse.

### Design principles

- **Planner != Authorization** — a plan is a proposal, never a grant.
- **Capability != Provider** — naming a capability does not select an implementation.
- **Provider != Authorization** — having a provider does not permit using it.
- **Executor success != Semantic success** — "the call returned" is not "it happened".
- **Memory != Authorization**, **Skills != Authorization** — knowledge never widens permission.
- **Verification is required** before any action is treated as semantically successful.
- **Fail closed** whenever identity, authority, evidence, target, or result is uncertain.

## Security model

- Every device MCP endpoint requires the `X-MCP-Token` header (constant-time compare,
  no exempt endpoint, fail closed).
- The host reads the token from the `PHONEHARNESS_MCP_TOKEN` environment variable;
  tokens are never hardcoded and never logged.
- The device generates its own token from the OS CSPRNG and stores it mode `0600`.
- The device server binds to loopback by default; LAN exposure is opt-in.
- Full detail: [`SECURITY.md`](SECURITY.md) and [`docs/security-model.md`](docs/security-model.md).

Report vulnerabilities via **GitHub Security Advisories** — never a public issue.

## Supported environment

| | |
|---|---|
| Host runtime | macOS or Linux, Python 3 (standard library only) |
| Device | jailbroken iOS device |
| Jailbreak schemes | rootful, rootless, roothide (RootHide) |
| Injection runtime | MobileSubstrate / ElleKit |
| Developed/tested against | iOS 17.0 with RootHide + ElleKit |
| Build system | [Theos](https://theos.dev) (+ Logos) |

## Preparing to use it

### Host requirements

- Python 3.10+ (no third-party packages required for the runtime or the test suite).
- Network reachability to the device endpoint (loopback/USB-forward by default).
- `PHONEHARNESS_MCP_TOKEN` set to the device's configured token.

### iOS requirements

- A jailbroken device with MobileSubstrate/ElleKit and PreferenceLoader.
- For roothide builds, the roothide library must be available in the build environment.
- An installed build of this tweak, with an auth token provisioned (the packaged
  `postinst` generates one on install).

### RootHide / ElleKit notes

- Build with `THEOS_PACKAGE_SCHEME=roothide` on RootHide, `rootless` on rootless jailbreaks.
- Path translation is handled by the roothide library and is only linked for roothide builds.

## Testing

```bash
python3 run_all_tests.py
```

**70/70 public host unit tests pass.** They are offline and require no device.

CI runs them on **macOS**, the project's host platform: a few of the host unit
tests compile a small Objective-C harness with the Apple toolchain
(`xcrun`/`clang`), so the complete suite is executed on macOS runners. On Linux
the Python-only tests run, but those harness tests cannot.

18 further internal regression tests are **not** included: they depend on private
device diagnostic/evidence artifacts that are not published. They are deliberately
not exported just to increase the count — see the roadmap item to re-derive them
against synthetic public fixtures [`docs/roadmap.md`](docs/roadmap.md).

CI runs the same public suite on every push and pull request
(`.github/workflows/host-tests.yml`). CI needs no device, no jailbreak, and no
credentials.

## External dependencies

This source tree vendors **no** third-party code. The build-time and runtime
dependencies (Theos, MobileSubstrate/ElleKit, PreferenceLoader, roothide, ldid,
AppSync, OpenSSL, libplist, libzip) are documented in
[`DEPENDENCIES.md`](DEPENDENCIES.md) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

The optional helper tools (`mcp-root`, `mcp-roothelper`, `mcp-logreader`,
`mcp-ldid`) build from their own Makefiles and depend on external sources that are
not vendored. Their Makefiles **fail fast with setup instructions** if those
sources are missing; they never download or vendor anything for you.

## Current limitations

- The optional helper tools require external third-party sources you must supply.
- The 18 device-evidence-bound regression tests are not public (see Testing).
- Host–device transport defaults to loopback/USB-forward; remote exposure is opt-in.
- Some subsystems are young and evolving (see roadmap).

## Experimental

The dynamic planner, capability-provider routing, recovery/state plane, and the
personal knowledge / memory layer are active research surfaces. Interfaces in these
areas may change between minor versions. The architectural invariants above do not.

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md). Highlights: state & recovery plane,
localized app resolution, provider router, personal knowledge & memory, and public
synthetic regression fixtures.

## Contributing

Issues and pull requests are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md).
By contributing you agree your contributions are licensed under Apache-2.0.

## Licensing

Project-owned source is licensed under the **Apache License 2.0** (see [`LICENSE`](LICENSE)).

This covers PhoneHarness-owned code **only**. It does **not** extend to external
third-party components, which are not vendored here and keep their own licenses:

- `ldid` — AGPL-3.0-only
- `AppSync Unified` / `appinst` — GPL-3.0-or-later
- `libplist` — LGPL-2.1-or-later
- OpenSSL — Apache-2.0
- `libzip` — BSD-3-Clause

> Source-code licensing under Apache-2.0 does **not** imply that a future binary
> distribution combining external copyleft dependencies can be redistributed under
> Apache-2.0 alone. Any future `.deb` / binary release requires a separate dependency
> and license review.

## Status

Pre-release staging (`v0.1.0`): source-only public release.
