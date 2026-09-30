import { useState, type FormEvent } from 'react';
import { AlertTriangle, ListChecks } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { SkeletonTable } from '../../../components/ui/Skeleton.tsx';
import { cn } from '../../../lib/cn.ts';
import { BASE_CURRENCY, formatCents } from '../lib/format.ts';
import { putBudget } from '../hooks/useFinanceApi.ts';
import type { BreakdownBucket, CategoryBreakdownRow, FinanceCategory } from '../types.ts';

/**
 * Slug -> categorical color-token class. Fixed order, validated against
 * `--color-surface` (see `ui/src/index.css`). A slug with no explicit
 * mapping (e.g. a future category) falls back to a neutral ink tone
 * rather than guessing a hue.
 */
const CATEGORY_BAR_CLASS: Record<string, string> = {
  vivienda: 'bg-cat-vivienda',
  alimentacion: 'bg-cat-alimentacion',
  transporte: 'bg-cat-transporte',
  servicios: 'bg-cat-servicios',
  salud: 'bg-cat-salud',
  'educacion-hijos': 'bg-cat-educacion',
  'gastos-personales': 'bg-cat-personales',
  entretenimiento: 'bg-cat-entretenimiento',
  ropa: 'bg-cat-ropa',
  'ahorro-inversion': 'bg-cat-ahorro',
};
const FALLBACK_BAR_CLASS = 'bg-ink-muted';

const BUCKET_LABEL: Record<BreakdownBucket, string> = {
  necesidad: 'Necesidad',
  deseo: 'Deseo',
  ahorro_inversion: 'Ahorro e inversión',
  sin_categoria: 'Sin clasificar',
};

interface CategoryBreakdownPanelProps {
  /** The month's spend by category (from `/summary`); the rows add up to the month's total expense. */
  breakdown: CategoryBreakdownRow[];
  /** Feeds the budget form's category picker. */
  categories: FinanceCategory[];
  month: string;
  loading?: boolean;
  error?: string | null;
  onSaved: () => void;
}

/**
 * The month's spend by category: budgeted categories keep their budget bar,
 * unbudgeted ones show their actual spend, and the "Sin categoría" row holds
 * what no category claims -- so nothing the month spent goes missing from the
 * list. Also an inline form to set a limit.
 */
export function CategoryBreakdownPanel({
  breakdown,
  categories,
  month,
  loading,
  error,
  onSaved,
}: CategoryBreakdownPanelProps) {
  const totalCents = breakdown.reduce((sum, row) => sum + row.actual_cents, 0);

  return (
    <Panel title="Categorías y presupuesto" icon={<ListChecks aria-hidden="true" className="h-4 w-4 text-cobalt" />}>
      {error ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudo cargar el desglose por categoría"
        />
      ) : loading && breakdown.length === 0 ? (
        <SkeletonTable rows={4} />
      ) : breakdown.length === 0 ? (
        <EmptyState
          icon={<ListChecks aria-hidden="true" className="h-6 w-6" />}
          title="Sin gastos ni presupuestos este mes"
          hint="Registra gastos para ver su desglose por categoría, o define un límite con el formulario de abajo."
        />
      ) : (
        <div className="flex flex-col">
          {breakdown.map((row) => (
            <CategoryRow key={row.category_id ?? 'sin-categoria'} row={row} />
          ))}
          <div className="flex items-baseline justify-between gap-3 border-t border-hairline pt-2.5 text-sm">
            <span className="font-medium text-ink">
              Total de gastos del mes <span className="text-xs font-normal text-ink-muted">(incluye lo ahorrado)</span>
            </span>
            <span className="font-semibold tabular-nums text-ink">{formatCents(totalCents, BASE_CURRENCY)}</span>
          </div>
        </div>
      )}

      <div className="mt-5 border-t border-hairline/60 pt-4">
        <BudgetForm categories={categories} month={month} onSaved={onSaved} />
      </div>
    </Panel>
  );
}

function CategoryRow({ row }: { row: CategoryBreakdownRow }) {
  const budget = row.budget_cents;
  const hasBudget = budget !== null;
  // A budget of zero is a budget: any spend against it is over the limit.
  const over = hasBudget && row.actual_cents > budget;
  const pct = hasBudget && budget > 0 ? (row.actual_cents / budget) * 100 : 0;
  const barColor = (row.slug ? CATEGORY_BAR_CLASS[row.slug] : undefined) ?? FALLBACK_BAR_CLASS;

  return (
    <div className="grid grid-cols-[28px_1fr_auto] items-center gap-3 border-b border-hairline/60 py-2.5">
      <span className="text-lg" aria-hidden="true">
        {row.emoji ?? '•'}
      </span>
      <div>
        <span className="text-sm font-medium text-ink">{row.category_name}</span>{' '}
        {/* The "Sin categoría" row is already "unclassified"; a label would only repeat it. */}
        {row.category_id !== null ? (
          <span className="text-xs text-ink-muted">· {BUCKET_LABEL[row.bucket]}</span>
        ) : null}
        {hasBudget ? (
          <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-surface-2">
            <div
              className={cn('h-full rounded-full', over ? 'bg-status-critical' : barColor)}
              style={{ width: `${over ? 100 : Math.min(pct, 100)}%` }}
            />
          </div>
        ) : null}
      </div>
      <div className="text-right text-[13px] font-medium">
        <span className={cn('block tabular-nums', over ? 'text-status-critical' : 'text-ink')}>
          {formatCents(row.actual_cents, BASE_CURRENCY)}
        </span>
        {hasBudget ? (
          <span className="block text-xs font-normal tabular-nums text-ink-muted">
            de {formatCents(budget, BASE_CURRENCY)}
          </span>
        ) : (
          <span className="block text-xs font-normal text-ink-muted">Sin presupuesto</span>
        )}
        {over ? (
          <span className="flex items-center justify-end gap-1 text-xs font-medium text-status-critical">
            <AlertTriangle aria-hidden="true" className="h-3 w-3 shrink-0" />
            Excedido
          </span>
        ) : null}
      </div>
    </div>
  );
}

function BudgetForm({
  categories,
  month,
  onSaved,
}: {
  categories: FinanceCategory[];
  month: string;
  onSaved: () => void;
}) {
  const [categoryId, setCategoryId] = useState('');
  const [limit, setLimit] = useState('');
  const [percentOfIncome, setPercentOfIncome] = useState('');
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!categoryId || !limit) return;
    setSaving(true);
    setStatus(null);
    try {
      await putBudget({
        category_id: categoryId,
        period_month: `${month}-01`,
        limit_cents: Math.round(Number(limit) * 100),
        percent_of_income: percentOfIncome ? Number(percentOfIncome) : undefined,
        // Budgets are base-currency only in v1; the API rejects anything else.
        currency: BASE_CURRENCY,
      });
      setStatus('Presupuesto guardado.');
      setLimit('');
      setPercentOfIncome('');
      onSaved();
    } catch {
      setStatus('No se pudo guardar el presupuesto.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-5 sm:items-end">
      <label className="block text-xs text-ink-muted sm:col-span-2">
        Categoría
        <select
          value={categoryId}
          onChange={(event) => setCategoryId(event.target.value)}
          required
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        >
          <option value="" disabled>
            Elegí una categoría
          </option>
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.emoji ? `${category.emoji} ` : ''}
              {category.name}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-ink-muted">
        Límite mensual
        <input
          type="number"
          min="0"
          step="0.01"
          value={limit}
          onChange={(event) => setLimit(event.target.value)}
          required
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted">
        % del ingreso
        <input
          type="number"
          min="0"
          max="100"
          step="1"
          value={percentOfIncome}
          onChange={(event) => setPercentOfIncome(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted">
        Moneda
        <input
          type="text"
          value={BASE_CURRENCY}
          readOnly
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm uppercase text-ink-muted outline-none"
        />
      </label>

      <button
        type="submit"
        disabled={saving}
        className="inline-flex h-9 items-center justify-center rounded-lg border border-cobalt/30 bg-cobalt/10 px-3 text-sm font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-5"
      >
        {saving ? 'Guardando' : 'Guardar presupuesto'}
      </button>

      {status ? <p className="text-xs text-ink-muted sm:col-span-5">{status}</p> : null}
    </form>
  );
}
