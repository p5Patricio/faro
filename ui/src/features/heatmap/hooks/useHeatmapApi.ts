import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '../../../lib/apiBase.ts';
import type { HeatmapTile } from '../types.ts';

interface ResourceState<T> {
  data: T;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Mirrors `features/finance/hooks/useFinanceApi.ts`'s fetch pattern: one
 * useState+useEffect+axios wrapper, no react-query in this repo.
 */
export function useHeatmap(market = 'us'): ResourceState<HeatmapTile[]> {
  const [data, setData] = useState<HeatmapTile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<HeatmapTile[]>(`${API_BASE_URL}/heatmap`, { params: { market } });
      setData(response.data);
    } catch {
      setError('No se pudo cargar el mapa de mercado.');
    } finally {
      setLoading(false);
    }
  }, [market]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
    };
  }, [refetch]);

  return { data, loading, error, refetch };
}
