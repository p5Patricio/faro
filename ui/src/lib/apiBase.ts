/**
 * Single source of truth for the API base URL. Extracted out of `App.tsx`
 * so both the markets dashboard and `features/finance` import the exact
 * same constant instead of each recomputing the same env-var/fallback
 * expression.
 */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api').replace(
  /\/$/,
  '',
);
