# ADR-051: Personal Language Intelligence Foundation

## Decision

Adopt a private, user-confirmed personal language knowledge layer that consumes
only pre-filtered semantic language candidates. Reuse TEST-36 permission
decisions, TEST-37 lifecycle/forgetting, TEST-43 contextual semantic relations,
and TEST-44.1's future temporary visual-session boundary.

Do not add a standalone language-learning app, screenshot store, OCR adapter,
model provider, model router, second memory system, execution path, or
automatic workflow/skill creation in TEST-44.2.

## Context

PhoneHarness should learn terms encountered in the user's real work without
retaining the screen, conversation, OCR transcript, or coordinate data that
produced them. Domain ambiguity is material: `FT` can mean different things in
different contexts. A generic translation without verified domain context is
not reliable enough to become personal knowledge.

## Decision Details

1. Use `LanguageEncounterCandidate` as the narrow semantic ingress. It accepts
   only a normalized term, approved meaning, domain, opaque concept reference,
   confidence values, source type, and timestamp.
2. Use `LanguageContextResolver` to consult only existing TEST-43 validated
   contextual-meaning relations. Require both graph and candidate confidence of
   at least 800/1000. Return `NEEDS_CONFIRMATION` for low-confidence or
   conflicting results.
3. Require separate TEST-36 decisions: `READ` for graph context and
   `TRAIN_MEMORY` for confirmed language persistence. This retains default deny
   and prevents a write grant from becoming unrestricted contextual access.
4. Make `ADD` explicitly confirmed. Make `IGNORE` non-persistent. Keep
   `AUTO_LEARN_SIMILAR` as a future policy proposal only.
5. Store only user-approved language semantics and aggregate study state.
   Calculate priority deterministically from encounter frequency, confirmations,
   work relevance, difficulty, and mastery reduction.
6. Use TEST-37 logical forgetting and redact stored language semantics after a
   confirmed forget request. Keep an immutable, metadata-only audit.

## Alternatives Considered

### Persist screenshots and OCR as a study library

Rejected. It would turn sensitive visual/business content into durable learning
data and require materially broader encryption, discovery, sharing, retention,
and incident-recovery design.

### Send encountered text directly to a cloud model for translation

Rejected. It would expose private content unnecessarily, silently bypass local
knowledge and confirmed graph context, and introduce cost/network dependence.

### Adopt a complete spaced-repetition framework now

Rejected for now. FSRS and related scheduling approaches are useful references,
but no real PhoneHarness review history exists to fit or evaluate a model. A
bounded deterministic score is explainable and reversible until a later
evidence-backed scheduler phase.

### Use generic translation if no graph relationship exists

Rejected. It risks storing an incorrect context-specific meaning as a personal
fact. The correct behavior is `NEEDS_CONFIRMATION`.

## Consequences

### Positive

- Real user vocabulary can become privacy-bounded personal learning knowledge.
- Work-domain context may override a generic meaning only with validated
  evidence.
- Forgetting disables future retrieval and redacts this engine's semantic data.
- The implementation has no action or model authority and preserves existing
  Planner/Risk/Executor/Verifier boundaries.

### Trade-offs

- TEST-44.2 has no live visual ingestion or usable end-user learning screen.
- Candidate meaning must currently come from a later approved local adapter or
  user-confirmed source; it is not inferred by this engine.
- Priority is not a clinically tuned spaced-repetition schedule.

## Compatibility

- iPhone 15 Pro / iOS 17.0: no device API is called in this phase; actual
  OCR/language behavior needs a future device gate.
- RootHide + ElleKit: unchanged. This is Mac-side Python with no bootstrap,
  tweak, package, source, or system configuration change.
- Existing PASS history: TEST-36, TEST-37, TEST-43, and TEST-44.1 boundaries
  are consumed through their existing public contracts. All offline unit suites
  pass after the extension.

## Validation Classification

- `STATIC_PASS`: focused 9/9 language tests plus syntax compilation.
- `REGRESSION_PASS`: all 38 offline unit suites and 329 tests.
- `DEVICE_PASS`: `NOT TESTED`; no screenshot capture, OCR, local model, or
  device action is implemented.
- `FUNCTIONAL_FAILURE`: none observed.
- `ENVIRONMENT_ISSUE`: an existing repository bytecode-cache restriction was
  isolated with a temporary cache; no project or device configuration changed.
