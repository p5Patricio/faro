import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CfdiPanel } from './CfdiPanel.tsx';

vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
    isAxiosError: (error: { isAxiosError?: boolean }) => Boolean(error?.isAxiosError),
  },
}));

const DOCUMENT = {
  uuid: 'u1', issued_at: '2026-03-10T12:00:00', invoice_type: 'I', issuer_rfc: 'AAA010101AAA',
  issuer_name: 'Clínica Ejemplo', uso_cfdi: 'D01', currency: 'MXN', total_cents: 150_000,
  personal_deduction_use: true, use_label: 'Honorarios médicos, dentales y gastos hospitalarios',
  use_label_status: 'verificado', paid_in_cash: true,
};

const YEAR_DATA = {
  year: 2026,
  documents: [DOCUMENT],
  personal_deductions_by_use: [
    { uso_cfdi: 'D01', currency: 'MXN', count: 1, total_cents: 150_000, use_label: DOCUMENT.use_label, use_label_status: 'verificado' },
  ],
  paid_in_cash_count: 1,
  disclaimer: 'Informativo: Faro no decide qué es deducible.',
};

describe('CfdiPanel', () => {
  beforeEach(() => {
    vi.mocked(axios.get).mockReset();
    vi.mocked(axios.put).mockReset();
  });

  it('summarizes personal deductions by use, flags cash payments and shows the disclaimer', async () => {
    vi.mocked(axios.get).mockResolvedValue({ data: YEAR_DATA });

    render(<CfdiPanel />);

    expect(await screen.findByText(/Honorarios médicos, dentales/)).toBeInTheDocument();
    expect(screen.getAllByText('$1,500.00')).toHaveLength(2);
    expect(screen.getByText('Clínica Ejemplo')).toBeInTheDocument();
    expect(screen.getByText(/pueden no ser deducibles; confírmalo con tu contador/)).toBeInTheDocument();
    expect(screen.getByText('Efectivo')).toBeInTheDocument();
    expect(screen.getByText(YEAR_DATA.disclaimer)).toBeInTheDocument();
  });

  it('omits the cash note when nothing was paid in cash and sends the filename on import', async () => {
    vi.mocked(axios.get).mockResolvedValue({ data: { ...YEAR_DATA, paid_in_cash_count: 0 } });
    vi.mocked(axios.put).mockResolvedValue({ data: { created: true } });
    const user = userEvent.setup();
    render(<CfdiPanel />);
    await screen.findByText('Clínica Ejemplo');

    expect(screen.queryByText(/pago en efectivo/)).not.toBeInTheDocument();
    await user.upload(screen.getByLabelText(/Facturas CFDI 4\.0/), new File(['<c/>'], 'factura.xml', { type: 'text/xml' }));
    await user.click(screen.getByRole('button', { name: 'Importar archivos' }));

    expect(await screen.findByText(/Importada/)).toBeInTheDocument();
    expect(vi.mocked(axios.put)).toHaveBeenCalledWith(expect.stringContaining('/finance/cfdi'), { xml: '<c/>', filename: 'factura.xml' });
  });

  it('shows the API detail as-is when the migration is missing', async () => {
    vi.mocked(axios.get).mockRejectedValue({
      isAxiosError: true,
      response: { status: 503, data: { detail: 'falta aplicar la migración 0017.' } },
    });

    render(<CfdiPanel />);

    expect(await screen.findByText('falta aplicar la migración 0017.')).toBeInTheDocument();
  });
});
