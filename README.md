[English](README.md) | [简体中文](README.zh-CN.md)

# ZTako

> ### You set the goal. ZTako handles the steps.
>
> 你只管说目标，剩下的交给 ZTako。

**Your iPhone. Your AI. Your Control.**

[![host tests](https://github.com/ZBC123067/PhoneHarness-iOS-Agent/actions/workflows/host-tests.yml/badge.svg)](https://github.com/ZBC123067/PhoneHarness-iOS-Agent/actions/workflows/host-tests.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Website](https://img.shields.io/badge/website-zbc123067.github.io%2FPhoneHarness--iOS--Agent-6c8cff)](https://zbc123067.github.io/PhoneHarness-iOS-Agent/)

ZTako is an open-source personal AI agent explored for jailbreak-capable iPhones. The goal: you only describe the outcome you want — ZTako works to understand the task, plan the steps, use device capabilities that are subject to your authorization, and verify what actually happened.

It is built for the users that the new AI-phone wave leaves behind: people who deliberately stay on older iOS versions for **jailbreak ecosystems, RootHide, TrollStore, tweaks, and deep customization**. AI phones are evolving from chat toward screen understanding and task execution — ZTako explores that direction for the iPhone you already own, without asking you to abandon the environment you chose.

🚀 **[Visit the website](https://zbc123067.github.io/PhoneHarness-iOS-Agent/)** — interactive demos in English / 简体中文

## One instruction. A world of possibilities.

The experience ZTako is building toward — you say the goal, the agent works the steps:

- 💬 **WeChat & messages** — *"Open WeChat and tell Zhang San I'll be a bit late."*
- ✉️ **Email & office** — *"Write an English email to the client and attach the quote file."*
- 🛍 **AI shopping** — *"Find suitable headphones on Taobao, JD and Pinduoduo."*
- 🎵 **Social apps** — *"Find this Douyin account, follow it, and prepare a DM."*
- 🎛 **System settings** — *"Brighten the screen, lower the volume, and turn on Bluetooth."*
- 🔎 **Web research** — *"Compare this laptop across stores and summarize the differences."*

> **Status: development direction / interactive concept.** These flows are demonstrated as labeled concept demos on the website. A full one-sentence autonomous chain across arbitrary apps is not a shipped feature; compatibility with any specific app always depends on real system interfaces and versions.

## AI works while you live

After you give a goal, ZTako works through understanding, planning and preparation in its allowed environment, and comes back to you only when a decision really needs you:

```text
You describe the goal
  ↓
The agent understands and plans
  ↓
Background preparation and research
  ↓
Sensitive actions require your approval
  ↓
Controlled execution
  ↓
Verification against the real screen
```

> **AI handles the steps. You control the decisions.** Every important action — sending a message, submitting an order — is shown to you with its key details (recipient, content, price) and waits for explicit confirmation. Background behavior is simulated as a concept on the website; real iOS background behavior always depends on the system.

## A brain to think. Eyes to understand. Hands to act.

ZTako is designed as one complete agent:

- 🧠 **Brain** — AI planning, local-first intelligence, optional cloud models, task understanding.
- 👁 **Eyes** — screen observation, screenshot intelligence, OCR, UI element recognition.
- 🤲 **Hands** — tap, swipe, type, open apps, interact with supported controls, verify results.
- 🎙 **Voice & chat** — natural language interaction (voice is a vision).
- ⌨️ **ZTako keyboard I/O** — the input method is one of the agent's intelligent input/output surfaces, next to text, voice, screenshots and quick entries.

**Platform note:** keyboard intelligence is explored as an input-method research direction, per platform. The Mac-side input method is a separate research workflow. This does not mean the Mac is a required device for ZTako, nor that full cross-device task sync or cross-device automatic control is finished — such capabilities are only ever claimed as far as they are actually implemented and tested.

## Screenshot it. Understand it. Act on it.

A screenshot is the beginning of a task: analyze it, then continue — translate, summarize, extract, or take the suggested next action.

- *"Help me translate and explain this page."*
- *"Look at this error and tell me what's wrong."*
- *"Find products similar to this one and compare prices."*

> **Status:** OCR recognition is an available foundation in the published source; screenshot-to-action chains (translation, diagnosis, similar-product search, image editing) are development directions or interactive concepts, and image editing would depend on external or local model services.

## Your intelligence. Your choice.

- 🖥 **Local-first** — prefer on-device or nearby models where possible; your screen and personal data stay with you by default.
- ☁️ **Cloud, when you choose** — stronger cloud models for tasks that need them, selected by you, never a mandate.
- 🔒 **Privacy-aware** — no automatic upload of screenshots, messages or personal data. Model capability and execution permission are separate systems.

The long-term direction is a **personal Jarvis**: task context, preference understanding, reminders, multi-step tasks, experience and reusable skills — always informing actions, never authorizing them. Voice-only autonomous operation is a vision, not a current feature.

## Why old-iOS users need ZTako

Apple Intelligence, Galaxy AI, Doubao Phone Assistant and nubia AI are turning new phones into AI assistants. But users who keep older iOS for jailbreak, TrollStore, RootHide and customization are cut off from that wave.

ZTako explores the third option: an **open, customizable personal AI agent** for the iPhone they chose to keep. The next generation of mobile AI shouldn't be limited to the newest iPhone on the shelf.

> Industry names are mentioned as public background only. No affiliation, endorsement or feature-equivalence is claimed.

## Real engineering, in the open

ZTako (historically developed under the codename "PhoneHarness") is a **pre-release open-source project** — real engineering, not just a concept site:

- **iOS MCP device server** — Objective-C + Theos for jailbroken iPhones; 20+ device tools in the published source: tap, swipe, text input, screenshots, OCR, accessibility-tree reading, app management, clipboard, process/service control, package management, helper CLIs.
- **Governed host agent runtime** — Python 3 (standard library only): planning, capability binding, authorization, observation, semantic verification and recovery boundaries.
- **Build support** — rootful, rootless, RootHide schemes; reference environment: **iPhone 15 Pro · iOS 17.0 · RootHide + ElleKit**.
- **Offline host test suite** — the public suite passed **70/70 at commit `98b965e` (CI run of 2026-10-02)**. This is a historical baseline tied to its verification point, not a claim about unreleased code; CI reruns the suite on every push, and the Actions badge above shows the current state.

### Documentation

- [Project website](https://zbc123067.github.io/PhoneHarness-iOS-Agent/) — product story with interactive demos (EN / 简体中文)
- [docs/PROJECT-TECHNICAL.md](docs/PROJECT-TECHNICAL.md) — full technical README (architecture, setup, testing, licensing)
- [docs/architecture.md](docs/architecture.md) · [docs/security-model.md](docs/security-model.md) · [docs/getting-started.md](docs/getting-started.md)
- [docs/roadmap.md](docs/roadmap.md) · [SECURITY.md](SECURITY.md) · [DEPENDENCIES.md](DEPENDENCIES.md) · [CONTRIBUTING.md](CONTRIBUTING.md)

### Status labels

| Label | Meaning |
|---|---|
| **Available Foundation** | Exists in the published source, exercised by the public test suite / CI |
| **In Development / Prototype** | Partially implemented or host-tested, actively being built |
| **Vision / Concept** | A product direction or labeled concept demo — not implemented end-to-end |

### Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Vulnerabilities go through GitHub Security Advisories, never public issues.

### Licensing

Project-owned source is licensed under the **Apache License 2.0** ([LICENSE](LICENSE)). Third-party components (ldid, AppSync Unified, libplist, OpenSSL, libzip) keep their own licenses and are intentionally not vendored — see [DEPENDENCIES.md](DEPENDENCIES.md).

---

*ZTako is an independent open-source research project. Apple, Samsung, ByteDance and nubia product names are trademarks of their respective owners, mentioned only as public industry background; no affiliation or endorsement is implied.*
