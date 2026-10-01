// Mirrors the locked `${API_BASE_URL}/finance` contract exactly. Every
// interface here is a response or PUT-payload shape from that contract.

export type FinanceCategoryKind = 'expense' | 'income' | 'transfer';
export type BudgetBucket = 'necesidad' | 'deseo' | 'ahorro_inversion' | null;

export interface FinanceCategory {
  id: string;
  slug: string;
  name: string;
  kind: FinanceCategoryKind;
  budget_bucket: BudgetBucket;
  // NOTE: the live `GET /finance/categories` repository query
  // (collector/local_repository.py `get_finance_categories`) does not
  // currently SELECT the `emoji` column even though it exists on the table
  // and is seeded — so this field is optional in practice. Every render
  // site must fall back gracefully when it is missing/undefined.
  emoji?: string | null;
}

export interface FinanceAccount {
  id: string;
  name: string;
  account_type: string;
  currency: string;
}

export interface FinanceTransaction {
  id: string;
  client_id: string;
  account_id: string;
  category_id: string | null;
  kind: FinanceCategoryKind;
  amount_cents: number;
  currency: string;
  // Rate to the base currency and the resulting base amount. Both are null
  // on a foreign-currency row written before base amounts existed.
  fx_rate_to_base?: number | null;
  amount_base_cents?: number | null;
  occurred_at: string;
  merchant?: string | null;
  notes?: string | null;
  source: string;
  deleted_at?: string | null;
}

export interface TransactionPayload {
  client_id: string;
  account_id: string;
  category_id?: string;
  kind: FinanceCategoryKind;
  amount_cents: number;
  currency: string;
  // Required by the API when `currency` is not the base currency; the base
  // amount is always computed server-side and never sent.
  fx_rate_to_base?: number;
  occurred_at: string;
  merchant?: string;
  notes?: string;
  source: 'ui';
  deleted_at?: string;
}

export interface TransactionFilters {
  month?: string;
  category_id?: string;
  account_id?: string;
  limit?: number;
}

export interface FinanceBudget {
  category_id: string;
  category_name: string;
  budget_bucket: BudgetBucket;
  limit_cents: number;
  percent_of_income: number | null;
  actual_cents: number;
}

export interface BudgetPayload {
  category_id: string;
  period_month?: string;
  limit_cents: number;
  percent_of_income?: number;
  currency: string;
}

export interface NetWorthItem {
  is_asset: boolean;
  label: string;
  item_type: string;
  amount_cents: number;
  currency: string;
  // Sent for a foreign-currency item (required there); returned with the
  // computed base amount. Snapshot totals are sums of the base amounts.
  fx_rate_to_base?: number | null;
  amount_base_cents?: number | null;
  // Assets only: true = liquid (money you could use in an emergency), false =
  // classified as not liquid, null/absent = not classified yet. Liabilities
  // never carry one.
  is_liquid?: boolean | null;
}

export interface NetWorthSnapshot {
  id: string;
  snapshot_date: string;
  notes?: string | null;
  total_assets_cents: number;
  total_liabilities_cents: number;
  net_worth_cents: number;
  items: NetWorthItem[];
  // Liquidity figures the API adds to every snapshot. `liquid_assets_cents`
  // sums the assets flagged liquid (liabilities NOT subtracted) and is null
  // when the database cannot store the flags.
  liquid_assets_cents?: number | null;
  liquid_items_count?: number;
  unclassified_items_count?: number;
  liquidity_flags_available?: boolean;
}

export interface NetWorthPayload {
  snapshot_date: string;
  notes?: string;
  items: NetWorthItem[];
}

export type BillFrequency =
  | 'weekly'
  | 'biweekly'
  | 'monthly'
  | 'bimonthly'
  | 'quarterly'
  | 'semiannual'
  | 'annual';

export interface RecurringBill {
  id: string;
  name: string;
  category_id: string | null;
  account_id: string | null;
  amount_cents: number;
  currency: string;
  frequency: BillFrequency;
  anchor_due_date: string;
  reminder_days_before: number;
  is_active: boolean;
  notes?: string | null;
  next_due_date: string | null;
  next_status: string | null;
}

export interface RecurringBillPayload {
  id?: string;
  name: string;
  category_id?: string;
  account_id?: string;
  amount_cents: number;
  currency: string;
  frequency: BillFrequency;
  anchor_due_date: string;
  reminder_days_before: number;
  is_active: boolean;
  notes?: string;
}

export type RecurringBillPaymentStatus = 'pending' | 'paid' | 'skipped';

export interface RecurringBillPaymentPayload {
  bill_id: string;
  due_date: string;
  status: RecurringBillPaymentStatus;
  transaction_id?: string;
}

export interface RecurringBillPayment {
  id: string;
  bill_id: string;
  due_date: string;
  status: RecurringBillPaymentStatus;
  transaction_id?: string | null;
}

export interface FinanceGoal {
  id: string;
  name: string;
  target_amount_cents: number;
  current_amount_cents: number;
  currency: string;
  target_date: string | null;
  purpose_note: string | null;
  is_achieved: boolean;
}

export interface GoalPayload {
  id?: string;
  name: string;
  target_amount_cents: number;
  current_amount_cents: number;
  currency: string;
  target_date?: string;
  purpose_note?: string;
  is_achieved: boolean;
}

export interface MonthlyBucketSummary {
  actual_cents: number;
  target_cents: number;
}

// Expenses whose category is missing (or has no bucket): an actual amount and
// NO target, because the 50/30/20 rule says nothing about unclassified money.
export interface UncategorizedBucketSummary {
  actual_cents: number;
}

export interface MonthlySummary {
  // True only when the month has at least one converted income/expense row.
  data_sufficient: boolean;
  income_cents: number;
  // Raw total of every converted expense row, savings included.
  expense_cents: number;
  // Expenses outside the savings bucket (necesidad + deseo + sin_categoria).
  spending_cents: number;
  // Expenses in the savings bucket: money moved, not spent.
  saved_cents: number;
  // Income minus `spending_cents`: what was NOT spent. Saving does not reduce it.
  net_cents: number;
  // `saved_cents` over income.
  savings_rate_pct: number;
  // Every converted expense row lands in exactly one bucket, so the actuals
  // add up to `expense_cents`.
  buckets: {
    necesidad: MonthlyBucketSummary;
    deseo: MonthlyBucketSummary;
    ahorro_inversion: MonthlyBucketSummary;
    sin_categoria: UncategorizedBucketSummary;
  };
  converted_transactions: number;
  // Income/expense rows left out of every figure above because they are in a
  // foreign currency with no FX rate. Optional: absent means none.
  unconverted_transactions?: number;
}

export type BreakdownBucket = 'necesidad' | 'deseo' | 'ahorro_inversion' | 'sin_categoria';

// One row of the month's spend by category. `category_id` is null on the
// "Sin categoría" row. The rows add up to `MonthlySummary.expense_cents`.
export interface CategoryBreakdownRow {
  category_id: string | null;
  category_name: string;
  slug: string | null;
  emoji: string | null;
  bucket: BreakdownBucket;
  actual_cents: number;
  // The category's effective monthly limit; null when it has no budget.
  budget_cents: number | null;
}

// How the trailing-average ("estimado") figures were built: the 3 completed
// months before the selected one, of which only those with at least
// `min_transactions_per_month` converted transactions count.
export interface FinanceHistory {
  months_used: number;
  months_considered: number;
  min_transactions_per_month: number;
  // Unconverted rows in the considered months (skipped months included).
  unconverted_transactions: number;
}

export interface NetWorthSummary {
  data_sufficient: boolean;
  snapshot_date: string | null;
  total_assets_cents: number | null;
  total_liabilities_cents: number | null;
  net_worth_cents: number | null;
  // Base amounts of the assets flagged liquid; liabilities are NOT subtracted.
  // Null when there is no snapshot or the database cannot store the flags.
  liquid_assets_cents: number | null;
  liquid_items_count: number;
  // Assets nobody has classified as liquid or not liquid yet.
  unclassified_items_count: number;
  // False while the database cannot store liquidity flags (migration 0013 unapplied).
  liquidity_flags_available: boolean;
}

export interface EmergencyFundSummary {
  data_sufficient: boolean;
  months_covered: number | null;
  target_min_months: number;
  target_max_months: number;
  // 'unclassified': no asset is marked liquid yet, so nothing was measured
  // (`months_covered` is null); it is not the same as 'below'.
  status: 'below' | 'within' | 'above' | 'unclassified';
}

export interface FireNumberSummary {
  data_sufficient: boolean;
  target_cents: number;
  progress_pct: number | null;
}

export interface InvestableSurplusSummary {
  data_sufficient: boolean;
  // GATED by the emergency fund: 0 while coverage is below target or unknown,
  // otherwise `max(available_cents, 0)`.
  surplus_cents: number;
  // Describes only the emergency-fund gate; check `shortfall_cents` first.
  // 'liquidity_unclassified': the fund could not be measured because no asset
  // is marked liquid yet; the surplus stays gated (0).
  reason: 'building_emergency_fund' | 'emergency_fund_covered' | 'liquidity_unclassified';
  // UNGATED: income minus spending, what the month left unspent (may be negative).
  available_cents: number;
  // How much spending exceeded income; 0 when it did not.
  shortfall_cents: number;
  income_cents: number;
  spending_cents: number;
  // Echoed so "only savings were logged" reads differently from "nothing was logged".
  saved_cents: number;
}

export interface SubscriptionBillSummary {
  name: string;
  annual_cents: number;
}

export interface SubscriptionsSummary {
  data_sufficient: boolean;
  annual_total_cents: number;
  monthly_average_cents: number;
  bills: SubscriptionBillSummary[];
  unconverted_bills?: number;
}

export interface CashFlowForecastSummary {
  // True when there are bills committed or overdue, or an income projection:
  // the bills are shown even when there is no income history.
  data_sufficient: boolean;
  horizon_days: number;
  // False when no trailing month supports an income estimate; then
  // `expected_income_cents` and `projected_net_cents` are null (unknown, not 0).
  income_data_sufficient: boolean;
  expected_income_cents: number | null;
  // Every bill payment due up to the horizon end, INCLUDING the overdue ones.
  committed_bills_cents: number;
  // Breakdown of `committed_bills_cents`: pending payments already past due.
  overdue_bills_cents: number;
  overdue_bills_count: number;
  projected_net_cents: number | null;
}

export interface FinanceSummary {
  month: string;
  monthly_summary: MonthlySummary;
  category_breakdown: CategoryBreakdownRow[];
  history: FinanceHistory;
  net_worth: NetWorthSummary;
  emergency_fund: EmergencyFundSummary;
  fire_number: FireNumberSummary;
  investable_surplus: InvestableSurplusSummary;
  subscriptions: SubscriptionsSummary;
  cash_flow_forecast: CashFlowForecastSummary;
}
