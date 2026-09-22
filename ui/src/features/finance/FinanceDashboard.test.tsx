import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { FinanceDashboard } from './FinanceDashboard.tsx';

vi.mock('axios');

// The real current state for a brand-new user: every `*_sufficient` flag is
// false because there is no history yet. The dashboard must render an honest
// empty state for each section instead of crashing or faking zeros.
const EMPTY_SUMMARY = {
  month: '2026-09',
  monthly_summary: {
    data_sufficient: false,
    income_cents: 0,
    expense_cents: 0,
    net_cents: 0,
    savings_rate_pct: 0,
    buckets: {
      necesidad: { actual_cents: 0, target_cents: 0 },
      deseo: { actual_cents: 0, target_cents: 0 },
      ahorro_inversion: { actual_cents: 0, target_cents: 0 },
    },
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
  investable_surplus: { data_sufficient: false, surplus_cents: 0, reason: 'building_emergency_fund' },
  subscriptions: { data_sufficient: true, annual_total_cents: 0, monthly_average_cents: 0, bills: [] },
  cash_flow_forecast: {
    data_sufficient: false,
    horizon_days: 30,
    expected_income_cents: 0,
    committed_bills_cents: 0,
    projected_net_cents: 0,
  },
};

describe('FinanceDashboard', () => {
  beforeEach(() => {
    vi.mocked(axios.get).mockImplementation((url: string) => {
      if (url.includes('/summary')) return Promise.resolve({ data: EMPTY_SUMMARY });
      return Promise.resolve({ data: [] });
    });
  });

  it('renders without crashing given a brand-new-user (empty) API response', async () => {
    render(<FinanceDashboard />);

    expect(await screen.findByRole('tablist', { name: 'Secciones de finanzas' })).toBeInTheDocument();
    expect(screen.getByText(/Todavía no hay transacciones este mes/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Nueva transacción/ })).toBeInTheDocument();
  });
});
