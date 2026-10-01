import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '../../../lib/apiBase.ts';
import type { HeatmapMarket, HeatmapTile } from '../types.ts';

interface ResourceState<T> {
  data: T;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Mirrors `features/finance/hooks/useFinanceApi.ts`'s fetch pattern: one
 * useState+useEffect+axios wrapper, no react-query in this repo. A request
 * counter keeps a slow reply for one market from landing under another, and
 * the previous market's tiles are dropped as soon as the market changes.
 */
export function useHeatmap(market: HeatmapMarket = 'us'): ResourceState<HeatmapTile[]> {
  const [data, setData] = useState<HeatmapTile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);
  const loadedMarket = useRef<HeatmapMarket | null>(null);

  const refetch = useCallback(async () => {
    const requestId = ++latestRequest.current;
    // Another market's tiles must not sit under this market's selection while it loads.
    if (loadedMarket.current !== market) setData([]);
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<HeatmapTile[]>(`${API_BASE_URL}/heatmap`, { params: { market } });
      if (requestId !== latestRequest.current) return;
      loadedMarket.current = market;
      setData(response.data);
    } catch {
      if (requestId !== latestRequest.current) return;
      setError('No se pudo cargar el mapa de mercado.');
    } finally {
      if (requestId === latestRequest.current) setLoading(false);
    }
  }, [market]);

  useEffect(() => {
    const requests = latestRequest;
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
      requests.current += 1; // invalidate any in-flight request
    };
  }, [refetch]);

  return { data, loading, error, refetch };
}
