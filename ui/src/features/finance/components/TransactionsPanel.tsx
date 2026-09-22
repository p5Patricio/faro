import { useMemo, useState } from 'react';
import { AlertTriangle, Pencil, Receipt, Trash2 } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { SkeletonTable } from '../../../components/ui/Skeleton.tsx';
import { Drawer } from '../../../components/ui/Drawer.tsx';
import { cn } from '../../../lib/cn.ts';
import { formatCents, formatShortDate } from '../lib/format.ts';
import { putTransaction } from '../hooks/useFinanceApi.ts';
import { TransactionForm } from './TransactionForm.tsx';
import type { FinanceAccount, FinanceCategory, FinanceTransaction } from '../types.ts';

/**
 * State-aware sticky header, per modern-web-guidance's `scroll-state`
 * container-query pattern: `container-type: scroll-state` on the sticky
 * `<thead>` wrapper lets `@container ... scroll-state(stuck: top)` swap
 * the header's background/shadow only while it is actually pinned. A
 * browser without support just keeps a plain `position: sticky` header
 * with no visual state change -- a graceful no-op, not a broken one.
 */
const TX_TABLE_STYLE = `
  .finance-tx-thead {
    position: sticky;
    inset-block-start: 0;
    container-type: scroll-state;
    container-name: finance-tx-head;
  }
  .finance-tx-thead th {
    transition: background-color 0.2s ease, box-shadow 0.2s ease;
  }
  @container finance-tx-head scroll-state(stuck: top) {
    .finance-tx-thead th {
      background: var(--color-surface-2);
      box-shadow: 0 4px 10px rgba(0, 0, 0, 0.35);
    }
  }
`;

interface TransactionsPanelProps {
  transactions: FinanceTransaction[];
  categories: FinanceCategory[];
  accounts: FinanceAccount[];
  loading?: boolean;
  error?: string | null;
  onChanged: () => void;
}

/** Recent transactions for the month, with edit and soft-delete affordances. */
export function TransactionsPanel({
  transactions,
  categories,
  accounts,
  loading,
  error,
  onChanged,
}: TransactionsPanelProps) {
  const [editing, setEditing] = useState<FinanceTransaction | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const categoryById = useMemo(() => new Map(categories.map((c) => [c.id, c])), [categories]);
  const accountById = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);

  const softDelete = async (transaction: FinanceTransaction) => {
    if (!window.confirm(`¿Eliminar el movimiento "${transaction.merchant || transaction.id}"?`)) return;
    setDeletingId(transaction.id);
    try {
      await putTransaction({
        client_id: transaction.client_id,
        account_id: transaction.account_id,
        category_id: transaction.category_id ?? undefined,
        kind: transaction.kind,
        amount_cents: transaction.amount_cents,
        currency: transaction.currency,
        occurred_at: transaction.occurred_at,
        merchant: transaction.merchant ?? undefined,
        notes: transaction.notes ?? undefined,
        source: 'ui',
        deleted_at: new Date().toISOString(),
      });
      onChanged();
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <Panel title="Movimientos del mes" icon={<Receipt aria-hidden="true" className="h-4 w-4 text-cobalt" />}>
      <style>{TX_TABLE_STYLE}</style>

      {error ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudieron cargar los movimientos"
        />
      ) : loading && transactions.length === 0 ? (
        <SkeletonTable rows={5} />
      ) : transactions.length === 0 ? (
        <EmptyState
          icon={<Receipt aria-hidden="true" className="h-6 w-6" />}
          title="Sin movimientos este mes"
          hint="Usá “+ Nueva transacción” para empezar a registrar tus finanzas."
        />
      ) : (
        <div className="max-h-[420px] overflow-auto rounded-xl border border-hairline [overflow-anchor:none]">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Movimientos del mes</caption>
            <thead className="finance-tx-thead">
              <tr className="border-b border-hairline bg-surface text-left text-[11px] uppercase tracking-wide text-ink-muted">
                <th scope="col" className="whitespace-nowrap px-3.5 py-2.5 font-semibold">
                  Fecha
                </th>
                <th scope="col" className="whitespace-nowrap px-3.5 py-2.5 font-semibold">
                  Categoría
                </th>
                <th scope="col" className="hidden whitespace-nowrap px-3.5 py-2.5 font-semibold md:table-cell">
                  Cuenta
                </th>
                <th scope="col" className="hidden whitespace-nowrap px-3.5 py-2.5 font-semibold md:table-cell">
                  Comercio
                </th>
                <th scope="col" className="whitespace-nowrap px-3.5 py-2.5 text-right font-semibold">
                  Monto
                </th>
                <th scope="col" className="whitespace-nowrap px-3.5 py-2.5 text-right font-semibold">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline/60">
              {transactions.map((row) => {
                const category = row.category_id ? categoryById.get(row.category_id) : undefined;
                return (
                  <tr key={row.id} className="transition-colors hover:bg-white/[0.03]">
                    <td className="whitespace-nowrap px-3.5 py-3 text-ink-secondary">{formatShortDate(row.occurred_at)}</td>
                    <td className="px-3.5 py-3">
                      <span className="flex items-center gap-1.5 text-ink">
                        {category?.emoji ? <span aria-hidden="true">{category.emoji}</span> : null}
                        {category?.name ?? 'Sin categoría'}
                      </span>
                    </td>
                    <td className="hidden px-3.5 py-3 text-ink-secondary md:table-cell">
                      {accountById.get(row.account_id)?.name ?? 'N/D'}
                    </td>
                    <td className="hidden px-3.5 py-3 text-ink-secondary md:table-cell">{row.merchant || '—'}</td>
                    <td
                      className={cn(
                        'whitespace-nowrap px-3.5 py-3 text-right font-medium tabular-nums',
                        row.kind === 'income'
                          ? 'text-status-good'
                          : row.kind === 'expense'
                            ? 'text-status-critical'
                            : 'text-ink',
                      )}
                    >
                      {formatCents(row.amount_cents, row.currency)}
                    </td>
                    <td className="px-3.5 py-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => setEditing(row)}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-muted transition hover:bg-white/5 hover:text-ink-secondary"
                          aria-label={`Editar movimiento ${row.merchant ?? row.id}`}
                        >
                          <Pencil aria-hidden="true" className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => softDelete(row)}
                          disabled={deletingId === row.id}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-muted transition hover:bg-status-critical/10 hover:text-status-critical disabled:cursor-not-allowed disabled:opacity-50"
                          aria-label={`Eliminar movimiento ${row.merchant ?? row.id}`}
                        >
                          <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Drawer open={editing !== null} onClose={() => setEditing(null)} title="Editar transacción">
        {editing ? (
          <TransactionForm
            categories={categories}
            accounts={accounts}
            initial={editing}
            onSaved={() => {
              setEditing(null);
              onChanged();
            }}
            onCancel={() => setEditing(null)}
          />
        ) : null}
      </Drawer>
    </Panel>
  );
}
