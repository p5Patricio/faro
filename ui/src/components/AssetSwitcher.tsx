import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { Check, ChevronsUpDown, CornerDownLeft, Search, Star, X } from 'lucide-react';
import { cn } from '../lib/cn.ts';
import { matchScore } from '../lib/fuzzy.ts';
import type { AssetMemory } from '../hooks/useAssetMemory.ts';

export interface SwitchableAsset {
  id: string;
  ticker: string;
  name?: string;
  asset_class?: string;
}

const CLASS_LABELS: Record<string, string> = {
  crypto: 'Cripto',
  stock: 'Acciones',
  etf: 'ETFs',
};

function classLabel(assetClass?: string): string {
  if (!assetClass) return 'Otros';
  return CLASS_LABELS[assetClass] ?? assetClass[0].toUpperCase() + assetClass.slice(1);
}

interface AssetSwitcherProps {
  assets: SwitchableAsset[];
  selectedTicker: string;
  onSelect: (ticker: string) => void;
  memory: AssetMemory;
}

export function AssetSwitcher({ assets, selectedTicker, onSelect, memory }: AssetSwitcherProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const selected = useMemo(
    () => assets.find((a) => a.ticker === selectedTicker),
    [assets, selectedTicker],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-3 rounded-lg border border-hairline/70 bg-inset px-3 py-2.5 text-left transition hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-cobalt/50"
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-slate-50">
              {selected?.ticker ?? 'Elegí un activo'}
            </span>
            {selected?.asset_class ? (
              <span className="rounded bg-hairline/50 px-1.5 py-0.5 text-xs uppercase tracking-wide text-slate-400">
                {classLabel(selected.asset_class)}
              </span>
            ) : null}
          </span>
          <span className="truncate text-xs text-slate-500">{selected?.name ?? `${assets.length} disponibles`}</span>
        </span>
        <kbd className="hidden shrink-0 items-center gap-1 rounded border border-hairline/70 bg-surface px-1.5 py-0.5 font-mono text-xs text-slate-500 sm:inline-flex">
          <span className="text-sm leading-none">⌘</span>K
        </kbd>
        <ChevronsUpDown aria-hidden="true" className="h-4 w-4 shrink-0 text-slate-500" />
      </button>

      {open ? (
        <AssetPalette
          assets={assets}
          selectedTicker={selectedTicker}
          memory={memory}
          onClose={close}
          onPick={(ticker) => {
            onSelect(ticker);
            memory.remember(ticker);
            close();
          }}
        />
      ) : null}
    </>
  );
}

interface AssetPaletteProps {
  assets: SwitchableAsset[];
  selectedTicker: string;
  memory: AssetMemory;
  onClose: () => void;
  onPick: (ticker: string) => void;
}

function AssetPalette({ assets, selectedTicker, memory, onClose, onPick }: AssetPaletteProps) {
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [prevQuery, setPrevQuery] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Reset the keyboard highlight to the top whenever the search text changes
  // (React's "adjust state during render" pattern, not an effect).
  if (query !== prevQuery) {
    setPrevQuery(query);
    setActiveIndex(0);
  }

  const byTicker = useMemo(() => {
    const map = new Map<string, SwitchableAsset>();
    for (const a of assets) map.set(a.ticker, a);
    return map;
  }, [assets]);

  // Ordered, grouped result set. When there is no query we surface pinned +
  // recent up top, then the full list by class.
  const groups = useMemo(() => {
    const q = query.trim();
    if (!q) {
      const pinned = memory.pins.map((t) => byTicker.get(t)).filter(isAsset);
      const recent = memory.recents
        .map((t) => byTicker.get(t))
        .filter(isAsset)
        .filter((a) => !memory.pins.includes(a.ticker));
      const rest = groupByClass(assets);
      return [
        ...(pinned.length ? [{ label: 'Fijados', items: pinned }] : []),
        ...(recent.length ? [{ label: 'Recientes', items: recent }] : []),
        ...rest,
      ];
    }
    const scored = assets
      .map((a) => ({ a, s: matchScore(q, a.ticker, a.name ?? '') }))
      .filter((x) => x.s >= 0)
      .sort((x, y) => y.s - x.s)
      .map((x) => x.a);
    return scored.length ? [{ label: `Resultados (${scored.length})`, items: scored }] : [];
  }, [assets, byTicker, memory.pins, memory.recents, query]);

  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    el?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((i) => (flat.length ? (i + 1) % flat.length : 0));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((i) => (flat.length ? (i - 1 + flat.length) % flat.length : 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const pick = flat[activeIndex];
      if (pick) onPick(pick.ticker);
    }
  };

  let runningIndex = -1;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-canvas/70 p-4 pt-[10vh] backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Cambiar de activo"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="flex max-h-[70vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-hairline/70 bg-surface shadow-2xl"
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-2 border-b border-hairline/60 px-3">
          <Search aria-hidden="true" className="h-4 w-4 shrink-0 text-slate-500" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Buscar por ticker o nombre…"
            className="h-11 w-full bg-transparent text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
            aria-label="Buscar activo"
            role="combobox"
            aria-expanded="true"
            aria-controls="asset-palette-list"
            autoComplete="off"
            spellCheck={false}
          />
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-500 transition hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-cobalt/50"
            aria-label="Cerrar"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>

        <div id="asset-palette-list" ref={listRef} role="listbox" className="min-h-0 flex-1 overflow-y-auto py-1">
          {flat.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-slate-500">
              Nada coincide con “{query}”.
            </p>
          ) : (
            groups.map((group) => (
              <div key={group.label} className="py-1">
                <p className="px-3 py-1 text-xs font-medium uppercase tracking-wide text-slate-500">
                  {group.label}
                </p>
                {group.items.map((asset) => {
                  runningIndex += 1;
                  const index = runningIndex;
                  const active = index === activeIndex;
                  const isSelected = asset.ticker === selectedTicker;
                  const isPinned = memory.pins.includes(asset.ticker);
                  return (
                    <div
                      key={asset.id}
                      data-active={active}
                      role="option"
                      aria-selected={isSelected}
                      onMouseMove={() => setActiveIndex(index)}
                      onClick={() => onPick(asset.ticker)}
                      className={cn(
                        'mx-1 flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2',
                        active ? 'bg-cobalt/15' : 'hover:bg-white/[0.04]',
                      )}
                    >
                      <span className="font-mono text-sm font-semibold text-slate-100">{asset.ticker}</span>
                      <span className="min-w-0 flex-1 truncate text-xs text-slate-400">
                        {asset.name ?? 'Sin nombre'}
                      </span>
                      {isSelected ? (
                        <Check aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-beam" />
                      ) : null}
                      <span className="shrink-0 rounded bg-hairline/50 px-1.5 py-0.5 text-xs uppercase tracking-wide text-slate-500">
                        {classLabel(asset.asset_class)}
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          memory.togglePin(asset.ticker);
                        }}
                        className="shrink-0 rounded p-1 text-slate-600 transition hover:text-beam focus:outline-none focus:ring-2 focus:ring-cobalt/50"
                        aria-label={isPinned ? `Dejar de fijar ${asset.ticker}` : `Fijar ${asset.ticker}`}
                        aria-pressed={isPinned}
                      >
                        <Star
                          aria-hidden="true"
                          className={cn('h-3.5 w-3.5', isPinned && 'fill-beam text-beam')}
                        />
                      </button>
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div className="flex items-center gap-4 border-t border-hairline/60 px-3 py-2 text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <kbd className="rounded border border-hairline/70 px-1">↑</kbd>
            <kbd className="rounded border border-hairline/70 px-1">↓</kbd>
            navegar
          </span>
          <span className="flex items-center gap-1">
            <CornerDownLeft aria-hidden="true" className="h-3 w-3" /> elegir
          </span>
          <span className="flex items-center gap-1">
            <kbd className="rounded border border-hairline/70 px-1">esc</kbd> cerrar
          </span>
        </div>
      </div>
    </div>
  );
}

interface WatchlistProps {
  assets: SwitchableAsset[];
  selectedTicker: string;
  onSelect: (ticker: string) => void;
  memory: AssetMemory;
}

/** Horizontal quick-switch strip: pinned first, then recent. */
export function Watchlist({ assets, selectedTicker, onSelect, memory }: WatchlistProps) {
  const byTicker = useMemo(() => {
    const map = new Map<string, SwitchableAsset>();
    for (const a of assets) map.set(a.ticker, a);
    return map;
  }, [assets]);

  const chips = useMemo(() => {
    const seen = new Set<string>();
    const ordered: SwitchableAsset[] = [];
    for (const ticker of [...memory.pins, ...memory.recents]) {
      if (seen.has(ticker)) continue;
      const asset = byTicker.get(ticker);
      if (asset) {
        ordered.push(asset);
        seen.add(ticker);
      }
    }
    return ordered;
  }, [byTicker, memory.pins, memory.recents]);

  if (chips.length === 0) return null;

  return (
    <div className="flex items-center gap-2 overflow-x-auto pb-1" aria-label="Accesos rápidos de activos">
      {chips.map((asset) => {
        const active = asset.ticker === selectedTicker;
        const pinned = memory.pins.includes(asset.ticker);
        return (
          <button
            key={asset.id}
            type="button"
            onClick={() => {
              onSelect(asset.ticker);
              memory.remember(asset.ticker);
            }}
            aria-current={active ? 'true' : undefined}
            className={cn(
              'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-xs transition focus:outline-none focus:ring-2 focus:ring-cobalt/50',
              active
                ? 'border-beam/50 bg-beam/10 text-beam'
                : 'border-hairline/70 bg-inset text-slate-300 hover:bg-white/5',
            )}
          >
            {pinned ? <Star aria-hidden="true" className="h-3 w-3 fill-current" /> : null}
            {asset.ticker}
          </button>
        );
      })}
    </div>
  );
}

function isAsset(value: SwitchableAsset | undefined): value is SwitchableAsset {
  return value !== undefined;
}

function groupByClass(assets: SwitchableAsset[]): { label: string; items: SwitchableAsset[] }[] {
  const buckets = new Map<string, SwitchableAsset[]>();
  for (const asset of assets) {
    const key = classLabel(asset.asset_class);
    const list = buckets.get(key) ?? [];
    list.push(asset);
    buckets.set(key, list);
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([label, items]) => ({
      label,
      items: items.sort((a, b) => a.ticker.localeCompare(b.ticker)),
    }));
}
