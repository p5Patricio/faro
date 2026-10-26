# Feature: new-machine-handoff

## Objective

Move the whole project to a new computer without losing anything and let a fresh AI agent
continue with full context: a reproducible, verified transfer bundle (database, trained models,
private documents, agent memory), complete up-to-date documentation (`AGENTS.md` as the single
entry point) and everything pushed to GitHub so the repo can be cloned.

## Why the bundle exists (decisions)

- The repo is **public**: no personal data, secrets, database dumps or private documents in git.
  `private/` is now ignored by `.gitignore` (it was only in the local `.git/info/exclude`, which a
  clone does not have).
- Outside git and needed on the new machine: the database (PostgreSQL 18, ~1.2M rows), `models/`
  (225 trained `.joblib` files, ~500 MB; `model_runs.artifact_uri` stores relative paths and the
  inference loads them from disk), `private/` (CFDI, statements, constancias), `.env` (secrets),
  Engram memory for project `faro`.
- `.env` is never copied by tooling; the user carries it by hand. `.env.example` lists the keys.
- The bundle is built into a local folder that is NOT synced to any cloud; the user moves it (USB).
- The bundle is repeatable (`ops/prepare_transfer.ps1`) because data keeps changing until cutover.

## Scope

- T1 `ops/transfer.py` (`manifest`, `verify`, `restore`) + tests, `ops/prepare_transfer.ps1`.
- T2 Documentation: `AGENTS.md` (decisions, tools, context, pending, proposals), `docs/MIGRACION-NUEVA-PC.md`,
  `docs/ROADMAP.md` status, `.env.example`, `.gitignore`, stale root docs marked as historical.
- T3 Real run: bundle, restore into a scratch database, verify against the manifest, drop scratch.
- T4 PR to `main`.

## Effective settings

- TDD off; Workflow v2. Runners: backend `py -3.14 -m pytest -q`; UI in `ui/`.
- No AI attribution in commits or PR text (user rule; it overrides any harness suggestion).

## Checklist

- [x] T1 transfer tooling (delegated writer) — route: delegated; docs written in parallel by the parent
- [x] T2 documentation
- [x] T3 real bundle + restore verification
- [ ] T4 PR (opened; waiting for the user to merge)

## Progress

- 2026-10-26: document created. Findings: repo public; `models/` 500 MB outside git; `private/`
  only ignored locally; no personal identifiers in tracked files (only the public SAT generic RFC).
- 2026-10-26: T1 by one delegated writer (12 tests, ruff clean); parent review fixed two details (script pointed to a
  non-existent `.env.example` -> `docs/env.template`; `--keep 3` -> `--keep 1` because the manifest matches only the newest
  dump). `.env.example` could not be created (the user's permission rules protect `.env*`), hence `docs/env.template`.
- 2026-10-26: T3 real run. Bundle built at `C:\Traspaso-Faro` (db 174 MB, models 500.7 MB, private 1.1 MB, Engram export of 105
  observations; 287 files, all SHA-256 verified; no `.env` inside). Restore of the dump into a scratch database: 36 tables,
  1,241,133 rows, md5 of 33 tables, 18 migrations and extensions all match the manifest (~53 s). The restore refuses a
  non-empty database (exit 2) and `verify` detects one altered row (exit 1). Scratch database dropped. `engram import` was
  not run here, to avoid duplicating the live memory.
- 2026-10-26: also added `cfdi_documents` and `retention_documents` to the JSON export in `ops/backup_db.py`; removed one real
  figure from `fiscal-documents-ui.md` (the repo is public). Full backend suite: 991 passed.
