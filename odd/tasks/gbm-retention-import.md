# Feature: gbm-retention-import

## Objective

Import a broker's annual CFDI de Retenciones 2.0 XML (constancias: interest, dividends, sale of
shares) and reconcile its totals against Faro's investment ledger for the same year, so the user
knows before filing that what the broker reported to the SAT matches their own records.

## Problem and why

The user's broker (GBM) issues yearly CFDI de Retenciones per concept. Today Faro can only read
CFDI 4.0 expense invoices. Without importing the retention CFDIs there is no automatic check
between the broker's figures and the ledger. Real files (2024, 2025) exist locally in the
gitignored `private/gbm/constancias/`; the 2024 ones were issued to the generic RFC
`XAXX010101000`, which the import must flag.

## Scope (this PR: backend only)

- Pure stdlib parser for CFDI de Retenciones 2.0 with the `intereses`, `dividendos` and
  `enajenaciondeacciones` complements; refuses DOCTYPE; money to integer cents (half-up).
- Migration `0018`: `retention_documents`, idempotent by stamp UUID.
- API under `/api/investments/retentions`: `PUT` one XML, `GET ?year=` with documents and a
  reconciliation against the ledger worksheet. 503 until `0018` is applied.
- Tests: one per rule plus one end-to-end scenario, synthetic fixtures only (invented RFC/UUID).

Out of scope: UI (next PR), automatic correction of ledger rows, tax computation.

## Constraints

- Informational only; never a tax verdict. Money in integer cents / `Decimal`, never float.
- No real personal data in the repo; fixtures use invented RFCs and UUIDs.
- Migration applied to the real DB only after a backup and the user's confirmation.

## Effective settings

- TDD: off (project setting, see `faro-macro-finance-expansion.md`). Runners: backend
  `py -3.14 -m pytest -q`. Workflow v2: one writer, tests <= source lines, full suite once per PR.
- Delivery: one PR, base `main`, branch `claude/retention-import`. The user reviews.

## Checklist

- [x] R1 Parser + reconciliation (pure) — route: delegated writer (2+ non-trivial files)
- [x] R2 Migration 0018 + repository + API router + AGENTS.md row — route: same writer
- [x] R3 Tests (synthetic fixtures) + full backend suite: 978 passed
- [ ] R4 Apply 0018 to the real DB (backup + user confirmation), import the 6 real XMLs locally,
      report the reconciliation for 2024 and 2025

## Acceptance criteria

- Parsing the three complement types yields year, concept, totals and complement amounts in cents.
- A receiver RFC equal to `XAXX010101000` is flagged.
- Re-importing the same UUID does not duplicate.
- `GET ?year=` returns per-concept constancia vs ledger amounts and their difference.

## Progress

- 2026-10-12: document created; structure of the real XMLs mapped (element and attribute names
  only).
- 2026-10-12: R1-R3 done by one delegated writer (targeted tests: 25 passed). Parent check: the
  parser reads all 6 real GBM XMLs read-only (2024 flagged as generic RFC). Parent fix: dividends
  are reconciled on `MontoTotOperacion` (dividend paid), because `MontDivAcumNal` is grossed up
  (x 1.4286, LISR art. 140) and would never match the ledger; the accumulable amount is reported
  as `constancia_accumulable_cents`. Full backend suite: 978 passed.

## Next step

R4 needs the user's confirmation to apply `0018` to the real database (after a backup).
