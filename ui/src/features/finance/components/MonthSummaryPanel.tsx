import type { ReactNode } from 'react';
import { AlertTriangle, Info, Minus, TrendingDown, TrendingUp, Wallet } from 'lucide-react';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { SkeletonLines, SkeletonMetrics } from '../../../components/ui/Skeleton.tsx';
import { cn } from '../../../lib/cn.ts';
import { BASE_CURRENCY, formatCents, formatSignedCents } from '../lib/format.ts';
import { BudgetFlowDiagram } from './BudgetFlowDiagram.tsx';
import type { MonthlySummary } from '../types.ts';

interface MonthSummaryPanelProps {
  summary: MonthlySummary | null;
  loading?: boolean;
  error?: string | null;
}

/**
 * Income / spending / saved / not-spent / savings-rate stat tiles plus the
 * 50/30/20 flow diagram. Every figure here is the selected month's own data
 * (nothing is estimated from trailing history), and the whole panel gives way
 * to an honest empty state when the API says the month has no usable data.
 */
export function MonthSummaryPanel({ summary, loading, error }: MonthSummaryPanelProps) {
  if (error) {
    return (
      <EmptyState
        variant="error"
        icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
        title="No se pudo cargar el resumen"
      />
    );
  }

  if (loading && !summary) {
    return (
      <div className="space-y-4">
        <SkeletonMetrics count={4} />
        <SkeletonLines rows={3} />
      </div>
    );
  }

  if (!summary || !summary.data_sufficient) {
    const unconvertedOnly = summary?.unconverted_transactions ?? 0;
    if (unconvertedOnly > 0) {
      return (
        <EmptyState
          icon={<Wallet aria-hidden="true" className="h-6 w-6" />}
          title="Este mes no tiene movimientos que se puedan sumar"
          hint={unconvertedOnlyHint(unconvertedOnly)}
        />
      );
    }
    return (
      <EmptyState
        icon={<Wallet aria-hidden="true" className="h-6 w-6" />}
        title="Todavía no hay transacciones este mes"
        hint="Registra tus movimientos con el botón “+ Nueva transacción” para ver tu resumen aquí."
      />
    );
  }

  const unconverted = summary.unconverted_transactions ?? 0;
  const uncategorizedCents = summary.buckets.sin_categoria.actual_cents;
  const notSpent = notSpentTone(summary.net_cents, summary.income_cents);

  return (
    <div className="space-y-5">
      {unconverted > 0 ? (
        <p
          role="status"
          className="flex items-start gap-2 rounded-lg border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-sm text-ink-secondary"
        >
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-status-warning" />
          <span>{unconvertedWarning(unconverted)}</span>
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-hairline bg-hairline md:grid-cols-5">
        <StatTile label="Ingresos" value={formatCents(summary.income_cents, BASE_CURRENCY)} />
        <StatTile
          label="Gastos"
          value={formatCents(summary.spending_cents, BASE_CURRENCY)}
          hint="Sin contar lo ahorrado"
        />
        <StatTile
          label="Ahorrado"
          value={formatCents(summary.saved_cents, BASE_CURRENCY)}
          hint="Ahorro e inversión"
        />
        {/* The sign and the icon carry the direction; the colour only reinforces it. */}
        <StatTile
          label="Sin gastar"
          value={formatSignedCents(summary.net_cents, BASE_CURRENCY)}
          hint={notSpent.hint}
          icon={notSpent.icon}
          valueClassName={notSpent.className}
        />
        <StatTile
          label="Tasa de ahorro"
          value={`${summary.savings_rate_pct.toFixed(0)}%`}
          hint="Ahorrado entre ingresos"
          className="col-span-2 md:col-span-1"
        />
      </div>

      {uncategorizedCents > 0 ? (
        <p className="flex items-start gap-2 text-xs text-ink-muted">
          <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            {formatCents(uncategorizedCents, BASE_CURRENCY)} de tus gastos no tienen categoría: cuentan como gasto,
            pero no entran en ninguna barra del reparto 50/30/20.
          </span>
        </p>
      ) : null}

      <BudgetFlowDiagram
        buckets={summary.buckets}
        incomeCents={summary.income_cents}
        dataSufficient={summary.data_sufficient}
      />
    </div>
  );
}

function unconvertedOnlyHint(count: number): string {
  if (count === 1) {
    return `Este mes solo hay 1 movimiento en otra moneda y no tiene tipo de cambio a ${BASE_CURRENCY}, así que todavía no hay cifras que mostrar. Edítalo y agrega el tipo de cambio.`;
  }
  return `Este mes solo hay ${count} movimientos en otra moneda y no tienen tipo de cambio a ${BASE_CURRENCY}, así que todavía no hay cifras que mostrar. Edítalos y agrega el tipo de cambio.`;
}

function unconvertedWarning(count: number): string {
  if (count === 1) {
    return `1 movimiento en otra moneda no está incluido en estas cifras porque no tiene tipo de cambio a ${BASE_CURRENCY}. Edítalo y agrega el tipo de cambio.`;
  }
  return `${count} movimientos en otra moneda no están incluidos en estas cifras porque no tienen tipo de cambio a ${BASE_CURRENCY}. Edítalos y agrega el tipo de cambio.`;
}

/**
 * The words under "Sin gastar". With no income logged, "spent more than you
 * earned" (or "spent everything you earned") would be untrue -- nothing was
 * declared as earned -- so those months say that no income is registered.
 */
function notSpentTone(netCents: number, incomeCents: number): { hint: string; icon: ReactNode; className: string } {
  if (netCents > 0) {
    return {
      hint: 'Ingresos menos gastos',
      icon: <TrendingUp aria-hidden="true" className="h-4 w-4 text-status-good" />,
      className: 'text-status-good',
    };
  }
  if (netCents < 0) {
    return {
      hint: incomeCents === 0 ? 'No hay ingresos registrados este mes' : 'Gastaste más de lo que ingresó',
      icon: <TrendingDown aria-hidden="true" className="h-4 w-4 text-status-critical" />,
      className: 'text-status-critical',
    };
  }
  return {
    hint: incomeCents === 0 ? 'Sin ingresos ni gastos este mes' : 'Gastaste todo lo que ingresó',
    icon: <Minus aria-hidden="true" className="h-4 w-4 text-ink-muted" />,
    className: '',
  };
}

function StatTile({
  label,
  value,
  hint,
  icon,
  valueClassName,
  className,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: ReactNode;
  valueClassName?: string;
  className?: string;
}) {
  return (
    <div className={cn('bg-surface px-4 py-4', className)}>
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
        {label}
        {icon}
      </p>
      <p
        className={cn(
          'font-display mt-2 text-[26px] leading-none tabular-nums text-ink [text-box:trim-both_cap_alphabetic]',
          valueClassName,
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-2 text-[11px] text-ink-muted">{hint}</p> : null}
    </div>
  );
}
