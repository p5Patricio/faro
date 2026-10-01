import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '../../lib/apiBase.ts';
import type { MarketsOverviewResponse } from './types.ts';

interface MarketsOverviewState {
  data: MarketsOverviewResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Same fetch shape as `features/heatmap/hooks/useHeatmapApi.ts` (useState +
 * useEffect + axios, no react-query), plus a request counter so a slow,
 * superseded response (or one that lands after unmount) never overwrites
 * newer state.
 */
export function useMarketsOverview(): MarketsOverviewState {
  const [data, setData] = useState<MarketsOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);

  const refetch = useCallback(async () => {
    const requestId = ++latestRequest.current;
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<MarketsOverviewResponse>(`${API_BASE_URL}/markets/overview`);
      if (requestId !== latestRequest.current) return;
      setData(response.data);
    } catch {
      if (requestId !== latestRequest.current) return;
      setError('No se pudo cargar el panorama de mercados.');
    } finally {
      if (requestId === latestRequest.current) setLoading(false);
    }
  }, []);

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
