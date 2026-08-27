# Security Policy

Faro is an experimental investment research platform. Treat secrets, model artifacts, market data pipelines, and deployment configuration as sensitive.

## Supported Scope

Security reports may cover:

- Exposed credentials or secret-handling issues.
- Supabase Row Level Security mistakes.
- Public API routes that expose private operational data.
- GitHub Actions workflows that leak secrets or run unsafe commands.
- Frontend usage of server-side keys.
- Model artifact storage or download paths that bypass intended access controls.

## Reporting

For now, report issues privately to the repository owner before opening a public issue. Include:

- A short description of the issue.
- Affected files, routes, tables, or workflows.
- Steps to reproduce, when safe.
- Whether any credentials may have been exposed.

Do not include live secrets in the report body.

## Credential Rotation

Rotate credentials immediately when exposure is suspected:

1. Revoke or regenerate the affected Supabase/API/provider key.
2. Update local `.env` privately.
3. Update GitHub Secrets, Render variables, and Vercel variables as needed.
4. Verify production health after rotation.
5. Audit git history if the secret may have been committed.

## Operational Guardrails

- `.env` must remain untracked.
- Supabase service-role credentials must never be used in frontend code.
- RLS must be enabled for public Supabase tables unless there is a documented exception.
- Broker live-trading credentials must not be added until paper trading, monitoring, and manual approval guardrails are complete.
