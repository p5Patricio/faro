import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { MarketsOverview } from './MarketsOverview.tsx';
import type { MarketsOverviewResponse } from './types.ts';

vi.mock('axios');

const OVERVIEW: MarketsOverviewResponse = {
  as_of: '2026-10-01T15:30:00Z',
  is_demo: true,
  groups: [
    {
      key: 'indices',
      label: 'Índices',
      items: [
        {
          ticker: '^GSPC',
          name: 'S&P 500',
          last: 5432.1,
          change_pct: 1.23,
          as_of: '2026-10-01',
          stale: false,
          currency: null,
          unit: 'points',
        },
      ],
    },
    {
      key: 'commodities',
      label: 'Materias primas',
      items: [
        {
          ticker: 'CL=F',
          name: 'Petróleo WTI',
          last: 71.5,
          change_pct: -0.87,
          as_of: '2026-09-29',
          stale: true,
          currency: 'USD',
          unit: 'price',
        },
      ],
    },
  ],
};

describe('MarketsOverview', () => {
  beforeEach(() => {
    vi.mocked(axios.get).mockResolvedValue({ data: OVERVIEW });
  });

  it('renders signed changes, the stale badge and the demo banner', async () => {
    render(<MarketsOverview />);

    expect(await screen.findByText('Datos de demostración, no son reales')).toBeInTheDocument();
    expect(screen.getByText('+1.23%')).toBeInTheDocument();
    expect(screen.getByText('-0.87%')).toBeInTheDocument();

    // Only the stale reading (the WTI card) carries the badge.
    const badges = screen.getAllByText('Desactualizado');
    expect(badges).toHaveLength(1);
    expect(within(screen.getByText('Petróleo WTI').closest('li')!).getByText('Desactualizado')).toBe(badges[0]);

    // Date-only `as_of` is a local calendar day: Oct 1, not Sep 30.
    expect(screen.getByText(/^1 oct/i)).toBeInTheDocument();
    expect(screen.getByText('Información con fines informativos; no es asesoría de inversión.')).toBeInTheDocument();
  });
});
