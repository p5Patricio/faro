/** How `MarketItem.last` should be displayed. */
export type MarketUnit = 'points' | 'price' | 'percent';

/** One instrument in the markets overview (index, rate, commodity, crypto...). */
export interface MarketItem {
  ticker: string;
  name: string;
  last: number;
  /** Day change in percent, e.g. 1.23 means +1.23%. */
  change_pct: number;
  /** Calendar day of the reading ("YYYY-MM-DD"), a date-only value (parse it as a LOCAL date). */
  as_of: string;
  /** True when the reading is older than the backend's freshness window. */
  stale: boolean;
  /** ISO currency code, only meaningful for `unit: 'price'`. */
  currency: string | null;
  unit: MarketUnit;
}

export interface MarketGroup {
  key: string;
  label: string;
  items: MarketItem[];
}

/** Response of `GET {API_BASE}/markets/overview`. */
export interface MarketsOverviewResponse {
  /** ISO timestamp of when the overview was assembled. */
  as_of: string;
  /** True when the backend served synthetic data (e.g. database unreachable). */
  is_demo: boolean;
  groups: MarketGroup[];
}
