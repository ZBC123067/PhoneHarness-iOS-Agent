# ADR-066: Preserve Strict AX Field Authority During TEST-52 Diagnosis

Date: 2026-08-27

## Status

Accepted diagnostic decision. TEST-52 device Gate currently fails.

## Context

TEST-51 requires one fresh semantic editable field with direct same-leaf AX/XC
evidence before focus, input, or submit may be authorized. The current iPhone
Gate reached the MCP service but exposed no direct state evidence for Safari's
opened search/address field.

## Decision

Keep the existing eligibility and verifier contracts unchanged. Diagnose the
current response using only aggregate role/state/provenance metadata. Do not
authorize legacy labels, generic controls, inferred visibility, OCR, Vision,
coordinates, or clickability as substitutes for direct editable-field evidence.

## Consequences

- TEST-52 remains `FAIL` until a fresh real-device observation satisfies the
  existing contract.
- TEST-51 remains host-complete with its device Gate `NOT_TESTED`.
- No focus, input, submit, retry, or recovery action may be performed from the
  failed TEST-52 observation.
- Any later fix must be minimal, retain privacy boundaries, pass focused host
  tests, and receive one fresh device Gate.
