import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TransactionsPanel } from './TransactionsPanel.tsx';
import type { FinanceTransaction } from '../types.ts';

vi.mock('axios');

const TRANSACTION: FinanceTransaction = {
  id: 'tx-1',
  client_id: 'client-1',
  account_id: 'acc-1',
  category_id: null,
  kind: 'expense',
  amount_cents: 12500,
  currency: 'MXN',
  occurred_at: '2026-09-10T18:00:00.000Z',
  merchant: 'Cafe',
  notes: null,
  source: 'ui',
} as FinanceTransaction;

describe('TransactionsPanel delete', () => {
  beforeEach(() => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(axios.put).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('says so next to the action when the delete fails, and does not refresh', async () => {
    vi.mocked(axios.put).mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    const onChanged = vi.fn();
    render(
      <TransactionsPanel transactions={[TRANSACTION]} categories={[]} accounts={[]} onChanged={onChanged} />,
    );

    await user.click(screen.getByRole('button', { name: 'Eliminar movimiento Cafe' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo eliminar el movimiento');
    expect(onChanged).not.toHaveBeenCalled();
  });
});
