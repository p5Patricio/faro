import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { InvestableSurplusPanel } from './InvestableSurplusPanel.tsx';
import type { CashFlowForecastSummary } from '../types.ts';

function makeForecast(overrides: Partial<CashFlowForecastSummary> = {}): CashFlowForecastSummary {
  return {
    data_sufficient: true,
    horizon_days: 30,
    expected_income_cents: 3000000,
    committed_bills_cents: 250000,
    overdue_bills_cents: 0,
    overdue_bills_count: 0,
    projected_net_cents: 2750000,
    ...overrides,
  };
}

function renderPanel(cashFlowForecast: CashFlowForecastSummary) {
  return render(
    <InvestableSurplusPanel
      investableSurplus={{ data_sufficient: false, surplus_cents: 0, reason: 'building_emergency_fund' }}
      fireNumber={{ data_sufficient: false, target_cents: 0, progress_pct: null }}
      subscriptions={{ data_sufficient: true, annual_total_cents: 0, monthly_average_cents: 0, bills: [] }}
      cashFlowForecast={cashFlowForecast}
      emergencyFund={null}
    />,
  );
}

describe('InvestableSurplusPanel cash-flow forecast', () => {
  it('shows the committed bills without an overdue note when nothing is overdue', () => {
    renderPanel(makeForecast());

    expect(screen.getByText('Pagos comprometidos')).toBeInTheDocument();
    expect(screen.queryByText(/vencido/)).not.toBeInTheDocument();
  });

  it('breaks out the overdue amount and count, in text with an icon, when some are overdue', () => {
    renderPanel(makeForecast({ committed_bills_cents: 350000, overdue_bills_cents: 100000, overdue_bills_count: 2 }));

    const note = screen.getByText(/Incluye .* de 2 pagos vencidos/);
    expect(note).toHaveTextContent(/\$1,000\.00/);
    expect(note.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('uses the singular for one overdue payment', () => {
    renderPanel(makeForecast({ committed_bills_cents: 150000, overdue_bills_cents: 100000, overdue_bills_count: 1 }));

    expect(screen.getByText(/Incluye .* de 1 pago vencido$/)).toBeInTheDocument();
  });
});
