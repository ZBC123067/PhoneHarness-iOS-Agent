# Contributing

Thanks for your interest in PhoneHarness.

## Where to talk

- **Bugs and feature requests:** open a GitHub Issue on this repository.
- **Security problems:** use GitHub Security Advisories (private report), never a
  public issue. See `SECURITY.md`.

## Ground rules

- Keep the architectural invariants intact (see `README.md`). A planner must never
  authorize itself; memory/skills must never widen what is permitted.
- New privileged behaviour must go through the existing boundary chain
  (Validator → RiskController → Capability Binding → Provider → Executor →
  Observation → Verifier → Ledger). Do not add side doors.
- Prefer explicit, auditable code over implicit magic.

## Development

Host runtime and tests are Python 3 (standard library only):

```bash
python3 run_all_tests.py     # offline unit suite, no device required; must be green
```

The device runtime builds with Theos (see `Makefile`). Helper tools require
external third-party sources that are not vendored here — see `DEPENDENCIES.md`.

## Pull requests

- One logical change per PR.
- Add or update tests; the offline unit suite must stay green.
- Do not include device evidence, personal paths, credentials, build output, or
  third-party source you may not redistribute.
- Describe which boundary the change touches and why.

## Licensing of contributions

Contributions are accepted under the Apache License 2.0 (see `LICENSE`), covering
project-owned code only. Do not contribute code you cannot license accordingly,
and do not add third-party code under an incompatible license.
