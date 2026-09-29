import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { formatCents } from '../lib/format.ts';
import { MonthSummaryPanel } from './MonthSummaryPanel.tsx';
import type { MonthlySummary } from '../types.ts';

const SUMMARY: MonthlySummary = {
  data_sufficient: true,
  income_cents: 500000,
  expense_cents: 187500,
  net_cents: 312500,
  savings_rate_pct: 0,
  buckets: {
    necesidad: { actual_cents: 187500, target_cents: 250000 },
    deseo: { actual_cents: 0, target_cents: 150000 },
    ahorro_inversion: { actual_cents: 0, target_cents: 100000 },
  },
};

describe('MonthSummaryPanel unconverted transactions', () => {
  it('formats the totals in the base currency', () => {
    render(<MonthSummaryPanel summary={SUMMARY} />);

    expect(screen.getByText(formatCents(187500, 'MXN'))).toBeInTheDocument();
  });

  it('warns, with the count, when transactions were left out for lack of an exchange rate', () => {
    render(<MonthSummaryPanel summary={{ ...SUMMARY, unconverted_transactions: 2 }} />);

    const warning = screen.getByRole('status');
    expect(warning).toHaveTextContent('2 movimientos en otra moneda no están incluidos');
    expect(warning).toHaveTextContent('tipo de cambio a MXN');
  });

  it('uses the singular for one transaction', () => {
    render(<MonthSummaryPanel summary={{ ...SUMMARY, unconverted_transactions: 1 }} />);

    expect(screen.getByRole('status')).toHaveTextContent('1 movimiento en otra moneda no está incluido');
  });

  it.each([0, undefined])('shows no warning when unconverted_transactions is %s', (count) => {
    render(<MonthSummaryPanel summary={{ ...SUMMARY, unconverted_transactions: count }} />);

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
