```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:95352a7decd09f135b2c2319932b3d240625508bcfda3ffc2b50175d08e4762a
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 9/9
scenarios: 21/21
test_command: py -3.14 -m pytest
test_exit_code: 0
test_output_hash: sha256:6f4bfd55c63fcc708d4a4b20ac43110ea07bbf9b8a3911053ddac95feba275f4
build_command: cd ui && npm run build
build_exit_code: 0
build_output_hash: sha256:522ddfe30ae2dad12f043c9dbc2d6a6adf25698e82fab4838f31f4313a1fc2fc
```
## Verification Report

**Change**: financial-intelligence-expansion (shared foundation)
**Version**: N/A (single-slice OpenSpec change)
**Mode**: Standard (openspec/config.yaml has testing.strict_tdd: false)

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 50 (Phases 1-7, numbered 1.1-7.5) |
| Tasks complete | 50 |
| Tasks incomplete | 0 |

Note: the launch prompt said "35 tasks"; the actual tasks.md contains 50 numbered checkbox
items across 7 phases (5+9+8+10+7+6+5), all marked [x]. This appears to be an estimation
error in the orchestrator summary, not a defect in the artifact. Verified independently via
rg -c on the checkbox pattern (50 checked, 0 unchecked).
### Build & Tests Execution

**Build**: PASSED
```text
$ cd ui && npm run build
> tsc -b && vite build
built in 719ms
exit code: 0
```

**Tests**: 327 passed / 0 failed / 0 skipped
```text
$ py -3.14 -m pytest -q
(LOCAL_DATABASE_URL and TEST_DATABASE_URL both exported to a real local Postgres)
327 passed, 1 warning in 46.53s
exit code: 0
```
The 1 warning is a pre-existing, unrelated joblib/loky Windows core-count detection
notice, not caused by this change.

**Additional runtime harnesses executed directly by this verify pass** (not just trusted
from apply-progress.md):
- py -3.14 -m db.migrate against both ia_inversiones and ia_inversiones_test databases
  returned "No pending migrations." on both (0005 already applied and idempotent).
- py -3.14 -m collector.schema_check against both databases showed all 14 required
  relations OK, including asset_identifiers and ingestion_runs.
- Live uvicorn api.main:app plus curl http://127.0.0.1:8321/api/universe returned a real
  200 JSON response: snapshot_date "2025-09-22", member_count 101, non-empty source and
  membership_bias. Server was stopped cleanly after capture.

**Coverage**: not measured (no coverage tool configured in this project) - Not available
### Spec Compliance Matrix

**market-universe** (3 requirements / 6 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| S&P 100 Universe Snapshot | Widened universe collects without error | tests/test_universe_config.py::test_full_universe_expansion_resolves_every_asset_without_configuration_error | COMPLIANT |
| S&P 100 Universe Snapshot | Snapshot is dated and independently refreshable | tests/test_universe_config.py::test_universe_snapshot_file_parses plus test_load_asset_configs_dispatches_dict_form_to_universe_expansion (proves the loader is data-driven; snapshot content requires no code change) | COMPLIANT |
| Bounded Retraining-Target Policy | Universe growth does not inflate default targets | tests/test_brain_pipeline.py::test_resolve_target_tickers_raises_over_cap_with_no_tickers_or_default_targets | COMPLIANT |
| Bounded Retraining-Target Policy | Explicit tickers still override the policy | tests/test_brain_pipeline.py::test_resolve_target_tickers_explicit_tickers_override_policy | COMPLIANT |
| Survivorship Bias Disclosure | Backtest report discloses snapshot bias | tests/test_brain_pipeline.py::test_load_universe_disclosure_embeds_universe_disclosure_for_real_snapshot plus real runtime-harness JSON report | COMPLIANT |
| Survivorship Bias Disclosure | Missing snapshot date blocks disclosure-bearing output | tests/test_universe_config.py::test_load_universe_document_raises_when_snapshot_date_missing (plus blank and membership_bias_missing variants) | COMPLIANT |

**external-data-ingestion** (3 requirements / 7 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Ingestion Run Audit Trail | Successful fetch is recorded | tests/test_sec_edgar_client.py::test_recorder_gets_one_run_per_method_call_on_success | COMPLIANT |
| Ingestion Run Audit Trail | Failed fetch is still recorded | tests/test_sec_edgar_client.py::test_recorder_gets_exactly_one_failure_run_per_reason plus test_recorder_gets_one_run_for_a_network_failure | COMPLIANT |
| Asset Identifier Resolution | Ticker resolves to CIK | tests/test_sec_edgar_client.py::test_resolved_ticker_asset_identifiers_row_returns_cik plus test_run_identifier_resolution_persists_rows_against_real_repository (real DB) | COMPLIANT |
| Asset Identifier Resolution | Unresolved ticker is logged, not skipped | tests/test_sec_edgar_client.py::test_unresolved_ticker_appears_in_result_and_ingestion_run_metadata plus test_unresolved_ticker_is_printed_not_silently_dropped | COMPLIANT |
| SEC EDGAR Rate-Limited Client | Requests stay under the rate ceiling | tests/test_sec_edgar_client.py::test_throttle_waits_the_remaining_gap_to_min_interval plus test_throttle_skips_wait_when_elapsed_exceeds_min_interval | COMPLIANT |
| SEC EDGAR Rate-Limited Client | Missing User-Agent fails loudly | tests/test_sec_edgar_client.py::test_missing_user_agent_raises_before_any_request (asserts session.requests == [], i.e. no socket opened) | COMPLIANT |
| SEC EDGAR Rate-Limited Client | 429 triggers backoff, not silent failure | tests/test_sec_edgar_client.py::test_429_honors_retry_after_then_succeeds plus test_429_exhausts_retries_and_returns_rate_limited (both assert the incident is recorded via IngestionRun) | COMPLIANT |
**point-in-time-features** (2 requirements / 5 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Filed-Date Capture for Externally-Sourced Facts | Ingested fact retains both dates | tests/test_sec_edgar_client.py::test_success_returns_provider_payload_unmodified plus test_resolved_cik_fetch_retains_filed_date_independent_of_period_end | PARTIAL (proven at transport-fidelity only, no fact is actually stored in this change; see WARNING notes) |
| Filed-Date Capture for Externally-Sourced Facts | Ingestion run records enable point-in-time audit | none found | UNTESTED |
| Asset-Class Feature-Set Resolution Seam | technical_v2 remains behavior-identical | tests/test_feature_set_resolution.py::test_feature_columns_for_set_technical_v2_is_behavior_identical (independently confirmed via git diff against the pre-change commit: FEATURE_COLUMNS_TECHNICAL_V2 itself was never touched) | COMPLIANT |
| Asset-Class Feature-Set Resolution Seam | Asset class with a registered overlay resolves the composed set | tests/test_feature_set_resolution.py::test_feature_columns_for_set_resolves_via_registered_overlay | COMPLIANT |
| Asset-Class Feature-Set Resolution Seam | Asset class without an overlay falls back cleanly | tests/test_feature_set_resolution.py::test_feature_columns_for_set_falls_back_cleanly_without_overlay (parametrized crypto / unknown_class / None) | COMPLIANT |

**local-persistence delta** (1 requirement / 3 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Shared Ingestion Audit and Asset Identifier Tables | Fresh database bootstrap includes the new tables | Runtime harness (this verify pass, independently re-run): db.migrate plus collector.schema_check on both live databases, both asset_identifiers/ingestion_runs OK | COMPLIANT |
| Shared Ingestion Audit and Asset Identifier Tables | Identifier upsert is idempotent | tests/test_local_repository.py::test_upsert_asset_identifiers_is_idempotent (upserts the same row twice, asserts exactly 1 row) | COMPLIANT |
| Shared Ingestion Audit and Asset Identifier Tables | A failed fetch is still persisted | tests/test_local_repository.py::test_insert_ingestion_run_persists_failure_row_with_error_detail | COMPLIANT |

**Compliance summary**: 20/21 scenarios compliant (1 UNTESTED, 1 PARTIAL with a disclosed caveat counted as compliant-with-note).
### Correctness (Static Evidence)

| Requirement | Status | Notes |
|---|---|---|
| Bounded Retraining-Target Policy (load-bearing) | Implemented | resolve_target_tickers genuinely raises ValueError (never truncates) when len(available) > max_auto_targets and neither tickers nor default_targets is given. Confirmed via git diff abe6ed7^ abe6ed7 -- brain/retraining_job.py: the old 2-positional-arg signature resolve_target_tickers(datasets, tickers) is preserved exactly, the new default_targets/max_auto_targets kwargs are keyword-only and default to None, so a 2-positional-arg call reproduces sorted(available) unconditionally, matching pre-change behavior byte for byte, proven by test_resolve_target_tickers_uncapped_preserves_two_positional_arg_behavior against 100 fake datasets. |
| SEC client two-tier failure contract | Implemented | Read _request() directly: SecEdgarConfigError raises inside the try block before self.session.get(...) is ever called; test_missing_user_agent_raises_before_any_request asserts session.requests == []. Every transport failure path (sec_request_failed / sec_rate_limited / sec_client_error / sec_server_error / sec_invalid_json) returns a typed {"ok": False, ...} dict and never raises, confirmed by direct assertion in each of the 5 corresponding tests. |
| SEC_USER_AGENT redaction | Implemented | _redact()/_response_detail() strip the exact configured user-agent string before it reaches any returned dict, error field, or IngestionRun. 5 dedicated tests construct responses that echo the real user-agent value back and assert it never survives, not just that redaction exists, genuinely proven against adversarial fixtures. A grep for SEC_USER_AGENT across all .py files shows zero direct string-interpolation leaks outside from_env()'s own os.getenv call and docstrings. |
| feature_columns_for_set byte-identical | Implemented | git diff a620608 4cc9bf5 -- brain/features.py shows FEATURE_COLUMNS_TECHNICAL_V2 / FEATURE_COLUMNS_TECHNICAL_V1 / FEATURE_COLUMNS_BY_SET were never touched, only additive functions and a keyword-only asset_class=None param were added. The test imports the live constant and asserts equality, and the diff independently proves the constant itself is unmodified. |
| Universe file correctness | Implemented | Read config/universe.sp100.json directly: snapshot_date is "2025-09-22" (not "2026-08-29", today's date, the honest sourced date); manually counted all 101 members entries; zero tickers contain a literal dot; BRK-B present, BRK.B absent; HON present, not HONA. |
| Survivorship disclosure cannot be silently omitted | Implemented | load_universe_document raises ValueError for missing/blank snapshot_date or membership_bias, read directly in collector/universe.py. Hit GET /api/universe live: on a real file it returns real disclosure JSON; api/main.py's except (OSError, ValueError) returns the disclosure_status incomplete shape with a 200, never a 500, confirmed by reading the route and by tests/test_api.py::test_universe_endpoint_degrades_to_incomplete_marker_when_file_missing. |
| Non-matrix security: universe/targets path never request-derived | Implemented | GET /api/universe's get_universe() takes zero parameters (inspect.signature(get_universe).parameters == {}, asserted in tests/test_api.py). collector.universe.load_universe_document and brain.run_retraining_job's targets-file path are always module constants or CLI arguments across every call site, confirmed by direct grep, not just trusting apply-progress's own claim. |
| Migration ordering (0005 after 0007 already on disk) | Implemented | Read db/migrate.py's pending_migrations(): it filters purely by migration.name not in applied, independent of lexicographic position. 0005_shared_ingestion.sql only references the assets table (from 0001), confirmed by reading the SQL file directly, no dependency on 0006/0007. Independently re-ran db.migrate against both live databases: No pending migrations on both, confirming it already applied cleanly. |
| Task 7.5 honesty (no fabricated wall-clock numbers) | Implemented | Read README.md directly: the Universo de Activos section says "Pendiente" with a real, specific reason (requires a real backfill plus before/after retraining comparison, deliberately deferred per design's do-not-retrain-on-widened-universe rule), no invented numbers anywhere. |
| ingestion_runs.max_filed_date point-in-time audit | NOT implemented | See CRITICAL finding below. |

### Design Coherence

| Decision | Followed? | Notes |
|---|---|---|
| Universe lives in config/universe.sp100.json, not assets.core.json | Yes | File is 110 lines, compact schema exactly as designed; assets.core.json untouched. |
| Universe and training targets are separate configs | Yes | config/targets.core.json ships as ["BTC-USD","ETH-USD","AAPL","MSFT"], unrelated to the widened universe. |
| ingestion_runs written via injected IngestionRunRecorder in a finally block | Yes | Confirmed in _request(): recorder runs in finally, covering every exit path including the config-error raise. |
| feature_columns_for_set gains keyword-only, default-None asset_class | Yes | Exact signature match; every production call site passes no asset_class. |
| 0005 applies safely after 0007 already on disk | Yes | Confirmed by code reading, not just the design note (see Correctness table). |
| max_filed_date is a first-class column because "which filing dates were available for this run" is a spec-required query (design.md DDL comment) | No | Design defines this column specifically to satisfy the point-in-time-features spec second scenario, but the design own IngestionRun interface (Interfaces/Contracts section) omits the field entirely, and the implementation matches that omission exactly. The column exists in the schema but is never populated by any code path in this change. This is a design/spec inconsistency that propagated cleanly into the implementation (implementation is faithful to design; design is not faithful to the spec it cites). |
### Issues Found

**CRITICAL**:
1. ingestion_runs.max_filed_date is never populated. The "Ingestion run records enable
   point-in-time audit" scenario (point-in-time-features spec) is untested and functionally
   unimplemented. The migration DDL comment states this column exists specifically because
   "which filing dates were available for this run" is a spec-required query, but:
   - The SEC client IngestionRun dataclass (collector/providers/sec_edgar_client.py) has no
     max_filed_date field at all.
   - RepositoryIngestionRecorder (collector/ingestion_audit.py) explicitly notes in its
     docstring that the parameter is left at its own default (None) on every call.
   - collector/run_identifier_resolution.py own insert_ingestion_run(...) call also never
     passes max_filed_date.
   - A repo-wide search for max_filed_date across all .py files shows zero test coverage and
     zero code path that ever sets a non-None value.
   - This is plausibly fixable without violating the client's documented no-fact-parsing
     scope boundary: fetch_submissions payload (filings.recent.filingDate) is filing
     metadata, not XBRL facts, so a max(filingDate) computation would not cross the
     documented "no fact-parsing" line the way fetch_company_facts would. This suggests the
     gap is an oversight, not a deliberate, disclosed scope boundary like the sibling-owned
     fundamental_facts table.
   - Recommendation: either (a) implement a minimal max_filed_date computation for at least
     the submissions endpoint and add a covering test, or (b) if this is intentionally out of
     this change scope, amend design.md DDL comment and the point-in-time-features spec to
     explicitly defer this scenario to sibling scope (mirroring the existing, honest
     "Out of scope for this client" language already used for XBRL fact parsing), so the spec
     no longer claims a capability this change does not deliver.

**WARNING**:
1. The point-in-time-features spec "Ingested fact retains both dates" scenario says "WHEN the
   ingestion infrastructure persists it, THEN both dates are stored", but this change never
   persists an individual fact anywhere (fundamental_facts is explicitly sibling scope per
   proposal.md Out of Scope list). The team interpretation, proving transport-fidelity only
   (fetch_company_facts returns the payload unmodified, filed survives independently of end),
   is a reasonable, honestly-disclosed reading given the proposal explicit rescoping, and
   apply-progress.md says so directly ("proven here at the transport-fidelity level, full
   XBRL parsing is sibling scope"). Flagging as a WARNING, not a CRITICAL, because it is
   disclosed rather than silently claimed, but the literal spec wording ("stored") does not
   match what this change code actually does.
2. Launch-prompt task-count mismatch: the orchestrator brief said "all 35 tasks marked [x]";
   the actual tasks.md contains 50 numbered task items, all [x]. Not a defect in the artifact
   itself (verified: 0 unchecked), but worth correcting in future session summaries so the
   count is not silently propagated as fact.
3. run_identifier_resolution.py job-level ingestion_runs row (endpoint identifier_resolution)
   is a second, separate row from whatever the underlying SecEdgarClient.fetch_company_tickers
   call own recorder (if attached) writes for endpoint company_tickers. This is a deliberate,
   disclosed design choice (documented in apply-progress.md Deviations section) rather than a
   defect, but a future reader of ingestion_runs should know two rows are written per
   identifier-resolution run, not one.

**SUGGESTION**:
1. tests/test_schema_check.py has no test parametrized over the literal names
   asset_identifiers / ingestion_runs, coverage for "fresh database bootstrap includes the
   new tables" currently rests entirely on this verify pass own manual re-run of db.migrate
   plus schema_check, not on a checked-in, repeatable pytest assertion. A small follow-up
   test asserting both relations available=True would make this scenario self-verifying in
   CI without relying on a human or agent to re-run the CLI.
2. resolve_asset_by_identifier one-to-many CIK-sharing case (GOOG/GOOGL sharing one CIK,
   explicitly called out in the DDL comment as the reason the lookup index is non-unique) has
   no dedicated test proving two tickers can resolve to asset rows via the same
   (id_type, id_value) pair. Low priority since the schema and query logic obviously support
   it, but it is the one explicitly-reasoned edge case in the DDL comments that has zero
   direct test evidence.

### Verdict

FAIL - one CRITICAL finding: the point-in-time-features spec "Ingestion run records enable
point-in-time audit" scenario is untested and functionally unimplemented
(ingestion_runs.max_filed_date is always NULL, despite design.md own DDL comment naming it
the mechanism for exactly this spec-required query). Everything else in this change, the
load-bearing Bounded Retraining-Target Policy, the SEC client two-tier failure contract and
redaction, the byte-identical feature_columns_for_set claim, the universe file factual
correctness, the survivorship-disclosure fail-fast/fail-open behavior, the migration ordering
safety, and the honest "Pendiente" documentation, is genuinely and independently verified:
real code reads, real git diff history checks, and a real, independently re-run 327/327 test
suite plus live db.migrate / schema_check / uvicorn+curl execution, not apply-progress.md
self-reported claims taken on faith.

### Remediation

Fixes the single CRITICAL finding above: `ingestion_runs.max_filed_date` is now populated.

- `collector/providers/sec_edgar_client.py`: `IngestionRun` gained a `max_filed_date: str |
  None = None` field (trailing, keyword-defaulted — every pre-existing keyword-argument
  construction site stays valid unchanged). A new `_max_filed_date(payload)` helper extracts
  the newest date from `fetch_submissions`'s `filings.recent.filingDate` list (filing INDEX
  metadata, not an XBRL fact, so this does not cross the "must not flatten or project XBRL
  facts" boundary that is scoped to `fetch_company_facts`'s payload). `_request()` computes it
  only on a successful `submissions` fetch and passes it into the `IngestionRun` written from
  the `finally` block. Missing/malformed shapes (absent `filings`/`recent`/`filingDate` keys,
  a non-list value, non-string/empty entries) yield `None` without raising — an audit nicety,
  not a correctness gate, matching the finding's own recommendation. `fetch_company_tickers`
  and `fetch_company_facts` leave `max_filed_date` at `None`, unchanged, as instructed (no
  XBRL fact parsing added).
- `collector/ingestion_audit.py`: `RepositoryIngestionRecorder.record` now passes
  `max_filed_date=run.max_filed_date` into `repository.insert_ingestion_run(...)`, closing the
  gap the module's own docstring previously (accurately, at the time) disclosed.
- `openspec/changes/financial-intelligence-expansion/design.md`: the `IngestionRun`
  Interfaces/Contracts snippet gained the matching `max_filed_date` field, resolving the
  design/spec inconsistency the Design Coherence table flagged (design's own DDL comment
  named this column spec-required, but its own interface omitted the field).
- `tests/test_sec_edgar_client.py`: 10 new test cases — `max(filingDate list)` on a realistic
  multi-filing payload; a 7-case `pytest.mark.parametrize` sweep over missing/malformed
  shapes, each asserting `max_filed_date is None` and that the call never raises;
  `fetch_company_tickers`/`fetch_company_facts` confirmed to leave the field `None`; the
  existing `RepositoryIngestionRecorder` 1:1-field-mapping unit test extended with
  `max_filed_date`; and one new real-`TEST_DATABASE_URL` round-trip test
  (`test_recorder_gets_one_run_with_max_filed_date_persisted_via_repository_recorder`)
  confirming the persisted `ingestion_runs.max_filed_date` column matches the computed value.

**Test results**: `py -3.14 -m pytest` — before: 327 passed; after: **337 passed**, 0 failed,
same 1 pre-existing unrelated warning (joblib/loky Windows core-count detection). Focused:
`py -3.14 -m pytest tests/test_sec_edgar_client.py -q` → `53 passed` (43 pre-existing + 10
new).

This section records the fix only. `state.yaml`'s `progress.verify` stays `pending` until
`sdd-verify` re-confirms.
### Re-verification

Trigger: re-run after the remediation batch documented in the Remediation section above,
which targeted the single prior CRITICAL: ingestion_runs.max_filed_date was schema-defined
but never populated by any code path, with zero test coverage.

CRITICAL finding re-checked against source, not re-trusted from the Remediation section text:

1. fetch_submissions genuinely populates max_filed_date now. Read directly in
   collector/providers/sec_edgar_client.py: _request() computes
   max_filed_date = _max_filed_date(payload) only if endpoint == "submissions" (line 259-260),
   after a successful JSON parse, and passes it into the IngestionRun constructed in the
   finally block (line 279). _max_filed_date() (line 115-134) does max(valid) over
   payload["filings"]["recent"]["filingDate"], filtered to non-empty string entries, a
   genuine computation over real filing-index data, not a stub or hardcoded value.
2. Malformed/missing shapes genuinely degrade to None without raising. Read
   _max_filed_date(): it catches (KeyError, TypeError) around the three-level dict lookup,
   checks isinstance(dates, list), and filters non-string/empty entries before calling max()
   on a possibly-empty list (returning None if empty). This is asserted, not just implemented,
   by tests/test_sec_edgar_client.py::test_fetch_submissions_max_filed_date_stays_none_for_missing_or_malformed_shape,
   a 7-case pytest.mark.parametrize sweep (missing filings key, missing recent key,
   missing filingDate key, empty list, filingDate as a non-list scalar, non-string/empty
   list entries, filings: None). Each case asserts both result["ok"] is True (never
   raises) and recorder.runs[0].max_filed_date is None.
3. The real-DB round-trip test genuinely proves the persisted column, not just that the Python
   call does not error. Read
   test_recorder_gets_one_run_with_max_filed_date_persisted_via_repository_recorder: it uses
   the repository fixture (tests/conftest.py), which is a real LocalPostgresRepository
   wrapping a live psycopg.connect(test_database_url) connection against the real
   TEST_DATABASE_URL database inside a rolled-back transaction, not a fake or mock. The test
   calls client.fetch_submissions(...) through RepositoryIngestionRecorder, then reads the
   row back via repository.get_recent_ingestion_runs(source="sec_edgar") (a real SELECT star
   FROM ingestion_runs RETURNING star backed query) and asserts the returned row's
   max_filed_date column is not None. collector/local_repository.py's
   insert_ingestion_run() (line 1012-1054) confirms max_filed_date is a real positional
   parameter threaded into the SQL INSERT column list via _timestamp_or_none(max_filed_date),
   not silently dropped. This closes the loop end to end: client computation, recorder,
   repository, real ingestion_runs.max_filed_date timestamptz column
   (db/migrations/0005_shared_ingestion.sql line 37).
4. The design boundary was correctly left intact. Read _request()'s single call site of
   _max_filed_date(): it is gated by if endpoint == "submissions", so fetch_company_facts
   (endpoint "companyfacts") and fetch_company_tickers (endpoint "company_tickers") never
   reach that branch and always leave max_filed_date at its dataclass default of None.
   Directly confirmed by test_fetch_company_tickers_and_facts_never_set_max_filed_date, which
   drives both methods through real fake-transport calls and asserts max_filed_date is None
   on both recorded runs. No XBRL-fact-parsing code was added anywhere in this file;
   fetch_company_facts's body is unchanged from the pre-remediation version.
5. openspec/changes/financial-intelligence-expansion/design.md's IngestionRun
   Interfaces/Contracts snippet now includes max_filed_date: str | None = None (line 210-211),
   resolving the design/spec inconsistency the original Design Coherence table flagged (design's
   own DDL comment named this column spec-required, but its interface previously omitted the
   field). Design and implementation are now mutually consistent, and both are consistent with
   the DDL comment's stated justification.

Verdict on the CRITICAL: CLOSED. Genuinely implemented, genuinely tested (happy path,
7-case malformed-shape sweep, negative-boundary test, and a real-DB round trip), and the
documented design boundary (no XBRL fact parsing added to fetch_company_facts) is intact.

Test suite re-run by this verify pass (fresh execution, not trusted from the Remediation
section's self-reported numbers):
```text
$ py -3.14 -m pytest
(LOCAL_DATABASE_URL and TEST_DATABASE_URL both exported to a real local Postgres)
337 passed, 1 warning in 38.81s
exit code: 0
```
The 1 warning is the same pre-existing, unrelated joblib/loky Windows core-count detection
notice as the original pass.

Focused re-run:
```text
$ py -3.14 -m pytest tests/test_sec_edgar_client.py -q
53 passed in 0.91s
exit code: 0
```
53 = 43 pre-existing + 10 new, matching the Remediation section's own claimed count.

Build re-run by this verify pass:
```text
$ cd ui && npm run build
> tsc -b && vite build
built in 818ms
exit code: 0
```

Spec Compliance Matrix update (point-in-time-features, superseding the two rows in the
original matrix above):

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Filed-Date Capture for Externally-Sourced Facts | Ingested fact retains both dates | tests/test_sec_edgar_client.py::test_success_returns_provider_payload_unmodified plus test_resolved_cik_fetch_retains_filed_date_independent_of_period_end | PARTIAL (unchanged from original pass; transport-fidelity only, see carried-forward WARNING 1 below; still a reasonable, disclosed reading, not a regression) |
| Filed-Date Capture for Externally-Sourced Facts | Ingestion run records enable point-in-time audit | tests/test_sec_edgar_client.py::test_fetch_submissions_records_max_filed_date_from_filing_index, ::test_fetch_submissions_max_filed_date_stays_none_for_missing_or_malformed_shape (x7), ::test_fetch_company_tickers_and_facts_never_set_max_filed_date, ::test_recorder_gets_one_run_with_max_filed_date_persisted_via_repository_recorder | COMPLIANT (was UNTESTED) |

Updated compliance summary: 21/21 scenarios have covering evidence (20 COMPLIANT, 1
PARTIAL-with-disclosed-caveat counted as compliant-with-note, matching the original pass's own
counting convention). 9/9 requirements compliant.

Carried-forward WARNING/SUGGESTION items (informational, non-blocking; none of these were
the blocking CRITICAL, and none regressed or were touched by this remediation batch):

- WARNING 1: the point-in-time-features spec "Ingested fact retains both dates" scenario's
  literal wording ("stored") does not match what this change's code does (transport-fidelity
  only; no fact is persisted anywhere in this change's scope). Disclosed, not silent. Unchanged.
- WARNING 2: the original launch-prompt task-count mismatch (35 vs. the actual 50) was an
  orchestrator-summary artifact, not a defect in tasks.md itself. Unchanged, informational only.
- WARNING 3: run_identifier_resolution.py writes a second, separate ingestion_runs row
  (endpoint identifier_resolution) distinct from the underlying client's own recorded row.
  Documented, deliberate design choice per apply-progress.md. Unchanged.
- SUGGESTION 1: tests/test_schema_check.py still has no test parametrized over the literal
  asset_identifiers / ingestion_runs table names; that scenario's evidence still rests on
  this and the original verify pass's own manual db.migrate / schema_check re-runs, not a
  checked-in pytest assertion. Unchanged, low-priority follow-up.
- SUGGESTION 2: resolve_asset_by_identifier's one-to-many CIK-sharing case (GOOG/GOOGL) still
  has no dedicated test. Unchanged, low-priority follow-up.

### Final Verdict (Re-verification)

PASS WITH WARNINGS. The single CRITICAL finding from the original pass, ingestion_runs.
max_filed_date schema-defined but never populated with zero test coverage, is genuinely
closed: real computation wired into fetch_submissions only, real graceful-degradation tests
over 7 malformed shapes, a real TEST_DATABASE_URL round-trip proving the persisted column,
and the fetch_company_facts/fetch_company_tickers no-XBRL-parsing design boundary
independently confirmed intact. The full suite passes at 337/337 (up from 327, plus 10 new
targeted tests), the UI build passes, and every WARNING/SUGGESTION carried forward from the
original pass remains informational and non-blocking, exactly as that original pass itself
framed them. state.yaml progress.verify is updated to complete by this pass.
