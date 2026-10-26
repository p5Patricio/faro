# Changelog

All notable project changes should be documented here.

## Unreleased

### Added

- Personal finance: ledger, budgets, net worth, recurring bills, goals, Telegram expense bot.
- Markets and macro: Panorama, heatmap with real market caps (US, Mexico, Canada), US and Mexico inflation and rates.
- Investment ledger (average cost per account, MXN gains with dated FX, FIBRAs, interest, dividends) and yearly worksheets; migrations `0016`-`0018`.
- CFDI 4.0 invoice importer and CFDI de Retenciones (broker constancias) importer with reconciliation against the ledger; UI panels in Finanzas and Inversiones.
- Verified Mexico tax parameters and calendar (`config/tax/`) and the official CFDI catalog (`config/sat/`); research in `docs/sat/`.
- Local database backup (`ops/backup_db`), daily backup task, and a verified machine-transfer bundle (`ops/transfer.py`, `ops/prepare_transfer.ps1`).
- `AGENTS.md` as the single entry point for agents, `docs/MIGRACION-NUEVA-PC.md`, `docs/env.template`, `docs/ROADMAP.md`.

### Changed

- Walk-forward evaluation takes an embargo; the backtest has a real buy-and-hold baseline and per-stride Sharpe annualization.
- Migration checksums ignore CRLF; `*.sql` files are kept LF (`.gitattributes`).
- Scheduled tasks run if missed and on battery.
- The API rejects unexpected `Host` headers and ignores `X-Forwarded-For` unless `API_TRUST_PROXY` is set.

### Fixed

- `/api/predictions/{ticker}` returned a 500 for un-evaluated predictions (NaN in JSON).
- Quantities in the investments view are shown without trailing zeros.

## 2026-07-11

### Added

- Professional improvement roadmap covering CI, data quality, drift monitoring, advanced models, model registry, shadow mode, observability, security, and broker-readiness.

## 2026-07-08

### Added

- Supabase RLS hardening for public market/model tables.
- Incumbent comparison guard for re-training promotion.
- Daily operational and weekly controlled retraining schedules.
- Optional operational webhook notifications.
