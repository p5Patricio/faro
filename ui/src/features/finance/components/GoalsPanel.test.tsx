import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GoalsPanel } from './GoalsPanel.tsx';
import type { EmergencyFundSummary } from '../types.ts';

vi.mock('axios');

function makeFund(overrides: Partial<EmergencyFundSummary> = {}): EmergencyFundSummary {
  return {
    data_sufficient: true,
    months_covered: 1.5,
    target_min_months: 3,
    target_max_months: 6,
    status: 'below',
    ...overrides,
  };
}

function renderPanel(emergencyFund: EmergencyFundSummary | null) {
  return render(<GoalsPanel goals={[]} emergencyFund={emergencyFund} onChanged={() => undefined} />);
}

describe('GoalsPanel emergency fund row', () => {
  it('shows the months covered and a status badge when coverage is measured', () => {
    renderPanel(makeFund({ months_covered: 1.5, status: 'below' }));

    expect(screen.getByText('1.5 meses cubiertos')).toBeInTheDocument();
    expect(screen.getByText('Por debajo')).toBeInTheDocument();
  });

  it('shows no status badge and no N/D, and says there is not enough history, when coverage is unknown', () => {
    // Sufficient history but no essential expenses to measure against: `months_covered` is null and the API's status is a placeholder "below".
    renderPanel(makeFund({ months_covered: null, status: 'below' }));

    expect(screen.queryByText('Por debajo')).not.toBeInTheDocument();
    expect(screen.queryByText('N/D')).not.toBeInTheDocument();
    expect(screen.getByText(/todavía no hay suficiente historial para estimarlo/)).toBeInTheDocument();
  });

  it('says there is not enough history when the fund is not sufficient at all', () => {
    renderPanel(makeFund({ data_sufficient: false, months_covered: null }));

    expect(screen.getByText(/todavía no hay suficiente historial/)).toBeInTheDocument();
    expect(screen.queryByText('Por debajo')).not.toBeInTheDocument();
  });
});
