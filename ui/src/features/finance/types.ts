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
}

export interface NetWorthSnapshot {
  id: string;
  snapshot_date: string;
  notes?: string | null;
  total_assets_cents: number;
  total_liabilities_cents: number;
  net_worth_cents: number;
  items: NetWorthItem[];
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

export interface MonthlySummary {
  data_sufficient: boolean;
  income_cents: number;
  expense_cents: number;
  net_cents: number;
  savings_rate_pct: number;
  buckets: {
    necesidad: MonthlyBucketSummary;
    deseo: MonthlyBucketSummary;
    ahorro_inversion: MonthlyBucketSummary;
  };
}

export interface NetWorthSummary {
  data_sufficient: boolean;
  snapshot_date: string | null;
  total_assets_cents: number | null;
  total_liabilities_cents: number | null;
  net_worth_cents: number | null;
  liquid_net_worth_cents: number | null;
}

export interface EmergencyFundSummary {
  data_sufficient: boolean;
  months_covered: number | null;
  target_min_months: number;
  target_max_months: number;
  status: 'below' | 'within' | 'above';
}

export interface FireNumberSummary {
  data_sufficient: boolean;
  target_cents: number;
  progress_pct: number | null;
}

export interface InvestableSurplusSummary {
  data_sufficient: boolean;
  surplus_cents: number;
  reason: 'building_emergency_fund' | 'emergency_fund_covered';
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
}

export interface CashFlowForecastSummary {
  data_sufficient: boolean;
  horizon_days: number;
  expected_income_cents: number;
  committed_bills_cents: number;
  projected_net_cents: number;
}

export interface FinanceSummary {
  month: string;
  monthly_summary: MonthlySummary;
  net_worth: NetWorthSummary;
  emergency_fund: EmergencyFundSummary;
  fire_number: FireNumberSummary;
  investable_surplus: InvestableSurplusSummary;
  subscriptions: SubscriptionsSummary;
  cash_flow_forecast: CashFlowForecastSummary;
}
