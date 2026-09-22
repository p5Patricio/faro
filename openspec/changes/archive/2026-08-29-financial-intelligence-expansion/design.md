# Design: Financial Intelligence Expansion (shared foundation)

Scope: the rescoped foundation only — universe widening, `asset_identifiers`,
`ingestion_runs`, the SEC client, the `asset_class` resolution seam, migration `0005`.
Siblings 3–7 own their own tables and feature sets; this design only builds their seams.

## Technical Approach

Four additive seams, each behavior-neutral on the existing 4-asset pipeline. New DDL lands
as `db/migrations/0005_shared_ingestion.sql` following `0004`/`0007` conventions. The SEC
client mirrors `ops/telegram_notifier.py`: injectable `session`/`sleep`, never raises,
returns a typed dict. `feature_columns_for_set` is **not touched**; a new policy layer sits
above it. Target resolution gains an explicit narrow list so widening the universe cannot
widen training by accident.

## Architecture Decisions

### Decision: universe lives in a separate compact document, not in `assets.core.json`

| Option | Tradeoff | Decision |
|---|---|---|
| Literal 105-entry `assets.core.json` | ~800 lines; blows the 400-line budget alone | Rejected |
| `config/universe.sp100.json` — `defaults` + 1-line members | ~120 lines; carries snapshot metadata | **Chosen** |
| DB-seeded constituent table | Needs a migration + seeding job; snapshot date invisible in review | Rejected |

Rationale: the repeated 6 fields per asset are the cost, not the tickers. Hoisting them
into `defaults` cuts ~85% of the lines and gives the survivorship snapshot a natural home.
`config/assets.core.json` is left untouched.

### Decision: universe and training targets are separate configs

| Option | Tradeoff | Decision |
|---|---|---|
| `assets.is_trading_target` column | Migration + API/UI awareness; couples ML policy to reference data | Rejected |
| `config/targets.core.json` + a hard cap | 6-line file; policy stays in `brain/`; cap fails loud | **Chosen** |
| `--universe`/`--targets` CLI flags only | An unflagged run still trains 100 targets | Rejected |

Rationale: `resolve_target_tickers` returns `sorted(available)` today — with 100 datasets
that is ~25× targets × ~25× per global fit. The file makes the narrow default explicit;
`max_auto_targets` raises rather than silently truncating alphabetically (truncation would
drop names invisibly and make `model_runs` unreproducible).

### Decision: `ingestion_runs` is written inside the client, via an injected recorder

| Option | Tradeoff | Decision |
|---|---|---|
| Explicit call sites in jobs | An exception path skips the row — breaks "success or failure" | Rejected |
| Repository handle inside the client | Puts `psycopg` in an HTTP module | Rejected |
| `finally`-block write via `IngestionRunRecorder` Protocol | Guarantees every exit path; DB-free unit tests | **Chosen** |

Granularity is one row per logical fetch (one client method call), not per HTTP retry.

### Decision: `feature_columns_for_set` gains a keyword-only, default-`None` `asset_class`

`feature_columns_for_set` has 28 callers and resolves a **stored** `model_runs.feature_set`
string. The spec requires it to also resolve by `asset_class`; the rollback plan requires
the stored-string path to stay immutable. A keyword-only `asset_class=None` satisfies both:
every existing call site is untouched and strictly string-keyed, while the new path is
opt-in. With the overlay registry empty, an overlay lookup returns `"technical_v2"` —
identical columns, no error for an unmapped class.

### Decision: `0005` applies after `0007` is already on disk

`db/migrate.py:discover_migrations` sorts lexicographically but only applies **pending**
files, so a new `0005` runs after `0007` was applied. Safe here strictly because `0005`
references only `assets` (from `0001`). Any future backfill must not assume ordinal order.

## Data Flow

    config/universe.sp100.json ──load_universe_document──┐
                                                          ├─→ AssetCollectionConfig[] ─→ collect_asset ─→ prices
    config/assets.core.json ────load_asset_configs───────┘

    SEC_USER_AGENT ─→ SecEdgarClient ──throttle(0.11s)──→ data.sec.gov
                            │                                  │
                            └── finally ─→ IngestionRunRecorder ─→ ingestion_runs
                                          (status, rows, error)
                                                  ↓
                     company_tickers.json ─→ asset_identifiers (id_type='cik')

    config/targets.core.json ─→ resolve_target_tickers ─→ narrow target list
    assets.asset_class ─→ feature_set_for_asset_class ─→ feature_columns_for_set (unchanged)

## Interfaces / Contracts

### `db/migrations/0005_shared_ingestion.sql`

```sql
-- Cross-source identifier map + external-fetch audit. DDL follows 0004/0007:
-- uuid/identity PKs, timestamptz, jsonb default '{}', create ... if not exists, no RLS.

create table if not exists asset_identifiers (
  id uuid primary key default gen_random_uuid(),
  asset_id uuid not null references assets(id) on delete cascade,
  id_type text not null,        -- 'cik' | 'cusip' | 'coingecko_id' | 'isin'
  id_value text not null,
  source text not null,         -- 'sec_company_tickers' | 'manual'
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (asset_id, id_type)    -- upsert conflict target
);

-- Deliberately NOT unique: share classes (GOOG/GOOGL) share one CIK, so the
-- reverse lookup is one-to-many. A unique index here would reject valid data.
create index if not exists asset_identifiers_lookup_idx
  on asset_identifiers(id_type, id_value);

create table if not exists ingestion_runs (
  id bigint primary key generated always as identity,
  source text not null,         -- 'sec_edgar' | 'yfinance' | 'coingecko'
  endpoint text not null,       -- 'company_tickers' | 'companyfacts' | 'submissions'
  target_key text not null default '',   -- CIK/ticker; '' for universe-wide fetches
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null,         -- 'success' | 'failure' (spec wording; note this
                                -- deliberately differs from notifications.status 'failed')
  http_status integer,
  rows_written integer not null default 0,
  request_count integer not null default 0,
  throttle_wait_seconds numeric not null default 0,
  -- Point-in-time audit: the newest source filing date this run made available.
  -- A first-class column, not a jsonb key, because "which filing dates were
  -- available for this run" is a spec-required query.
  max_filed_date timestamptz,
  error text,                   -- never contains SEC_USER_AGENT (operator email)
  metadata jsonb not null default '{}'::jsonb  -- {unresolved_tickers: [...], failure_kind: 'rate_limited'|...}
);

-- Append-only audit: no unique constraint, so _insert_batch applies.
create index if not exists ingestion_runs_source_started_idx
  on ingestion_runs(source, endpoint, started_at desc);
-- Partial index = the incident/staleness read, mirroring 0007's cooldown index.
create index if not exists ingestion_runs_failures_idx
  on ingestion_runs(started_at desc) where status <> 'success';
```

Add `asset_identifiers` and `ingestion_runs` to `REQUIRED_ML_RELATIONS` in
`collector/schema_check.py`.

### `config/universe.sp100.json`

```json
{
  "index": "S&P 100 (OEX)",
  "snapshot_date": "2026-08-28",
  "source": "manual snapshot; S&P DJI licenses the official constituent list",
  "membership_bias": "Current membership applied to 2020-2026 history is survivorship / index-inclusion bias: constituents are the survivors and post-inclusion winners.",
  "defaults": {"provider": "yfinance", "asset_class": "stock", "interval": "1d", "start": "2020-01-01"},
  "members": [
    {"ticker": "AAPL", "name": "Apple Inc."}
  ]
}
```

### `collector/universe.py` (new) and `collector/main.py`

`collector/universe.py` must **not** import `AssetCollectionConfig` — `collector/main.py`
imports from it, so the expansion function lives in `main.py` to keep the dependency
one-way.

```python
# collector/universe.py
@dataclass(frozen=True)
class UniverseDocument:
    index: str; snapshot_date: str; source: str; membership_bias: str
    defaults: dict[str, Any]; members: tuple[dict[str, str], ...]

def load_universe_document(path: str | Path) -> UniverseDocument: ...
def universe_disclosure(doc: UniverseDocument) -> dict[str, Any]: ...  # index/snapshot_date/source/membership_bias/member_count

# collector/main.py -- one new branch, list form stays byte-identical
def expand_universe_document(raw: dict[str, Any]) -> list[AssetCollectionConfig]: ...

def load_asset_configs(path: str | None = None) -> list[AssetCollectionConfig]:
    if not path:
        return DEFAULT_ASSETS
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):                      # NEW
        return expand_universe_document(raw)
    if not isinstance(raw, list):
        raise ValueError("assets file must contain a JSON array or a universe document")
    return [AssetCollectionConfig(**item) for item in raw]
```

### `collector/providers/sec_edgar_client.py` (new)

Placed beside the price providers but **not** registered in `registry.PROVIDERS` — it does
not satisfy the `PriceProvider` protocol, so `get_provider("sec_edgar")` must keep failing.

```python
SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE  = "https://www.sec.gov"
MIN_REQUEST_INTERVAL_SECONDS = 0.11   # 10 req/s SEC ceiling, with headroom
MAX_RETRIES = 3

@dataclass(frozen=True)
class SecEdgarConfig:
    user_agent: str                    # "Name email" -- 403 without it
    @classmethod
    def from_env(cls) -> "SecEdgarConfig | None": ...   # SEC_USER_AGENT; None when blank

@dataclass(frozen=True)
class IngestionRun:
    source: str; endpoint: str; target_key: str
    started_at: datetime; finished_at: datetime
    status: str; http_status: int | None
    rows_written: int; request_count: int
    throttle_wait_seconds: float; error: str | None; metadata: dict[str, Any]
    max_filed_date: str | None = None   # populated only by fetch_submissions, from
                                         # filings.recent.filingDate (max of the list)

class IngestionRunRecorder(Protocol):
    def record(self, run: IngestionRun) -> None: ...

@dataclass
class SecEdgarClient:
    config: SecEdgarConfig | None
    session: Any = requests
    sleep: Any = time.sleep
    monotonic: Any = time.monotonic
    recorder: IngestionRunRecorder | None = None
    min_interval: float = MIN_REQUEST_INTERVAL_SECONDS

    def fetch_company_tickers(self) -> dict[str, Any]: ...   # SEC_WWW_BASE/files/company_tickers.json
    def fetch_company_facts(self, cik: str) -> dict[str, Any]: ...
    def fetch_submissions(self, cik: str) -> dict[str, Any]: ...

class SecEdgarConfigError(RuntimeError): ...   # missing/blank SEC_USER_AGENT

def pad_cik(value: str) -> str: ...   # "320193" -> "CIK0000320193"
```

**Two-tier failure contract** (the spec forces this split, and it is the right one):

- *Configuration* error — `config is None` (no `SEC_USER_AGENT`) — **raises**
  `SecEdgarConfigError` before any socket is opened, per the spec's "fails loudly …
  raises an error before sending the request". An unidentified request earns a 403 and
  burns fair-access goodwill, so this is programmer/operator error, not a runtime outcome.
  Never fabricate a default User-Agent.
- *Transport* failure — network, 403, 429, 5xx, bad JSON — **never raises**, matching
  `send_telegram_message`: `{"ok": False, "reason": ..., "detail": ...}` with `reason` in
  `sec_request_failed | sec_rate_limited | sec_client_error | sec_server_error |
  sec_invalid_json`. Success is `{"ok": True, "payload": ..., "status_code": 200}`.

Every method writes exactly one `IngestionRun` from a `finally` block — including the
`SecEdgarConfigError` path when a recorder is attached, so a misconfigured run is still
auditable. 429 backs off via `sleep` (honoring `Retry-After` when present) before retrying
up to `MAX_RETRIES`, and records `metadata.failure_kind = "rate_limited"`.
`SEC_USER_AGENT` carries the operator's email, so it is never copied into `error`,
`detail`, or `metadata`.

**Rate ceiling**: `min_interval = 0.11s` between request starts caps throughput at ~9.1
req/s, satisfying "no more than 10 requests in any rolling 1-second window" without
maintaining a sliding window.

**Bulk preference** (spec MUST): ticker→CIK resolution for ~105 tickers uses the single
`company_tickers.json` file — 1 request — never a 105-iteration `submissions` loop. The
DERA quarterly-dataset downloader is a named, deliberately unbuilt seam
(`fetch_dera_dataset`) owned by sibling `fundamental-analysis`, which is the first change
that needs history; this change ingests no history.

**Payload fidelity**: the client returns provider JSON **unmodified**. It must not flatten
or project XBRL facts — that is exactly where the per-fact `filed` date gets lost, and
`point-in-time-features` requires `filed` to survive intact to the sibling that parses it.

**Out of scope for this client**: parsing XBRL facts into `fundamental_facts` /
`fundamental_metrics`. It fetches and audits; siblings 3 and 4 parse.

### Identifier resolution job — `collector/run_identifier_resolution.py` (new)

Fetches `company_tickers.json` once, upserts `(asset_id, 'cik')` for every matched
universe ticker, and returns `{"resolved": [...], "unresolved": [...]}`. Unresolved
tickers are written to `ingestion_runs.metadata.unresolved_tickers` and printed — never
omitted from output, per spec.

### `collector/local_repository.py` (new methods, existing shapes)

```python
def upsert_asset_identifiers(self, rows, batch_size=500) -> int   # _upsert_batch(..., ("asset_id", "id_type"))
def get_asset_identifiers(self, id_type: str | None = None) -> list[dict[str, Any]]
def resolve_asset_by_identifier(self, id_type: str, id_value: str) -> dict[str, Any] | None
def insert_ingestion_run(self, source, endpoint, target_key, started_at, finished_at,
                         status, http_status=None, rows_written=0, request_count=0,
                         throttle_wait_seconds=0.0, max_filed_date=None, error=None,
                         metadata=None) -> dict[str, Any] | None   # metadata via Jsonb(_json_safe(...))
def get_recent_ingestion_runs(self, source=None, limit=50) -> list[dict[str, Any]]
```

`collector/ingestion_audit.py` (new) holds `RepositoryIngestionRecorder(repository)`
implementing `IngestionRunRecorder` over `insert_ingestion_run`.

### `brain/features.py` — one keyword-only parameter, otherwise additive

```python
FEATURE_SET_OVERLAYS_BY_ASSET_CLASS: dict[str, str] = {}   # empty here; siblings register
DEFAULT_BASE_FEATURE_SET = "technical_v2"

def feature_set_for_asset_class(asset_class, base_feature_set=DEFAULT_BASE_FEATURE_SET) -> str:
    """Policy: which set an asset SHOULD use. Never raises; unmapped class -> base."""
    return FEATURE_SET_OVERLAYS_BY_ASSET_CLASS.get((asset_class or "").strip().lower(), base_feature_set)

def feature_columns_for_set(feature_set: str, *, asset_class: str | None = None) -> list[str]:
    # asset_class is None on all 28 existing call sites -> strictly string-keyed,
    # byte-identical behavior including the ValueError for an unknown name.
    resolved = feature_set if asset_class is None else feature_set_for_asset_class(asset_class, feature_set)
    try:
        return FEATURE_COLUMNS_BY_SET[resolved]
    except KeyError as error:
        raise ValueError(f"Unknown feature_set: {resolved}. Available: {sorted(FEATURE_COLUMNS_BY_SET)}") from error

def compose_feature_set(base_feature_set: str, overlay_columns: list[str]) -> list[str]:
    """Siblings register the result under a NEW name; technical_v2 is never mutated."""
    return [*feature_columns_for_set(base_feature_set), *overlay_columns]
```

The keyword-only `asset_class` satisfies the spec's "`feature_columns_for_set` MUST
support resolving by `assets.asset_class`, in addition to by explicit name" while
preserving the rollback plan's requirement that a **stored** `model_runs.feature_set`
resolve string-only: every inference and promotion path passes `feature_set` alone, so
`asset_class is None` and no overlay can silently change a promoted model's column shape.

### `brain/retraining_job.py` / `run_retraining_job.py` / `scoped_evaluation.py`

```python
# brain/retraining_job.py -- keyword-only additions, existing call sites unchanged
def resolve_target_tickers(
    datasets, tickers: list[str] | None, *,
    default_targets: list[str] | None = None,
    max_auto_targets: int | None = None,
) -> list[str]: ...
# tickers given            -> today's behavior (intersect with available)
# default_targets given    -> intersect default_targets with available
# neither, count <= cap    -> sorted(available)  (today's behavior)
# neither, count >  cap    -> ValueError naming --tickers / --targets-file / --max-auto-targets

# RetrainingJobConfig gains:
default_targets: list[str] | None = None
max_auto_targets: int = 8
max_global_scope_assets: int = 12

# brain/scoped_evaluation.py -- keyword-only, default None = today's behavior
def select_scope_datasets(datasets, target_ticker, scope, *, max_scope_assets: int | None = None): ...
# Over the cap: keep the target, then rank the rest by (-row_count, ticker) -- deterministic,
# so a re-run reproduces the same model. Threaded through run_scoped_walk_forward_backtest
# and run_candidate_matrix; the chosen set is already reported via participating_assets.
```

`brain/run_retraining_job.py` adds `--targets-file` (default `config/targets.core.json`),
`--max-auto-targets`, `--max-global-scope-assets`. `--tickers` still wins over the file.
`config/targets.core.json` ships as `["BTC-USD", "ETH-USD", "AAPL", "MSFT"]` — the widened
universe changes nothing about what trains by default.

### Survivorship disclosure surfacing

`universe_disclosure(doc)` is embedded in the `run_retraining_job` JSON report under
`"universe"`, and served by a new `GET /api/universe` in `api/main.py`. It is **not** added
to `GET /api/assets`: that endpoint returns a bare list consumed as `Asset[]` by
`ui/src/App.tsx`, and turning it into an object is a breaking UI change for no benefit.

Per the spec's "missing snapshot date blocks disclosure-bearing output", the caveat can
never be silently omitted, on two levels: `load_universe_document` raises `ValueError` when
`snapshot_date` or `membership_bias` is absent (a malformed file fails at load, not at
report time), and a report generated with no universe document at all emits
`{"universe": {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}}`
rather than dropping the key.

## File Changes

| File | Action | Description |
|---|---|---|
| `db/migrations/0005_shared_ingestion.sql` | Create | `asset_identifiers`, `ingestion_runs` |
| `config/universe.sp100.json` | Create | ~101 members + snapshot metadata |
| `config/targets.core.json` | Create | 4-ticker training-target list |
| `collector/universe.py` | Create | Document loader + disclosure builder |
| `collector/providers/sec_edgar_client.py` | Create | Throttled, audited SEC fetcher |
| `collector/ingestion_audit.py` | Create | `RepositoryIngestionRecorder` |
| `collector/run_identifier_resolution.py` | Create | One-shot ticker→CIK job; reports unresolved |
| `collector/main.py` | Modify | `expand_universe_document` + one `isinstance(raw, dict)` branch |
| `collector/local_repository.py` | Modify | 5 methods for the two new tables |
| `collector/schema_check.py` | Modify | 2 new required relations |
| `brain/features.py` | Modify | 3 additive functions; `feature_columns_for_set` untouched |
| `brain/retraining_job.py` | Modify | `resolve_target_tickers` kwargs; 3 config fields |
| `brain/run_retraining_job.py` | Modify | 3 CLI flags; `universe` report block |
| `brain/scoped_evaluation.py` | Modify | `max_scope_assets` cap on global scope |
| `api/main.py` | Modify | `GET /api/universe` |
| `tests/test_sec_edgar_client.py` | Create | Fake session/clock/recorder |
| `tests/test_universe_config.py` | Create | Expansion + disclosure |
| `tests/test_feature_set_resolution.py` | Create | Byte-identical `technical_v2`; unmapped class |
| `tests/test_collector_job.py`, `tests/test_brain_pipeline.py` | Modify | Target/cap regression |

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | SEC client success/403/429/5xx/bad-JSON | `FakeSession` per `tests/test_collector_providers.py:23`, extended with `headers` capture; assert `User-Agent` sent |
| Unit | 10 req/s throttle | Injected `monotonic` counter + recording `sleep` (the `sleep: Any = time.sleep` pattern from `ops/telegram_notifier.py:155`); assert waits ≥ `min_interval`, zero wall-clock time |
| Unit | `ingestion_runs` on every exit path | Fake `IngestionRunRecorder` collecting `IngestionRun`s; assert one row for success **and** for each failure reason |
| Unit | Missing `SEC_USER_AGENT` | `monkeypatch.delenv`; assert `from_env() is None` and `pytest.raises(SecEdgarConfigError)`, with `FakeSession.requests == []` proving no socket was opened |
| Unit | Unresolved ticker surfacing | Fake `company_tickers` payload missing one universe ticker; assert it appears in `unresolved` **and** in `metadata.unresolved_tickers` |
| Unit | Resolution seam | `feature_columns_for_set("technical_v2")` equals the pre-change list; `feature_columns_for_set("technical_v2", asset_class="crypto"/"unknown"/None)` returns the same list without raising |
| Unit | Disclosure cannot be omitted | Universe doc without `snapshot_date` → `ValueError` at load; report with no document → `disclosure_status: "incomplete"` |
| Unit | Target policy | 100 fake datasets + no targets + cap 8 → `ValueError`; with `default_targets` → exactly those; explicit `tickers` → today's result |
| Unit | Global-scope cap | 40 datasets, cap 12 → 12 selected, target always included, stable across runs |
| Integration | Migration + schema | `py -3.14 -m db.migrate` then `py -3.14 -m collector.schema_check` on the CI Postgres service |
| Integration | Repository round-trip | Injected-connection repository (existing `TEST_DATABASE_URL` pattern): upsert same `(asset_id, 'cik')` twice → one row; two ingestion runs → two rows |

**No test may reach the real SEC API.** The universe file is loaded from a module constant
path, never a request parameter.

## CI / Security Workflows

`.github/workflows/ci.yml` is the only workflow. `backend-tests` exists to prove the
migration runner and pytest suite pass against a clean `postgres:16` service — it is the
gate that catches DDL that only works on a developer's already-migrated database.
`frontend-checks` exists to keep `ui/` lint and build green independently of Python.

No new workflow is added, and no CI change is required. Deliberately: CI does **not** set
`SEC_USER_AGENT`, so a client instantiated there returns `missing_sec_user_agent` instead
of issuing a request. A real SEC request from a shared GitHub runner IP could earn a
temporary block on an address this project does not control and cannot get unblocked.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or
process-integration boundary. Two non-matrix security requirements carry into tasks:
(1) `SEC_USER_AGENT` (operator name + email) must never be written to `ingestion_runs`,
logs, or returned dicts; (2) universe/target file paths are module constants or CLI
arguments, never request-derived.

## Migration / Rollout

Additive and reversible in this order: apply `0005` → land the universe file and the target
policy → backfill prices → run the SEC identifier resolution. `pg_dump` and tag
`pre-financial-intelligence` before the backfill. **Do not retrain on the widened universe
in the slice that adds it** — `model_runs` is append-only and a widened `global` scope
changes model semantics irreversibly. Rollback is "stop populating, drop `0005`" plus
delete-by-`asset_id` for backfilled prices.

Slicing for the 400-line budget: (1) migration + repository methods + schema check;
(2) universe file + loader + disclosure; (3) target policy + global cap; (4) SEC client +
audit recorder; (5) feature-set seam. Slice 2 is the file itself and must not be merged
with any other slice.

## Open Questions

- [ ] Exact S&P 100 snapshot content and `snapshot_date` — must be captured on the day the
      file is written, not backdated.
- [ ] `max_auto_targets = 8` and `max_global_scope_assets = 12` are proposed defaults; the
      proposal requires measuring full-retrain wall time before and after, which may move them.
