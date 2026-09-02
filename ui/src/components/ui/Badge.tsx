import type { ReactNode } from 'react';
import { cn } from '../../lib/cn.ts';

type BadgeTone = 'neutral' | 'ok' | 'warning' | 'critical' | 'info' | 'beam';

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-hairline/40 text-slate-300',
  ok: 'bg-emerald-300/15 text-emerald-100',
  warning: 'bg-amber-300/15 text-amber-100',
  critical: 'bg-red-300/15 text-red-100',
  info: 'bg-cobalt/15 text-cobalt',
  beam: 'bg-beam/15 text-beam',
};

interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
}

/** Small uppercase status pill. Minimum readable size is 12px (`text-xs`). */
export function Badge({ children, tone = 'neutral', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium uppercase tracking-wide',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
