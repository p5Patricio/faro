import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import { describe, expect, it, vi } from 'vitest';
import { GoalsPanel } from './GoalsPanel.tsx';
import type { EmergencyFundSummary, FinanceGoal } from '../types.ts';

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

  it('asks to mark the liquid assets, with no months and no "Por debajo", when the fund is unclassified', () => {
    renderPanel(makeFund({ months_covered: null, status: 'unclassified' }));

    expect(screen.getByText(/Marca cuáles de tus activos son líquidos/)).toBeInTheDocument();
    expect(screen.queryByText('Por debajo')).not.toBeInTheDocument();
    expect(screen.queryByText(/meses cubiertos/)).not.toBeInTheDocument();
  });

  it('says a measured fund is based on the assets marked as liquid', () => {
    renderPanel(makeFund());

    expect(screen.getByText('Calculado con los activos que marcaste como líquidos.')).toBeInTheDocument();
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

describe('GoalsPanel goal update', () => {
  it('says so next to the action when updating a goal amount fails, and does not refresh', async () => {
    vi.mocked(axios.put).mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const goal = {
      id: 'goal-1',
      name: 'Viaje',
      target_amount_cents: 100000,
      current_amount_cents: 20000,
      currency: 'MXN',
      target_date: null,
      purpose_note: null,
      is_achieved: false,
    } as FinanceGoal;
    render(<GoalsPanel goals={[goal]} emergencyFund={null} onChanged={onChanged} />);

    await user.click(screen.getByRole('button', { name: 'Actualizar monto' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo actualizar el monto de «Viaje»');
    expect(onChanged).not.toHaveBeenCalled();
  });
});
