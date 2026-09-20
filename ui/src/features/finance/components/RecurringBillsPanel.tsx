import { useMemo, useState, type FormEvent } from 'react';
import { AlertTriangle, CheckCircle2, Repeat } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { SkeletonTable } from '../../../components/ui/Skeleton.tsx';
import { cn } from '../../../lib/cn.ts';
import { DEFAULT_CURRENCY, formatCents } from '../lib/format.ts';
import { putRecurringBill, putRecurringBillPayment } from '../hooks/useFinanceApi.ts';
import type { BillFrequency, FinanceAccount, FinanceCategory, RecurringBill } from '../types.ts';

const FREQUENCY_LABELS: Record<BillFrequency, string> = {
  weekly: 'Semanal',
  biweekly: 'Quincenal',
  monthly: 'Mensual',
  bimonthly: 'Bimestral',
  quarterly: 'Trimestral',
  semiannual: 'Semestral',
  annual: 'Anual',
};

interface RecurringBillsPanelProps {
  bills: RecurringBill[];
  categories: FinanceCategory[];
  accounts: FinanceAccount[];
  loading?: boolean;
  error?: string | null;
  onChanged: () => void;
}

/**
 * Recurring bills as understated rows -- plain gray "vence en N días" text,
 * switching to `--color-status-warning` only inside the bill's own
 * `reminder_days_before` window. Never a traffic-light status pill.
 */
export function RecurringBillsPanel({
  bills,
  categories,
  accounts,
  loading,
  error,
  onChanged,
}: RecurringBillsPanelProps) {
  const [payingId, setPayingId] = useState<string | null>(null);
  const categoryById = useMemo(() => new Map(categories.map((category) => [category.id, category])), [categories]);

  const markPaid = async (bill: RecurringBill) => {
    if (!bill.next_due_date) return;
    setPayingId(bill.id);
    try {
      await putRecurringBillPayment({ bill_id: bill.id, due_date: bill.next_due_date, status: 'paid' });
      onChanged();
    } finally {
      setPayingId(null);
    }
  };

  return (
    <Panel title="Pagos recurrentes" icon={<Repeat aria-hidden="true" className="h-4 w-4 text-cobalt" />}>
      {error ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudieron cargar los pagos recurrentes"
        />
      ) : loading && bills.length === 0 ? (
        <SkeletonTable rows={4} />
      ) : bills.length === 0 ? (
        <EmptyState
          icon={<Repeat aria-hidden="true" className="h-6 w-6" />}
          title="Sin pagos recurrentes registrados"
          hint="Agregá tus suscripciones y pagos fijos con el formulario de abajo."
        />
      ) : (
        <div className="flex flex-col">
          {bills.map((bill) => (
            <BillRow
              key={bill.id}
              bill={bill}
              category={bill.category_id ? categoryById.get(bill.category_id) : undefined}
              paying={payingId === bill.id}
              onMarkPaid={() => markPaid(bill)}
            />
          ))}
        </div>
      )}

      <div className="mt-5 border-t border-hairline/60 pt-4">
        <RecurringBillForm categories={categories} accounts={accounts} onSaved={onChanged} />
      </div>
    </Panel>
  );
}

function BillRow({
  bill,
  category,
  paying,
  onMarkPaid,
}: {
  bill: RecurringBill;
  category?: FinanceCategory;
  paying: boolean;
  onMarkPaid: () => void;
}) {
  const due = describeDue(bill);
  const canMarkPaid = bill.next_status === 'pending' && Boolean(bill.next_due_date);

  return (
    <div className="flex items-center gap-3 border-b border-hairline/60 py-2.5 last:border-b-0">
      <span
        className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[9px] bg-surface-2 text-[15px]"
        aria-hidden="true"
      >
        {category?.emoji ?? '🔁'}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13.5px] font-medium text-ink">{bill.name}</p>
        <p className={cn('text-xs', due.warn ? 'text-status-warning' : 'text-ink-muted')}>{due.text}</p>
      </div>
      <span className="shrink-0 text-sm font-semibold tabular-nums text-ink">
        {formatCents(bill.amount_cents, bill.currency)}
      </span>
      {canMarkPaid ? (
        <button
          type="button"
          onClick={onMarkPaid}
          disabled={paying}
          aria-label={`Marcar ${bill.name} como pagado`}
          title="Marcar como pagado"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-muted transition hover:bg-white/5 hover:text-status-good disabled:cursor-not-allowed disabled:opacity-50"
        >
          <CheckCircle2 aria-hidden="true" className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}

function describeDue(bill: RecurringBill): { text: string; warn: boolean } {
  if (bill.next_status === 'paid') return { text: 'Pagado', warn: false };
  if (bill.next_status === 'skipped') return { text: 'Omitido', warn: false };
  if (!bill.next_due_date) return { text: 'Sin pendiente', warn: false };

  const days = daysUntil(bill.next_due_date);
  const warn = days <= bill.reminder_days_before;
  let text: string;
  if (days < 0) {
    const overdue = Math.abs(days);
    text = `venció hace ${overdue} día${overdue === 1 ? '' : 's'}`;
  } else if (days === 0) {
    text = 'vence hoy';
  } else if (days === 1) {
    text = 'vence mañana';
  } else {
    text = `vence en ${days} días`;
  }
  return { text, warn };
}

function daysUntil(dateOnly: string): number {
  const due = new Date(`${dateOnly}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - today.getTime()) / 86_400_000);
}

function RecurringBillForm({
  categories,
  accounts,
  onSaved,
}: {
  categories: FinanceCategory[];
  accounts: FinanceAccount[];
  onSaved: () => void;
}) {
  const [name, setName] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [accountId, setAccountId] = useState('');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState(DEFAULT_CURRENCY);
  const [frequency, setFrequency] = useState<BillFrequency>('monthly');
  const [anchorDueDate, setAnchorDueDate] = useState('');
  const [reminderDays, setReminderDays] = useState('3');
  const [isActive, setIsActive] = useState(true);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !amount || !anchorDueDate) return;
    setSaving(true);
    setStatus(null);
    try {
      await putRecurringBill({
        name: name.trim(),
        category_id: categoryId || undefined,
        account_id: accountId || undefined,
        amount_cents: Math.round(Number(amount) * 100),
        currency,
        frequency,
        anchor_due_date: anchorDueDate,
        reminder_days_before: Number(reminderDays) || 0,
        is_active: isActive,
        notes: notes || undefined,
      });
      setStatus('Pago recurrente guardado.');
      setName('');
      setAmount('');
      setAnchorDueDate('');
      setNotes('');
      onSaved();
    } catch {
      setStatus('No se pudo guardar el pago recurrente.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <label className="block text-xs text-ink-muted sm:col-span-2">
        Nombre
        <input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          placeholder="Netflix, renta, gimnasio..."
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted">
        Monto
        <input
          type="number"
          min="0"
          step="0.01"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          required
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted">
        Categoría (opcional)
        <select
          value={categoryId}
          onChange={(event) => setCategoryId(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        >
          <option value="">Sin categoría</option>
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.emoji ? `${category.emoji} ` : ''}
              {category.name}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-ink-muted">
        Cuenta (opcional)
        <select
          value={accountId}
          onChange={(event) => setAccountId(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        >
          <option value="">Sin cuenta</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.name}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-ink-muted">
        Moneda
        <input
          type="text"
          value={currency}
          onChange={(event) => setCurrency(event.target.value.toUpperCase())}
          maxLength={3}
          minLength={3}
          required
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm uppercase text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted">
        Frecuencia
        <select
          value={frequency}
          onChange={(event) => setFrequency(event.target.value as BillFrequency)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        >
          {(Object.keys(FREQUENCY_LABELS) as BillFrequency[]).map((key) => (
            <option key={key} value={key}>
              {FREQUENCY_LABELS[key]}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-ink-muted">
        Primer vencimiento
        <input
          type="date"
          value={anchorDueDate}
          onChange={(event) => setAnchorDueDate(event.target.value)}
          required
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted">
        Recordar (días antes)
        <input
          type="number"
          min="0"
          value={reminderDays}
          onChange={(event) => setReminderDays(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="flex items-center gap-2 self-end text-sm text-ink-secondary">
        <input
          type="checkbox"
          checked={isActive}
          onChange={(event) => setIsActive(event.target.checked)}
          className="h-4 w-4 accent-cobalt"
        />
        Activo
      </label>

      <label className="block text-xs text-ink-muted sm:col-span-3">
        Notas (opcional)
        <input
          type="text"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <button
        type="submit"
        disabled={saving}
        className="inline-flex h-9 items-center justify-center rounded-lg border border-cobalt/30 bg-cobalt/10 px-3 text-sm font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-3"
      >
        {saving ? 'Guardando' : 'Guardar pago recurrente'}
      </button>

      {status ? <p className="text-xs text-ink-muted sm:col-span-3">{status}</p> : null}
    </form>
  );
}
