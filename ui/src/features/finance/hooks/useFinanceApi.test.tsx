import { act, renderHook, waitFor } from '@testing-library/react';
import axios from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useFinanceSummary } from './useFinanceApi.ts';
import type { FinanceSummary } from '../types.ts';

vi.mock('axios');

/** A GET whose response the test releases by hand, to control the arrival order. */
function deferredGet() {
  let resolve: (value: { data: FinanceSummary }) => void = () => {};
  const promise = new Promise<{ data: FinanceSummary }>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const summaryFor = (month: string) => ({ month }) as unknown as FinanceSummary;

describe('useFinanceSummary', () => {
  beforeEach(() => {
    vi.mocked(axios.get).mockReset();
  });

  it('ignores a slow response for a month the user already left', async () => {
    const monthA = deferredGet();
    const monthB = deferredGet();
    vi.mocked(axios.get).mockImplementation((_url, config) =>
      (config?.params as { month: string }).month === '2026-08' ? monthA.promise : monthB.promise,
    );

    const { result, rerender } = renderHook(({ month }) => useFinanceSummary(month), {
      initialProps: { month: '2026-08' },
    });
    await waitFor(() => expect(axios.get).toHaveBeenCalledTimes(1));

    rerender({ month: '2026-09' });
    await waitFor(() => expect(axios.get).toHaveBeenCalledTimes(2));

    // September answers first; August's late reply must not replace it.
    await act(async () => monthB.resolve({ data: summaryFor('2026-09') }));
    await act(async () => monthA.resolve({ data: summaryFor('2026-08') }));

    expect(result.current.data).toEqual(summaryFor('2026-09'));
    expect(result.current.loading).toBe(false);
  });
});
