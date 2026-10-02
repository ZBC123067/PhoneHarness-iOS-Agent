# PhoneHarness AI Start Here

PROJECT: PhoneHarness

REPOSITORY: this repository checkout

This repository is the source of truth for a local, model-agnostic takeover.
Do not depend on prior Codex, ChatGPT, Gemini, Claude, Cursor, Windsurf, or
other conversation history.

Read in order:

1. `docs/roadmap/PHONEHARNESS_CANONICAL_ROADMAP.md`
2. `docs/MASTER_HANDOFF.md`
3. `docs/AI_PROJECT_RULES.md`
4. `docs/TEST_STATUS_MATRIX.md`
5. current Git status and only the implementation relevant to the assigned task

PERMANENT GOVERNANCE — P21/P22/P23/P24 (do not skip):

PhoneHarness is ONE AI-native operating layer, not "AI + independent feature
modules". Every capability must be composable by the shared AI runtime
through typed observation, semantic context, shared world/task context,
governed capability exposure, fresh post-action observation, semantic
verification, and controlled learning. No feature or module may become an
isolated intelligence island (`INTELLIGENCE_ISLAND_ALLOWED = NO`). From
S4-M6 onward every Final Closeout/Freeze must pass the mandatory P21
AI-native freeze gate, and every A0 audit must include an AI-Native
Integration Audit. The authoritative statement lives in the canonical
roadmap ("P21 — AI-Native System Unity" through "P24 — Perceptually
Real-Time Interaction"). Coding agents implement this architecture; they do
not own or reinterpret it. Shared semantic context is descriptive evidence,
never authority, and real-time product claims are based on perceptual metrics
and real-device evidence rather than fictional zero-latency guarantees.

PERMANENT FROZEN-INCIDENT RULE:

If a frozen file differs and the active task did not explicitly authorize a
frozen reopen, stop immediately. Do not repair, reconstruct, normalize,
rebaseline, update tests around the drift, or update frozen hashes. Report
`FROZEN_INTEGRITY_INCIDENT = YES` and request architect review. Every
substantive implementation task declares `EXPECTED_WRITE_SET`,
`ACTUAL_WRITE_SET`, and `UNAUTHORIZED_WRITE_COUNT`.

Current facts:

- `STAGE_2_STATUS = FROZEN_PROVEN`.
- `STAGE_3_STATUS = FROZEN_PROVEN`.
- `S4-M0` through `S4-M5 = FROZEN_PROVEN`.
- Current module: `S4-M6 Process / Service`.
- `CURRENT_COMPLETED = S4-M6-A3-R2`.
- `CURRENT_NEXT = S4-M6-A3-R3` (`PLANNED / NOT_EXECUTED`).
- Do not mark or describe `S4-M6-A3-R3` as PASS until its evidence exists.
- Do not perform device actions during takeover validation.
- Preserve the dirty/untracked worktree.
- The canonical roadmap defines evidence precedence and future module order.
- Frozen evidence and newer applicable device evidence remain authoritative for
  their exact gates.

Use `docs/AI_TAKEOVER_PROMPT.md` when beginning from a new AI platform.
