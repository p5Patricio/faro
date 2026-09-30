import { useMemo, useState, type FormEvent } from 'react';
import { AlertTriangle, Info, Landmark, Plus, Trash2 } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { SkeletonLines } from '../../../components/ui/Skeleton.tsx';
import { cn } from '../../../lib/cn.ts';
import {
  BASE_CURRENCY,
  SELECTABLE_CURRENCIES,
  formatCents,
  formatDateOnly,
  formatShortDate,
  parseDateValue,
} from '../lib/format.ts';
import { defaultIsLiquid, isLiquidityUnclassified } from '../lib/liquidity.ts';
import { putNetWorthSnapshot } from '../hooks/useFinanceApi.ts';
import type { NetWorthItem, NetWorthSnapshot } from '../types.ts';

interface NetWorthPanelProps {
  snapshots: NetWorthSnapshot[];
  loading?: boolean;
  error?: string | null;
  onSaved: () => void;
}

/** Net-worth trend sparkline, latest breakdown, and a new-snapshot form. */
export function NetWorthPanel({ snapshots, loading, error, onSaved }: NetWorthPanelProps) {
  const latest = snapshots[0];
  const previous = snapshots[1];
  const delta = latest && previous ? latest.net_worth_cents - previous.net_worth_cents : null;
  const liquidityUnclassified = latest ? isLiquidityUnclassified(latest) : false;

  return (
    <Panel title="Patrimonio" icon={<Landmark aria-hidden="true" className="h-4 w-4 text-cobalt" />}>
      {error ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudieron cargar los patrimonios"
        />
      ) : loading && snapshots.length === 0 ? (
        <SkeletonLines rows={4} />
      ) : (
        <div className="space-y-5">
          {snapshots.length === 0 ? (
            <EmptyState
              icon={<Landmark aria-hidden="true" className="h-6 w-6" />}
              title="Todavía no registraste tu patrimonio"
              hint="Carga tu primer corte de activos y pasivos con el formulario de abajo."
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-[1.3fr_1fr]">
              <div className="rounded-2xl border border-hairline bg-surface p-5">
                <h3 className="text-[13px] font-semibold tracking-wide text-ink-secondary">
                  Tendencia · últimos {snapshots.length} {snapshots.length === 1 ? 'corte' : 'cortes'}
                </h3>
                {/* Snapshot totals are sums of BASE amounts, whatever currencies the items are in. */}
                <div className="mt-3 flex flex-wrap gap-x-8 gap-y-3">
                  <div>
                    <p className="text-xs text-ink-muted">Patrimonio neto</p>
                    <p className="font-display mt-1 text-[28px] leading-none tabular-nums text-ink">
                      {formatCents(latest.net_worth_cents, BASE_CURRENCY)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-ink-muted">Activos líquidos</p>
                    <p className="font-display mt-1 text-[28px] leading-none tabular-nums text-ink">
                      {liquidityUnclassified || latest.liquid_assets_cents == null
                        ? 'Sin clasificar'
                        : formatCents(latest.liquid_assets_cents, BASE_CURRENCY)}
                    </p>
                  </div>
                </div>
                {liquidityUnclassified ? (
                  <p className="mt-3 flex items-start gap-2 text-[13px] text-ink-secondary">
                    <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{liquidityNotice(latest)}</span>
                  </p>
                ) : null}
                {delta != null && previous ? (
                  <p
                    className={cn(
                      'mt-1 text-[13px] font-medium',
                      delta >= 0 ? 'text-status-good' : 'text-status-critical',
                    )}
                  >
                    {delta >= 0 ? '↑' : '↓'} {formatCents(Math.abs(delta), BASE_CURRENCY)} vs.{' '}
                    {formatMonthName(previous.snapshot_date)}
                  </p>
                ) : null}
                <div className="mt-4">
                  <NetWorthSparkline snapshots={snapshots} />
                </div>
              </div>

              <div className="rounded-2xl border border-hairline bg-surface p-5">
                <h3 className="text-[13px] font-semibold tracking-wide text-ink-secondary">
                  Corte del {formatShortDate(latest.snapshot_date)}
                </h3>
                <div className="mt-3 flex flex-col">
                  {latest.items.map((item, index) => (
                    <NetWorthItemRow key={`${item.label}-${index}`} item={item} />
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="border-t border-hairline/60 pt-4">
            <NetWorthForm onSaved={onSaved} />
          </div>
        </div>
      )}
    </Panel>
  );
}

function NetWorthItemRow({ item }: { item: NetWorthItem }) {
  const isForeign = item.currency !== BASE_CURRENCY;
  return (
    <div className="flex items-center justify-between gap-3 border-b border-hairline/60 py-2 text-sm last:border-b-0">
      <span className={item.is_asset ? 'text-ink' : 'text-status-critical'}>
        {item.label}
        {item.is_asset && item.is_liquid !== undefined ? (
          <span className="ml-2 text-xs font-normal text-ink-muted">{liquidityLabel(item.is_liquid)}</span>
        ) : null}
      </span>
      <span className={cn('text-right font-medium tabular-nums', item.is_asset ? 'text-ink' : 'text-status-critical')}>
        {item.is_asset ? '' : '–'}
        {formatCents(Math.abs(item.amount_cents), item.currency)}
        {isForeign && item.amount_base_cents != null ? (
          <span className="block text-xs font-normal text-ink-muted">
            ≈ {formatCents(Math.abs(item.amount_base_cents), BASE_CURRENCY)}
          </span>
        ) : null}
      </span>
    </div>
  );
}

function liquidityLabel(isLiquid: boolean | null): string {
  if (isLiquid === true) return 'Líquido';
  if (isLiquid === false) return 'No líquido';
  return 'Sin clasificar';
}

function liquidityNotice(snapshot: NetWorthSnapshot): string {
  if (snapshot.liquidity_flags_available === false) {
    return 'Los activos líquidos todavía no se pueden calcular: falta aplicar la migración de liquidez en la base de datos.';
  }
  return 'Todavía no has marcado cuáles de tus activos son líquidos. Guarda un corte nuevo y marca «Líquido» en el dinero que podrías usar en una emergencia.';
}

function formatMonthName(value: string): string {
  return new Intl.DateTimeFormat('es-MX', { month: 'long' }).format(parseDateValue(value));
}

const SPARKLINE_WIDTH = 560;
const SPARKLINE_HEIGHT = 140;
const SPARKLINE_PAD_TOP = 16;
const SPARKLINE_PAD_BOTTOM = 20;

/**
 * Thin hairline-grid sparkline ported from the approved mockup: a faint
 * 3-line grid, a 2px trend line, a soft area fill, and a single end-point
 * marker dot. Plain SVG -- no charting library needed for this shape.
 */
function NetWorthSparkline({ snapshots }: { snapshots: NetWorthSnapshot[] }) {
  const sparkline = useMemo(() => buildSparkline(snapshots), [snapshots]);

  if (!sparkline) {
    return (
      <div className="flex h-[140px] items-center justify-center rounded-lg border border-dashed border-hairline text-sm text-ink-muted">
        Se necesita más de un corte para ver la tendencia
      </div>
    );
  }

  const { linePath, areaPath, lastPoint, firstDate, lastDate } = sparkline;

  return (
    <svg viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`} className="w-full" role="img" aria-hidden="true">
      <line x1={0} y1={20} x2={SPARKLINE_WIDTH} y2={20} stroke="var(--color-hairline)" strokeWidth={1} />
      <line x1={0} y1={70} x2={SPARKLINE_WIDTH} y2={70} stroke="var(--color-hairline)" strokeWidth={1} />
      <line x1={0} y1={120} x2={SPARKLINE_WIDTH} y2={120} stroke="var(--color-hairline)" strokeWidth={1} />
      <path d={linePath} fill="none" stroke="var(--color-beam)" strokeWidth={2} />
      <path d={areaPath} fill="var(--color-beam)" fillOpacity={0.08} />
      <circle cx={lastPoint.x} cy={lastPoint.y} r={4} fill="var(--color-beam)" />
      <text x={2} y={16} fill="var(--color-ink-muted)" fontSize={10}>
        {firstDate}
      </text>
      <text x={SPARKLINE_WIDTH - 28} y={16} fill="var(--color-ink-muted)" fontSize={10}>
        {lastDate}
      </text>
    </svg>
  );
}

function buildSparkline(snapshots: NetWorthSnapshot[]) {
  const ordered = [...snapshots]
    .filter((snapshot) => Number.isFinite(snapshot.net_worth_cents))
    .sort((a, b) => parseDateValue(a.snapshot_date).getTime() - parseDateValue(b.snapshot_date).getTime());
  if (ordered.length < 2) return null;

  const values = ordered.map((snapshot) => snapshot.net_worth_cents);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const innerHeight = SPARKLINE_HEIGHT - SPARKLINE_PAD_TOP - SPARKLINE_PAD_BOTTOM;
  const stepX = SPARKLINE_WIDTH / (ordered.length - 1);

  const points = ordered.map((snapshot, index) => {
    const x = index * stepX;
    const normalized = (snapshot.net_worth_cents - min) / range;
    const y = SPARKLINE_PAD_TOP + (1 - normalized) * innerHeight;
    return { x, y };
  });

  const linePath = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L${SPARKLINE_WIDTH},${SPARKLINE_HEIGHT} L0,${SPARKLINE_HEIGHT} Z`;
  const shortMonth = new Intl.DateTimeFormat('es-MX', { month: 'short' });

  return {
    linePath,
    areaPath,
    lastPoint: points[points.length - 1],
    firstDate: shortMonth.format(parseDateValue(ordered[0].snapshot_date)),
    lastDate: shortMonth.format(parseDateValue(ordered[ordered.length - 1].snapshot_date)),
  };
}

interface DraftItem {
  key: string;
  is_asset: boolean;
  label: string;
  item_type: string;
  amount: string;
  currency: string;
  // Rate to the base currency; only used (and required) when `currency` is not the base.
  fx: string;
  // Assets only. Starts from the item type (cash-like = liquid) until the user
  // toggles it, and is always sent for an asset: what the checkbox shows is
  // what is saved.
  is_liquid: boolean;
  liquid_touched: boolean;
}

function newDraftItem(isAsset: boolean): DraftItem {
  return {
    key: crypto.randomUUID(),
    is_asset: isAsset,
    label: '',
    item_type: 'other',
    amount: '',
    currency: BASE_CURRENCY,
    fx: '',
    is_liquid: false,
    liquid_touched: false,
  };
}

function NetWorthForm({ onSaved }: { onSaved: () => void }) {
  const [snapshotDate, setSnapshotDate] = useState(() => formatDateOnly());
  const [notes, setNotes] = useState('');
  const [items, setItems] = useState<DraftItem[]>([newDraftItem(true)]);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const updateItem = (key: string, patch: Partial<DraftItem>) => {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  };

  const removeItem = (key: string) => {
    setItems((current) => current.filter((item) => item.key !== key));
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const filledItems = items.filter((item) => item.label.trim() && item.amount);
    if (filledItems.length === 0) {
      setStatus('Agrega al menos un concepto con monto.');
      return;
    }
    if (filledItems.some((item) => item.currency !== BASE_CURRENCY && !(Number(item.fx) > 0))) {
      setStatus(`Ingresa el tipo de cambio a ${BASE_CURRENCY} de cada concepto en otra moneda.`);
      return;
    }
    const validItems: NetWorthItem[] = filledItems.map((item) => ({
      is_asset: item.is_asset,
      label: item.label.trim(),
      item_type: item.item_type.trim() || 'other',
      amount_cents: Math.round(Number(item.amount) * 100),
      currency: item.currency,
      ...(item.currency !== BASE_CURRENCY ? { fx_rate_to_base: Number(item.fx) } : {}),
      ...(item.is_asset ? { is_liquid: item.is_liquid } : {}),
    }));
    setSaving(true);
    setStatus(null);
    try {
      await putNetWorthSnapshot({ snapshot_date: snapshotDate, notes: notes || undefined, items: validItems });
      setStatus('Corte guardado.');
      setItems([newDraftItem(true)]);
      setNotes('');
      onSaved();
    } catch {
      setStatus('No se pudo guardar el corte.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-xs text-ink-muted">
          Fecha del corte
          <input
            type="date"
            value={snapshotDate}
            onChange={(event) => setSnapshotDate(event.target.value)}
            required
            className="mt-1 h-9 rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
          />
        </label>
        <label className="block flex-1 min-w-[12rem] text-xs text-ink-muted">
          Notas (opcional)
          <input
            type="text"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
          />
        </label>
      </div>

      <div className="space-y-2">
        {items.map((item) => (
          <div key={item.key} className="space-y-2 rounded-lg border border-hairline p-2">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[auto_1fr_auto_auto_auto_auto]">
              <select
                value={item.is_asset ? 'asset' : 'liability'}
                onChange={(event) => updateItem(item.key, { is_asset: event.target.value === 'asset' })}
                className="h-9 rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none focus:border-cobalt/40"
              >
                <option value="asset">Activo</option>
                <option value="liability">Pasivo</option>
              </select>
              <input
                type="text"
                placeholder="Concepto (ej. Cuenta de ahorro)"
                value={item.label}
                onChange={(event) => updateItem(item.key, { label: event.target.value })}
                className="h-9 rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none focus:border-cobalt/40"
              />
              <input
                type="text"
                placeholder="Categoría"
                value={item.item_type}
                onChange={(event) =>
                  updateItem(item.key, {
                    item_type: event.target.value,
                    ...(item.liquid_touched ? {} : { is_liquid: defaultIsLiquid(event.target.value) }),
                  })
                }
                className="h-9 w-28 rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none focus:border-cobalt/40"
              />
              <input
                type="number"
                step="0.01"
                placeholder="Monto"
                value={item.amount}
                onChange={(event) => updateItem(item.key, { amount: event.target.value })}
                className="h-9 w-28 rounded-lg border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none focus:border-cobalt/40"
              />
              <select
                aria-label="Moneda"
                value={item.currency}
                onChange={(event) => updateItem(item.key, { currency: event.target.value })}
                className="h-9 rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none focus:border-cobalt/40"
              >
                {SELECTABLE_CURRENCIES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => removeItem(item.key)}
                disabled={items.length <= 1}
                className="inline-flex h-9 items-center justify-center rounded-lg border border-hairline px-2 text-ink-muted transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Quitar concepto"
              >
                <Trash2 aria-hidden="true" className="h-4 w-4" />
              </button>
            </div>
            {item.is_asset ? (
              <label className="flex items-start gap-2 text-xs text-ink-muted">
                <input
                  type="checkbox"
                  checked={item.is_liquid}
                  onChange={(event) => updateItem(item.key, { is_liquid: event.target.checked, liquid_touched: true })}
                  className="mt-0.5 h-4 w-4 shrink-0"
                />
                <span>
                  <span className="font-medium text-ink-secondary">Líquido</span> · dinero que podrías usar en una
                  emergencia
                </span>
              </label>
            ) : null}
            {item.currency !== BASE_CURRENCY ? (
              <label className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                Tipo de cambio a {BASE_CURRENCY} (1 {item.currency} = ? {BASE_CURRENCY})
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="any"
                  value={item.fx}
                  onChange={(event) => updateItem(item.key, { fx: event.target.value })}
                  className="h-9 w-32 rounded-lg border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none focus:border-cobalt/40"
                />
              </label>
            ) : null}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setItems((current) => [...current, newDraftItem(true)])}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-hairline px-3 text-sm text-ink-secondary transition hover:bg-white/5"
        >
          <Plus aria-hidden="true" className="h-4 w-4" /> Agregar activo
        </button>
        <button
          type="button"
          onClick={() => setItems((current) => [...current, newDraftItem(false)])}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-hairline px-3 text-sm text-ink-secondary transition hover:bg-white/5"
        >
          <Plus aria-hidden="true" className="h-4 w-4" /> Agregar pasivo
        </button>
        <button
          type="submit"
          disabled={saving}
          className="ml-auto inline-flex h-9 items-center justify-center rounded-lg border border-cobalt/30 bg-cobalt/10 px-3 text-sm font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? 'Guardando' : 'Guardar corte'}
        </button>
      </div>

      {status ? <p className="text-xs text-ink-muted">{status}</p> : null}
    </form>
  );
}
