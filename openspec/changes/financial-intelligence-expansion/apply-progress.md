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

None.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `py -3.14 -m pytest tests/test_universe_config.py -q` → `14 passed in 2.30s` |
| Runtime harness command/scenario and exact result | `LOCAL_DATABASE_URL=<TEST_DATABASE_URL value> py -3.14 -m collector.main --assets-file <5-ticker subset universe doc: AAPL/MSFT/JNJ/HON/BRK-B> --start 2020-01-01 --end 2020-01-05` against real `yfinance` and real `TEST_DATABASE_URL` → all 5 tickers returned `rows_loaded: 2`; verified by direct SQL query against `TEST_DATABASE_URL`: all 5 rows present in `assets` (`asset_class='stock'`) and 2 price rows each in `prices`, including `HON` and `BRK-B` resolving correctly through real `yfinance` — the strongest possible confirmation that task 2.1's `HON` (not `HONA`) correction is right |
| Rollback boundary | Delete `config/universe.sp100.json`, `collector/universe.py`, `tests/test_universe_config.py`; revert `collector/main.py`'s `expand_universe_document` function and the `isinstance(raw, dict)` branch (the `isinstance(raw, list)` path and `config/assets.core.json` consumers are completely untouched) |

### Full Suite Regression

`py -3.14 -m pytest -q` (both `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` exported via `.env`):
- Before this batch (measured at batch start, matching Batch 2's end-state): **284 passed**
- After this batch: **307 passed** — this run captured concurrent sibling-batch landings in
  the same shared tree (Phase 3/5/6 test files/additions were present at the time this batch
  ran the full suite), so 307 is not solely this batch's contribution. This batch's own
  isolated contribution is exactly **14 new tests** (`py -3.14 -m pytest
  tests/test_universe_config.py -q` → `14 passed`), 0 regressions in that file or in any file
  this batch touched.

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
