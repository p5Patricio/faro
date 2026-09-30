import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { FinanceDashboard } from './FinanceDashboard.tsx';
import { formatCents } from './lib/format.ts';
import type { FinanceSummary } from './types.ts';

vi.mock('axios');

// EXACTLY what `GET /api/finance/summary` returns for a brand-new user with
// nothing logged: the same payload `test_get_summary_degrades_gracefully_with_no_data`
// (tests/test_finance_api.py) asserts, key for key. Keep the two in step -- a
// fixture production never returns tests nothing. Every `*_sufficient` flag is
// derived from data (none is hard-coded true except subscriptions, where "no
// subscriptions" is a true zero), and the income-dependent forecast figures are
// null (unknown), not 0.
const NEW_USER_SUMMARY: FinanceSummary = {
  month: '2026-09',
  monthly_summary: {
    data_sufficient: false,
    income_cents: 0,
    expense_cents: 0,
    spending_cents: 0,
    saved_cents: 0,
    net_cents: 0,
    savings_rate_pct: 0,
    buckets: {
      necesidad: { actual_cents: 0, target_cents: 0 },
      deseo: { actual_cents: 0, target_cents: 0 },
      ahorro_inversion: { actual_cents: 0, target_cents: 0 },
      sin_categoria: { actual_cents: 0 },
    },
    converted_transactions: 0,
    unconverted_transactions: 0,
  },
  category_breakdown: [],
  history: {
    months_used: 0,
    months_considered: 3,
    min_transactions_per_month: 5,
    unconverted_transactions: 0,
  },
  net_worth: {
    data_sufficient: false,
    snapshot_date: null,
    total_assets_cents: null,
    total_liabilities_cents: null,
    net_worth_cents: null,
    liquid_net_worth_cents: null,
  },
  emergency_fund: {
    data_sufficient: false,
    months_covered: null,
    target_min_months: 3,
    target_max_months: 6,
    status: 'below',
  },
  fire_number: { data_sufficient: false, target_cents: 0, progress_pct: null },
  investable_surplus: {
    data_sufficient: false,
    surplus_cents: 0,
    reason: 'building_emergency_fund',
    available_cents: 0,
    shortfall_cents: 0,
    income_cents: 0,
    spending_cents: 0,
    saved_cents: 0,
  },
  subscriptions: {
    data_sufficient: true,
    annual_total_cents: 0,
    monthly_average_cents: 0,
    bills: [],
    unconverted_bills: 0,
  },
  cash_flow_forecast: {
    data_sufficient: false,
    horizon_days: 30,
    income_data_sufficient: false,
    expected_income_cents: null,
    committed_bills_cents: 0,
    overdue_bills_cents: 0,
    overdue_bills_count: 0,
    projected_net_cents: null,
  },
};

// A month with real activity but no history behind it yet: an income, one
// expense per bucket and one with no category, plus a bill that is overdue and
// another committed, with no income history to project from.
const ACTIVE_MONTH_SUMMARY: FinanceSummary = {
  ...NEW_USER_SUMMARY,
  monthly_summary: {
    data_sufficient: true,
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
    converted_transactions: 5,
    unconverted_transactions: 0,
  },
  category_breakdown: [
    {
      category_id: 'cat-alimentacion',
      category_name: 'Alimentacion',
      slug: 'alimentacion',
      emoji: '🍽',
      bucket: 'necesidad',
      actual_cents: 200_000,
      budget_cents: 300_000,
    },
    {
      category_id: 'cat-entretenimiento',
      category_name: 'Entretenimiento',
      slug: 'entretenimiento',
      emoji: '🎬',
      bucket: 'deseo',
      actual_cents: 100_000,
      budget_cents: null,
    },
    {
      category_id: 'cat-ahorro',
      category_name: 'Ahorro e Inversion',
      slug: 'ahorro-inversion',
      emoji: '💰',
      bucket: 'ahorro_inversion',
      actual_cents: 150_000,
      budget_cents: null,
    },
    {
      category_id: null,
      category_name: 'Sin categoría',
      slug: null,
      emoji: null,
      bucket: 'sin_categoria',
      actual_cents: 50_000,
      budget_cents: null,
    },
  ],
  investable_surplus: {
    data_sufficient: false,
    surplus_cents: 0,
    reason: 'building_emergency_fund',
    available_cents: 650_000,
    shortfall_cents: 0,
    income_cents: 1_000_000,
    spending_cents: 350_000,
    saved_cents: 150_000,
  },
  cash_flow_forecast: {
    data_sufficient: true,
    horizon_days: 30,
    income_data_sufficient: false,
    expected_income_cents: null,
    committed_bills_cents: 200_000,
    overdue_bills_cents: 100_000,
    overdue_bills_count: 1,
    projected_net_cents: null,
  },
};

describe('summary fixtures', () => {
  it.each([
    ['a brand-new user', NEW_USER_SUMMARY],
    ['an active month', ACTIVE_MONTH_SUMMARY],
  ])('the category breakdown of %s adds up to the month expense, as the API guarantees', (_name, fixture) => {
    const total = fixture.category_breakdown.reduce((sum, row) => sum + row.actual_cents, 0);

    expect(total).toBe(fixture.monthly_summary.expense_cents);
    expect(fixture.monthly_summary.spending_cents + fixture.monthly_summary.saved_cents).toBe(
      fixture.monthly_summary.expense_cents,
    );
  });
});

describe('FinanceDashboard', () => {
  let summary: FinanceSummary;

  beforeEach(() => {
    summary = NEW_USER_SUMMARY;
    vi.mocked(axios.get).mockImplementation((url: string) => {
      if (url.includes('/summary')) return Promise.resolve({ data: summary });
      return Promise.resolve({ data: [] });
    });
  });

  it('renders the live empty state, not a $0.00 month, for a brand-new user', async () => {
    render(<FinanceDashboard />);

    expect(await screen.findByRole('tablist', { name: 'Secciones de finanzas' })).toBeInTheDocument();
    expect(await screen.findByText(/Todavía no hay transacciones este mes/)).toBeInTheDocument();
    expect(screen.getByText(/Registra tus movimientos/)).toBeInTheDocument();
    expect(screen.queryByText('Sin gastar')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Nueva transacción/ })).toBeInTheDocument();
  });

  it('shows honest empty states on the category and surplus tabs for a brand-new user', async () => {
    const user = userEvent.setup();
    render(<FinanceDashboard />);
    await screen.findByText(/Todavía no hay transacciones este mes/);

    await user.click(screen.getByRole('tab', { name: 'Categorías' }));
    expect(await screen.findByText('Sin gastos ni presupuestos este mes')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Excedente' }));
    // Both the surplus card and the FIRE card say what they are still waiting for.
    expect(await screen.findAllByText(/Para calcularlo falta un corte de patrimonio/)).toHaveLength(2);
    expect(screen.getByText(/Todavía no hay meses anteriores suficientes para estimar/)).toBeInTheDocument();
    expect(screen.getByText('Todavía no hay nada que proyectar')).toBeInTheDocument();
    expect(screen.getByText(/No hay pagos por vencer en los próximos 30 días ni ingresos de meses anteriores/)).toBeInTheDocument();
  });

  it('shows the month with spending, saved and not-spent, and the uncategorized row in the breakdown', async () => {
    summary = ACTIVE_MONTH_SUMMARY;
    const user = userEvent.setup();
    render(<FinanceDashboard />);

    expect(await screen.findByText(formatCents(350_000))).toBeInTheDocument(); // Gastos: without the savings bucket
    expect(screen.getByText(formatCents(150_000))).toBeInTheDocument(); // Ahorrado
    expect(screen.getByText(`+${formatCents(650_000)}`)).toBeInTheDocument(); // Sin gastar, with its sign

    await user.click(screen.getByRole('tab', { name: 'Categorías' }));
    expect(await screen.findByText('Sin categoría')).toBeInTheDocument();
    expect(screen.getByText('Alimentacion')).toBeInTheDocument();
    expect(screen.getByText('Entretenimiento')).toBeInTheDocument();
    expect(screen.getByText('Ahorro e Inversion')).toBeInTheDocument();
    // The list adds up to the month's total expense: nothing vanishes.
    expect(screen.getByText(/Total de gastos del mes/).parentElement).toHaveTextContent(formatCents(500_000));
  });

  it('keeps the committed and overdue bills visible on the surplus tab when there is no income history', async () => {
    summary = ACTIVE_MONTH_SUMMARY;
    const user = userEvent.setup();
    render(<FinanceDashboard />);
    await screen.findByText(formatCents(350_000));

    await user.click(screen.getByRole('tab', { name: 'Excedente' }));

    expect(await screen.findByText('Pagos comprometidos')).toBeInTheDocument();
    expect(screen.getByText(formatCents(200_000))).toBeInTheDocument();
    expect(screen.getByText(/Incluye .* de 1 pago vencido/)).toHaveTextContent(formatCents(100_000));
    expect(screen.getAllByText('Sin historial')).toHaveLength(2); // no income estimate, no projected net
  });
});
