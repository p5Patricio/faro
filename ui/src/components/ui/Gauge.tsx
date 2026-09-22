import { cn } from '../../lib/cn.ts';

interface GaugeProps {
  /** 0..1. */
  value: number | null | undefined;
  /** 0..1. Draws a threshold tick — e.g. the min confidence to trade. */
  threshold?: number | null;
  label?: string;
  /** Tone of the filled portion. */
  tone?: 'beam' | 'emerald' | 'red' | 'slate';
  className?: string;
}

const TONE_FILL: Record<NonNullable<GaugeProps['tone']>, string> = {
  beam: 'bg-beam',
  emerald: 'bg-emerald-300',
  red: 'bg-red-300',
  slate: 'bg-slate-400',
};

/**
 * A horizontal confidence meter. A linear track (not a dial) so the reader
 * can see at a glance how the value sits relative to the trade threshold.
 */
export function Gauge({ value, threshold, label, tone = 'beam', className }: GaugeProps) {
  const pct = value == null || Number.isNaN(value) ? null : clamp01(value) * 100;
  const thresholdPct =
    threshold == null || Number.isNaN(threshold) ? null : clamp01(threshold) * 100;
  const belowThreshold = pct != null && thresholdPct != null && pct < thresholdPct;

  return (
    <div className={className}>
      <div className="mb-1 flex items-baseline justify-between">
        {label ? <span className="text-xs text-slate-500">{label}</span> : <span />}
        <span
          className={cn(
            'text-sm font-semibold tabular-nums',
            belowThreshold ? 'text-slate-300' : 'text-slate-100',
          )}
        >
          {pct == null ? 'N/D' : `${pct.toFixed(0)}%`}
        </span>
      </div>
      <div
        className="relative h-2 overflow-hidden rounded-full bg-slate-100/[0.08]"
        role="meter"
        aria-valuenow={pct ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? 'Confianza'}
      >
        {pct != null ? (
          <div
            className={cn('h-full rounded-full transition-[width]', TONE_FILL[tone])}
            style={{ width: `${pct}%` }}
          />
        ) : null}
        {thresholdPct != null ? (
          <span
            className="absolute top-1/2 h-3.5 w-0.5 -translate-y-1/2 rounded-full bg-slate-100/70"
            style={{ left: `calc(${thresholdPct}% - 1px)` }}
            title={`Umbral ${thresholdPct.toFixed(0)}%`}
          />
        ) : null}
      </div>
      {thresholdPct != null ? (
        <p className="mt-1 text-xs text-slate-500">
          Umbral para operar: {thresholdPct.toFixed(0)}%
          {belowThreshold ? ' · por debajo' : ''}
        </p>
      ) : null}
    </div>
  );
}

function clamp01(n: number): number {
  return Math.max(0, Math.min(1, n));
}
