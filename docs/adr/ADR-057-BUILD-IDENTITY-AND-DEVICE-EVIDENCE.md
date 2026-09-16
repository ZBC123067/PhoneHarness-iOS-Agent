# ADR-057: Build Identity And Device Evidence

Status: Accepted, implemented, and focus-device validated on 2026-08-24.

## Context

Package version text alone cannot prove which source inputs, architecture, or
offline test baseline produced a RootHide `.deb`. Earlier package records also
left a generic `iphoneos-arm` declaration beside an `iphoneos-arm64e` artifact.
That ambiguity is unacceptable for future device evidence.

The project needs a local, privacy-safe chain that binds a package to its
source revision summary and test baseline, then independently binds a focused
device gate to that exact immutable package record. It must not collect source
contents, source paths, device identifiers, screenshots, UI/OCR data, user
data, or MCP responses.

## Research And Evaluation

1. Manual release notes: rejected. They are not mechanically bound to a
   package digest and are easy to drift.
2. GitHub artifact attestations: evaluated as a mature CI provenance reference.
   It provides issuer-backed artifact provenance and digest verification, but
   requires a hosted CI/identity workflow that is not part of the local Theos
   and RootHide build path.
3. SLSA or in-toto provenance: evaluated as the stronger future supply-chain
   option. It adds signer, builder, and deployment infrastructure beyond this
   project's current local build boundary.
4. Local standard-library identity and evidence records: selected. This adapts
   the useful concepts of a source digest, immutable package digest, explicit
   test baseline, and separate device evidence without adding a network
   dependency, a heavyweight framework, or a second runtime service.

No ACP is required. The selected approach improves local traceability now but
does not claim a signed or reproducible-build supply-chain attestation.

## Decision

Theos `after-stage` generates
`/usr/share/doc/ios-mcp/BUILD_IDENTITY.json` inside every package. It contains
only:

- a deterministic build identifier;
- UTC build time;
- package name, declared version, and declared architecture;
- Git commit and dirty/clean availability state;
- a SHA-256 summary of selected build inputs and its count;
- package scheme, Theos target, feature flags, and an unbound test baseline.

`scripts/build_identity.py finalize` then creates a separate immutable package
evidence record. It binds the staged identity to the final package name,
version, exact architecture, SHA-256 digest, byte size, and static/unit/
regression baselines. The finalizer fails closed when the package name,
version, or architecture differs from the staged identity. The package
architecture is explicitly `iphoneos-arm64e`; `iphoneos-arm` is no longer
accepted as an implicit substitute.

`device-bind` creates a separate device-evidence record. It copies the exact
package identity and offline baseline, records only a generic target profile
and safe evidence codes, and classifies the result as exactly one of
`DEVICE_PASS`, `FUNCTIONAL_FAILURE`, or `ENVIRONMENT_ISSUE`. It never mutates
the finalized package record.

## Validation Contract

The focused tests cover safe schemas, clean Git state, unsafe input rejection,
atomic output, package digest binding, strict Theos version derivation,
architecture mismatch rejection, private-data rejection, and device-result
classification consistency. Package audit must prove that the exact embedded
identity manifest exists.

## Current Build-Audit Evidence

- Build ID: `phb-2992805ce20a677ee83528f3`
- Package: `com.witchan.ios-mcp`
- Version: `1.2.2+ph1-7+debug-1+debug`
- Architecture: `iphoneos-arm64e`
- SHA-256: `234200c74fc33d0e88d8f6a453b930a6ce4daad3a4d97be4aa30f1f959e66cad`
- Size: `2,429,146` bytes
- Transfer: `TRANSFER_PASS` -- AFC upload to the real iPhone Documents root
  was read back byte-for-byte with the same SHA-256. This proves transfer only;
  it is not installation or device-runtime evidence.
- Static: 83 Python files passed syntax validation
- Focused P3 unit tests: 11/11 passed
- Offline regression: 43/43 suites passed in 16.27 seconds
- Device: `DEVICE_PASS` -- after the owner installed the exact package and
  restarted the device, a fixed, read-only manifest audit ran through the
  existing Risk Controller and PlanExecutor. Package name, declared arm64e
  architecture, build ID, source digest, feature flags, and the unbound
  target/test baseline all matched the finalized P3 record. No UI action,
  device configuration change, or raw manifest response was retained.
- Device evidence: `evidence/device/phoneharness-ph1-7-device-evidence.json`
  binds that focused result to the immutable package evidence without a device
  identifier or private device content.

## Non-Goals And Deferred Work

- No hosted CI, artifact signer, key management, or reproducible-build claim.
- No automatic transfer, installation, or device configuration change.
- No device identifier, screenshot, raw test result, visual content, user
  content, or raw MCP response in evidence.
- No claim of a signed supply-chain attestation or reproducible build. The
  device result proves only the focused P3 identity contract, not unrelated
  interactive device capabilities.
