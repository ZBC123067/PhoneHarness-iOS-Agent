[English](README.md) | [简体中文](README.zh-CN.md)

# ZTako

> ### AI 的未来，不应该让你的 iPhone 掉队。
>
> The AI future shouldn't leave your iPhone behind.

**你的 iPhone，你的 AI，你的掌控。**

[![host tests](https://github.com/ZBC123067/PhoneHarness-iOS-Agent/actions/workflows/host-tests.yml/badge.svg)](https://github.com/ZBC123067/PhoneHarness-iOS-Agent/actions/workflows/host-tests.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Website](https://img.shields.io/badge/website-zbc123067.github.io%2FPhoneHarness--iOS--Agent-6c8cff)](https://zbc123067.github.io/PhoneHarness-iOS-Agent/zh-CN/)

## 新一代 AI 手机正在到来，那些仍停留在旧系统的 iPhone 呢？

Apple Intelligence、Galaxy AI、豆包手机助手、努比亚 AI —— 整个行业正在把智能手机变成能理解自然语言、读懂屏幕、替你完成任务的 AI 助手。

但这些体验不会自动降临到那些**刻意停留在 iOS 17 或更旧版本**的用户身上 —— 他们为了越狱生态、RootHide、TrollStore、插件、兼容性，或者只是想保留自己选择的环境。

ZTako 探索第三种选择：**不**强迫用户放弃当前环境，而是探索如何让现代 AI Agent 与他们已经掌控的 iPhone 协同工作 —— 把越狱级的设备控制能力与现代 AI 模型结合，同时让特权执行始终处于明确的授权边界之内。

> ZTako 致力于把下一代 AI Agent 体验带给仍然使用越狱环境的 iPhone 用户。

🚀 **[访问官网](https://zbc123067.github.io/PhoneHarness-iOS-Agent/zh-CN/)**（简体中文 / English）

## 一句话，真实行动。

ZTako 正在构建的长期体验：

```text
你描述目标
  ↓
AI 理解任务
  ↓
观察当前屏幕
  ↓
识别 App 和交互元素
  ↓
规划操作步骤
  ↓
在需要时请求授权
  ↓
执行点击、滑动、输入或启动
  ↓
再次观察屏幕
  ↓
核对真实结果
```

ZTako 不只是回答问题的聊天机器人 —— 它探索的是一个真正与设备交互的 Agent。完整的一句话自主执行是研发方向，不是已上线功能；背后的设备控制原语今天已作为开源 MCP 基础存在。

## 我们在构建什么

- 🤖 **个人 Jarvis 愿景** —— 语音、任务上下文、跨 App 目标、如实反馈、记忆与技能（分阶段方向；记忆可以为操作提供参考，但永远不会授权操作）。
- 🖥 **iPhone × Mac** —— 今天是受控的、令牌认证的连接；任务接力与跨设备上下文是未来方向，始终坚持每个用户的本地优先。
- 📸 **截图与视觉智能** —— OCR 今天已具备；Ask AI、错误诊断、版面感知翻译与总结处于开发中或规划中。
- ⌨️ **AI 输入法方向** —— 智能就在你输入的地方，跨平台探索，按平台如实标注进度。
- 🧠 **本地优先 + 云端可选** —— 质量优先，本地优先。模型能力与执行权限始终是分离的两套系统。

## 越狱为何重要

普通 iOS 应用被沙盒限制。越狱研究环境可以合理解锁更深的系统层面供 Agent 使用：系统观察、无障碍树、真实设备交互、App 生命周期控制、进程与服务管理、文件与诊断、MCP 设备控制、软件包分析。

更大的访问能力也意味着更大的责任：

> **AI 可以提议操作，决定权始终在你手中。**

越狱扩大的是技术上可触达的范围 —— 不代表所有操作都能无条件执行。ZTako 保留真实的授权边界，任何不确定时都会 fail closed。详见 [SECURITY.md](SECURITY.md) 与 [docs/security-model.md](docs/security-model.md)。

## 今天已有什么

ZTako（研发代号 "PhoneHarness"）是一个**预发布开源项目**，通过公开的宿主测试套件验证 —— 不是已完成的消费级产品。

- **iOS MCP 设备服务端** —— Objective-C + Theos，已公开源码中包含 20+ 设备工具：点击、滑动、文本输入、截图、OCR、无障碍树读取、App 管理、剪贴板、进程/服务控制、软件包管理，以及多个辅助 CLI。
- **受控宿主 Agent 运行环境** —— Python 3（仅标准库）：规划、能力绑定、授权、观察、语义验证与恢复边界。
- **构建支持** —— rootful、rootless、RootHide（roothide）三种方案；参考环境：**iPhone 15 Pro · iOS 17.0 · RootHide + ElleKit**。
- **离线宿主测试套件** —— 公开测试套件在最近一次已验证 CI 运行中 **70/70** 全部通过（2026-10-02，提交 `98b965e`）。CI 会在每次推送时重新运行；上方 Actions 徽章始终显示当前状态。这是与其验证时点绑定的历史基线，不代表未发布代码的状态。

项目和官网使用的状态标签：

| 标签 | 含义 |
|---|---|
| **已验证基础 / Available Foundation** | 已存在于公开源码中，并被公开测试套件 / CI 覆盖 |
| **开发中 / In Development** | 部分实现，正在积极构建 |
| **愿景 / Vision** | 产品方向 —— 尚未端到端实现 |

## 文档

- [项目官网](https://zbc123067.github.io/PhoneHarness-iOS-Agent/zh-CN/) —— 产品故事，简体中文 / English
- [docs/PROJECT-TECHNICAL.md](docs/PROJECT-TECHNICAL.md) —— 原完整技术版 README（架构、环境准备、测试、许可）
- [docs/architecture.md](docs/architecture.md) · [docs/security-model.md](docs/security-model.md) · [docs/getting-started.md](docs/getting-started.md)
- [docs/roadmap.md](docs/roadmap.md) —— 基础 → 设备智能 → 行动与验证 → 个人 AI → 互联体验 → Agent OS
- [SECURITY.md](SECURITY.md) · [DEPENDENCIES.md](DEPENDENCIES.md) · [CONTRIBUTING.md](CONTRIBUTING.md)

## 参与贡献

欢迎提交 Issue 和 Pull Request —— 见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全漏洞请通过 GitHub Security Advisories 报告，不要提公开 Issue。

## 许可

项目自有源码以 **Apache License 2.0** 许可（[LICENSE](LICENSE)）。第三方组件（ldid、AppSync Unified、libplist、OpenSSL、libzip）保留各自许可证，且有意不内嵌进源码树 —— 见 [DEPENDENCIES.md](DEPENDENCIES.md)。

---

*ZTako 是一个独立的开源研究项目。Apple、Samsung、字节跳动、努比亚及其产品名称为各自所有者的商标，此处仅作为公开行业背景提及；不代表任何合作或认可关系。*
