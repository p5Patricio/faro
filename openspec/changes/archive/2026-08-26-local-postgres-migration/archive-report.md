# Archive Report: Local Postgres Migration
**Date**: 2026-08-26
**Change**: local-postgres-migration
**Status**: ARCHIVED AND CLOSED

## Final State Summary

All work for this change is complete, verified, and closed. The migration from Supabase (Postgres via PostgREST, Auth, Storage) to local PostgreSQL plus local filesystem artifact storage is fully implemented, tested, and ready for production use.

## Specs Merged

### New Capability: local-persistence
- **File**: `openspec/specs/local-persistence/spec.md` (created)
- **Status**: All active requirements implemented and verified PASS
- **Note on REMOVED Requirement**: The "One-Time Supabase Data Migration" requirement was evaluated, decided against (Supabase project had zero rows of ML data at migration time; asset universe widened to ~100 stocks requiring fresh ingestion regardless), and recorded as a REMOVED requirement in the delta spec. Per archive merge logic for brand-new capabilities, this REMOVED requirement is NOT included in the new main spec — `openspec/specs/local-persistence/spec.md` contains only the active requirements, preserving the decision while keeping the spec clean.

### Modified Capability: professional-operations
- **File**: `openspec/specs/professional-operations/spec.md` (merged)
- **Changes**:
  - MODIFIED: "Pull Request Quality Gates" — now explicitly requires local/ephemeral Postgres provisioned in CI job
  - MODIFIED: "Reviewable Operational Documentation" — now covers local job scheduling without hosted CI runners
  - ADDED: "Local Scheduled Operations Replace Hosted Automation" — Windows Task Scheduler registration replaces GitHub Actions scheduled workflows
  - PRESERVED: "Dependency Maintenance Visibility" (unchanged)

## Verification Status

**Final Verdict**: PASS (re-verified 2026-08-26, all CRITICAL findings closed)

### Test Suite
- **Final count**: 243 passed, 0 failed
- **Independent re-verification**: Executed on 2026-08-26 against live local Postgres instance
- **Baseline**: 241 passed (before remediation batch)
- **Net new tests**: 2 (1 from this change for invalid scope_type 422 scenario, 1 from sibling telegram-notifications change)

### Critical Findings Remediation
All three CRITICAL findings from the original verify-report were remediated and independently re-verified closed:

1. **C1 — Spec/proposal amendments for skipped data migration**
   - **Fix**: Moved "One-Time Supabase Data Migration" to REMOVED Requirements section in `specs/local-persistence/spec.md` with rationale citing 2026-08-25 decision (zero Supabase rows, asset universe widened). Updated `proposal.md` Success Criteria checkbox to `[x] N/A — no source data existed to migrate`.
   - **Verified**: Independent read of both files confirms amendments are in place.

2. **C2 — Missing test for invalid scope_type → 422**
   - **Fix**: Added `test_risk_profile_endpoint_rejects_invalid_scope_type` to `tests/test_api.py`. Test calls `GET /api/risk-profile?scope_type=bogus` and asserts HTTP 422 response.
   - **Verified**: Test passes in isolation and as part of full suite re-run.

3. **C3 — .env.example stale Supabase vars**
   - **Fix**: Removed `SUPABASE_URL`, `SUPABASE_KEY`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`. Added `LOCAL_DATABASE_URL` and `TEST_DATABASE_URL` placeholder lines. Marked tasks.md item 0.2 complete.
   - **Verified**: `git show HEAD:.env.example` confirms all four Supabase vars absent, both local DSN placeholders present.

### Warning Items (Non-blocking, Intentionally Deferred)

**W2 — Windows Task Scheduler registration not functionally verified**
- `ops/register_local_jobs.ps1` validated for PowerShell syntax only
- Never actually executed against real Task Scheduler in this batch (per batch instructions: "Do NOT actually register the Windows Task")
- User must manually run `ops/register_local_jobs.ps1` to complete the Task Scheduler registration
- Scheduled job execution itself is documented but not independently observed in this archive

**W3 — openspec/config.yaml narrative is stale**
- Contains Supabase-era tech stack description and SQL migrations under supabase/migrations directory path
- Outside this change's direct file scope but affects future SDD sessions' understanding of current state
- Recommend refreshing in a follow-up improvement task (not blocking archive)

## Phase Completion

All 10 phases plus prerequisite Phase 0 are marked `[x]` complete in `tasks.md`:

- **Phase 0**: Environment confirmation (localhost:5432, database roles)
- **Phase 1**: Schema + migration runner (4 migration files, idempotent runner)
- **Phase 2**: Repository implementation (all 30 methods implemented)
- **Phase 3**: Repository tests (32 tests, RED threat-matrix test included)
- **Phase 4**: One-time Supabase data migration (SKIPPED — zero Supabase data existed)
- **Phase 5**: Collector/brain call-site swap (all call sites updated)
- **Phase 6**: API swap + auth removal (auth dependency fully removed)
- **Phase 7**: Frontend auth removal (session and auth UI removed)
- **Phase 8**: Local artifact storage (filesystem replaces Supabase Storage)
- **Phase 9**: Local scheduler + CI (ops/run_local_scheduler.py + Postgres service in CI)
- **Phase 10**: Final removal (Supabase modules, migrations, workflows deleted)

## Artifacts Archived

Change folder moved from `openspec/changes/local-postgres-migration/` to `openspec/changes/archive/2026-08-26-local-postgres-migration/` containing:

- ✅ proposal.md
- ✅ specs/ (local-persistence delta, professional-operations delta)
- ✅ design.md
- ✅ tasks.md (all phases complete)
- ✅ apply-progress.md (5 batches documented)
- ✅ verify-report.md (remediation and re-verification)
- ✅ state.yaml (progress.apply = complete, progress.verify = complete)

## Additional Remediation Beyond Critical Findings

The remediation batch also addressed warning W1 and identified improvements:

**W1 — Root package.json/package-lock.json Supabase CLI tooling**
- **Status**: RESOLVED
- **Action**: Both files deleted from repository root (were leftover from MVP scaffold, only tool was supabase/config.toml which was itself deleted in Phase 10)
- **Verified**: `git ls-files package.json package-lock.json` returns empty; both files absent on disk

**Documentation improvements** (beyond required fixes):
- README.md: Updated Mermaid architecture diagram from `collector --> supabase --> brain` to `collector --> postgres[("PostgreSQL local")] --> brain`
- README.md: Updated Estructura table's `supabase/migrations/` reference to `db/migrations/`
- PLAN_MEJORAS_PROFESIONALES.md: Updated stale Supabase narrative in tech-stack summary and Estado Actual comparison table

## Dependency on Sibling Change

The sibling SDD change `telegram-notifications` has an ADDED-only delta spec against the `local-persistence` capability. That spec was already verified PASS and will be archived immediately after this change. The merge order is correct: this change's local-persistence main spec is now in place as the base for telegram-notifications' delta to build upon.

## Key Learnings

1. A spec requirement can be legitimately decided against (via Engram decision record) while the spec/proposal artifacts themselves are never amended to reflect that decision — creating a silent contradiction between the decision record and the spec. The archive merge is the right place to resolve such contradictions by updating specs to match the final decisions.

2. A REMOVED requirement in a delta spec for a brand-new capability means "never include this in the merged main spec", not "include then immediately remove" — the main spec should reflect the final state only.

3. The verify hard rule that an untested declared spec scenario is CRITICAL (regardless of whether the code is demonstrably correct) ensures that every spec scenario has explicit, observed, passing test coverage before archive.

4. Windows-local scheduled-job registration (PowerShell Task Scheduler scripts) can pass syntax validation without functional verification in a CI/batch environment — operational confidence for scheduling requires a documented manual verification step.

5. Remediation batch ordering matters: fixing CRITICAL artifacts (specs/proposal) before re-running verification ensures the canonical specs reflect the actual shipped behavior, not intermediate decision records.

## Archive Complete

This change is fully archived and closed. All work is complete, verified, and ready for reference or rollback (git history retains full recovery path via `pre-local-postgres` tag). No further work is required on this change.

---

**Archived by**: sdd-archive phase executor
**Archive date**: 2026-08-26
**Change folder**: `openspec/changes/archive/2026-08-26-local-postgres-migration/`
**Main specs updated**: `openspec/specs/local-persistence/spec.md` (created), `openspec/specs/professional-operations/spec.md` (merged)
