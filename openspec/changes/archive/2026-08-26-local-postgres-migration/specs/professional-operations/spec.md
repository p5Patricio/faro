# Delta for Professional Operations

## MODIFIED Requirements

### Requirement: Pull Request Quality Gates

The repository MUST provide CI checks that validate backend tests and
frontend build quality without requiring any Supabase or other hosted
database secrets. Backend tests MUST run against a local/ephemeral Postgres
instance provisioned inside the CI job.
(Previously: only excluded "production" Supabase secrets, silent on how
backend tests obtain a database since Supabase itself was that database.)

#### Scenario: Pull request validation

- GIVEN a pull request changes code
- WHEN GitHub Actions runs CI
- THEN Python tests run against a local/ephemeral Postgres instance with zero Supabase secrets
- AND frontend lint/build checks run independently of any scheduled/operational job

#### Scenario: No references to the removed operational workflow

- GIVEN `.github/workflows/operational-jobs.yml` and `render.yaml` have been removed
- WHEN `ci.yml` is inspected
- THEN it contains no `SUPABASE_URL` or `SUPABASE_KEY` references
- AND it does not depend on either removed file

### Requirement: Reviewable Operational Documentation

The repository MUST document how contributors verify, secure, and operate
the project locally, including how recurring collector/brain jobs are
scheduled without any hosted CI runner or cloud secrets.
(Previously: did not address local job scheduling or the removal of
`operational-jobs.yml`/`render.yaml`.)

#### Scenario: New contributor onboarding

- GIVEN a contributor opens the repository
- WHEN they read the root documentation
- THEN they can find setup, test, security, and contribution guidance
- AND they can identify which commands are local-only versus operational

#### Scenario: Local job scheduling documented

- GIVEN `operational-jobs.yml` and `render.yaml` have been removed
- WHEN a contributor reads the operational documentation
- THEN they find the Windows Task Scheduler registration steps for the local orchestration entrypoint
- AND no instructions reference `SUPABASE_URL` or `SUPABASE_KEY`

## ADDED Requirements

### Requirement: Local Scheduled Operations Replace Hosted Automation

The repository MUST NOT provide a Supabase-dependent scheduled GitHub
Actions workflow (`.github/workflows/operational-jobs.yml`) or a
Supabase-dependent deploy config (`render.yaml`). Recurring collector/brain
jobs MUST instead run via a documented Windows Task Scheduler registration
invoking a single local orchestration entrypoint that wraps the existing CLI
scripts.

#### Scenario: No hosted scheduled job remains

- GIVEN the repository after this change
- WHEN `.github/workflows/` is inspected
- THEN no workflow references `SUPABASE_URL`, `SUPABASE_KEY`, or a `schedule:` trigger tied to Supabase
- AND `render.yaml` no longer exists

#### Scenario: Local Task Scheduler registration documented and functional

- GIVEN the local orchestration entrypoint exists
- WHEN it is registered in Windows Task Scheduler per the documented steps
- THEN scheduled runs execute the same `JOB_MODE` branching the removed workflow used
- AND runs succeed offline with no network dependency on GitHub-hosted runners
