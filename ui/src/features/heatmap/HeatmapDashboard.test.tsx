import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { HeatmapDashboard } from './HeatmapDashboard.tsx';

vi.mock('axios');

// jsdom has no real <canvas> 2D context, so ECharts itself can't actually
// render here -- stub the wrapper with a lightweight probe that exposes
// what HeatmapDashboard handed it (tile count via the treemap series data),
// same spirit as mocking axios: verify OUR wiring, not the chart library.
vi.mock('echarts-for-react/lib/core', () => ({
  default: ({ option }: { option: { series: Array<{ data: unknown[] }> } }) => (
    <div data-testid="heatmap-chart" data-tile-count={option.series[0].data.length} />
  ),
}));

const TILES = [
  {
    ticker: 'AAPL',
    name: 'Apple Inc.',
    sector: 'Information Technology',
    market_cap: 3_000_000_000_000,
    change_pct: 1.23,
    price: 220.5,
  },
  {
    ticker: 'MSFT',
    name: 'Microsoft Corp.',
    sector: 'Information Technology',
    market_cap: 2_800_000_000_000,
    change_pct: -0.87,
    price: 480.1,
  },
];

describe('HeatmapDashboard', () => {
  beforeEach(() => {
    vi.mocked(axios.get).mockResolvedValue({ data: TILES });
  });

  it('renders the treemap with one tile per ticker once the API responds', async () => {
    render(<HeatmapDashboard />);

    const chart = await screen.findByTestId('heatmap-chart');
    expect(chart).toHaveAttribute('data-tile-count', '2');
    expect(screen.getByText('2 tickers')).toBeInTheDocument();
  });

  it('renders an honest empty state when the API returns no tiles', async () => {
    vi.mocked(axios.get).mockResolvedValue({ data: [] });

    render(<HeatmapDashboard />);

    expect(await screen.findByText('Sin datos de mercado para mostrar.')).toBeInTheDocument();
  });

  it('renders a retryable error state when the request fails', async () => {
    vi.mocked(axios.get).mockRejectedValue(new Error('network down'));

    render(<HeatmapDashboard />);

    expect(await screen.findByText('No se pudo cargar el mapa de mercado.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument();
  });
});
