[English](README.md) | [简体中文](README.zh-CN.md)

# ZTako

> ### 你只管说目标，剩下的交给 ZTako。
>
> You set the goal. ZTako handles the steps.

**你的 iPhone，你的 AI，你的掌控。**

[![host tests](https://github.com/ZBC123067/PhoneHarness-iOS-Agent/actions/workflows/host-tests.yml/badge.svg)](https://github.com/ZBC123067/PhoneHarness-iOS-Agent/actions/workflows/host-tests.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Website](https://img.shields.io/badge/website-zbc123067.github.io%2FPhoneHarness--iOS--Agent-6c8cff)](https://zbc123067.github.io/PhoneHarness-iOS-Agent/zh-CN/)

ZTako 是为可越狱 iPhone 探索的开源个人 AI 助理。目标是：你只需要描述想要的结果 —— ZTako 努力理解任务、规划步骤，在获得你授权的前提下使用设备能力，并核对真实执行结果。

它服务于被新一代 AI 手机浪潮落下的用户：那些为了**越狱生态、RootHide、TrollStore、插件与深度自定义**而刻意停留在旧版 iOS 的人。AI 手机正从聊天问答走向屏幕理解与任务执行 —— ZTako 为你已经拥有的 iPhone 探索这个方向，不要求你放弃自己选择的环境。

🚀 **[访问官网](https://zbc123067.github.io/PhoneHarness-iOS-Agent/zh-CN/)** —— 交互演示，简体中文 / English

## 一句话，手机任务交给 AI

ZTako 正在构建的体验 —— 你说目标，Agent 负责步骤：

- 💬 **微信与消息** —"帮我打开微信，给张三发消息说我晚点到。"
- ✉️ **邮件与办公** —"给客户写封英文邮件，附上今天的报价文件。"
- 🛍 **AI 购物** —"去淘宝、京东和拼多多，帮我找适合的耳机。"
- 🎵 **社交应用** —"找到这个抖音账号，关注他，并准备一条私信。"
- 🎛 **系统设置** —"把屏幕调亮一点，声音调小，打开蓝牙。"
- 🔎 **网络搜索** —"帮我查一下这款电脑，比较不同平台的配置和价格。"

> **状态：开发方向 / 交互概念演示。** 以上流程在官网上以明确标注的概念演示呈现。覆盖任意 App 的一句话自主执行链路不是已上线功能；对任何具体 App 的兼容性始终取决于真实系统接口与版本。

## AI 在你生活时工作

目标发出后，ZTako 在允许的环境里完成理解、规划与准备，只在真正需要你决策时回到你面前：

```text
你描述目标
  ↓
AI 理解并规划
  ↓
后台准备与信息收集
  ↓
敏感动作需要你的授权
  ↓
受控执行
  ↓
对照真实屏幕核对结果
```

> **AI 负责步骤，你掌控决定。**每个重要动作 —— 发送消息、提交订单 —— 都会向你展示关键信息（收件人、内容、价格），并等待你的明确确认。官网上的后台行为是概念模拟；真实的 iOS 后台行为始终取决于系统。

## 让 AI 拥有大脑、眼睛和双手

ZTako 被设计为一个完整的智能体：

- 🧠 **大脑** —— AI 规划、本地优先智能、可选云端模型、任务理解。
- 👁 **眼睛** —— 屏幕观察、截图智能、OCR、UI 元素识别。
- 🤲 **双手** —— 点击、滑动、输入、打开 App、与受支持的控件交互、核对结果。
- 🎙 **声音与交流** —— 自然语言交互（语音为愿景）。
- ⌨️ **ZTako 输入法 I/O** —— 输入法是智能体的智能输入输出接口之一，与文字、语音、截图、快捷入口并列。

**平台说明：**键盘智能按平台作为输入法研发方向探索。Mac 端输入法属于独立的研发工作流。这不意味着 Mac 是 ZTako 手机的必需运行设备，也不代表整机任务同步或跨设备自动控制已经完成 —— 此类能力只能按真实实现与测试状态描述。

## 截个图，让 AI 接着办

截图是任务的起点：先分析，再继续 —— 翻译、总结、提取，或执行建议的后续动作。

- *"帮我翻译并解释这段内容。"*
- *"看看这个错误，告诉我哪里出了问题。"*
- *"帮我找类似商品，比较一下价格。"*

> **状态：**OCR 文字识别是已公开源码中的可用基础；截图到动作的链路（翻译、诊断、相似商品搜索、图片编辑）属于开发方向或交互概念，其中图片编辑将依赖外部或本地模型服务。

## 你的 AI，由你选择

- 🖥 **本地优先** —— 尽可能在设备上或设备附近完成理解；屏幕内容与个人数据默认留在你手里。
- ☁️ **云端，由你选择** —— 当任务需要更强能力时使用云端模型，由你选择，绝非强制。
- 🔒 **隐私自觉** —— 不自动上传截图、消息或个人资料。模型能力与执行权限是分离的两套系统。

长期方向是一个**个人 Jarvis**：任务上下文、偏好理解、任务提醒、多步骤任务、经验与可复用技能 —— 始终为操作提供参考，永远不授权操作。纯语音的自主运行是愿景，不是当前功能。

## 为什么旧版 iOS 用户需要 ZTako

Apple Intelligence、Galaxy AI、豆包手机助手和努比亚 AI 正把新手机变成 AI 助手。但为越狱、TrollStore、RootHide 和自定义而保留旧版 iOS 的用户，被挡在了这波浪潮之外。

ZTako 探索第三种选择：为他们选择保留的 iPhone，打造一个**开放、可定制的个人 AI Agent**。下一代手机 AI，不应该只属于货架上最新的手机。

> 行业名称仅作为公开背景提及。不声称任何官方合作、认可或功能等效。

## 真实工程，公开透明

ZTako（研发代号 "PhoneHarness"）是一个**预发布开源项目** —— 真实工程，不只是概念站：

- **iOS MCP 设备服务端** —— Objective-C + Theos，面向越狱 iPhone；已公开源码中包含 20+ 设备工具：点击、滑动、文本输入、截图、OCR、无障碍树读取、App 管理、剪贴板、进程/服务控制、软件包管理、辅助 CLI。
- **受控宿主 Agent 运行环境** —— Python 3（仅标准库）：规划、能力绑定、授权、观察、语义验证与恢复边界。
- **构建支持** —— rootful、rootless、RootHide 三种方案；参考环境：**iPhone 15 Pro · iOS 17.0 · RootHide + ElleKit**。
- **离线宿主测试套件** —— 公开测试套件在**提交 `98b965e`（2026-10-02 的 CI 运行）时点 70/70 全部通过**。这是与其验证时点绑定的历史基线，不代表未发布代码的状态；CI 会在每次推送时重新运行，上方 Actions 徽章始终显示当前状态。

### 文档

- [项目官网](https://zbc123067.github.io/PhoneHarness-iOS-Agent/zh-CN/) —— 带交互演示的产品故事（简体中文 / English）
- [docs/PROJECT-TECHNICAL.md](docs/PROJECT-TECHNICAL.md) —— 完整技术版 README（架构、环境准备、测试、许可）
- [docs/architecture.md](docs/architecture.md) · [docs/security-model.md](docs/security-model.md) · [docs/getting-started.md](docs/getting-started.md)
- [docs/roadmap.md](docs/roadmap.md) · [SECURITY.md](SECURITY.md) · [DEPENDENCIES.md](DEPENDENCIES.md) · [CONTRIBUTING.md](CONTRIBUTING.md)

### 状态标签

| 标签 | 含义 |
|---|---|
| **可用基础 / Available Foundation** | 已存在于公开源码，被公开测试套件 / CI 覆盖 |
| **开发中 / 原型 / In Development · Prototype** | 部分实现或经宿主测试，正在积极构建 |
| **愿景 / 概念 / Vision · Concept** | 产品方向或明确标注的概念演示 —— 尚未端到端实现 |

### 参与贡献

欢迎提交 Issue 和 Pull Request —— 见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全漏洞请通过 GitHub Security Advisories 报告，不要提公开 Issue。

### 许可

项目自有源码以 **Apache License 2.0** 许可（[LICENSE](LICENSE)）。第三方组件（ldid、AppSync Unified、libplist、OpenSSL、libzip）保留各自许可证，且有意不内嵌进源码树 —— 见 [DEPENDENCIES.md](DEPENDENCIES.md)。

---

*ZTako 是一个独立的开源研究项目。Apple、Samsung、字节跳动与努比亚产品名称为各自所有者的商标，仅作为公开行业背景提及；不代表任何合作或认可关系。*
