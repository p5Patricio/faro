import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { MacroOverview } from './MacroOverview.tsx';
import type { MacroOverviewResponse } from './types.ts';

vi.mock('axios');

const OVERVIEW: MacroOverviewResponse = {
  as_of: '2026-10-01T15:30:00Z',
  sections: [
    {
      key: 'inflation',
      label: 'Inflación',
      items: [
        {
          series_id: 'MX_INPC_ANNUAL',
          label: 'Inflación anual México (INPC)',
          country: 'MX',
          unit: 'percent',
          frequency: 'monthly',
          source: 'Banxico',
          status: 'ok',
          latest: { date: '2026-09-15', value: 4.21 },
          previous: { date: '2026-08-31', value: 4.09 },
          history: [
            { date: '2026-07-15', value: 4.4 },
            { date: '2026-08-31', value: 4.09 },
            { date: '2026-09-15', value: 4.21 },
          ],
        },
      ],
    },
    {
      key: 'rates',
      label: 'Tasas',
      items: [
        {
          series_id: 'MX_TIIE_28',
          label: 'TIIE a 28 días',
          country: 'MX',
          unit: 'percent',
          frequency: 'daily',
          source: 'Banxico',
          status: 'not_configured',
          latest: null,
          previous: null,
          history: [],
        },
      ],
    },
  ],
  real_rate: { cetes_364d: 7.1, inflation: 3.85, real_rate: 3.15 },
};

describe('MacroOverview', () => {
  beforeEach(() => {
    vi.mocked(axios.get).mockResolvedValue({ data: OVERVIEW });
  });

  it('renders an ok series, a not-configured Mexican series and the real-rate callout', async () => {
    render(<MacroOverview />);

    // ok series: percentage value, signed change in percentage points, local date, source, sparkline.
    const okCard = (await screen.findByText('Inflación anual México (INPC)')).closest('li')!;
    expect(within(okCard).getByText('4.21%')).toBeInTheDocument();
    expect(within(okCard).getByText('+0.12 pp')).toBeInTheDocument();
    // Date-only value is a local calendar day: Sep 15, never the 14th.
    expect(within(okCard).getByText(/^15 sep/i)).toBeInTheDocument();
    expect(within(okCard).getByText('Fuente: Banxico')).toBeInTheDocument();
    expect(within(okCard).getByRole('img', { name: /^Tendencia de los últimos 3 datos/ })).toBeInTheDocument();
    expect(within(okCard).queryByText('Desactualizado')).not.toBeInTheDocument();

    // not_configured Mexican series: no value, explains how to configure it.
    const missingCard = screen.getByText('TIIE a 28 días').closest('li')!;
    expect(within(missingCard).getByText('La fuente de datos todavía no está configurada.')).toBeInTheDocument();
    expect(within(missingCard).getByText('Configura BANXICO_TOKEN para ver este dato')).toBeInTheDocument();
    expect(within(missingCard).queryByRole('img')).not.toBeInTheDocument();

    // Inflation cadence note, real-rate callout with its formula, and the disclaimer.
    expect(screen.getByText(/no es un dato diario\.$/)).toBeInTheDocument();
    expect(screen.getByText('Tasa real aproximada de los CETES a 364 días: 3.15 %')).toBeInTheDocument();
    expect(screen.getByText('(1 + tasa) / (1 + inflación) − 1')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Información con fines informativos; no es asesoría de inversión. Tasas indicativas, sin impuestos, comisiones ni riesgo cambiario.',
      ),
    ).toBeInTheDocument();
  });
});
