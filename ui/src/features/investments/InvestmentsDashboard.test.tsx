import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { InvestmentsDashboard } from './InvestmentsDashboard.tsx';
import { decimalToCents } from './api.ts';

vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
    isAxiosError: (error: { isAxiosError?: boolean }) => Boolean(error?.isAxiosError),
  },
}));

const RESPONSES: Record<string, unknown> = {
  accounts: [{ id: 'a1', name: 'GBM SIC', broker: 'GBM', currency: 'MXN' }],
  positions: {
    disclaimer: 'Informativo: no es un cálculo de impuestos.',
    positions: [
      {
        account_id: 'a1',
        account_name: 'GBM SIC',
        symbol: 'VOO',
        instrument_type: 'etf',
        quantity: '3',
        cost_basis_mxn_cents: 2_587_500,
        average_cost_mxn_cents: '862500.0000',
      },
    ],
  },
  transactions: [],
  worksheet: {
    year: 2026,
    disclaimer: 'x',
    summary: [{ account_id: 'a1', concept: 'sale_gain', amount_mxn_cents: 217_500, tax_withheld_mxn_cents: 0 }],
  },
};

describe('InvestmentsDashboard', () => {
  beforeEach(() => {
    vi.mocked(axios.get).mockReset();
  });

  it('shows positions with their MXN average cost and the yearly totals', async () => {
    vi.mocked(axios.get).mockImplementation(async (url: string) => ({
      data: RESPONSES[url.split('/').pop() as string],
    }));

    render(<InvestmentsDashboard />);

    expect(await screen.findByText('VOO')).toBeInTheDocument();
    expect(screen.getByText(/8,625\.00/)).toBeInTheDocument();
    expect(screen.getByText('Ganancia o pérdida en ventas')).toBeInTheDocument();
    expect(screen.getByText('Informativo: no es un cálculo de impuestos.')).toBeInTheDocument();
  });

  it('explains when the migration has not been applied', async () => {
    vi.mocked(axios.get).mockRejectedValue({
      isAxiosError: true,
      response: { status: 503, data: { detail: 'falta aplicar la migración 0016.' } },
    });

    render(<InvestmentsDashboard />);

    expect(await screen.findByText('falta aplicar la migración 0016.')).toBeInTheDocument();
  });
});

describe('decimalToCents', () => {
  it('converts by string arithmetic and rejects malformed amounts', () => {
    expect(decimalToCents('1,234.5')).toBe(123_450);
    expect(decimalToCents('0.07')).toBe(7);
    expect(decimalToCents('1.234')).toBeNull();
    expect(decimalToCents('-5')).toBeNull();
  });
});
