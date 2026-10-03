import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Briefcase, Download, Info } from 'lucide-react';
import { EmptyState } from '../../components/ui/EmptyState.tsx';
import { Panel } from '../../components/ui/Panel.tsx';
import { SkeletonLines } from '../../components/ui/Skeleton.tsx';
import { formatCents, formatDateOnly, formatShortDate, BASE_CURRENCY } from '../finance/lib/format.ts';
import {
  CONCEPT_LABELS,
  INSTRUMENT_LABELS,
  INVESTMENTS_URL,
  KIND_LABELS,
  decimalToCents,
  errorDetail,
  fetchInvestments,
  putAccount,
  putOperation,
  type InstrumentType,
  type InvestmentAccount,
  type InvestmentOperation,
  type OperationKind,
  type Position,
  type Worksheet,
} from './api.ts';

const FIELD_CLASS =
  'mt-1.5 h-11 w-full rounded-lg border border-hairline bg-canvas px-3 text-sm text-ink outline-none transition focus:border-cobalt/50';
const LABEL_CLASS = 'block text-xs font-medium text-ink-muted';
const BUTTON_CLASS =
  'inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-cobalt/30 bg-cobalt/10 px-4 text-sm font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50';
const QUANTITY_KINDS: OperationKind[] = ['buy', 'sell', 'split'];

interface LedgerData {
  accounts: InvestmentAccount[];
  positions: Position[];
  operations: InvestmentOperation[];
  worksheet: Worksheet;
  disclaimer: string;
}

export function InvestmentsDashboard() {
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [data, setData] = useState<LedgerData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++latestRequest.current;
    setError(null);
    try {
      const loaded = await fetchInvestments(year);
      if (requestId === latestRequest.current) setData(loaded);
    } catch (caught) {
      if (requestId === latestRequest.current) {
        setError(errorDetail(caught, 'No se pudo cargar el libro de inversiones.'));
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

  if (error) {
    return <EmptyState variant="error" title="Inversiones no disponibles" hint={error} onRetry={() => void load()} />;
  }
  if (!data) return <SkeletonLines rows={6} />;

  return (
    <div className="space-y-4">
      <p className="flex items-start gap-2 rounded-lg border border-hairline/70 bg-surface px-3 py-2 text-xs text-ink-muted">
        <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {data.disclaimer}
      </p>
      <PositionsPanel positions={data.positions} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Registrar operación" icon={<Briefcase aria-hidden="true" className="h-4 w-4" />}>
          {data.accounts.length ? (
            <OperationForm accounts={data.accounts} onSaved={() => void load()} />
          ) : (
            <p className="text-sm text-ink-muted">Primero crea una cuenta (casa de bolsa, exchange o banco).</p>
          )}
          <AccountForm onSaved={() => void load()} />
        </Panel>
        <WorksheetPanel worksheet={data.worksheet} accounts={data.accounts} year={year} onYearChange={setYear} />
      </div>
      <OperationsPanel operations={data.operations} accounts={data.accounts} />
    </div>
  );
}

function PositionsPanel({ positions }: { positions: Position[] }) {
  return (
    <Panel title="Posiciones">
      {positions.length === 0 ? (
        <p className="text-sm text-ink-muted">Aún no hay posiciones. Registra tu primera compra abajo.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Posiciones con costo promedio en pesos</caption>
            <thead className="text-left text-xs text-ink-muted">
              <tr>
                <th scope="col" className="py-2 pr-3 font-medium">Emisora</th>
                <th scope="col" className="py-2 pr-3 font-medium">Cuenta</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Títulos</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Costo promedio</th>
                <th scope="col" className="py-2 text-right font-medium">Costo total</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr key={`${position.account_id}-${position.symbol}`} className="border-t border-hairline/50">
                  <td className="py-2 pr-3">
                    <span className="font-medium text-ink">{position.symbol}</span>
                    <span className="block text-xs text-ink-muted">{INSTRUMENT_LABELS[position.instrument_type]}</span>
                  </td>
                  <td className="py-2 pr-3 text-ink-secondary">{position.account_name ?? '—'}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{position.quantity}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {position.average_cost_mxn_cents === null
                      ? '—'
                      : formatCents(Math.round(Number(position.average_cost_mxn_cents)))}
                  </td>
                  <td className="py-2 text-right tabular-nums">{formatCents(position.cost_basis_mxn_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function AccountForm({ onSaved }: { onSaved: () => void }) {
  const idPrefix = useId();
  const [name, setName] = useState('');
  const [broker, setBroker] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await putAccount({ name: name.trim(), broker: broker.trim() || undefined });
      setName('');
      setBroker('');
      onSaved();
    } catch (caught) {
      setError(errorDetail(caught, 'No se pudo guardar la cuenta.'));
    }
  };

  return (
    <form onSubmit={submit} className="mt-4 grid gap-3 border-t border-hairline/50 pt-4 sm:grid-cols-[1fr_1fr_auto]">
      <div>
        <label htmlFor={`${idPrefix}-name`} className={LABEL_CLASS}>Nueva cuenta</label>
        <input id={`${idPrefix}-name`} value={name} onChange={(e) => setName(e.target.value)} placeholder="GBM SIC" className={FIELD_CLASS} />
      </div>
      <div>
        <label htmlFor={`${idPrefix}-broker`} className={LABEL_CLASS}>Intermediario</label>
        <input id={`${idPrefix}-broker`} value={broker} onChange={(e) => setBroker(e.target.value)} placeholder="GBM" className={FIELD_CLASS} />
      </div>
      <button type="submit" className={`${BUTTON_CLASS} self-end`}>Crear cuenta</button>
      {error ? <p className="text-sm text-status-critical sm:col-span-3">{error}</p> : null}
    </form>
  );
}

function OperationForm({ accounts, onSaved }: { accounts: InvestmentAccount[]; onSaved: () => void }) {
  const idPrefix = useId();
  const [accountId, setAccountId] = useState(accounts[0].id);
  const [kind, setKind] = useState<OperationKind>('buy');
  const [instrumentType, setInstrumentType] = useState<InstrumentType>('accion_sic');
  const [symbol, setSymbol] = useState('');
  const [tradeDate, setTradeDate] = useState(() => formatDateOnly());
  const [quantity, setQuantity] = useState('');
  const [amount, setAmount] = useState('');
  const [fee, setFee] = useState('');
  const [withheld, setWithheld] = useState('');
  const [currency, setCurrency] = useState(BASE_CURRENCY);
  const [fxRate, setFxRate] = useState('');
  const [fxDate, setFxDate] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isForeign = currency !== BASE_CURRENCY;
  const needsQuantity = QUANTITY_KINDS.includes(kind);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const amountCents = kind === 'split' ? 0 : decimalToCents(amount || '0');
    const feeCents = decimalToCents(fee || '0');
    const withheldCents = decimalToCents(withheld || '0');
    if (!symbol.trim() || amountCents === null || feeCents === null || withheldCents === null) {
      setError('Revisa la emisora y los montos (números con hasta dos decimales).');
      return;
    }
    if (needsQuantity && !/^\d+(\.\d+)?$/.test(quantity.trim())) {
      setError(kind === 'split' ? 'Indica el factor del split (2 = dos por uno).' : 'Indica la cantidad de títulos.');
      return;
    }
    if (isForeign && (!/^\d+(\.\d+)?$/.test(fxRate.trim()) || !fxDate)) {
      setError(`Una operación en ${currency} necesita el tipo de cambio a ${BASE_CURRENCY} y su fecha.`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await putOperation({
        client_id: crypto.randomUUID(),
        account_id: accountId,
        trade_date: tradeDate,
        kind,
        symbol: symbol.trim(),
        instrument_type: instrumentType,
        quantity: needsQuantity ? quantity.trim() : null,
        amount_cents: amountCents,
        fee_cents: feeCents,
        tax_withheld_cents: withheldCents,
        currency,
        fx_rate_to_mxn: isForeign ? fxRate.trim() : null,
        fx_rate_date: isForeign ? fxDate : null,
        fx_source: isForeign ? 'manual' : null,
      });
      setSymbol('');
      setQuantity('');
      setAmount('');
      setFee('');
      setWithheld('');
      onSaved();
    } catch (caught) {
      setError(errorDetail(caught, 'No se pudo guardar la operación.'));
    } finally {
      setSaving(false);
    }
  };

  const field = (key: string, label: string, input: ReactNode, hint?: string) => (
    <div>
      <label htmlFor={`${idPrefix}-${key}`} className={LABEL_CLASS}>{label}</label>
      {input}
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
    </div>
  );

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      {field('account', 'Cuenta', (
        <select id={`${idPrefix}-account`} value={accountId} onChange={(e) => setAccountId(e.target.value)} className={FIELD_CLASS}>
          {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
        </select>
      ))}
      {field('kind', 'Operación', (
        <select id={`${idPrefix}-kind`} value={kind} onChange={(e) => setKind(e.target.value as OperationKind)} className={FIELD_CLASS}>
          {Object.entries(KIND_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      ))}
      {field('symbol', 'Emisora o símbolo', (
        <input id={`${idPrefix}-symbol`} value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="FUNO11, VOO, BTC" className={FIELD_CLASS} />
      ))}
      {field('instrument', 'Tipo de instrumento', (
        <select id={`${idPrefix}-instrument`} value={instrumentType} onChange={(e) => setInstrumentType(e.target.value as InstrumentType)} className={FIELD_CLASS}>
          {Object.entries(INSTRUMENT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      ))}
      {field('date', 'Fecha de la operación', (
        <input id={`${idPrefix}-date`} type="date" value={tradeDate} onChange={(e) => setTradeDate(e.target.value)} className={FIELD_CLASS} />
      ))}
      {needsQuantity
        ? field('quantity', kind === 'split' ? 'Factor del split' : 'Títulos', (
            <input id={`${idPrefix}-quantity`} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={`${FIELD_CLASS} text-right`} />
          ))
        : null}
      {kind !== 'split'
        ? field('amount', kind === 'fee' ? 'Monto (usa el campo comisión)' : 'Monto bruto', (
            <input id={`${idPrefix}-amount`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={`${FIELD_CLASS} text-right`} />
          ), kind === 'buy' || kind === 'sell' ? 'Títulos × precio, sin comisión.' : undefined)
        : null}
      {field('fee', 'Comisión (con IVA)', (
        <input id={`${idPrefix}-fee`} inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value)} className={`${FIELD_CLASS} text-right`} />
      ))}
      {field('withheld', 'Retención', (
        <input id={`${idPrefix}-withheld`} inputMode="decimal" value={withheld} onChange={(e) => setWithheld(e.target.value)} className={`${FIELD_CLASS} text-right`} />
      ), 'ISR retenido o impuesto extranjero, según tu constancia.')}
      {field('currency', 'Moneda', (
        <select id={`${idPrefix}-currency`} value={currency} onChange={(e) => setCurrency(e.target.value)} className={FIELD_CLASS}>
          {[BASE_CURRENCY, 'USD', 'CAD', 'EUR'].map((code) => <option key={code} value={code}>{code}</option>)}
        </select>
      ))}
      {isForeign ? (
        <>
          {field('fx', `Tipo de cambio ${currency}→${BASE_CURRENCY}`, (
            <input id={`${idPrefix}-fx`} inputMode="decimal" value={fxRate} onChange={(e) => setFxRate(e.target.value)} className={`${FIELD_CLASS} text-right`} />
          ))}
          {field('fx-date', 'Fecha del tipo de cambio', (
            <input id={`${idPrefix}-fx-date`} type="date" value={fxDate} onChange={(e) => setFxDate(e.target.value)} className={FIELD_CLASS} />
          ), 'Por ejemplo, el FIX publicado en el DOF el día anterior.')}
        </>
      ) : null}
      {error ? <p className="text-sm text-status-critical sm:col-span-2">{error}</p> : null}
      <button type="submit" disabled={saving} className={`${BUTTON_CLASS} sm:col-span-2`}>
        {saving ? 'Guardando' : 'Guardar operación'}
      </button>
    </form>
  );
}

function WorksheetPanel({
  worksheet,
  accounts,
  year,
  onYearChange,
}: {
  worksheet: Worksheet;
  accounts: InvestmentAccount[];
  year: number;
  onYearChange: (year: number) => void;
}) {
  const idPrefix = useId();
  const names = new Map(accounts.map((account) => [account.id, account.name]));
  const currentYear = new Date().getFullYear();
  return (
    <Panel
      title="Papeles de trabajo para tu contador"
      actions={
        <a href={`${INVESTMENTS_URL}/worksheet?year=${year}&format=csv`} className={BUTTON_CLASS} download>
          <Download aria-hidden="true" className="h-4 w-4" />
          CSV {year}
        </a>
      }
    >
      <label htmlFor={`${idPrefix}-year`} className={LABEL_CLASS}>Año</label>
      <select id={`${idPrefix}-year`} value={year} onChange={(e) => onYearChange(Number(e.target.value))} className={`${FIELD_CLASS} max-w-32`}>
        {[currentYear, currentYear - 1, currentYear - 2].map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
      {worksheet.summary.length === 0 ? (
        <p className="mt-3 text-sm text-ink-muted">Sin ventas, dividendos ni intereses registrados en {year}.</p>
      ) : (
        <ul className="mt-3 space-y-2 text-sm">
          {worksheet.summary.map((row) => (
            <li key={`${row.account_id}-${row.concept}`} className="flex justify-between gap-3 border-t border-hairline/50 pt-2">
              <span>
                <span className="text-ink">{CONCEPT_LABELS[row.concept] ?? row.concept}</span>
                <span className="block text-xs text-ink-muted">{names.get(row.account_id) ?? row.account_id}</span>
              </span>
              <span className="text-right tabular-nums">
                {formatCents(row.amount_mxn_cents)}
                {row.tax_withheld_mxn_cents ? (
                  <span className="block text-xs text-ink-muted">Retenido {formatCents(row.tax_withheld_mxn_cents)}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function OperationsPanel({ operations, accounts }: { operations: InvestmentOperation[]; accounts: InvestmentAccount[] }) {
  const names = new Map(accounts.map((account) => [account.id, account.name]));
  const shown = operations.slice(0, 50);
  return (
    <Panel title="Operaciones recientes">
      {shown.length === 0 ? (
        <p className="text-sm text-ink-muted">Sin operaciones registradas.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {shown.map((operation) => (
            <li key={operation.client_id} className="flex justify-between gap-3 border-t border-hairline/50 pt-2">
              <span>
                <span className="text-ink">{KIND_LABELS[operation.kind]} · {operation.symbol}</span>
                <span className="block text-xs text-ink-muted">
                  {formatShortDate(operation.trade_date)} · {names.get(operation.account_id) ?? '—'}
                  {operation.quantity ? ` · ${operation.quantity} títulos` : ''}
                </span>
              </span>
              <span className="text-right tabular-nums">
                {formatCents(operation.amount_cents, operation.currency)}
                {operation.currency !== BASE_CURRENCY && operation.fx_rate_to_mxn ? (
                  <span className="block text-xs text-ink-muted">TC {operation.fx_rate_to_mxn}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      {operations.length > shown.length ? (
        <p className="mt-2 text-xs text-ink-muted">Se muestran las 50 más recientes de {operations.length}.</p>
      ) : null}
    </Panel>
  );
}
