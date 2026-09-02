import type { ReactNode } from 'react';
import { cn } from '../../lib/cn.ts';

export interface Column<Row> {
  key: string;
  header: ReactNode;
  render: (row: Row) => ReactNode;
  /** Numeric columns right-align and use tabular figures. */
  numeric?: boolean;
  /** `secondary` columns are hidden below the `md` breakpoint. */
  priority?: 'primary' | 'secondary';
  /** Extra classes for the cell (not the header). */
  cellClassName?: string;
}

interface DataTableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  getRowKey: (row: Row, index: number) => string;
  ariaLabel: string;
  className?: string;
}

/**
 * The single table primitive. A real <table> (better semantics than the old
 * grid-of-divs), horizontally scrollable, with `secondary` columns dropping
 * out below md. All numeric cells share `tabular-nums` so figures line up.
 */
export function DataTable<Row>({ columns, rows, getRowKey, ariaLabel, className }: DataTableProps<Row>) {
  return (
    <div className={cn('overflow-x-auto rounded-lg border border-hairline/70', className)}>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{ariaLabel}</caption>
        <thead>
          <tr className="border-b border-hairline/60 bg-inset text-left text-xs uppercase tracking-wide text-slate-500">
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cn(
                  'whitespace-nowrap px-3 py-2 font-medium',
                  col.numeric && 'text-right',
                  col.priority === 'secondary' && 'hidden md:table-cell',
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-hairline/60">
          {rows.map((row, index) => (
            <tr key={getRowKey(row, index)} className="transition-colors hover:bg-white/[0.03]">
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    'px-3 py-3 align-middle text-slate-300',
                    col.numeric && 'text-right tabular-nums',
                    col.priority === 'secondary' && 'hidden md:table-cell',
                    col.cellClassName,
                  )}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
