import { useCallback, useState } from 'react';

const RECENTS_KEY = 'faro:asset-recents';
const PINS_KEY = 'faro:asset-pins';
const MAX_RECENTS = 6;

function readList(key: string): string[] {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function writeList(key: string, value: string[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode / disabled storage — the feature just degrades */
  }
}

export interface AssetMemory {
  recents: string[];
  pins: string[];
  remember: (ticker: string) => void;
  togglePin: (ticker: string) => void;
}

/** Recently viewed + pinned tickers, persisted per browser via localStorage. */
export function useAssetMemory(): AssetMemory {
  const [recents, setRecents] = useState<string[]>(() => readList(RECENTS_KEY));
  const [pins, setPins] = useState<string[]>(() => readList(PINS_KEY));

  const remember = useCallback((ticker: string) => {
    setRecents((current) => {
      const next = [ticker, ...current.filter((t) => t !== ticker)].slice(0, MAX_RECENTS);
      writeList(RECENTS_KEY, next);
      return next;
    });
  }, []);

  const togglePin = useCallback((ticker: string) => {
    setPins((current) => {
      const next = current.includes(ticker)
        ? current.filter((t) => t !== ticker)
        : [...current, ticker];
      writeList(PINS_KEY, next);
      return next;
    });
  }, []);

  return { recents, pins, remember, togglePin };
}
