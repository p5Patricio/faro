import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { formatCents } from '../lib/format.ts';
import { NetWorthPanel } from './NetWorthPanel.tsx';
import type { NetWorthSnapshot } from '../types.ts';

vi.mock('axios');

// A mixed-currency worksheet whose FIRST item is foreign: the old panel took
// the currency of `items[0]` for the whole total, so it would have labelled
// this MXN figure as USD.
const MIXED_SNAPSHOT: NetWorthSnapshot = {
  id: 'snap-1',
  snapshot_date: '2026-09-15',
  total_assets_cents: 275000,
  total_liabilities_cents: 30000,
  net_worth_cents: 245000,
  items: [
    {
      is_asset: true,
      label: 'Dolares',
      item_type: 'cash',
      amount_cents: 10000,
      currency: 'USD',
      fx_rate_to_base: 17.5,
      amount_base_cents: 175000,
    },
    {
      is_asset: true,
      label: 'Efectivo',
      item_type: 'cash',
      amount_cents: 100000,
      currency: 'MXN',
      fx_rate_to_base: 1,
      amount_base_cents: 100000,
    },
    {
      is_asset: false,
      label: 'Tarjeta',
      item_type: 'credit_card',
      amount_cents: 30000,
      currency: 'MXN',
      fx_rate_to_base: 1,
      amount_base_cents: 30000,
    },
  ],
};

function renderPanel(snapshots: NetWorthSnapshot[] = []) {
  return render(<NetWorthPanel snapshots={snapshots} onSaved={() => {}} />);
}

// Testing Library collapses whitespace in the DOM text but not in the string
// it is matched against, and es-MX puts a no-break space inside "USD 100.00".
const asRenderedText = (value: string) => value.replace(/\s+/g, ' ');

describe('NetWorthPanel base-currency totals', () => {
  it('formats the net worth total in the base currency, not the first item currency', () => {
    renderPanel([MIXED_SNAPSHOT]);

    expect(screen.getByText(asRenderedText(formatCents(245000, 'MXN')))).toBeInTheDocument();
    expect(screen.queryByText(asRenderedText(formatCents(245000, 'USD')))).not.toBeInTheDocument();
  });

  it('shows a foreign item in its own currency with its base equivalent underneath', () => {
    renderPanel([MIXED_SNAPSHOT]);

    expect(screen.getByText(asRenderedText(formatCents(10000, 'USD')))).toBeInTheDocument();
    expect(screen.getByText(asRenderedText(`≈ ${formatCents(175000, 'MXN')}`))).toBeInTheDocument();
  });
});

describe('NetWorthPanel form', () => {
  beforeEach(() => {
    vi.mocked(axios.put).mockReset();
    vi.mocked(axios.put).mockResolvedValue({ data: MIXED_SNAPSHOT });
  });

  it('defaults each item to the base currency and shows a rate field only for a foreign one', async () => {
    const user = userEvent.setup();
    renderPanel();

    const currency = screen.getByLabelText('Moneda');
    expect(currency).toHaveValue('MXN');
    expect(screen.queryByLabelText(/Tipo de cambio/)).not.toBeInTheDocument();

    await user.selectOptions(currency, 'USD');

    expect(screen.getByLabelText(/Tipo de cambio a MXN/)).toBeInTheDocument();
  });

  it('sends the rate with a foreign item and none with a base item', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByPlaceholderText(/Concepto/), 'Dolares');
    await user.type(screen.getByPlaceholderText('Monto'), '100');
    await user.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await user.type(screen.getByLabelText(/Tipo de cambio a MXN/), '17.5');
    await user.click(screen.getByRole('button', { name: 'Guardar corte' }));

    expect(axios.put).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(axios.put).mock.calls[0][1] as { items: Array<Record<string, unknown>> };
    expect(payload.items).toHaveLength(1);
    expect(payload.items[0]).toMatchObject({ currency: 'USD', amount_cents: 10000, fx_rate_to_base: 17.5 });
  });

  it('does not save a foreign item that has no rate', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByPlaceholderText(/Concepto/), 'Dolares');
    await user.type(screen.getByPlaceholderText('Monto'), '100');
    await user.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await user.click(screen.getByRole('button', { name: 'Guardar corte' }));

    expect(axios.put).not.toHaveBeenCalled();
    expect(screen.getByText(/tipo de cambio a MXN de cada concepto/)).toBeInTheDocument();
  });
});
