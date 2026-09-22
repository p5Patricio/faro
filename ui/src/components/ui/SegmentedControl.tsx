import type { ReactNode } from 'react';
import { cn } from '../../lib/cn.ts';

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  /** Optional trailing count / dot. */
  badge?: ReactNode;
}

interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Accessible name for the tablist. */
  label: string;
  /** Prefix for generated tab / panel ids, so a tabpanel can be linked. */
  idPrefix?: string;
  className?: string;
}

/**
 * Tab bar for the dashboard's evidence sections. Horizontally scrollable on
 * narrow viewports; arrow keys move between tabs (roving tabindex).
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  idPrefix,
  className,
}: SegmentedControlProps<T>) {
  const index = Math.max(0, options.findIndex((o) => o.value === value));

  return (
    <div
      role="tablist"
      aria-label={label}
      className={cn(
        'flex gap-1 overflow-x-auto rounded-lg border border-hairline/70 bg-inset p-1',
        className,
      )}
      onKeyDown={(event) => {
        if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
        event.preventDefault();
        const delta = event.key === 'ArrowRight' ? 1 : -1;
        const next = (index + delta + options.length) % options.length;
        onChange(options[next].value);
      }}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            id={idPrefix ? `${idPrefix}-tab-${option.value}` : undefined}
            aria-controls={idPrefix ? `${idPrefix}-panel-${option.value}` : undefined}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(option.value)}
            className={cn(
              'inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-cobalt/50',
              active
                ? 'bg-surface text-slate-100 shadow-sm ring-1 ring-hairline/60'
                : 'text-slate-400 hover:text-slate-200',
            )}
          >
            {option.label}
            {option.badge != null ? (
              <span
                className={cn(
                  'rounded px-1 text-xs tabular-nums',
                  active ? 'bg-hairline/50 text-slate-300' : 'text-slate-500',
                )}
              >
                {option.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
