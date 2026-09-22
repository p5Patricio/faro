import { useId, useState, type ReactNode } from 'react';
import { HelpCircle } from 'lucide-react';
import { cn } from '../../lib/cn.ts';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * Hover/focus tooltip. Dismissable with Escape (WCAG 1.4.13). The trigger
 * element is whatever `children` renders; it must be focusable on its own.
 */
export function Tooltip({ content, children, className }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <span
      className={cn('relative inline-flex', className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocusCapture={() => setOpen(true)}
      onBlurCapture={() => setOpen(false)}
      onKeyDown={(event) => {
        if (event.key === 'Escape') setOpen(false);
      }}
    >
      <span aria-describedby={open ? id : undefined}>{children}</span>
      {open ? (
        <span
          role="tooltip"
          id={id}
          className="absolute bottom-full left-1/2 z-50 mb-1.5 w-max max-w-[16rem] -translate-x-1/2 rounded-md border border-hairline/70 bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-slate-200 shadow-xl"
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}

/**
 * A label paired with a small "?" affordance that explains a non-obvious
 * term. Use in place of a bare label for jargon (Base, Profit factor, …).
 */
export function InfoLabel({
  label,
  hint,
  className,
}: {
  label: ReactNode;
  hint: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      {label}
      <Tooltip content={hint}>
        <button
          type="button"
          className="rounded text-slate-500 transition hover:text-slate-300 focus:outline-none focus:ring-2 focus:ring-cobalt/50"
          aria-label={typeof label === 'string' ? `Qué es ${label}` : 'Más información'}
        >
          <HelpCircle aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      </Tooltip>
    </span>
  );
}
