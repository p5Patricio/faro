import { useCallback, useState, type ReactNode } from 'react';
import { AlertTriangle, ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { Panel } from '../../components/ui/Panel.tsx';
import { EmptyState } from '../../components/ui/EmptyState.tsx';
import { SkeletonLines, SkeletonMetrics } from '../../components/ui/Skeleton.tsx';
import { Drawer } from '../../components/ui/Drawer.tsx';
import { cn } from '../../lib/cn.ts';
import {
  useFinanceAccounts,
  useFinanceBudgets,
  useFinanceCategories,
  useFinanceGoals,
  useFinanceNetWorth,
  useFinanceRecurringBills,
  useFinanceSummary,
  useFinanceTransactions,
} from './hooks/useFinanceApi.ts';
import { formatMonth, formatMonthLabel, shiftMonth } from './lib/format.ts';
import { MonthSummaryPanel } from './components/MonthSummaryPanel.tsx';
import { CategoryBreakdownPanel } from './components/CategoryBreakdownPanel.tsx';
import { NetWorthPanel } from './components/NetWorthPanel.tsx';
import { RecurringBillsPanel } from './components/RecurringBillsPanel.tsx';
import { GoalsPanel } from './components/GoalsPanel.tsx';
import { InvestableSurplusPanel } from './components/InvestableSurplusPanel.tsx';
import { TransactionsPanel } from './components/TransactionsPanel.tsx';
import { TransactionForm } from './components/TransactionForm.tsx';

type FinanceSection = 'resumen' | 'categorias' | 'patrimonio' | 'recurrentes' | 'metas' | 'excedente' | 'movimientos';

interface SectionOption {
  value: FinanceSection;
  label: string;
}

const SECTION_OPTIONS: SectionOption[] = [
  { value: 'resumen', label: 'Resumen' },
  { value: 'categorias', label: 'Categorías' },
  { value: 'patrimonio', label: 'Patrimonio' },
  { value: 'recurrentes', label: 'Recurrentes' },
  { value: 'metas', label: 'Metas' },
  { value: 'excedente', label: 'Excedente' },
  { value: 'movimientos', label: 'Movimientos' },
];

/**
 * Anchor-positioned animated tab underline (per modern-web-guidance's
 * anchor-positioning-tab-underline pattern), with a `border-bottom`
 * fallback for browsers without `position-anchor` support and a
 * `prefers-reduced-motion` guard on the transition. Scoped to this
 * component only (not shared with the Mercados tab bar) via the
 * `.finance-tabs` class.
 */
const FINANCE_TABS_STYLE = `
  .finance-tabs { position: relative; }
  .finance-tab-active { anchor-name: --finance-active-tab; }
  .finance-tab-underline {
    position: absolute;
    inset-block-end: -1px;
    block-size: 2px;
    background: var(--color-beam);
    position-anchor: --finance-active-tab;
    inset-inline-start: anchor(left);
    inset-inline-end: anchor(right);
    pointer-events: none;
  }
  @supports not (position-anchor: auto) {
    .finance-tab-active {
      border-bottom: 2px solid var(--color-beam);
      padding-bottom: 10px;
      margin-bottom: -1px;
    }
  }
  @media (prefers-reduced-motion: no-preference) {
    .finance-tab-underline { transition: inset 0.2s ease; }
  }
`;

/**
 * Container for the personal-finance dashboard: owns the active section and
 * the selected month, fetches every resource via `hooks/useFinanceApi.ts`,
 * and hands already-fetched data down to presentational panels.
 */
export function FinanceDashboard() {
  const [month, setMonth] = useState(() => formatMonth());
  const [section, setSection] = useState<FinanceSection>('resumen');
  const [drawerOpen, setDrawerOpen] = useState(false);

  const summary = useFinanceSummary(month);
  const categories = useFinanceCategories();
  const accounts = useFinanceAccounts();
  const budgets = useFinanceBudgets(month);
  const netWorth = useFinanceNetWorth();
  const recurringBills = useFinanceRecurringBills();
  const goals = useFinanceGoals();
  const transactions = useFinanceTransactions({ month, limit: 100 });

  const refetchAfterTransaction = useCallback(() => {
    void transactions.refetch();
    void summary.refetch();
    void budgets.refetch();
  }, [transactions, summary, budgets]);

  const firstLoad = summary.loading && !summary.data && categories.loading;
  const referenceDataFailed = Boolean(categories.error || accounts.error);

  let sectionContent: ReactNode;
  if (section === 'resumen') {
    sectionContent = (
      <MonthSummaryPanel
        summary={summary.data?.monthly_summary ?? null}
        loading={summary.loading}
        error={summary.error}
      />
    );
  } else if (section === 'categorias') {
    sectionContent = (
      <CategoryBreakdownPanel
        budgets={budgets.data}
        categories={categories.data}
        month={month}
        loading={budgets.loading}
        error={budgets.error}
        onSaved={() => {
          void budgets.refetch();
          void summary.refetch();
        }}
      />
    );
  } else if (section === 'patrimonio') {
    sectionContent = (
      <NetWorthPanel
        snapshots={netWorth.data}
        loading={netWorth.loading}
        error={netWorth.error}
        onSaved={() => {
          void netWorth.refetch();
          void summary.refetch();
        }}
      />
    );
  } else if (section === 'recurrentes') {
    sectionContent = (
      <RecurringBillsPanel
        bills={recurringBills.data}
        categories={categories.data}
        accounts={accounts.data}
        loading={recurringBills.loading}
        error={recurringBills.error}
        onChanged={() => {
          void recurringBills.refetch();
          void summary.refetch();
        }}
      />
    );
  } else if (section === 'metas') {
    sectionContent = (
      <GoalsPanel
        goals={goals.data}
        emergencyFund={summary.data?.emergency_fund ?? null}
        loading={goals.loading}
        error={goals.error}
        onChanged={() => void goals.refetch()}
      />
    );
  } else if (section === 'excedente') {
    sectionContent = summary.data ? (
      <InvestableSurplusPanel
        investableSurplus={summary.data.investable_surplus}
        fireNumber={summary.data.fire_number}
        subscriptions={summary.data.subscriptions}
        cashFlowForecast={summary.data.cash_flow_forecast}
        emergencyFund={summary.data.emergency_fund}
      />
    ) : (
      <Panel title="Excedente invertible">
        {summary.error ? (
          <EmptyState
            variant="error"
            icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
            title="No se pudo cargar el resumen"
          />
        ) : (
          <SkeletonLines rows={3} />
        )}
      </Panel>
    );
  } else {
    sectionContent = (
      <TransactionsPanel
        transactions={transactions.data}
        categories={categories.data}
        accounts={accounts.data}
        loading={transactions.loading}
        error={transactions.error}
        onChanged={refetchAfterTransaction}
      />
    );
  }

  return (
    <div className="space-y-5">
      <style>{FINANCE_TABS_STYLE}</style>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Finanzas personales</p>
          <h1 className="font-display mt-1 text-[28px] font-medium leading-none text-ink first-letter:uppercase">
            {formatMonthLabel(month)}
          </h1>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => setMonth((current) => shiftMonth(current, -1))}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-hairline bg-surface text-ink-secondary transition hover:bg-surface-2"
              aria-label="Mes anterior"
            >
              <ChevronLeft aria-hidden="true" className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setMonth((current) => shiftMonth(current, 1))}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-hairline bg-surface text-ink-secondary transition hover:bg-surface-2"
              aria-label="Mes siguiente"
            >
              <ChevronRight aria-hidden="true" className="h-4 w-4" />
            </button>
          </div>

          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-beam px-4 text-sm font-semibold text-canvas transition hover:brightness-105"
          >
            <Plus aria-hidden="true" className="h-4 w-4" />
            Nueva transacción
          </button>
        </div>
      </div>

      {referenceDataFailed ? (
        <div className="rounded-lg border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
          No se pudieron cargar categorías o cuentas; los formularios de esta sección pueden no funcionar
          correctamente.
        </div>
      ) : null}

      <div className="finance-tabs border-b border-hairline">
        <div
          role="tablist"
          aria-label="Secciones de finanzas"
          className="flex gap-6 overflow-x-auto"
          onKeyDown={(event) => {
            if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
            event.preventDefault();
            const index = SECTION_OPTIONS.findIndex((option) => option.value === section);
            const delta = event.key === 'ArrowRight' ? 1 : -1;
            const next = (index + delta + SECTION_OPTIONS.length) % SECTION_OPTIONS.length;
            setSection(SECTION_OPTIONS[next].value);
          }}
        >
          {SECTION_OPTIONS.map((option) => {
            const active = option.value === section;
            return (
              <button
                key={option.value}
                type="button"
                role="tab"
                id={`finanzas-tab-${option.value}`}
                aria-controls={`finanzas-panel-${option.value}`}
                aria-selected={active}
                tabIndex={active ? 0 : -1}
                onClick={() => setSection(option.value)}
                className={cn(
                  'shrink-0 whitespace-nowrap rounded-t pb-3 pt-1 text-sm font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cobalt/50',
                  active ? 'finance-tab-active text-ink' : 'text-ink-muted hover:text-ink-secondary',
                )}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        <span aria-hidden="true" className="finance-tab-underline" />
      </div>

      <div
        role="tabpanel"
        id={`finanzas-panel-${section}`}
        aria-labelledby={`finanzas-tab-${section}`}
        tabIndex={0}
        className="focus:outline-none"
      >
        {firstLoad ? (
          <Panel>
            <SkeletonMetrics count={4} />
            <div className="mt-4">
              <SkeletonLines rows={3} />
            </div>
          </Panel>
        ) : (
          sectionContent
        )}
      </div>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title="Nueva transacción">
        <TransactionForm
          categories={categories.data}
          accounts={accounts.data}
          onSaved={() => {
            setDrawerOpen(false);
            refetchAfterTransaction();
          }}
          onCancel={() => setDrawerOpen(false)}
        />
      </Drawer>
    </div>
  );
}
