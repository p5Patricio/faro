# Contributing

Thanks for helping improve Faro. This project handles market data, model artifacts, and deployment secrets, so contributions should be reviewable, reproducible, and careful with credentials.

## Local Setup

1. Create a local environment file:

```bash
cp .env.example .env
```

2. Fill local credentials only. Never commit `.env`.

3. Install dependencies:

```bash
pip install -r requirements.txt
cd ui
npm install
```

## Development Workflow

Use a focused branch for each change:

```bash
git switch -c codex/<short-change-name>
```

Keep commits reviewable. A good commit should contain one coherent behavior, its tests, and any docs needed to understand it.

## Verification

Run the checks that match your change.

Backend and pipeline:

```bash
py -3.14 -m pytest
```

Supabase schema check, only when your local `.env` points to the intended project:

```bash
py -3.14 -m collector.schema_check
```

Frontend:

```bash
cd ui
npm run lint
npm run build
```

Whitespace/config sanity:

```bash
git diff --check
```

## Secret Safety

- Do not commit `.env`, Supabase service keys, database passwords, provider tokens, or broker credentials.
- Frontend variables must use public/anon keys only.
- Backend, collector, training, and GitHub Actions may use server-side credentials through private environment variables or GitHub Secrets.
- If a credential is exposed, rotate it before continuing development.

Before committing security-sensitive changes, scan staged diffs for Supabase access tokens, database URLs, service-role keys, JWT-looking values, and provider credentials. Keep the scan patterns local so the repository itself does not store secret signatures that trigger automated scanners.

## SDD Changes

Major feature work should use OpenSpec artifacts under `openspec/changes/<change-name>/`:

- `proposal.md`: intent and scope.
- `specs/`: requirements and scenarios.
- `design.md`: technical approach.
- `tasks.md`: implementation checklist and verification plan.

Keep active changes small enough to review comfortably. If a change is likely to exceed 400 changed lines, split it into chained work units.
