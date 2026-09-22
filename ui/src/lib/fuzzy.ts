/**
 * Tiny ranking helper for the asset command palette. Higher score = better
 * match; a negative score means "no match". Exact ticker > ticker prefix >
 * name prefix > substring > subsequence, with shorter matches winning ties.
 */
export function matchScore(query: string, ticker: string, name: string): number {
  const q = query.toLowerCase().trim();
  if (!q) return 0;
  const t = ticker.toLowerCase();
  const n = name.toLowerCase();
  if (t === q) return 1000;
  if (t.startsWith(q)) return 850 - t.length;
  if (n.startsWith(q)) return 650 - n.length;
  if (t.includes(q)) return 450;
  if (n.includes(q)) return 320;
  if (isSubsequence(q, t)) return 180;
  if (isSubsequence(q, n)) return 120;
  return -1;
}

export function isSubsequence(needle: string, haystack: string): boolean {
  let i = 0;
  for (let j = 0; j < haystack.length && i < needle.length; j += 1) {
    if (haystack[j] === needle[i]) i += 1;
  }
  return i === needle.length;
}
