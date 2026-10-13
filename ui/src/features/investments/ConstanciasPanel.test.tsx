import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConstanciasPanel } from './ConstanciasPanel.tsx';

vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
    isAxiosError: (error: { isAxiosError?: boolean }) => Boolean(error?.isAxiosError),
  },
}));

const YEAR_DATA = {
  year: 2025,
  documents: [
    {
      uuid: 'u1', year: 2025, month_start: 1, month_end: 12, concept: 'intereses', emitter_rfc: 'AAA010101AAA',
      receiver_is_generic: false, operation_cents: 125_050, withheld_cents: 1_234,
    },
  ],
  reconciliation: [
    { concept: 'interest', constancia_cents: 125_050, ledger_cents: 125_100, difference_cents: -50, status: 'coincide',
      constancia_real_cents: 100_025, constancia_loss_cents: 5_000 },
    { concept: 'dividends', constancia_cents: 50_000, ledger_cents: 0, difference_cents: 50_000, status: 'sin_libro',
      constancia_accumulable_cents: 62_075 },
    { concept: 'sale', constancia_cents: 0, ledger_cents: 9_900, difference_cents: -9_900, status: 'sin_constancia' },
  ],
  warnings: ['Las constancias de AAA010101AAA de 2025 (intereses) se emitieron al RFC genérico.'],
  disclaimer: 'Informativo: revisa cualquier diferencia con tu contador.',
};

describe('ConstanciasPanel', () => {
  beforeEach(() => {
    vi.mocked(axios.get).mockReset();
    vi.mocked(axios.put).mockReset();
  });

  it('shows documents, reconciliation statuses, real interest, warnings and the disclaimer', async () => {
    vi.mocked(axios.get).mockResolvedValue({ data: YEAR_DATA });

    render(<ConstanciasPanel year={2025} />);

    expect(await screen.findByText('Coincide')).toBeInTheDocument();
    expect(screen.getByText('Falta en tu libro')).toBeInTheDocument();
    expect(screen.getByText('Falta constancia')).toBeInTheDocument();
    expect(screen.getByText('AAA010101AAA')).toBeInTheDocument();
    expect(screen.getByText('$1,000.25')).toBeInTheDocument();
    expect(screen.getByText('Pérdida real por intereses')).toBeInTheDocument();
    expect(screen.getByText('$620.75')).toBeInTheDocument();
    expect(screen.getByText(/RFC genérico/)).toBeInTheDocument();
    expect(screen.getByText(YEAR_DATA.disclaimer)).toBeInTheDocument();
    expect(vi.mocked(axios.get)).toHaveBeenCalledWith(expect.stringContaining('/investments/retentions'), { params: { year: 2025 } });
  });

  it('imports each selected file and reports created, existing and rejected ones', async () => {
    vi.mocked(axios.get).mockResolvedValue({ data: YEAR_DATA });
    vi.mocked(axios.put)
      .mockResolvedValueOnce({ data: { created: true } })
      .mockResolvedValueOnce({ data: { created: false } })
      .mockRejectedValueOnce({ isAxiosError: true, response: { data: { detail: 'El archivo no es XML válido.' } } });
    const user = userEvent.setup();
    render(<ConstanciasPanel year={2025} />);
    await screen.findByText('Coincide');

    await user.upload(screen.getByLabelText(/Constancias de retenciones/), [
      new File(['<a/>'], 'a.xml', { type: 'text/xml' }),
      new File(['<b/>'], 'b.xml', { type: 'text/xml' }),
      new File(['x'], 'c.xml', { type: 'text/xml' }),
    ]);
    await user.click(screen.getByRole('button', { name: 'Importar archivos' }));

    expect(await screen.findByText(/Error: El archivo no es XML válido\./)).toBeInTheDocument();
    expect(screen.getByText(/Importada/)).toBeInTheDocument();
    expect(screen.getByText(/Ya existía/)).toBeInTheDocument();
    expect(vi.mocked(axios.put)).toHaveBeenNthCalledWith(1, expect.stringContaining('/retentions'), { xml: '<a/>' });
    expect(vi.mocked(axios.get)).toHaveBeenCalledTimes(2);
  });

  it('shows the API detail as-is when the migration is missing', async () => {
    vi.mocked(axios.get).mockRejectedValue({
      isAxiosError: true,
      response: { status: 503, data: { detail: 'falta aplicar la migración 0018.' } },
    });

    render(<ConstanciasPanel year={2025} />);

    expect(await screen.findByText('falta aplicar la migración 0018.')).toBeInTheDocument();
  });
});
