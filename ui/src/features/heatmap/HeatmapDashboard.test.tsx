import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { HeatmapDashboard } from './HeatmapDashboard.tsx';
import type { HeatmapTile } from './types.ts';

vi.mock('axios');

// jsdom has no real <canvas> 2D context, so ECharts itself can't actually
// render here -- stub the wrapper with a lightweight probe that exposes
// what HeatmapDashboard handed it (tile count via the treemap series data,
// plus each tile's tooltip text, since the real tooltip only shows on hover),
// same spirit as mocking axios: verify OUR wiring, not the chart library.
interface ProbeNode {
  ticker: string;
}
interface ProbeOption {
  series: Array<{ data: ProbeNode[] }>;
  tooltip: { formatter: (info: { data: ProbeNode }) => string };
}

vi.mock('echarts-for-react/lib/core', () => ({
  default: ({ option }: { option: ProbeOption }) => (
    <div data-testid="heatmap-chart" data-tile-count={option.series[0].data.length}>
      {option.series[0].data.map((node) => (
        <p key={node.ticker} data-testid={`tooltip-${node.ticker}`}>
          {option.tooltip.formatter({ data: node })}
        </p>
      ))}
    </div>
  ),
}));

const TILES: HeatmapTile[] = [
  {
    ticker: 'AAPL',
    name: 'Apple Inc.',
    sector: 'Information Technology',
    market_cap: 3_000_000_000_000,
    change_pct: 1.23,
    price: 220.5,
    currency: 'USD',
    market_cap_estimated: false,
  },
  {
    ticker: 'MSFT',
    name: 'Microsoft Corp.',
    sector: 'Information Technology',
    market_cap: 2_800_000_000_000,
    change_pct: -0.87,
    price: 480.1,
    currency: 'USD',
    market_cap_estimated: false,
  },
];

const MX_TILES: HeatmapTile[] = [
  {
    ticker: 'WALMEX.MX',
    name: 'Walmart de Mexico',
    sector: 'Consumer Staples',
    market_cap: 900_000_000_000,
    change_pct: 0.4,
    price: 55.25,
    currency: 'MXN',
    market_cap_estimated: false,
  },
  {
    ticker: 'AMXB.MX',
    name: 'America Movil',
    sector: 'Communication Services',
    market_cap: 800_000_000_000,
    change_pct: -1.1,
    price: 17.8,
    currency: 'MXN',
    market_cap_estimated: true,
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

  it('requests the selected market and labels currency and estimated caps per tile', async () => {
    const CA_TILES: HeatmapTile[] = [{ ...MX_TILES[1], ticker: 'RY.TO', currency: 'CAD' }];
    const byMarket: Record<string, HeatmapTile[]> = { us: TILES, mx: MX_TILES, ca: CA_TILES };
    vi.mocked(axios.get).mockImplementation((_url, config) =>
      Promise.resolve({ data: byMarket[(config?.params as { market: string }).market] }),
    );
    const user = userEvent.setup();

    render(<HeatmapDashboard />);

    expect(await screen.findByTestId('tooltip-AAPL')).toHaveTextContent('Precio: $220.50 USD');
    expect(vi.mocked(axios.get)).toHaveBeenLastCalledWith(expect.stringContaining('/heatmap'), {
      params: { market: 'us' },
    });
    // Real values carry no "estimada" label, and no note is shown above the map.
    expect(screen.getByTestId('tooltip-AAPL')).toHaveTextContent('Cap. de mercado: $3.00T USD');
    expect(screen.getByTestId('tooltip-AAPL')).not.toHaveTextContent('estimada');
    expect(screen.queryByText(/Capitalización estimada/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'México' }));

    expect(await screen.findByTestId('tooltip-WALMEX.MX')).toHaveTextContent('Precio: $55.25 MXN');
    expect(vi.mocked(axios.get)).toHaveBeenLastCalledWith(expect.stringContaining('/heatmap'), {
      params: { market: 'mx' },
    });
    // Mixed market: only the estimated tile is labelled, and the all-estimated note stays hidden.
    expect(screen.getByTestId('tooltip-WALMEX.MX')).not.toHaveTextContent('estimada');
    expect(screen.getByTestId('tooltip-AMXB.MX')).toHaveTextContent('Cap. de mercado (estimada): $800.0B MXN');
    expect(screen.queryByText(/Capitalización estimada/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Canadá' }));

    // Every tile estimated: tooltip says CAD and one short note sits above the map.
    expect(await screen.findByTestId('tooltip-RY.TO')).toHaveTextContent('Precio: $17.80 CAD');
    expect(
      screen.getByText('Capitalización estimada: aún no hay datos reales para este mercado.'),
    ).toBeInTheDocument();
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
