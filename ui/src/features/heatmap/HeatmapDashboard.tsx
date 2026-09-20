import { useMemo } from 'react';
import * as ReactEChartsCoreModule from 'echarts-for-react/lib/core';

// `echarts-for-react/lib/core` is CJS, compiled by TypeScript as
// `exports.default = EChartsReactCore`. The dev server's esbuild
// pre-bundling unwraps that to the class itself, but `vite build`'s
// bundler (Rolldown) wraps the whole CJS `module.exports` object as this
// namespace's OWN `.default` -- so `import ReactEChartsCore from '...'`
// gets `{ default: EChartsReactCore, __esModule: true }` (an object, not a
// component) in production only, crashing with React error #130 ("element
// type is invalid... got: object"). Walk `.default` until something is
// actually a function/class, regardless of how many times it's wrapped.
function unwrapDefault<T>(mod: unknown): T {
  let candidate = mod;
  while (candidate && typeof candidate !== 'function' && 'default' in (candidate as object)) {
    candidate = (candidate as { default: unknown }).default;
  }
  return candidate as T;
}

const ReactEChartsCore = unwrapDefault<typeof import('echarts-for-react/lib/core').default>(
  ReactEChartsCoreModule,
);
import { LayoutGrid } from 'lucide-react';
import { Panel } from '../../components/ui/Panel.tsx';
import { EmptyState } from '../../components/ui/EmptyState.tsx';
import { SkeletonLines } from '../../components/ui/Skeleton.tsx';
import { useHeatmap } from './hooks/useHeatmapApi.ts';
import echarts from './lib/echartsCore.ts';
import type { HeatmapTile } from './types.ts';

// Diverging red -> neutral gray -> green scale keyed to `change_pct` --
// the Finviz convention (green = up, red = down). The poles reuse this
// app's own already-validated status tokens (ui/src/index.css
// --color-status-critical / --color-status-good); the midpoint is a
// neutral slate close to --color-ink-muted -- gray rather than white,
// since white would read as a bright highlight (not "neutral") against
// this dashboard's dark canvas. The domain is a fixed +/-6% band (values
// beyond clamp to the pole color) so one outlier ticker on a volatile day
// doesn't wash out every other tile's color.
const COLOR_DOMAIN_PCT = 6;
const DIVERGING_COLORS = ['#e0575a', '#5b6472', '#35b06a'];

interface TreemapNode {
  name: string;
  value: [number, number];
  ticker: string;
  companyName: string;
  sector: string;
  price: number;
  change_pct: number;
  market_cap: number;
}

function toTreemapNode(tile: HeatmapTile): TreemapNode {
  return {
    // ECharts' own "name" field (breadcrumb/id) -- the ticker, not the
    // full company name, which is kept separately as `companyName` below.
    name: tile.ticker,
    // value[0] sizes the tile (market_cap); value[1] is what visualMap's
    // `dimension: 1` reads to color it (change_pct).
    value: [tile.market_cap, tile.change_pct],
    ticker: tile.ticker,
    companyName: tile.name,
    sector: tile.sector,
    price: tile.price,
    change_pct: tile.change_pct,
    market_cap: tile.market_cap,
  };
}

function formatChangePct(value: number): string {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function formatMarketCap(value: number): string {
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(0)}M`;
  return `$${value.toFixed(0)}`;
}

function buildTreemapOption(tiles: HeatmapTile[]) {
  return {
    backgroundColor: 'transparent',
    tooltip: {
      borderWidth: 0,
      backgroundColor: '#16213f',
      textStyle: { color: '#eef1fb' },
      formatter: (info: { data: TreemapNode }) => {
        const node = info.data;
        return [
          `<strong>${node.ticker}</strong> &middot; ${node.companyName}`,
          node.sector,
          `Precio: $${node.price.toFixed(2)} &nbsp; Cambio: ${formatChangePct(node.change_pct)}`,
          // "estimada": see the market_cap doc comment in ../types.ts --
          // this is a placeholder proxy, not sourced market-cap data.
          `Cap. de mercado (estimada): ${formatMarketCap(node.market_cap)}`,
        ].join('<br/>');
      },
    },
    visualMap: {
      show: true,
      type: 'continuous',
      min: -COLOR_DOMAIN_PCT,
      max: COLOR_DOMAIN_PCT,
      dimension: 1,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 4,
      itemWidth: 14,
      itemHeight: 120,
      text: [`+${COLOR_DOMAIN_PCT}%`, `-${COLOR_DOMAIN_PCT}%`],
      textStyle: { color: '#aab3cf', fontSize: 11 },
      inRange: { color: DIVERGING_COLORS },
    },
    series: [
      {
        type: 'treemap',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        itemStyle: { borderColor: '#0a0f1e', borderWidth: 2, gapWidth: 2 },
        upperLabel: { show: false },
        label: {
          show: true,
          overflow: 'truncate',
          color: '#fff',
          formatter: (info: { data: TreemapNode }) =>
            `{ticker|${info.data.ticker}}\n{pct|${formatChangePct(info.data.change_pct)}}`,
          rich: {
            ticker: { fontSize: 13, fontWeight: 600, lineHeight: 18, color: '#fff' },
            pct: { fontSize: 11, lineHeight: 14, color: 'rgba(255,255,255,0.85)' },
          },
        },
        data: tiles.map(toTreemapNode),
      },
    ],
  };
}

/**
 * Finviz-style S&P-100 market heatmap: one treemap tile per US ticker,
 * sized by (estimated) market cap and colored by the day's %% change.
 * Mirrors `features/finance/FinanceDashboard.tsx`'s container shape: owns
 * the data fetch via `hooks/useHeatmapApi.ts` and hands it to the chart.
 */
export function HeatmapDashboard() {
  const { data: tiles, loading, error, refetch } = useHeatmap('us');
  const option = useMemo(() => buildTreemapOption(tiles), [tiles]);
  const firstLoad = loading && tiles.length === 0;

  return (
    <Panel
      title="Mapa de mercado (S&P 100, EE. UU.)"
      icon={<LayoutGrid aria-hidden="true" className="h-4 w-4 text-cobalt" />}
      actions={tiles.length > 0 ? <span className="text-xs text-slate-500">{tiles.length} tickers</span> : null}
    >
      {firstLoad ? (
        <div className="space-y-3">
          <SkeletonLines rows={2} className="max-w-xs" />
          <div className="h-[520px] rounded-lg border border-hairline/60 bg-inset" />
        </div>
      ) : error && tiles.length === 0 ? (
        <EmptyState
          variant="error"
          icon={<LayoutGrid aria-hidden="true" className="h-6 w-6" />}
          title={error}
          onRetry={() => void refetch()}
        />
      ) : tiles.length === 0 ? (
        <EmptyState
          icon={<LayoutGrid aria-hidden="true" className="h-6 w-6" />}
          title="Sin datos de mercado para mostrar."
        />
      ) : (
        <ReactEChartsCore
          echarts={echarts}
          option={option}
          notMerge
          lazyUpdate
          style={{ height: 560, width: '100%' }}
          opts={{ renderer: 'canvas' }}
        />
      )}
    </Panel>
  );
}
