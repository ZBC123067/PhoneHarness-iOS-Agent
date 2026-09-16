# ADR-054: Add a Non-Executable Visual Intent Advisory

**Date:** 2026-08-24
**Status:** Accepted and implemented for TEST-44.4
**Decision type:** Visual intelligence integration boundary

## Context

TEST-44.3 can produce a privacy-safe semantic candidate from a temporary local
visual session. The runtime needs a way to offer useful help without treating
visual content as authority or allowing a screenshot path to bypass the
existing Planner, Risk Controller, Executor, and Verifier.

## Decision

Introduce `VisualIntentAdvisory` as a pure, in-memory, deterministic
component. It accepts an existing safe semantic candidate plus strictly
enumerated context, then returns confirmable suggestions only. The follow-up
handoff is declarative and always requires a fresh observation, planning, risk
check, execution, and verification.

`CANCEL` is only a user choice. High-impact operations are not valid visual
intent suggestions or handoffs.

## Consequences

Positive:

- Adds useful visual assistance without duplicating core runtime modules.
- Preserves temporary visual-data and Executor-only MCP boundaries.
- Keeps confidence honest until a labeled device corpus supports calibration.
- Provides a small sanitized fixture structure for later evaluation.

Negative:

- The first version needs a trusted semantic adapter to derive its enum-only
  context; it does not interpret raw screenshots itself.
- It offers suggestions only. A confirmed intent still requires the existing
  runtime and may be refused by later risk or permission checks.

## Alternatives Rejected

1. Direct OCR-to-action routing: rejected because OCR is untrusted content.
2. A screenshot-first GUI controller: rejected because it conflicts with
   AX-first observation and Executor-only action control.
3. Persisting visual context to improve recommendations: rejected for privacy
   and contamination risk.
4. Adding another Planner or Executor: rejected as duplicate authority.
