# Tasks: Professional Improvements Foundation

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 250-380 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR/commit is acceptable for foundation docs + CI |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | SDD foundation | PR 1 | OpenSpec artifacts only. |
| 2 | Repo hygiene + CI | PR 1 | Docs, CI, dependabot, verification. |

## Phase 1: SDD Foundation

- [x] 1.1 Create `openspec/config.yaml` with stack context and verification commands.
- [x] 1.2 Create `openspec/specs/professional-operations/spec.md`.
- [x] 1.3 Create change proposal/spec/design/tasks/state under `openspec/changes/professional-improvements-foundation/`.

## Phase 2: Repository Hygiene

- [x] 2.1 Create `CONTRIBUTING.md` with setup, branch, test, and secret-safety workflow.
- [x] 2.2 Create `SECURITY.md` with vulnerability reporting and credential rotation guidance.
- [x] 2.3 Create `CHANGELOG.md` summarizing current professionalization milestones.
- [x] 2.4 Update `README.md`, `PLAN_DESPLIEGUE.md`, and `ESTADO_PROYECTO.md` to link new docs and remove stale pending items.

## Phase 3: CI and Dependency Maintenance

- [x] 3.1 Create `.github/workflows/ci.yml` for backend pytest and frontend lint/build.
- [x] 3.2 Create `.github/dependabot.yml` for pip, npm root, npm UI, and GitHub Actions.

## Phase 4: Verification

- [x] 4.1 Run Python tests, frontend lint/build, and diff checks.
- [x] 4.2 Update `tasks.md` and add `verify-report.md` with runtime evidence.
