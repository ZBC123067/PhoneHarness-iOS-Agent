[English](README.md) | [简体中文](README.zh-CN.md)

# ZTako

> ### The AI future shouldn't leave your iPhone behind.
>
> AI 的未来，不应该让你的 iPhone 掉队。

**Your iPhone. Your AI. Your Control.**

[![host tests](https://github.com/ZBC123067/PhoneHarness-iOS-Agent/actions/workflows/host-tests.yml/badge.svg)](https://github.com/ZBC123067/PhoneHarness-iOS-Agent/actions/workflows/host-tests.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Website](https://img.shields.io/badge/website-zbc123067.github.io%2FPhoneHarness--iOS--Agent-6c8cff)](https://zbc123067.github.io/PhoneHarness-iOS-Agent/)

## New AI phones are arriving. What about the iPhones left behind?

Apple Intelligence, Galaxy AI, Doubao Phone Assistant, nubia AI — the industry is turning smartphones into AI assistants that understand natural language, read the screen, and complete tasks.

But none of that automatically reaches the users who deliberately stay on **iOS 17 or older** — for jailbreak ecosystems, RootHide, TrollStore, tweaks, compatibility, or simply because they want to keep the environment they chose.

ZTako explores a third option: **not** forcing users to abandon their current environment, but exploring how a modern AI agent can work with the iPhone they already control — combining jailbreak-grade device access with modern AI models, while keeping privileged execution under explicit authorization boundaries.

> ZTako is bringing next-generation AI agent experiences to jailbreak-capable iPhones.

🚀 **[Visit the website](https://zbc123067.github.io/PhoneHarness-iOS-Agent/)** (English / 简体中文)

## One instruction. Real action.

The long-term experience ZTako is building toward:

```text
You describe the goal
  ↓
The agent understands the task
  ↓
Observes the current screen
  ↓
Identifies apps and interactive elements
  ↓
Plans the steps
  ↓
Asks for authorization where needed
  ↓
Taps, swipes, types, or launches
  ↓
Observes the screen again
  ↓
Verifies the real outcome
```

ZTako is not just a chatbot that answers questions — it is an exploration of an agent that actually interacts with the device. Full one-sentence autonomy is a development direction, not a shipped feature; the device-control primitives behind it exist today as the open MCP foundation.

## What we are building

- 🤖 **Personal Jarvis vision** — voice, task context, cross-app goals, honest feedback, memory and skills (staged direction; memory informs actions but never authorizes them).
- 🖥 **iPhone × Mac** — a controlled, token-authenticated connection today; task handoff and cross-device context as a future direction, always local-first per user.
- 📸 **Screenshot & vision intelligence** — OCR today; Ask AI, error diagnosis, layout-aware translation and summaries in development or planned.
- ⌨️ **AI keyboard direction** — intelligence where you type, across platforms, explored honestly per platform.
- 🧠 **Local-first + cloud choice** — Quality First. Local Preferred. Model capability and execution permission stay separate systems.

## Why jailbreak matters

An ordinary iOS app is sandboxed. A jailbreak research environment legitimately unlocks deeper surfaces an agent can use: system observation, the accessibility tree, real device interaction, app lifecycle control, process and service management, files and diagnostics, MCP device control, and package analysis.

More access also means more responsibility:

> **AI can propose actions. You remain in control.**

Jailbreak expands what is technically accessible — it does not make every action unrestricted. ZTako keeps real authorization boundaries and fails closed when anything is uncertain. Details: [SECURITY.md](SECURITY.md) and [docs/security-model.md](docs/security-model.md).

## What exists today

ZTako (historically developed under the codename "PhoneHarness") is a **pre-release open-source project**, verified through its public host test suite — not a finished consumer product.

- **iOS MCP device server** — Objective-C + Theos, 20+ device tools in the published source: tap, swipe, text input, screenshots, OCR, accessibility-tree reading, app management, clipboard, process/service control, package management, and helper CLIs.
- **Governed host agent runtime** — Python 3 (standard library only): planning, capability binding, authorization, observation, semantic verification and recovery boundaries.
- **Build support** — rootful, rootless, and RootHide (roothide) schemes; reference environment: **iPhone 15 Pro · iOS 17.0 · RootHide + ElleKit**.
- **Offline host test suite** — the public suite passed **70/70** at the latest verified CI run (2026-10-02, commit `98b965e`). CI reruns it on every push; the Actions badge above always shows the current state. This is a historical baseline tied to its verification point, not a claim about unreleased code.

Status labels used across the project and website:

| Label | Meaning |
|---|---|
| **Available Foundation** | Exists in the published source and is exercised by the public test suite / CI |
| **In Development** | Partially implemented, actively being built |
| **Vision** | A product direction — not implemented end-to-end yet |

## Documentation

- [Project website](https://zbc123067.github.io/PhoneHarness-iOS-Agent/) — the product story, in English and 简体中文
- [docs/PROJECT-TECHNICAL.md](docs/PROJECT-TECHNICAL.md) — the previous full technical README (architecture, setup, testing, licensing)
- [docs/architecture.md](docs/architecture.md) · [docs/security-model.md](docs/security-model.md) · [docs/getting-started.md](docs/getting-started.md)
- [docs/roadmap.md](docs/roadmap.md) — Foundation → Device Intelligence → Action & Verification → Personal AI → Connected Experience → Agent OS
- [SECURITY.md](SECURITY.md) · [DEPENDENCIES.md](DEPENDENCIES.md) · [CONTRIBUTING.md](CONTRIBUTING.md)

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Vulnerabilities go through GitHub Security Advisories, never public issues.

## Licensing

Project-owned source is licensed under the **Apache License 2.0** ([LICENSE](LICENSE)). Third-party components (ldid, AppSync Unified, libplist, OpenSSL, libzip) keep their own licenses and are intentionally not vendored — see [DEPENDENCIES.md](DEPENDENCIES.md).

---

*ZTako is an independent open-source research project. Apple, Samsung, ByteDance, nubia and their product names are trademarks of their respective owners, mentioned here only as public industry background; no affiliation or endorsement is implied.*
