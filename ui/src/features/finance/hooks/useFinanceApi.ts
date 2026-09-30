import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '../../../lib/apiBase.ts';
import type {
  BudgetPayload,
  FinanceAccount,
  FinanceBudget,
  FinanceCategory,
  FinanceGoal,
  FinanceSummary,
  FinanceTransaction,
  GoalPayload,
  NetWorthPayload,
  NetWorthSnapshot,
  RecurringBill,
  RecurringBillPayment,
  RecurringBillPaymentPayload,
  RecurringBillPayload,
  TransactionFilters,
  TransactionPayload,
} from '../types.ts';

const FINANCE_BASE_URL = `${API_BASE_URL}/finance`;

interface ResourceState<T> {
  data: T;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

interface RequestGuard {
  /** Starts a request; the returned check is true only while no newer request has begun. */
  begin: () => () => boolean;
  /** Marks every in-flight request stale (inputs changed or the component unmounted). */
  invalidate: () => void;
}

/**
 * Sequence guard: responses can arrive out of order (flipping months quickly),
 * and only the latest request may write state, so a slow reply for month A never
 * lands under month B.
 */
function useRequestGuard(): RequestGuard {
  const latest = useRef(0);
  return useMemo(
    () => ({
      begin: () => {
        latest.current += 1;
        const id = latest.current;
        return () => id === latest.current;
      },
      invalidate: () => {
        latest.current += 1;
      },
    }),
    [],
  );
}

/**
 * One small useState+useEffect+axios wrapper per GET resource — mirrors
 * `App.tsx`'s own imperative fetch style (no react-query in this repo).
 */

export function useFinanceSummary(month: string): ResourceState<FinanceSummary | null> {
  const [data, setData] = useState<FinanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const guard = useRequestGuard();
  const loadedMonth = useRef<string | null>(null);

  const refetch = useCallback(async () => {
    const isCurrent = guard.begin();
    // Another month's figures must not sit under this month's heading while it loads.
    if (loadedMonth.current !== month) setData(null);
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceSummary>(`${FINANCE_BASE_URL}/summary`, { params: { month } });
      if (!isCurrent()) return;
      loadedMonth.current = month;
      setData(response.data);
    } catch {
      if (!isCurrent()) return;
      setError('No se pudo cargar el resumen del mes.');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [guard, month]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
      guard.invalidate();
    };
  }, [guard, refetch]);

  return { data, loading, error, refetch };
}

export function useFinanceCategories(): ResourceState<FinanceCategory[]> {
  const [data, setData] = useState<FinanceCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const guard = useRequestGuard();

  const refetch = useCallback(async () => {
    const isCurrent = guard.begin();
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceCategory[]>(`${FINANCE_BASE_URL}/categories`);
      if (!isCurrent()) return;
      setData(response.data);
    } catch {
      if (!isCurrent()) return;
      setError('No se pudieron cargar las categorías.');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [guard]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
      guard.invalidate();
    };
  }, [guard, refetch]);

  return { data, loading, error, refetch };
}

export function useFinanceAccounts(): ResourceState<FinanceAccount[]> {
  const [data, setData] = useState<FinanceAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const guard = useRequestGuard();

  const refetch = useCallback(async () => {
    const isCurrent = guard.begin();
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceAccount[]>(`${FINANCE_BASE_URL}/accounts`);
      if (!isCurrent()) return;
      setData(response.data);
    } catch {
      if (!isCurrent()) return;
      setError('No se pudieron cargar las cuentas.');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [guard]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
      guard.invalidate();
    };
  }, [guard, refetch]);

  return { data, loading, error, refetch };
}

export function useFinanceTransactions(filters: TransactionFilters = {}): ResourceState<FinanceTransaction[]> {
  const { month, category_id: categoryId, account_id: accountId, limit } = filters;
  const [data, setData] = useState<FinanceTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const guard = useRequestGuard();
  const loadedFilters = useRef<string | null>(null);

  const refetch = useCallback(async () => {
    const isCurrent = guard.begin();
    const filtersKey = JSON.stringify([month, categoryId, accountId, limit]);
    // Rows of other filters (another month) must not be shown while these load.
    if (loadedFilters.current !== filtersKey) setData([]);
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceTransaction[]>(`${FINANCE_BASE_URL}/transactions`, {
        params: { month, category_id: categoryId, account_id: accountId, limit },
      });
      if (!isCurrent()) return;
      loadedFilters.current = filtersKey;
      setData(response.data);
    } catch {
      if (!isCurrent()) return;
      setError('No se pudieron cargar las transacciones.');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [guard, month, categoryId, accountId, limit]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
      guard.invalidate();
    };
  }, [guard, refetch]);

  return { data, loading, error, refetch };
}

export function useFinanceNetWorth(limit = 24): ResourceState<NetWorthSnapshot[]> {
  const [data, setData] = useState<NetWorthSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const guard = useRequestGuard();

  const refetch = useCallback(async () => {
    const isCurrent = guard.begin();
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<NetWorthSnapshot[]>(`${FINANCE_BASE_URL}/net-worth`, { params: { limit } });
      if (!isCurrent()) return;
      setData(response.data);
    } catch {
      if (!isCurrent()) return;
      setError('No se pudieron cargar los patrimonios.');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [guard, limit]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
      guard.invalidate();
    };
  }, [guard, refetch]);

  return { data, loading, error, refetch };
}

export function useFinanceRecurringBills(includeInactive = false): ResourceState<RecurringBill[]> {
  const [data, setData] = useState<RecurringBill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const guard = useRequestGuard();

  const refetch = useCallback(async () => {
    const isCurrent = guard.begin();
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<RecurringBill[]>(`${FINANCE_BASE_URL}/recurring-bills`, {
        params: { include_inactive: includeInactive },
      });
      if (!isCurrent()) return;
      setData(response.data);
    } catch {
      if (!isCurrent()) return;
      setError('No se pudieron cargar los pagos recurrentes.');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [guard, includeInactive]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
      guard.invalidate();
    };
  }, [guard, refetch]);

  return { data, loading, error, refetch };
}

export function useFinanceGoals(): ResourceState<FinanceGoal[]> {
  const [data, setData] = useState<FinanceGoal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const guard = useRequestGuard();

  const refetch = useCallback(async () => {
    const isCurrent = guard.begin();
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceGoal[]>(`${FINANCE_BASE_URL}/goals`);
      if (!isCurrent()) return;
      setData(response.data);
    } catch {
      if (!isCurrent()) return;
      setError('No se pudieron cargar las metas.');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [guard]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void refetch();
    });
    return () => {
      disposed = true;
      guard.invalidate();
    };
  }, [guard, refetch]);

  return { data, loading, error, refetch };
}

// -- Mutations: plain async functions, called directly from forms ----------

export async function putTransaction(payload: TransactionPayload): Promise<FinanceTransaction> {
  const response = await axios.put<FinanceTransaction>(`${FINANCE_BASE_URL}/transactions`, payload);
  return response.data;
}

export async function putBudget(payload: BudgetPayload): Promise<FinanceBudget> {
  const response = await axios.put<FinanceBudget>(`${FINANCE_BASE_URL}/budgets`, payload);
  return response.data;
}

export async function putNetWorthSnapshot(payload: NetWorthPayload): Promise<NetWorthSnapshot> {
  const response = await axios.put<NetWorthSnapshot>(`${FINANCE_BASE_URL}/net-worth`, payload);
  return response.data;
}

export async function putRecurringBill(payload: RecurringBillPayload): Promise<RecurringBill> {
  const response = await axios.put<RecurringBill>(`${FINANCE_BASE_URL}/recurring-bills`, payload);
  return response.data;
}

export async function putRecurringBillPayment(
  payload: RecurringBillPaymentPayload,
): Promise<RecurringBillPayment> {
  const response = await axios.put<RecurringBillPayment>(`${FINANCE_BASE_URL}/recurring-bills/payments`, payload);
  return response.data;
}

export async function putGoal(payload: GoalPayload): Promise<FinanceGoal> {
  const response = await axios.put<FinanceGoal>(`${FINANCE_BASE_URL}/goals`, payload);
  return response.data;
}
