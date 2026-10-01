import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { formatCents } from '../lib/format.ts';
import { MonthSummaryPanel } from './MonthSummaryPanel.tsx';
import type { MonthlySummary } from '../types.ts';

const SUMMARY: MonthlySummary = {
  data_sufficient: true,
  income_cents: 500000,
  expense_cents: 187500,
  spending_cents: 187500,
  saved_cents: 0,
  net_cents: 312500,
  savings_rate_pct: 0,
  buckets: {
    necesidad: { actual_cents: 187500, target_cents: 250000 },
    deseo: { actual_cents: 0, target_cents: 150000 },
    ahorro_inversion: { actual_cents: 0, target_cents: 100000 },
    sin_categoria: { actual_cents: 0 },
  },
  converted_transactions: 3,
};

const EMPTY_MONTH: MonthlySummary = {
  ...SUMMARY,
  data_sufficient: false,
  income_cents: 0,
  expense_cents: 0,
  spending_cents: 0,
  net_cents: 0,
  buckets: {
    necesidad: { actual_cents: 0, target_cents: 0 },
    deseo: { actual_cents: 0, target_cents: 0 },
    ahorro_inversion: { actual_cents: 0, target_cents: 0 },
    sin_categoria: { actual_cents: 0 },
  },
  converted_transactions: 0,
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

describe('MonthSummaryPanel empty state', () => {
  it('shows a live empty state, in neutral es-MX, instead of a $0.00 month when the month has no data', () => {
    render(<MonthSummaryPanel summary={EMPTY_MONTH} />);

    expect(screen.getByText('Todavía no hay transacciones este mes')).toBeInTheDocument();
    expect(screen.getByText(/Registra tus movimientos con el botón/)).toBeInTheDocument();
    // No fake zeros and no green "net" tile.
    expect(screen.queryByText('Sin gastar')).not.toBeInTheDocument();
    expect(screen.queryByText('Ingresos')).not.toBeInTheDocument();
  });

  it('shows the empty state while there is no summary at all', () => {
    render(<MonthSummaryPanel summary={null} />);

    expect(screen.getByText('Todavía no hay transacciones este mes')).toBeInTheDocument();
  });

  it('explains a month with only unconverted rows instead of promising figures that cannot appear', () => {
    render(<MonthSummaryPanel summary={{ ...EMPTY_MONTH, unconverted_transactions: 2 }} />);

    expect(screen.getByText('Este mes no tiene movimientos que se puedan sumar')).toBeInTheDocument();
    expect(screen.getByText(/Este mes solo hay 2 movimientos en otra moneda/)).toBeInTheDocument();
  });
});

describe('MonthSummaryPanel spending, saving and what was not spent', () => {
  const WITH_SAVING: MonthlySummary = {
    ...SUMMARY,
    income_cents: 1_000_000,
    expense_cents: 500_000,
    spending_cents: 350_000,
    saved_cents: 150_000,
    net_cents: 650_000,
    savings_rate_pct: 15,
    buckets: {
      necesidad: { actual_cents: 200_000, target_cents: 500_000 },
      deseo: { actual_cents: 100_000, target_cents: 300_000 },
      ahorro_inversion: { actual_cents: 150_000, target_cents: 200_000 },
      sin_categoria: { actual_cents: 50_000 },
    },
  };

  it('shows spending without the savings bucket, what was saved, and the savings rate', () => {
    render(<MonthSummaryPanel summary={WITH_SAVING} />);

    expect(screen.getByText('Gastos').parentElement).toHaveTextContent(formatCents(350_000));
    expect(screen.getByText('Ahorrado').parentElement).toHaveTextContent(formatCents(150_000));
    expect(screen.getByText('Tasa de ahorro').parentElement).toHaveTextContent('15%');
  });

  it('signs what was not spent and adds an icon, so the direction is not only a colour', () => {
    render(<MonthSummaryPanel summary={WITH_SAVING} />);

    const tile = screen.getByText('Sin gastar').parentElement as HTMLElement;
    expect(tile).toHaveTextContent(`+${formatCents(650_000)}`);
    expect(tile).toHaveTextContent('Ingresos menos gastos');
    expect(tile.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('shows a negative amount not spent with its minus sign and a plain-words explanation', () => {
    render(
      <MonthSummaryPanel
        summary={{ ...WITH_SAVING, income_cents: 200_000, spending_cents: 350_000, net_cents: -150_000 }}
      />,
    );

    const tile = screen.getByText('Sin gastar').parentElement as HTMLElement;
    expect(tile).toHaveTextContent(formatCents(-150_000));
    expect(tile).toHaveTextContent('Gastaste más de lo que ingresó');
    expect(tile.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('says so when the month spent exactly what it earned', () => {
    render(<MonthSummaryPanel summary={{ ...WITH_SAVING, net_cents: 0, spending_cents: 1_000_000 }} />);

    expect(screen.getByText('Sin gastar').parentElement).toHaveTextContent('Gastaste todo lo que ingresó');
  });

  it('says no income is registered, not that more was spent than earned, when there is spending but no income', () => {
    render(<MonthSummaryPanel summary={{ ...WITH_SAVING, income_cents: 0, net_cents: -350_000, savings_rate_pct: 0 }} />);

    const tile = screen.getByText('Sin gastar').parentElement as HTMLElement;
    expect(tile).toHaveTextContent(formatCents(-350_000));
    expect(tile).toHaveTextContent('No hay ingresos registrados este mes');
    expect(tile).not.toHaveTextContent('Gastaste más de lo que ingresó');
  });

  it('does not say everything earned was spent when a month with only savings has no income and no spending', () => {
    render(
      <MonthSummaryPanel
        summary={{ ...WITH_SAVING, income_cents: 0, expense_cents: 150_000, spending_cents: 0, net_cents: 0, savings_rate_pct: 0 }}
      />,
    );

    const tile = screen.getByText('Sin gastar').parentElement as HTMLElement;
    expect(tile).toHaveTextContent('Sin ingresos ni gastos este mes');
    expect(tile).not.toHaveTextContent('Gastaste todo lo que ingresó');
  });

  it('notes the uncategorized spend, which counts as spending but sits outside the 50/30/20 bars', () => {
    render(<MonthSummaryPanel summary={WITH_SAVING} />);

    expect(screen.getByText(/de tus gastos no tienen categoría/)).toHaveTextContent(formatCents(50_000));
  });

  it('shows no uncategorized note when every expense has a category', () => {
    render(<MonthSummaryPanel summary={SUMMARY} />);

    expect(screen.queryByText(/no tienen categoría/)).not.toBeInTheDocument();
  });
});
