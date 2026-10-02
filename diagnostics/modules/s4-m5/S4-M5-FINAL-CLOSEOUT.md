# S4-M5 Final Closeout

Status: **FROZEN_PROVEN**

Date: 2026-09-27

## Scope

S4-M5 freezes the typed File, Log, and Crash evidence foundation in
`phoneharness_diagnostics.py`. It composes the existing bounded device
providers (FileSystemManager, LogManager/mcp-logreader, CrashReporter
directories) into typed, privacy-safe evidence and preserves every frozen
owner: RiskController (sole authorization), S3-M1 (Artifact/Receipt/Trace
Store), S4-M0 (observation/freshness), S4-M1 (semantic UI), S4-M2
(perception), S4-M3 (region runtime), S4-M4 (clipboard/text/app/system
capabilities). No second authority, artifact store, trace store, freshness
runtime, collection runtime, shell, process/service runtime, package manager,
software manager, symbolication engine, or LLM root-cause engine was
introduced.

The B-stage made no production-symbol change and performed no device action.
It consolidates accepted A1/A2 Host evidence and A3/A3-R1 real-device
evidence without turning an unavailable proof into a pass.

## File Contract

- `FileResourceRef` binds provider, scope, lexically normalized absolute
  path, and provider-resolution status. The path is excluded from
  `repr`/`str`; safe diagnostics expose root alias, policy-gated basename,
  and path digest only.
- Path invariants: `PATH_STRING != authorization`; lexical normalization is
  not symlink safety and does not prove the provider target; traversal
  segments, control characters, oversized paths, and relative paths fail
  closed; `%2e%2e` is never decoded.
- `FileEvidence` is metadata-only (size/mtime/type/mode/encoding/truncation/
  content digest); it has no plaintext or base64 content field. Content is
  explicit bounded acquisition material (1 byte to 4 MiB typed bound) and is
  never auto-persisted.
- `evaluate_stable_file_read` classifies observed instability without
  claiming atomicity or global identity; equal size/mtime on another path is
  not the same file.
- `FileOperationKind` distinguishes LIST/READ_METADATA/READ_CONTENT
  (non-mutating) from CREATE/WRITE/APPEND/MOVE_OR_RENAME (mutating) and
  DELETE (destructive). Classification is never authorization; no
  read-to-write escalation surface exists.

## Log Contract

- `LogWindowSpec` hard-clamps seconds (≤ 60) and lines (≤ 5000); there is no
  unbounded stream or accumulation. `LogEntry.from_provider` normalizes real
  provider lines without exceptions and without fabricating timestamp, PID,
  severity, subsystem, or category; unknown stays UNKNOWN and partial stays
  PARTIAL.
- `redact_log_message` (A2-hardened) removes URL userinfo/query/fragment,
  secret assignments (password/passwd/passcode/otp/token/access_token/
  refresh_token/api_key/apikey/authorization/x-mcp-token, including
  two-token `Authorization: Basic <cred>` forms) and bearer tokens, with a
  2048-character bound. Provider `<private>` markers are preserved and never
  reconstructed.
- `LogWindowEvidence` binds typed entries to the spec, capture window,
  provider, provenance, and artifact references, with task-scope
  consistency.

## Crash Contract

- `parse_crash_report` supports modern iOS `.ips` structure: JSON header
  line plus multi-line JSON body. Scalar fields (including `procName`,
  `pid`, `incident_id`, `bundleID`, `os_version`) are merged across
  parseable forms, and `exception.type`/`exception.signal` are read from the
  body's exception object. Reports are bounded at 1 MiB with
  `acquisition_truncated` representation.
- `CrashIdentity` prefers the genuine incident/report UUID and otherwise
  composes report + metadata digests. Filenames, paths, timestamps, and
  process names are never sole identity. Conflicting incident identifiers
  are never silently merged; there is no merge or deduplication API.
- `IncidentType` classification is non-causal and uses only structured
  fields (exception type, signal, termination reason, process context,
  process). Module names, stack strings, filenames, and user text never
  determine the type; unknown evidence stays UNKNOWN. RootHide / Bootstrap /
  ElleKit / injection / tweak names are recorded as environment provenance
  only and never as causation.
- `CrashEvidence` safe diagnostics exclude the full raw report, sensitive
  paths, environment dumps, and credentials.

## Diagnostic Correlation Contract

`DiagnosticCorrelation` is bounded (window ≤ 24 h, reversed/negative/extreme
rejected), requires typed evidence, requires every claimed reason's
supporting field/window/references (TIME_WINDOW_MATCH, PROCESS_ID_MATCH,
BUNDLE_ID_MATCH, TRACE_REFERENCE_MATCH, OBSERVATION_REFERENCE_MATCH,
ARTIFACT_REFERENCE_MATCH), and is explicitly non-causal, non-authoritative,
and never an automatic root cause. A live log window that does not overlap
historical crash timestamps yields no correlation; that is an honest
NOT_APPLICABLE, not a failure.

## Real-Device Proof

Target: iPhone 15 Pro (iPhone16,1), iOS 17.0, RootHide Bootstrap 2.2.1,
ElleKit 1.2-1.

- A3 (USB channels): 50,941 real unified-log lines through the typed parser
  with 0 exceptions and 9,646/9,646 provider `<private>` markers preserved;
  7 real `.ips` reports parsed with 0 exceptions. Device testing exposed the
  modern `.ips` multi-line JSON gap; the accepted parser fix merges the
  header line, per-line JSON, and the remainder body document and reads
  `procName`/`pid`/`exception.type`/`exception.signal` where present.
- A3-R1 (canonical MCP path, after the approved user-assisted SSH auth
  handoff): authenticated initialize and tools/list (47 tools), path
  resolution including the RootHide root prefix (`/var/jb`, 21 entries) and
  the jbroot scheme exposed by `get_device_info`, bounded canonical read of
  a real crash report (4,934 bytes within a 65,536-byte bound), canonical
  `get_syslog` live-stream capture (3 s, 20 entries, truncated at the bound,
  20/20 typed, 0 exceptions), and the crash-directory query (7 `.ips`
  reports). The canonical read digest is byte-identical to the A3 USB
  extraction digest of the same report (cross-channel content identity for
  the canonical sample; not generalized into universal transport
  equivalence).
- The A3/R1 auth handoff recovered the existing device-local MCP token via
  approved user-assisted SSH without printing, logging, persisting, or
  committing it; the token was not rotated; the host secret file is 0600,
  outside the repository, and untracked. The MCP token is transport
  authentication only and is never agent authorization.
- Diagnostic correlation on-device was honestly NOT_APPLICABLE (the live
  window did not legitimately overlap historical crash timestamps); no
  correlation was fabricated.

## Ownership Boundaries

S4-M5 does not own and did not absorb: generic shell (S4-M7), process/service
intelligence (S4-M6), package/repository intelligence (S4-M8), software
manager (S4-M9), heavy symbolication (deferred to a later adapter), LLM
root-cause diagnosis, file/log/crash raw-content persistence, or a second
artifact/trace/freshness system. The legacy `read_crash_log` raw surface
remains a compatibility primitive and is never the governed proof path.

## Validation

- S4-M5 focused tests: **100/100 PASS** (76 A1 + 24 A2).
- S4-M4 compatibility: **51/51 PASS**; S4-M3: **50/50**; S4-M2: **45/45**;
  S4-M1: **49/49**; S4-M0: **38/38**.
- Complete offline Host regression: **116/116 files PASS**.
- Static/compile, diff, and frozen Stage-2/Stage-3/S4-M0..M4 integrity
  checks: **PASS** (all frozen modules byte-identical to their pins).
- Real-device proofs (A3 USB + A3-R1 canonical MCP): **PASS** as itemized
  above; real-device provider behavior for file, unified log, and crash
  paths proven on the accepted target environment.
- Blocking debt: **0**. Device environment blockers: **0**.
- Production device execution behavior changed: **NO**.

`S4_M5_STATUS = FROZEN_PROVEN`

The next legal module is `S4-M6 Process / Service`; it was not started by
this closeout.
