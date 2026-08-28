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
