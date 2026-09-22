# Design: Professional Improvements Foundation

## Technical Approach

Create an OpenSpec planning layer and implement the first professionalization slice from `PLAN_MEJORAS_PROFESIONALES.md`: docs hygiene, CI, and dependency maintenance. Keep this separate from production-connected operational jobs.

## Architecture Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| SDD storage | File-based OpenSpec under `openspec/` | Keeps the plan reviewable in the repo and survives chat compaction. |
| CI shape | New `.github/workflows/ci.yml` | CI should validate code without running Supabase-connected operational jobs. |
| Python version | Use `3.14` in CI | Matches current local test runtime evidence from this workspace. |
| Dependency updates | Add `.github/dependabot.yml` | Makes package and action updates visible without manual scanning. |
| Docs | Add `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` | Standard public-repo expectations and safer collaborator onboarding. |

## Data Flow

    push / pull_request
      -> CI workflow
      -> Python tests
      -> UI lint/build
      -> pass/fail signal

    scheduled dependabot
      -> grouped update PRs
      -> maintainer review

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `openspec/config.yaml` | Create | Project SDD config and verification commands. |
| `openspec/specs/professional-operations/spec.md` | Create | Baseline operations spec. |
| `openspec/changes/professional-improvements-foundation/*` | Create | Active change artifacts. |
| `.github/workflows/ci.yml` | Create | Secret-free CI checks. |
| `.github/dependabot.yml` | Create | Dependency update configuration. |
| `CONTRIBUTING.md` | Create | Local workflow and verification guide. |
| `SECURITY.md` | Create | Secret handling and vulnerability reporting. |
| `CHANGELOG.md` | Create | Project history anchor. |
| `README.md`, `PLAN_DESPLIEGUE.md`, `ESTADO_PROYECTO.md` | Modify | Link new docs and remove obsolete pending notes. |

## Interfaces / Contracts

No API contract changes. CI contract:

```yaml
on: [push, pull_request]
jobs:
  backend-tests: pytest
  frontend-checks: npm lint/build
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Backend | Existing Python behavior | `py -3.14 -m pytest` locally; CI uses `python -m pytest`. |
| Frontend | TypeScript/Vite build quality | `npm run lint` and `npm run build` in `ui/`. |
| Docs/Config | Markdown and YAML sanity | `git diff --check`, inspect workflow syntax. |

## Migration / Rollout

No database migration required. The CI workflow becomes active after push. Dependabot creates future PRs only.

## Open Questions

- [ ] Whether to make CI required in GitHub branch protection after the workflow proves stable.
