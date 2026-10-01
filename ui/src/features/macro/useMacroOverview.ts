import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '../../lib/apiBase.ts';
import type { MacroOverviewResponse } from './types.ts';

interface MacroOverviewState {
  data: MacroOverviewResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Same fetch shape as `features/markets/useMarketsOverview.ts`: useState +
 * useEffect + axios, with a request counter so a slow, superseded response (or
 * one that lands after unmount) never overwrites newer state.
 */
export function useMacroOverview(): MacroOverviewState {
  const [data, setData] = useState<MacroOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);

  const refetch = useCallback(async () => {
    const requestId = ++latestRequest.current;
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<MacroOverviewResponse>(`${API_BASE_URL}/macro/overview`);
      if (requestId !== latestRequest.current) return;
      setData(response.data);
    } catch {
      if (requestId !== latestRequest.current) return;
      setError('No se pudieron cargar los datos macroeconómicos.');
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
