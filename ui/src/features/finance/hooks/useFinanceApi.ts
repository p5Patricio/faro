import { useCallback, useEffect, useState } from 'react';
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

/**
 * One small useState+useEffect+axios wrapper per GET resource — mirrors
 * `App.tsx`'s own imperative fetch style (no react-query in this repo).
 */

export function useFinanceSummary(month: string): ResourceState<FinanceSummary | null> {
  const [data, setData] = useState<FinanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceSummary>(`${FINANCE_BASE_URL}/summary`, { params: { month } });
      setData(response.data);
    } catch {
      setError('No se pudo cargar el resumen del mes.');
    } finally {
      setLoading(false);
    }
  }, [month]);

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

export function useFinanceCategories(): ResourceState<FinanceCategory[]> {
  const [data, setData] = useState<FinanceCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceCategory[]>(`${FINANCE_BASE_URL}/categories`);
      setData(response.data);
    } catch {
      setError('No se pudieron cargar las categorías.');
    } finally {
      setLoading(false);
    }
  }, []);

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

export function useFinanceAccounts(): ResourceState<FinanceAccount[]> {
  const [data, setData] = useState<FinanceAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceAccount[]>(`${FINANCE_BASE_URL}/accounts`);
      setData(response.data);
    } catch {
      setError('No se pudieron cargar las cuentas.');
    } finally {
      setLoading(false);
    }
  }, []);

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

export function useFinanceTransactions(filters: TransactionFilters = {}): ResourceState<FinanceTransaction[]> {
  const { month, category_id: categoryId, account_id: accountId, limit } = filters;
  const [data, setData] = useState<FinanceTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceTransaction[]>(`${FINANCE_BASE_URL}/transactions`, {
        params: { month, category_id: categoryId, account_id: accountId, limit },
      });
      setData(response.data);
    } catch {
      setError('No se pudieron cargar las transacciones.');
    } finally {
      setLoading(false);
    }
  }, [month, categoryId, accountId, limit]);

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

export function useFinanceBudgets(month: string): ResourceState<FinanceBudget[]> {
  const [data, setData] = useState<FinanceBudget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceBudget[]>(`${FINANCE_BASE_URL}/budgets`, { params: { month } });
      setData(response.data);
    } catch {
      setError('No se pudieron cargar los presupuestos.');
    } finally {
      setLoading(false);
    }
  }, [month]);

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

export function useFinanceNetWorth(limit = 24): ResourceState<NetWorthSnapshot[]> {
  const [data, setData] = useState<NetWorthSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<NetWorthSnapshot[]>(`${FINANCE_BASE_URL}/net-worth`, { params: { limit } });
      setData(response.data);
    } catch {
      setError('No se pudieron cargar los patrimonios.');
    } finally {
      setLoading(false);
    }
  }, [limit]);

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

export function useFinanceRecurringBills(includeInactive = false): ResourceState<RecurringBill[]> {
  const [data, setData] = useState<RecurringBill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<RecurringBill[]>(`${FINANCE_BASE_URL}/recurring-bills`, {
        params: { include_inactive: includeInactive },
      });
      setData(response.data);
    } catch {
      setError('No se pudieron cargar los pagos recurrentes.');
    } finally {
      setLoading(false);
    }
  }, [includeInactive]);

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

export function useFinanceGoals(): ResourceState<FinanceGoal[]> {
  const [data, setData] = useState<FinanceGoal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<FinanceGoal[]>(`${FINANCE_BASE_URL}/goals`);
      setData(response.data);
    } catch {
      setError('No se pudieron cargar las metas.');
    } finally {
      setLoading(false);
    }
  }, []);

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
