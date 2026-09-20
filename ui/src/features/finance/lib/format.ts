/**
 * Fallback currency for aggregate figures the API computes server-side
 * without echoing a `currency` field (e.g. `monthly_summary`, the
 * net-worth snapshot totals, `GET /budgets` rows). Every one of this
 * user's real accounts is MXN today, so this is a safe assumption for
 * those specific aggregates only — everywhere the API DOES return a
 * `currency` on the record (transactions, accounts, net-worth items,
 * recurring bills, goals) that field is used instead, never this
 * constant.
 */
export const DEFAULT_CURRENCY = 'MXN';

/** Format integer cents as a localized currency string. */
export function formatCents(amountCents: number, currency: string): string {
  return new Intl.NumberFormat('es-MX', { style: 'currency', currency }).format(amountCents / 100);
}

/** "YYYY-MM" for the given date (defaults to now). */
export function formatMonth(date: Date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
}

/** Parses a "YYYY-MM" string; returns null when malformed. */
export function parseMonthInput(month: string): { year: number; month: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return null;
  const year = Number(match[1]);
  const monthNumber = Number(match[2]);
  if (monthNumber < 1 || monthNumber > 12) return null;
  return { year, month: monthNumber };
}

/** Human-readable label for a "YYYY-MM" string, e.g. "septiembre de 2026". */
export function formatMonthLabel(month: string): string {
  const parsed = parseMonthInput(month);
  if (!parsed) return month;
  const date = new Date(parsed.year, parsed.month - 1, 1);
  return new Intl.DateTimeFormat('es-MX', { month: 'long', year: 'numeric' }).format(date);
}

/** Adds `delta` calendar months to a "YYYY-MM" string. */
export function shiftMonth(month: string, delta: number): string {
  const parsed = parseMonthInput(month);
  if (!parsed) return month;
  const date = new Date(parsed.year, parsed.month - 1 + delta, 1);
  return formatMonth(date);
}

/** Short date label for a date-only or ISO-timestamp string. */
export function formatShortDate(value: string): string {
  return new Intl.DateTimeFormat('es-MX', { month: 'short', day: 'numeric' }).format(new Date(value));
}
