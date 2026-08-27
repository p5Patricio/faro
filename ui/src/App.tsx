import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Brain,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Gauge,
  History,
  MinusCircle,
  RefreshCcw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react';
import type { PricePoint } from './components/FinancialChart';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api').replace(/\/$/, '');
const FinancialChart = lazy(() =>
  import('./components/FinancialChart').then((module) => ({ default: module.FinancialChart })),
);
const EquityCurveChart = lazy(() =>
  import('./components/EquityCurveChart').then((module) => ({ default: module.EquityCurveChart })),
);

type Signal = 'BUY' | 'SELL' | 'HOLD' | string;
type RiskProfileScopeType = 'default' | 'asset_class' | 'ticker';

interface Asset {
  id: string;
  ticker: string;
  name?: string;
  asset_class?: string;
}

interface RiskMetadata {
  position_size?: number;
  stop_loss?: number | null;
  take_profit?: number | null;
  blocked_reasons?: string[];
  pre_risk_action?: Signal | null;
  profile_source?: string | null;
  profile_name?: string | null;
}

interface ModelMetadata {
  name?: string;
  version?: string;
  run_id?: string;
  feature_set?: string;
  label_method?: string;
  horizon?: number;
}

interface FeedbackMetadata {
  actual_label?: string | null;
  is_correct?: boolean | null;
  outcome_return?: number | null;
}

interface Analysis {
  signal: Signal;
  confidence: number;
  reason?: string;
  reasons?: string[];
  probabilities?: Record<string, number>;
  model?: ModelMetadata;
  risk?: RiskMetadata;
  feedback?: FeedbackMetadata;
  indicators?: {
    rsi?: number | null;
    close?: number | null;
    sma_20?: number | null;
  };
  prediction_timestamp?: string;
  expected_return?: number | null;
  expected_risk?: number | null;
}

interface AnalysisResponse {
  ticker: string;
  timestamp: string;
  source?: 'prediction' | 'fallback_indicators' | 'demo_indicators' | string;
  analysis: Analysis;
}

interface PredictionAuditRow {
  prediction_id?: number;
  timestamp?: string;
  created_at?: string;
  action: Signal;
  confidence?: number | null;
  probabilities?: Record<string, number>;
  expected_return?: number | null;
  expected_risk?: number | null;
  model?: ModelMetadata;
  risk?: RiskMetadata;
  feedback?: FeedbackMetadata;
}

interface FeedbackSummaryResponse {
  summary: {
    evaluated_predictions?: number;
    accuracy?: number | null;
    mean_confidence?: number | null;
    mean_outcome_return?: number | null;
    total_outcome_return?: number | null;
  };
  by_action: FeedbackGroupRow[];
  by_confidence_bucket: FeedbackGroupRow[];
}

interface FeedbackGroupRow {
  action?: Signal | null;
  bucket?: string | null;
  count?: number;
  accuracy?: number | null;
  mean_confidence?: number | null;
  mean_outcome_return?: number | null;
  total_outcome_return?: number | null;
}

interface SystemHealthResponse {
  status: 'ok' | 'degraded' | string;
  environment: string;
  allow_demo_fallback: boolean;
  timestamp: string;
  checks: Record<string, { status?: string; reason?: string; missing?: string[] }>;
}

interface OperationalAlertsResponse {
  ticker: string;
  status: 'ok' | 'info' | 'warning' | 'critical' | string;
  timestamp: string;
  alerts: OperationalAlert[];
}

interface OperationalAlert {
  severity: 'info' | 'warning' | 'critical' | string;
  code: string;
  message: string;
  details?: Record<string, string | number | boolean | null>;
}

interface BacktestSummaryRow {
  id?: string;
  name?: string;
  started_at?: string | null;
  ended_at?: string | null;
  created_at?: string | null;
  metrics?: {
    total_return?: number | null;
    max_drawdown?: number | null;
    profit_factor?: number | null;
    active_trade_count?: number | null;
    trade_count?: number | null;
    win_rate?: number | null;
    exposure?: number | null;
    final_equity?: number | null;
  };
  model?: ModelMetadata;
}

interface PaperTradingTimelineRow {
  timestamp?: string;
  action?: Signal;
  confidence?: number | null;
  price?: number | null;
  mark_return?: number | null;
  exposure?: number | null;
  exposure_delta?: number | null;
  cost?: number | null;
  equity?: number | null;
  position_state?: 'LONG' | 'SHORT' | 'FLAT' | string;
}

interface PaperTradingResponse {
  ticker: string;
  timestamp: string;
  persisted_run_id?: string | null;
  metrics: {
    initial_capital?: number;
    final_equity?: number;
    total_return?: number;
    max_drawdown?: number;
    signal_count?: number;
    trade_count?: number;
    active_signal_count?: number;
    average_abs_exposure?: number;
    open_exposure?: number;
    open_position?: 'LONG' | 'SHORT' | 'FLAT' | string;
    last_price?: number | null;
    profit_factor?: number | null;
    fee_bps?: number;
    slippage_bps?: number;
    allow_short?: boolean;
  };
  timeline: PaperTradingTimelineRow[];
}

interface PaperTradingRunRow {
  id?: string;
  name?: string;
  started_at?: string | null;
  ended_at?: string | null;
  created_at?: string | null;
  metrics?: PaperTradingResponse['metrics'];
  params?: {
    initial_capital?: number;
    default_position_size?: number;
    fee_bps?: number;
    slippage_bps?: number;
    allow_short?: boolean;
    model_name?: string | null;
    model_version?: string | null;
  };
  model?: ModelMetadata;
}

interface RiskProfile {
  name: string;
  scope_type?: RiskProfileScopeType | string;
  scope_value?: string;
  max_position_size: number;
  min_confidence_to_trade: number;
  max_expected_risk: number;
  stop_loss: number;
  take_profit: number;
  allow_short: boolean;
}

interface RiskProfileResponse {
  source: 'default' | 'user' | string;
  profile: RiskProfile;
}

const DEFAULT_RISK_PROFILE: RiskProfile = {
  name: 'default',
  scope_type: 'default',
  scope_value: '',
  max_position_size: 0.1,
  min_confidence_to_trade: 0.6,
  max_expected_risk: 0.05,
  stop_loss: 0.02,
  take_profit: 0.04,
  allow_short: true,
};

function App() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedTicker, setSelectedTicker] = useState('');
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [analysisResponse, setAnalysisResponse] = useState<AnalysisResponse | null>(null);
  const [predictionHistory, setPredictionHistory] = useState<PredictionAuditRow[]>([]);
  const [feedbackSummary, setFeedbackSummary] = useState<FeedbackSummaryResponse | null>(null);
  const [backtests, setBacktests] = useState<BacktestSummaryRow[]>([]);
  const [paperTrading, setPaperTrading] = useState<PaperTradingResponse | null>(null);
  const [paperTradingRuns, setPaperTradingRuns] = useState<PaperTradingRunRow[]>([]);
  const [operationalAlerts, setOperationalAlerts] = useState<OperationalAlertsResponse | null>(null);
  const [paperSaving, setPaperSaving] = useState(false);
  const [paperStatus, setPaperStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [systemHealth, setSystemHealth] = useState<SystemHealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [riskProfile, setRiskProfile] = useState<RiskProfileResponse | null>(null);
  const [riskDraft, setRiskDraft] = useState<RiskProfile>(DEFAULT_RISK_PROFILE);
  const [riskScopeType, setRiskScopeType] = useState<RiskProfileScopeType>('default');
  const [riskStatus, setRiskStatus] = useState<string | null>(null);
  const [riskSaving, setRiskSaving] = useState(false);

  const selectedAsset = useMemo(
    () => assets.find((asset) => asset.ticker === selectedTicker),
    [assets, selectedTicker],
  );

  const riskScopeValue = useMemo(() => {
    if (riskScopeType === 'ticker') {
      return selectedAsset?.ticker ?? selectedTicker;
    }
    if (riskScopeType === 'asset_class') {
      return selectedAsset?.asset_class?.toLowerCase() ?? '';
    }
    return '';
  }, [riskScopeType, selectedAsset?.asset_class, selectedAsset?.ticker, selectedTicker]);

  const fetchAssets = useCallback(async () => {
    try {
      const response = await axios.get<Asset[]>(`${API_BASE_URL}/assets`);
      setAssets(response.data);
      setSelectedTicker((currentTicker) => currentTicker || response.data[0]?.ticker || '');
    } catch {
      setError('No se pudieron cargar los activos.');
    }
  }, []);

  const fetchData = useCallback(async (ticker: string) => {
    setLoading(true);
    setError(null);
    try {
      const [
        pricesResponse,
        analysisResponse,
        historyResponse,
        feedbackResponse,
        alertsResponse,
        backtestsResponse,
        paperTradingResponse,
        paperRunsResponse,
      ] = await Promise.all([
        axios.get<PricePoint[]>(`${API_BASE_URL}/prices/${ticker}?limit=240`),
        axios.get<AnalysisResponse>(`${API_BASE_URL}/analysis/${ticker}`),
        axios
          .get<PredictionAuditRow[]>(`${API_BASE_URL}/predictions/${ticker}?limit=8`)
          .catch(() => ({ data: [] as PredictionAuditRow[] })),
        axios
          .get<FeedbackSummaryResponse>(`${API_BASE_URL}/feedback/${ticker}?limit=250`)
          .catch(() => ({ data: null as FeedbackSummaryResponse | null })),
        axios
          .get<OperationalAlertsResponse>(`${API_BASE_URL}/alerts/${ticker}`)
          .catch(() => ({ data: null as OperationalAlertsResponse | null })),
        axios
          .get<BacktestSummaryRow[]>(`${API_BASE_URL}/backtests/${ticker}?limit=5`)
          .catch(() => ({ data: [] as BacktestSummaryRow[] })),
        axios
          .get<PaperTradingResponse>(`${API_BASE_URL}/paper-trading/${ticker}?limit=250`)
          .catch(() => ({ data: null as PaperTradingResponse | null })),
        axios
          .get<PaperTradingRunRow[]>(`${API_BASE_URL}/paper-trading-runs/${ticker}?limit=8`)
          .catch(() => ({ data: [] as PaperTradingRunRow[] })),
      ]);
      setPrices(pricesResponse.data);
      setAnalysisResponse(analysisResponse.data);
      setPredictionHistory(historyResponse.data);
      setFeedbackSummary(feedbackResponse.data);
      setOperationalAlerts(alertsResponse.data);
      setBacktests(backtestsResponse.data);
      setPaperTrading(paperTradingResponse.data);
      setPaperTradingRuns(paperRunsResponse.data);
      setPaperStatus(null);
    } catch {
      setError('No se pudo actualizar la señal.');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchSystemHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const response = await axios.get<SystemHealthResponse>(`${API_BASE_URL}/health`);
      setSystemHealth(response.data);
    } catch {
      setSystemHealth(null);
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const persistPaperTrading = useCallback(async () => {
    if (!selectedTicker || paperSaving) {
      return;
    }
    setPaperSaving(true);
    setPaperStatus(null);
    try {
      const response = await axios.get<PaperTradingResponse>(
        `${API_BASE_URL}/paper-trading/${selectedTicker}?limit=250&persist=true`,
      );
      setPaperTrading(response.data);
      const runsResponse = await axios.get<PaperTradingRunRow[]>(
        `${API_BASE_URL}/paper-trading-runs/${selectedTicker}?limit=8`,
      );
      setPaperTradingRuns(runsResponse.data);
      setPaperStatus(response.data.persisted_run_id ? 'Corrida guardada.' : 'Simulacion recalculada.');
    } catch {
      setPaperStatus('No se pudo guardar la corrida.');
    } finally {
      setPaperSaving(false);
    }
  }, [paperSaving, selectedTicker]);

  const fetchRiskProfile = useCallback(async (scopeType: RiskProfileScopeType, scopeValue: string) => {
    const params = new URLSearchParams({ scope_type: scopeType });
    if (scopeValue) {
      params.set('scope_value', scopeValue);
    }
    try {
      const response = await axios.get<RiskProfileResponse>(`${API_BASE_URL}/risk-profile?${params}`);
      const profile =
        response.data.source === 'default' && scopeType !== 'default'
          ? { ...response.data.profile, name: scopeValue || scopeType, scope_type: scopeType, scope_value: scopeValue }
          : response.data.profile;
      setRiskProfile(response.data);
      setRiskDraft(profile);
      setRiskStatus(
        response.data.source === 'default' && scopeType !== 'default'
          ? 'Sin perfil especifico; guarda para crearlo.'
          : null,
      );
    } catch {
      setRiskProfile({ source: 'default', profile: DEFAULT_RISK_PROFILE });
      setRiskDraft({ ...DEFAULT_RISK_PROFILE, scope_type: scopeType, scope_value: scopeValue });
      setRiskStatus('No se pudo cargar el perfil.');
    }
  }, []);

  const updateRiskDraft = useCallback((field: keyof RiskProfile, value: number | string | boolean) => {
    setRiskDraft((current) => ({ ...current, [field]: value }));
  }, []);

  const saveRiskProfile = useCallback(async () => {
    setRiskSaving(true);
    setRiskStatus(null);
    try {
      const payload = { ...riskDraft, scope_type: riskScopeType, scope_value: riskScopeValue };
      const response = await axios.put<RiskProfileResponse>(`${API_BASE_URL}/risk-profile`, payload);
      setRiskProfile(response.data);
      setRiskDraft(response.data.profile);
      setRiskStatus('Perfil guardado.');
    } catch {
      setRiskStatus('No se pudo guardar.');
    } finally {
      setRiskSaving(false);
    }
  }, [riskDraft, riskScopeType, riskScopeValue]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) {
        void fetchAssets();
        void fetchSystemHealth();
      }
    });

    return () => {
      disposed = true;
    };
  }, [fetchAssets, fetchSystemHealth]);

  useEffect(() => {
    if (!selectedTicker) {
      return;
    }

    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) {
        void fetchData(selectedTicker);
      }
    });

    return () => {
      disposed = true;
    };
  }, [fetchData, selectedTicker]);

  useEffect(() => {
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) {
        void fetchRiskProfile(riskScopeType, riskScopeValue);
      }
    });

    return () => {
      disposed = true;
    };
  }, [fetchRiskProfile, riskScopeType, riskScopeValue]);

  const analysis = analysisResponse?.analysis ?? null;

  return (
    <div className="min-h-screen bg-[#111312] text-zinc-100">
      <header className="border-b border-white/10 bg-[#171918]">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 md:flex-row md:items-center md:justify-between md:px-6">
          <div className="flex items-center gap-3">
            <img
              src="/brand/ia-inversiones-logo.png"
              alt="Faro"
              className="h-12 w-12 rounded-lg border border-amber-200/20 bg-zinc-50 object-cover"
            />
            <div>
              <h1 className="text-xl font-semibold tracking-normal text-zinc-50">Faro</h1>
              <p className="text-sm text-zinc-400">Decisiones de mercado con riesgo visible</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <StatusPill source={analysisResponse?.source} loading={loading} />
            <button
              type="button"
              onClick={() => selectedTicker && fetchData(selectedTicker)}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-zinc-200 transition hover:bg-white/[0.08] focus:outline-none focus:ring-2 focus:ring-emerald-300/50"
              aria-label="Actualizar datos"
              title="Actualizar"
            >
              <RefreshCcw aria-hidden="true" className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-5 px-4 py-5 md:px-6 lg:grid-cols-[280px_1fr]">
        <aside className="space-y-4">
          <SystemHealthPanel health={systemHealth} loading={healthLoading} onRefresh={fetchSystemHealth} />
          <OperationalAlertsPanel report={operationalAlerts} />

          <section className="rounded-lg border border-white/10 bg-[#181b1a] p-3">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-medium text-zinc-200">Activos</h2>
              <span className="text-xs text-zinc-500">{assets.length}</span>
            </div>
            <div className="space-y-2">
              {assets.map((asset) => (
                <button
                  key={asset.id}
                  type="button"
                  onClick={() => setSelectedTicker(asset.ticker)}
                  className={`w-full rounded-lg border px-3 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-emerald-300/40 ${
                    selectedTicker === asset.ticker
                      ? 'border-emerald-300/40 bg-emerald-300/10'
                      : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.06]'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-zinc-50">{asset.ticker}</span>
                    <span className="rounded-md bg-zinc-900 px-2 py-1 text-[11px] uppercase text-zinc-400">
                      {asset.asset_class ?? 'asset'}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-sm text-zinc-400">{asset.name ?? 'Sin nombre'}</p>
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
              <Clock3 aria-hidden="true" className="h-4 w-4 text-amber-300" />
              Última lectura
            </div>
            <p className="mt-3 text-sm text-zinc-400">
              {analysisResponse?.timestamp ? formatDateTime(analysisResponse.timestamp) : 'Sin datos'}
            </p>
            {error && (
              <div className="mt-3 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">
                {error}
              </div>
            )}
          </section>

          <RiskProfilePanel
            asset={selectedAsset}
            draft={riskDraft}
            onChange={updateRiskDraft}
            onSave={saveRiskProfile}
            onScopeChange={setRiskScopeType}
            saving={riskSaving}
            scopeType={riskScopeType}
            scopeValue={riskScopeValue}
            source={riskProfile?.source ?? 'default'}
            status={riskStatus}
          />
        </aside>

        <section className="space-y-5">
          <DecisionHeader asset={selectedAsset} analysis={analysis} />

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_0.8fr]">
            <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
              <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-base font-medium text-zinc-100">Precio</h2>
                  <p className="text-sm text-zinc-400">{selectedTicker || 'Selecciona un activo'}</p>
                </div>
                <PriceSnapshot prices={prices} />
              </div>
              {prices.length > 0 ? (
                <Suspense fallback={<ChartLoadingState height={420} />}>
                  <FinancialChart data={prices} />
                </Suspense>
              ) : (
                <div className="flex h-[420px] items-center justify-center rounded-lg border border-dashed border-white/10 text-sm text-zinc-500">
                  Sin histórico disponible
                </div>
              )}
            </section>

            <div className="space-y-5">
              <RiskPanel analysis={analysis} />
              <ProbabilityPanel probabilities={analysis?.probabilities} />
              <ModelPanel analysis={analysis} />
            </div>
          </div>

          <BacktestPanel rows={backtests} />
          <PaperTradingPanel
            onPersist={persistPaperTrading}
            paper={paperTrading}
            runs={paperTradingRuns}
            saving={paperSaving}
            status={paperStatus}
          />
          <FeedbackQualityPanel report={feedbackSummary} />
          <PredictionHistoryPanel rows={predictionHistory} />
        </section>
      </main>
    </div>
  );
}

function SystemHealthPanel({
  health,
  loading,
  onRefresh,
}: {
  health: SystemHealthResponse | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const status = health?.status ?? 'unknown';
  const isOk = status === 'ok';
  const missing = health?.checks.schema?.missing ?? [];

  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {isOk ? (
            <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-emerald-300" />
          ) : (
            <AlertTriangle aria-hidden="true" className="h-4 w-4 text-amber-300" />
          )}
          <h2 className="text-sm font-medium text-zinc-100">Sistema</h2>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/10 text-zinc-300 transition hover:bg-white/5"
          aria-label="Revisar sistema"
          title="Revisar"
        >
          <RefreshCcw aria-hidden="true" className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="space-y-2 text-sm">
        <InfoRow label="Estado" value={isOk ? 'Listo' : status === 'unknown' ? 'Sin lectura' : 'Revisar'} />
        <InfoRow label="Entorno" value={health?.environment ?? 'N/D'} />
        <InfoRow label="Base de datos" value={health?.checks.database?.status ?? 'N/D'} />
        <InfoRow label="Schema" value={health?.checks.schema?.status ?? 'N/D'} />
      </div>
      {missing.length > 0 ? <p className="mt-3 text-xs text-amber-200">Faltan: {missing.join(', ')}</p> : null}
    </section>
  );
}

function OperationalAlertsPanel({ report }: { report: OperationalAlertsResponse | null }) {
  const status = report?.status ?? 'unknown';
  const alerts = report?.alerts ?? [];
  const tone = alertTone(status);

  return (
    <section className={`rounded-lg border p-4 ${tone.surface}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {status === 'ok' ? (
            <CheckCircle2 aria-hidden="true" className={`h-4 w-4 ${tone.icon}`} />
          ) : (
            <AlertTriangle aria-hidden="true" className={`h-4 w-4 ${tone.icon}`} />
          )}
          <h2 className="text-sm font-medium text-zinc-100">Alertas</h2>
        </div>
        <span className={`rounded-md px-2 py-1 text-[11px] uppercase ${tone.badge}`}>{statusLabel(status)}</span>
      </div>

      {!report ? (
        <p className="text-sm text-zinc-500">Sin lectura operativa.</p>
      ) : alerts.length === 0 ? (
        <p className="text-sm text-zinc-400">Sin alertas activas para {report.ticker}.</p>
      ) : (
        <div className="space-y-2">
          {alerts.map((alert) => {
            const itemTone = alertTone(alert.severity);
            return (
              <div key={`${alert.code}-${alert.message}`} className={`rounded-lg border px-3 py-2 ${itemTone.item}`}>
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm text-zinc-100">{alert.message}</p>
                  <span className={`shrink-0 rounded-md px-2 py-1 text-[10px] uppercase ${itemTone.badge}`}>
                    {statusLabel(alert.severity)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-zinc-500">{alert.code}</p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function alertTone(status: string) {
  if (status === 'critical') {
    return {
      surface: 'border-red-300/30 bg-red-300/10',
      item: 'border-red-300/20 bg-red-300/10',
      icon: 'text-red-300',
      badge: 'bg-red-300/15 text-red-100',
    };
  }
  if (status === 'warning') {
    return {
      surface: 'border-amber-300/30 bg-amber-300/10',
      item: 'border-amber-300/20 bg-amber-300/10',
      icon: 'text-amber-300',
      badge: 'bg-amber-300/15 text-amber-100',
    };
  }
  if (status === 'info') {
    return {
      surface: 'border-sky-300/20 bg-sky-300/10',
      item: 'border-sky-300/15 bg-sky-300/10',
      icon: 'text-sky-300',
      badge: 'bg-sky-300/15 text-sky-100',
    };
  }
  if (status === 'ok') {
    return {
      surface: 'border-emerald-300/20 bg-emerald-300/10',
      item: 'border-emerald-300/15 bg-emerald-300/10',
      icon: 'text-emerald-300',
      badge: 'bg-emerald-300/15 text-emerald-100',
    };
  }
  return {
    surface: 'border-white/10 bg-[#181b1a]',
    item: 'border-white/10 bg-black/20',
    icon: 'text-zinc-400',
    badge: 'bg-white/10 text-zinc-300',
  };
}

function statusLabel(status: string) {
  if (status === 'critical') return 'Critica';
  if (status === 'warning') return 'Revision';
  if (status === 'info') return 'Info';
  if (status === 'ok') return 'OK';
  return 'N/D';
}

function RiskProfilePanel({
  asset,
  draft,
  onChange,
  onSave,
  onScopeChange,
  saving,
  scopeType,
  scopeValue,
  source,
  status,
}: {
  asset?: Asset;
  draft: RiskProfile;
  onChange: (field: keyof RiskProfile, value: number | string | boolean) => void;
  onSave: () => void;
  onScopeChange: (scopeType: RiskProfileScopeType) => void;
  saving: boolean;
  scopeType: RiskProfileScopeType;
  scopeValue: string;
  source: string;
  status: string | null;
}) {
  const canUseAssetClass = Boolean(asset?.asset_class);
  const canUseTicker = Boolean(asset?.ticker);

  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <SlidersHorizontal aria-hidden="true" className="h-4 w-4 text-sky-300" />
          <h2 className="text-sm font-medium text-zinc-100">Perfil</h2>
        </div>
        <span className="rounded-md bg-black/20 px-2 py-1 text-[11px] uppercase text-zinc-500">{source}</span>
      </div>

      <div className="space-y-3">
        <div>
          <p className="mb-2 text-xs text-zinc-500">Alcance</p>
          <div className="grid grid-cols-3 gap-1 rounded-lg bg-black/20 p-1">
            <ScopeButton active={scopeType === 'default'} label="Default" onClick={() => onScopeChange('default')} />
            <ScopeButton
              active={scopeType === 'asset_class'}
              disabled={!canUseAssetClass}
              label={asset?.asset_class ?? 'Clase'}
              onClick={() => onScopeChange('asset_class')}
            />
            <ScopeButton
              active={scopeType === 'ticker'}
              disabled={!canUseTicker}
              label={asset?.ticker ?? 'Ticker'}
              onClick={() => onScopeChange('ticker')}
            />
          </div>
          <p className="mt-2 truncate text-xs text-zinc-500">{scopeLabel(scopeType, scopeValue)}</p>
        </div>

        <label className="block text-xs text-zinc-500">
          Nombre
          <input
            type="text"
            value={draft.name}
            onChange={(event) => onChange('name', event.target.value)}
            className="mt-1 h-9 w-full rounded-lg border border-white/10 bg-black/20 px-3 text-sm text-zinc-100 outline-none transition focus:border-sky-300/40"
          />
        </label>

        <PercentField label="Posicion max" value={draft.max_position_size} onChange={(value) => onChange('max_position_size', value)} />
        <PercentField label="Confianza min" value={draft.min_confidence_to_trade} onChange={(value) => onChange('min_confidence_to_trade', value)} />
        <PercentField label="Riesgo max" value={draft.max_expected_risk} onChange={(value) => onChange('max_expected_risk', value)} />
        <PercentField label="Stop" value={draft.stop_loss} onChange={(value) => onChange('stop_loss', value)} />
        <PercentField label="Objetivo" value={draft.take_profit} onChange={(value) => onChange('take_profit', value)} />

        <label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-zinc-300">
          Permitir short
          <input
            type="checkbox"
            checked={draft.allow_short}
            onChange={(event) => onChange('allow_short', event.target.checked)}
            className="h-4 w-4 accent-emerald-300"
          />
        </label>

        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-sky-300/30 bg-sky-300/10 px-3 text-sm font-medium text-sky-100 transition hover:bg-sky-300/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Save aria-hidden="true" className="h-4 w-4" />
          {saving ? 'Guardando' : 'Guardar perfil'}
        </button>
      </div>

      {status && <p className="mt-3 text-sm text-zinc-400">{status}</p>}
    </section>
  );
}

function ScopeButton({
  active,
  disabled,
  label,
  onClick,
}: {
  active: boolean;
  disabled?: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`h-8 min-w-0 truncate rounded-md px-2 text-xs transition ${
        active ? 'bg-sky-300/15 text-sky-100' : 'text-zinc-400 hover:text-zinc-100'
      } disabled:cursor-not-allowed disabled:opacity-40`}
      title={label}
    >
      {label}
    </button>
  );
}

function scopeLabel(scopeType: RiskProfileScopeType, scopeValue: string) {
  if (scopeType === 'ticker') return `Ticker ${scopeValue || 'sin activo'}`;
  if (scopeType === 'asset_class') return `Clase ${scopeValue || 'sin clase'}`;
  return 'Perfil global del usuario';
}

function PercentField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="grid grid-cols-[1fr_84px] items-center gap-3 text-xs text-zinc-500">
      <span>{label}</span>
      <span className="relative">
        <input
          type="number"
          min="0"
          max="100"
          step="1"
          value={percentInputValue(value)}
          onChange={(event) => onChange(Number(event.target.value || 0) / 100)}
          className="h-9 w-full rounded-lg border border-white/10 bg-black/20 pl-3 pr-7 text-right text-sm text-zinc-100 outline-none transition focus:border-sky-300/40"
        />
        <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-zinc-500">%</span>
      </span>
    </label>
  );
}

function DecisionHeader({ asset, analysis }: { asset?: Asset; analysis: Analysis | null }) {
  const signal = analysis?.signal ?? 'HOLD';
  const tone = signalTone(signal);
  const reasons = analysis?.reasons ?? (analysis?.reason ? [analysis.reason] : []);
  const baseSignal = analysis?.risk?.pre_risk_action;
  const isUserProfile = analysis?.risk?.profile_source === 'user';
  const wasAdjusted = Boolean(baseSignal && baseSignal !== signal);

  return (
    <section className={`rounded-lg border p-5 ${tone.surface}`}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_220px]">
        <div>
          <div className="mb-4 flex items-center gap-3">
            <div className={`flex h-12 w-12 items-center justify-center rounded-lg ${tone.iconBg}`}>
              <SignalIcon signal={signal} className={`h-6 w-6 ${tone.icon}`} />
            </div>
            <div>
              <p className="text-sm text-zinc-400">{asset?.name ?? 'Activo seleccionado'}</p>
              <h2 className="text-2xl font-semibold tracking-normal text-zinc-50">{asset?.ticker ?? '...'}</h2>
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-4">
            <div>
              <p className="text-sm text-zinc-400">Decisión</p>
              <p className={`text-4xl font-semibold tracking-normal ${tone.text}`}>{signal}</p>
            </div>
            {baseSignal && <MetricInline label="Modelo base" value={baseSignal} />}
            <MetricInline label="Confianza" value={formatPercent(analysis?.confidence)} />
            <MetricInline label="Horizonte" value={analysis?.model?.horizon ? `${analysis.model.horizon}d` : 'N/D'} />
          </div>

          {(wasAdjusted || isUserProfile) && (
            <RiskAdjustmentNotice
              baseSignal={baseSignal ?? signal}
              finalSignal={signal}
              profileName={analysis?.risk?.profile_name}
              reasons={analysis?.risk?.blocked_reasons ?? []}
              userProfile={isUserProfile}
            />
          )}

          {reasons.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {reasons.map((reason) => (
                <span key={reason} className="rounded-md border border-white/10 bg-black/20 px-2 py-1 text-xs text-zinc-300">
                  {reason}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-1">
          <MetricBox icon={ShieldCheck} label="Posición" value={formatPercent(analysis?.risk?.position_size)} />
          <MetricBox icon={Gauge} label="Riesgo esperado" value={formatPercent(analysis?.expected_risk ?? null)} />
        </div>
      </div>
    </section>
  );
}

function RiskAdjustmentNotice({
  baseSignal,
  finalSignal,
  profileName,
  reasons,
  userProfile,
}: {
  baseSignal: Signal;
  finalSignal: Signal;
  profileName?: string | null;
  reasons: string[];
  userProfile: boolean;
}) {
  const adjusted = baseSignal !== finalSignal;
  const title = adjusted ? `Modelo ${baseSignal} -> decision ${finalSignal}` : `Decision con perfil ${profileName ?? 'default'}`;
  const detail = adjusted
    ? 'La accion final fue ajustada por las reglas de riesgo antes de mostrarse como recomendacion operativa.'
    : 'La recomendacion usa los limites del perfil configurado para tamano, stop, objetivo y bloqueos.';

  return (
    <div className="mt-4 rounded-lg border border-sky-300/20 bg-sky-300/10 p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-sky-100">{title}</p>
          <p className="mt-1 text-sm text-sky-100/70">{detail}</p>
        </div>
        <span className="shrink-0 rounded-md bg-black/20 px-2 py-1 text-xs text-sky-100">
          {userProfile ? `Perfil ${profileName ?? 'usuario'}` : 'Politica global'}
        </span>
      </div>

      {reasons.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {reasons.map((reason) => (
            <span key={reason} className="rounded-md border border-sky-200/15 bg-black/20 px-2 py-1 text-xs text-sky-100/80">
              {humanizeReason(reason)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function RiskPanel({ analysis }: { analysis: Analysis | null }) {
  const risk = analysis?.risk;
  const blocked = risk?.blocked_reasons ?? [];
  const profileLabel = risk?.profile_source === 'user' ? risk.profile_name || 'usuario' : 'global';

  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck aria-hidden="true" className="h-4 w-4 text-emerald-300" />
          <h2 className="text-sm font-medium text-zinc-100">Riesgo</h2>
        </div>
        {blocked.length > 0 ? (
          <span className="rounded-md bg-amber-300/10 px-2 py-1 text-xs text-amber-200">Bloqueada</span>
        ) : (
          <span className="rounded-md bg-emerald-300/10 px-2 py-1 text-xs text-emerald-200">Activa</span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3">
        <SmallMetric label="Tamaño" value={formatPercent(risk?.position_size)} />
        <SmallMetric label="Stop" value={formatPercent(risk?.stop_loss)} />
        <SmallMetric label="Objetivo" value={formatPercent(risk?.take_profit)} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <SmallMetric label="Perfil" value={profileLabel} />
        <SmallMetric label="Base" value={risk?.pre_risk_action ?? analysis?.signal ?? 'N/D'} />
      </div>

      {blocked.length > 0 && (
        <div className="mt-4 space-y-2">
          {blocked.map((reason) => (
            <div key={reason} className="flex items-center gap-2 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
              <AlertTriangle aria-hidden="true" className="h-4 w-4" />
              {humanizeReason(reason)}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ProbabilityPanel({ probabilities }: { probabilities?: Record<string, number> }) {
  const entries = Object.entries(probabilities ?? { BUY: 0, HOLD: 0, SELL: 0 });

  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-4 flex items-center gap-2">
        <BarChart3 aria-hidden="true" className="h-4 w-4 text-sky-300" />
        <h2 className="text-sm font-medium text-zinc-100">Probabilidades</h2>
      </div>
      <div className="space-y-3">
        {entries.map(([label, value]) => (
          <div key={label}>
            <div className="mb-1 flex items-center justify-between text-sm">
              <span className="text-zinc-300">{label}</span>
              <span className="font-medium text-zinc-100">{formatPercent(value)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
              <div className={`h-full ${probabilityColor(label)}`} style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ModelPanel({ analysis }: { analysis: Analysis | null }) {
  const model = analysis?.model;
  const feedback = analysis?.feedback;

  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-4 flex items-center gap-2">
        <Brain aria-hidden="true" className="h-4 w-4 text-violet-300" />
        <h2 className="text-sm font-medium text-zinc-100">Modelo</h2>
      </div>
      <div className="space-y-3 text-sm">
        <InfoRow label="Nombre" value={model?.name ?? 'Indicadores'} />
        <InfoRow label="Versión" value={model?.version ?? 'Fallback'} />
        <InfoRow label="Feature set" value={model?.feature_set ?? 'N/D'} />
        <InfoRow label="Label" value={model?.label_method ?? 'N/D'} />
        <InfoRow label="Resultado" value={feedbackLabel(feedback)} />
      </div>
    </section>
  );
}

function BacktestPanel({ rows }: { rows: BacktestSummaryRow[] }) {
  const latest = rows[0];

  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <BarChart3 aria-hidden="true" className="h-4 w-4 text-sky-300" />
          <h2 className="text-sm font-medium text-zinc-100">Backtests</h2>
        </div>
        <span className="text-xs text-zinc-500">{rows.length}</span>
      </div>

      {!latest ? (
        <div className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-sm text-zinc-500">
          Sin backtests persistidos
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SmallMetric label="Retorno" value={formatPercent(latest.metrics?.total_return)} />
            <SmallMetric label="Drawdown" value={formatPercent(latest.metrics?.max_drawdown)} />
            <SmallMetric label="Profit factor" value={formatNumber(latest.metrics?.profit_factor)} />
            <SmallMetric label="Trades" value={formatCount(latest.metrics?.active_trade_count)} />
          </div>

          <div className="overflow-hidden rounded-lg border border-white/10">
            <div className="grid grid-cols-[1fr_88px_88px_72px] gap-3 border-b border-white/10 bg-black/20 px-3 py-2 text-xs text-zinc-500 md:grid-cols-[1fr_100px_100px_92px_96px]">
              <span>Modelo</span>
              <span>Retorno</span>
              <span>Drawdown</span>
              <span>PF</span>
              <span className="hidden md:block">Fecha</span>
            </div>
            <div className="divide-y divide-white/10">
              {rows.map((row) => (
                <div
                  key={row.id ?? row.name}
                  className="grid grid-cols-[1fr_88px_88px_72px] gap-3 px-3 py-3 text-sm md:grid-cols-[1fr_100px_100px_92px_96px]"
                >
                  <span className="min-w-0 truncate text-zinc-200">
                    {row.model?.name ?? 'Modelo'}:{row.model?.version ?? row.name ?? 'N/D'}
                  </span>
                  <span className={metricTone(row.metrics?.total_return)}>{formatPercent(row.metrics?.total_return)}</span>
                  <span className="text-zinc-300">{formatPercent(row.metrics?.max_drawdown)}</span>
                  <span className="text-zinc-300">{formatNumber(row.metrics?.profit_factor)}</span>
                  <span className="hidden text-zinc-400 md:block">{row.created_at ? formatShortDate(row.created_at) : 'N/D'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function PaperTradingPanel({
  onPersist,
  paper,
  runs,
  saving,
  status,
}: {
  onPersist: () => void;
  paper: PaperTradingResponse | null;
  runs: PaperTradingRunRow[];
  saving: boolean;
  status: string | null;
}) {
  const metrics = paper?.metrics;
  const recentSignals = (paper?.timeline ?? []).slice(-5).reverse();
  const recentTrades = (paper?.timeline ?? [])
    .filter((row) => Math.abs(row.exposure_delta ?? 0) > 0)
    .slice(-5)
    .reverse();

  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity aria-hidden="true" className="h-4 w-4 text-emerald-300" />
          <h2 className="text-sm font-medium text-zinc-100">Paper trading</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded-md px-2 py-1 text-xs ${paperPositionTone(metrics?.open_position)}`}>
            {metrics?.open_position ?? 'FLAT'}
          </span>
          <button
            type="button"
            onClick={onPersist}
            disabled={!paper || saving}
            className="inline-flex h-8 items-center gap-2 rounded-md border border-white/10 px-3 text-xs text-zinc-200 transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save aria-hidden="true" className="h-3.5 w-3.5" />
            {saving ? 'Guardando' : 'Guardar'}
          </button>
        </div>
      </div>
      {status ? <p className="mb-4 text-xs text-zinc-400">{status}</p> : null}

      {!paper ? (
        <div className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-sm text-zinc-500">
          Sin simulacion disponible
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <SmallMetric label="Equity" value={formatCurrencyOrNA(metrics?.final_equity ?? metrics?.initial_capital)} />
            <SmallMetric label="Retorno" value={formatPercent(metrics?.total_return)} />
            <SmallMetric label="Drawdown" value={formatPercent(metrics?.max_drawdown)} />
            <SmallMetric label="Trades" value={formatCount(metrics?.trade_count)} />
            <SmallMetric label="Exposicion" value={formatPercent(metrics?.average_abs_exposure)} />
          </div>

          <div className="rounded-lg border border-white/10 p-3">
            <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-sm font-medium text-zinc-100">Curva de equity</h3>
                <p className="text-xs text-zinc-500">
                  {formatCount(metrics?.signal_count)} senales, {formatCount(metrics?.active_signal_count)} activas
                </p>
              </div>
              <span className="text-xs text-zinc-500">Costo {formatNumber((metrics?.fee_bps ?? 0) + (metrics?.slippage_bps ?? 0))} bps</span>
            </div>
            <Suspense fallback={<ChartLoadingState height={260} />}>
              <EquityCurveChart data={paper.timeline} />
            </Suspense>
          </div>

          {recentTrades.length > 0 ? (
            <div className="overflow-hidden rounded-lg border border-white/10">
              <div className="grid grid-cols-[78px_64px_1fr_78px] gap-3 border-b border-white/10 bg-black/20 px-3 py-2 text-xs text-zinc-500 md:grid-cols-[100px_80px_92px_92px_1fr]">
                <span>Fecha</span>
                <span>Accion</span>
                <span className="hidden md:block">Delta</span>
                <span>Costo</span>
                <span>Equity</span>
              </div>
              <div className="divide-y divide-white/10">
                {recentTrades.map((row, index) => {
                  const action = row.action ?? 'HOLD';
                  return (
                    <div
                      key={`trade-${row.timestamp ?? index}-${action}`}
                      className="grid grid-cols-[78px_64px_1fr_78px] gap-3 px-3 py-3 text-sm md:grid-cols-[100px_80px_92px_92px_1fr]"
                    >
                      <span className="text-zinc-400">{row.timestamp ? formatShortDate(row.timestamp) : 'N/D'}</span>
                      <span className={`font-medium ${signalTone(action).text}`}>{action}</span>
                      <span className="hidden text-zinc-300 md:block">{formatPercent(row.exposure_delta)}</span>
                      <span className="text-zinc-300">{formatBasisPoints(row.cost)}</span>
                      <span className="text-zinc-200">{formatCurrencyOrNA(row.equity)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {recentSignals.length === 0 ? (
            <div className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-sm text-zinc-500">
              Sin senales simuladas
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border border-white/10">
              <div className="grid grid-cols-[78px_64px_1fr_78px] gap-3 border-b border-white/10 bg-black/20 px-3 py-2 text-xs text-zinc-500 md:grid-cols-[100px_80px_92px_1fr_96px]">
                <span>Fecha</span>
                <span>Accion</span>
                <span className="hidden md:block">Precio</span>
                <span>Posicion</span>
                <span>Equity</span>
              </div>
              <div className="divide-y divide-white/10">
                {recentSignals.map((row, index) => {
                  const action = row.action ?? 'HOLD';
                  return (
                    <div
                      key={`signal-${row.timestamp ?? index}-${action}`}
                      className="grid grid-cols-[78px_64px_1fr_78px] gap-3 px-3 py-3 text-sm md:grid-cols-[100px_80px_92px_1fr_96px]"
                    >
                      <span className="text-zinc-400">{row.timestamp ? formatShortDate(row.timestamp) : 'N/D'}</span>
                      <span className={`font-medium ${signalTone(action).text}`}>{action}</span>
                      <span className="hidden text-zinc-300 md:block">{formatCurrencyOrNA(row.price)}</span>
                      <span className="min-w-0 truncate text-zinc-300">{row.position_state ?? 'FLAT'}</span>
                      <span className="text-zinc-200">{formatCurrencyOrNA(row.equity)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <PaperTradingRunsPanel rows={runs} />
        </div>
      )}
    </section>
  );
}

function PaperTradingRunsPanel({ rows }: { rows: PaperTradingRunRow[] }) {
  const best = [...rows].sort((a, b) => (b.metrics?.total_return ?? -Infinity) - (a.metrics?.total_return ?? -Infinity))[0];

  return (
    <div className="rounded-lg border border-white/10 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-zinc-100">Corridas guardadas</h3>
          <p className="text-xs text-zinc-500">
            {rows.length > 0 && best ? `Mejor retorno: ${formatPercent(best.metrics?.total_return)}` : 'Sin historial persistido'}
          </p>
        </div>
        <span className="text-xs text-zinc-500">{rows.length}</span>
      </div>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-sm text-zinc-500">
          Guarda una corrida para comparar resultados.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-white/10">
          <div className="grid grid-cols-[1fr_76px_76px_64px] gap-3 border-b border-white/10 bg-black/20 px-3 py-2 text-xs text-zinc-500 md:grid-cols-[1fr_92px_92px_76px_96px_88px]">
            <span>Modelo</span>
            <span>Retorno</span>
            <span>Drawdown</span>
            <span>Trades</span>
            <span className="hidden md:block">Equity</span>
            <span className="hidden md:block">Fecha</span>
          </div>
          <div className="divide-y divide-white/10">
            {rows.map((row) => (
              <div
                key={row.id ?? row.name}
                className="grid grid-cols-[1fr_76px_76px_64px] gap-3 px-3 py-3 text-sm md:grid-cols-[1fr_92px_92px_76px_96px_88px]"
              >
                <span className="min-w-0 truncate text-zinc-200">
                  {row.model?.name ?? row.params?.model_name ?? 'Modelo'}:
                  {row.model?.version ?? row.params?.model_version ?? row.name ?? 'N/D'}
                </span>
                <span className={metricTone(row.metrics?.total_return)}>{formatPercent(row.metrics?.total_return)}</span>
                <span className="text-zinc-300">{formatPercent(row.metrics?.max_drawdown)}</span>
                <span className="text-zinc-300">{formatCount(row.metrics?.trade_count)}</span>
                <span className="hidden text-zinc-300 md:block">{formatCurrencyOrNA(row.metrics?.final_equity)}</span>
                <span className="hidden text-zinc-400 md:block">{row.created_at ? formatShortDate(row.created_at) : 'N/D'}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FeedbackQualityPanel({ report }: { report: FeedbackSummaryResponse | null }) {
  const summary = report?.summary;
  const actionRows = report?.by_action ?? [];

  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck aria-hidden="true" className="h-4 w-4 text-sky-300" />
          <h2 className="text-sm font-medium text-zinc-100">Calidad del modelo</h2>
        </div>
        <span className="text-xs text-zinc-500">{formatCount(summary?.evaluated_predictions)}</span>
      </div>

      {!report || !summary?.evaluated_predictions ? (
        <div className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-sm text-zinc-500">
          Sin feedback evaluado todavia
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SmallMetric label="Acierto" value={formatPercent(summary.accuracy)} />
            <SmallMetric label="Confianza" value={formatPercent(summary.mean_confidence)} />
            <SmallMetric label="Retorno medio" value={formatPercent(summary.mean_outcome_return)} />
            <SmallMetric label="Retorno total" value={formatPercent(summary.total_outcome_return)} />
          </div>

          <div className="overflow-hidden rounded-lg border border-white/10">
            <div className="grid grid-cols-[80px_72px_82px_1fr] gap-3 border-b border-white/10 bg-black/20 px-3 py-2 text-xs text-zinc-500 md:grid-cols-[92px_80px_92px_96px_1fr]">
              <span>Accion</span>
              <span>Casos</span>
              <span>Acierto</span>
              <span className="hidden md:block">Confianza</span>
              <span>Retorno</span>
            </div>
            <div className="divide-y divide-white/10">
              {actionRows.map((row) => {
                const action = row.action ?? 'HOLD';
                return (
                  <div
                    key={action}
                    className="grid grid-cols-[80px_72px_82px_1fr] gap-3 px-3 py-3 text-sm md:grid-cols-[92px_80px_92px_96px_1fr]"
                  >
                    <span className={`font-medium ${signalTone(action).text}`}>{action}</span>
                    <span className="text-zinc-300">{formatCount(row.count)}</span>
                    <span className="text-zinc-300">{formatPercent(row.accuracy)}</span>
                    <span className="hidden text-zinc-300 md:block">{formatPercent(row.mean_confidence)}</span>
                    <span className={metricTone(row.total_outcome_return)}>{formatPercent(row.total_outcome_return)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function PredictionHistoryPanel({ rows }: { rows: PredictionAuditRow[] }) {
  return (
    <section className="rounded-lg border border-white/10 bg-[#181b1a] p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <History aria-hidden="true" className="h-4 w-4 text-emerald-300" />
          <h2 className="text-sm font-medium text-zinc-100">Auditoria</h2>
        </div>
        <span className="text-xs text-zinc-500">{rows.length}</span>
      </div>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-sm text-zinc-500">
          Sin predicciones historicas
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-white/10">
          <div className="grid grid-cols-[88px_1fr_88px_96px] gap-3 border-b border-white/10 bg-black/20 px-3 py-2 text-xs text-zinc-500 md:grid-cols-[116px_92px_1fr_96px_112px_120px]">
            <span>Fecha</span>
            <span className="hidden md:block">Accion</span>
            <span>Modelo</span>
            <span>Confianza</span>
            <span className="hidden md:block">Resultado</span>
            <span className="hidden md:block">Riesgo</span>
          </div>
          <div className="divide-y divide-white/10">
            {rows.map((row, index) => {
              const blocked = row.risk?.blocked_reasons ?? [];
              return (
                <div
                  key={`${row.prediction_id ?? row.timestamp ?? index}`}
                  className="grid grid-cols-[88px_1fr_88px_96px] gap-3 px-3 py-3 text-sm md:grid-cols-[116px_92px_1fr_96px_112px_120px]"
                >
                  <span className="text-zinc-400">{row.timestamp ? formatShortDate(row.timestamp) : 'N/D'}</span>
                  <span className={`hidden font-medium md:block ${signalTone(row.action).text}`}>{row.action}</span>
                  <span className="min-w-0 truncate text-zinc-200">
                    {row.model?.name ?? 'Modelo'}:{row.model?.version ?? 'N/D'}
                  </span>
                  <span className="text-zinc-200">{formatPercent(row.confidence)}</span>
                  <span className="hidden text-zinc-300 md:block">{feedbackLabel(row.feedback)}</span>
                  <span className="hidden truncate text-zinc-400 md:block">
                    {blocked.length > 0 ? blocked.map(humanizeReason).join(', ') : formatPercent(row.risk?.position_size)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function PriceSnapshot({ prices }: { prices: PricePoint[] }) {
  const latest = prices[0];
  if (!latest) {
    return <span className="text-sm text-zinc-500">Sin precio</span>;
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <CircleDollarSign aria-hidden="true" className="h-4 w-4 text-emerald-300" />
      <span className="text-sm font-medium text-zinc-100">{formatCurrency(Number(latest.close))}</span>
    </div>
  );
}

function StatusPill({ source, loading }: { source?: string; loading: boolean }) {
  if (loading) {
    return (
      <span className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-zinc-300">
        <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-sky-300" />
        Actualizando
      </span>
    );
  }

  const isPrediction = source === 'prediction';
  const isDemo = source === 'demo_indicators';
  return (
    <span className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-zinc-300">
      {isPrediction ? (
        <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-emerald-300" />
      ) : isDemo ? (
        <AlertTriangle aria-hidden="true" className="h-4 w-4 text-amber-300" />
      ) : (
        <MinusCircle aria-hidden="true" className="h-4 w-4 text-amber-300" />
      )}
      {isPrediction ? 'Modelo activo' : isDemo ? 'Datos demo' : 'Indicadores'}
    </span>
  );
}

function MetricInline({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-sm text-zinc-400">{label}</p>
      <p className="text-lg font-medium text-zinc-100">{value}</p>
    </div>
  );
}

function MetricBox({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <Icon aria-hidden="true" className="mb-2 h-4 w-4 text-zinc-400" />
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-lg font-medium text-zinc-100">{value}</p>
    </div>
  );
}

function SmallMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 text-sm font-medium text-zinc-100">{value}</p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-white/5 pb-2 last:border-b-0 last:pb-0">
      <span className="text-zinc-500">{label}</span>
      <span className="truncate text-right text-zinc-200">{value}</span>
    </div>
  );
}

function ChartLoadingState({ height }: { height: number }) {
  return (
    <div
      className="flex items-center justify-center rounded-lg border border-dashed border-white/10 text-sm text-zinc-500"
      style={{ height }}
    >
      Cargando grafico
    </div>
  );
}

function signalTone(signal: Signal) {
  if (signal === 'BUY') {
    return {
      surface: 'border-emerald-300/25 bg-emerald-300/[0.07]',
      text: 'text-emerald-300',
      icon: 'text-emerald-200',
      iconBg: 'bg-emerald-300/15',
    };
  }
  if (signal === 'SELL') {
    return {
      surface: 'border-red-300/25 bg-red-300/[0.07]',
      text: 'text-red-300',
      icon: 'text-red-200',
      iconBg: 'bg-red-300/15',
    };
  }
  return {
    surface: 'border-amber-300/25 bg-amber-300/[0.07]',
    text: 'text-amber-200',
    icon: 'text-amber-200',
    iconBg: 'bg-amber-300/15',
  };
}

function SignalIcon({ signal, className }: { signal: Signal; className: string }) {
  if (signal === 'BUY') return <TrendingUp aria-hidden="true" className={className} />;
  if (signal === 'SELL') return <TrendingDown aria-hidden="true" className={className} />;
  return <MinusCircle aria-hidden="true" className={className} />;
}

function probabilityColor(label: string) {
  if (label === 'BUY') return 'bg-emerald-300';
  if (label === 'SELL') return 'bg-red-300';
  return 'bg-amber-300';
}

function formatPercent(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/D';
  return `${(value * 100).toFixed(0)}%`;
}

function percentInputValue(value: number) {
  if (Number.isNaN(value)) return 0;
  return Math.round(value * 100);
}

function formatNumber(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/D';
  return value.toFixed(2);
}

function formatBasisPoints(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/D';
  return `${(value * 10_000).toFixed(1)} bps`;
}

function formatCount(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/D';
  return String(Math.round(value));
}

function metricTone(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-zinc-300';
  if (value > 0) return 'text-emerald-300';
  if (value < 0) return 'text-red-300';
  return 'text-zinc-300';
}

function paperPositionTone(position?: string | null) {
  if (position === 'LONG') return 'bg-emerald-300/10 text-emerald-200';
  if (position === 'SHORT') return 'bg-red-300/10 text-red-200';
  return 'bg-zinc-800 text-zinc-300';
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

function formatCurrencyOrNA(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/D';
  return formatCurrency(value);
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function formatShortDate(value: string) {
  return new Intl.DateTimeFormat('es-MX', {
    month: 'short',
    day: 'numeric',
  }).format(new Date(value));
}

function humanizeReason(reason: string) {
  const map: Record<string, string> = {
    confidence_below_trade_threshold: 'Confianza insuficiente',
    short_disabled: 'Ventas en corto desactivadas',
    expected_risk_above_limit: 'Riesgo esperado sobre el límite',
  };
  return map[reason] ?? reason.replaceAll('_', ' ');
}

function feedbackLabel(feedback?: FeedbackMetadata) {
  if (!feedback || feedback.actual_label === undefined || feedback.actual_label === null) return 'Pendiente';
  if (feedback.is_correct === true) return `Acertó (${feedback.actual_label})`;
  if (feedback.is_correct === false) return `Falló (${feedback.actual_label})`;
  return feedback.actual_label;
}

export default App;
