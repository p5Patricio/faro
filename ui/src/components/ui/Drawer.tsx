import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from '../../lib/cn.ts';

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  /** Restore focus here on close. */
  returnFocusRef?: React.RefObject<HTMLElement | null>;
  className?: string;
}

/** Right-side slide-over. Backdrop click and Esc close it. */
export function Drawer({ open, onClose, title, children, returnFocusRef, className }: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const returnTarget = returnFocusRef?.current ?? previouslyFocused;
    panelRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      returnTarget?.focus?.();
    };
  }, [open, onClose, returnFocusRef]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Cerrar"
        onClick={onClose}
        className="absolute inset-0 bg-canvas/70 backdrop-blur-sm"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={cn(
          'relative flex h-full w-full max-w-md flex-col border-l border-hairline/70 bg-surface shadow-2xl outline-none',
          className,
        )}
      >
        <div className="flex items-center justify-between border-b border-hairline/60 px-4 py-3">
          {typeof title === 'string' ? (
            <h2 className="text-sm font-medium text-slate-100">{title}</h2>
          ) : (
            title
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-500 transition hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-cobalt/50"
            aria-label="Cerrar"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
