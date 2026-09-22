import { cn } from '../../lib/cn.ts';

const ORDER = ['BUY', 'HOLD', 'SELL'] as const;
const SEGMENT_TONE: Record<string, string> = {
  BUY: 'bg-emerald-300',
  HOLD: 'bg-slate-500',
  SELL: 'bg-red-300',
};

interface ProbabilityBarProps {
  probabilities?: Record<string, number>;
  className?: string;
}

/** A single stacked bar of the action distribution, replacing three bars. */
export function ProbabilityBar({ probabilities, className }: ProbabilityBarProps) {
  const raw = probabilities ?? {};
  const total = ORDER.reduce((sum, key) => sum + (raw[key] ?? 0), 0) || 1;
  const parts = ORDER.map((key) => ({ key, pct: ((raw[key] ?? 0) / total) * 100 }));

  return (
    <div className={className}>
      <div
        className="flex h-2.5 overflow-hidden rounded-full bg-slate-100/[0.06]"
        role="img"
        aria-label={parts.map((p) => `${p.key} ${p.pct.toFixed(0)}%`).join(', ')}
      >
        {parts.map((part) =>
          part.pct > 0 ? (
            <div
              key={part.key}
              className={cn('h-full transition-[width]', SEGMENT_TONE[part.key])}
              style={{ width: `${part.pct}%` }}
            />
          ) : null,
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {parts.map((part) => (
          <span key={part.key} className="inline-flex items-center gap-1.5 text-xs text-slate-400">
            <span className={cn('h-2 w-2 rounded-full', SEGMENT_TONE[part.key])} />
            {part.key}
            <span className="font-medium tabular-nums text-slate-200">{part.pct.toFixed(0)}%</span>
          </span>
        ))}
      </div>
    </div>
  );
}
