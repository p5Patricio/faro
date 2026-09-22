import type { ReactNode } from 'react';
import { cn } from '../../lib/cn.ts';

interface PanelProps {
  children: ReactNode;
  /** Optional heading rendered in a consistent panel header row. */
  title?: ReactNode;
  /** Small icon shown before the title. */
  icon?: ReactNode;
  /** Right-aligned content in the header (badges, buttons, counts). */
  actions?: ReactNode;
  /** Tighter internal padding for dense side panels. */
  dense?: boolean;
  /** Replace the default surface treatment (used by toned alert panels). */
  tone?: string;
  className?: string;
  /** Applied to the content wrapper only, not the header. */
  bodyClassName?: string;
}

/**
 * The single card primitive for the dashboard. Every section that used to
 * inline `rounded-lg border border-hairline/70 bg-surface p-4` should use
 * this so spacing, borders and header rhythm stay consistent.
 */
export function Panel({
  children,
  title,
  icon,
  actions,
  dense = false,
  tone,
  className,
  bodyClassName,
}: PanelProps) {
  const pad = dense ? 'p-3' : 'p-4';
  return (
    <section
      className={cn(
        'rounded-lg border',
        tone ?? 'border-hairline/70 bg-surface',
        pad,
        className,
      )}
    >
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            {icon}
            {typeof title === 'string' ? (
              <h2 className="truncate text-sm font-medium text-slate-100">{title}</h2>
            ) : (
              title
            )}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
