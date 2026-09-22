# Archive Report: Professional Improvements Foundation

**Date**: 2026-09-02
**Change**: professional-improvements-foundation
**Status**: ARCHIVED AND CLOSED

## Final State Summary

This was the first professional-improvements change (created 2026-07-12). All
work was implemented and verified PASS at the time. It established the OpenSpec
SDD scaffolding, the `professional-operations` capability spec, PR-check CI
(`.github/workflows/ci.yml`), Dependabot (`.github/dependabot.yml`), and the
`CONTRIBUTING.md` / `SECURITY.md` / `CHANGELOG.md` maintainer docs. Those
deliverables are all still present on disk.

It sat unarchived through three later changes (`local-postgres-migration`,
`telegram-notifications`, `financial-intelligence-expansion`) that archived
ahead of it. Archiving it now, its spec delta was updated first: the original
"Secret-Free CI" requirement was written for the Supabase era and has since been
superseded by the stronger **Pull Request Quality Gates** and **Local Scheduled
Operations Replace Hosted Automation** requirements that `local-postgres-migration`
merged into the main spec. That one delta requirement is therefore dropped as
superseded rather than merged.

## Specs Merged

### Modified Capability: professional-operations

- **File**: `openspec/specs/professional-operations/spec.md` (merged, ADDED-only)
- **Merged**: two genuinely net-new requirements —
  - **SDD Change Tracking**: professional-improvement work is tracked through
    OpenSpec artifacts before implementation.
  - **Maintainer Guidance**: the repository documents contribution, security,
    and release-history expectations; `.env` and any secret MUST NOT be committed
    (the original "private Supabase keys" wording generalised — there is no
    Supabase).
- **Dropped as superseded**: "Secret-Free CI" — the base spec's later
  "Pull Request Quality Gates" requirement (local/ephemeral Postgres, zero cloud
  secrets) is the current, stronger acceptance criterion.

## Verification Status

**Original verdict** (`verify-report.md`): PASS — `py -3.14 -m pytest` 131 passed,
`npm run lint` PASS, `npm run build` PASS, `git diff --check` PASS, GitHub Actions
CI run PASS.

**At archive time**: the suite has grown to ~350 passing tests across the three
later changes; nothing in this change was reverted. `ci.yml` and `dependabot.yml`
remain in place; the `operational-jobs.yml` Supabase cron this change never
touched was removed by `local-postgres-migration`.

## Phase Completion

All tasks `[x]` in `tasks.md`:

- **Phase 1**: `openspec/config.yaml`, `openspec/specs/professional-operations/spec.md`,
  and the change artifacts.
- **Phase 2**: `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`; README /
  `PLAN_DESPLIEGUE.md` / `ESTADO_PROYECTO.md` links and stale-item cleanup.
- **Phase 3**: `.github/workflows/ci.yml` (backend pytest + frontend lint/build),
  `.github/dependabot.yml` (pip, npm root, npm ui, GitHub Actions).
- **Phase 4**: verification run + `verify-report.md`.

## Artifacts Archived

Change folder moved from `openspec/changes/professional-improvements-foundation/`
to `openspec/changes/archive/2026-09-02-professional-improvements-foundation/`:

- proposal.md
- specs/professional-operations/spec.md (rewritten on archive with a supersession note)
- design.md
- tasks.md (all phases complete)
- verify-report.md
- state.yaml (`status: archived`, `progress.archive: complete`)

## Key Learnings

1. A change that stays unarchived while sibling changes ship and archive can end
   up with a spec delta that partly contradicts the base spec the siblings have
   since strengthened. On archive, reconcile the delta against the current base
   spec — merge only what is still net-new, drop what has been superseded.
2. `openspec/config.yaml`'s `context:` block is not spec — it is free-text stack
   context — but it still drifts. Refreshed here alongside the archive
   (Supabase/GitHub-Actions-cron -> local Postgres / local scheduler).

## Archive Complete

This change is fully archived and closed. No further work is required.

---

**Archived by**: Claude Code orchestrator (direct archive, not a sub-agent), per
the 2026-09-02 SDD Session Preflight (pace: auto, artifacts: hybrid, delivery:
auto-chain, review budget: 400).
**Main spec updated**: `openspec/specs/professional-operations/spec.md` (2 requirements merged)
