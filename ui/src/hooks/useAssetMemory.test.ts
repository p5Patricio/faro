import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { useAssetMemory } from './useAssetMemory.ts';

beforeEach(() => window.localStorage.clear());

describe('useAssetMemory', () => {
  it('records recents newest-first, de-duped and capped at 6', () => {
    const { result } = renderHook(() => useAssetMemory());

    act(() => {
      for (const t of ['A', 'B', 'C', 'D', 'E', 'F', 'G']) result.current.remember(t);
      result.current.remember('B'); // re-visit moves it to the front
    });

    expect(result.current.recents).toEqual(['B', 'G', 'F', 'E', 'D', 'C']);
    expect(JSON.parse(window.localStorage.getItem('faro:asset-recents')!)).toEqual(result.current.recents);
  });

  it('toggles pins and persists them', () => {
    const { result } = renderHook(() => useAssetMemory());

    act(() => result.current.togglePin('AAPL'));
    expect(result.current.pins).toEqual(['AAPL']);

    act(() => result.current.togglePin('AAPL'));
    expect(result.current.pins).toEqual([]);
    expect(window.localStorage.getItem('faro:asset-pins')).toBe('[]');
  });

  it('hydrates from localStorage on mount', () => {
    window.localStorage.setItem('faro:asset-recents', JSON.stringify(['MSFT']));
    window.localStorage.setItem('faro:asset-pins', JSON.stringify(['NVDA']));

    const { result } = renderHook(() => useAssetMemory());

    expect(result.current.recents).toEqual(['MSFT']);
    expect(result.current.pins).toEqual(['NVDA']);
  });

  it('degrades gracefully when localStorage holds garbage', () => {
    window.localStorage.setItem('faro:asset-recents', 'not json');
    const { result } = renderHook(() => useAssetMemory());
    expect(result.current.recents).toEqual([]);
  });
});
