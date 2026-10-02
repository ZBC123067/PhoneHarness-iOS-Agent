# S4-M5 Frozen Source Recovery Artifact

Status: `RECOVERY_ARTIFACT_ONLY`

- `RECOVERY_ARTIFACT_ONLY = YES`
- `PRODUCTION_SOURCE = NO`
- `HISTORICAL_FREEZE_REDEFINED = NO`

The byte-exact S4-M5 production source was recovered on 2026-09-30 from a
complete ZCode session read plus the recorded deterministic source
transformations. Its SHA256 matches the existing S4-M5 frozen manifest. This
directory preserves a durable recovery copy; production continues to import
the repository-root `phoneharness_diagnostics.py`.

This artifact does not amend, replace, or rebaseline the historical S4-M5
freeze evidence.
