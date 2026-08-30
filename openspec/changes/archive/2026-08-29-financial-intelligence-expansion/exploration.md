# Exploration: financial-intelligence-expansion

Date: 2026-08-25

Scope researched: (1) fundamental/financial-statement analysis for buy-sell decisions,
(2) copy trading of professional investors, (3) Telegram notification bot,
(4) personal finance tracking + optional Gemini AI.

## Current State (verified in repo)

The pipeline is price-only. `brain/features.py` holds `FEATURE_COLUMNS_BY_SET =
{"technical_v1": [...15 cols], "technical_v2": [...25 cols]}` — all derived from OHLCV.
`assets.asset_class` already exists (`stock | crypto | etf`) and
`collector/main.py:AssetCollectionConfig` already carries it, but **nothing branches on
it** — every asset gets the same feature set. `collector/providers/yfinance_provider.py`
calls only `yf.download()`; no financial-statement call exists anywhere.

`ops/notify_operational_job.py` is a ~100-line `requests.post(webhook_url, json=payload)`
notifier. Zero Telegram references exist — this is greenfield, not completion.

Persistence is mid-migration. All new tables must land as new `db/migrations/000N_*.sql`
files **after 0004**, never as edits to existing ones.

---

## AREA 1 — Fundamental analysis

### Factors with documented predictive value

| Factor | Source | Needs |
|---|---|---|
| **Piotroski F-Score** (9 binary tests) | Piotroski (2000); high-minus-low spread ~23%/yr, t=5.59 | Income + balance + cash flow, 2 consecutive years |
| **Altman Z-Score** | Altman (1968); distress predictor doubling as value screen | Balance + income + market cap |
| **Gross profitability** (GP/Assets) | Novy-Marx (2013), "the other side of value" | Revenue, COGS, total assets |
| **Cash-based operating profitability** | Ball, Gerakos, Linnainmaa & Nikolaev (2016) | Income + cash flow |
| **Accruals anomaly** | Sloan (1996) | Balance-sheet deltas |
| **Magic Formula** | Greenblatt (2005); practitioner-grade | Income + balance + market cap |
| **Composite Mispricing Score** | Stambaugh, Yu & Yuan (2015) | All of the above |

F-Score and gross profitability are the highest value-per-unit-of-effort — both
computable from ~10 XBRL concepts.

### Data source: SEC EDGAR, not yfinance

**yfinance is unusable as a training source** for fundamentals, for three reasons in
order of severity:
1. It returns only the **latest restated** statements — no filing date, no revision
   history. You cannot reconstruct what was knowable on a past date.
2. It carries ~4 annual / ~5 quarterly periods — nowhere near enough for walk-forward.
3. It is an unofficial scrape intended for personal, non-commercial use.

**SEC EDGAR XBRL is the correct source.** Free, no API key, requires a declared
`User-Agent` (`"Name email"`); requests without one return 403. Fair-access ceiling is
**10 req/s** per IP; exceeding it returns 429 and can trigger a temporary IP block.

- `https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digit}.json` — every XBRL fact ever filed
- `https://data.sec.gov/api/xbrl/companyconcept/CIK{...}/us-gaap/{Concept}.json` — one concept
- `https://data.sec.gov/submissions/CIK{...}.json` — filing index
- `https://www.sec.gov/files/company_tickers.json` — ticker → CIK map
- Bulk: SEC DERA quarterly Financial Statement Data Sets (preferred over per-company loops)

The decisive property: every fact carries `{start, end, val, accn, fy, fp, form, filed}`.
**`filed` is what makes bias-free fundamentals possible.**

### The look-ahead trap — the most important finding

Two independent leaks, both must be closed.

**Leak 1 — timing.** Fundamentals become public a **median ~66 days after period end**;
10-Qs run 40-45 days, 10-Ks 60-75. A feature row for Q1 stamped `2026-03-31` encoding Q1
revenue asserts knowledge the market did not have until roughly June. `features_daily` is
keyed `(asset_id, timestamp, feature_set)` and `brain/scoped_evaluation.py` splits
walk-forward on that `timestamp` — a naive period-end join leaks into **every** fold and
inflates **every** backtest.

**Leak 2 — restatement.** Even a correctly date-joined series leaks if the *values* are
restated ones. Companies revise; vendors silently overwrite history.

**Mandatory fix:**
- Store facts **as filed**, keyed by `(cik, concept, period_start, period_end, unit,
  accession_number)`, with `filed_date` first-class. Never UPDATE — a restatement is a
  new row with a new accession number.
- Materializing for date `D`: select `filed_date <= D`, take the latest `period_end`
  among those, then the **earliest** `filed_date` for that period (original, not restatement).
- Set `features_daily.timestamp` for fundamental sets to the **filing date**, not period
  end. Fundamental features become sparse and step-shaped — correct, not a bug.
- Add a safety lag (`filed_date + 1 trading day`) so a same-day filing isn't traded at that day's open.
- **Unit test**: assert `max(source_filed_date) <= feature_timestamp` for every generated
  fundamental row. This single test separates an honest backtest from a fantasy.

### Per-asset-class reality — one uniform fundamental set cannot exist

**ETFs have no earnings; crypto has no financial statements at all.** Forcing one schema
produces mostly-NULL columns that either crash scikit-learn or get imputed to zeros the
model happily learns from.

| Class | Analogue | Free source | Feature set |
|---|---|---|---|
| **Stock** | Real statements | SEC companyfacts (point-in-time) | `fundamental_v1` |
| **ETF/index** | Expense ratio, AUM, holdings, sector weights, tracking error, premium/discount | `Ticker.funds_data` (top 10 holdings only), issuer CSVs | `fund_profile_v1` |
| **Crypto** | Supply schedule, circulating vs max, holder distribution, NVT, network activity | CoinGecko free (~10k calls/mo, ~30/min) | `crypto_onchain_v1` |

**Approach:** keep `technical_v2` as the universal spine; treat each fundamental set as an
**additive overlay resolved by `assets.asset_class`**, with `feature_columns_for_set` as
the single resolution point. Train **separate models per (asset_class, feature_set)** —
already supported, since `brain/scoped_evaluation.py` has an `asset_class` scope.

Sequencing: stocks first (best data, best literature), ETFs second, crypto last (weakest
evidence; CoinGecko gates the interesting endpoints behind paid tier).

### Honest limitations
- Only AAPL and MSFT have fundamentals. ~4 filings/yr = tiny-sample regime. F-Score is a
  0-9 integer; it will not carry a daily model. Fundamentals belong as **slow-moving
  regime/quality gates layered over technical signals**, not standalone daily predictors.
- Cross-sectional factors are **ranking devices** for universes of hundreds. With 2
  stocks there is nothing to rank. Either widen the universe substantially or use
  fundamentals as absolute-threshold filters ("no long if Z-Score < 1.8").
- XBRL concept names are not uniform (`Revenues`, `RevenueFromContractWithCustomer...`,
  `SalesRevenueNet`). Needs a per-concept fallback chain with logging of unresolved concepts.

---

## AREA 2 — Copy trading

### The expectation gap — state before anything else

**Public-data copy trading is not mirroring. It is archaeology.**

Form 13F is filed by managers with ≥$100M in 13(f) securities, **within 45 days after
quarter end**. A position opened 1 January appears publicly by 15 May — **up to ~135 days
stale**. The manager may have exited entirely.

It is partial even then. 13F **omits**: short positions entirely (those go to confidential
Form SHO under Rule 13f-2, published only in aggregate), non-US holdings, most
derivatives, cash, bonds, currencies, commodities, and sub-threshold positions.

**A 13F showing "80% long tech" may belong to a market-neutral fund that is 80% short tech
through instruments you cannot see. Following it naively can be the exact inverse of the
manager's actual bet.** This is the single most important disclosure in this exploration.

### What the research supports

- **Cohen, Polk & Silli (2010)** — managers' *highest-conviction* positions generate
  significant risk-adjusted returns; the rest of the portfolio does not.
- **Verbeek & Wang (2013)** — copycats of past-winning funds beat most real mutual funds
  net of costs, precisely by avoiding fees.
- Consistent caveat: mechanical whole-portfolio replication is **ineffective** due to lag
  and incompleteness. Concentration on high-conviction, low-turnover, long-only managers
  is what survives.

**Form 4** (insider transactions) is the genuinely timely signal: **2 business days**.
Insider *purchases* predict 4-8% abnormal returns over 6-12 months, strengthened when
multiple insiders buy simultaneously; insider *sales* carry weak-to-zero signal (sales
happen for diversification, taxes, option exercises). **Model buys, ignore sells.**

**Schedule 13D/13G** tightened in 2024: 13D initial now **5 business days**, amendments
**2 business days**; 13G for qualified institutions 45 days after quarter end. 13D is the
activist signal and is timely enough to matter.

### Access (all free, User-Agent required, 10 req/s)
- **Bulk 13F**: SEC DERA quarterly Form 13F Data Sets — `COVERPAGE` + `INFOTABLE` TSVs.
  One zip per quarter beats thousands of per-filer requests.
- **Per-filer**: `data.sec.gov/submissions/CIK{padded}.json` → filter `form` for `13F-HR`,
  `4`, `SC 13D`. Form 4 XML has clean `<nonDerivativeTransaction>` (code `P` = purchase,
  `S` = sale).
- **Full-text search** (`efts.sec.gov`): undocumented and unversioned — best-effort only,
  **never a pipeline dependency**.

### Commercial alternatives — out of scope
eToro CopyTrader and ZuluTrade require funded real-money brokerage accounts and execute
real orders. This project is local-only, no real money, no cloud. Architecturally and
legally out of scope. **No free API provides real-time professional positions — that data
is the product these platforms sell.**

### Recommended design: "Institutional Consensus Tracker", not "Copy Trading"

What it can truthfully offer:
1. **Conviction tracking** — position weight as % of manager's 13F portfolio across
   quarters for ~10-30 curated long-only, low-turnover managers. Entries, exits, >25% changes.
2. **Consensus overlap** — how many tracked managers hold a ticker, and the QoQ delta.
3. **Insider buy alerts** — T+2, cluster detection. **The only genuinely timely piece.**
4. **Activist alerts** — new 13D on watchlist tickers (T+5 business days).
5. **Overlap with own holdings** (needs Area 4's real-holdings table).
6. **A permanent, non-dismissible staleness badge**: `as of {period_end} · filed
   {filed_date} · {n} days stale`.

Must **not** claim: live mirroring, real-time following, "invest like Buffett automatically."

Backtesting: same point-in-time discipline. A consensus feature for date `D` uses only
filings with `filed_date <= D`. The 45-day lag must be **preserved** in the backtest, or
the equity curve is fiction.

---

## AREA 3 — Telegram bot

### Verified facts
- Token from BotFather; `POST https://api.telegram.org/bot{TOKEN}/sendMessage`.
- **4096 characters** max per message; formatting entities can exceed the byte limit
  before the visible character count — chunk conservatively.
- Rate limits: **~1 msg/sec per chat**, **20 msg/min per group**, **~30 msg/sec global**.
- `parse_mode`: **use `HTML`**. `MarkdownV2` requires escaping 18 characters including
  `.`, `-`, `(`, `)` — which appear constantly in tickers, percentages and prices. HTML
  needs only `&`, `<`, `>`.

### Architecture: long polling, decisively

Webhooks require a publicly reachable HTTPS endpoint with a valid certificate on port
443/80/88/8443. On a NAT'd Windows home machine that means either a tunneling service (an
external cloud dependency, violating local-only) or router port-forwarding plus a
certificate (**inbound attack surface on a machine holding personal finance data**). You
also cannot use long polling while a webhook is set — the choice is exclusive.

Long polling via `getUpdates` works behind NAT with zero inbound exposure, no certificate,
no domain, no third party.

**Split outbound from inbound:**
- **Outbound-only** (send an alert) needs *no polling at all* — a plain `POST
  /sendMessage` from the existing scheduler. Ship this first.
- **Inbound** (`/signals`, `/portfolio`) needs a long-running `getUpdates` loop with
  `timeout=30`. Separable work unit; must not gate the first.

### Library: thin `requests` client

`python-telegram-bot` v22 is **asyncio-only since v20** — no synchronous API. Every
synchronous `python -m` job would need an `asyncio.run()` wrapper. That is a genuine
architectural mismatch in a codebase where every entry point is a synchronous CLI job.

Recommend `ops/telegram_notifier.py` (~60 lines + ~40 for chunking/retry/429 backoff),
mirroring `ops/notify_operational_job.py`'s injectable-session signature so the existing
`FakeSession` test pattern applies. **Generalize the existing notifier** — add Telegram as
a *transport* alongside the generic webhook, sharing `build_notification_payload` /
`summarize_report`. Config via `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; absent → silent
no-op, matching the existing `{"sent": False, "reason": "missing_webhook_url"}` pattern.

### Notification catalog

| Priority | Trigger | Source | Cadence |
|---|---|---|---|
| P0 | Job failure / `failed > 0` | `ops/run_local_scheduler.py` | per run |
| P0 | New BUY/SELL crossing confidence threshold | `brain/inference_job.py` | daily |
| P1 | Model degradation (accuracy/profit factor below floor) | `brain/feedback_report.py` | daily |
| P1 | Stale data — no new price row for N days | freshness check | daily |
| P1 | Insider cluster buy on watchlist | Area 2 Form 4 | T+2 |
| P2 | Model promotion/demotion | `brain/promotion.py` | on event |
| P2 | 13F consensus changes | Area 2 | quarterly |
| P2 | Price threshold crossed | new alert-rule table | daily |
| P3 | Weekly digest | aggregate | weekly |

**Not** notified: every HOLD, every price tick. Alert fatigue kills the channel. Add a
per-rule cooldown so a persistent condition fires once, not daily.

---

## AREA 4 — Personal finance + Gemini

### Data model: hybrid single-entry — recommended

GnuCash, Beancount and Firefly III use **double-entry** (transaction → ≥2 splits summing
to zero). Actual Budget and most consumer trackers use **single-entry**.

| Approach | Pros | Cons |
|---|---|---|
| Full double-entry | Self-balancing; correct paycheck splits, partial refunds, multi-currency | Every write ≥2 rows + balance constraint; ~2× query complexity; ceremony with no auditor to satisfy |
| Pure single-entry | Trivial entry; direct map to a one-line form and to LLM categorizer output | Self-transfers double-count; no invariant to catch entry errors |
| **Hybrid: single-entry + `transfer_group_id`** | Keeps the simple case simple; links the two legs of a self-transfer; upgradeable later without data loss | Not a true accounting invariant |

**Recommend the hybrid.** This project's auditability requirement is about the trading
signal, not the grocery ledger. The nullable `transfer_group_id` costs nothing and closes
the one real correctness hole.

### The investment bridge

Tracking real purchases unlocks what the platform cannot currently do: **compare its own
signals against actual behaviour.**

Model real holdings **strictly separate from paper trading.** `paper_trading_runs` /
`paper_trading_events` are a *simulation artifact* — parameterized, regenerated per run,
disposable. Real holdings are **ground truth**, append-only, never recomputed. Conflating
them would let a backtest re-run silently mutate the record of what you actually own.

- `portfolio_transactions` — immutable log of real BUY/SELL/DIVIDEND/FEE
- `portfolio_holdings` — derived current position, recomputed from the log

Enables: signal-vs-action divergence ("model said SELL AAPL on 2026-03-04, you still
hold"), realized vs paper-simulated return, unrealized P&L in the Telegram digest, and
"3 tracked institutions exited a position you hold."

**Caveat:** personal transactions are **not** training data — a handful of rows with a
selection bias of exactly one person. Reporting and alerting only; never join into
`features_daily`.

### Gemini — verified

- SDK: `pip install google-genai`; `from google import genai; client = genai.Client(...)`.
  The older `google-generativeai` is superseded.
- Free tier: Flash and Flash-Lite only — **Pro moved behind billing as of May 2026**.
  Roughly 10 RPM / 250k TPM / 1,500 RPD for Flash. Authoritative live figure is the AI
  Studio dashboard, not any doc page.
- Pin an explicit model version string in config, never an alias — a silent model swap
  would invalidate every cached extraction.
- Structured output: `types.GenerateContentConfig(response_mime_type="application/json",
  response_schema=PydanticModel)`. Pydantic is already a dependency. This is what makes
  LLM output safe to persist.
- Requires an API key and outbound internet — a real deviation from local-only. Must be
  **explicitly optional, disabled by default**; absent key → feature unavailable.

**Ranked uses:** (1) transaction categorization — batch 50 per call with a category enum
schema; **cache by normalized merchant** so the LLM is called almost never after warm-up.
(2) Natural-language explanation of an already-emitted signal. (3) Filing summarization
into features — viable but treacherous. (4) Weekly digest prose.

### Should an LLM emit the trading signal? — No. Firmly no.

In favour, fairly stated: LLMs read unstructured text no numeric feature captures, reason
across heterogeneous evidence, and the free tier makes experimentation cheap.

Against, and decisive **for this project**:
1. **Non-determinism destroys reproducibility.** The repo's discipline is
   `model_runs(name, version, params, metrics, artifact_uri)` + `predictions` +
   `prediction_feedback`. Re-running a version on the same data must give the same answer.
   A remote API gives no such guarantee, even at temperature 0.
2. **Fundamentally un-backtestable.** You cannot ask a model trained through 2026 what it
   would have said in 2019 — *it knows what happened*. This is the most severe and least
   detectable class of look-ahead bias, and the exact error Area 1 works hard to eliminate.
   Building a rigorous point-in-time XBRL pipeline and then letting an LLM emit the signal
   would be self-defeating.
3. **Cannot be walk-forward validated.** There is no "retrain" for an API-hosted model, so
   it cannot enter `brain/scoped_evaluation.py` at all.
4. **No feature attribution, no promotion criteria.** `PromotionCriteria` cannot be
   evaluated for something with no reproducible historical track record.
5. **Availability coupling.** Hard-depending on an external API breaks local-only and adds
   a failure mode to the one thing that must be reliable.

**Boundary — the LLM sits on both edges, never in the middle:**

```
UPSTREAM (allowed, conditional)     CORE (LLM forbidden)        DOWNSTREAM (allowed)
────────────────────────────        ────────────────────        ────────────────────
Filing/news text                    features_daily              predictions
  ↓ LLM extract                       ↓                           ↓ LLM explain
llm_extractions (cached,            model_runs (sklearn)        prose in UI + Telegram
 schema-constrained, versioned,       ↓
 stamped with source_filed_date)    predictions
  ↓ deterministic transform           ↓
features_daily                      backtests / paper_trading
```

**Upstream conditions, all mandatory:** (a) schema-constrained output via
`response_schema`, never free text; (b) every extraction persisted in a versioned
`llm_extractions` table keyed by source hash + prompt version + model ID, so the pipeline
reads the *cache*, never the API, and is deterministic on re-run; (c) stamped with the
source document's `filed_date` so Area 1's point-in-time join applies unchanged; (d) any
feature set with LLM-derived columns is a *separate, named* set that competes against the
pure-numeric one in the existing candidate matrix — if it doesn't win out-of-sample, it
isn't promoted.

Downstream explanation is unconditional: it reads a final decision and produces text. If
Gemini is unreachable, the signal still exists; only the prose is missing.

---

## Consolidated new tables

All as new `db/migrations/` files after `0004_paper_trading.sql`, following existing
conventions (identity/uuid PKs, `timestamptz`, `jsonb default '{}'`, explicit `unique(...)`
for upsert conflict targets).

### `0005_fundamentals.sql`
| Table | Purpose |
|---|---|
| `asset_identifiers` | ticker → CIK / CUSIP / CoinGecko id. Needed by Areas 1 **and** 2 |
| `fundamental_facts` | **Append-only** raw XBRL as filed. The point-in-time backbone |
| `fundamental_metrics` | Derived per-filing scores (F-Score, Z-Score, gross profitability, accruals) |
| `fund_profiles` | ETF snapshots — expense ratio, AUM, NAV, top holdings, sector weights |
| `crypto_metrics` | Supply, market cap, on-chain metrics |
| `ingestion_runs` | Audit of every external fetch — makes staleness and rate-limit incidents visible |

`features_daily` needs **no schema change** — the `feature_set` discriminator and
`features` jsonb already accommodate new sets. New rows use **`filed_date` as `timestamp`**.

### `0006_institutional.sql`
| Table | Purpose |
|---|---|
| `institutions` | Curated watchlist of tracked 13F filers |
| `institutional_filings` | One row per 13F-HR submission — the lag ledger |
| `institutional_holdings` | INFOTABLE rows (cusip, value, shares, discretion) |
| `institutional_position_changes` | Derived QoQ deltas (NEW/EXIT/INCREASE/DECREASE) — what UI and alerts read |
| `insider_transactions` | Form 4 — the only near-real-time signal |
| `ownership_filings` | 13D/13G stakes |

### `0007_notifications.sql`
| Table | Purpose |
|---|---|
| `notification_rules` | What to alert on, per channel, with cooldown |
| `notifications` | Delivery log with `dedupe_key` — prevents re-sends, gives an audit trail |

Bot token and chat id live in `.env`, **not** the database.

### `0008_personal_finance.sql`
| Table | Purpose |
|---|---|
| `finance_accounts` | Bank/cash/card/brokerage |
| `finance_categories` | Hierarchical, `kind` = income/expense/transfer |
| `finance_transactions` | Single-entry signed amount + nullable `transfer_group_id` |
| `finance_budgets` | Monthly limit per category |
| `portfolio_transactions` | **Real** trades — immutable ground truth |
| `portfolio_holdings` | Derived current real position |
| `merchant_category_map` | Learned merchant → category cache; why the LLM is called almost never |
| `llm_extractions` | Cache + audit of every Gemini call. **Makes the LLM deterministic on re-run** |

---

## Recommended sequencing

Dependency-ordered with an early Telegram slice:

`0005` shared infra + stock fundamentals → **Telegram outbound-only** (small, unblocks
alerting for everything after) → Form 4 insiders (timely, strong literature) → personal
finance + real holdings → 13F consensus → ETF/crypto profiles → Gemini categorization →
Gemini explanation.

Each slice independently shippable and revertible; alerting exists before the
alert-worthy features do; highest-evidence signals land before the weakest; Gemini last
and fully optional.

**Blocking dependency:** all of this lands **after** `local-postgres-migration` completes.
That change deletes `supabase/`, establishes `db/migrations/` + `LocalPostgresRepository`.
Writing new tables against the Supabase schema now guarantees conflicts in exactly the
files that change most.

## Four non-negotiables for propose/design

1. **`filed_date` is the timestamp for every externally-sourced feature.** Not period end.
   Enforce with a test.
2. **Feature sets branch on `assets.asset_class`.** One uniform fundamental schema is not
   achievable and produces silent NULL-imputation bugs.
3. **Rename the copy-trading feature** to "Institutional Consensus Tracker" with a
   permanent staleness badge.
4. **The LLM never emits a signal.**

## Risks

- **Look-ahead bias is the dominant technical risk** — silent failure mode; backtests look
  excellent and mean nothing.
- **Expectation gap on copy trading** — real-time mirroring is impossible with free public data.
- **13F omits shorts** — a long-only reading of a market-neutral fund can be the exact inverse.
- **Universe too small** for cross-sectional factors (2 stocks). Decide in propose, not later.
- **SEC 10 req/s** — a naive per-company loop over a widened universe trips it. Prefer DERA bulk.
- **EDGAR full-text search undocumented/unversioned** — never a pipeline dependency.
- **yfinance unofficial scrape**, personal-use only — argues for EDGAR as source of record.
- **Gemini breaks local-only** — must be optional, disabled by default, cache-backed.
- **Scope ~10× the 400-line PR budget** — needs aggressive slicing.
- **`local-postgres-migration` unmerged** — schema work before it lands guarantees conflicts.

## Open questions for propose

1. Is an "institutional consensus tracker" (45-day-lagged 13F + T+2 insider alerts)
   acceptable in place of live mirroring?
2. Widen the stock universe beyond AAPL/MSFT? Cross-sectional fundamental factors are
   ranking devices that need a real universe to function.

## Ready for Proposal

Yes, pending the two questions above.
