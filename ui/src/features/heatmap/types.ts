// Mirrors the `${API_BASE_URL}/heatmap` contract exactly (api/routers/heatmap.py).

export interface HeatmapTile {
  ticker: string;
  name: string;
  sector: string;
  /**
   * NOTE: not real market-cap data yet -- see the docstring on
   * `_placeholder_market_cap` in api/routers/heatmap.py. It is a
   * deterministic per-ticker estimate (real price x a synthetic share
   * count), used only to give the treemap varied tile sizes. Never render
   * it as if it were a sourced figure (e.g. no "as of <date>" claim).
   */
  market_cap: number;
  change_pct: number;
  price: number;
}
