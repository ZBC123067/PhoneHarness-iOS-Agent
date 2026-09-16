# Security Model

## Threat model

PhoneHarness is a privileged agent on a jailbroken device. Assume the network,
the planner's inputs, and any learned memory may be hostile or wrong.

## Controls

| Control | Behaviour |
|---|---|
| Authentication | every device MCP endpoint requires `X-MCP-Token`; constant-time compare; no exempt endpoint; fail closed |
| Token handling | host reads `PHONEHARNESS_MCP_TOKEN` from the environment; never hardcoded; never logged |
| Token origin | generated on device from the OS CSPRNG; stored in protected preferences (0600) |
| Network exposure | loopback by default; LAN off unless explicitly enabled |
| Authorization | `PlanValidator` + `RiskController` decide admissibility, independent of the planner |
| Least privilege | capability binding selects the narrowest provider for the intent |
| Verification | every action is observed and verified before it is treated as complete |
| Auditability | append-only ledger records action, evidence, and verdict |

## Trust boundaries

1. **User intent → Planner.** Untrusted input shapes a proposal only.
2. **Planner → Validator/Risk.** The plan is data; it is checked, not trusted.
3. **Runtime → Device.** The device is the blast radius; every privileged step is
   gated and logged.
4. **Memory/Skills → Runtime.** Read-only for planning; never authorizing.

## Non-goals

PhoneHarness is not a sandbox for untrusted third-party code, and it does not
protect against a compromised device or a malicious jailbreak environment.
