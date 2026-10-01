import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RecurringBillsPanel } from './RecurringBillsPanel.tsx';
import type { RecurringBill } from '../types.ts';

vi.mock('axios');

/** A local calendar day, `offsetDays` from today, as a date-only string. */
function dateOnly(offsetDays: number): string {
  const day = new Date();
  day.setDate(day.getDate() + offsetDays);
  const month = String(day.getMonth() + 1).padStart(2, '0');
  const date = String(day.getDate()).padStart(2, '0');
  return `${day.getFullYear()}-${month}-${date}`;
}

/** The label the panel shows for a date-only string (a local calendar day). */
function shownDate(value: string): string {
  return new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'short', year: 'numeric' }).format(
    new Date(`${value}T00:00:00`),
  );
}

function makeBill(overrides: Partial<RecurringBill> = {}): RecurringBill {
  return {
    id: 'bill-1',
    name: 'Netflix',
    category_id: null,
    account_id: null,
    amount_cents: 19900,
    currency: 'MXN',
    frequency: 'monthly',
    anchor_due_date: '2026-01-05',
    reminder_days_before: 3,
    is_active: true,
    notes: null,
    next_due_date: dateOnly(10),
    next_status: 'pending',
    ...overrides,
  };
}

function renderPanel(bills: RecurringBill[], onChanged: () => void | Promise<unknown> = () => {}) {
  return render(<RecurringBillsPanel bills={bills} categories={[]} accounts={[]} onChanged={onChanged} />);
}

describe('RecurringBillsPanel next due date', () => {
  it('shows the next due date and how far away it is for an upcoming bill', () => {
    const due = dateOnly(10);
    renderPanel([makeBill({ next_due_date: due })]);

    expect(screen.getByText(`Vence en 10 días · ${shownDate(due)}`)).toBeInTheDocument();
    expect(screen.queryByText(/Sin pendiente/)).not.toBeInTheDocument();
  });

  it.each([
    [0, 'Vence hoy'],
    [1, 'Vence mañana'],
  ])('says so in words when the bill is due %i days from now', (offset, label) => {
    const due = dateOnly(offset);
    renderPanel([makeBill({ next_due_date: due })]);

    expect(screen.getByText(`${label} · ${shownDate(due)}`)).toBeInTheDocument();
  });

  it('marks an overdue bill with text and an icon, including how many days late it is', () => {
    const due = dateOnly(-14);
    renderPanel([makeBill({ next_due_date: due })]);

    const line = screen.getByText(`Vencido hace 14 días · ${shownDate(due)}`);
    expect(line).toBeInTheDocument();
    // Never color alone: the same line carries a (decorative) warning icon.
    expect(line.closest('p')?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('uses the singular for a bill one day late', () => {
    renderPanel([makeBill({ next_due_date: dateOnly(-1) })]);

    expect(screen.getByText(/Vencido hace 1 día ·/)).toBeInTheDocument();
  });

  it('does not show the overdue state for an upcoming bill', () => {
    renderPanel([makeBill({ next_due_date: dateOnly(2) })]);

    expect(screen.queryByText(/Vencido/)).not.toBeInTheDocument();
  });

  it('never tells the user an active bill has nothing pending', () => {
    renderPanel([makeBill({ next_due_date: null, next_status: null })]);

    expect(screen.queryByText(/Sin pendiente/)).not.toBeInTheDocument();
    expect(screen.getByText('Próximo vencimiento no disponible')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Marcar Netflix como pagado/ })).not.toBeInTheDocument();
  });

  it('labels a deactivated bill as inactive', () => {
    renderPanel([makeBill({ is_active: false, next_due_date: null, next_status: null })]);

    expect(screen.getByText('Inactivo')).toBeInTheDocument();
  });
});

describe('RecurringBillsPanel actions', () => {
  beforeEach(() => {
    vi.mocked(axios.put).mockReset();
    vi.mocked(axios.put).mockResolvedValue({ data: {} });
  });

  it('marks the pending occurrence paid and refreshes the list', async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const due = dateOnly(3);
    renderPanel([makeBill({ next_due_date: due })], onChanged);

    await user.click(screen.getByRole('button', { name: 'Marcar Netflix como pagado' }));

    expect(axios.put).toHaveBeenCalledTimes(1);
    const [url, payload] = vi.mocked(axios.put).mock.calls[0];
    expect(url).toMatch(/\/finance\/recurring-bills\/payments$/);
    expect(payload).toEqual({ bill_id: 'bill-1', due_date: due, status: 'paid' });
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it('skips the pending occurrence and refreshes the list', async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const due = dateOnly(-2);
    renderPanel([makeBill({ next_due_date: due })], onChanged);

    await user.click(screen.getByRole('button', { name: 'Omitir el pago de Netflix' }));

    expect(vi.mocked(axios.put).mock.calls[0][1]).toEqual({ bill_id: 'bill-1', due_date: due, status: 'skipped' });
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it('offers both actions on an overdue bill', () => {
    renderPanel([makeBill({ next_due_date: dateOnly(-5) })]);

    expect(screen.getByRole('button', { name: 'Marcar Netflix como pagado' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Omitir el pago de Netflix' })).toBeEnabled();
  });

  it('keeps the row actions disabled until the refresh finishes', async () => {
    const user = userEvent.setup();
    let finishRefresh: () => void = () => {};
    const onChanged = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishRefresh = resolve;
        }),
    );
    renderPanel([makeBill()], onChanged);

    await user.click(screen.getByRole('button', { name: 'Marcar Netflix como pagado' }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: 'Marcar Netflix como pagado' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Omitir el pago de Netflix' })).toBeDisabled();

    finishRefresh();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Marcar Netflix como pagado' })).toBeEnabled());
  });

  it('reports a failed action instead of failing silently, and does not refresh', async () => {
    vi.mocked(axios.put).mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    const onChanged = vi.fn();
    renderPanel([makeBill()], onChanged);

    await user.click(screen.getByRole('button', { name: 'Marcar Netflix como pagado' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo marcar «Netflix» como pagado.');
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Marcar Netflix como pagado' })).toBeEnabled();
  });
});
