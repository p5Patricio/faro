export type MacroSectionKey = 'inflation' | 'rates';
export type MacroCountry = 'MX' | 'US';
export type MacroFrequency = 'monthly' | 'daily' | 'weekly';
export type MacroStatus = 'ok' | 'stale' | 'no_data' | 'not_configured';

/** One reading of a series; `date` is a date-only value ("YYYY-MM-DD", parse it as a LOCAL date). */
export interface MacroPoint {
  date: string;
  value: number;
}

/** One macro series (inflation, a policy rate...). Values are percentages, e.g. 4.21 means 4.21%. */
export interface MacroItem {
  series_id: string;
  label: string;
  country: MacroCountry;
  unit: 'percent';
  frequency: MacroFrequency;
  source: string;
  status: MacroStatus;
  latest: MacroPoint | null;
  previous: MacroPoint | null;
  /** Recent readings for the sparkline; sorted defensively by date before drawing. */
  history: MacroPoint[];
}

export interface MacroSection {
  key: MacroSectionKey;
  label: string;
  items: MacroItem[];
}

/** Approximate real yield of the 364-day CETES, expressed in percent like the series values. */
export interface RealRate {
  cetes_364d: number;
  inflation: number;
  real_rate: number;
}

/** Response of `GET {API_BASE}/macro/overview`. */
export interface MacroOverviewResponse {
  /** ISO timestamp of when the overview was assembled. */
  as_of: string;
  sections: MacroSection[];
  real_rate: RealRate | null;
}
