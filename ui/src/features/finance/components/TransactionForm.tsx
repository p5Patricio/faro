import { useId, useMemo, useState, type FormEvent } from 'react';
import { putTransaction } from '../hooks/useFinanceApi.ts';
import { DEFAULT_CURRENCY } from '../lib/format.ts';
import type { FinanceAccount, FinanceCategory, FinanceCategoryKind, FinanceTransaction, TransactionPayload } from '../types.ts';

const KIND_LABELS: Record<FinanceCategoryKind, string> = {
  expense: 'Gasto',
  income: 'Ingreso',
  transfer: 'Transferencia',
};

/**
 * Shared field chrome: label above input, 48px minimum tap target, and
 * `:user-invalid`/`:user-valid` so error styling only ever appears after
 * the visitor has actually interacted with the field (blur or submit),
 * never while they are still typing into it for the first time.
 */
const FIELD_CLASS =
  'mt-1.5 h-12 w-full rounded-lg border border-hairline bg-canvas px-3 text-sm text-ink outline-none transition focus:border-cobalt/50 [&:user-invalid]:border-status-critical [&:user-invalid]:focus:border-status-critical';
const LABEL_CLASS = 'block text-xs font-medium text-ink-muted';

interface TransactionFormProps {
  categories: FinanceCategory[];
  accounts: FinanceAccount[];
  /** Present when editing an existing transaction; omit to create a new one. */
  initial?: FinanceTransaction;
  onSaved: (transaction: FinanceTransaction) => void;
  onCancel?: () => void;
}

/**
 * Manual transaction entry/edit form. `kind` is never a free choice — it is
 * always derived from the selected category's own `kind`, exactly like
 * `ops/finance_bot.py`'s server-side matcher does (`kind=category["kind"]`).
 */
export function TransactionForm({ categories, accounts, initial, onSaved, onCancel }: TransactionFormProps) {
  const idPrefix = useId();
  const [clientId] = useState(() => initial?.client_id ?? crypto.randomUUID());
  const [categoryId, setCategoryId] = useState(initial?.category_id ?? '');
  const [accountId, setAccountId] = useState(initial?.account_id ?? '');
  const [amount, setAmount] = useState(initial ? String(initial.amount_cents / 100) : '');
  const [occurredAt, setOccurredAt] = useState(() =>
    toDatetimeLocalValue(initial?.occurred_at ?? new Date().toISOString()),
  );
  const [merchant, setMerchant] = useState(initial?.merchant ?? '');
  const [notes, setNotes] = useState(initial?.notes ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedCategory = useMemo(() => categories.find((c) => c.id === categoryId), [categories, categoryId]);
  const selectedAccount = useMemo(() => accounts.find((a) => a.id === accountId), [accounts, accountId]);
  const currency = selectedAccount?.currency ?? initial?.currency ?? DEFAULT_CURRENCY;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedCategory || !accountId || !amount) {
      setError('Completá categoría, cuenta y monto.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload: TransactionPayload = {
        client_id: clientId,
        account_id: accountId,
        category_id: selectedCategory.id,
        kind: selectedCategory.kind,
        amount_cents: Math.round(Number(amount) * 100),
        currency,
        occurred_at: new Date(occurredAt).toISOString(),
        merchant: merchant || undefined,
        notes: notes || undefined,
        source: 'ui',
      };
      const saved = await putTransaction(payload);
      onSaved(saved);
    } catch {
      setError('No se pudo guardar la transacción.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor={`${idPrefix}-category`} className={LABEL_CLASS}>
          Categoría
        </label>
        <select
          id={`${idPrefix}-category`}
          value={categoryId}
          onChange={(event) => setCategoryId(event.target.value)}
          required
          className={FIELD_CLASS}
        >
          <option value="" disabled>
            Elegí una categoría
          </option>
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.emoji ? `${category.emoji} ` : ''}
              {category.name}
            </option>
          ))}
        </select>
        {selectedCategory ? (
          <p className="mt-1.5 text-xs text-ink-muted">
            Tipo: <span className="font-medium text-ink-secondary">{KIND_LABELS[selectedCategory.kind]}</span> (según
            la categoría elegida)
          </p>
        ) : null}
      </div>

      <div>
        <label htmlFor={`${idPrefix}-account`} className={LABEL_CLASS}>
          Cuenta
        </label>
        <select
          id={`${idPrefix}-account`}
          value={accountId}
          onChange={(event) => setAccountId(event.target.value)}
          required
          className={FIELD_CLASS}
        >
          <option value="" disabled>
            Elegí una cuenta
          </option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.name} ({account.currency})
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor={`${idPrefix}-amount`} className={LABEL_CLASS}>
          Monto ({currency})
        </label>
        <input
          id={`${idPrefix}-amount`}
          type="number"
          min="0"
          step="0.01"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          required
          className={`${FIELD_CLASS} text-right`}
        />
      </div>

      <div>
        <label htmlFor={`${idPrefix}-occurred-at`} className={LABEL_CLASS}>
          Fecha y hora
        </label>
        <input
          id={`${idPrefix}-occurred-at`}
          type="datetime-local"
          value={occurredAt}
          onChange={(event) => setOccurredAt(event.target.value)}
          required
          className={FIELD_CLASS}
        />
      </div>

      <div>
        <label htmlFor={`${idPrefix}-merchant`} className={LABEL_CLASS}>
          Comercio (opcional)
        </label>
        <input
          id={`${idPrefix}-merchant`}
          type="text"
          value={merchant}
          onChange={(event) => setMerchant(event.target.value)}
          className={FIELD_CLASS}
        />
      </div>

      <div>
        <label htmlFor={`${idPrefix}-notes`} className={LABEL_CLASS}>
          Notas (opcional)
        </label>
        <textarea
          id={`${idPrefix}-notes`}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          rows={2}
          className="mt-1.5 min-h-12 w-full rounded-lg border border-hairline bg-canvas px-3 py-2.5 text-sm text-ink outline-none transition focus:border-cobalt/50"
        />
      </div>

      {error ? <p className="text-sm text-status-critical">{error}</p> : null}

      <div className="flex items-center gap-2 pt-1">
        <button
          type="submit"
          disabled={saving}
          className="inline-flex h-12 flex-1 items-center justify-center rounded-lg border border-cobalt/30 bg-cobalt/10 px-3 text-sm font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? 'Guardando' : initial ? 'Guardar cambios' : 'Agregar transacción'}
        </button>
        {onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex h-12 items-center justify-center rounded-lg border border-hairline px-4 text-sm text-ink-secondary transition hover:bg-white/5"
          >
            Cancelar
          </button>
        ) : null}
      </div>
    </form>
  );
}

function toDatetimeLocalValue(iso: string): string {
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
