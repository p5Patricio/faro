// Mirrors the `${API_BASE_URL}/heatmap?market=us|mx|ca` contract (api/routers/heatmap.py).

export type HeatmapMarket = 'us' | 'mx' | 'ca';

export interface HeatmapTile {
  ticker: string;
  name: string;
  sector: string;
  /**
   * Real market cap when `market_cap_estimated` is false. When it is true
   * there is no sourced figure yet -- see the docstring on
   * `_placeholder_market_cap` in api/routers/heatmap.py: it is a
   * deterministic per-ticker estimate (real price x a synthetic share
   * count), used only to give the treemap varied tile sizes. Always label
   * it "estimada" in that case (no "as of <date>" claim).
   */
  market_cap: number;
  change_pct: number;
  price: number;
  /** Currency of `price` and `market_cap`. */
  currency: 'USD' | 'MXN' | 'CAD';
  /** True only while no real market-cap value exists for this ticker. */
  market_cap_estimated: boolean;
}
