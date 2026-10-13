import axios from 'axios';
import { API_BASE_URL } from '../../../lib/apiBase.ts';

const CFDI_URL = `${API_BASE_URL}/finance/cfdi`;

export interface CfdiDocument {
  uuid: string;
  issued_at: string;
  invoice_type: string | null;
  issuer_rfc: string | null;
  issuer_name: string | null;
  uso_cfdi: string | null;
  currency: string;
  total_cents: number;
  personal_deduction_use: boolean;
  use_label: string | null;
  use_label_status: string | null;
  paid_in_cash: boolean;
}

export interface CfdiUseSummary {
  uso_cfdi: string;
  currency: string;
  count: number;
  total_cents: number;
  use_label: string;
  use_label_status: string;
}

export interface CfdiYear {
  year: number;
  documents: CfdiDocument[];
  personal_deductions_by_use: CfdiUseSummary[];
  paid_in_cash_count: number;
  disclaimer: string;
}

/** The API's Spanish `detail` when it sent one (e.g. the missing-migration 503), else `fallback`. */
export function apiDetail(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return fallback;
}

export async function fetchCfdis(year: number): Promise<CfdiYear> {
  return (await axios.get<CfdiYear>(CFDI_URL, { params: { year } })).data;
}

/** Uploads one invoice; a rejected file throws an `Error` carrying the API's Spanish detail. */
export async function putCfdi(xml: string, filename: string): Promise<{ created: boolean }> {
  try {
    return (await axios.put<{ created: boolean }>(CFDI_URL, { xml, filename })).data;
  } catch (caught) {
    throw new Error(apiDetail(caught, 'No se pudo importar la factura.'), { cause: caught });
  }
}
