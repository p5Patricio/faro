/**
 * The ledger's base currency. Mirrors `BASE_CURRENCY` in
 * `brain/finance/currency.py` (decision D1). Every aggregate the API
 * computes — monthly summary, net-worth totals, budget actuals,
 * subscription and forecast figures — is expressed in it, so those
 * figures are formatted with it. A record that carries its own native
 * `currency` (a transaction, a net-worth item) is formatted with that
 * currency instead.
 */
export const BASE_CURRENCY = 'MXN';

/**
 * Currencies offered where a foreign amount can be entered (transactions
 * take theirs from the account; net-worth items pick one). The four
 * markets the app follows; the API accepts any ISO code given an FX rate.
 */
export const SELECTABLE_CURRENCIES = [BASE_CURRENCY, 'USD', 'CAD', 'CNY'] as const;

/** Format integer cents as a localized currency string (base currency by default). */
export function formatCents(amountCents: number, currency: string = BASE_CURRENCY): string {
  return new Intl.NumberFormat('es-MX', { style: 'currency', currency }).format(amountCents / 100);
}

/**
 * `formatCents` with an explicit "+" on positive amounts (negatives already
 * carry "-"), so the direction of a difference reads from the sign and not
 * from a colour alone.
 */
export function formatSignedCents(amountCents: number, currency: string = BASE_CURRENCY): string {
  const formatted = formatCents(amountCents, currency);
  return amountCents > 0 ? `+${formatted}` : formatted;
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

const DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Parses a date-only ("YYYY-MM-DD") string as a LOCAL calendar day and anything
 * else (an ISO timestamp) as the instant it names. `new Date("2026-10-01")` is
 * UTC midnight, which is still Sep 30 in any UTC-negative zone (Mexico), so a
 * bare date must never go through it.
 */
export function parseDateValue(value: string): Date {
  const match = DATE_ONLY_PATTERN.exec(value);
  if (!match) return new Date(value);
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

/** "YYYY-MM-DD" from the LOCAL date parts (`toISOString` is UTC: tomorrow after 6 pm in Mexico). */
export function formatDateOnly(date: Date = new Date()): string {
  const day = String(date.getDate()).padStart(2, '0');
  return `${formatMonth(date)}-${day}`;
}

/** Short date label for a date-only or ISO-timestamp string. */
export function formatShortDate(value: string): string {
  return new Intl.DateTimeFormat('es-MX', { month: 'short', day: 'numeric' }).format(parseDateValue(value));
}
