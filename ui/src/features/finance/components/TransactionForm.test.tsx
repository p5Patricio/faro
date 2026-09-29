import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TransactionForm } from './TransactionForm.tsx';
import type { FinanceAccount, FinanceCategory, FinanceTransaction } from '../types.ts';

vi.mock('axios');

const CATEGORIES: FinanceCategory[] = [
  { id: 'cat-food', slug: 'alimentacion', name: 'Alimentacion', kind: 'expense', budget_bucket: 'necesidad' },
];

const ACCOUNTS: FinanceAccount[] = [
  { id: 'acc-mxn', name: 'Efectivo', account_type: 'cash', currency: 'MXN' },
  { id: 'acc-usd', name: 'Dolares', account_type: 'cash', currency: 'USD' },
];

const FX_LABEL = /Tipo de cambio a MXN/;

const USD_TRANSACTION: FinanceTransaction = {
  id: 'tx-1',
  client_id: 'client-1',
  account_id: 'acc-usd',
  category_id: 'cat-food',
  kind: 'expense',
  amount_cents: 5000,
  currency: 'USD',
  fx_rate_to_base: 17.5,
  amount_base_cents: 87500,
  occurred_at: '2026-09-10T12:00:00.000Z',
  source: 'ui',
};

function renderForm(props: Partial<Parameters<typeof TransactionForm>[0]> = {}) {
  return render(
    <TransactionForm categories={CATEGORIES} accounts={ACCOUNTS} onSaved={() => {}} {...props} />,
  );
}

async function fillCommonFields(user: ReturnType<typeof userEvent.setup>, accountId: string, amount: string) {
  await user.selectOptions(screen.getByLabelText('Categoría'), 'cat-food');
  await user.selectOptions(screen.getByLabelText('Cuenta'), accountId);
  await user.type(screen.getByLabelText(/^Monto/), amount);
}

describe('TransactionForm currency handling', () => {
  beforeEach(() => {
    vi.mocked(axios.put).mockReset();
    vi.mocked(axios.put).mockResolvedValue({ data: USD_TRANSACTION });
  });

  it('shows no exchange-rate field for a base-currency account', async () => {
    const user = userEvent.setup();
    renderForm();

    await user.selectOptions(screen.getByLabelText('Cuenta'), 'acc-mxn');

    expect(screen.queryByLabelText(FX_LABEL)).not.toBeInTheDocument();
    expect(screen.getByText('MXN', { selector: 'span' })).toBeInTheDocument();
  });

  it('requires an exchange rate once a non-base account is selected', async () => {
    const user = userEvent.setup();
    renderForm();

    await user.selectOptions(screen.getByLabelText('Cuenta'), 'acc-usd');

    expect(screen.getByLabelText(FX_LABEL)).toBeRequired();
    expect(screen.getByLabelText(/^Monto \(USD\)/)).toBeInTheDocument();
  });

  it("sends the account's currency and the rate for a non-base transaction", async () => {
    const user = userEvent.setup();
    renderForm();

    await fillCommonFields(user, 'acc-usd', '50');
    await user.type(screen.getByLabelText(FX_LABEL), '17.5');
    await user.click(screen.getByRole('button', { name: 'Agregar transacción' }));

    expect(axios.put).toHaveBeenCalledTimes(1);
    expect(axios.put).toHaveBeenCalledWith(
      expect.stringContaining('/finance/transactions'),
      expect.objectContaining({
        account_id: 'acc-usd',
        currency: 'USD',
        amount_cents: 5000,
        fx_rate_to_base: 17.5,
      }),
    );
  });

  it('does not send a rate for a base-currency transaction', async () => {
    const user = userEvent.setup();
    renderForm();

    await fillCommonFields(user, 'acc-mxn', '150');
    await user.click(screen.getByRole('button', { name: 'Agregar transacción' }));

    const payload = vi.mocked(axios.put).mock.calls[0][1] as Record<string, unknown>;
    expect(payload.currency).toBe('MXN');
    expect(payload.amount_cents).toBe(15000);
    expect(payload).not.toHaveProperty('fx_rate_to_base');
  });

  it('refuses to save a non-base transaction whose rate is not greater than zero', async () => {
    const user = userEvent.setup();
    renderForm();

    await fillCommonFields(user, 'acc-usd', '50');
    await user.type(screen.getByLabelText(FX_LABEL), '0');
    await user.click(screen.getByRole('button', { name: 'Agregar transacción' }));

    expect(axios.put).not.toHaveBeenCalled();
    expect(screen.getByText(/mayor que cero/)).toBeInTheDocument();
  });

  it('keeps the transaction currency and its rate when editing, and only offers accounts in that currency', async () => {
    const user = userEvent.setup();
    renderForm({ initial: USD_TRANSACTION });

    const accountOptions = screen.getAllByRole('option').map((option) => option.textContent);
    expect(accountOptions).toContain('Dolares (USD)');
    expect(accountOptions).not.toContain('Efectivo (MXN)');
    expect(screen.getByLabelText(FX_LABEL)).toHaveValue(17.5);

    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));

    expect(axios.put).toHaveBeenCalledWith(
      expect.stringContaining('/finance/transactions'),
      expect.objectContaining({ client_id: 'client-1', currency: 'USD', fx_rate_to_base: 17.5 }),
    );
  });
});
