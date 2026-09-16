# ADR-065: Modernize TEST-25 Search with Governed Step Obligations

Date: 2026-08-26

## Status

Accepted on host evidence. Focused device action Gate not run because the
fresh preflight did not expose one eligible editable search field.

## Context

TEST-25 proved a narrow semantic search prototype, but it bundled focus,
input, and submit into one plan and could treat query presence as completion.
That predates Rich Context, TEST-45 Action Obligations, TEST-46 recovery, and
TEST-47 method health. Replacing the Planner, Executor, Context system, or
Capability Registry would duplicate established authority.

## Decision

Retain the existing search capability and modernize its execution governance.
A process-local `SemanticSearchTransactionStore` binds one trusted query and
one fresh, unique AX field to the current task, context, observation version,
and page fingerprint. It exposes only an opaque transaction reference.

The existing task boundary executes three independent plans and TEST-45
obligations:

```text
FOCUS -> observe and verify focus
INPUT -> observe and verify query entry
SUBMIT -> fresh observation and verify submission
```

Each step passes through the existing Planner, Risk Controller, PlanExecutor,
Action Obligation Ledger, and Verifier. Query entry and search submission are
separate verification levels. TEST-46 continuation performs fresh observation
and never replays focus, input, or submit. TEST-47 receives only attributable
outcomes for dispatched methods.

## Consequences

- AX is the only action-authoritative field source; OCR and Vision remain
  untrusted candidate evidence.
- Explicit current user input or one unique trusted Rich Context resolution is
  required for query authority.
- Ambiguous, stale, hidden, disabled, non-editable, cross-task, expired, or
  consumed bindings fail closed before action.
- A possible submit side effect without confirmation becomes
  `UNKNOWN_SIDE_EFFECT`; it is not retried automatically.
- Query presence proves only `QUERY_ENTRY_VERIFIED`. Final success requires a
  dispatched submit plus fresh result-consistent evidence and yields
  `SEARCH_SUBMISSION_VERIFIED`.
- The private transaction is process-local and short-lived. Query, selector,
  page contents, OCR, screenshots, coordinates, and replay parameters are not
  persisted.

## Alternatives Rejected

1. Keep the TEST-25 bundled plan: cannot represent step-level side-effect
   reality and permits weak completion evidence.
2. Add a Search Agent or Search Executor: duplicates Planner and Executor.
3. Authorize OCR/Vision fields: allows untrusted content to drive actions.
4. Retry Enter after response loss: may duplicate a real submission.
5. Persist the query or element selector: creates unnecessary search history
   and replay authority.
