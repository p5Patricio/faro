import { useState, type ReactNode } from 'react';
import { Check, Copy } from 'lucide-react';
import { cn } from '../../lib/cn.ts';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  /** One short line explaining why it is empty / what to do. */
  hint?: ReactNode;
  /** A shell command the operator can run to populate this panel. */
  command?: string;
  /** Any extra action (a button/link). Rendered under the hint. */
  action?: ReactNode;
  /** `error` swaps the copy for a failure tone + optional retry. */
  variant?: 'empty' | 'error';
  onRetry?: () => void;
  className?: string;
}

/**
 * The single empty/failure placeholder. Teaches instead of just saying
 * "Sin datos": shows the next concrete step, and for an operator tool that
 * usually means a command to run.
 */
export function EmptyState({
  icon,
  title,
  hint,
  command,
  action,
  variant = 'empty',
  onRetry,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center',
        variant === 'error' ? 'border-red-300/30 bg-red-300/[0.04]' : 'border-hairline/60',
        className,
      )}
    >
      {icon ? (
        <div className={cn('mb-1', variant === 'error' ? 'text-red-300' : 'text-slate-500')}>{icon}</div>
      ) : null}
      <p className={cn('text-sm font-medium', variant === 'error' ? 'text-red-200' : 'text-slate-300')}>
        {title}
      </p>
      {hint ? <p className="max-w-sm text-xs text-slate-500">{hint}</p> : null}
      {command ? <CommandChip command={command} /> : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 rounded-md border border-hairline/70 px-3 py-1 text-xs text-slate-200 transition hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-cobalt/50"
        >
          Reintentar
        </button>
      ) : null}
      {action}
    </div>
  );
}

function CommandChip({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      className="mt-1 inline-flex max-w-full items-center gap-2 rounded-md border border-hairline/70 bg-inset px-2.5 py-1.5 text-left font-mono text-xs text-slate-300 transition hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-cobalt/50"
      title="Copiar comando"
    >
      <span className="truncate">{command}</span>
      {copied ? (
        <Check aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-emerald-300" />
      ) : (
        <Copy aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-slate-500" />
      )}
      <span className="sr-only">{copied ? 'Copiado' : 'Copiar comando'}</span>
    </button>
  );
}
