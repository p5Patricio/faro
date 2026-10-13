import axios from 'axios';
import { API_BASE_URL } from '../../lib/apiBase.ts';

export const INVESTMENTS_URL = `${API_BASE_URL}/investments`;

export type OperationKind =
  | 'buy'
  | 'sell'
  | 'split'
  | 'dividend'
  | 'fibra_distribution'
  | 'capital_return'
  | 'interest'
  | 'fee';

export type InstrumentType = 'accion_mx' | 'accion_sic' | 'etf' | 'fibra' | 'fondo' | 'deuda' | 'cripto' | 'otro';

export interface InvestmentAccount {
  id: string;
  name: string;
  broker: string | null;
  currency: string;
}

/** Quantities, prices and FX rates are decimal strings: never parsed into floats for money. */
export interface InvestmentOperation {
  client_id: string;
  account_id: string;
  trade_date: string;
  kind: OperationKind;
  symbol: string;
  instrument_type: InstrumentType;
  quantity: string | null;
  price?: string | null;
  amount_cents: number;
  fee_cents: number;
  tax_withheld_cents: number;
  currency: string;
  fx_rate_to_mxn: string | null;
  fx_rate_date: string | null;
  fx_source?: 'manual' | 'banxico_fix' | 'broker' | null;
  notes?: string | null;
}

export interface Position {
  account_id: string;
  account_name: string | null;
  symbol: string;
  instrument_type: InstrumentType;
  quantity: string;
  cost_basis_mxn_cents: number;
  average_cost_mxn_cents: string | null;
}

export interface WorksheetSummaryRow {
  account_id: string;
  concept: string;
  amount_mxn_cents: number;
  tax_withheld_mxn_cents: number;
}

export interface Worksheet {
  year: number;
  summary: WorksheetSummaryRow[];
  disclaimer: string;
}

export const KIND_LABELS: Record<OperationKind, string> = {
  buy: 'Compra',
  sell: 'Venta',
  split: 'Split',
  dividend: 'Dividendo',
  fibra_distribution: 'Distribución FIBRA (resultado fiscal)',
  capital_return: 'Reembolso de capital',
  interest: 'Interés',
  fee: 'Comisión',
};

export const CONCEPT_LABELS: Record<string, string> = { ...KIND_LABELS, sale_gain: 'Ganancia o pérdida en ventas' };

export const INSTRUMENT_LABELS: Record<InstrumentType, string> = {
  accion_mx: 'Acción BMV/BIVA',
  accion_sic: 'Acción SIC',
  etf: 'ETF',
  fibra: 'FIBRA',
  fondo: 'Fondo de inversión',
  deuda: 'Deuda (CETES, bonos)',
  cripto: 'Cripto',
  otro: 'Otro',
};

/**
 * "1,234.5" / "1234.56" -> 123456 cents, by string arithmetic so a binary
 * float never touches the amount. Returns null for anything that is not a
 * non-negative amount with at most two decimals.
 */
export function decimalToCents(text: string): number | null {
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(text.trim().replace(/,/g, ''));
  if (!match) return null;
  const cents = Number(match[1]) * 100 + Number((match[2] ?? '').padEnd(2, '0'));
  return Number.isSafeInteger(cents) ? cents : null;
}

/**
 * A quantity as the API sends it ("69.0000000000") without trailing zeros ("69",
 * "0.125"), grouping thousands. String-based, so no digit is lost to a float.
 */
export function formatQuantity(text: string): string {
  const [whole, fraction = ''] = text.split('.');
  const digits = fraction.replace(/0+$/, '');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return digits ? `${grouped}.${digits}` : grouped;
}

/** The API's `detail` when it sent one (e.g. the missing-migration 503), else `fallback`. */
export function errorDetail(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return fallback;
}

export async function fetchInvestments(year: number) {
  const [accounts, positions, operations, worksheet] = await Promise.all([
    axios.get<InvestmentAccount[]>(`${INVESTMENTS_URL}/accounts`),
    axios.get<{ positions: Position[]; disclaimer: string }>(`${INVESTMENTS_URL}/positions`),
    axios.get<InvestmentOperation[]>(`${INVESTMENTS_URL}/transactions`),
    axios.get<Worksheet>(`${INVESTMENTS_URL}/worksheet`, { params: { year } }),
  ]);
  return {
    accounts: accounts.data,
    positions: positions.data.positions,
    disclaimer: positions.data.disclaimer,
    operations: operations.data,
    worksheet: worksheet.data,
  };
}

export async function putAccount(payload: { name: string; broker?: string }): Promise<InvestmentAccount> {
  return (await axios.put<InvestmentAccount>(`${INVESTMENTS_URL}/accounts`, payload)).data;
}

export async function putOperation(payload: InvestmentOperation): Promise<InvestmentOperation> {
  return (await axios.put<InvestmentOperation>(`${INVESTMENTS_URL}/transactions`, payload)).data;
}

export type ReconciliationConcept = 'interest' | 'interest_withheld' | 'dividends' | 'sale';
export type ReconciliationStatus = 'coincide' | 'difiere' | 'sin_libro' | 'sin_constancia';

export interface ReconciliationRow {
  concept: ReconciliationConcept;
  constancia_cents: number;
  ledger_cents: number;
  difference_cents: number;
  status: ReconciliationStatus;
  constancia_real_cents?: number;
  constancia_loss_cents?: number;
  constancia_accumulable_cents?: number;
}

export interface RetentionDocument {
  uuid: string;
  year: number;
  month_start: number;
  month_end: number;
  concept: string;
  emitter_rfc: string | null;
  receiver_is_generic: boolean;
  operation_cents: number;
  withheld_cents: number;
}

export interface RetentionsYear {
  year: number;
  documents: RetentionDocument[];
  reconciliation: ReconciliationRow[];
  warnings: string[];
  disclaimer: string;
}

export const RETENTIONS_URL = `${INVESTMENTS_URL}/retentions`;

export async function fetchRetentions(year: number): Promise<RetentionsYear> {
  return (await axios.get<RetentionsYear>(RETENTIONS_URL, { params: { year } })).data;
}

/** Uploads one constancia; a rejected file throws an `Error` carrying the API's Spanish detail. */
export async function putRetention(xml: string): Promise<{ created: boolean }> {
  try {
    return (await axios.put<{ created: boolean }>(RETENTIONS_URL, { xml })).data;
  } catch (caught) {
    throw new Error(errorDetail(caught, 'No se pudo importar la constancia.'), { cause: caught });
  }
}
