import { AlertTriangle, Wallet } from 'lucide-react';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { SkeletonLines, SkeletonMetrics } from '../../../components/ui/Skeleton.tsx';
import { cn } from '../../../lib/cn.ts';
import { DEFAULT_CURRENCY, formatCents } from '../lib/format.ts';
import { BudgetFlowDiagram } from './BudgetFlowDiagram.tsx';
import type { MonthlySummary } from '../types.ts';

interface MonthSummaryPanelProps {
  summary: MonthlySummary | null;
  loading?: boolean;
  error?: string | null;
}

/** Income/expense/net/savings-rate stat tiles plus the 50/30/20 flow diagram. */
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
    return (
      <EmptyState
        icon={<Wallet aria-hidden="true" className="h-6 w-6" />}
        title="Todavía no hay transacciones este mes"
        hint="Registrá tus movimientos con el botón “+ Nueva transacción” para ver tu resumen aquí."
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-hairline bg-hairline sm:grid-cols-4">
        <StatTile label="Ingresos" value={formatCents(summary.income_cents, DEFAULT_CURRENCY)} />
        <StatTile label="Gastos" value={formatCents(summary.expense_cents, DEFAULT_CURRENCY)} />
        <StatTile
          label="Neto"
          value={formatCents(summary.net_cents, DEFAULT_CURRENCY)}
          valueClassName={summary.net_cents < 0 ? 'text-status-critical' : 'text-status-good'}
        />
        <StatTile label="Tasa de ahorro" value={`${summary.savings_rate_pct.toFixed(0)}%`} />
      </div>

      <BudgetFlowDiagram
        buckets={summary.buckets}
        incomeCents={summary.income_cents}
        dataSufficient={summary.data_sufficient}
      />
    </div>
  );
}

function StatTile({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="bg-surface px-4 py-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">{label}</p>
      <p
        className={cn(
          'font-display mt-2 text-[26px] leading-none tabular-nums text-ink [text-box:trim-both_cap_alphabetic]',
          valueClassName,
        )}
      >
        {value}
      </p>
    </div>
  );
}
