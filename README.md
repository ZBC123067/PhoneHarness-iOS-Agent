# PhoneHarness

### An AI agent for the iPhone you actually control.

**Jailbreak gives AI power. PhoneHarness gives that power boundaries.**

AI phones are moving beyond chat.

Apple, Samsung, nubia, Doubao and other platforms are building assistants that understand context, work across apps, and increasingly act on behalf of the user.

But another group of iPhone users deliberately remains on older iOS versions for **TrollStore, jailbreak, RootHide, tweaks, customization, and deeper control of their own devices**.

They may not receive the newest official AI-phone experiences.

Yet a jailbroken iPhone has something an ordinary sandboxed app does not:

> **deeper access to the operating system itself.**

PhoneHarness is an open-source project exploring what becomes possible when that access is combined with a modern personal AI agent — while keeping privileged execution under explicit system control.

---

## A Personal AI Operating Agent

PhoneHarness is building toward a **Personal AI Operating Agent** for real iOS devices.

It is not intended to be another chatbot or a collection of hard-coded automation scripts.

The long-term user experience should be simple:

> **"Help me finish this."**

Behind that request, PhoneHarness works through a governed loop:

```text
Observe
→ Understand
→ Plan
→ Authorize
→ Bind
→ Act
→ Observe
→ Verify
→ Recover
→ Learn
```

The goal is an assistant that can understand what the user wants, interact with the real device, check what actually happened, recover when things go wrong, and become more useful over time.

---

## What we are building toward

PhoneHarness is designed as one agent runtime with multiple intelligence and interaction layers.

### 🧠 Personal AI

Knowledge, memory, preferences, verified experience, and reusable skills can help the assistant gradually understand its owner.

But:

> **Memory can inform an action. Memory can never authorize an action.**

### 🤖 Local + Cloud Intelligence

The architecture is designed to support both local and cloud models instead of being permanently tied to one provider.

The principle is:

> **Quality First. Local Preferred.**

### 👁 Visual & Screenshot Intelligence

Planned capabilities include OCR, Ask AI, visual understanding, screen translation, layout-aware translation, screenshot Q&A, long screenshots, annotation, error diagnosis, and structured information extraction.

### ✉️ Communication Intelligence

Email and messaging workflows can eventually combine understanding, translation, summarization, information extraction, reply generation, and governed sending.

### 🎙 Multiple entry points

The same PhoneHarness runtime is intended to be accessible through interfaces such as:

- text;
- voice;
- Siri;
- Action Button;
- Shortcuts;
- floating assistant UI;
- ChatGPT.

Different interfaces should not become different agents.

They connect to the same governed runtime.

### 🧑‍🏫 Learn from the user

Instead of recording fixed tap coordinates, PhoneHarness is designed to learn semantic workflows from demonstrations and verified experience.

### 🔄 Recover instead of blindly retrying

If PhoneHarness does not know whether an action actually happened, it should first observe reality and reconcile state.

> **A privileged side effect that may already have happened must never be blindly repeated.**

---

## Why jailbreak changes the problem

A jailbroken device can expose capabilities unavailable to an ordinary sandboxed iOS application.

That creates opportunities for deeper:

- device observation;
- app and process control;
- semantic UI interaction;
- files and diagnostics;
- system capabilities;
- controlled privileged helpers;
- package and software management.

But greater access also increases risk.

A hallucinated chatbot answer may only be wrong.

A hallucinated privileged action can change the real device.

That is why PhoneHarness follows one foundational rule:

> **The AI may propose an action. The AI is never the authority that permits the action.**

```text
Goal
  ↓
Planner
  ↓
Validator
  ↓
RiskController
  ↓
Governed Capability Binding
  ↓
Provider / Executor
  ↓
Fresh Observation
  ↓
Semantic Verifier
  ↓
Verified Result
```

Planning, authorization, binding, execution, observation, verification, and recovery remain separate boundaries.

If authority, identity, target, evidence, or result is uncertain:

**PhoneHarness fails closed.**

---

## Starting with iOS 17.0 — not ending there

The current reference platform is:

**iPhone 15 Pro · iOS 17.0 · RootHide + ElleKit**

This is the project's first controlled development and validation environment — **not its intended final compatibility boundary**.

After the core architecture is mature, PhoneHarness plans to research broader jailbreak-capable iOS environments and different jailbreak schemes.

Longer term, the same governed agent architecture may also be explored on **macOS**.

> **PhoneHarness starts with the iPhone. The architecture is intended to go further.**

Compatibility will be earned through platform-specific testing and device gates rather than assumed.

---

## What exists today

PhoneHarness is currently a **pre-release open-source runtime**.

The public project focuses first on the foundations required before increasingly powerful AI capabilities can be exposed safely:

```text
Security & Authority
→ Reliable Execution
→ Device Capabilities
→ Personal Intelligence
→ Product Experience
```

The repository currently includes:

- governed agent runtime foundations;
- capability / provider separation;
- authorization and semantic verification boundaries;
- MCP authentication and transport hardening;
- execution evidence / ledger concepts;
- RootHide, rootless, and rootful build support;
- offline host tests;
- GitHub Actions CI;
- security, dependency, contribution, and licensing documentation.

The current public host suite passes:

```text
70 / 70 tests
```

The full Personal AI experience described above is the direction of the project — not a claim that every capability is already complete.

---

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
