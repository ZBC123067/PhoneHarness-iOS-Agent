# Architecture

PhoneHarness is a governed privileged agent runtime for a real iOS device.

## Pipeline

```
          proposal                    admissibility          execution
Goal ──▶ Planner ──▶ PlanValidator ──▶ TaskCoordinator ──▶ RiskController
                                                              │
                                                              ▼
                            GovernedCapabilityBindingRuntime ──▶ Provider
                                                              │
                                                              ▼
                                                          Executor
                                                              │
                                                              ▼
                              Ledger ◀── Verifier ◀── Observation
```

## Stage responsibilities

| Stage | Responsibility | Can refuse? |
|---|---|---|
| Goal | what the user asked for | — |
| Planner | proposes a plan from context | yes (no plan) |
| PlanValidator | checks plan shape/admissibility before anything runs | yes |
| TaskCoordinator | sequences tasks, owns lifecycle and recovery | yes |
| RiskController | classifies risk, gates the action | yes |
| Capability Binding | binds a capability to a concrete provider | yes |
| Provider | performs the tool call against the device | yes |
| Executor | drives the provider call | yes |
| Observation | captures structured evidence of what happened | — |
| Verifier | checks the observation against the intent | yes |
| Ledger | append-only record of the action and its verdict | — |

## Boundaries that are load-bearing

- **Planner != Authorization.** The planner is creative; it is never authoritative.
  Admissibility is decided by `PlanValidator` and `RiskController`, which do not
  trust the planner's confidence.
- **Capability != Provider.** A capability is a contract; a provider is an
  implementation. The binding step is explicit, governed, and auditable.
- **Executor success != Semantic success.** A tool can return `ok` while the
  intended outcome did not happen. Only the Verifier may declare success.
- **Memory / Skills are never authorization authority.** Persisted knowledge and
  learned skills can shape a plan; they can never expand permissions.

## Recovery

Actions carry obligation/ledger state so an interrupted run can be recovered
without double-executing privileged steps: restart-safe recovery, ownership
fencing, and retention/reconciliation rules. Memory of an action is not
authorization to repeat it.
