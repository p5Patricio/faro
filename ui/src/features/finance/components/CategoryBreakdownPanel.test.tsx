import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { formatCents } from '../lib/format.ts';
import { CategoryBreakdownPanel } from './CategoryBreakdownPanel.tsx';
import type { CategoryBreakdownRow, FinanceCategory } from '../types.ts';

vi.mock('axios');

const FOOD: FinanceCategory = {
  id: 'cat-alimentacion',
  slug: 'alimentacion',
  name: 'Alimentacion',
  kind: 'expense',
  budget_bucket: 'necesidad',
  emoji: '🍽',
};

const BUDGETED: CategoryBreakdownRow = {
  category_id: 'cat-alimentacion',
  category_name: 'Alimentacion',
  slug: 'alimentacion',
  emoji: '🍽',
  bucket: 'necesidad',
  actual_cents: 200_000,
  budget_cents: 300_000,
};

const UNBUDGETED: CategoryBreakdownRow = {
  category_id: 'cat-entretenimiento',
  category_name: 'Entretenimiento',
  slug: 'entretenimiento',
  emoji: '🎬',
  bucket: 'deseo',
  actual_cents: 100_000,
  budget_cents: null,
};

const UNCATEGORIZED: CategoryBreakdownRow = {
  category_id: null,
  category_name: 'Sin categoría',
  slug: null,
  emoji: null,
  bucket: 'sin_categoria',
  actual_cents: 50_000,
  budget_cents: null,
};

function renderPanel(
  breakdown: CategoryBreakdownRow[],
  props: { loading?: boolean; error?: string | null; categories?: FinanceCategory[]; onSaved?: () => void } = {},
) {
  return render(
    <CategoryBreakdownPanel
      breakdown={breakdown}
      categories={props.categories ?? []}
      month="2026-09"
      loading={props.loading}
      error={props.error}
      onSaved={props.onSaved ?? (() => undefined)}
    />,
  );
}

describe('CategoryBreakdownPanel', () => {
  it('shows a budgeted category against its limit and an unbudgeted one with only its actual spend', () => {
    renderPanel([BUDGETED, UNBUDGETED]);

    expect(screen.getByText('Alimentacion')).toBeInTheDocument();
    expect(screen.getByText(formatCents(200_000))).toBeInTheDocument();
    expect(screen.getByText(`de ${formatCents(300_000)}`)).toBeInTheDocument();
    expect(screen.getByText('Entretenimiento')).toBeInTheDocument();
    expect(screen.getByText(formatCents(100_000))).toBeInTheDocument();
    expect(screen.getByText('Sin presupuesto')).toBeInTheDocument();
    expect(screen.queryByText('Excedido')).not.toBeInTheDocument();
  });

  it('lists the uncategorized row so the money no category claims does not vanish', () => {
    renderPanel([BUDGETED, UNCATEGORIZED]);

    expect(screen.getByText('Sin categoría')).toBeInTheDocument();
    expect(screen.getByText(formatCents(50_000))).toBeInTheDocument();
    expect(screen.getByText('Sin categoría').parentElement).not.toHaveTextContent('Sin clasificar');
  });

  it('labels each category with its 50/30/20 bucket, and a category without one as unclassified', () => {
    renderPanel([BUDGETED, { ...UNBUDGETED, bucket: 'sin_categoria' }]);

    expect(screen.getByText('Alimentacion').parentElement).toHaveTextContent('Necesidad');
    expect(screen.getByText('Entretenimiento').parentElement).toHaveTextContent('Sin clasificar');
  });

  it('totals the rows, which is the month expense', () => {
    renderPanel([BUDGETED, UNBUDGETED, UNCATEGORIZED]);

    expect(screen.getByText(/Total de gastos del mes/)).toBeInTheDocument();
    expect(screen.getByText(formatCents(350_000))).toBeInTheDocument();
  });

  it('says a category is over its budget in words with an icon, not only in red', () => {
    renderPanel([{ ...BUDGETED, actual_cents: 350_000 }]);

    const flag = screen.getByText('Excedido');
    expect(flag.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('treats a zero budget as a limit that any spend exceeds', () => {
    renderPanel([{ ...BUDGETED, budget_cents: 0, actual_cents: 100 }]);

    expect(screen.getByText('Excedido')).toBeInTheDocument();
  });

  it('keeps a budgeted category with no spend', () => {
    renderPanel([{ ...BUDGETED, actual_cents: 0 }]);

    expect(screen.getByText('Alimentacion')).toBeInTheDocument();
    expect(screen.getByText(`de ${formatCents(300_000)}`)).toBeInTheDocument();
    expect(screen.queryByText('Excedido')).not.toBeInTheDocument();
  });

  it('shows an empty state, in neutral es-MX, when the month has no spend and no budgets', () => {
    renderPanel([]);

    expect(screen.getByText('Sin gastos ni presupuestos este mes')).toBeInTheDocument();
    expect(screen.getByText(/Registra gastos para ver su desglose/)).toBeInTheDocument();
  });

  it('shows a failure state when the summary could not be loaded', () => {
    renderPanel([], { error: 'No se pudo cargar el resumen del mes.' });

    expect(screen.getByText('No se pudo cargar el desglose por categoría')).toBeInTheDocument();
  });
});

describe('CategoryBreakdownPanel budget form', () => {
  beforeEach(() => {
    vi.mocked(axios.put).mockReset();
    vi.mocked(axios.put).mockResolvedValue({ data: {} });
  });

  it('saves the limit for the selected month and then asks for the summary to be refetched', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    renderPanel([], { categories: [FOOD], onSaved });

    await user.selectOptions(screen.getByLabelText(/Categoría/), FOOD.id);
    await user.type(screen.getByLabelText(/Límite mensual/), '3000');
    await user.click(screen.getByRole('button', { name: 'Guardar presupuesto' }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(axios.put).toHaveBeenCalledTimes(1);
    expect(vi.mocked(axios.put).mock.calls[0][0]).toMatch(/\/finance\/budgets$/);
    expect(vi.mocked(axios.put).mock.calls[0][1]).toMatchObject({
      category_id: FOOD.id,
      period_month: '2026-09-01',
      limit_cents: 300_000,
      currency: 'MXN',
    });
    // The write happened before the refetch was requested.
    expect(vi.mocked(axios.put).mock.invocationCallOrder[0]).toBeLessThan(onSaved.mock.invocationCallOrder[0]);
  });

  it('does not ask for a refetch when the save fails', async () => {
    vi.mocked(axios.put).mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    const onSaved = vi.fn();
    renderPanel([], { categories: [FOOD], onSaved });

    await user.selectOptions(screen.getByLabelText(/Categoría/), FOOD.id);
    await user.type(screen.getByLabelText(/Límite mensual/), '3000');
    await user.click(screen.getByRole('button', { name: 'Guardar presupuesto' }));

    expect(await screen.findByText('No se pudo guardar el presupuesto.')).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });
});
