# Security Policy

## Reporting a vulnerability

Report suspected vulnerabilities through this repository's **GitHub Security
Advisories** ("Report a vulnerability" on the Security tab). Please do not open a
public issue for a security problem.

Include: a description, the affected component (host runtime or device runtime),
reproduction steps, and impact. If you are unsure whether something is a
vulnerability, report it privately anyway.

## Design posture

PhoneHarness executes privileged actions on a real device. Its security posture
is deliberately conservative:

- **Fail closed.** Authentication and authorization failures deny the action.
- **Token-authenticated MCP surface.** Every device MCP endpoint requires the
  `X-MCP-Token` header, compared in constant time. A missing or wrong token is
  rejected. There is no exempt endpoint.
- **Host-supplied token only.** The host reads the token from the
  `PHONEHARNESS_MCP_TOKEN` environment variable. Tokens are never hardcoded and
  never written to logs.
- **Loopback by default.** The device server binds to loopback; LAN exposure is
  off unless explicitly enabled.
- **Device-generated tokens.** On install, the device generates its own token from
  the OS CSPRNG and stores it in protected preferences (mode 0600).
- **Defence in depth.** Auth sits in front of the planner's own Validator /
  RiskController layers; neither replaces the other.

## Scope

In scope: the host runtime and the device runtime in this repository. Out of
scope: third-party components not vendored here (see `DEPENDENCIES.md`) and
jailbreak tooling itself.

## Do not

Do not run this against devices or accounts you do not own or are explicitly
authorized to automate.
