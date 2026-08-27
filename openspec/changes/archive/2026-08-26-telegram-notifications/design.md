# Design: Telegram Notifications

## Technical Approach

Three new `ops/` modules with one responsibility each — **transport** (`ops/telegram_notifier.py`),
**policy** (`ops/notification_rules.py`, stdlib-only, pure functions), **orchestration**
(`ops/notification_dispatch.py`) — plus an additive migration and five repository reads/writes.
`ops/notify_operational_job.py` becomes a two-transport fan-out over its existing, unmodified
payload builders. No job module gains notification logic: `brain/inference_job.py` only *emits*
one extra field.

Layering (no cycles; `ops/notification_rules.py` imports nothing from this project):

    api/main.py ─────────────┐
    brain/inference_job.py   ├──→ ops/notification_rules.py   (thresholds + evaluators + keys)
                             │
    ops/notify_operational_job.py ──→ ops/notification_dispatch.py
                                          ├──→ collector/local_repository.py  (rules, log)
                                          ├──→ ops/notification_rules.py      (policy)
                                          └──→ ops/telegram_notifier.py       (transport)

---

## 1. `ops/telegram_notifier.py`

```python
TELEGRAM_API_BASE = "https://api.telegram.org"
CHUNK_BUDGET_CHARS = 3800        # < 4096; see rationale
MIN_SEND_INTERVAL_SECONDS = 1.05
MAX_RETRIES = 3

@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str
    @classmethod
    def from_env(cls) -> "TelegramConfig | None": ...   # both absent/blank -> None

def escape_html(text: str) -> str: ...
def redact(text: str, token: str | None = None) -> str: ...
def chunk_message(text: str, limit: int = CHUNK_BUDGET_CHARS) -> list[str]: ...
def render_operational_message(payload: dict[str, Any]) -> str: ...
def send_telegram_message(
    text: str,
    config: TelegramConfig | None,
    *,
    session=requests,
    sleep=time.sleep,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]: ...
```

Return contract mirrors `send_notification` exactly:
`{"sent": False, "reason": "missing_telegram_config"}` when `config is None`; otherwise
`{"sent": True, "chunks": n, "status_code": 200}` or `{"sent": False, "reason": ..., "detail": ...}`.
**It never raises** — every `requests.RequestException` is caught and returned.

**HTML escaping.** Only `&`, `<`, `>`, `&` first. Applied to every interpolated value
(tickers, reasons, model names); never to the tags the renderer emits.

**Chunking.** Split on `\n`, accumulate lines up to `CHUNK_BUDGET_CHARS`; a single over-budget
line is hard-split into tagless fragments. HTML validity per chunk rests on a **renderer
invariant, not a chunk-time parser**: `render_operational_message` emits only line-scoped tags
(every `<b>`/`<code>` opens and closes inside one line), so a line-boundary split can never
orphan a tag. 3800 not 4096 because Telegram's limit applies to the parsed text while we measure
the raw string *including* markup — measuring the larger value with a margin is conservative in
the safe direction.

**Pacing.** No module-level state. `send_telegram_message` sleeps `MIN_SEND_INTERVAL_SECONDS`
*between its own chunks*; the dispatch loop sleeps between logical messages. Both take an
injectable `sleep`, so tests record intervals and never wait.

**429 / retries.** On 429, read `response.json()["parameters"]["retry_after"]` (fallback 1),
`sleep(retry_after)`, retry; bounded at `max_retries`, then
`{"sent": False, "reason": "telegram_rate_limited"}`. 5xx retries with a fixed 2s. Other 4xx does
not retry.

**Token redaction — every error path.** The token is in the URL *path*, so `response.url`,
`requests.HTTPError` strings, and connection errors all carry it by default. Defenses, in order:

1. The URL is built inside a private `_endpoint(token)` and **never** stored in a returned dict,
   log line, or `notifications` row.
2. `redact(text, token)` does an exact `str.replace(token, "***")` — Telegram tokens match
   `\d+:[A-Za-z0-9_-]{35}`, all URL-safe, so no percent-encoded variant can exist and exact
   replacement is complete.
3. `redact` *also* applies `re.sub(r"bot\d+:[\w-]+", "bot***", ...)` as a structural fallback for a
   token that arrived by another route (nested exception, a second token).
4. Every `except` branch returns `redact(str(error), token)`, never the exception object.

`redact` is the **only** sanitization point; `insert_notification` trusts its `error_reason`.

---

## 2. Transport refactor of `ops/notify_operational_job.py`

| | Before | After |
|---|---|---|
| `build_notification_payload` | builds payload | **unchanged** (now uses `load_reports`) |
| `summarize_report` / `summarize_issue` | — | **unchanged** |
| `load_reports(dir) -> dict[name, raw]` | inline glob | extracted, shared with the dispatcher |
| `send_notification(payload, url, *, session)` | the only transport | **unchanged** — generic webhook |
| `send_telegram_notification(payload, config, *, session, sleep)` | — | new; renders + delegates |
| `dispatch_notification(payload, *, webhook_url, telegram_config, session, sleep)` | — | new fan-out |
| `main()` | one result | `{"notification": {"webhook": {...}, "telegram": {...}, "rules": {...}}, "payload": ...}` |

Each transport is called independently inside its own guard, so one failing transport never
suppresses the other. `build_notification_payload` is untouched, so the payload builders are shared
**by construction**, not by copy — and the three existing tests in
`tests/test_operational_notifications.py` pass verbatim, proving the refactor is additive.

**No `--telegram-bot-token` CLI flag.** A flag would put the token in the Windows process table,
Task Scheduler's stored action, and every scheduler log. Config comes from
`TelegramConfig.from_env()` only. New flags are `--no-telegram` and `--no-rule-notifications`.

**Credential boundary:** `telegram_config` never enters `payload`, so the generic webhook (a
third-party URL) cannot receive Telegram credentials. Enforced by a test.

**DB optionality:** `main()` attempts a connection inside a `try`; on failure the rule dispatch
records `{"dispatched": False, "reason": "database_unavailable"}` and the plain webhook path still
runs. An install without Postgres, without Telegram, or without both behaves exactly as today.

---

## 3. `db/migrations/0007_notifications.sql`

```sql
create table if not exists notification_rules (
  id uuid primary key default gen_random_uuid(),
  rule_type text not null,
  asset_id uuid references assets(id) on delete cascade,   -- null = global rule
  channel text not null default 'telegram',
  params jsonb not null default '{}'::jsonb,
  cooldown_minutes integer not null default 1440,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Two partial indexes, not `unique (rule_type, asset_id, channel)`: Postgres treats
-- NULLs as distinct in a UNIQUE constraint, so two identical *global* rules would both
-- be allowed. `unique nulls not distinct` needs PG15+; partial indexes work on any version.
create unique index if not exists notification_rules_scoped_key
  on notification_rules(rule_type, asset_id, channel) where asset_id is not null;
create unique index if not exists notification_rules_global_key
  on notification_rules(rule_type, channel) where asset_id is null;
create index if not exists notification_rules_active_idx
  on notification_rules(rule_type) where is_active;

create table if not exists notifications (
  id bigint primary key generated always as identity,
  rule_id uuid references notification_rules(id) on delete set null,
  rule_type text not null,          -- denormalized: log survives rule deletion,
  asset_id uuid references assets(id) on delete set null,  -- and cooldown needs no join
  scope_key text not null default '',   -- sub-asset cooldown scope (model_name, job_mode)
  channel text not null,
  dedupe_key text not null,
  severity text not null default 'info',
  title text not null,
  body text not null,
  status text not null,             -- 'sent' | 'failed'
  error_reason text,
  payload jsonb not null default '{}'::jsonb,
  fired_at timestamptz not null default now()
);

-- PARTIAL unique: only *delivered* messages dedupe. A plain `unique(dedupe_key)` would let
-- one failed attempt permanently block the retry of that same alert — a Telegram outage would
-- silently swallow a P0 forever. Failures accumulate as history; exactly one send survives.
create unique index if not exists notifications_dedupe_sent_key
  on notifications(dedupe_key) where status = 'sent';

-- Exact shape of the cooldown read. Partial on 'sent' for the same reason: a failed
-- delivery must not start a cooldown window.
create index if not exists notifications_cooldown_idx
  on notifications(rule_type, asset_id, scope_key, fired_at desc) where status = 'sent';

insert into notification_rules (rule_type, channel, params, cooldown_minutes) values
  ('job_failure',          'telegram', '{"min_failed": 1}'::jsonb, 0),
  ('signal_action_change', 'telegram', '{"min_confidence": 0.55, "actions": ["BUY", "SELL"]}'::jsonb, 0),
  ('model_degradation',    'telegram', '{"min_feedback_samples": 20, "min_accuracy": 0.45, "min_mean_outcome_return": 0.0}'::jsonb, 1440),
  ('stale_prices',         'telegram', '{"max_price_age_hours": 72.0}'::jsonb, 1440)
on conflict do nothing;
```

Bare `on conflict do nothing` (no inferred target) covers any unique violation across both partial
indexes — belt-and-braces beyond `schema_migrations`, for a dropped-and-recreated database.
DDL follows `0004_paper_trading.sql`: `uuid`/identity PKs, `timestamptz`, `jsonb default '{}'`,
`create ... if not exists`, no RLS.

`collector/schema_check.py` gains `notification_rules` and `notifications` in
`REQUIRED_ML_RELATIONS` — every install runs `db.migrate` regardless of Telegram config, so their
absence means the DB is behind, which is precisely what schema_check reports.

---

## 4. Dedupe key composition

**The spine of the design:** `dedupe_key = scope + bucket`; the **cooldown key is the scope alone**.
Two mechanisms over one decomposition (§5).

    dedupe_key = "|".join([rule_type, ticker or "-", scope_key or "-", discriminator or "-", bucket])

`|` as the separator, not `:` — ISO timestamps contain `:`. Tickers uppercased, `rule_type`
lowercased, all dates `YYYY-MM-DD` **UTC** (a local-time bucket would double-fire or skip a day
around midnight/DST). No hashing: every component is bounded far below btree's ~2704-byte key
limit, and a readable key is directly greppable in the delivery log.

| rule_type | scope_key | discriminator | bucket | Why this granularity |
|---|---|---|---|---|
| `job_failure` | `{job_mode}` | sorted failing step names, `,`-joined | run date | Same failure set on the same day is one incident; a *different* step failing fires immediately. **Counts excluded** — 3 failures ticking to 4 is the same outage. A week-long outage yields 1/day, which is correct for a P0 and not fatigue. |
| `signal_action_change` | `{model_name}` | `{prev}>{new}` | **prediction** date | The transition *is* the event. Bucketing on the prediction's own bar date (never `now()`) makes re-running `brain.run_inference_job` on the same bar idempotent. `model_name` not `model_run_id`: a version bump should not re-announce a position you already hold. **Confidence excluded** — 0.61 re-scoring to 0.63 is the same signal. |
| `model_degradation` | `{model_name}` | `{alert_code}` | today | `low_accuracy` and `negative_edge` are distinct conditions and must each alert, hence the code. **Measured value excluded** — a drifting number is the same condition. `scope_key = model_name` so degradation of model A cannot mask model B. |
| `stale_prices` | `''` | `''` | **last price date** (or `none`) | The fatigue-critical case. Bucketing on *today* would alert every day forever on a dead feed and `cooldown_minutes` could not stop it. Bucketing on the last observed price date fires **once per staleness episode** and re-arms only when the feed recovers and then goes stale at a new date. |

The staleness tradeoff is deliberate: a feed dead for months alerts once. The standing indicator
stays where it already is — `GET /api/alerts/{ticker}` shows it continuously. Telegram carries the
*transition*; the dashboard carries the *state*.

---

## 5. Cooldown vs dedupe — two distinct mechanisms

| | Dedupe | Cooldown |
|---|---|---|
| Question | "Is this the *same event* I already sent?" | "Have I sent *anything* for this scope too recently?" |
| Key | `dedupe_key` (scope **+ bucket**) | `(rule_type, asset_id, scope_key)` (scope **only**) |
| Enforcement | `notifications_dedupe_sent_key` — **database** | `SELECT max(fired_at)` + compare — **Python** |
| Configurable | No (code-defined recipe) | Yes (`notification_rules.cooldown_minutes`) |
| Wrong-too-tight | duplicate alerts | duplicate alerts |
| Wrong-too-loose | a real second event is swallowed **permanently** | a real second event is delayed one window |

Evaluation order in `ops/notification_dispatch.py`, **dedupe first**:

```python
for rule in repository.get_active_notification_rules(channel="telegram"):
    for event in evaluate(rule, context, now=now):          # pure, no I/O
        if repository.notification_already_sent(event.dedupe_key):
            outcomes.append("deduped"); continue
        last = repository.get_last_notification_fired_at(
            event.rule_type, event.asset_id, event.scope_key)
        if last and (now - last) < timedelta(minutes=rule["cooldown_minutes"]):
            outcomes.append("cooldown"); continue           # NOT persisted — see below
        result = send_telegram_message(render(event), config, session=session, sleep=sleep)
        repository.insert_notification(..., status="sent" if result["sent"] else "failed",
                                       error_reason=result.get("detail"))
        sleep(MIN_SEND_INTERVAL_SECONDS)
```

- **Order matters.** Cooldown-first would let a genuinely new event (new `dedupe_key`) be
  suppressed inside another event's window and then fire later out of context. Dedupe-first
  rejects an exact repeat cheaply and permanently without consuming a cooldown decision.
- **Cooldown-suppressed events are never inserted.** A suppression row would carry the same
  `dedupe_key` as the eventual real send and collide with the partial unique index, making
  suppression permanent. Suppression is reported in the dispatch return value and stdout JSON only.
- **`cooldown_minutes = 0` (both P0 rules)** makes the cooldown check a no-op, so dedupe is the
  sole gate for P0 — intentional, that is what "immediate" means here.
- **Comparison in Python, query in SQL.** The repository stays a dumb read (matching every other
  method in `LocalPostgresRepository`, where policy lives in the caller) and `now` stays injectable,
  so cooldown tests need no DB clock and no `freezegun` dependency.
- **Accepted limitation:** `SELECT`-then-`INSERT` is TOCTOU-racy. The unique index closes the
  window on the *record*, not on the *send*, so a true race could deliver twice while persisting
  once. The scheduler runs its steps sequentially in one process on one machine, so this is
  theoretical; documented rather than papered over.

---

## 6. Repository methods (`collector/local_repository.py`)

New `# -- Notifications ---` section between "Risk profiles" and "Schema introspection".
All parameterized, `dict_row`, wrapped by the existing `_cursor()` seam (so the injected-connection
test path works unchanged); `jsonb` via `Jsonb(_json_safe(...))`.

```python
def get_active_notification_rules(self, rule_type=None, channel=None) -> list[dict[str, Any]]:
    # conditions/params/where_clause idiom copied from get_model_runs
    "SELECT id, rule_type, asset_id, channel, params, cooldown_minutes "
    "FROM notification_rules WHERE is_active [AND rule_type = %s] [AND channel = %s] "
    "ORDER BY rule_type ASC, asset_id ASC NULLS FIRST"

def notification_already_sent(self, dedupe_key: str) -> bool:
    "SELECT 1 FROM notifications WHERE dedupe_key = %s AND status = 'sent' LIMIT 1"

def get_last_notification_fired_at(
    self, rule_type: str, asset_id: str | None = None, scope_key: str = ""
) -> datetime | None:
    # Branch on NULL instead of `IS NOT DISTINCT FROM`: btree cannot serve that operator,
    # so the branch is what keeps notifications_cooldown_idx usable.
    "SELECT max(fired_at) AS fired_at FROM notifications "
    "WHERE rule_type = %s AND asset_id IS NULL|= %s AND scope_key = %s AND status = 'sent'"

def insert_notification(
    self, rule_id, rule_type, asset_id, scope_key, channel, dedupe_key,
    severity, title, body, status, error_reason=None, payload=None,
) -> dict[str, Any] | None:
    """Returns the inserted row, or None when the partial unique index rejected a
    duplicate *sent* delivery (the caller reports 'raced_duplicate')."""
    "INSERT INTO notifications (...) VALUES (...) "
    "ON CONFLICT (dedupe_key) WHERE status = 'sent' DO NOTHING RETURNING *"
    # The index predicate must be restated for Postgres to infer a partial unique index.

def get_latest_price_timestamps(self) -> list[dict[str, Any]]:
    """One row per asset for the staleness check — including assets with zero prices."""
    "SELECT a.id AS asset_id, a.ticker, max(p.timestamp) AS latest_price_at "
    "FROM assets a LEFT JOIN prices p ON p.asset_id = a.id "
    "GROUP BY a.id, a.ticker ORDER BY a.ticker ASC"
```

`get_latest_price_timestamps` replaces N calls to `get_prices(limit=1)` with one query and, via the
`LEFT JOIN`, distinguishes *no prices at all* (critical, matching `build_operational_alerts`'
`no_prices`) from *stale*. No rule-write method: seeding is in SQL and tuning is manual `psql`.

---

## 7. Integration points for the four triggers

**Shared threshold source (settled requirement).** `ops/notification_rules.py` holds the canonical
defaults — `DEFAULT_MAX_PRICE_AGE_HOURS = 72.0`, `DEFAULT_MIN_FEEDBACK_SAMPLES = 20`,
`DEFAULT_MIN_ACCURACY = 0.45`, `DEFAULT_MIN_MEAN_OUTCOME_RETURN = 0.0`, plus `SEEDED_RULE_PARAMS`.
The two consumers bind differently and deliberately:

| Consumer | Binding | Drift impossible because |
|---|---|---|
| `api/main.py` alerts endpoint | `Query(default=DEFAULT_MIN_ACCURACY, ...)` — an **import** | compile-time reference; no test needed |
| `db/migrations/0007_notifications.sql` seed | a SQL literal | a **test** parses the literals and asserts equality with `SEEDED_RULE_PARAMS` |

Rejected: importing `api.main.build_operational_alerts` into a CLI job (pulls FastAPI and
`app = FastAPI(...)` import-time wiring into every scheduler subprocess). Rejected: duplicating the
numbers (the exact silent drift the orchestrator forbade). Per-rule `params` jsonb still overrides
at runtime, so a threshold is tunable without a deploy.

**A. Job failure — `ops/run_local_scheduler.py`.** ⚠️ **This file does not exist yet: it is task 9
of `local-postgres-migration`.** The seam is therefore designed to be a *one-argv-element* change
there, and this change ships and tests without it. The scheduler's final step is already
`ops.notify_operational_job --reports-dir reports`; `build_notification_payload` already aggregates
`failed` across every report JSON and names each report. So job-failure evaluation runs entirely
inside the notifier, from data it already has. The only gap is a step that crashed *before* writing
a report — covered by an optional new flag the scheduler appends to its existing fixed argv list:

    ops.notify_operational_job --reports-dir reports --status failure --failed-steps brain.run_inference_job

`--failed-steps` is optional; absent, the rule falls back to the report-derived `failed > 0`.
**Dependency to flag to sdd-tasks:** if `local-postgres-migration` task 9 lands with a different
final-step argv, only that one line needs adjusting.

**B. Signal action transition — `brain/inference_job.py`.** *How the previous action is retrieved:*
inside `run_latest_inference_job`, call the **existing**
`repository.get_latest_prediction(asset_id, model_name=model_run["model_name"])`
**immediately before** `generate_latest_prediction` — that call upserts into `predictions`, so
reading after it would return the new row. Add
`"previous_action": previous.get("predicted_action") if previous else None` to the `results` entry.
That is the *entire* change to this file: it emits data, it never notifies. Two useful properties
fall out: re-running the job on the same bar reads back its own row, so `previous == new` and no
transition is detected (defense in depth, independent of dedupe); and a first-ever prediction gives
`previous_action = None`, which fires only for BUY/SELL, never HOLD. The dispatcher reads
`reports/inference_job.json` via the shared `load_reports`.

**C. Model degradation — `brain/feedback_report.py` is NOT modified.** *Deviation from the
proposal's Affected Areas, with reason:* `feedback_report.py` is a human-invoked CLI report writer,
not a scheduler step, so no `reports/feedback_report.json` exists during an unattended run —
alerts would fire only when someone ran the report manually. Instead the dispatcher calls
`repository.get_prediction_feedback(only_evaluated=True)` once, groups by `model_name`, and runs
`brain.feedback.analyze_prediction_feedback` per group — the **same function**
`feedback_report.py` calls, so the CLI report and the alert agree by construction. Below
`min_feedback_samples` produces **no** event, matching `build_operational_alerts` treating
`insufficient_feedback` as `info`.

**D. Staleness.** No existing module; evaluated in the dispatcher from
`repository.get_latest_price_timestamps()`, one row per asset, comparing against
`max_price_age_hours` from `rule["params"]`. A global rule (`asset_id IS NULL`) fans out to every
asset, emitting one event per stale asset with that asset's `asset_id`; a scoped rule checks only
its asset.

**Latency note:** all four dispatch from the notifier step, so "P0 immediate" means *same scheduler
run*, not sub-second. A standalone `py -3.14 -m brain.run_inference_job` outside the scheduler does
not alert — a deliberate consequence of "Telegram is a transport inside the existing notifier".

---

## 8. Testing strategy

| File | Layer | What / How |
|---|---|---|
| `tests/test_telegram_notifier.py` | unit, no DB | `FakeResponse`/`FakeSession` with a `post(url, json, timeout)` recorder, mirroring `tests/test_collector_providers.py`. Escaping (`&` first, only `&<>`); chunk order + reassembly + a single 5000-char line hard-split; injected `sleep` sees one `>=1.0` gap between two chunks and **zero** for one chunk; 429 + `retry_after: 2` then 200 → `sent`, `post` called twice, `sleep` saw 2; 4×429 → `telegram_rate_limited`, never raises, exactly `MAX_RETRIES+1` posts; `from_env()` with `monkeypatch.delenv` → `None` → `missing_telegram_config`. |
| ↳ **redaction test** | unit | `FakeSession.post` raises `HTTPError(f"...for url: .../bot{TOKEN}/sendMessage")` → assert `TOKEN not in json.dumps(result)` **and** `"***" in result["detail"]`. Second case: a 400 body echoing `response.url`. Third: the persisted `error_reason` for that failure contains no token. |
| `tests/test_operational_notifications.py` | unit, no DB | Existing three tests **unchanged** (proof the refactor is additive). Both transports unconfigured → two no-ops, nothing raised. Webhook `post` raising → Telegram still attempted. **Credential boundary:** with `TELEGRAM_BOT_TOKEN` set, the JSON body posted to the generic webhook contains neither token nor chat id. |
| `tests/test_notification_rules.py` | unit, no DB, `now` injected | The four `dedupe_key` recipes, `@pytest.mark.parametrize`. **The fatigue assertion:** the staleness key is unchanged when `now` advances a week and changes only when `last_price_date` changes. HOLD→HOLD → no event; BUY→SELL → one; `previous_action=None` + HOLD → none, + BUY → one. Degradation below `min_accuracy` → `low_accuracy`; `evaluated < min_feedback_samples` → none. **Drift test:** `json.loads` every `'{...}'::jsonb` literal parsed in order out of `db/migrations/0007_notifications.sql` equals `SEEDED_RULE_PARAMS`. (Adding another jsonb literal to `0007` breaks this test — that is the point.) |
| `tests/test_notification_dispatch.py` | integration, **real test DB** | Reuses `repository` / `db_connection` / `test_database_url` from `tests/conftest.py` — per-test `BEGIN`/`ROLLBACK`, auto-skipped when Postgres is unreachable, migrations applied once per session. Seeded rules readable via `get_active_notification_rules()`. Two `sent` inserts, same key → second returns `None`, one row. Two `failed` inserts, same key → **both** rows, then a `sent` with that key succeeds. `get_last_notification_fired_at` returns `None` when only `failed` rows exist. Cooldown: a `sent` row at `now - 30min`, cooldown 1440 → `cooldown`; cooldown 0 → proceeds. A global and a scoped rule of the same `rule_type` do not suppress each other; two `model_degradation` events with different `scope_key` do not suppress each other. End-to-end: a `failed > 0` report → exactly one `FakeSession.post` and one `sent` row; re-invoke → zero posts, still one row. |

Command: `py -3.14 -m pytest` (`strict_tdd: false` — tests accompany implementation).
No new test dependency: time is injected as a `now` parameter rather than adding `freezegun`.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `ops/telegram_notifier.py` | Create | Transport: HTML, chunking, pacing, 429 backoff, redaction |
| `ops/notification_rules.py` | Create | Canonical thresholds, pure evaluators, `dedupe_key` recipes (stdlib only) |
| `ops/notification_dispatch.py` | Create | Rules → evaluate → dedupe → cooldown → send → log |
| `db/migrations/0007_notifications.sql` | Create | Both tables, partial unique indexes, four seeded active rules |
| `ops/notify_operational_job.py` | Modify | `load_reports` extraction, `send_telegram_notification`, `dispatch_notification`, two new flags |
| `collector/local_repository.py` | Modify | 5 methods in a new `# -- Notifications ---` section |
| `collector/schema_check.py` | Modify | +2 entries in `REQUIRED_ML_RELATIONS` |
| `brain/inference_job.py` | Modify | Emit `previous_action` (read before `generate_latest_prediction`) |
| `api/main.py` | Modify | 4 `Query(default=...)` values reference `ops.notification_rules` constants (**scope delta vs. the proposal** — required by the single-shared-source decision) |
| `brain/feedback_report.py` | **Unchanged** | Deviation from the proposal, justified in §7-C |
| `ops/run_local_scheduler.py` | Modify (blocked) | One argv element: `--failed-steps`. File is task 9 of `local-postgres-migration` |
| `.env.example`, `README.md` | Modify | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; BotFather + chat-id setup, `/revoke` |
| `tests/test_telegram_notifier.py`, `tests/test_notification_rules.py`, `tests/test_notification_dispatch.py` | Create | See §8 |
| `tests/test_operational_notifications.py` | Modify | Fan-out + credential-boundary tests appended |

**CI/security workflows.** No workflow is added or changed. `.github/workflows/ci.yml` (lint +
`pytest`) exists as this change's regression gate — the new DB tests self-skip there because
`tests/conftest.py` skips when `TEST_DATABASE_URL` is unreachable, so CI keeps proving the
unit-level chunking, 429, redaction, and dedupe-recipe behavior without a Postgres service.
No secret is added to any workflow: the bot token is `.env`-only and never reaches CI.

---

## Threat Matrix

| Boundary | Applicability | Reason |
|---|---|---|
| Documentation-like paths | **N/A** | No file-classification or execution-by-extension logic. |
| Git repository selection | **N/A** | No `git` invocation anywhere in this change. |
| Commit state | **N/A** | No VCS automation. |
| Push state | **N/A** | No VCS automation. |
| PR commands | **N/A** | No PR automation. |

The subprocess row is borderline and resolved as N/A: this change adds one *fixed literal* argv
element (`--failed-steps` plus a comma-joined list drawn from the scheduler's own closed set of
step names) to an existing fixed-argv `subprocess.run` list owned by `local-postgres-migration`
(D13, never `shell=True`). No user-controlled string reaches argv.

Real boundaries for this change, each with a planned test (§8):

| Boundary | Safe behavior | Failure behavior | Test |
|---|---|---|---|
| Credential in the URL path | Token never in a return value, log, DB row, or webhook payload | `redact()` on every error path; BotFather `/revoke` if leaked | redaction test + credential-boundary test |
| Third-party payload egress | The generic webhook receives only `payload` | Telegram config is a separate argument, never merged | credential-boundary test |
| SQL injection | Every statement parameterized `%s`; identifiers via `psycopg.sql.Identifier` | Follows the existing repository, no string interpolation of values | covered by the integration tests |
| Untrusted text in HTML | `escape_html` on every interpolated value | Renderer emits only line-scoped tags | escaping + chunking tests |

---

## Migration / Rollout

`0007` is additive and unreferenced by existing code. `db/migrate.py` applies pending files
lexicographically, so the `0005`/`0006` reservation gap is safe and later arrivals still apply.
Rollout order: apply the migration → `collector.schema_check` → run with no Telegram env vars (must
be a byte-for-byte no-op) → set the two variables → force `failed > 0` and confirm one message →
re-run and confirm silence. Rollback per the proposal: unset the env vars, or
`update notification_rules set is_active = false`, or drop `notifications` then
`notification_rules` and delete the `0007` row from `schema_migrations`.

## Open Questions

- [ ] Should `stale_prices` add escalation buckets (7d / 30d) so a permanently dead feed re-alerts?
      Current design alerts exactly once per episode; the dashboard is the standing indicator.
- [ ] Extracting `build_operational_alerts`' body from `api/main.py` into a shared pure module
      would make degradation/staleness zero-drift *by construction* rather than by shared
      constants. Larger refactor of `api/main.py`; deliberately deferred, not blocking.
- [ ] `--failed-steps` is the contract this change asks of `local-postgres-migration` task 9.
      Confirm before apply, or the P0 job-failure trigger degrades to report-derived `failed > 0`.

## Review Budget Forecast (input to sdd-tasks)

~1230 authored lines across 14 files — well over the 400-line budget. Recommended slices:
**(1)** `0007` migration + 5 repository methods + `schema_check` + `tests/test_notification_dispatch.py`;
**(2)** `ops/telegram_notifier.py` + `tests/test_telegram_notifier.py`;
**(3)** `ops/notification_rules.py` + `ops/notification_dispatch.py` + notifier refactor + the four
wiring touches + remaining tests.
