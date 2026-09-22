import { cn } from '../../lib/cn.ts';

type Signal = 'BUY' | 'SELL' | 'HOLD' | string;

const DOT_TONE: Record<string, string> = {
  BUY: 'bg-emerald-300',
  SELL: 'bg-red-300',
  HOLD: 'bg-slate-500',
};

interface SignalSparklineProps {
  /** Oldest → newest. Only the last `max` are shown. */
  signals: Signal[];
  max?: number;
  className?: string;
}

/**
 * Categorical sparkline for signal history: one dot per recent decision,
 * oldest left, newest emphasised. Shows regime / stability at a glance.
 */
export function SignalSparkline({ signals, max = 12, className }: SignalSparklineProps) {
  if (signals.length === 0) return null;
  const shown = signals.slice(-max);

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span className="text-xs uppercase tracking-wide text-slate-500">Recientes</span>
      <div className="flex items-center gap-1" aria-label="Historial de señales">
        {shown.map((signal, i) => {
          const newest = i === shown.length - 1;
          return (
            <span
              key={i}
              title={signal}
              className={cn(
                'inline-block rounded-full',
                DOT_TONE[signal] ?? 'bg-slate-600',
                newest ? 'h-2.5 w-2.5 ring-2 ring-slate-100/20' : 'h-2 w-2',
              )}
            />
          );
        })}
      </div>
    </div>
  );
}
