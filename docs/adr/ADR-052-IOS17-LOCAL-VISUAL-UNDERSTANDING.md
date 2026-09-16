# ADR-052: Use Apple Vision Behind a Restricted Local Visual Session Contract

**Date:** 2026-08-24  
**Status:** Accepted for TEST-44.3 implementation  
**Decision type:** Runtime boundary and local OCR implementation

## Context

PhoneHarness needs to turn a user-requested visual input into a temporary,
privacy-safe semantic candidate. Existing iOS code already captures an image
in-process and recognizes text with `VNRecognizeTextRequest`, but its generic
MCP OCR endpoints return raw text, rectangles, and tap data for existing
observation use cases. That output cannot become the public interface for
personal language learning or visual intelligence.

## Decision

Reuse the existing local Apple Vision path and add a separate restricted
visual-session adapter. The adapter owns a short-lived analysis only and emits
an internal temporary observation followed by a stripped safe semantic
candidate. It is read-only and cannot reach Planner, Risk Controller, Executor,
or action MCP tools.

Use `VNRecognizeTextRequest` with `.accurate` as the default. Use explicit,
supported English and Simplified Chinese recognition languages. Analyze language
with bounded `NLLanguageRecognizer` hypotheses in a non-shared recognizer.

## Consequences

### Positive

- Runs locally on iOS 17 and preserves AX-first action policy.
- Reuses the installed Vision framework rather than adding an OCR dependency.
- Supports OCR confidence, orientation-aware temporary geometry, and explicit
  uncertainty without persisting raw visual data.
- Keeps TEST-43 semantic meaning and TEST-44.2 consent-based language learning
  as separate downstream responsibilities.

### Negative

- The first implementation is limited to Apple Vision's device behavior and
  needs an actual iPhone corpus gate before quality claims.
- Table structure and short abbreviations may be ambiguous. They must produce
  `NEEDS_CONFIRMATION`, not invented structure or meaning.
- A new internal transport path requires careful redacted logging and cleanup
  tests across normal and interrupted sessions.

## Alternatives Rejected

1. **Third-party Apple Vision wrapper:** rejected because it introduces another
   dependency without providing the required privacy/session contract.
2. **Cloud or VLM-first OCR:** rejected for privacy, network dependence, cost,
   and because it conflicts with the local-first requirement.
3. **Generic `ocr_screen` output as input to language intelligence:** rejected
   because generic raw OCR/rect/tap output is too broad and risks trace,
   memory, and action-boundary contamination.
4. **Vision coordinate execution:** rejected. TEST-44.3 is observation only;
   visual grounding can only be considered later after Planner, Risk, Executor,
   and Verifier authorization.

## PASS Impact

No current DEVICE_PASS is changed by this ADR. TEST-44.3 is `NOT_TESTED` until
the focused local iPhone gate completes. Build or package evidence alone is not
device evidence.
