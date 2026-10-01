import type { NetWorthSnapshot } from '../types.ts';

// Asset types that are clearly cash-like. Mirrors LIQUID_ITEM_TYPES in
// brain/finance/liquidity.py; `item_type` is free text, so matching ignores
// case and surrounding spaces.
const LIQUID_ITEM_TYPES: ReadonlySet<string> = new Set(['cash', 'checking', 'savings', 'efectivo', 'ahorro']);

/** Whether a NEW asset of this type starts out checked as liquid. */
export function defaultIsLiquid(itemType: string): boolean {
  return LIQUID_ITEM_TYPES.has(itemType.trim().toLowerCase());
}

/**
 * True when the snapshot says nothing yet about which assets are liquid: the
 * database cannot store the flags, or no asset is marked liquid while some
 * asset is still unclassified. Mirrors `is_liquidity_classified` in the API,
 * so "every asset classified, none liquid" is a real answer, not a gap.
 */
export function isLiquidityUnclassified(snapshot: NetWorthSnapshot): boolean {
  if (snapshot.liquidity_flags_available === false) return true;
  return (snapshot.liquid_items_count ?? 0) === 0 && (snapshot.unclassified_items_count ?? 0) > 0;
}
