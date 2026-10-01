import { AlertTriangle, ArrowDown, ArrowUp, Clock, Globe, Minus } from 'lucide-react';
import { EmptyState } from '../../components/ui/EmptyState.tsx';
import { Panel } from '../../components/ui/Panel.tsx';
import { SkeletonLines } from '../../components/ui/Skeleton.tsx';
import { cn } from '../../lib/cn.ts';
import { parseDateValue } from '../finance/lib/format.ts';
import type { MarketItem } from './types.ts';
import { useMarketsOverview } from './useMarketsOverview.ts';

const NUMBER_FORMAT = new Intl.NumberFormat('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const DAY_FORMAT = new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'short', year: 'numeric' });
const TIMESTAMP_FORMAT = new Intl.DateTimeFormat('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
const MISSING = '—';

function formatLast(item: MarketItem): string {
  if (!Number.isFinite(item.last)) return MISSING;
  if (item.unit === 'percent') return `${NUMBER_FORMAT.format(item.last)}%`;
  if (item.unit === 'price' && item.currency) {
    try {
      return new Intl.NumberFormat('es-MX', { style: 'currency', currency: item.currency }).format(item.last);
    } catch {
      return NUMBER_FORMAT.format(item.last); // not a valid ISO currency code
    }
  }
  return NUMBER_FORMAT.format(item.last);
}

/** `as_of` is a date-only value: parse it as a LOCAL day so it never slips to the previous day. */
function formatDay(value: string): string {
  const date = parseDateValue(value);
  return Number.isNaN(date.getTime()) ? value : DAY_FORMAT.format(date);
}

function formatTimestamp(value: string): string | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : TIMESTAMP_FORMAT.format(date);
}

/** Direction comes from the sign, an arrow and the colour -- never the colour alone. */
function ChangeIndicator({ value }: { value: number }) {
  if (!Number.isFinite(value)) return <span className="text-sm text-slate-500">{MISSING}</span>;
  const rounded = Math.round(value * 100) / 100;
  const sign = rounded > 0 ? '+' : rounded < 0 ? '-' : '';
  const Icon = rounded > 0 ? ArrowUp : rounded < 0 ? ArrowDown : Minus;
  const tone = rounded > 0 ? 'text-emerald-300' : rounded < 0 ? 'text-red-300' : 'text-slate-400';
  return (
    <span className={cn('inline-flex items-center gap-1 text-sm font-medium tabular-nums', tone)}>
      <Icon aria-hidden="true" className="h-3.5 w-3.5" />
      {`${sign}${NUMBER_FORMAT.format(Math.abs(rounded))}%`}
    </span>
  );
}

function MarketCard({ item }: { item: MarketItem }) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-hairline/70 bg-inset p-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-slate-100" title={item.name}>
          {item.name}
        </p>
        <p className="font-mono text-xs text-slate-500">{item.ticker}</p>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-lg font-semibold tabular-nums text-slate-50">{formatLast(item)}</span>
        <ChangeIndicator value={item.change_pct} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <time dateTime={item.as_of}>{formatDay(item.as_of)}</time>
        {item.stale ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-0.5 text-amber-200">
            <Clock aria-hidden="true" className="h-3 w-3" />
            Desactualizado
          </span>
        ) : null}
      </div>
    </li>
  );
}

function LoadingState() {
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <span className="sr-only">Cargando panorama de mercados…</span>
      <SkeletonLines rows={2} className="max-w-xs" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className="h-28 rounded-lg border border-hairline/60 bg-inset" />
        ))}
      </div>
    </div>
  );
}

/**
 * "Panorama" view: indices, rates, commodities and crypto grouped as card
 * grids, fed by `GET /markets/overview`. Owns the fetch via
 * `useMarketsOverview` (same container shape as `HeatmapDashboard`).
 */
export function MarketsOverview() {
  const { data, loading, error, refetch } = useMarketsOverview();
  const groups = (data?.groups ?? []).filter((group) => group.items.length > 0);
  const updatedAt = data ? formatTimestamp(data.as_of) : null;

  return (
    <Panel
      title="Panorama de mercados"
      icon={<Globe aria-hidden="true" className="h-4 w-4 text-cobalt" />}
      actions={updatedAt ? <span className="text-xs text-slate-500">Actualizado: {updatedAt}</span> : null}
    >
      {loading && !data ? (
        <LoadingState />
      ) : error ? (
        <EmptyState
          variant="error"
          icon={<Globe aria-hidden="true" className="h-6 w-6" />}
          title={error}
          onRetry={() => void refetch()}
        />
      ) : groups.length === 0 ? (
        <EmptyState
          icon={<Globe aria-hidden="true" className="h-6 w-6" />}
          title="Sin datos de mercado para mostrar."
        />
      ) : (
        <div className="space-y-5">
          {data?.is_demo ? (
            <div
              role="status"
              className="flex items-center gap-2 rounded-lg border border-amber-300/50 bg-amber-300/10 px-3 py-2.5 text-sm font-semibold text-amber-100"
            >
              <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />
              Datos de demostración, no son reales
            </div>
          ) : null}

          {groups.map((group) => (
            <section key={group.key} aria-labelledby={`markets-group-${group.key}`} className="space-y-2">
              <h3 id={`markets-group-${group.key}`} className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {group.label}
              </h3>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {group.items.map((item) => (
                  <MarketCard key={item.ticker} item={item} />
                ))}
              </ul>
            </section>
          ))}

          <p className="text-xs text-slate-500">Información con fines informativos; no es asesoría de inversión.</p>
        </div>
      )}
    </Panel>
  );
}
