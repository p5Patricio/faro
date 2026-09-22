import type { ReactNode } from 'react';
import { cn } from '../../lib/cn.ts';

type MetricSize = 'inline' | 'box' | 'small';

interface MetricProps {
  label: ReactNode;
  value: ReactNode;
  /** `inline` = label over value, no chrome. `box` = bordered card, larger value.
   *  `small` = bordered card, compact value. */
  size?: MetricSize;
  icon?: ReactNode;
  /** Tone applied to the value text (e.g. positive/negative colouring). */
  valueClassName?: string;
  className?: string;
}

/**
 * Unifies the old MetricInline / MetricBox / SmallMetric trio. All numeric
 * values render with `tabular-nums` so columns of figures line up.
 */
export function Metric({ label, value, size = 'inline', icon, valueClassName, className }: MetricProps) {
  if (size === 'inline') {
    return (
      <div className={className}>
        <p className="text-sm text-slate-400">{label}</p>
        <p className={cn('text-lg font-medium tabular-nums text-slate-100', valueClassName)}>{value}</p>
      </div>
    );
  }

  const valueSize = size === 'box' ? 'text-lg' : 'mt-1 text-sm';
  return (
    <div className={cn('rounded-lg border border-hairline/70 bg-inset p-3', className)}>
      {icon ? <div className="mb-2 text-slate-400">{icon}</div> : null}
      <p className="text-xs text-slate-500">{label}</p>
      <p className={cn('font-medium tabular-nums text-slate-100', valueSize, valueClassName)}>{value}</p>
    </div>
  );
}
