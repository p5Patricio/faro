import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { cn } from '../../lib/cn.ts';

interface PopoverProps {
  /** Render prop for the trigger; receives props to spread onto a button. */
  trigger: (props: {
    onClick: () => void;
    'aria-expanded': boolean;
    'aria-controls': string;
    'aria-haspopup': 'dialog';
  }) => ReactNode;
  children: ReactNode;
  /** Align the panel to the trigger's left or right edge. */
  align?: 'left' | 'right';
  className?: string;
  panelClassName?: string;
}

/** Anchored dropdown panel. Closes on outside pointer-down and Esc. */
export function Popover({ trigger, children, align = 'right', className, panelClassName }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={wrapRef} className={cn('relative', className)}>
      {trigger({
        onClick: () => setOpen((v) => !v),
        'aria-expanded': open,
        'aria-controls': panelId,
        'aria-haspopup': 'dialog',
      })}
      {open ? (
        <div
          id={panelId}
          role="dialog"
          className={cn(
            'absolute top-full z-40 mt-2 w-80 rounded-lg border border-hairline/70 bg-surface p-1 shadow-2xl',
            align === 'right' ? 'right-0' : 'left-0',
            panelClassName,
          )}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}
