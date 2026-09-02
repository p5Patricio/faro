import { describe, expect, it } from 'vitest';
import { isSubsequence, matchScore } from './fuzzy.ts';

describe('isSubsequence', () => {
  it('accepts in-order gapped matches', () => {
    expect(isSubsequence('abc', 'aXbXc')).toBe(true);
    expect(isSubsequence('', 'anything')).toBe(true);
  });
  it('rejects out-of-order or missing chars', () => {
    expect(isSubsequence('cba', 'abc')).toBe(false);
    expect(isSubsequence('abcd', 'abc')).toBe(false);
  });
});

describe('matchScore', () => {
  it('returns 0 for an empty query and -1 for no match', () => {
    expect(matchScore('', 'AAPL', 'Apple')).toBe(0);
    expect(matchScore('zzz', 'AAPL', 'Apple')).toBe(-1);
  });

  it('ranks exact ticker > ticker prefix > name prefix > substring', () => {
    const exact = matchScore('aapl', 'AAPL', 'Apple Inc.');
    const tickerPrefix = matchScore('aap', 'AAPL', 'Apple Inc.');
    const namePrefix = matchScore('app', 'AAPL', 'Apple Inc.');
    const substring = matchScore('ppl', 'AAPL', 'Apple Inc.');

    expect(exact).toBeGreaterThan(tickerPrefix);
    expect(tickerPrefix).toBeGreaterThan(namePrefix);
    expect(namePrefix).toBeGreaterThan(substring);
    expect(substring).toBeGreaterThan(0);
  });

  it('is case-insensitive and trims the query', () => {
    expect(matchScore('  NvDa ', 'NVDA', 'Nvidia')).toBe(matchScore('nvda', 'NVDA', 'Nvidia'));
  });

  it('matches on the company name when the ticker does not', () => {
    expect(matchScore('tesla', 'TSLA', 'Tesla, Inc.')).toBeGreaterThan(0);
  });
});
