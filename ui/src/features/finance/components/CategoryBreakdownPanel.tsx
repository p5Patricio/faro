import { useMemo, useState, type FormEvent } from 'react';
import { AlertTriangle, ListChecks } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { SkeletonTable } from '../../../components/ui/Skeleton.tsx';
import { cn } from '../../../lib/cn.ts';
import { DEFAULT_CURRENCY, formatCents } from '../lib/format.ts';
import { putBudget } from '../hooks/useFinanceApi.ts';
import type { FinanceBudget, FinanceCategory } from '../types.ts';

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

interface CategoryBreakdownPanelProps {
  budgets: FinanceBudget[];
  categories: FinanceCategory[];
  month: string;
  loading?: boolean;
  error?: string | null;
  onSaved: () => void;
}

/** Budgeted vs. actual spend per category, plus an inline form to set a limit. */
export function CategoryBreakdownPanel({
  budgets,
  categories,
  month,
  loading,
  error,
  onSaved,
}: CategoryBreakdownPanelProps) {
  const categoryById = useMemo(() => new Map(categories.map((category) => [category.id, category])), [categories]);

  return (
    <Panel title="Categorías y presupuesto" icon={<ListChecks aria-hidden="true" className="h-4 w-4 text-cobalt" />}>
      {error ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudieron cargar los presupuestos"
        />
      ) : loading && budgets.length === 0 ? (
        <SkeletonTable rows={4} />
      ) : budgets.length === 0 ? (
        <EmptyState
          icon={<ListChecks aria-hidden="true" className="h-6 w-6" />}
          title="Sin presupuestos configurados"
          hint="Definí un límite por categoría con el formulario de abajo."
        />
      ) : (
        <div className="flex flex-col">
          {budgets.map((budget) => (
            <CategoryRow key={budget.category_id} budget={budget} category={categoryById.get(budget.category_id)} />
          ))}
        </div>
      )}

      <div className="mt-5 border-t border-hairline/60 pt-4">
        <BudgetForm categories={categories} month={month} onSaved={onSaved} />
      </div>
    </Panel>
  );
}

function CategoryRow({ budget, category }: { budget: FinanceBudget; category?: FinanceCategory }) {
  const pct = budget.limit_cents > 0 ? (budget.actual_cents / budget.limit_cents) * 100 : 0;
  const over = budget.limit_cents > 0 && pct > 100;
  const barColor = (category ? CATEGORY_BAR_CLASS[category.slug] : undefined) ?? FALLBACK_BAR_CLASS;

  return (
    <div className="grid grid-cols-[28px_1fr_auto] items-center gap-3 border-b border-hairline/60 py-2.5 last:border-b-0">
      <span className="text-lg" aria-hidden="true">
        {category?.emoji ?? '•'}
      </span>
      <div>
        <span className="text-sm font-medium text-ink">{budget.category_name}</span>
        <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-surface-2">
          <div
            className={cn('h-full rounded-full', over ? 'bg-status-critical' : barColor)}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
      </div>
      <div className="text-right text-[13px] font-medium">
        <span className={cn('block tabular-nums', over ? 'text-status-critical' : 'text-ink')}>
          {budget.limit_cents > 0 ? formatCents(budget.actual_cents, DEFAULT_CURRENCY) : 'N/D'}
        </span>
        <span className="block text-xs font-normal tabular-nums text-ink-muted">
          de {formatCents(budget.limit_cents, DEFAULT_CURRENCY)}
        </span>
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
  const [currency, setCurrency] = useState(DEFAULT_CURRENCY);
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
        currency,
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
          value={currency}
          onChange={(event) => setCurrency(event.target.value.toUpperCase())}
          maxLength={3}
          minLength={3}
          required
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm uppercase text-ink outline-none transition focus:border-cobalt/40"
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
