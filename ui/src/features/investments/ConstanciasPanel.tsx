import { useCallback, useEffect, useRef, useState } from 'react';
import { FileText, Info } from 'lucide-react';
import { Badge } from '../../components/ui/Badge.tsx';
import { Panel } from '../../components/ui/Panel.tsx';
import { SkeletonLines } from '../../components/ui/Skeleton.tsx';
import { XmlImportForm } from '../../components/ui/XmlImportForm.tsx';
import { formatCents, formatSignedCents } from '../finance/lib/format.ts';
import {
  errorDetail,
  fetchRetentions,
  putRetention,
  type ReconciliationConcept,
  type ReconciliationRow,
  type ReconciliationStatus,
  type RetentionsYear,
} from './api.ts';

const DOCUMENT_CONCEPT_LABELS: Record<string, string> = {
  intereses: 'Intereses',
  dividendos: 'Dividendos',
  enajenacion: 'Venta de acciones',
};

const RECONCILIATION_LABELS: Record<ReconciliationConcept, string> = {
  interest: 'Intereses (nominal)',
  interest_withheld: 'ISR retenido por intereses',
  dividends: 'Dividendos pagados',
  sale: 'Ganancia o pérdida en ventas',
};

const STATUS_BADGES: Record<ReconciliationStatus, { label: string; tone: 'ok' | 'warning' | 'neutral' }> = {
  coincide: { label: 'Coincide', tone: 'ok' },
  difiere: { label: 'Difiere', tone: 'warning' },
  sin_libro: { label: 'Falta en tu libro', tone: 'warning' },
  sin_constancia: { label: 'Falta constancia', tone: 'neutral' },
};

const TH_CLASS = 'py-2 pr-3 font-medium';

function monthName(month: number): string {
  return new Intl.DateTimeFormat('es-MX', { month: 'short' }).format(new Date(2000, month - 1, 1));
}

function periodLabel(start: number, end: number, year: number): string {
  return start === end ? `${monthName(start)} ${year}` : `${monthName(start)}–${monthName(end)} ${year}`;
}

function findRow(rows: ReconciliationRow[], concept: ReconciliationConcept): ReconciliationRow | undefined {
  return rows.find((row) => row.concept === concept);
}

/**
 * Broker constancias (CFDI de Retenciones): import the XMLs and see them
 * reconciled against the investment ledger for `year`. Informational only.
 */
export function ConstanciasPanel({ year }: { year: number }) {
  const [data, setData] = useState<RetentionsYear | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++latestRequest.current;
    setError(null);
    try {
      const loaded = await fetchRetentions(year);
      if (requestId === latestRequest.current) setData(loaded);
    } catch (caught) {
      if (requestId === latestRequest.current) {
        setData(null);
        setError(errorDetail(caught, 'No se pudieron cargar las constancias.'));
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
    <Panel title={`Constancias fiscales ${year}`} icon={<FileText aria-hidden="true" className="h-4 w-4" />}>
      <XmlImportForm label="Constancias de retenciones (XML de tu intermediario)" upload={putRetention} onDone={() => void load()} />
      <p className="mt-2 text-xs text-ink-muted">Se muestra el año seleccionado en «Papeles de trabajo para tu contador».</p>
      <div className="mt-4 border-t border-hairline/50 pt-4">
        {error ? (
          <p role="alert" className="text-sm text-status-critical">{error}</p>
        ) : !data ? (
          <SkeletonLines rows={3} />
        ) : (
          <ConstanciasResult data={data} />
        )}
      </div>
    </Panel>
  );
}

function ConstanciasResult({ data }: { data: RetentionsYear }) {
  const interest = findRow(data.reconciliation, 'interest');
  const dividends = findRow(data.reconciliation, 'dividends');
  const extras: Array<[string, number]> = [];
  if (interest?.constancia_real_cents !== undefined) extras.push(['Interés real', interest.constancia_real_cents]);
  if (interest?.constancia_loss_cents !== undefined) extras.push(['Pérdida real por intereses', interest.constancia_loss_cents]);
  if (dividends?.constancia_accumulable_cents !== undefined) {
    extras.push(['Dividendo acumulable (piramidado)', dividends.constancia_accumulable_cents]);
  }

  return (
    <div className="space-y-5">
      {data.warnings.length > 0 ? (
        <ul className="space-y-1 rounded-lg border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
          {data.warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      ) : null}

      {data.documents.length === 0 ? (
        <p className="text-sm text-ink-muted">Aún no hay constancias importadas para {data.year}.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Constancias importadas de {data.year}</caption>
            <thead className="text-left text-xs text-ink-muted">
              <tr>
                <th scope="col" className={TH_CLASS}>Concepto</th>
                <th scope="col" className={TH_CLASS}>Periodo</th>
                <th scope="col" className={TH_CLASS}>RFC del emisor</th>
                <th scope="col" className={`${TH_CLASS} text-right`}>Operación</th>
                <th scope="col" className="py-2 text-right font-medium">Retenido</th>
              </tr>
            </thead>
            <tbody>
              {data.documents.map((document) => (
                <tr key={document.uuid} className="border-t border-hairline/50">
                  <th scope="row" className="py-2 pr-3 text-left font-medium text-ink">
                    {DOCUMENT_CONCEPT_LABELS[document.concept] ?? 'Otro'}
                  </th>
                  <td className="py-2 pr-3 text-ink-secondary">{periodLabel(document.month_start, document.month_end, document.year)}</td>
                  <td className="py-2 pr-3 text-ink-secondary">{document.emitter_rfc ?? '—'}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatCents(document.operation_cents)}</td>
                  <td className="py-2 text-right tabular-nums">{formatCents(document.withheld_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.reconciliation.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="mb-2 text-left text-xs font-medium text-ink-muted">Constancias contra tu libro de inversiones</caption>
            <thead className="text-left text-xs text-ink-muted">
              <tr>
                <th scope="col" className={TH_CLASS}>Concepto</th>
                <th scope="col" className={`${TH_CLASS} text-right`}>Constancia</th>
                <th scope="col" className={`${TH_CLASS} text-right`}>Tu libro</th>
                <th scope="col" className={`${TH_CLASS} text-right`}>Diferencia</th>
                <th scope="col" className="py-2 font-medium">Estado</th>
              </tr>
            </thead>
            <tbody>
              {data.reconciliation.map((row) => (
                <tr key={row.concept} className="border-t border-hairline/50">
                  <th scope="row" className="py-2 pr-3 text-left font-medium text-ink">{RECONCILIATION_LABELS[row.concept]}</th>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatCents(row.constancia_cents)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatCents(row.ledger_cents)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatSignedCents(row.difference_cents)}</td>
                  <td className="py-2"><Badge tone={STATUS_BADGES[row.status].tone}>{STATUS_BADGES[row.status].label}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {extras.length > 0 ? (
        <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_auto] sm:justify-start">
          {extras.map(([label, cents]) => (
            <div key={label} className="flex justify-between gap-6">
              <dt className="text-ink-muted">{label}</dt>
              <dd className="tabular-nums text-ink">{formatCents(cents)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <p className="flex items-start gap-2 text-xs text-ink-muted">
        <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {data.disclaimer}
      </p>
    </div>
  );
}
