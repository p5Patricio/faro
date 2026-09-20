import { describe, expect, it } from 'vitest';
import { formatCents, formatMonth, formatMonthLabel, parseMonthInput, shiftMonth } from './format.ts';

describe('formatCents', () => {
  it('formats a positive MXN amount', () => {
    expect(formatCents(150000, 'MXN')).toBe(
      new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' }).format(1500),
    );
  });

  it('formats zero', () => {
    expect(formatCents(0, 'MXN')).toBe(
      new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' }).format(0),
    );
  });

  it('formats a non-MXN currency using its own code, not a hardcoded one', () => {
    expect(formatCents(250099, 'USD')).toBe(
      new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'USD' }).format(2500.99),
    );
    expect(formatCents(250099, 'USD')).not.toBe(formatCents(250099, 'MXN'));
  });

  it('formats a negative amount', () => {
    expect(formatCents(-500, 'MXN')).toBe(
      new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' }).format(-5),
    );
  });
});

describe('parseMonthInput', () => {
  it('parses a valid YYYY-MM string', () => {
    expect(parseMonthInput('2026-09')).toEqual({ year: 2026, month: 9 });
  });

  it('rejects malformed input', () => {
    expect(parseMonthInput('2026-9')).toBeNull();
    expect(parseMonthInput('not-a-month')).toBeNull();
    expect(parseMonthInput('2026-13')).toBeNull();
  });
});

describe('formatMonth', () => {
  it('zero-pads the month', () => {
    expect(formatMonth(new Date(2026, 0, 15))).toBe('2026-01');
  });
});

describe('shiftMonth', () => {
  it('advances across a year boundary', () => {
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
  });

  it('goes back across a year boundary', () => {
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
  });
});

describe('formatMonthLabel', () => {
  it('returns the raw string when malformed', () => {
    expect(formatMonthLabel('bad')).toBe('bad');
  });

  it('produces a localized label for a valid month', () => {
    expect(formatMonthLabel('2026-09')).toBe(
      new Intl.DateTimeFormat('es-MX', { month: 'long', year: 'numeric' }).format(new Date(2026, 8, 1)),
    );
  });
});
