# ADR-049: Local Semantic Capability Graph for TEST-43

- Status: Accepted and implemented for TEST-43.
- Date: 2026-08-23
- Decision: Add a bounded, local, advisory-only Cognitive Intelligence Layer.

## Context

PhoneHarness has governed knowledge, experience, capability, planning, risk,
execution, verification, and one verified native execution bridge.  Those
layers intentionally avoid inventing relationships or action paths.  Without a
small relationship layer, the runtime risks becoming a collection of isolated
commands and app-specific adapters.

TEST-43 must improve conceptual reuse and composition without changing the
existing authority chain:

```text
Goal -> Planner -> Risk Controller -> Executor -> Verifier
```

## Decision

Implement four local, data-only contracts:

1. `SemanticCapabilityGraph` accepts canonical concepts and explicit typed
   relationships with aggregate evidence only.  It can expand an accepted
   `is_a` hierarchy and discover capabilities linked to known concepts.
2. `CapabilityCompositionEngine` creates a non-executable ordered candidate
   set from already-registered, eligible capabilities.  Its output is an
   advisory for the existing Planner; it cannot produce a plan or tool call.
3. `SkillEvolutionAdvisor` turns an existing TEST-39 procedure-candidate
   handoff into a TEST-32 validation recommendation.  It cannot create,
   activate, or modify a Skill.
4. `ExperienceReinforcementAdvisor` exposes a bounded preference signal for a
   declared method, not an action decision and not an operation trace.

Only canonical metadata identifiers and aggregate evidence enter this layer.
Natural-language teaching, raw semantic entities, raw documents, user
messages, AX/OCR, screenshots, coordinates, URLs, tool arguments, and raw MCP
responses remain outside it.

## Evidence And Relationship Rules

- A relationship starts as `CANDIDATE`; only explicit confirmation or
  verifier-confirmed aggregate evidence can make it `VALIDATED`.
- `is_a` relationships are acyclic.  The graph refuses circular taxonomy
  claims instead of guessing.
- Conflicting same-subject / relation / domain / object claims remain
  `CONFLICTED` and are not used for expansion or discovery.
- A concept expansion includes only recorded, validated edges.  It does not
  infer siblings, hidden categories, or new facts.
- Revoked relationships remain auditable but are excluded from future answers.

## Authority Boundary

The graph, discovery, composition, evolution, and reinforcement contracts have
no MCP client, model client, Planner, Risk Controller, Executor, Verifier,
Shortcut, App Intent, or device transport.  A composition result always states
that the next gate is `Planner -> Risk Controller -> Executor -> Verifier`.
Permission eligibility is preserved as an input gate; a denied decision returns
`BLOCKED` before graph-derived advice is exposed.

## External Research Decision

Reviewed ideas:

- Graphiti / Zep demonstrate useful temporal relation and provenance concepts,
  but require graph-storage infrastructure and typically model-assisted
  ingestion.  Do not import them for this local, deterministic phase.
- LangGraph demonstrates durable state and human-in-the-loop checkpoints.
  PhoneHarness already owns its task/context lifecycle; importing a second
  runtime would duplicate state authority.
- Agent Skills specifications support portable declarative manifests.  Reuse
  the contract-and-lifecycle principle only; TEST-40.3 remains the existing
  Skill governance source of truth.
- Recent skill-composition research supports structural dependency-aware
  selection.  TEST-43 uses deterministic dependency ordering and does not use
  embeddings, an LLM reranker, or generative skill synthesis.

No ACP is required.  None of the reviewed projects is a compatible replacement
for the private, Mac-hosted, iOS 17 / RootHide-safe runtime.

## Consequences

TEST-43 will not claim generic reasoning, autonomous discovery, cloud-model
reasoning, or real-device execution.  It creates the bounded semantic contract
needed before those later phases can safely consume cognitive suggestions.

## Validation

- `STATIC_PASS`: focused TEST-43 unit coverage passed 8/8, including explicit
  taxonomy expansion, cycle/conflict rejection, discovery, dependency ordering,
  TEST-39 to TEST-32 handoff, permission denial, and privacy rejection.
- `REGRESSION_PASS`: all 36 offline `test-agent-*-unit.py` suites passed.
- `DEVICE_PASS: N/A`: the layer has no device action surface; no iPhone test is
  implied by these static results.
