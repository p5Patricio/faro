import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { formatCents } from '../lib/format.ts';
import { InvestableSurplusPanel } from './InvestableSurplusPanel.tsx';
import type {
  CashFlowForecastSummary,
  EmergencyFundSummary,
  FinanceHistory,
  FireNumberSummary,
  InvestableSurplusSummary,
  NetWorthSummary,
  SubscriptionsSummary,
} from '../types.ts';

function makeForecast(overrides: Partial<CashFlowForecastSummary> = {}): CashFlowForecastSummary {
  return {
    data_sufficient: true,
    horizon_days: 30,
    income_data_sufficient: true,
    expected_income_cents: 3000000,
    committed_bills_cents: 250000,
    overdue_bills_cents: 0,
    overdue_bills_count: 0,
    projected_net_cents: 2750000,
    ...overrides,
  };
}

function makeSurplus(overrides: Partial<InvestableSurplusSummary> = {}): InvestableSurplusSummary {
  return {
    data_sufficient: true,
    surplus_cents: 0,
    reason: 'building_emergency_fund',
    available_cents: 0,
    shortfall_cents: 0,
    income_cents: 1_000_000,
    spending_cents: 1_000_000,
    saved_cents: 0,
    ...overrides,
  };
}

const HISTORY: FinanceHistory = {
  months_used: 2,
  months_considered: 3,
  min_transactions_per_month: 5,
  unconverted_transactions: 0,
};

const NO_HISTORY: FinanceHistory = { ...HISTORY, months_used: 0 };

const NET_WORTH: NetWorthSummary = {
  data_sufficient: true,
  snapshot_date: '2026-09-01',
  total_assets_cents: 700_000,
  total_liabilities_cents: 0,
  net_worth_cents: 700_000,
  liquid_assets_cents: 700_000,
  liquid_items_count: 1,
  unclassified_items_count: 0,
  liquidity_flags_available: true,
};

const NO_NET_WORTH: NetWorthSummary = {
  data_sufficient: false,
  snapshot_date: null,
  total_assets_cents: null,
  total_liabilities_cents: null,
  net_worth_cents: null,
  liquid_assets_cents: null,
  liquid_items_count: 0,
  unclassified_items_count: 0,
  liquidity_flags_available: true,
};

function makeFund(monthsCovered: number | null): EmergencyFundSummary {
  return {
    data_sufficient: true,
    months_covered: monthsCovered,
    target_min_months: 3,
    target_max_months: 6,
    status: monthsCovered !== null && monthsCovered >= 3 ? 'within' : 'below',
  };
}

interface PanelOverrides {
  investableSurplus?: InvestableSurplusSummary;
  fireNumber?: FireNumberSummary;
  cashFlowForecast?: CashFlowForecastSummary;
  emergencyFund?: EmergencyFundSummary | null;
  history?: FinanceHistory;
  netWorth?: NetWorthSummary;
  subscriptions?: SubscriptionsSummary;
}

function renderPanel({
  investableSurplus = makeSurplus({ data_sufficient: false }),
  // Sufficient by default so its own "what is missing" hint never duplicates the surplus card's.
  fireNumber = { data_sufficient: true, target_cents: 12_000_000, progress_pct: null },
  cashFlowForecast = makeForecast(),
  emergencyFund = null,
  history = HISTORY,
  netWorth = NET_WORTH,
  subscriptions = { data_sufficient: true, annual_total_cents: 0, monthly_average_cents: 0, bills: [] },
}: PanelOverrides = {}) {
  return render(
    <InvestableSurplusPanel
      investableSurplus={investableSurplus}
      fireNumber={fireNumber}
      subscriptions={subscriptions}
      cashFlowForecast={cashFlowForecast}
      emergencyFund={emergencyFund}
      history={history}
      netWorth={netWorth}
    />,
  );
}

describe('InvestableSurplusPanel cash-flow forecast', () => {
  it('shows the committed bills without an overdue note when nothing is overdue', () => {
    renderPanel({ cashFlowForecast: makeForecast() });

    expect(screen.getByText('Pagos comprometidos')).toBeInTheDocument();
    expect(screen.queryByText(/vencido/)).not.toBeInTheDocument();
  });

  it('breaks out the overdue amount and count, in text with an icon, when some are overdue', () => {
    renderPanel({
      cashFlowForecast: makeForecast({ committed_bills_cents: 350000, overdue_bills_cents: 100000, overdue_bills_count: 2 }),
    });

    const note = screen.getByText(/Incluye .* de 2 pagos vencidos/);
    expect(note).toHaveTextContent(/\$1,000\.00/);
    expect(note.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('uses the singular for one overdue payment', () => {
    renderPanel({
      cashFlowForecast: makeForecast({ committed_bills_cents: 150000, overdue_bills_cents: 100000, overdue_bills_count: 1 }),
    });

    expect(screen.getByText(/Incluye .* de 1 pago vencido$/)).toBeInTheDocument();
  });

  it('labels the income projection as an estimate and signs the projected net', () => {
    renderPanel({ cashFlowForecast: makeForecast({ projected_net_cents: -150000 }) });

    expect(screen.getByText('Ingreso esperado (estimado)')).toBeInTheDocument();
    // A negative net reads from its minus sign, not only from the red colour.
    expect(screen.getByText(formatCents(-150000))).toBeInTheDocument();
  });

  it('keeps the committed and overdue bills when there is no income history, and says the income is unknown', () => {
    renderPanel({
      cashFlowForecast: makeForecast({
        income_data_sufficient: false,
        expected_income_cents: null,
        projected_net_cents: null,
        committed_bills_cents: 200000,
        overdue_bills_cents: 100000,
        overdue_bills_count: 1,
      }),
    });

    expect(screen.getByText('Pagos comprometidos')).toBeInTheDocument();
    expect(screen.getByText(formatCents(200000))).toBeInTheDocument();
    expect(screen.getByText(/Incluye .* de 1 pago vencido$/)).toBeInTheDocument();
    // Unknown, not $0.00 and not a made-up shortfall.
    expect(screen.getAllByText('Sin historial')).toHaveLength(2);
    expect(screen.getByText(/no se proyecta un ingreso ni un neto/)).toBeInTheDocument();
  });

  it('shows an empty state only when there are no bills and no income history at all', () => {
    renderPanel({
      cashFlowForecast: makeForecast({
        data_sufficient: false,
        income_data_sufficient: false,
        expected_income_cents: null,
        projected_net_cents: null,
        committed_bills_cents: 0,
      }),
    });

    expect(screen.getByText('Todavía no hay nada que proyectar')).toBeInTheDocument();
    expect(screen.queryByText('Pagos comprometidos')).not.toBeInTheDocument();
  });

  it('does not claim there are no recurring payments: a yearly bill may simply not fall inside the window', () => {
    renderPanel({
      cashFlowForecast: makeForecast({
        data_sufficient: false,
        income_data_sufficient: false,
        expected_income_cents: null,
        projected_net_cents: null,
        committed_bills_cents: 0,
      }),
    });

    expect(
      screen.getByText('No hay pagos por vencer en los próximos 30 días ni ingresos de meses anteriores con los que proyectar.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/cuando registres pagos recurrentes/)).not.toBeInTheDocument();
  });
});

describe('InvestableSurplusPanel surplus insight copy', () => {
  it('says how much was left unspent and that the emergency fund comes first, with the months still missing', () => {
    renderPanel({
      investableSurplus: makeSurplus({ available_cents: 300_000, spending_cents: 700_000, income_cents: 1_000_000 }),
      emergencyFund: makeFund(1.5),
    });

    const card = screen.getByText(/te quedaron .* sin gastar/);
    expect(card).toHaveTextContent(formatCents(300_000));
    expect(card).toHaveTextContent('Antes de invertir va tu fondo de emergencia');
    expect(card).toHaveTextContent('te faltan 1.5 meses para completarlo');
  });

  it('says the emergency fund is almost complete instead of claiming there is no data', () => {
    renderPanel({
      investableSurplus: makeSurplus({ available_cents: 300_000, spending_cents: 700_000 }),
      emergencyFund: makeFund(2.98),
    });

    expect(screen.getByText(/está a punto de completarse/)).toBeInTheDocument();
    expect(screen.queryByText(/todavía no hay datos para medir/)).not.toBeInTheDocument();
  });

  it('says the fund cannot be measured yet when its coverage is unknown', () => {
    renderPanel({
      investableSurplus: makeSurplus({ available_cents: 300_000, spending_cents: 700_000 }),
      emergencyFund: makeFund(null),
    });

    expect(screen.getByText(/todavía no hay datos para medir cuánto te falta/)).toBeInTheDocument();
  });

  it('says the fund cannot be measured, and names the next action, while no asset is marked liquid', () => {
    renderPanel({
      investableSurplus: makeSurplus({ reason: 'liquidity_unclassified', available_cents: 300_000, spending_cents: 700_000 }),
      emergencyFund: { ...makeFund(null), status: 'unclassified' },
    });

    expect(screen.getByText(/todavía no se puede medir tu fondo de emergencia/)).toHaveTextContent(formatCents(300_000));
    expect(screen.getByText(/Marca cuáles de tus activos son líquidos/)).toBeInTheDocument();
    expect(screen.queryByText(/todavía no hay datos para medir/)).not.toBeInTheDocument();
  });

  it('says the money can work, and points at Mercados, once the emergency fund is covered', () => {
    renderPanel({
      investableSurplus: makeSurplus({
        reason: 'emergency_fund_covered',
        surplus_cents: 300_000,
        available_cents: 300_000,
        spending_cents: 700_000,
      }),
      emergencyFund: makeFund(4),
    });

    expect(screen.getByText(/tu fondo de emergencia ya está cubierto, así que este dinero puede trabajar/)).toHaveTextContent(
      formatCents(300_000),
    );
    // Neutral es-MX, not voseo.
    expect(screen.getByText('Con este excedente, revisa las señales de tus activos en la pestaña Mercados antes de moverlo.')).toBeInTheDocument();
  });

  it('leads with the shortfall when spending exceeded income, whatever the emergency fund says', () => {
    renderPanel({
      investableSurplus: makeSurplus({
        reason: 'emergency_fund_covered',
        available_cents: -250_000,
        shortfall_cents: 250_000,
        income_cents: 750_000,
        spending_cents: 1_000_000,
      }),
      emergencyFund: makeFund(5),
    });

    const card = screen.getByText(/tus gastos superaron a tus ingresos/);
    expect(card).toHaveTextContent(formatCents(250_000));
    expect(screen.queryByText(/te quedaron/)).not.toBeInTheDocument();
  });

  it('says there is no income logged, instead of an overspend, when only expenses exist', () => {
    renderPanel({
      investableSurplus: makeSurplus({
        available_cents: -400_000,
        shortfall_cents: 400_000,
        income_cents: 0,
        spending_cents: 400_000,
      }),
    });

    expect(screen.getByText(/y no hay ingresos registrados/)).toHaveTextContent(formatCents(400_000));
  });

  it('says nothing was logged when the month has neither income nor spending', () => {
    renderPanel({ investableSurplus: makeSurplus({ income_cents: 0, spending_cents: 0 }) });

    expect(screen.getByText(/todavía no hay ingresos ni gastos registrados/)).toBeInTheDocument();
  });

  it('says only savings were logged, not that nothing was, when the month has just a saving entry', () => {
    renderPanel({ investableSurplus: makeSurplus({ income_cents: 0, spending_cents: 0, saved_cents: 80_000 }) });

    const card = screen.getByText(/solo hay ahorro registrado/);
    expect(card).toHaveTextContent(formatCents(80_000));
    expect(card).toHaveTextContent('ningún ingreso ni gasto');
    expect(screen.queryByText(/todavía no hay ingresos ni gastos registrados/)).not.toBeInTheDocument();
  });

  it('says everything was spent when the month broke even', () => {
    renderPanel({
      investableSurplus: makeSurplus({ reason: 'emergency_fund_covered', available_cents: 0 }),
      emergencyFund: makeFund(4),
    });

    expect(screen.getByText(/gastaste todo lo que ingresó, así que no quedó excedente/)).toBeInTheDocument();
  });

  it('names what is missing when there is not enough information, without a hard-coded history claim', () => {
    renderPanel({ investableSurplus: makeSurplus({ data_sufficient: false }), history: NO_HISTORY, netWorth: NO_NET_WORTH });

    expect(screen.getByText('Todavía no hay suficiente información')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Para calcularlo falta un corte de patrimonio (pestaña Patrimonio) y un mes anterior con al menos 5 movimientos registrados.',
      ),
    ).toBeInTheDocument();
  });

  it('names only the piece that is still missing', () => {
    renderPanel({ investableSurplus: makeSurplus({ data_sufficient: false }), history: HISTORY, netWorth: NO_NET_WORTH });

    expect(screen.getByText('Para calcularlo falta un corte de patrimonio (pestaña Patrimonio).')).toBeInTheDocument();
  });
});

describe('InvestableSurplusPanel estimates', () => {
  it('says how many months the estimates were built from', () => {
    renderPanel({ history: HISTORY });

    expect(screen.getByText(/Estimado con 2 meses/)).toBeInTheDocument();
  });

  it('uses the singular for one month', () => {
    renderPanel({ history: { ...HISTORY, months_used: 1 } });

    expect(screen.getByText(/Estimado con 1 mes:/)).toBeInTheDocument();
  });

  it('says there are not enough months when none met the coverage rule', () => {
    renderPanel({ history: NO_HISTORY, fireNumber: { data_sufficient: false, target_cents: 0, progress_pct: null } });

    expect(screen.getByText(/Todavía no hay meses anteriores suficientes para estimar/)).toBeInTheDocument();
    expect(screen.queryByText(/Estimado con/)).not.toBeInTheDocument();
  });

  it('reports the unconverted rows of the considered months instead of dropping them silently', () => {
    renderPanel({ history: { ...HISTORY, unconverted_transactions: 3 } });

    expect(screen.getByText(/3 movimientos de esos meses no se incluyen/)).toBeInTheDocument();
  });

  it('labels the FIRE number as an estimate and states its baseline excludes savings', () => {
    renderPanel({ fireNumber: { data_sufficient: true, target_cents: 105_000_000, progress_pct: 0.7 }, history: HISTORY });

    expect(screen.getByText(formatCents(105_000_000))).toBeInTheDocument();
    expect(screen.getByText(/sin contar lo ahorrado\) · estimado con 2 meses · llevas 0\.7% del camino/)).toBeInTheDocument();
  });

  it('explains a FIRE number that sufficient history cannot compute', () => {
    renderPanel({ fireNumber: { data_sufficient: true, target_cents: 0, progress_pct: null } });

    expect(screen.getByText('Sin gasto promedio que proyectar')).toBeInTheDocument();
  });
});

describe('InvestableSurplusPanel unconverted bills', () => {
  const SUBSCRIPTIONS: SubscriptionsSummary = {
    data_sufficient: true,
    annual_total_cents: 0,
    monthly_average_cents: 0,
    bills: [],
  };

  it('warns that active bills outside the base currency are left out of the subscription figures', () => {
    renderPanel({ subscriptions: { ...SUBSCRIPTIONS, unconverted_bills: 2 } });

    expect(screen.getByText(/2 pagos recurrentes activos no están incluidos en estas cifras/)).toBeInTheDocument();
  });

  it.each([0, undefined])('shows no such warning when unconverted_bills is %s', (count) => {
    renderPanel({ subscriptions: { ...SUBSCRIPTIONS, unconverted_bills: count } });

    expect(screen.queryByText(/pagos? recurrentes? activos? no está/)).not.toBeInTheDocument();
  });
});
