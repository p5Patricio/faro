# Feature: fiscal-documents-ui

## Objective

Let the user upload their fiscal XMLs from the app and see what they mean: broker constancias
(CFDI de Retenciones) reconciled against the investment ledger, and expense invoices (CFDI 4.0)
summarized by personal-deduction use. Both backends exist (`/api/investments/retentions`,
`/api/finance/cfdi`); there is no UI for either.

## Scope (one PR, branch `claude/fiscal-documents-ui`)

- Backend polish on the retention reconciliation: one generic-RFC warning per issuer and year
  (not one per document); report the interest real loss (`loss_cents` of the interest complement)
  on the `interest` row.
- Investments view: "Constancias fiscales" panel — upload one or more retention XMLs, year
  selector, documents list, reconciliation table (constancia vs libro, difference, status) and
  warnings.
- Finance view: "Facturas (CFDI)" panel — upload one or more CFDI 4.0 XMLs, year selector,
  documents list and the personal-deduction summary by `UsoCFDI` with the cash-payment flag.
- Spanish (Mexico, "tú") UI copy; informational disclaimers; accessible file inputs and tables.
- Tests: one per rule plus one rendering scenario per panel (Vitest); backend rules in pytest.

Out of scope: bank statement importers (waiting for the user's Nu and BBVA files).

## Constraints

- Files are read in the browser and sent as text to the local API; nothing leaves the machine.
- No real personal data in fixtures. Money stays in integer cents until formatting.

## Effective settings

- TDD off; Workflow v2 (one writer, tests <= source lines, full suites once per PR).
- Runners: backend `py -3.14 -m pytest -q`; UI `npm run lint`, `npm test`, `npm run build` in `ui/`.

## Checklist

- [x] F1 Backend: grouped warnings + interest real loss — route: delegated writer
- [x] F2 Constancias panel (investments) — route: same writer
- [x] F3 Facturas panel (finance) — route: same writer
- [x] F4 Full suites, build, browser check on the always-on app with the real imported data

## Progress

- 2026-10-12: document created. Carried over from `gbm-retention-import` R4: migration 0018
  applied to the real DB and the 6 real constancias imported (no duplicates on re-import).
- 2026-10-12: F1-F3 by one delegated writer (targeted: pytest 10 passed, vitest 14 files passed, lint and tsc
  clean). Parent checks: backend 979 passed; UI lint clean, 150 tests passed, build OK. Browser check on
  the always-on app with the real imported data: the 2024 constancias show one grouped generic-RFC warning,
  the reconciliation rows (all `sin_libro`) and the interest real loss (9.86); the Facturas tab renders its
  empty state for 2026. Only console error: the pre-existing `/api/predictions` CORS one (unrelated).
