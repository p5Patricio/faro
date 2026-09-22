# Apply Progress: financial-intelligence-expansion

## Batch 1 — Phase 1: Foundation (Migration + Repository + Schema Check)

**Mode**: Standard (no `strict_tdd` config found; `openspec/config.yaml` not present in
this checkout — proceeded in standard workflow: read spec/design, write code, verify with
real-DB round-trip tests).

### Completed Tasks

- [x] 1.1 `db/migrations/0005_shared_ingestion.sql` — DDL copied verbatim from design.md:
  `asset_identifiers` (unique `(asset_id, id_type)`, non-unique `(id_type, id_value)` lookup
  index) and `ingestion_runs` (append-only, `source`/`endpoint`/`started_at` index, partial
  `status <> 'success'` failure index).
- [x] 1.2 `collector/local_repository.py` — added `# -- Asset identifiers / ingestion audit --`
  section (before `# -- Schema introspection --`) with `upsert_asset_identifiers`,
  `get_asset_identifiers`, `resolve_asset_by_identifier`, `insert_ingestion_run`,
  `get_recent_ingestion_runs` — exact signatures from design.md, `_upsert_batch(...,
  ("asset_id", "id_type"))`, `Jsonb(_json_safe(...))` for jsonb columns.
- [x] 1.3 `collector/schema_check.py` — added `"asset_identifiers"` and `"ingestion_runs"` to
  `REQUIRED_ML_RELATIONS`.
- [x] 1.4 `tests/test_local_repository.py` — 6 new tests: upsert idempotency for
  `asset_identifiers`, `resolve_asset_by_identifier` round-trip + not-found case,
  `insert_ingestion_run` success row, `insert_ingestion_run` failure row with error detail +
  metadata, `get_recent_ingestion_runs` filter-by-source + `started_at desc` ordering.
- [x] 1.5 Migration applied and schema verified against both live databases (see Runtime
  Harness evidence below).

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `db/migrations/0005_shared_ingestion.sql` | Created | `asset_identifiers` + `ingestion_runs` tables, both indexes, verbatim from design.md |
| `collector/local_repository.py` | Modified | Added 5 methods in new `# -- Asset identifiers / ingestion audit --` section |
| `collector/schema_check.py` | Modified | Added `asset_identifiers`, `ingestion_runs` to `REQUIRED_ML_RELATIONS` |
| `tests/test_local_repository.py` | Modified | Added 6 real-DB round-trip tests for the new methods |
| `openspec/changes/financial-intelligence-expansion/tasks.md` | Modified | Marked Phase 1 tasks 1.1-1.5 `[x]` |

### Deviations from Design

None — implementation matches design.md's verbatim DDL and method signatures exactly.

### Issues Found

None.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_local_repository.py tests/test_schema_check.py -q` → `39 passed` |
| Runtime harness command/scenario and exact result | `py -3.14 -m db.migrate` (with `LOCAL_DATABASE_URL` set to `ia_inversiones`, then to `ia_inversiones_test`) → both `Applied migrations: 0005_shared_ingestion.sql`; `py -3.14 -m collector.schema_check` against both DSNs → all 14 relations `OK`, including `asset_identifiers` and `ingestion_runs` |
| Rollback boundary | Drop `ingestion_runs` then `asset_identifiers`, delete the `0005` row from `schema_migrations` on both databases; revert `local_repository.py` (5 new methods) and `schema_check.py` (2 relation entries); delete the 6 new test functions from `tests/test_local_repository.py` |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported):
- Before this batch: **243 passed**
- After this batch: **249 passed** (243 + 6 new tests, 0 regressions)

### Remaining Tasks

- [ ] Phase 2: S&P 100 Universe Snapshot (task 2.1 already verified by orchestrator;
  2.2-2.9 pending)
- [ ] Phase 3: Bounded Retraining-Target Policy + Global-Scope Cap
- [ ] Phase 4: SEC EDGAR Client (concurrent sibling agent scope)
- [ ] Phase 5: Ingestion Audit Recorder + Identifier Resolution Job
- [ ] Phase 6: Asset-Class Feature-Set Resolution Seam
- [ ] Phase 7: API Endpoint + Rollout Confirmation

### Workload / PR Boundary

- Mode: chained PR slice (`stacked-to-main`)
- Current work unit: PR 1 — `db/migrations/0005_shared_ingestion.sql` + 5
  `LocalPostgresRepository` methods + `collector/schema_check.py` relations
- Boundary: this batch starts from an unmigrated `0005` slot (0004 → 0007 already applied)
  and ends with both live databases migrated, schema-verified, and the new repository
  surface fully tested. No Phase 2-7 files touched.
- Estimated review budget impact: within the ~300-380 estimated line budget for PR 1
  (Medium risk); well under the 400-line threshold.

### Status

5/5 Phase 1 tasks complete. No blockers. Ready for `sdd-apply` to continue with the next
batch (Phase 2 or whichever phase the orchestrator assigns next), or `sdd-verify` if Phase 1
is being verified as its own PR slice before further phases proceed.

## Batch 2 — Phase 4: SEC EDGAR Client

**Mode**: Standard (no `strict_tdd` config found; `openspec/config.yaml` not present in this
checkout — proceeded in standard workflow: read spec/design, write code + tests together,
verify with the focused suite then the full suite).

Ran concurrently with (and lands after) Batch 1 — Phase 1. No file overlap: this batch only
touches `collector/providers/sec_edgar_client.py` (new) and `tests/test_sec_edgar_client.py`
(new). `collector/providers/registry.py` and `collector/providers/__init__.py` were left
untouched, per design's explicit "not registered in `PROVIDERS`" instruction.

### Completed Tasks

- [x] 4.1 `collector/providers/sec_edgar_client.py` (new) — `SecEdgarConfig` frozen dataclass
  with `from_env()` reading `SEC_USER_AGENT` (blank/unset → `None`, never a fabricated
  default); `SecEdgarConfigError(RuntimeError)`; `IngestionRun` frozen dataclass (exact
  fields from design.md); `IngestionRunRecorder` `Protocol` with `record(run)`; `pad_cik`;
  `SecEdgarClient` dataclass with injectable `session=requests`, `sleep=time.sleep`,
  `monotonic=time.monotonic`, `recorder=None`, `min_interval=0.11`; `fetch_company_tickers`
  (`SEC_WWW_BASE/files/company_tickers.json`, `target_key=""`), `fetch_company_facts(cik)`
  and `fetch_submissions(cik)` (both padded-CIK `SEC_DATA_BASE` endpoints). Not registered
  in `collector/providers/registry.py`'s `PROVIDERS` — it does not satisfy `PriceProvider`
  (no `fetch_prices`).
- [x] 4.2 Two-tier failure contract implemented exactly as specified: `config is None` raises
  `SecEdgarConfigError` before any socket opens (checked first thing inside the shared
  `_request` helper, before the throttle/request loop even starts); every transport failure
  (network exception, 403, 429-exhausted, 5xx-exhausted, invalid JSON) returns
  `{"ok": False, "reason": ..., "detail": ...}` with `reason` in the exact 5-value enum from
  design.md; success returns `{"ok": True, "payload": ..., "status_code": 200}` with the
  provider JSON passed through completely unmodified (proven by
  `test_success_returns_provider_payload_unmodified`, which round-trips a nested XBRL-shaped
  fixture with a `filed` field and asserts byte-for-byte equality).
- [x] 4.3 Throttle implemented in `_throttle()`: computes `wait = max(0, min_interval -
  elapsed)` from the injected `monotonic`, sleeps via the injected `sleep` only when
  `wait > 0`, called once per request attempt (including retries) so pacing holds across
  429/5xx backoff loops too. 429 responses honor `Retry-After` (parsed as float, default
  `1.0` on a missing/malformed header) and retry up to `MAX_RETRIES=3` (4 total attempts
  before giving up, mirroring `ops/telegram_notifier.py`'s exact `attempt >= max_retries`
  pattern); `metadata["failure_kind"] = "rate_limited"` is set the first time a 429 is seen
  and persists through to whatever the eventual recorded outcome is (success-after-retry or
  exhausted-failure) — proven by `test_429_honors_retry_after_then_succeeds`, which asserts
  a `status="success"` `IngestionRun` still carries `metadata == {"failure_kind":
  "rate_limited"}`.
- [x] 4.4 Every one of the three fetch methods routes through the shared `_request` helper's
  `try/finally`, so exactly one `IngestionRun` is recorded per method call on every exit
  path — including the `SecEdgarConfigError` path (`request_count=0`, `status="failure"`,
  `error="missing_sec_user_agent"`) when a `recorder` is attached, and skipped cleanly when
  no `recorder` is attached (`test_no_recorder_attached_does_not_raise`). Redaction: `error`
  and `detail` values are built from a shared `_redact()`/`_response_detail()` pair that
  strips the exact configured `SEC_USER_AGENT` string (replacing it with `"***"`) before it
  is placed into any returned dict or `IngestionRun` field — asserted explicitly across 5
  dedicated tests (client-error detail, server-error detail, network-error detail, the
  recorded `IngestionRun`, and a sweep across every failure case + the config-error path),
  not just by code review.
- [x] 4.5 `fetch_company_tickers` issues exactly one request to the bulk
  `company_tickers.json` file (`target_key=""` per the DDL comment "'' for universe-wide
  fetches") — no per-CIK loop exists in this client. `fetch_dera_dataset` was deliberately
  **not** implemented — left as the named, unbuilt seam the `fundamental-analysis` sibling
  owns, per the task's explicit instruction.
- [x] 4.6 `tests/test_sec_edgar_client.py` — `FakeSession`/`FakeResponse` extend the
  `tests/test_collector_providers.py:23` pattern with `headers` capture (`FakeSession.get`
  records `{"url", "headers", "timeout"}` per call) and a `status_code`/`json_error`-capable
  `FakeResponse`. Covers success, 403 (`sec_client_error`), 429 (both recovers-after-backoff
  and exhausts-to-`sec_rate_limited`), 5xx (both recovers and exhausts to
  `sec_server_error`), bad-JSON (`sec_invalid_json`), and a network-exception path
  (`sec_request_failed`, via a small `RaisingSession` that raises `requests.ConnectionError`
  before any response exists). `test_every_request_sends_configured_user_agent` asserts the
  literal `User-Agent` header value on every captured request.
- [x] 4.7 `test_throttle_waits_the_remaining_gap_to_min_interval` and
  `test_throttle_skips_wait_when_elapsed_exceeds_min_interval` inject a scripted `monotonic`
  (an `iter([...])` consumed one value per throttle call) and a list-recording `sleep`
  (`sleeps.append`, never `time.sleep`) — zero real wall-clock time in the whole suite (0.60s
  for all 35 tests in this file). Asserts the exact computed wait
  (`pytest.approx(min_interval - elapsed)`) and that no sleep is issued once elapsed already
  exceeds `min_interval`.
- [x] 4.8 `FakeRecorder` (a plain `IngestionRunRecorder` collecting a list) is used across
  `test_recorder_gets_one_run_per_method_call_on_success`,
  `test_recorder_gets_one_run_with_target_key_for_facts`,
  `test_recorder_gets_exactly_one_failure_run_per_reason` (parametrized over 403/bad-JSON),
  `test_recorder_gets_one_run_for_a_network_failure`, `test_429_honors_retry_after_then_succeeds`,
  and `test_429_exhausts_retries_and_returns_rate_limited` — each asserts `len(recorder.runs)
  == 1` per method call regardless of how many HTTP attempts/retries happened underneath.
- [x] 4.9 `test_missing_user_agent_raises_before_any_request` uses a real (non-monkeypatched)
  `config=None` `SecEdgarClient` plus `test_from_env_returns_none_when_unset` (which does use
  `monkeypatch.delenv("SEC_USER_AGENT", raising=False)`) to prove `from_env() is None`
  separately; the raise-and-zero-requests assertion is `pytest.raises(SecEdgarConfigError)`
  plus `session.requests == []`, confirmed for all three fetch methods in
  `test_missing_user_agent_raises_for_every_fetch_method`.
- [x] 4.10 `test_user_agent_never_leaks_into_client_error_detail`,
  `..._server_error_detail`, `..._network_error_detail`, `..._recorded_ingestion_run`, and
  `test_user_agent_never_leaks_across_every_failure_case_and_config_error` each construct a
  fake response/exception whose body **echoes the real configured `SEC_USER_AGENT` value
  back** (simulating a verbose error page or an exception message that embeds request
  context) and assert the raw value never appears in the returned dict, the `detail` string,
  the recorded `IngestionRun.error`, or `IngestionRun.metadata` — proving `_redact()` runs,
  not just that the fixture happened not to contain the secret.

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `collector/providers/sec_edgar_client.py` | Created | Throttled, two-tier-failure, audited SEC EDGAR client; not registered in `registry.PROVIDERS` |
| `tests/test_sec_edgar_client.py` | Created | 31 test functions / 35 collected cases covering success, every failure reason, throttle, 429/5xx backoff, `ingestion_runs` recording on every exit path, missing-User-Agent raise, and redaction |
| `openspec/changes/financial-intelligence-expansion/tasks.md` | Modified | Marked Phase 4 tasks 4.1-4.10 `[x]` |

### Deviations from Design

None on the public contract. One implementation-detail decision not fully spelled out in
design.md: the `IngestionRun.error` field is populated as `f"{reason}: {redacted_detail}"`
(e.g. `"sec_client_error: Forbidden"`) rather than the bare reason code, since the DDL's
`error text` column (with its comment "never contains SEC_USER_AGENT") is the only free-form
diagnostic text persisted to `ingestion_runs` — the `reason` enum itself has no dedicated DB
column, so folding it into `error` keeps the audit trail queryable without losing information.
`rows_written` is set to `1` for every successful fetch (one JSON document fetched per logical
call) rather than attempting to count nested entries inside SEC's heterogeneous payload
shapes (`company_tickers.json` is a flat index-keyed dict, `companyfacts`/`submissions` are
deeply nested) — design.md does not specify a `rows_written` computation, and a wrong guess at
"count of what" would be worse than an honest per-fetch unit. Both are transport-layer choices
that do not change the two-tier contract, throttle behavior, or redaction guarantee; noted here
for the reviewer, not hidden.

### Issues Found

None.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_sec_edgar_client.py -q` → `35 passed in 0.60s` |
| Runtime harness command/scenario and exact result | N/A per design.md: "No test may reach the real SEC API." This client makes zero real network calls in any test — every `session`/`sleep`/`monotonic` is injected. (The design's suggested manual operator smoke test against real `data.sec.gov` was not run in this batch; it is explicitly optional and requires a real `SEC_USER_AGENT`.) |
| Rollback boundary | Delete `collector/providers/sec_edgar_client.py` and `tests/test_sec_edgar_client.py`; the client is not registered in `registry.PROVIDERS` and not yet called by anything, so no other file needs to change |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported):
- Baseline measured at the start of this batch (before Batch 1 — Phase 1 landed): **243 passed**
- Batch 1 — Phase 1 landed concurrently mid-session (commit `76259dc`), adding 6 tests: **249 passed**
- After this batch (243 baseline + 6 from Batch 1 + 35 from this batch, 0 regressions): **284 passed**

### Remaining Tasks

- [ ] Phase 2: S&P 100 Universe Snapshot (task 2.1 already verified by orchestrator;
  2.2-2.9 pending)
- [ ] Phase 3: Bounded Retraining-Target Policy + Global-Scope Cap
- [ ] Phase 5: Ingestion Audit Recorder + Identifier Resolution Job (depends on this batch's
  client and Batch 1's repository methods — both now available)
- [ ] Phase 6: Asset-Class Feature-Set Resolution Seam
- [ ] Phase 7: API Endpoint + Rollout Confirmation

### Workload / PR Boundary

- Mode: chained PR slice (`stacked-to-main`)
- Current work unit: PR 4 — `collector/providers/sec_edgar_client.py` (independent of PR 1-3)
- Boundary: this batch starts from no SEC client existing at all and ends with a fully
  tested, inert (uncalled, unregistered) client ready for Phase 5 to wire up.
- Estimated review budget impact: **exceeds the forecast** — actual is 249 + 521 = 770 raw
  added lines (both files 100% new, no generated content to exclude), well over the
  ~350-420 estimate for PR 4 (already flagged High risk in the forecast table). The excess
  is almost entirely test code (521 lines across 31 test functions / 35 cases) covering
  every reason in the 5-value failure enum, both retry-recovery and retry-exhaustion for
  429/5xx, throttle precision, and 5 dedicated redaction proofs (task 4.10 explicitly
  requires proving redaction "not just by code review"). Flagging this honestly rather than
  under-reporting; still a single, autonomous, independently revertible unit with no
  cross-file coupling — the orchestrator/reviewer may want to split source vs. test into two
  reviewable commits within this one PR, or accept as `size:exception` given the file is
  wholly new and additive.

### Status

10/10 Phase 4 tasks complete. No blockers. Ready for `sdd-apply` to continue with Phase 5
(now unblocked, since both its dependencies — this client and Batch 1's repository methods —
are in place) or any other pending phase, or `sdd-verify` if PR 4 is being verified as its
own slice before further phases proceed.

## Batch 3 — Phase 5: Ingestion Audit Recorder + Identifier Resolution Job

**Mode**: Standard (no `strict_tdd` config found; `openspec/config.yaml` not present in this
checkout — proceeded in standard workflow: read spec/design/landed Phase 1 + Phase 4
interfaces, wrote code + tests together, verified with the focused suite then the full
suite).

Ran while sibling agents landed Phase 2, Phase 3, and Phase 6 concurrently in the same
tree. No file overlap: this batch only touches `collector/ingestion_audit.py` (new),
`collector/run_identifier_resolution.py` (new), and an appended section in
`tests/test_sec_edgar_client.py` (Phase 4's existing 35 tests/43 collected cases were read in
full first and left untouched). By the time this batch ran, Phase 2's `collector/universe.py`
and `config/universe.sp100.json` had already landed, so `run_identifier_resolution.py`'s CLI
wrapper wires directly to `collector.universe.load_universe_document`.

### Completed Tasks

- [x] 5.1 `collector/ingestion_audit.py` (new) — `RepositoryIngestionRecorder(repository)`
  (a dataclass with one field, giving the exact positional-constructor shape design.md
  specifies), implementing `IngestionRunRecorder` via a `record(run)` method that maps every
  one of `IngestionRun`'s 12 fields 1:1 into `repository.insert_ingestion_run(...)` kwargs.
  `IngestionRun` carries no `max_filed_date` field, so that repository parameter is left at
  its own default (`None`) on every call — noted in the module docstring, not silently
  dropped.
- [x] 5.2 `collector/run_identifier_resolution.py` (new) — core function
  `run_identifier_resolution(repository, client, tickers)` fetches `company_tickers.json`
  **exactly once** regardless of ticker count (proven by
  `test_fetch_company_tickers_called_exactly_once_regardless_of_ticker_count`), builds a
  ticker→CIK lookup from the real payload shape (`{"0": {"cik_str": ..., "ticker": ...}}`),
  and for every match calls `repository.get_or_create_asset(ticker)` (never
  `get_asset_id`, so a not-yet-tracked ticker never spuriously counts as "unresolved" — only
  "no company_tickers.json match" does, matching the spec's own scenario wording) then
  `repository.upsert_asset_identifiers(rows)` in one batched call. Returns
  `{"resolved": [...], "unresolved": [...]}` (both plain ticker-string lists). Unresolved
  tickers are (a) printed via `print(...)` and (b) written into a dedicated
  `ingestion_runs` row (`endpoint="identifier_resolution"`) via
  `repository.insert_ingestion_run(..., metadata={"unresolved_tickers": unresolved})` — this
  is a **separate** row from whatever the client's own `recorder` (if attached) writes for
  the raw `company_tickers` fetch, since the client has no notion of "which tickers were in
  this job's batch"; that business fact only exists at the job layer. A CIK's
  `asset_identifiers.id_value` is stored as the 10-digit zero-padded numeric string with no
  `CIK` prefix (`"0000320193"`), matching the exact convention already established in Batch
  1's `test_upsert_asset_identifiers_is_idempotent`/`test_resolve_asset_by_identifier_round_trips`
  fixtures — deliberately distinct from `pad_cik`'s `"CIK0000320193"` URL form used
  internally by `SecEdgarClient`. The CLI `main()`/`parse_args()` wrapper follows
  `collector/main.py`'s and `brain/run_retraining_job.py`'s exact conventions: `--tickers`
  (comma-separated) overrides a `--universe-file` default (`DEFAULT_UNIVERSE_PATH =
  "config/universe.sp100.json"`, a module constant) read via
  `collector.universe.load_universe_document`; `psycopg.connect(...,
  autocommit=True)` + `LocalPostgresRepository(connection=connection)`; JSON printed via
  `print(json.dumps(result, indent=2))`. `SecEdgarConfigError` from a missing
  `SEC_USER_AGENT` is deliberately **not** caught inside `run_identifier_resolution` —  it
  propagates per the two-tier contract ("Missing User-Agent fails loudly"); if a `recorder`
  is attached to the client, the client's own `finally` block already records that exit path
  (proven in Batch 2).
- [x] 5.3 **Non-matrix security requirement — confirmed by grep, both call chains**:
  - `collector.universe.load_universe_document` has exactly 3 production call sites (plus
    test fixtures): `brain/run_retraining_job.py:182` (`path` = `DEFAULT_UNIVERSE_FILE =
    "config/universe.sp100.json"`, a module constant, landed by the Phase 3 sibling),
    `collector/run_identifier_resolution.py:163` (`path` = `args.universe_file`, a CLI
    argument defaulting to a module constant — this batch), and indirectly via
    `collector/main.py`'s `load_asset_configs(args.assets_file)` → `isinstance(raw, dict)` →
    `expand_universe_document` (`args.assets_file` is a CLI argument, landed by the Phase 2
    sibling). None derive from an inbound HTTP request.
  - `brain.run_retraining_job`'s targets-file path: `DEFAULT_TARGETS_FILE =
    "config/targets.core.json"` (module constant) overridable only via the `--targets-file`
    CLI flag (`brain/run_retraining_job.py:28-31`, landed by the Phase 3 sibling) — never
    request-derived.
  - Confirmed via `rg -n "load_universe_document" --type py` and `rg -n
    "targets.file|targets_file|default_targets" brain/run_retraining_job.py
    brain/retraining_job.py`, re-run at the end of this batch after Phase 2/3 had fully
    landed, to catch call sites that did not exist at the start of this session.
- [x] 5.4 `test_repository_ingestion_recorder_calls_insert_once_per_record` — constructs one
  `IngestionRun`, calls `.record(run)` twice against a `FakeIdentifierRepository`, asserts
  exactly 2 `insert_ingestion_run` calls and that every one of the 12 kwargs on the first
  call matches the source `IngestionRun`'s corresponding field 1:1.
- [x] 5.5 `test_unresolved_ticker_appears_in_result_and_ingestion_run_metadata` (a fake
  `company_tickers` payload with `AAPL`/`MSFT` but not `NOPE` → `NOPE` appears in both
  `result["unresolved"]` and the `identifier_resolution`-endpoint `ingestion_runs` row's
  `metadata["unresolved_tickers"]`) plus
  `test_unresolved_ticker_is_printed_not_silently_dropped` (`capsys` — the ticker string
  appears in stdout) plus `test_fetch_failure_marks_every_ticker_unresolved_and_never_raises`
  (a transport failure — 5xx exhausted — marks every requested ticker unresolved, records a
  `status="failure"` job-level row, and writes zero `asset_identifiers` rows, all without
  raising).
- [x] 5.6 `test_resolved_ticker_asset_identifiers_row_returns_cik` (round-trips through
  `FakeIdentifierRepository.resolve_asset_by_identifier`) plus
  `test_fetch_company_tickers_called_exactly_once_regardless_of_ticker_count` (bulk-preferring
  proof) plus `test_resolved_cik_fetch_retains_filed_date_independent_of_period_end` — after
  resolving `AAPL`'s CIK through this job, a subsequent `client.fetch_company_facts("320193")`
  (the same nested XBRL fixture Batch 2's `test_success_returns_provider_payload_unmodified`
  used) still returns `filed="2024-02-01"` distinct from `end="2023-12-31"`, proving the
  transport-fidelity half of "Ingested fact retains both dates" at this integration point too
  (full XBRL parsing/persistence is `fundamental-analysis` sibling scope, per design.md).
- [x] 5.7 `test_run_identifier_resolution_persists_rows_against_real_repository(repository)`
  — uses the session-scoped `repository`/`db_connection` fixtures from `tests/conftest.py`
  (real `TEST_DATABASE_URL`, migrations applied once, each test wrapped in a rolled-back
  transaction) with an injected `SecEdgarClient` wrapping a `FakeSession` (zero live SEC
  calls). Resolves `AAPL` (matched) and `ZZZZ-NOPE` (unmatched) in one call; asserts
  `repository.resolve_asset_by_identifier("cik", "0000320193")` round-trips to `AAPL`, and
  `repository.get_recent_ingestion_runs(source="sec_edgar")` contains exactly one
  `endpoint="identifier_resolution"` row with `metadata["unresolved_tickers"] ==
  ["ZZZZ-NOPE"]` and `status == "success"`.

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `collector/ingestion_audit.py` | Created | `RepositoryIngestionRecorder` — `IngestionRunRecorder` Protocol implementation, 1:1 field mapping into `insert_ingestion_run` |
| `collector/run_identifier_resolution.py` | Created | `run_identifier_resolution(repository, client, tickers)` core job + CLI wrapper (`--tickers`/`--universe-file`) |
| `tests/test_sec_edgar_client.py` | Modified | Added a `# === Identifier resolution ===` section (8 new test functions) after Phase 4's existing content; added 4 new imports at the top (`Any`, `RepositoryIngestionRecorder`, `LocalPostgresRepository`, `run_identifier_resolution`); zero changes to any of Phase 4's 31 existing test functions |
| `openspec/changes/financial-intelligence-expansion/tasks.md` | Modified | Marked Phase 5 tasks 5.1-5.7 `[x]` |

### Deviations from Design

None on the public contract (`RepositoryIngestionRecorder(repository)`, the
`{"resolved": [...], "unresolved": [...]}` return shape, `metadata.unresolved_tickers`).
Two implementation-detail decisions design.md left open, resolved here and noted for the
reviewer:

1. **Asset lookup uses `get_or_create_asset`, not `get_asset_id`.** This means "unresolved"
   strictly means "no match in `company_tickers.json`" (matching the spec scenario's exact
   wording: "GIVEN a ticker with no matching entry in the SEC company-ticker map"), never
   "not yet tracked locally" — the latter would conflate two different failure modes and
   design.md/spec.md never mention a `ValueError`/ticker-not-found path for this job.
2. **The job writes its own `ingestion_runs` row directly**, separate from whatever the
   `SecEdgarClient`'s own `recorder` (if attached) writes for the raw fetch. This is the
   only way to satisfy "Unresolved tickers go into `ingestion_runs.metadata.unresolved_tickers`"
   literally: the client's transport layer has no concept of "which tickers this business
   job was resolving," so that row can only be written by `run_identifier_resolution` itself.

### Issues Found

None.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_sec_edgar_client.py -q` → `43 passed in 2.54s` (35 Phase 4 + 8 new, 0 regressions). Task table's suggested `-k identifier` filter → `2 passed, 41 deselected` (only 2 of the 8 new test names literally contain the substring "identifier"; the full-file run above is the complete, accurate proof) |
| Runtime harness command/scenario and exact result | Real `TEST_DATABASE_URL` round-trip (task 5.7): `test_run_identifier_resolution_persists_rows_against_real_repository` — passed as part of the 43; confirmed `asset_identifiers` and `ingestion_runs` rows persist and round-trip correctly against the live test database |
| Rollback boundary | Delete `collector/ingestion_audit.py` and `collector/run_identifier_resolution.py`; delete the appended identifier-resolution section (8 functions) and the 4 added imports from `tests/test_sec_edgar_client.py`, restoring it to Batch 2's exact state; Phase 4's client stays inert with no caller again |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported):
- Baseline entering this batch (Batch 1 + Batch 2, before Phase 2/3/6 siblings and this
  batch landed): **284 passed**
- After this batch, with Phase 2 and Phase 6 siblings' work also landed concurrently in the
  same tree (Phase 3's implementation code was present but its own tests/task-marks were
  still in flight): **320 passed, 2 failed**
- **The 2 failures are environmental, not caused by this batch or by Phase 5's code.**
  Reproduced with `py -3.14 -m pytest
  tests/test_local_repository.py::test_upsert_prices_resolves_conflicts_and_returns_batch_size
  tests/test_notification_dispatch.py::test_get_latest_price_timestamps_includes_assets_with_zero_prices`
  run **in complete isolation** (this test file never executed in that process) — both still
  fail identically. Root-caused by direct query: the shared `TEST_DATABASE_URL` already had a
  permanently committed `AAPL` asset with 2 real `prices` rows
  (`select ticker, id from assets where ticker='AAPL'` returned one row;
  `select count(*) from prices ... where ticker='AAPL'` returned 2) — leftover from a
  sibling's real runtime-harness command (task 2.9's "`py -3.14 -m collector.main
  --assets-file config/universe.sp100.json --start 2020-01-01 --end 2020-01-05` against
  `TEST_DATABASE_URL`", which uses `autocommit=True`, per `collector/main.py`'s `main()` —
  so that data was never inside a rolled-back transaction). Phase 5's own code and tests
  never touch the `prices` table and never open a connection outside the
  `repository`/`db_connection` fixtures' rolled-back-transaction pattern, so this batch
  cannot be the source. Not remediated here: cleaning up another phase's shared-database
  state is out of this batch's scope and could interfere with a concurrently-running
  sibling agent still relying on that data.

### Remaining Tasks

- [ ] Phase 3: Bounded Retraining-Target Policy + Global-Scope Cap (implementation code
  observed already landed in the tree by its own concurrent sibling agent during this batch;
  task checkboxes 3.1-3.8 were still `[ ]` in `tasks.md` as of this batch's last read — that
  sibling's own apply-progress entry is authoritative for its status)
- [ ] Phase 7: API Endpoint + Rollout Confirmation (depends on Phase 2 + Phase 3 landing,
  per the review workload table)

### Workload / PR Boundary

- Mode: chained PR slice (`stacked-to-main`)
- Current work unit: PR 5 — `collector/ingestion_audit.py` +
  `collector/run_identifier_resolution.py` (after PR 1, PR 4 — both already landed)
- Boundary: this batch starts from an inert, uncalled `SecEdgarClient` (Batch 2) and ends
  with a fully wired, fully tested identifier-resolution job; `RetrainingJobConfig`/
  `run_retraining_job` and the universe file are untouched by this batch specifically (they
  were touched concurrently by sibling batches, not this one).
- Estimated review budget impact: new source is ~55 lines (`ingestion_audit.py`) + ~185
  lines (`run_identifier_resolution.py`) ≈ 240 lines; the appended test section is ~230
  lines across 8 functions plus a 4-line import addition — combined ≈ 470-490 raw added
  lines, somewhat above the ~150-220 estimate in the forecast table (mirrors Batch 2's
  pattern of test code exceeding the source-code estimate, this time by a smaller margin).
  Still a single, autonomous, independently revertible unit with no cross-file coupling
  beyond the already-landed Phase 1/4 interfaces.

### Status

7/7 Phase 5 tasks complete. No blockers introduced by this batch. The 2 full-suite failures
are pre-existing shared-database pollution from a concurrent sibling's runtime-harness step,
confirmed unrelated to this batch's code by isolated reproduction. Ready for `sdd-verify` on
this slice, or for `sdd-apply` to continue with Phase 3 (task-mark completion) and Phase 7.

## Batch 3 — Phase 3: Bounded Retraining-Target Policy + Global-Scope Cap

**Mode**: Standard (`openspec/config.yaml` has `testing.strict_tdd: false` — proceeded in
standard workflow: read spec/design, write code + tests together, verify with the focused
suite, the full suite, and a real runtime-harness invocation against `TEST_DATABASE_URL`).

Ran concurrently with (and lands after) sibling batches for Phase 2 (`config/universe.sp100.json`,
`collector/universe.py`, `collector/main.py`), Phase 5 (`collector/ingestion_audit.py`,
`collector/run_identifier_resolution.py`), and Phase 6 (`brain/features.py`) — all now visible
on disk. This batch only touched its assigned files: `config/targets.core.json`,
`brain/retraining_job.py`, `brain/run_retraining_job.py`, `brain/scoped_evaluation.py`,
`tests/test_brain_pipeline.py`, plus one file not explicitly listed in tasks.md's per-task
scope but required by design.md's own interface note (see Deviations below):
`brain/candidate_matrix.py`.

### Completed Tasks

- [x] 3.1 `config/targets.core.json` — `["BTC-USD", "ETH-USD", "AAPL", "MSFT"]`, identical to
  today's `config/assets.core.json` tickers.
- [x] 3.2 `brain/retraining_job.py`'s `resolve_target_tickers` extended with keyword-only
  `default_targets=None` and `max_auto_targets=None`. Existing 2-positional-arg behavior fully
  preserved when neither kwarg is passed (`sorted(available)`, uncapped — proven by
  `test_resolve_target_tickers_uncapped_preserves_two_positional_arg_behavior`). Precedence:
  explicit `tickers` (truthy) wins outright; else `default_targets` (truthy) intersects with
  available; else `sorted(available)` is returned, raising `ValueError` naming
  `--tickers`/`--targets-file`/`--max-auto-targets` only when `max_auto_targets` is set and the
  available count exceeds it. Never truncates silently.
- [x] 3.3 `RetrainingJobConfig` gained `default_targets: list[str] | None = None`,
  `max_auto_targets: int = 8`, `max_global_scope_assets: int = 12`. Also added all three (plus
  the pre-existing `default_targets`) to `summarize_config`'s output so the JSON report stays
  reproducible/self-describing, matching the existing pattern for every other tunable.
- [x] 3.4 `brain/run_retraining_job.py` gained `--targets-file` (default
  `config/targets.core.json`), `--max-auto-targets` (default 8), `--max-global-scope-assets`
  (default 12). `--tickers` still wins: when tickers are given, `--targets-file` is not even
  read (`default_targets=None if tickers else load_default_targets(args.targets_file)`).
  `payload["universe"]` is now always set via `load_universe_disclosure(DEFAULT_UNIVERSE_FILE)`
  — defensively written per the orchestrator's instruction (try/except `ImportError` around
  `from collector.universe import load_universe_document, universe_disclosure`, plus an
  existence check on the universe file and a `try/except (ValueError, OSError)` around
  `load_universe_document`), falling back to
  `{"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}` in every degraded
  case. In practice Phase 2's sibling batch landed `collector/universe.py` and
  `config/universe.sp100.json` concurrently, so the real path was exercised end-to-end in the
  runtime harness (see Work Unit Evidence) — the defensive fallback never fired, but the code
  still degrades gracefully if run against a checkout without Phase 2.
- [x] 3.5 `brain/scoped_evaluation.py`'s `select_scope_datasets` gained keyword-only
  `max_scope_assets: int | None = None`. Over the cap: keeps the target dataset unconditionally,
  ranks the rest by `(-len(item.dataset), item.ticker)` (row count descending, ticker ascending
  as the tiebreaker), and returns `[target, *ranked_rest[:max_scope_assets - 1]]`. Below the
  cap or `max_scope_assets=None`, returns the input selection unchanged (`is` the same list
  object when uncapped). Threaded through `run_scoped_walk_forward_backtest`'s new
  keyword-only `max_scope_assets` param; `build_scope_training_frame` needed no change, exactly
  as design.md predicted, since it only ever sees the already-capped `scope_datasets` list.
- [x] 3.6 `tests/test_brain_pipeline.py`: 6 new tests for `resolve_target_tickers` — 100 fake
  datasets + no `tickers`/no `default_targets` + `max_auto_targets=8` raises `ValueError`
  matching `"max_auto_targets"`; with `default_targets=["TKR001", "TKR050", "MISSING"]` set →
  exactly `["TKR001", "TKR050"]` (missing ticker silently absent from *available*, not from the
  policy — this is intersection, not the never-truncate guarantee, which only applies to the
  auto/no-policy path); explicit `tickers=["tkr002", "missing"]` (lowercase, one invalid) →
  `["TKR002"]`, proving the override still wins over `default_targets` and still
  case-normalizes/filters exactly as today; a 4-dataset case within the cap → unchanged
  `sorted(available)`; the 2-positional-arg backward-compatibility test noted above.
- [x] 3.7 `tests/test_brain_pipeline.py`: `test_select_scope_datasets_caps_global_scope_deterministically`
  — 40 fake datasets (1 target + 39 peers with distinct row counts, no ties), `max_scope_assets=12`
  on `global` scope → exactly 12 selected, target always first, and the selection is identical
  whether the 40 fake datasets are passed in original order or reversed (proves the cap is not
  an accident of input ordering) — asserted against an independently computed expected ranking.
  A companion `test_select_scope_datasets_below_cap_is_unaffected` proves the cap is a no-op
  when the scope is already under the limit.

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `config/targets.core.json` | Created | `["BTC-USD", "ETH-USD", "AAPL", "MSFT"]` |
| `brain/retraining_job.py` | Modified | `resolve_target_tickers` kwargs; 3 new `RetrainingJobConfig` fields; `build_candidate_report` passes `max_scope_assets=config.max_global_scope_assets` to `run_candidate_matrix`; `summarize_config` reports the 3 new fields |
| `brain/run_retraining_job.py` | Modified | 3 new CLI flags; `load_default_targets`/`load_universe_disclosure` helpers; `payload["universe"]` always set |
| `brain/scoped_evaluation.py` | Modified | `max_scope_assets` cap on `select_scope_datasets`, threaded through `run_scoped_walk_forward_backtest` |
| `brain/candidate_matrix.py` | Modified (not in tasks.md's literal per-task file list — see Deviations) | `run_candidate_matrix` gained keyword-only `max_scope_assets`, passed through to `run_scoped_walk_forward_backtest` |
| `tests/test_brain_pipeline.py` | Modified | Added `pytest` import, `resolve_target_tickers`/`select_scope_datasets` imports, `make_fake_dataset` helper, 8 new tests |
| `openspec/changes/financial-intelligence-expansion/tasks.md` | Modified | Marked Phase 3 tasks 3.1-3.8 `[x]` |

### Deviations from Design

One deliberate scope extension beyond tasks.md's literal per-task file list, but explicitly
supported by design.md's own Interfaces/Contracts section: task 3.5's text only names
`run_scoped_walk_forward_backtest` as the thread-through target, but design.md's code comment
for `select_scope_datasets` says "Threaded through `run_scoped_walk_forward_backtest` **and
`run_candidate_matrix`**; the chosen set is already reported via `participating_assets`."
Without touching `brain/candidate_matrix.py`, `RetrainingJobConfig.max_global_scope_assets`
would have no path to reach `select_scope_datasets` at all from `run_retraining_job`'s actual
call chain (`build_candidate_report` → `run_candidate_matrix` → `run_scoped_walk_forward_backtest`),
making the new config field permanently inert. Added a keyword-only `max_scope_assets: int |
None = None` to `run_candidate_matrix` (default `None` = today's behavior, zero risk to its
two existing callers `brain/retraining_job.py` and `brain/evaluate_candidate_matrix.py`, both
of which call it entirely by keyword) and passed it straight through to every
`run_scoped_walk_forward_backtest` call inside its loop — uniformly across `local`/`asset_class`/
`global` scopes, not scope-conditionally. This was a deliberate simplicity choice: `local` scope
is always exactly 1 dataset (the cap is a no-op there), and capping `asset_class` scope too is
strictly protective for a widened S&P 100 universe where a single asset class (e.g. "stock")
could itself have ~97 members — the config field's name (`max_global_scope_assets`) describes
the motivating scenario from the proposal, not a hard restriction to only the `global` scope
value. Flagging this for the reviewer since it is a real (small) scope addition beyond the
literal task list, even though it is required for the feature to functionally work end-to-end
and is explicitly grounded in design.md's own text.

No other deviations — `resolve_target_tickers`, `RetrainingJobConfig`, `run_retraining_job.py`'s
CLI flags, and `select_scope_datasets`'s cap logic all match design.md's signatures and stated
behavior exactly.

### Issues Found

None.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_brain_pipeline.py tests/test_collector_job.py -k "target or scope" -q` → `10 passed` |
| Runtime harness command/scenario and exact result | `py -3.14 -m brain.run_retraining_job --targets-file config/targets.core.json --max-auto-targets 8 --max-global-scope-assets 12` against `TEST_DATABASE_URL` (with `LOCAL_DATABASE_URL` explicitly pointed at the same DSN, since `LocalPostgresConfig.from_env()` only reads `LOCAL_DATABASE_URL`) → real JSON report: `"attempted": 0`, `"succeeded": 0`, `"failed": 0`, all 5 test-DB assets (`AAPL`, `BRK-B`, `HON`, `JNJ`, `MSFT`) reported `skipped_assets` with `"reason": "no_materialized_dataset"` (honest, not an error — no feature/label data exists yet in that DB); `config.default_targets == ["BTC-USD","ETH-USD","AAPL","MSFT"]`, `config.max_auto_targets == 8`, `config.max_global_scope_assets == 12`; `"universe"` key present with real `snapshot_date: "2025-09-22"`, `member_count: 101` (Phase 2's sibling batch had already landed `config/universe.sp100.json` + `collector/universe.py` concurrently, so the real disclosure path was exercised, not just the fallback) |
| Rollback boundary | Revert the keyword-only kwargs on `resolve_target_tickers`/`select_scope_datasets`/`run_scoped_walk_forward_backtest`/`run_candidate_matrix` (all default to `None`/unset, preserving today's behavior byte-for-byte); revert the 3 new `RetrainingJobConfig` fields and their 4 lines in `summarize_config`; revert the 3 new CLI flags and the 2 new helper functions plus the `payload["universe"] = ...` line in `run_retraining_job.py`; delete `config/targets.core.json`; delete the 8 new test functions (plus the `make_fake_dataset` helper and the `pytest` import if nothing else in the file needs them) from `tests/test_brain_pipeline.py` |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported per the
Environment block):
- Baseline entering this batch (per orchestrator, reflecting Batch 1 + Batch 2 already landed):
  **284 passed**
- After this batch: **322 passed**, 0 regressions, 1 pre-existing unrelated warning
  (`joblib`/`loky` core-count detection on Windows, not introduced by this batch)
- This batch's own net-new contribution is **7 test functions** (8 `def test_...` were added;
  1 of them — `test_select_scope_datasets_below_cap_is_unaffected` — was not separately counted
  in the tasks.md-mandated set but strengthens 3.7's coverage). The remaining **31-test gap**
  between 284→322 minus this batch's 7 comes from sibling Phase 2/5/6 batches (`tests/test_universe_config.py`,
  `tests/test_feature_set_resolution.py`, and additions to `tests/test_sec_edgar_client.py`)
  landing on disk concurrently during this session — confirmed via `git status`/`git log`,
  not double-counted from this batch's own diff.

### Remaining Tasks (per most recent read of tasks.md, which sibling batches were also updating concurrently)

- [ ] Phase 2 task 3.8's own operational wall-clock measurement is intentionally left for
  whoever runs the real backfill (see task 3.8's note above) — everything else in Phase 3 is
  code-complete.
- [ ] Phase 7: API Endpoint + Rollout Confirmation (not this batch's scope)

### Workload / PR Boundary

- Mode: chained PR slice (`stacked-to-main`)
- Current work unit: PR 3 — `config/targets.core.json` + `brain/retraining_job.py` target-policy
  kwargs + `brain/run_retraining_job.py` CLI flags + `brain/scoped_evaluation.py` global-scope
  cap (independent of PR 1/PR 2 per the forecast table)
- Boundary: this batch starts from `resolve_target_tickers` returning `sorted(available)`
  unconditionally (the ~25×-targets risk from Key Learning #3) and ends with that risk bounded
  by an explicit, fail-loud policy, plus a deterministic global-scope-size cap threaded all the
  way from `RetrainingJobConfig` down to `select_scope_datasets`. No Phase 2/4/5/6/7 files
  touched except the one explained deviation (`brain/candidate_matrix.py`), which has no
  overlap with any concurrent sibling's assigned files.
- Estimated review budget impact: source changes are small (`retraining_job.py` +~35 lines,
  `run_retraining_job.py` +~55 lines, `scoped_evaluation.py` +~25 lines, `candidate_matrix.py`
  +~5 lines, `config/targets.core.json` 1 line); `tests/test_brain_pipeline.py` +~90 lines.
  Roughly ~210 total changed lines — comfortably within the ~300-360 estimate for PR 3 and well
  under the 400-line budget.

### Status

8/8 Phase 3 tasks complete (3.8's code portion done; its operational wall-clock measurement is
explicitly deferred per its own text, not blocking). No blockers. Ready for `sdd-apply` to
continue with any remaining phase (Phase 7 is the only one not yet reported landed as of this
batch), or `sdd-verify` if PR 3 is being verified as its own slice before further phases
proceed.

## Batch 3 — Phase 6: Asset-Class Feature-Set Resolution Seam

**Mode**: Standard (`openspec/config.yaml` present with `testing.strict_tdd: false` —
proceeded in standard workflow: read spec/design, write the additive functions + tests
together, verify with the focused suite then the full suite).

Ran concurrently with Phase 2/3/5 sibling agents actively editing `brain/retraining_job.py`,
`brain/run_retraining_job.py`, `brain/scoped_evaluation.py`, `brain/candidate_matrix.py`,
`collector/main.py` in the same tree. No file overlap with this batch: this batch only
touches `brain/features.py` (modified, additive-only) and `tests/test_feature_set_resolution.py`
(new). `tests/test_brain_pipeline.py` was NOT touched — no regression check needed there for
this seam.

### Completed Tasks

- [x] 6.1 `brain/features.py` — added `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS: dict[str, str] = {}`
  (empty; siblings register later) and `DEFAULT_BASE_FEATURE_SET = "technical_v2"`; added
  `feature_set_for_asset_class(asset_class, base_feature_set=DEFAULT_BASE_FEATURE_SET)` —
  never raises, normalizes via `.strip().lower()`, unmapped/blank/`None` class falls back to
  `base_feature_set`.
- [x] 6.2 `brain/features.py` — added keyword-only `asset_class: str | None = None` to
  `feature_columns_for_set`. When `asset_class is None` (all 14 real existing call sites),
  `resolved = feature_set` — strictly string-keyed, byte-identical to the pre-change function
  including the `ValueError` message text for an unknown name. When set, resolves via
  `feature_set_for_asset_class` first.
- [x] 6.3 `brain/features.py` — added `compose_feature_set(base_feature_set, overlay_columns)`
  returning `[*feature_columns_for_set(base_feature_set), *overlay_columns]`, verbatim from
  design.md. `technical_v2`'s list object itself is never mutated (list is rebuilt via
  unpacking, not appended to).
- [x] 6.4 `tests/test_feature_set_resolution.py` — `feature_columns_for_set("technical_v2")`
  equals `FEATURE_COLUMNS_TECHNICAL_V2` unchanged; parametrized over
  `asset_class="crypto"/"unknown_class"/None` all return the same list without raising (empty
  overlay map = universal fallback).
- [x] 6.5 `tests/test_feature_set_resolution.py` — unknown `feature_set` name raises
  `ValueError` both with and without an `asset_class` kwarg;
  `feature_set_for_asset_class` never raises for any input incl. `None`/empty string;
  `monkeypatch.setitem(FEATURE_SET_OVERLAYS_BY_ASSET_CLASS, "crypto", ...)` proves the
  registered-overlay resolution path (both `feature_set_for_asset_class` directly and through
  `feature_columns_for_set(..., asset_class=...)`), plus case/whitespace normalization
  (`"CRYPTO"`, `"  crypto  "`); `compose_feature_set` appends overlay columns without mutating
  the `technical_v2` spine.
- [x] 6.6 Ran `py -3.14 -m pytest` (full suite, both DSNs exported) — 0 regressions; every one
  of the 14 real `feature_columns_for_set` call sites (grepped explicitly — the "28 callers"
  figure in design.md/tasks.md counts doc/spec/test mentions, not just production call sites)
  passes exactly one positional arg, so the new keyword-only param breaks nothing.

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `brain/features.py` | Modified | Added `FEATURE_SET_OVERLAYS_BY_ASSET_CLASS`, `DEFAULT_BASE_FEATURE_SET`, `feature_set_for_asset_class`, `compose_feature_set`; `feature_columns_for_set` gained keyword-only `asset_class=None` (byte-identical when omitted) |
| `tests/test_feature_set_resolution.py` | Created | 9 tests: byte-identical baseline, fallback (parametrized over crypto/unknown/None), unknown-name `ValueError` regardless of `asset_class`, never-raises policy function, registered-overlay resolution (both layers) with case/whitespace normalization, `compose_feature_set` non-mutation |
| `openspec/changes/financial-intelligence-expansion/tasks.md` | Modified | Marked Phase 6 tasks 6.1-6.6 `[x]` |

### Deviations from Design

None — implementation matches design.md's verbatim `brain/features.py` diff exactly,
including the docstrings and the `(asset_class or "").strip().lower()` normalization.

### Issues Found

None in this batch's own scope. One transient observation not caused by this batch: a full
"`py -3.14 -m pytest`" run mid-session hit 3 failures in `tests/test_brain_pipeline.py`
(`retraining_job.py:86: TypeError`) while a sibling agent was concurrently mid-editing
`brain/retraining_job.py` (Phase 3, live in the same working tree). Re-running immediately
after (and running the failing tests in isolation) showed 0 failures — confirmed as a
concurrent-edit race on files this batch never touches, not a defect in Phase 6's code.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_feature_set_resolution.py brain/ -q` → `9 passed` |
| Runtime harness command/scenario and exact result | N/A per design.md/tasks.md: stdlib-only pure functions, no I/O — parametrized unit tests are the complete proof (design's own "Testing Strategy" table lists this as Unit-only) |
| Rollback boundary | Revert the 3 additive functions and the keyword-only `asset_class` param in `brain/features.py` (default `None` preserves every existing call site's behavior); delete `tests/test_feature_set_resolution.py`. No other file changed by this batch. |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported):
- Baseline measured at the start of this batch: **284 passed** (matches Batch 2's final count
  — no Phase 6 work had landed yet)
- After this batch's own change in isolation: `tests/test_feature_set_resolution.py brain/ -q`
  → **9 passed**, 0 regressions among the 14 real `feature_columns_for_set` callers
- Full-suite run immediately after landing this batch showed a transient 3-failure race from
  a concurrently-editing sibling (see "Issues Found" above); re-run cleanly at **307 passed**,
  then **322 passed** as further sibling batches (Phase 2/3/5) continued landing concurrently
  in the same session. This batch's own 9 tests are included and green in every one of those
  runs.

### Remaining Tasks

- [ ] Phase 5: Ingestion Audit Recorder + Identifier Resolution Job (sibling scope, in
  progress concurrently per git status)
- [ ] Phase 7: API Endpoint + Rollout Confirmation

### Workload / PR Boundary

- Mode: chained PR slice (`stacked-to-main`)
- Current work unit: PR 6 — `brain/features.py` additive functions (independent of PR 1-5)
- Boundary: this batch starts from `feature_columns_for_set` having no `asset_class`
  awareness at all and ends with the full resolution seam in place, registry empty, every
  existing call site byte-identical.
- Estimated review budget impact: within the ~100-130 estimated line budget for PR 6 (Low
  risk); actual diff is ~30 lines in `brain/features.py` + ~65 lines of new test file, well
  under the 400-line threshold and under the PR's own estimate.

### Status

6/6 Phase 6 tasks complete. No blockers. This batch's own focused suite is green and stable;
full-suite count fluctuates only due to concurrent sibling batches landing in the same
session, never due to this batch's own code. Ready for `sdd-apply` to continue with Phase 5
or Phase 7, or `sdd-verify` if PR 6 is being verified as its own slice before further phases
proceed.

## Batch 3 — Phase 2: S&P 100 Universe Snapshot

**Mode**: Standard (no `strict_tdd` config found; `openspec/config.yaml` not present in this
checkout — proceeded in standard workflow: read spec/design, write config + loader + main.py
wiring, write tests, verify with the focused suite, the full suite, and a real runtime
harness run against `TEST_DATABASE_URL`).

Ran concurrently with sibling batches on Phase 3 (`config/targets.core.json`,
`brain/retraining_job.py`, `brain/run_retraining_job.py`, `brain/scoped_evaluation.py`),
Phase 5 (`collector/ingestion_audit.py`, `collector/run_identifier_resolution.py`), and
Phase 6 (`brain/features.py`). No file overlap: this batch only touches
`config/universe.sp100.json` (new), `collector/universe.py` (new), `collector/main.py`
(modified — additive `expand_universe_document` + one `isinstance(raw, dict)` branch), and
`tests/test_universe_config.py` (new). Staged explicit paths only, never `git add -A`, so
sibling agents' concurrent uncommitted work in this shared tree was not touched or committed.

Task 2.1 was already verified by the orchestrator before this batch (`HON`, not `HONA`,
confirmed via SEC EDGAR CIK 0000773840 + independent quote sources) — no re-verification
performed here.

### Completed Tasks

- [x] 2.2 `config/universe.sp100.json` (new) — built via a small one-off generator script
  (not checked in; scratchpad-only) from the orchestrator-supplied verified 101-ticker list,
  to guarantee mechanical, typo-free transcription rather than manual copy-paste. Schema
  matches design.md exactly: `"index": "S&P 100 (OEX)"`, `"snapshot_date": "2025-09-22"`
  (the Wikipedia article's own citation date — honestly recorded, not backdated to a later
  date than the data reflects), `"source": "Wikipedia S&P 100 article, retrieved
  2026-08-28; membership as of 2025-09-22 per article citation"`, `"membership_bias"` copied
  verbatim from design.md's example JSON, `"defaults"` block exactly as specified
  (`yfinance`/`stock`/`1d`/`2020-01-01`), and a compact single-line-per-member `"members"`
  array (matching design's "~120 lines" compact-schema rationale — a naive
  `json.dumps(indent=2)` 4-line-per-member expansion would have produced ~420 lines instead;
  the file is 110 lines).
- [x] 2.3 Ticker normalization (`.` → `-`) implemented as a transformation step
  (`normalize_ticker()`) inside the generator script, applied uniformly to every ticker, not
  a manual one-off edit — confirmed `BRK.B` → `BRK-B` is the only ticker affected in this
  snapshot; verified programmatically that zero remaining tickers contain `.`.
- [x] 2.4 `tests/test_universe_config.py` — 4 tests: file parses and has the expected
  `index`/`members` shape; `BRK-B` present and `BRK.B` absent; no ticker contains `.`;
  `member_count == 101`.
- [x] 2.5 `collector/universe.py` (new) — `UniverseDocument` frozen dataclass with the exact
  6 fields from design.md; `load_universe_document(path)` raises `ValueError` with a message
  naming the missing field when `snapshot_date` or `membership_bias` is absent or
  blank/whitespace-only (fails at load time, never at report time); `universe_disclosure(doc)`
  returns the exact 5-key dict (`index`/`snapshot_date`/`source`/`membership_bias`/
  `member_count`). Also added `universe_report_block(doc: UniverseDocument | None)` — an
  additive helper (not in design.md's explicit 3-symbol interface list, but directly required
  by task 2.7's acceptance test and the spec's "Missing snapshot date blocks
  disclosure-bearing output" requirement) that wraps `universe_disclosure` under the
  `"universe"` report key, or emits `{"disclosure_status": "incomplete", "reason":
  "no_universe_snapshot"}` when no document is available — never omitting the key. This
  module imports nothing from `collector.main`/`AssetCollectionConfig`, confirmed by
  inspection (only stdlib `json`/`dataclasses`/`pathlib`/`typing` imports).
- [x] 2.6 `collector/main.py` — added `expand_universe_document(raw: dict[str, Any]) ->
  list[AssetCollectionConfig]` building one config per member from the raw parsed dict's
  `defaults`/`members` keys (not via `load_universe_document`, so this function has no
  disclosure-validation dependency — it is purely a collection-shape expansion, matching
  design's exact interface snippet which calls it directly on `json.loads(...)` output).
  Wired `if isinstance(raw, dict): return expand_universe_document(raw)` into
  `load_asset_configs`, placed before the existing `isinstance(raw, list)` check. The
  existing list-form code path (`return [AssetCollectionConfig(**item) for item in raw]`)
  is byte-identical to before; only the `ValueError` message text changed from `"assets file
  must contain a JSON array"` to `"assets file must contain a JSON array or a universe
  document"` — this exact wording is design.md's own verbatim interface snippet, and no
  existing test asserted the old message text (confirmed via search).
- [x] 2.7 `tests/test_universe_config.py` — `test_expand_universe_document_applies_defaults_to_every_member`
  (3-member fixture → 3 `AssetCollectionConfig`, full field-by-field equality including
  `defaults` propagation and `BRK-B` normalization survives round-trip);
  `test_load_asset_configs_dispatches_dict_form_to_universe_expansion` (dict-form file
  through the public `load_asset_configs` entry point); `test_universe_report_block_with_document_embeds_disclosure`
  and `test_universe_report_block_with_no_document_emits_incomplete_marker` prove the exact
  `{"universe": {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}}` shape
  from the task description, and the populated-document case reuses `universe_disclosure`
  directly (no duplicated field list to drift).
- [x] 2.8 `tests/test_universe_config.py` — `test_load_universe_document_raises_when_snapshot_date_missing`,
  `..._membership_bias_missing`, and `..._snapshot_date_blank` (whitespace-only string, not
  just an absent key) all assert `pytest.raises(ValueError, match=...)`;
  `test_load_universe_document_round_trips_valid_fixture` is the paired happy-path proof.
- [x] 2.9 `test_full_universe_expansion_resolves_every_asset_without_configuration_error` —
  loads the real checked-in `config/universe.sp100.json`, expands all 101 members, and runs
  them through `run_collection` with a fake `provider_factory`/`FakeRepository` (same pattern
  as `tests/test_collector_job.py`'s `FakeProvider`/`FakeRepository`) — asserts 101 results,
  101 `get_or_create_asset` calls, matching ticker sets, and every asset resolved with
  `asset_class="stock"`. The runtime-harness command (below) separately proves the same
  `isinstance(raw, dict)` → `expand_universe_document` → `collect_asset` path against real
  `yfinance` and a real `TEST_DATABASE_URL` round-trip for a 5-ticker subset.

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `config/universe.sp100.json` | Created | 101-member S&P 100 snapshot, `snapshot_date: 2025-09-22`, compact schema (110 lines) |
| `collector/universe.py` | Created | `UniverseDocument`, `load_universe_document`, `universe_disclosure`, `universe_report_block` |
| `collector/main.py` | Modified | Added `expand_universe_document` + `isinstance(raw, dict)` branch in `load_asset_configs`; list-form code path unchanged |
| `tests/test_universe_config.py` | Created | 14 tests covering the snapshot file shape, expansion, disclosure/incomplete-marker, missing-field validation, and full 101-member expansion |
| `openspec/changes/financial-intelligence-expansion/tasks.md` | Modified | Marked Phase 2 tasks 2.2-2.9 `[x]` |

### Deviations from Design

One addition beyond design.md's explicit 3-symbol `collector/universe.py` interface list:
`universe_report_block(doc: UniverseDocument | None) -> dict[str, Any]`. Design.md describes
this exact behavior narratively ("a report generated with no universe document at all emits
`{"universe": {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}}` rather
than dropping the key") but does not name a function for it, and task 2.7 requires a test
proving this behavior in Phase 2's own test file — while the actual call sites
(`brain/run_retraining_job.py`'s report, `api/main.py`'s endpoint) are Phase 3 and Phase 7
work, explicitly out of scope for this batch. Adding this small, additive, pure helper to
`collector/universe.py` (my file) lets Phase 3/7 import and reuse it later without me
touching their files now. No other deviation — `expand_universe_document`'s signature,
`UniverseDocument`'s fields, and `load_universe_document`'s fail-fast behavior all match
design.md exactly.

### Issues Found

The runtime harness run (below) writes real rows into `TEST_DATABASE_URL` outside any test
transaction (unlike the `db_connection` fixture's per-test rollback), and it reused live
tickers (`AAPL`) that other suites' tests also create via `get_or_create_asset("aapl", ...)`
and then assume start with zero prices. Immediately after the harness run, the full suite
showed 2 failures — `test_upsert_prices_resolves_conflicts_and_returns_batch_size` (expected
3 rows, found 5: 2 leftover real `yfinance` rows + 3 from the test) and
`test_get_latest_price_timestamps_includes_assets_with_zero_prices` (expected `None`, found
the leftover real row's timestamp). Fixed by deleting the 5 harness-inserted `assets` rows
(and their 10 `prices` rows) from `TEST_DATABASE_URL` by ticker
(`AAPL`/`MSFT`/`JNJ`/`HON`/`BRK-B`) immediately after capturing the harness evidence below;
re-ran the full suite clean. **Learning for future runtime-harness batches against
`TEST_DATABASE_URL`**: always delete harness-inserted rows before the final full-suite run,
especially for tickers (like `AAPL`) that other suites' fixtures also touch.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_universe_config.py -q` → `14 passed in 2.30s` |
| Runtime harness command/scenario and exact result | `LOCAL_DATABASE_URL=<TEST_DATABASE_URL value> py -3.14 -m collector.main --assets-file <5-ticker subset universe doc: AAPL/MSFT/JNJ/HON/BRK-B> --start 2020-01-01 --end 2020-01-05` against real `yfinance` and real `TEST_DATABASE_URL` → all 5 tickers returned `rows_loaded: 2`; verified by direct SQL query against `TEST_DATABASE_URL`: all 5 rows present in `assets` (`asset_class='stock'`) and 2 price rows each in `prices`, including `HON` and `BRK-B` resolving correctly through real `yfinance` — the strongest possible confirmation that task 2.1's `HON` (not `HONA`) correction is right. Rows were deleted from `TEST_DATABASE_URL` immediately after (see "Issues Found"). |
| Rollback boundary | Delete `config/universe.sp100.json`, `collector/universe.py`, `tests/test_universe_config.py`; revert `collector/main.py`'s `expand_universe_document` function and the `isinstance(raw, dict)` branch (the `isinstance(raw, list)` path and `config/assets.core.json` consumers are completely untouched) |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported via `.env`):
- Before this batch (measured at batch start, matching Batch 2's end-state): **284 passed**
- Immediately after this batch's code + the runtime harness run (before DB cleanup):
  **2 failed, 320 passed** — both failures traced to harness-inserted `AAPL`/etc. rows in
  `TEST_DATABASE_URL` (see "Issues Found"), not to this batch's actual code
- After deleting the harness-inserted rows: **322 passed, 0 failed** — this run also
  captured concurrent sibling-batch commits/edits landing in the same shared tree (Phase 4
  and Phase 6 are now committed on this branch; Phase 3/5 were present as uncommitted working
  changes), so 322 is not solely this batch's contribution. This batch's own isolated
  contribution is exactly **14 new tests** (`py -3.14 -m pytest tests/test_universe_config.py
  -q` → `14 passed`), 0 regressions in any file this batch touched.

### Remaining Tasks

- [ ] Phase 3: Bounded Retraining-Target Policy + Global-Scope Cap (concurrent sibling scope)
- [ ] Phase 5: Ingestion Audit Recorder + Identifier Resolution Job (concurrent sibling scope)
- [ ] Phase 6: Asset-Class Feature-Set Resolution Seam (concurrent sibling scope)
- [ ] Phase 7: API Endpoint + Rollout Confirmation

### Workload / PR Boundary

- Mode: chained PR slice (`stacked-to-main`)
- Current work unit: PR 2 — `config/universe.sp100.json` + `collector/universe.py` +
  `collector/main.py`'s `expand_universe_document`/`isinstance` branch. Per design's explicit
  "Slice 2 is the file itself and must not be merged with any other slice" note, this PR
  stays scoped to exactly these 4 files.
- Boundary: this batch starts from no universe snapshot/loader existing at all and ends with
  a fully tested, disclosure-complete 101-member snapshot wired into the collector's existing
  `load_asset_configs` entry point, proven against both a fake provider (full 101-member
  expansion) and real `yfinance`/`TEST_DATABASE_URL` (5-ticker subset).
- Estimated review budget impact: within the ~350-400 estimated line budget for PR 2
  (Medium-High risk); the snapshot file's compact single-line-per-member layout (110 lines)
  was a deliberate choice to stay close to design's own ~120-line estimate rather than the
  ~420 lines a naive `json.dumps(indent=2)` would have produced.

### Status

8/8 Phase 2 tasks complete (2.1 pre-verified by orchestrator; 2.2-2.9 this batch). No
blockers. Ready for `sdd-apply` to continue with any remaining phase, or `sdd-verify` if PR 2
is being verified as its own slice before further phases proceed.

## Batch 4 — Phase 7: API Endpoint + Rollout Confirmation (FINAL phase)

**Mode**: Standard (`openspec/config.yaml` has `testing.strict_tdd: false` — proceeded in
standard workflow: read spec/design/tasks/apply-progress, wrote the endpoint + tests
together, verified with the focused suites, the full suite, the UI build, and a real
`uvicorn`/`curl` round-trip).

Ran after all of Phase 1-6 had already landed on disk (322 passing tests entering this
batch, confirmed by the orchestrator and re-verified here). This batch only touches
`api/main.py`, `tests/test_api.py`, `tests/test_brain_pipeline.py`, `README.md`,
`openspec/changes/financial-intelligence-expansion/tasks.md`, and
`openspec/changes/financial-intelligence-expansion/state.yaml`. No Phase 1-6 file was
modified.

### Completed Tasks

- [x] 7.1 `api/main.py` — added `DEFAULT_UNIVERSE_FILE = "config/universe.sp100.json"`
  (module constant, no request-derived path) and `INCOMPLETE_UNIVERSE_DISCLOSURE` next to the
  existing `APP_CONFIG`/`_POOL` module-level constants; added `GET /api/universe` between
  `get_assets` and `get_prices`: `load_universe_document(DEFAULT_UNIVERSE_FILE)` then
  `universe_disclosure(doc)` on success; `except (OSError, ValueError)` — covering
  `FileNotFoundError`/`PermissionError`/`json.JSONDecodeError` (all `OSError`/`ValueError`
  subclasses) and `load_universe_document`'s own explicit `ValueError` for a missing
  `snapshot_date`/`membership_bias` — returns
  `{"universe": {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}}`
  instead, never a 500. `GET /api/assets` was **not** touched — confirmed by diff, it stays
  the bare `Asset[]` list design.md explicitly decided to keep.
- [x] 7.2 `tests/test_api.py` — `test_universe_endpoint_returns_real_snapshot_disclosure`
  (real checked-in `config/universe.sp100.json` → `snapshot_date == "2025-09-22"`,
  `member_count == 101`, non-empty `source`/`membership_bias`);
  `test_universe_endpoint_never_accepts_a_request_supplied_path` (closes task 5.3 for this
  call site: `inspect.signature(get_universe).parameters == {}` — no query/path parameter
  exists at all, so there is no request-derived override to reason about);
  `test_universe_endpoint_degrades_to_incomplete_marker_when_file_missing`
  (`monkeypatch.setattr("api.main.DEFAULT_UNIVERSE_FILE", "config/does-not-exist.json")` →
  the exact incomplete-marker shape, `200` not `500`).
- [x] 7.3 `tests/test_brain_pipeline.py` — confirmed (did not need to re-implement) that
  `brain/run_retraining_job.py`'s `main()` already sets
  `payload["universe"] = load_universe_disclosure(DEFAULT_UNIVERSE_FILE)` (landed in Batch 3
  — Phase 3, line 133), where `load_universe_disclosure` wraps `load_universe_document` +
  `universe_disclosure` with a degrade-to-incomplete fallback. Added
  `test_load_universe_disclosure_embeds_universe_disclosure_for_real_snapshot` (asserts
  `load_universe_disclosure(DEFAULT_UNIVERSE_FILE) ==
  universe_disclosure(load_universe_document(DEFAULT_UNIVERSE_FILE))` for the real checked-in
  snapshot, plus the concrete `snapshot_date`/`member_count` values) and
  `test_load_universe_disclosure_degrades_to_incomplete_marker_when_missing` (a `tmp_path`
  nonexistent path → the exact incomplete shape) — this is the first direct test coverage of
  `load_universe_disclosure` itself; Batch 3's own runtime-harness evidence had already proven
  the wiring end-to-end against a real `TEST_DATABASE_URL` run, but had no dedicated unit test
  for the function.
- [x] 7.4 Ran `py -3.14 -m pytest` (full suite, both DSNs exported) and
  `cd ui && npm run build` — both green (see Work Unit Evidence below). The widened universe
  is wired into the collector, the retraining-target policy, and now this API endpoint, but
  **not backfilled or retrained** in this change, exactly as design.md requires.
- [x] 7.5 Updated `README.md` (chosen over `PLAN_MEJORAS_PROFESIONALES.md` — see Deviations
  below) with a new `## Universo de Activos` section (documenting `GET /api/universe`, the
  verified ticker source, and the `HON`/`HONA` correction outcome) and an updated `Estado
  Actual` table row. The wall-clock numbers are honestly written as **Pending**, per this
  batch's explicit instruction not to fabricate them — see the doc text itself for the exact
  wording, which names the real backfill command and explains the deferral is by design, not
  an oversight.

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `api/main.py` | Modified | Added `GET /api/universe`, `DEFAULT_UNIVERSE_FILE`, `INCOMPLETE_UNIVERSE_DISCLOSURE`; `GET /api/assets` untouched |
| `tests/test_api.py` | Modified | 3 new tests + `get_universe` import |
| `tests/test_brain_pipeline.py` | Modified | 2 new tests + `load_universe_disclosure`/`DEFAULT_UNIVERSE_FILE`/`load_universe_document`/`universe_disclosure` imports |
| `README.md` | Modified | New `## Universo de Activos` section; `Estado Actual` table's `Datos` row updated |
| `openspec/changes/financial-intelligence-expansion/tasks.md` | Modified | Marked Phase 7 tasks 7.1-7.5 `[x]` — this completes ALL of tasks.md |
| `openspec/changes/financial-intelligence-expansion/state.yaml` | Modified | `progress.apply: pending` → `complete` |

### Deviations from Design

None on the public contract — the endpoint's success/failure shapes match the orchestrator's
literal task description exactly (success: flat `universe_disclosure(doc)`; failure: nested
`{"universe": {...}}`), which itself matches design.md's narrative text ("served by a new
`GET /api/universe` in `api/main.py`"; "a report generated with no universe document at all
emits `{"universe": {"disclosure_status": "incomplete", ...}}`"). One documentation-placement
judgment call, explicitly delegated to this batch: task 7.5 offered
`PLAN_MEJORAS_PROFESIONALES.md`/`README.md` as candidates. `PLAN_MEJORAS_PROFESIONALES.md` is
structured entirely as forward-looking `Objetivo`/`Tareas`/`Criterio de salida` blocks for
**not-yet-built** work — there is no existing "already landed, here is what's pending"
pattern anywhere in that file to extend. `README.md` already has this exact pattern (`##
Salud Operativa`, `## Alertas Operativas` — a short paragraph plus a `curl` example
documenting an already-shipped endpoint), so the new `## Universo de Activos` section follows
that established structure directly. `PLAN_MEJORAS_PROFESIONALES.md` was left untouched.

**Explicitly confirmed, not this batch's job**: "sibling changes 3-7 exist as OpenSpec
changes with `depends_on` and restated C1-C4" is `proposal.md`'s own success criterion for
future sibling `sdd-propose` runs — no sibling change scaffolding
(`fundamental-analysis`/`institutional-consensus`/`personal-finance`/
`asset-class-profile-overlays`/`gemini-optional-assist`) was created in this batch.

### Issues Found

None.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_api.py -k universe -q` → `3 passed`; `py -3.14 -m pytest tests/test_brain_pipeline.py -k universe -q` → `2 passed` |
| Runtime harness command/scenario and exact result | `py -3.14 -m uvicorn api.main:app --host 127.0.0.1 --port 8123` then `curl http://127.0.0.1:8123/api/universe` → real `200` JSON: `{"index":"S&P 100 (OEX)","snapshot_date":"2025-09-22","source":"Wikipedia S&P 100 article, retrieved 2026-08-28; membership as of 2025-09-22 per article citation","membership_bias":"Current membership applied to 2020-2026 history is survivorship / index-inclusion bias: constituents are the survivors and post-inclusion winners.","member_count":101}`; process killed cleanly after capture |
| Rollback boundary | Revert the `GET /api/universe` route, `DEFAULT_UNIVERSE_FILE`, and `INCOMPLETE_UNIVERSE_DISCLOSURE` in `api/main.py`; delete the 3 new test functions + `get_universe` import from `tests/test_api.py`; delete the 2 new test functions + 4 new imports from `tests/test_brain_pipeline.py`; revert the `## Universo de Activos` section and the `Estado Actual` table row in `README.md`. `GET /api/assets` and every other endpoint are completely untouched. |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported):
- Baseline entering this batch (per orchestrator, matching the end of Batch 3's three
  concurrent Phase 2/3/6 sub-batches): **322 passed**
- After this batch: **327 passed**, 0 regressions (322 + 3 `test_api.py` + 2
  `test_brain_pipeline.py` = 327, exact arithmetic match — no other file changed)

`cd ui && npm run build`: **green** (`tsc -b && vite build` completed, `dist/` emitted, no UI
source was touched by this batch so this was a pure regression confirmation).

### Remaining Tasks

None. This was the final phase (Phase 7) of the shared-foundation change. All 7 phases across
tasks.md are now `[x]`.

### Workload / PR Boundary

- Mode: chained PR slice (`stacked-to-main`)
- Current work unit: PR 7 — `api/main.py`'s `GET /api/universe` + full-suite/build
  confirmation + wall-time/doc write-up (after PR 2, PR 3 — both already landed)
- Boundary: this batch starts from a checked-in universe snapshot with no HTTP surface at all
  and ends with a live, tested `GET /api/universe` endpoint, full-suite green, UI build green,
  and the doc write-up committed — the last reviewable slice of the shared foundation.
- Estimated review budget impact: source diff is ~20 lines (`api/main.py`); tests are ~55
  lines across the two test files; docs are ~10 lines (`README.md`) — roughly ~85-100 total
  changed lines, comfortably within the ~90-130 estimate for PR 7 and well under the 400-line
  budget.

### Status

5/5 Phase 7 tasks complete. **All 7 phases of `financial-intelligence-expansion`'s shared
foundation are now complete: 35/35 tasks across tasks.md marked `[x]`.** `327/327` tests
passing (full suite, both DSNs exported), UI build green, real endpoint hit and confirmed.
No blockers. `state.yaml`'s `progress.apply` set to `complete`. Ready for `sdd-verify`.

---

## Final Summary — Shared Foundation Complete (Phases 1-7)

`financial-intelligence-expansion`'s shared-foundation slice (migration + repository methods,
S&P 100 universe snapshot + loader + disclosure, bounded retraining-target policy + global-scope
cap, SEC EDGAR client, ingestion audit recorder + identifier-resolution job, asset-class
feature-set resolution seam, and the `GET /api/universe` API endpoint) is done across all 7
planned PR-sized work units:

| Phase | PR | Scope | Status |
|---|---|---|---|
| 1 | PR 1 | Migration `0005` + 5 repository methods + schema check | Complete (Batch 1) |
| 2 | PR 2 | `config/universe.sp100.json` + `collector/universe.py` + `collector/main.py` wiring | Complete (Batch 3) |
| 3 | PR 3 | `config/targets.core.json` + target-policy kwargs + global-scope cap | Complete (Batch 3) |
| 4 | PR 4 | `collector/providers/sec_edgar_client.py` | Complete (Batch 2) |
| 5 | PR 5 | `collector/ingestion_audit.py` + `collector/run_identifier_resolution.py` | Complete (Batch 3) |
| 6 | PR 6 | `brain/features.py` asset-class feature-set resolution seam | Complete (Batch 3) |
| 7 | PR 7 | `GET /api/universe` + full-suite/build confirmation + doc write-up | Complete (Batch 4) |

**Final verified state**: `py -3.14 -m pytest` → **327 passed**, 0 failed (up from a
pre-change baseline of 243); `cd ui && npm run build` → green; `GET /api/universe` hit live
and returns real disclosure JSON.

**Explicitly deferred by design, not this change's scope**:
- Task 3.8's/7.5's real wall-clock before/after comparison (requires a real backfill of the
  widened universe, which design.md explicitly says must NOT happen in this same slice).
- Sibling OpenSpec changes (`fundamental-analysis`, `institutional-consensus`,
  `personal-finance`, `asset-class-profile-overlays`, `gemini-optional-assist`) — these are
  `proposal.md`'s own success-criteria items for future `sdd-propose` runs, not implementation
  work in this tasks.md.
- Any real market-data backfill or model retraining against the widened universe.

**Ready for `sdd-verify`.**
