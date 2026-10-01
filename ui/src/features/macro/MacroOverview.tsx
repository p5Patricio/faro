import { ArrowDown, ArrowUp, Clock, Info, Landmark, Minus } from 'lucide-react';
import { EmptyState } from '../../components/ui/EmptyState.tsx';
import { Panel } from '../../components/ui/Panel.tsx';
import { SkeletonLines } from '../../components/ui/Skeleton.tsx';
import { cn } from '../../lib/cn.ts';
import { parseDateValue } from '../finance/lib/format.ts';
import type { MacroCountry, MacroFrequency, MacroItem, MacroPoint } from './types.ts';
import { useMacroOverview } from './useMacroOverview.ts';

const NUMBER_FORMAT = new Intl.NumberFormat('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const DAY_FORMAT = new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'short', year: 'numeric' });
const TIMESTAMP_FORMAT = new Intl.DateTimeFormat('es-MX', { dateStyle: 'medium', timeStyle: 'short' });

const COUNTRY_LABEL: Record<MacroCountry, string> = { MX: 'México', US: 'EE.UU.' };
const FREQUENCY_LABEL: Record<MacroFrequency, string> = { monthly: 'Mensual', daily: 'Diaria', weekly: 'Semanal' };

const INFLATION_NOTE = 'La inflación oficial se publica cada quincena en México y cada mes en EE.UU.; no es un dato diario.';
const DISCLAIMER =
  'Información con fines informativos; no es asesoría de inversión. Tasas indicativas, sin impuestos, comisiones ni riesgo cambiario.';

const SPARK_WIDTH = 120;
const SPARK_HEIGHT = 32;
const SPARK_PADDING = 2;

function formatPercent(value: number): string {
  return `${NUMBER_FORMAT.format(value)}%`;
}

/** `date` is a date-only value: parse it as a LOCAL day so it never slips to the previous day. */
function formatDay(value: string): string {
  const date = parseDateValue(value);
  return Number.isNaN(date.getTime()) ? value : DAY_FORMAT.format(date);
}

function formatTimestamp(value: string): string | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : TIMESTAMP_FORMAT.format(date);
}

/** Change in percentage points. Direction comes from the sign, an arrow and the colour -- never the colour alone. */
function ChangeIndicator({ latest, previous }: { latest: MacroPoint; previous: MacroPoint | null }) {
  const delta = previous ? latest.value - previous.value : Number.NaN;
  if (!Number.isFinite(delta)) return <span className="text-xs text-slate-500">Sin dato anterior</span>;
  const rounded = Math.round(delta * 100) / 100;
  const sign = rounded > 0 ? '+' : rounded < 0 ? '-' : '';
  const Icon = rounded > 0 ? ArrowUp : rounded < 0 ? ArrowDown : Minus;
  const tone = rounded > 0 ? 'text-emerald-300' : rounded < 0 ? 'text-red-300' : 'text-slate-400';
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn('inline-flex items-center gap-1 text-sm font-medium tabular-nums', tone)}>
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
        {`${sign}${NUMBER_FORMAT.format(Math.abs(rounded))} pp`}
      </span>
      <span className="text-xs text-slate-500">vs. dato anterior</span>
    </span>
  );
}

/** Inline SVG polyline; flat series are drawn as a mid-height line, fewer than two points draw nothing. */
function Sparkline({ history, label }: { history: MacroPoint[]; label: string }) {
  const points = history.filter((point) => Number.isFinite(point.value)).sort((a, b) => a.date.localeCompare(b.date));
  if (points.length < 2) return null;

  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const span = Math.max(...values) - min;
  const coordinates = points
    .map((point, index) => {
      const x = SPARK_PADDING + (index / (points.length - 1)) * (SPARK_WIDTH - 2 * SPARK_PADDING);
      const y =
        span === 0
          ? SPARK_HEIGHT / 2
          : SPARK_PADDING + (1 - (point.value - min) / span) * (SPARK_HEIGHT - 2 * SPARK_PADDING);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      role="img"
      aria-label={`Tendencia de los últimos ${points.length} datos de ${label}`}
      viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
      preserveAspectRatio="none"
      className="h-8 w-full text-cobalt"
    >
      <polyline
        points={coordinates}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function ItemBody({ item }: { item: MacroItem }) {
  const { latest } = item;

  if (item.status === 'not_configured') {
    return (
      <div className="space-y-1 text-sm text-slate-400">
        <p>La fuente de datos todavía no está configurada.</p>
        {item.country === 'MX' ? <p>Configura BANXICO_TOKEN para ver este dato</p> : null}
      </div>
    );
  }

  if (item.status === 'no_data' || !latest || !Number.isFinite(latest.value)) {
    return <p className="text-sm text-slate-400">Todavía no hay datos para esta serie.</p>;
  }

  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-lg font-semibold tabular-nums text-slate-50">{formatPercent(latest.value)}</span>
        <ChangeIndicator latest={latest} previous={item.previous} />
      </div>
      <Sparkline history={item.history} label={item.label} />
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <time dateTime={latest.date}>{formatDay(latest.date)}</time>
        {item.status === 'stale' ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-0.5 text-amber-200">
            <Clock aria-hidden="true" className="h-3 w-3" />
            Desactualizado
          </span>
        ) : null}
      </div>
    </>
  );
}

function MacroCard({ item }: { item: MacroItem }) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-hairline/70 bg-inset p-3">
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-100">{item.label}</p>
        <p className="text-xs text-slate-500">
          {COUNTRY_LABEL[item.country]} · {FREQUENCY_LABEL[item.frequency]}
        </p>
      </div>
      <ItemBody item={item} />
      <p className="text-xs text-slate-500">Fuente: {item.source}</p>
    </li>
  );
}

function RealRateCallout({ value }: { value: number }) {
  return (
    <div className="space-y-1 rounded-lg border border-cobalt/40 bg-cobalt/10 px-3 py-2.5">
      <p className="text-sm font-semibold text-slate-50">
        {`Tasa real aproximada de los CETES a 364 días: ${NUMBER_FORMAT.format(value)} %`}
      </p>
      <p className="text-xs text-slate-400">(1 + tasa) / (1 + inflación) − 1</p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <span className="sr-only">Cargando datos macroeconómicos…</span>
      <SkeletonLines rows={2} className="max-w-xs" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className="h-32 rounded-lg border border-hairline/60 bg-inset" />
        ))}
      </div>
    </div>
  );
}

/**
 * "Macro" view: inflation and interest-rate series as card grids with a
 * sparkline each, plus the approximate real CETES rate. Owns the fetch via
 * `useMacroOverview` (same container shape as `MarketsOverview`).
 */
export function MacroOverview() {
  const { data, loading, error, refetch } = useMacroOverview();
  const sections = (data?.sections ?? []).filter((section) => section.items.length > 0);
  const updatedAt = data ? formatTimestamp(data.as_of) : null;

  return (
    <Panel
      title="Macro"
      icon={<Landmark aria-hidden="true" className="h-4 w-4 text-cobalt" />}
      actions={updatedAt ? <span className="text-xs text-slate-500">Actualizado: {updatedAt}</span> : null}
    >
      {loading && !data ? (
        <LoadingState />
      ) : error ? (
        <EmptyState
          variant="error"
          icon={<Landmark aria-hidden="true" className="h-6 w-6" />}
          title={error}
          onRetry={() => void refetch()}
        />
      ) : sections.length === 0 ? (
        <EmptyState
          icon={<Landmark aria-hidden="true" className="h-6 w-6" />}
          title="Sin datos macroeconómicos para mostrar."
        />
      ) : (
        <div className="space-y-5">
          {sections.map((section) => (
            <section key={section.key} aria-labelledby={`macro-section-${section.key}`} className="space-y-2">
              <h3 id={`macro-section-${section.key}`} className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {section.label}
              </h3>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {section.items.map((item) => (
                  <MacroCard key={item.series_id} item={item} />
                ))}
              </ul>
              {section.key === 'inflation' ? (
                <p className="flex items-start gap-1.5 text-xs text-slate-500">
                  <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {INFLATION_NOTE}
                </p>
              ) : null}
              {section.key === 'rates' && data?.real_rate ? <RealRateCallout value={data.real_rate.real_rate} /> : null}
            </section>
          ))}

          <p className="text-xs text-slate-500">{DISCLAIMER}</p>
        </div>
      )}
    </Panel>
  );
}
