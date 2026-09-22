# Delta for Professional Operations

> Archive note (2026-09-02): this was the first professional-improvements
> change (created 2026-07-12). Its "Secret-Free CI" requirement has since
> been superseded by the stronger **Pull Request Quality Gates** and
> **Local Scheduled Operations Replace Hosted Automation** requirements that
> `local-postgres-migration` merged into the main spec. Only the two
> genuinely net-new requirements below are merged on archive; the CI one is
> dropped as superseded.

## ADDED Requirements

### Requirement: SDD Change Tracking

Substantial professional-improvement work MUST be tracked through OpenSpec
artifacts (proposal, specs, design, tasks, state) before implementation.

#### Scenario: Active change is inspectable

- GIVEN a professional-improvement change is in development
- WHEN a reviewer opens its folder under `openspec/changes/`
- THEN proposal, specs, design, tasks, and state artifacts exist
- AND they describe scope, success criteria, and verification.

### Requirement: Maintainer Guidance

The repository MUST document contribution, security, and release-history
expectations.

#### Scenario: Contributor verifies a change

- GIVEN a contributor changes backend, frontend, or docs
- WHEN they read the repository guidance (CONTRIBUTING, SECURITY, CHANGELOG)
- THEN they can find the relevant verification commands
- AND they understand that `.env` and any other secret MUST NOT be committed.
