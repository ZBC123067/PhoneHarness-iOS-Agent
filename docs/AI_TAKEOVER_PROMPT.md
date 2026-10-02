# PhoneHarness Model-Agnostic Takeover Prompt

Copy the text below into any capable AI coding platform that has local
filesystem and repository access.

---

You are taking over the PhoneHarness project with zero prior conversation
context.

Repository:

the current PhoneHarness repository checkout

First read:

1. `docs/AI_START_HERE.md`
2. `docs/MASTER_HANDOFF.md`
3. `docs/AI_PROJECT_RULES.md`
4. `docs/TEST_STATUS_MATRIX.md`
5. `docs/ROADMAP.md`

Then inspect the actual repository and current Git worktree. Repository code,
TEST/ADR/device evidence, and fresh applicable results override model
assumptions or any old conversation.

Do not start development yet. Perform takeover validation only.

Do not:

- clean, reset, restore, checkout over, stash, or delete existing work;
- convert `BLOCKED`, `NOT_TESTED`, or `ENVIRONMENT_ISSUE` into PASS;
- run builds, tests, device actions, WDA, XCTest, MCP actions, or AX mutation;
- start the Foundation Stabilization Audit or TEST-60;
- change RootHide, Bootstrap, package sources, signing, or device configuration.

Report:

```text
TAKEOVER_VALIDATION: READY / NOT_READY

CURRENT_HEAD:
BRANCH_OR_DETACHED:
WORKTREE_STATE:

LATEST_COMPLETED_GATE:
TEST51_STATUS:
TEST52_STATUS:

CURRENT_MAINLINE:
IMMEDIATE_NEXT_TASK:

DEVICE_ACTION_COUNT: 0

CONFLICTS:
MISSING_FILES:
STALE_REFERENCES:
BLOCKERS:
```

Expected current baseline, to be verified rather than assumed:

- latest completed gate: TEST-59 `HOST_PASS`;
- latest PhoneHarness process/service completion: `S4-M6-A3-R2`;
- next process/service gate: `S4-M6-A3-R3` (`PLANNED / NOT_EXECUTED`);
- TEST-51 device action Gate: `BLOCKED`;
- TEST-52: `NOT_PASS` / `FAIL_CLOSED`;
- Foundation Stabilization Audit: `NOT_STARTED`;
- TEST-60: `PLANNED / NOT_STARTED`.

Wait for explicit user instruction before development.

---
