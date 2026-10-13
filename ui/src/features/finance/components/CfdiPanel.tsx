import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Info, Receipt } from 'lucide-react';
import { Badge } from '../../../components/ui/Badge.tsx';
import { EmptyState } from '../../../components/ui/EmptyState.tsx';
import { Panel } from '../../../components/ui/Panel.tsx';
import { SkeletonLines } from '../../../components/ui/Skeleton.tsx';
import { XmlImportForm } from '../../../components/ui/XmlImportForm.tsx';
import { apiDetail, fetchCfdis, putCfdi, type CfdiYear } from '../lib/cfdi.ts';
import { formatCents, formatShortDate } from '../lib/format.ts';

const TH_CLASS = 'py-2 pr-3 font-medium';

/**
 * Expense invoices (CFDI 4.0): import the SAT XMLs and see the personal
 * deduction uses (D01–D10) added up by `UsoCFDI`. Informational only.
 */
export function CfdiPanel() {
  const yearSelectId = useId();
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const [data, setData] = useState<CfdiYear | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++latestRequest.current;
    setError(null);
    try {
      const loaded = await fetchCfdis(year);
      if (requestId === latestRequest.current) setData(loaded);
    } catch (caught) {
      if (requestId === latestRequest.current) {
        setData(null);
        setError(apiDetail(caught, 'No se pudieron cargar las facturas.'));
      }
    }
  }, [year]);

  useEffect(() => {
    const requests = latestRequest;
    queueMicrotask(() => void load());
    return () => {
      requests.current += 1;
    };
  }, [load]);

  return (
    <Panel title="Facturas (CFDI)" icon={<Receipt aria-hidden="true" className="h-4 w-4" />}>
      <XmlImportForm label="Facturas CFDI 4.0 (XML descargados del SAT)" upload={putCfdi} onDone={() => void load()} />
      <div className="mt-4 border-t border-hairline/50 pt-4">
        <label htmlFor={yearSelectId} className="block text-xs font-medium text-ink-muted">Año</label>
        <select
          id={yearSelectId}
          value={year}
          onChange={(event) => setYear(Number(event.target.value))}
          className="mt-1.5 h-11 w-full max-w-32 rounded-lg border border-hairline bg-canvas px-3 text-sm text-ink outline-none transition focus:border-cobalt/50"
        >
          {[currentYear, currentYear - 1, currentYear - 2].map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
        <div className="mt-4">
          {error ? (
            <EmptyState variant="error" title="Facturas no disponibles" hint={error} onRetry={() => void load()} />
          ) : !data ? (
            <SkeletonLines rows={3} />
          ) : (
            <CfdiResult data={data} />
          )}
        </div>
      </div>
    </Panel>
  );
}

function CfdiResult({ data }: { data: CfdiYear }) {
  const cashCount = data.paid_in_cash_count;
  return (
    <div className="space-y-5">
      {cashCount > 0 ? (
        <p role="note" className="rounded-lg border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
          {cashCount === 1 ? '1 factura de gastos personales indica' : `${cashCount} facturas de gastos personales indican`} pago en
          efectivo. Los gastos médicos pagados en efectivo pueden no ser deducibles; confírmalo con tu contador.
        </p>
      ) : null}

      {data.documents.length === 0 ? (
        <p className="text-sm text-ink-muted">Aún no hay facturas importadas para {data.year}.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="mb-2 text-left text-xs font-medium text-ink-muted">Gastos personales por uso del CFDI</caption>
              <thead className="text-left text-xs text-ink-muted">
                <tr>
                  <th scope="col" className={TH_CLASS}>Uso del CFDI</th>
                  <th scope="col" className={`${TH_CLASS} text-right`}>Facturas</th>
                  <th scope="col" className="py-2 text-right font-medium">Monto</th>
                </tr>
              </thead>
              <tbody>
                {data.personal_deductions_by_use.length === 0 ? (
                  <tr className="border-t border-hairline/50">
                    <td colSpan={3} className="py-2 text-ink-muted">Ninguna factura usa claves D01 a D10.</td>
                  </tr>
                ) : (
                  data.personal_deductions_by_use.map((row) => (
                    <tr key={`${row.uso_cfdi}-${row.currency}`} className="border-t border-hairline/50">
                      <th scope="row" className="py-2 pr-3 text-left font-normal">
                        <span className="font-medium text-ink">{row.uso_cfdi}</span> · {row.use_label}
                        {row.use_label_status === 'verificado' ? null : <span className="block text-xs text-ink-muted">Etiqueta por verificar</span>}
                      </th>
                      <td className="py-2 pr-3 text-right tabular-nums">{row.count}</td>
                      <td className="py-2 text-right tabular-nums">{formatCents(row.total_cents, row.currency)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="mb-2 text-left text-xs font-medium text-ink-muted">Facturas importadas de {data.year}</caption>
              <thead className="text-left text-xs text-ink-muted">
                <tr>
                  <th scope="col" className={TH_CLASS}>Fecha</th>
                  <th scope="col" className={TH_CLASS}>Emisor</th>
                  <th scope="col" className={TH_CLASS}>Uso</th>
                  <th scope="col" className={`${TH_CLASS} text-right`}>Total</th>
                  <th scope="col" className="py-2 font-medium">Pago</th>
                </tr>
              </thead>
              <tbody>
                {data.documents.map((document) => (
                  <tr key={document.uuid} className="border-t border-hairline/50">
                    <td className="py-2 pr-3 text-ink-secondary">{formatShortDate(document.issued_at)}</td>
                    <td className="py-2 pr-3">
                      <span className="text-ink">{document.issuer_name ?? document.issuer_rfc ?? '—'}</span>
                      {document.issuer_name && document.issuer_rfc ? (
                        <span className="block text-xs text-ink-muted">{document.issuer_rfc}</span>
                      ) : null}
                    </td>
                    <td className="py-2 pr-3 text-ink-secondary">{document.uso_cfdi ?? '—'}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{formatCents(document.total_cents, document.currency)}</td>
                    <td className="py-2">{document.paid_in_cash ? <Badge tone="warning">Efectivo</Badge> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="flex items-start gap-2 text-xs text-ink-muted">
        <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {data.disclaimer}
      </p>
    </div>
  );
}
