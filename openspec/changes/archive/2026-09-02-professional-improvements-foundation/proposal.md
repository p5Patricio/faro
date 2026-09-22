# Proposal: Professional Improvements Foundation

## Intent

Raise Faro from a functional deployed MVP to a reviewable professional project foundation. This first slice addresses repository hygiene and CI before deeper model, drift, and broker work.

## Scope

### In Scope
- Initialize OpenSpec SDD artifacts for the professional improvements program.
- Add contribution, security, changelog, CI, and dependency maintenance documentation/config.
- Correct obsolete deployment-plan pending items.

### Out of Scope
- Drift monitoring, LightGBM/XGBoost, Optuna, model cards, shadow mode, and broker integrations.
- Production secret rotation or provider account changes.

## Capabilities

### New Capabilities
- `professional-operations`: repository hygiene, CI quality gates, dependency maintenance, and operational docs.

### Modified Capabilities
- None.

## Approach

Use OpenSpec file artifacts in `openspec/`. Implement the smallest reviewable slice from `PLAN_MEJORAS_PROFESIONALES.md`: documentation hygiene plus CI/dependency automation that does not require production secrets.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `openspec/` | New | SDD config, base spec, active change artifacts. |
| `.github/workflows/` | New | CI workflow for tests/lint/build. |
| `.github/dependabot.yml` | New | Dependency update visibility. |
| Root docs | Modified/New | README links, changelog, contribution and security docs. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| CI fails due environment mismatch | Med | Use existing local commands and Python 3.14 where available. |
| Docs overpromise production readiness | Low | Keep broker/live trading explicitly out of scope. |

## Rollback Plan

Revert the SDD/docs/CI commit. Operational jobs and deployed services are unaffected.

## Dependencies

- Existing pytest suite and frontend npm scripts.

## Success Criteria

- [ ] SDD artifacts exist and describe this foundation change.
- [ ] CI validates Python tests and frontend lint/build separately from operational jobs.
- [ ] Dependency updates are visible through Dependabot.
- [ ] Repository docs explain contribution and security expectations.
