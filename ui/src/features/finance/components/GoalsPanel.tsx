import { useState, type FormEvent } from 'react';
import { AlertTriangle, Target } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { SkeletonLines } from '../../../components/ui/Skeleton.tsx';
import { cn } from '../../../lib/cn.ts';
import { DEFAULT_CURRENCY, formatCents } from '../lib/format.ts';
import { putGoal } from '../hooks/useFinanceApi.ts';
import type { EmergencyFundSummary, FinanceGoal } from '../types.ts';

interface GoalsPanelProps {
  goals: FinanceGoal[];
  emergencyFund: EmergencyFundSummary | null;
  loading?: boolean;
  error?: string | null;
  onChanged: () => void;
}

/**
 * One "Metas y fondo de emergencia" card, per the mockup -- the emergency
 * fund is rendered with the exact same goal-row visual pattern as a real
 * savings goal (name + target line, thin beam-colored track, figures row),
 * not a separate widget.
 */
export function GoalsPanel({ goals, emergencyFund, loading, error, onChanged }: GoalsPanelProps) {
  return (
    <Panel title="Metas y fondo de emergencia" icon={<Target aria-hidden="true" className="h-4 w-4 text-cobalt" />}>
      {error ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudieron cargar las metas"
        />
      ) : loading && goals.length === 0 ? (
        <SkeletonLines rows={4} />
      ) : (
        <div className="flex flex-col">
          <div className="border-b border-hairline/60 py-3.5 last:border-b-0">
            <EmergencyFundRow emergencyFund={emergencyFund} />
          </div>
          {goals.length === 0 ? (
            <div className="py-3.5">
              <EmptyState
                icon={<Target aria-hidden="true" className="h-6 w-6" />}
                title="Sin metas registradas"
                hint="Creá tu primera meta con el formulario de abajo."
              />
            </div>
          ) : (
            goals.map((goal) => (
              <div key={goal.id} className="border-b border-hairline/60 py-3.5 last:border-b-0">
                <GoalCard goal={goal} onChanged={onChanged} />
              </div>
            ))
          )}
        </div>
      )}

      <div className="mt-2 border-t border-hairline/60 pt-4">
        <GoalForm onSaved={onChanged} />
      </div>
    </Panel>
  );
}

interface GoalRowProps {
  name: string;
  targetLabel?: string | null;
  ratio: number | null;
  leftFigure: string;
  rightFigure: string;
  badge?: string | null;
  fillClassName?: string;
}

/** The shared goal-progress visual: name + target line, track + fill, figures row. */
function GoalRow({ name, targetLabel, ratio, leftFigure, rightFigure, badge, fillClassName }: GoalRowProps) {
  const pct = ratio == null ? 0 : Math.max(0, Math.min(ratio, 1)) * 100;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-sm font-medium text-ink">
          {name}
          {badge ? <span className="ml-2 text-xs font-medium text-status-good">{badge}</span> : null}
        </span>
        {targetLabel ? <span className="text-xs text-ink-muted">{targetLabel}</span> : null}
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div className={cn('h-full rounded-full', fillClassName ?? 'bg-beam')} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-xs font-medium text-ink-secondary">
        <span className="tabular-nums">{leftFigure}</span>
        <span className="tabular-nums">{rightFigure}</span>
      </div>
    </div>
  );
}

function EmergencyFundRow({ emergencyFund }: { emergencyFund: EmergencyFundSummary | null }) {
  if (!emergencyFund || !emergencyFund.data_sufficient) {
    return (
      <div className="flex items-start gap-2 text-sm text-ink-muted">
        <Target aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          Fondo de emergencia: todavía no hay suficiente historial. Necesita un corte de patrimonio y unos meses de
          gasto registrado para estimarse.
        </span>
      </div>
    );
  }

  const ratio =
    emergencyFund.months_covered == null ? null : emergencyFund.months_covered / emergencyFund.target_max_months;
  const badge =
    emergencyFund.status === 'above' ? 'Sobre el objetivo' : emergencyFund.status === 'below' ? 'Por debajo' : null;
  const fillClassName =
    emergencyFund.status === 'above'
      ? 'bg-status-good'
      : emergencyFund.status === 'below'
        ? 'bg-status-warning'
        : 'bg-beam';

  return (
    <GoalRow
      name="Fondo de emergencia"
      targetLabel={`${emergencyFund.target_min_months} a ${emergencyFund.target_max_months} meses de gasto fijo`}
      ratio={ratio}
      leftFigure={emergencyFund.months_covered != null ? `${emergencyFund.months_covered.toFixed(1)} meses cubiertos` : 'N/D'}
      rightFigure={`objetivo ${emergencyFund.target_max_months} meses`}
      badge={badge}
      fillClassName={fillClassName}
    />
  );
}

function GoalCard({ goal, onChanged }: { goal: FinanceGoal; onChanged: () => void }) {
  const [current, setCurrent] = useState(String(goal.current_amount_cents / 100));
  const [saving, setSaving] = useState(false);
  const ratio = goal.target_amount_cents > 0 ? goal.current_amount_cents / goal.target_amount_cents : null;

  const save = async () => {
    setSaving(true);
    try {
      await putGoal({
        id: goal.id,
        name: goal.name,
        target_amount_cents: goal.target_amount_cents,
        current_amount_cents: Math.round(Number(current) * 100),
        currency: goal.currency,
        target_date: goal.target_date ?? undefined,
        purpose_note: goal.purpose_note ?? undefined,
        is_achieved: goal.target_amount_cents > 0 && Math.round(Number(current) * 100) >= goal.target_amount_cents,
      });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <GoalRow
        name={goal.name}
        targetLabel={goal.target_date ? `meta: ${goal.target_date}` : (goal.purpose_note ?? null)}
        ratio={ratio}
        leftFigure={formatCents(goal.current_amount_cents, goal.currency)}
        rightFigure={`de ${formatCents(goal.target_amount_cents, goal.currency)}`}
        badge={goal.is_achieved ? 'Lograda' : null}
        fillClassName={goal.is_achieved ? 'bg-status-good' : 'bg-beam'}
      />

      <div className="mt-3 flex items-center gap-2">
        <input
          type="number"
          min="0"
          step="0.01"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          className="h-8 w-28 rounded-md border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none focus:border-cobalt/40"
          aria-label={`Monto actual de ${goal.name}`}
        />
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="inline-flex h-8 items-center rounded-md border border-cobalt/30 bg-cobalt/10 px-2.5 text-xs font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? 'Guardando' : 'Actualizar monto'}
        </button>
      </div>
    </div>
  );
}

function GoalForm({ onSaved }: { onSaved: () => void }) {
  const [name, setName] = useState('');
  const [targetAmount, setTargetAmount] = useState('');
  const [currentAmount, setCurrentAmount] = useState('0');
  const [currency, setCurrency] = useState(DEFAULT_CURRENCY);
  const [targetDate, setTargetDate] = useState('');
  const [purposeNote, setPurposeNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !targetAmount) return;
    setSaving(true);
    setStatus(null);
    try {
      await putGoal({
        name: name.trim(),
        target_amount_cents: Math.round(Number(targetAmount) * 100),
        current_amount_cents: Math.round(Number(currentAmount || '0') * 100),
        currency,
        target_date: targetDate || undefined,
        purpose_note: purposeNote || undefined,
        is_achieved: false,
      });
      setStatus('Meta creada.');
      setName('');
      setTargetAmount('');
      setCurrentAmount('0');
      setTargetDate('');
      setPurposeNote('');
      onSaved();
    } catch {
      setStatus('No se pudo crear la meta.');
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
          placeholder="Fondo de emergencia, viaje, enganche..."
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
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
        Monto objetivo
        <input
          type="number"
          min="0"
          step="0.01"
          value={targetAmount}
          onChange={(event) => setTargetAmount(event.target.value)}
          required
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted">
        Monto actual
        <input
          type="number"
          min="0"
          step="0.01"
          value={currentAmount}
          onChange={(event) => setCurrentAmount(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-right text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted">
        Fecha objetivo (opcional)
        <input
          type="date"
          value={targetDate}
          onChange={(event) => setTargetDate(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <label className="block text-xs text-ink-muted sm:col-span-3">
        Para qué es (opcional)
        <input
          type="text"
          value={purposeNote}
          onChange={(event) => setPurposeNote(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-hairline bg-canvas px-2 text-sm text-ink outline-none transition focus:border-cobalt/40"
        />
      </label>

      <button
        type="submit"
        disabled={saving}
        className="inline-flex h-9 items-center justify-center rounded-lg border border-cobalt/30 bg-cobalt/10 px-3 text-sm font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-3"
      >
        {saving ? 'Guardando' : 'Crear meta'}
      </button>

      {status ? <p className="text-xs text-ink-muted sm:col-span-3">{status}</p> : null}
    </form>
  );
}
