import { Compass, PiggyBank, Repeat, Rocket } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { cn } from '../../../lib/cn.ts';
import { DEFAULT_CURRENCY, formatCents } from '../lib/format.ts';
import type {
  CashFlowForecastSummary,
  EmergencyFundSummary,
  FireNumberSummary,
  InvestableSurplusSummary,
  SubscriptionsSummary,
} from '../types.ts';

interface InvestableSurplusPanelProps {
  investableSurplus: InvestableSurplusSummary;
  fireNumber: FireNumberSummary;
  subscriptions: SubscriptionsSummary;
  cashFlowForecast: CashFlowForecastSummary;
  emergencyFund: EmergencyFundSummary | null;
}

/**
 * Investable surplus, FIRE progress, subscription cost, and the 30-day
 * cash-flow forecast. The surplus insight is the ONE loud, warm-gradient
 * moment in the whole redesign -- everything else on this page stays
 * quiet and contained.
 */
export function InvestableSurplusPanel({
  investableSurplus,
  fireNumber,
  subscriptions,
  cashFlowForecast,
  emergencyFund,
}: InvestableSurplusPanelProps) {
  return (
    <div className="space-y-5">
      {investableSurplus.data_sufficient ? (
        <InsightCard investableSurplus={investableSurplus} emergencyFund={emergencyFund} />
      ) : (
        <Panel title="Excedente invertible" icon={<PiggyBank aria-hidden="true" className="h-4 w-4 text-cobalt" />}>
          <EmptyState
            icon={<PiggyBank aria-hidden="true" className="h-6 w-6" />}
            title="Todavía no hay suficiente historial"
            hint="Se calcula una vez que hay un fondo de emergencia estimado y meses de gasto registrados."
          />
        </Panel>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-hairline bg-surface p-5">
          <h2 className="mb-3 flex items-center gap-2 text-[13px] font-semibold tracking-wide text-ink-secondary">
            <Repeat aria-hidden="true" className="h-4 w-4 text-cobalt" />
            Suscripciones · anualizado
          </h2>
          {!subscriptions.data_sufficient || subscriptions.bills.length === 0 ? (
            <EmptyState
              icon={<Repeat aria-hidden="true" className="h-6 w-6" />}
              title="Sin suscripciones activas registradas"
              hint="Aparecen automáticamente cuando registrás pagos recurrentes activos."
            />
          ) : (
            <div>
              <p className="mb-2 text-xs text-ink-muted">
                Total anual {formatCents(subscriptions.annual_total_cents, DEFAULT_CURRENCY)} · promedio mensual{' '}
                {formatCents(subscriptions.monthly_average_cents, DEFAULT_CURRENCY)}
              </p>
              <div className="flex flex-col">
                {subscriptions.bills.map((bill, index) => (
                  <div
                    key={`${bill.name}-${index}`}
                    className="flex items-center justify-between gap-3 border-b border-hairline/60 py-2 text-sm last:border-b-0"
                  >
                    <span className="text-ink">{bill.name}</span>
                    <span className="font-medium tabular-nums text-ink-secondary">
                      {formatCents(bill.annual_cents, DEFAULT_CURRENCY)} / año
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-hairline bg-surface p-5">
          <h2 className="mb-3 flex items-center gap-2 text-[13px] font-semibold tracking-wide text-ink-secondary">
            <Rocket aria-hidden="true" className="h-4 w-4 text-cobalt" />
            Número de libertad financiera
          </h2>
          {!fireNumber.data_sufficient ? (
            <EmptyState
              icon={<Rocket aria-hidden="true" className="h-6 w-6" />}
              title="Todavía no hay suficiente historial"
              hint="Se necesita un corte de patrimonio y gasto promedio de meses recientes."
            />
          ) : (
            <>
              <p className="font-display text-[22px] leading-none tabular-nums text-ink [text-box:trim-both_cap_alphabetic]">
                {formatCents(fireNumber.target_cents, DEFAULT_CURRENCY)}
              </p>
              <p className="mt-2 text-xs text-ink-muted">
                gasto anual × 25
                {fireNumber.progress_pct != null ? ` · llevás ${fireNumber.progress_pct.toFixed(1)}% del camino` : ''}
              </p>
            </>
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-hairline bg-surface p-5">
        <h2 className="mb-3 flex items-center gap-2 text-[13px] font-semibold tracking-wide text-ink-secondary">
          <Compass aria-hidden="true" className="h-4 w-4 text-cobalt" />
          Flujo de caja a 30 días
        </h2>
        {!cashFlowForecast.data_sufficient ? (
          <EmptyState
            icon={<Compass aria-hidden="true" className="h-6 w-6" />}
            title="Todavía no hay suficiente historial"
            hint="Se necesitan meses previos con ingresos registrados para proyectar el flujo."
          />
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <ForecastStat label="Horizonte" value={`${cashFlowForecast.horizon_days} días`} />
            <ForecastStat label="Ingreso esperado" value={formatCents(cashFlowForecast.expected_income_cents, DEFAULT_CURRENCY)} />
            <ForecastStat label="Pagos comprometidos" value={formatCents(cashFlowForecast.committed_bills_cents, DEFAULT_CURRENCY)} />
            <ForecastStat
              label="Neto proyectado"
              value={formatCents(cashFlowForecast.projected_net_cents, DEFAULT_CURRENCY)}
              valueClassName={cashFlowForecast.projected_net_cents >= 0 ? 'text-status-good' : 'text-status-critical'}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function ForecastStat({ label, value, valueClassName }: { label: string; value: string; valueClassName?: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-ink-muted">{label}</p>
      <p className={cn('mt-1 text-sm font-semibold tabular-nums text-ink', valueClassName)}>{value}</p>
    </div>
  );
}

function InsightCard({
  investableSurplus,
  emergencyFund,
}: {
  investableSurplus: InvestableSurplusSummary;
  emergencyFund: EmergencyFundSummary | null;
}) {
  const sentence = buildInsightSentence(investableSurplus, emergencyFund);

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-2xl border px-7 py-6',
        'border-[#4a380f] bg-[linear-gradient(155deg,#3a2c10,#1c1408_70%)]',
        "after:pointer-events-none after:absolute after:[inset:-40%_-10%_auto_auto] after:h-[260px] after:w-[260px] after:rounded-full after:bg-[radial-gradient(circle,rgba(242,179,58,0.20),transparent_70%)] after:content-['']",
      )}
    >
      <p className="relative text-[11px] font-semibold uppercase tracking-wider text-beam">Excedente invertible</p>
      <p className="font-display relative mt-2.5 max-w-[34ch] text-[26px] leading-[1.28] text-cream">{sentence}</p>
      <p className="relative mt-3 max-w-[46ch] text-[13px] leading-relaxed text-[#d8c497]">
        Con este excedente, revisá las señales de tus activos en la pestaña Mercados antes de moverlo.
      </p>
    </div>
  );
}

function buildInsightSentence(surplus: InvestableSurplusSummary, emergencyFund: EmergencyFundSummary | null): string {
  const amount = formatCents(Math.abs(surplus.surplus_cents), DEFAULT_CURRENCY);

  if (surplus.surplus_cents < 0) {
    return `Este mes te faltaron ${amount} para cubrir tus gastos — no hay excedente para invertir todavía.`;
  }

  if (surplus.reason === 'emergency_fund_covered') {
    return `Este mes te sobraron ${amount} — tu fondo de emergencia ya está cubierto, así que este dinero puede trabajar.`;
  }

  if (emergencyFund?.data_sufficient && emergencyFund.months_covered != null) {
    const remaining = Math.max(emergencyFund.target_min_months - emergencyFund.months_covered, 0);
    if (remaining > 0.05) {
      return `Este mes te sobraron ${amount} — te faltan ${remaining.toFixed(1)} meses para completar tu fondo de emergencia, así que este excedente debería ir ahí primero.`;
    }
  }

  return `Este mes te sobraron ${amount} — estás construyendo tu fondo de emergencia, así que este excedente debería ir ahí antes de invertir.`;
}
