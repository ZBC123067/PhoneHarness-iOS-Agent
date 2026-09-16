# Roadmap

## v0.1.0 — source-only public staging (current)

- Governed host runtime + device runtime published as project-owned source.
- Offline host unit suite green; no device evidence in-tree.
- Root license pending review (recommendation: Apache-2.0).

## Next

- Re-derive the private-evidence-bound regression tests (18) using synthetic
  public fixtures, so the public suite covers the same runtime behaviour without
  depending on private device diagnostic/evidence artifacts.
- Finalise root license and add `LICENSE`.
- CI that runs the offline host unit suite on every pull request.
- Expand `postman/` and `testdata/` with device-free, runnable demonstrations.
- Tighten and document the public API surface of the host runtime.
- Optional: re-introduce helper tools behind documented external dependencies
  without vendoring copyleft sources.

## Explicitly out of scope

- Vendoring AGPL/GPL source into the tree.
- Shipping device evidence, credentials, or captured logs.
