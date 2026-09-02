import { cn } from '../../lib/cn.ts';

/**
 * A single shimmering placeholder block. Respects `prefers-reduced-motion`
 * via Tailwind's `motion-reduce` variant (falls back to a static tint).
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'animate-pulse rounded-md bg-slate-100/[0.06] motion-reduce:animate-none',
        className,
      )}
    />
  );
}

/** A row of evenly sized skeleton lines, for text-heavy panels. */
export function SkeletonLines({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={cn('h-4', i === rows - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}

/** Skeleton shaped like a metrics grid (used inside panels while loading). */
export function SkeletonMetrics({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div className={cn('grid grid-cols-2 gap-3 md:grid-cols-4', className)}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-hairline/70 bg-inset p-3">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="mt-2 h-5 w-12" />
        </div>
      ))}
    </div>
  );
}

/** Skeleton shaped like a data table. */
export function SkeletonTable({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('overflow-hidden rounded-lg border border-hairline/70', className)}>
      <Skeleton className="h-8 w-full rounded-none" />
      <div className="divide-y divide-hairline/60">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="px-3 py-3">
            <Skeleton className="h-4 w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
