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
  liquid_assets_cents: 100000,
  liquid_items_count: 1,
  unclassified_items_count: 1,
  liquidity_flags_available: true,
  items: [
    {
      is_asset: true,
      label: 'Dolares',
      item_type: 'cash',
      amount_cents: 10000,
      currency: 'USD',
      fx_rate_to_base: 17.5,
      amount_base_cents: 175000,
      is_liquid: null,
    },
    {
      is_asset: true,
      label: 'Efectivo',
      item_type: 'cash',
      amount_cents: 100000,
      currency: 'MXN',
      fx_rate_to_base: 1,
      amount_base_cents: 100000,
      is_liquid: true,
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

describe('NetWorthPanel liquidity', () => {
  it('shows the net worth and the liquid assets side by side', () => {
    renderPanel([MIXED_SNAPSHOT]);

    expect(screen.getByText('Patrimonio neto')).toBeInTheDocument();
    expect(screen.getByText('Activos líquidos')).toBeInTheDocument();
    expect(screen.getByText('Patrimonio neto').parentElement).toHaveTextContent(asRenderedText(formatCents(245000, 'MXN')));
    expect(screen.getByText('Activos líquidos').parentElement).toHaveTextContent(asRenderedText(formatCents(100000, 'MXN')));
    expect(screen.queryByText(/Todavía no has marcado/)).not.toBeInTheDocument();
  });

  it('says no asset is classified yet, instead of showing a zero, while none is marked liquid', () => {
    renderPanel([{ ...MIXED_SNAPSHOT, liquid_assets_cents: 0, liquid_items_count: 0, unclassified_items_count: 2 }]);

    expect(screen.getByText('Activos líquidos').parentElement).toHaveTextContent('Sin clasificar');
    expect(screen.getByText(/Todavía no has marcado cuáles de tus activos son líquidos/)).toBeInTheDocument();
    expect(screen.queryByText(asRenderedText(formatCents(0, 'MXN')))).not.toBeInTheDocument();
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

  it('sends is_liquid with an asset, defaulted from its category until the user decides', async () => {
    const user = userEvent.setup();
    renderPanel();

    const liquid = screen.getByRole('checkbox', { name: /Líquido/ });
    expect(liquid).not.toBeChecked();

    await user.type(screen.getByPlaceholderText(/Concepto/), 'Cuenta');
    await user.type(screen.getByPlaceholderText('Monto'), '500');
    await user.clear(screen.getByPlaceholderText('Categoría'));
    await user.type(screen.getByPlaceholderText('Categoría'), 'savings');
    expect(liquid).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Guardar corte' }));

    const payload = vi.mocked(axios.put).mock.calls[0][1] as { items: Array<Record<string, unknown>> };
    expect(payload.items[0]).toMatchObject({ item_type: 'savings', is_liquid: true });
  });

  it('sends the checkbox choice even when it goes against the category default, and none for a liability', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByPlaceholderText(/Concepto/), 'Casa');
    await user.type(screen.getByPlaceholderText('Monto'), '900');
    await user.click(screen.getByRole('checkbox', { name: /Líquido/ }));
    await user.click(screen.getByRole('button', { name: /Agregar pasivo/ }));
    await user.type(screen.getAllByPlaceholderText(/Concepto/)[1], 'Tarjeta');
    await user.type(screen.getAllByPlaceholderText('Monto')[1], '100');
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Guardar corte' }));

    const payload = vi.mocked(axios.put).mock.calls[0][1] as { items: Array<Record<string, unknown>> };
    expect(payload.items[0]).toMatchObject({ is_asset: true, is_liquid: true });
    expect(payload.items[1]).not.toHaveProperty('is_liquid');
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
