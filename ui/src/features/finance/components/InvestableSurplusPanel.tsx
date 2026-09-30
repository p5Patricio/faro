import { AlertTriangle, Compass, Info, PiggyBank, Repeat, Rocket } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { cn } from '../../../lib/cn.ts';
import { BASE_CURRENCY, formatCents, formatSignedCents } from '../lib/format.ts';
import type {
  CashFlowForecastSummary,
  EmergencyFundSummary,
  FinanceHistory,
  FireNumberSummary,
  InvestableSurplusSummary,
  NetWorthSummary,
  SubscriptionsSummary,
} from '../types.ts';

interface InvestableSurplusPanelProps {
  investableSurplus: InvestableSurplusSummary;
  fireNumber: FireNumberSummary;
  subscriptions: SubscriptionsSummary;
  cashFlowForecast: CashFlowForecastSummary;
  emergencyFund: EmergencyFundSummary | null;
  history: FinanceHistory;
  netWorth: NetWorthSummary;
}

/**
 * What the month left unspent (and whether it is free to invest), FIRE
 * progress, subscription cost, and the 30-day cash-flow forecast. The surplus
 * insight is the ONE loud, warm-gradient moment in the whole redesign --
 * everything else on this page stays quiet and contained.
 *
 * Figures that depend on trailing history are labelled as estimates, with the
 * number of months behind them (`HistoryNote`).
 */
export function InvestableSurplusPanel({
  investableSurplus,
  fireNumber,
  subscriptions,
  cashFlowForecast,
  emergencyFund,
  history,
  netWorth,
}: InvestableSurplusPanelProps) {
  return (
    <div className="space-y-5">
      {investableSurplus.data_sufficient ? (
        <InsightCard investableSurplus={investableSurplus} emergencyFund={emergencyFund} />
      ) : (
        <Panel title="Excedente invertible" icon={<PiggyBank aria-hidden="true" className="h-4 w-4 text-cobalt" />}>
          <EmptyState
            icon={<PiggyBank aria-hidden="true" className="h-6 w-6" />}
            title="Todavía no hay suficiente información"
            hint={missingForEstimateHint(netWorth, history)}
          />
        </Panel>
      )}

      <HistoryNote history={history} />

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
                Total anual {formatCents(subscriptions.annual_total_cents, BASE_CURRENCY)} · promedio mensual{' '}
                {formatCents(subscriptions.monthly_average_cents, BASE_CURRENCY)}
              </p>
              <div className="flex flex-col">
                {subscriptions.bills.map((bill, index) => (
                  <div
                    key={`${bill.name}-${index}`}
                    className="flex items-center justify-between gap-3 border-b border-hairline/60 py-2 text-sm last:border-b-0"
                  >
                    <span className="text-ink">{bill.name}</span>
                    <span className="font-medium tabular-nums text-ink-secondary">
                      {formatCents(bill.annual_cents, BASE_CURRENCY)} / año
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
              title="Todavía no hay suficiente información"
              hint={missingForEstimateHint(netWorth, history)}
            />
          ) : fireNumber.target_cents <= 0 ? (
            <EmptyState
              icon={<Rocket aria-hidden="true" className="h-6 w-6" />}
              title="Sin gasto promedio que proyectar"
              hint="Los meses considerados no tienen gastos fuera del ahorro, así que no hay un gasto anual sobre el cual calcular."
            />
          ) : (
            <>
              <p className="font-display text-[22px] leading-none tabular-nums text-ink [text-box:trim-both_cap_alphabetic]">
                {formatCents(fireNumber.target_cents, BASE_CURRENCY)}
              </p>
              <p className="mt-2 text-xs text-ink-muted">
                gasto anual × 25 (sin contar lo ahorrado) · {estimatedWith(history.months_used)}
                {fireNumber.progress_pct != null ? ` · llevas ${fireNumber.progress_pct.toFixed(1)}% del camino` : ''}
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
            title="Todavía no hay nada que proyectar"
            hint={`No hay pagos por vencer en los próximos ${cashFlowForecast.horizon_days} días ni ingresos de meses anteriores con los que proyectar.`}
          />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <ForecastStat label="Horizonte" value={`${cashFlowForecast.horizon_days} días`} />
              <ForecastStat
                label="Ingreso esperado (estimado)"
                value={
                  cashFlowForecast.expected_income_cents != null
                    ? formatCents(cashFlowForecast.expected_income_cents, BASE_CURRENCY)
                    : 'Sin historial'
                }
              />
              <ForecastStat
                label="Pagos comprometidos"
                value={formatCents(cashFlowForecast.committed_bills_cents, BASE_CURRENCY)}
              />
              <ForecastStat
                label="Neto proyectado"
                value={
                  cashFlowForecast.projected_net_cents != null
                    ? formatSignedCents(cashFlowForecast.projected_net_cents, BASE_CURRENCY)
                    : 'Sin historial'
                }
                valueClassName={
                  cashFlowForecast.projected_net_cents == null
                    ? undefined
                    : cashFlowForecast.projected_net_cents >= 0
                      ? 'text-status-good'
                      : 'text-status-critical'
                }
              />
            </div>
            {!cashFlowForecast.income_data_sufficient ? (
              <p className="mt-3 flex items-start gap-1.5 text-xs text-ink-muted">
                <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                Todavía no hay un mes anterior con ingresos registrados, así que no se proyecta un ingreso ni un
                neto. Los pagos comprometidos sí se muestran.
              </p>
            ) : null}
            {cashFlowForecast.overdue_bills_count > 0 ? (
              <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-status-critical">
                <AlertTriangle aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
                Incluye {formatCents(cashFlowForecast.overdue_bills_cents, BASE_CURRENCY)} de{' '}
                {cashFlowForecast.overdue_bills_count} pago
                {cashFlowForecast.overdue_bills_count === 1 ? ' vencido' : 's vencidos'}
              </p>
            ) : null}
          </>
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

function monthsLabel(count: number): string {
  return `${count} ${count === 1 ? 'mes' : 'meses'}`;
}

function estimatedWith(monthsUsed: number): string {
  return `estimado con ${monthsLabel(monthsUsed)}`;
}

/** What is still missing for the trailing-history sections, in words the user can act on. */
function missingForEstimateHint(netWorth: NetWorthSummary, history: FinanceHistory): string {
  const missing: string[] = [];
  if (!netWorth.data_sufficient) missing.push('un corte de patrimonio (pestaña Patrimonio)');
  if (history.months_used < 1) {
    missing.push(`un mes anterior con al menos ${history.min_transactions_per_month} movimientos registrados`);
  }
  if (missing.length === 0) return 'Todavía no hay datos suficientes para calcularlo.';
  return `Para calcularlo falta ${missing.join(' y ')}.`;
}

/** The basis of every "estimado" figure on this page: how many trailing months counted. */
function HistoryNote({ history }: { history: FinanceHistory }) {
  const excluded = history.unconverted_transactions;
  return (
    <p className="flex items-start gap-2 text-xs text-ink-muted">
      <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>
        {history.months_used >= 1
          ? `Estimado con ${monthsLabel(history.months_used)}: de los ${history.months_considered} meses anteriores, solo cuentan los que tienen al menos ${history.min_transactions_per_month} movimientos.`
          : `Todavía no hay meses anteriores suficientes para estimar: cada uno de los ${history.months_considered} meses anteriores necesita al menos ${history.min_transactions_per_month} movimientos registrados.`}
        {excluded > 0
          ? ` ${unconvertedHistoryNote(excluded)}`
          : ''}
      </span>
    </p>
  );
}

function unconvertedHistoryNote(count: number): string {
  if (count === 1) {
    return `1 movimiento de esos meses no se incluye porque está en otra moneda sin tipo de cambio a ${BASE_CURRENCY}.`;
  }
  return `${count} movimientos de esos meses no se incluyen porque están en otra moneda sin tipo de cambio a ${BASE_CURRENCY}.`;
}

// The emergency fund is measured against the assets the user marked as liquid.
const LIQUID_BASIS = 'Tu fondo de emergencia se mide con los activos que marcaste como líquidos.';

function InsightCard({
  investableSurplus,
  emergencyFund,
}: {
  investableSurplus: InvestableSurplusSummary;
  emergencyFund: EmergencyFundSummary | null;
}) {
  const { sentence, followUp, basis } = buildInsight(investableSurplus, emergencyFund);

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
      {followUp ? (
        <p className="relative mt-3 max-w-[46ch] text-[13px] leading-relaxed text-[#d8c497]">{followUp}</p>
      ) : null}
      {basis ? <p className="relative mt-2 max-w-[46ch] text-xs leading-relaxed text-[#b9a679]">{basis}</p> : null}
    </div>
  );
}

/**
 * The truth about the month, in order of precedence: nothing logged; spending
 * beat income (the shortfall leads whatever the emergency-fund gate says);
 * otherwise what was left unspent and whether the emergency fund lets it
 * count as investable. `surplus_cents` is gated by the fund and
 * `available_cents` is not -- the wording never presents the gated figure as
 * "what was left".
 */
function buildInsight(
  surplus: InvestableSurplusSummary,
  emergencyFund: EmergencyFundSummary | null,
): { sentence: string; followUp?: string; basis?: string } {
  if (surplus.income_cents === 0 && surplus.spending_cents === 0) {
    // Saving alone is neither income nor spending: say what is there, not that nothing is.
    if (surplus.saved_cents > 0) {
      return {
        sentence: `Este mes solo hay ahorro registrado (${formatCents(surplus.saved_cents, BASE_CURRENCY)}) y ningún ingreso ni gasto, así que no hay excedente que calcular.`,
      };
    }
    return { sentence: 'Este mes todavía no hay ingresos ni gastos registrados, así que no hay excedente que calcular.' };
  }

  if (surplus.shortfall_cents > 0) {
    if (surplus.income_cents === 0) {
      return {
        sentence: `Este mes gastaste ${formatCents(surplus.spending_cents, BASE_CURRENCY)} y no hay ingresos registrados, así que no hay excedente para invertir.`,
      };
    }
    return {
      sentence: `Este mes tus gastos superaron a tus ingresos por ${formatCents(surplus.shortfall_cents, BASE_CURRENCY)}, así que no hay excedente para invertir.`,
    };
  }

  if (surplus.reason === 'emergency_fund_covered') {
    if (surplus.surplus_cents > 0) {
      return {
        sentence: `Este mes te quedaron ${formatCents(surplus.surplus_cents, BASE_CURRENCY)} sin gastar y tu fondo de emergencia ya está cubierto, así que este dinero puede trabajar.`,
        followUp: 'Con este excedente, revisa las señales de tus activos en la pestaña Mercados antes de moverlo.',
        basis: LIQUID_BASIS,
      };
    }
    return { sentence: 'Este mes gastaste todo lo que ingresó, así que no quedó excedente.' };
  }

  if (surplus.available_cents <= 0) {
    return { sentence: 'Este mes gastaste todo lo que ingresó, así que no quedó dinero sin gastar.' };
  }

  const unspent = formatCents(surplus.available_cents, BASE_CURRENCY);
  if (surplus.reason === 'liquidity_unclassified') {
    return {
      sentence: `Este mes te quedaron ${unspent} sin gastar, pero todavía no se puede medir tu fondo de emergencia porque no has marcado cuáles de tus activos son líquidos.`,
      followUp: 'Marca cuáles de tus activos son líquidos en la pestaña Patrimonio para saber si este dinero ya puede invertirse.',
    };
  }
  if (emergencyFund?.months_covered != null) {
    const remaining = Math.max(emergencyFund.target_min_months - emergencyFund.months_covered, 0);
    const progress =
      remaining > 0.05 ? `te faltan ${remaining.toFixed(1)} meses para completarlo` : 'está a punto de completarse';
    return {
      sentence: `Este mes te quedaron ${unspent} sin gastar. Antes de invertir va tu fondo de emergencia: ${progress}.`,
      basis: LIQUID_BASIS,
    };
  }
  return {
    sentence: `Este mes te quedaron ${unspent} sin gastar. Antes de invertir va tu fondo de emergencia, y todavía no hay datos para medir cuánto te falta.`,
  };
}
