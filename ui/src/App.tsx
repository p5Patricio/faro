import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import axios from 'axios';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Brain,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  Gauge,
  History,
  Inbox,
  MinusCircle,
  Pause,
  Play,
  RefreshCcw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import type { PricePoint } from './components/FinancialChart';
import { AssetSwitcher, Watchlist } from './components/AssetSwitcher.tsx';
import { useAssetMemory } from './hooks/useAssetMemory.ts';
import { EmptyState } from './components/ui/EmptyState.tsx';
import { SkeletonLines, SkeletonMetrics, SkeletonTable } from './components/ui/Skeleton.tsx';
import { SegmentedControl, type SegmentOption } from './components/ui/SegmentedControl.tsx';
import { Gauge as ConfidenceGauge } from './components/ui/Gauge.tsx';
import { ProbabilityBar } from './components/ui/ProbabilityBar.tsx';
import { SignalSparkline } from './components/ui/SignalSparkline.tsx';
import { Drawer } from './components/ui/Drawer.tsx';
import { Popover } from './components/ui/Popover.tsx';
import { DataTable } from './components/ui/DataTable.tsx';
import { InfoLabel } from './components/ui/Tooltip.tsx';

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

type TabKey = 'resumen' | 'precio' | 'riesgo' | 'backtests' | 'paper' | 'auditoria';

const TAB_STORAGE_KEY = 'faro:active-tab';
const AUTO_REFRESH_KEY = 'faro:auto-refresh';
const AUTO_REFRESH_MS = 60_000;
const TAB_KEYS: TabKey[] = ['resumen', 'precio', 'riesgo', 'backtests', 'paper', 'auditoria'];

function readTab(): TabKey {
  try {
    const stored = window.localStorage.getItem(TAB_STORAGE_KEY);
    if (stored && (TAB_KEYS as string[]).includes(stored)) return stored as TabKey;
  } catch {
    /* ignore */
  }
  return 'resumen';
}

function readAutoRefresh(): boolean {
  try {
    return window.localStorage.getItem(AUTO_REFRESH_KEY) === '1';
  } catch {
    return false;
  }
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
  const [failedSections, setFailedSections] = useState<Set<string>>(() => new Set());
  const [systemHealth, setSystemHealth] = useState<SystemHealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [riskProfile, setRiskProfile] = useState<RiskProfileResponse | null>(null);
  const [riskDraft, setRiskDraft] = useState<RiskProfile>(DEFAULT_RISK_PROFILE);
  const [riskScopeType, setRiskScopeType] = useState<RiskProfileScopeType>('default');
  const [riskStatus, setRiskStatus] = useState<string | null>(null);
  const [riskSaving, setRiskSaving] = useState(false);

  const assetMemory = useAssetMemory();
  const firstLoad = loading && !analysisResponse;

  const [activeTab, setActiveTab] = useState<TabKey>(readTab);
  const [riskDrawerOpen, setRiskDrawerOpen] = useState(false);
  const editRiskButtonRef = useRef<HTMLButtonElement>(null);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(readAutoRefresh);
  const [lastFetchAt, setLastFetchAt] = useState<number | null>(null);

  const changeTab = useCallback((tab: TabKey) => {
    setActiveTab(tab);
    try {
      window.localStorage.setItem(TAB_STORAGE_KEY, tab);
    } catch {
      /* storage unavailable — tab just won't persist */
    }
  }, []);

  const toggleAutoRefresh = useCallback(() => {
    setAutoRefresh((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(AUTO_REFRESH_KEY, next ? '1' : '0');
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

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
    const failed = new Set<string>();
    const get = async <T,>(section: string, url: string, fallback: T): Promise<T> => {
      try {
        const response = await axios.get<T>(url);
        return response.data;
      } catch {
        failed.add(section);
        return fallback;
      }
    };
    try {
      const [
        pricesData,
        analysisData,
        historyData,
        feedbackData,
        alertsData,
        backtestsData,
        paperData,
        paperRunsData,
      ] = await Promise.all([
        get<PricePoint[]>('prices', `${API_BASE_URL}/prices/${ticker}?limit=240`, []),
        get<AnalysisResponse | null>('analysis', `${API_BASE_URL}/analysis/${ticker}`, null),
        get<PredictionAuditRow[]>('history', `${API_BASE_URL}/predictions/${ticker}?limit=8`, []),
        get<FeedbackSummaryResponse | null>('feedback', `${API_BASE_URL}/feedback/${ticker}?limit=250`, null),
        get<OperationalAlertsResponse | null>('alerts', `${API_BASE_URL}/alerts/${ticker}`, null),
        get<BacktestSummaryRow[]>('backtests', `${API_BASE_URL}/backtests/${ticker}?limit=5`, []),
        get<PaperTradingResponse | null>('paper', `${API_BASE_URL}/paper-trading/${ticker}?limit=250`, null),
        get<PaperTradingRunRow[]>('paperRuns', `${API_BASE_URL}/paper-trading-runs/${ticker}?limit=8`, []),
      ]);
      setPrices(pricesData);
      setAnalysisResponse(analysisData);
      setPredictionHistory(historyData);
      setFeedbackSummary(feedbackData);
      setOperationalAlerts(alertsData);
      setBacktests(backtestsData);
      setPaperTrading(paperData);
      setPaperTradingRuns(paperRunsData);
      setPaperStatus(null);
      setFailedSections(failed);
      if (failed.has('analysis') && failed.has('prices')) {
        setError('No se pudo contactar la API.');
      }
    } finally {
      setLoading(false);
      setLastFetchAt(Date.now());
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

    // Debounce so arrow-spamming the switcher doesn't fire a request per keystroke.
    const timer = window.setTimeout(() => {
      void fetchData(selectedTicker);
    }, 250);

    return () => {
      window.clearTimeout(timer);
    };
  }, [fetchData, selectedTicker]);

  useEffect(() => {
    if (!autoRefresh || !selectedTicker) return;
    const id = window.setInterval(() => {
      void fetchData(selectedTicker);
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [autoRefresh, selectedTicker, fetchData]);

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
  const activeMinConfidence =
    riskProfile?.profile.min_confidence_to_trade ?? DEFAULT_RISK_PROFILE.min_confidence_to_trade;
  const signalHistory = useMemo(
    () => [...predictionHistory].reverse().map((row) => row.action),
    [predictionHistory],
  );
  const chartSignals = useMemo(
    () => predictionHistory.map((row) => ({ timestamp: row.timestamp, action: row.action })),
    [predictionHistory],
  );

  const priceChart = (
    <PricePanel
      prices={prices}
      ticker={selectedTicker}
      signals={chartSignals}
      failed={failedSections.has('prices')}
      onRetry={() => selectedTicker && fetchData(selectedTicker)}
    />
  );

  const tabOptions: SegmentOption<TabKey>[] = [
    { value: 'resumen', label: 'Resumen' },
    { value: 'precio', label: 'Precio' },
    { value: 'riesgo', label: 'Riesgo' },
    { value: 'backtests', label: 'Backtests', badge: backtests.length || undefined },
    { value: 'paper', label: 'Paper trading' },
    { value: 'auditoria', label: 'Auditoría', badge: predictionHistory.length || undefined },
  ];

  let tabContent: ReactNode;
  if (activeTab === 'resumen') {
    tabContent = (
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.5fr_1fr]">
        {priceChart}
        <div className="space-y-5">
          <ModelPanel analysis={analysis} />
          <RiskPanel analysis={analysis} onEdit={() => setRiskDrawerOpen(true)} />
        </div>
      </div>
    );
  } else if (activeTab === 'precio') {
    tabContent = priceChart;
  } else if (activeTab === 'riesgo') {
    tabContent = (
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <RiskPanel analysis={analysis} onEdit={() => setRiskDrawerOpen(true)} />
        <ModelPanel analysis={analysis} />
      </div>
    );
  } else if (activeTab === 'backtests') {
    tabContent = <BacktestPanel rows={backtests} failed={failedSections.has('backtests')} />;
  } else if (activeTab === 'paper') {
    tabContent = (
      <PaperTradingPanel
        onPersist={persistPaperTrading}
        paper={paperTrading}
        runs={paperTradingRuns}
        saving={paperSaving}
        status={paperStatus}
        failed={failedSections.has('paper')}
      />
    );
  } else {
    tabContent = (
      <div className="space-y-5">
        <PredictionHistoryPanel rows={predictionHistory} failed={failedSections.has('history')} />
        <FeedbackQualityPanel report={feedbackSummary} failed={failedSections.has('feedback')} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-canvas text-slate-100">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-md focus:border focus:border-cobalt/50 focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:text-slate-100"
      >
        Saltar al contenido
      </a>
      <header className="border-b border-hairline/70 bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 md:px-6">
          <div className="flex items-center gap-3">
            <img
              src="/brand/faro-logo.png"
              alt="Faro"
              className="h-11 w-11 object-contain drop-shadow-[0_0_14px_rgba(242,179,58,0.28)]"
            />
            <div>
              <h1 className="text-lg font-semibold tracking-normal text-slate-50">Faro</h1>
              <p className="text-xs text-slate-400">Decisiones de mercado con riesgo visible</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <SystemStatusButton
              health={systemHealth}
              alerts={operationalAlerts}
              loading={healthLoading}
              onRefresh={fetchSystemHealth}
            />
            <StatusPill source={analysisResponse?.source} loading={loading} />
            {lastFetchAt ? (
              <span className="hidden text-xs text-slate-500 md:inline">
                <RelativeTime since={lastFetchAt} />
              </span>
            ) : null}
            <button
              type="button"
              onClick={toggleAutoRefresh}
              aria-pressed={autoRefresh}
              className={`inline-flex h-9 w-9 items-center justify-center rounded-lg border transition focus:outline-none focus:ring-2 focus:ring-cobalt/50 ${
                autoRefresh
                  ? 'border-cobalt/50 bg-cobalt/15 text-cobalt'
                  : 'border-hairline/70 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]'
              }`}
              aria-label={autoRefresh ? 'Desactivar auto-actualización' : 'Activar auto-actualización cada 60s'}
              title={autoRefresh ? 'Auto-actualización activa (60s)' : 'Auto-actualización'}
            >
              {autoRefresh ? (
                <Pause aria-hidden="true" className="h-4 w-4" />
              ) : (
                <Play aria-hidden="true" className="h-4 w-4" />
              )}
            </button>
            <button
              type="button"
              onClick={() => selectedTicker && fetchData(selectedTicker)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-hairline/70 bg-white/[0.04] text-slate-200 transition hover:bg-white/[0.08] focus:outline-none focus:ring-2 focus:ring-cobalt/50"
              aria-label="Actualizar datos ahora"
              title="Actualizar"
            >
              <RefreshCcw aria-hidden="true" className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </header>

      <main id="main" aria-label="Panel de decisión" className="mx-auto max-w-6xl space-y-5 px-4 py-5 md:px-6">
        <SourceRibbon source={analysisResponse?.source} />

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="w-full sm:max-w-sm">
            {assets.length > 0 ? (
              <AssetSwitcher
                assets={assets}
                selectedTicker={selectedTicker}
                onSelect={setSelectedTicker}
                memory={assetMemory}
              />
            ) : (
              <p className="rounded-lg border border-hairline/70 bg-inset px-3 py-2.5 text-sm text-slate-500">
                Cargando activos…
              </p>
            )}
          </div>
          <span className="text-xs text-slate-500">{assets.length} activos</span>
        </div>

        <Watchlist
          assets={assets}
          selectedTicker={selectedTicker}
          onSelect={setSelectedTicker}
          memory={assetMemory}
        />

        {error ? (
          <div className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        {firstLoad ? (
          <DashboardSkeleton />
        ) : (
          <div className={loading ? 'pointer-events-none space-y-5 opacity-60 transition-opacity' : 'space-y-5'}>
            <DecisionHero
              asset={selectedAsset}
              analysis={analysis}
              minConfidence={activeMinConfidence}
              signalHistory={signalHistory}
              editRiskButtonRef={editRiskButtonRef}
              onEditRisk={() => setRiskDrawerOpen(true)}
            />

            <SegmentedControl
              label="Secciones de evidencia"
              idPrefix="evidencia"
              value={activeTab}
              onChange={changeTab}
              options={tabOptions}
            />

            <div
              role="tabpanel"
              id={`evidencia-panel-${activeTab}`}
              aria-labelledby={`evidencia-tab-${activeTab}`}
              tabIndex={0}
              className="focus:outline-none focus-visible:ring-2 focus-visible:ring-cobalt/40"
            >
              {tabContent}
            </div>
          </div>
        )}
      </main>

      <Drawer
        open={riskDrawerOpen}
        onClose={() => setRiskDrawerOpen(false)}
        title="Perfil de riesgo"
        returnFocusRef={editRiskButtonRef}
      >
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
          bare
        />
      </Drawer>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Cargando panel">
      <section className="rounded-lg border border-hairline/70 bg-surface p-5">
        <SkeletonLines rows={2} className="max-w-xs" />
        <div className="mt-4 flex flex-wrap gap-6">
          <SkeletonLines rows={2} className="w-24" />
          <SkeletonLines rows={2} className="w-24" />
          <SkeletonLines rows={2} className="w-24" />
        </div>
      </section>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_0.8fr]">
        <section className="rounded-lg border border-hairline/70 bg-surface p-4">
          <SkeletonLines rows={1} className="mb-4 max-w-[120px]" />
          <div className="h-[420px] rounded-lg border border-hairline/60 bg-inset" />
        </section>
        <div className="space-y-5">
          <section className="rounded-lg border border-hairline/70 bg-surface p-4">
            <SkeletonMetrics count={4} />
          </section>
          <section className="rounded-lg border border-hairline/70 bg-surface p-4">
            <SkeletonLines rows={3} />
          </section>
        </div>
      </div>
      <section className="rounded-lg border border-hairline/70 bg-surface p-4">
        <SkeletonTable rows={3} />
      </section>
    </div>
  );
}

function SystemStatusButton({
  health,
  alerts,
  loading,
  onRefresh,
}: {
  health: SystemHealthResponse | null;
  alerts: OperationalAlertsResponse | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const healthOk = health?.status === 'ok';
  const alertLevel = alerts?.status;
  const bad = !health || !healthOk || alertLevel === 'critical' || alertLevel === 'warning';
  const dot = !health ? 'bg-slate-500' : bad ? 'bg-amber-300' : 'bg-emerald-300';
  const text = !health ? 'Sin lectura' : bad ? 'Revisar' : 'Sistema OK';

  return (
    <Popover
      align="right"
      trigger={(props) => (
        <button
          {...props}
          type="button"
          className="inline-flex items-center gap-2 rounded-lg border border-hairline/70 bg-white/[0.04] px-3 py-2 text-sm text-slate-300 transition hover:bg-white/[0.08] focus:outline-none focus:ring-2 focus:ring-cobalt/50"
        >
          <span className={`h-2 w-2 rounded-full ${dot}`} />
          <span className="hidden sm:inline">{text}</span>
          <ChevronDown aria-hidden="true" className="h-3.5 w-3.5 text-slate-500" />
        </button>
      )}
      panelClassName="w-[min(92vw,22rem)] max-h-[70vh] overflow-y-auto space-y-2 p-2"
    >
      <SystemHealthPanel health={health} loading={loading} onRefresh={onRefresh} />
      <OperationalAlertsPanel report={alerts} />
    </Popover>
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
    <section className="rounded-lg border border-hairline/70 bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {isOk ? (
            <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-emerald-300" />
          ) : (
            <AlertTriangle aria-hidden="true" className="h-4 w-4 text-amber-300" />
          )}
          <h2 className="text-sm font-medium text-slate-100">Sistema</h2>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-hairline/70 text-slate-300 transition hover:bg-white/5"
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
          <h2 className="text-sm font-medium text-slate-100">Alertas</h2>
        </div>
        <span className={`rounded-md px-2 py-1 text-xs uppercase ${tone.badge}`}>{statusLabel(status)}</span>
      </div>

      {!report ? (
        <p className="text-sm text-slate-500">Sin lectura operativa.</p>
      ) : alerts.length === 0 ? (
        <p className="text-sm text-slate-400">Sin alertas activas para {report.ticker}.</p>
      ) : (
        <div className="space-y-2">
          {alerts.map((alert) => {
            const itemTone = alertTone(alert.severity);
            return (
              <div key={`${alert.code}-${alert.message}`} className={`rounded-lg border px-3 py-2 ${itemTone.item}`}>
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm text-slate-100">{alert.message}</p>
                  <span className={`shrink-0 rounded-md px-2 py-1 text-xs uppercase ${itemTone.badge}`}>
                    {statusLabel(alert.severity)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{alert.code}</p>
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
      surface: 'border-cobalt/20 bg-cobalt/10',
      item: 'border-cobalt/15 bg-cobalt/10',
      icon: 'text-cobalt',
      badge: 'bg-cobalt/15 text-cobalt',
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
    surface: 'border-hairline/70 bg-surface',
    item: 'border-hairline/70 bg-inset',
    icon: 'text-slate-400',
    badge: 'bg-hairline/40 text-slate-300',
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
  bare = false,
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
  bare?: boolean;
}) {
  const canUseAssetClass = Boolean(asset?.asset_class);
  const canUseTicker = Boolean(asset?.ticker);
  const Wrapper = bare ? 'div' : 'section';

  return (
    <Wrapper className={bare ? '' : 'rounded-lg border border-hairline/70 bg-surface p-4'}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {bare ? null : <SlidersHorizontal aria-hidden="true" className="h-4 w-4 text-cobalt" />}
          <h2 className={bare ? 'text-xs uppercase tracking-wide text-slate-500' : 'text-sm font-medium text-slate-100'}>
            {bare ? 'Alcance y límites' : 'Perfil'}
          </h2>
        </div>
        <span className="rounded-md bg-inset px-2 py-1 text-xs uppercase text-slate-500">{source}</span>
      </div>

      <div className="space-y-3">
        <div>
          <p className="mb-2 text-xs text-slate-500">Alcance</p>
          <div className="grid grid-cols-3 gap-1 rounded-lg bg-inset p-1">
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
          <p className="mt-2 truncate text-xs text-slate-500">{scopeLabel(scopeType, scopeValue)}</p>
        </div>

        <label className="block text-xs text-slate-500">
          Nombre
          <input
            type="text"
            value={draft.name}
            onChange={(event) => onChange('name', event.target.value)}
            className="mt-1 h-9 w-full rounded-lg border border-hairline/70 bg-inset px-3 text-sm text-slate-100 outline-none transition focus:border-cobalt/40"
          />
        </label>

        <PercentField label="Posicion max" value={draft.max_position_size} onChange={(value) => onChange('max_position_size', value)} />
        <PercentField label="Confianza min" value={draft.min_confidence_to_trade} onChange={(value) => onChange('min_confidence_to_trade', value)} />
        <PercentField label="Riesgo max" value={draft.max_expected_risk} onChange={(value) => onChange('max_expected_risk', value)} />
        <PercentField label="Stop" value={draft.stop_loss} onChange={(value) => onChange('stop_loss', value)} />
        <PercentField label="Objetivo" value={draft.take_profit} onChange={(value) => onChange('take_profit', value)} />

        <label className="flex items-center justify-between gap-3 rounded-lg border border-hairline/70 bg-inset px-3 py-2 text-sm text-slate-300">
          Permitir short
          <input
            type="checkbox"
            checked={draft.allow_short}
            onChange={(event) => onChange('allow_short', event.target.checked)}
            className="h-4 w-4 accent-cobalt"
          />
        </label>

        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-cobalt/30 bg-cobalt/10 px-3 text-sm font-medium text-cobalt transition hover:bg-cobalt/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Save aria-hidden="true" className="h-4 w-4" />
          {saving ? 'Guardando' : 'Guardar perfil'}
        </button>
      </div>

      {status && <p className="mt-3 text-sm text-slate-400">{status}</p>}
    </Wrapper>
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
        active ? 'bg-cobalt/15 text-cobalt' : 'text-slate-400 hover:text-slate-100'
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
    <label className="grid grid-cols-[1fr_84px] items-center gap-3 text-xs text-slate-500">
      <span>{label}</span>
      <span className="relative">
        <input
          type="number"
          min="0"
          max="100"
          step="1"
          value={percentInputValue(value)}
          onChange={(event) => onChange(Number(event.target.value || 0) / 100)}
          className="h-9 w-full rounded-lg border border-hairline/70 bg-inset pl-3 pr-7 text-right text-sm text-slate-100 outline-none transition focus:border-cobalt/40"
        />
        <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-500">%</span>
      </span>
    </label>
  );
}

function DecisionHero({
  asset,
  analysis,
  minConfidence,
  signalHistory,
  editRiskButtonRef,
  onEditRisk,
}: {
  asset?: Asset;
  analysis: Analysis | null;
  minConfidence: number;
  signalHistory: Signal[];
  editRiskButtonRef: React.RefObject<HTMLButtonElement | null>;
  onEditRisk: () => void;
}) {
  const signal = analysis?.signal ?? 'HOLD';
  const tone = signalTone(signal);
  const reasons = analysis?.reasons ?? (analysis?.reason ? [analysis.reason] : []);
  const baseSignal = analysis?.risk?.pre_risk_action;
  const isUserProfile = analysis?.risk?.profile_source === 'user';
  const wasAdjusted = Boolean(baseSignal && baseSignal !== signal);
  const gaugeTone = signal === 'BUY' ? 'emerald' : signal === 'SELL' ? 'red' : 'slate';

  return (
    <section className={`rounded-lg border p-5 ${tone.surface}`}>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_260px]">
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <div className={`flex h-12 w-12 items-center justify-center rounded-lg ${tone.iconBg}`}>
              <SignalIcon signal={signal} className={`h-6 w-6 ${tone.icon}`} />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm text-slate-400">{asset?.name ?? 'Activo seleccionado'}</p>
              <h2 className="font-mono text-2xl font-semibold tracking-normal text-slate-50">
                {asset?.ticker ?? '...'}
              </h2>
            </div>
          </div>

          {analysis?.prediction_timestamp ? (
            <p className="flex items-center gap-1.5 text-xs text-slate-500">
              <Clock3 aria-hidden="true" className="h-3.5 w-3.5" />
              Predicción del {formatDateTime(analysis.prediction_timestamp)}
            </p>
          ) : null}

          <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
            <div aria-live="polite">
              <p className="text-sm text-slate-400">Decisión</p>
              <p className={`text-4xl font-semibold tracking-normal ${tone.text}`}>
                {signal}
                <span className="sr-only">
                  {' '}
                  para {asset?.ticker ?? 'el activo seleccionado'}, confianza{' '}
                  {formatPercent(analysis?.confidence)}
                </span>
              </p>
            </div>
            {baseSignal && baseSignal !== signal ? (
              <MetricInline label="Modelo base" value={baseSignal} />
            ) : null}
            <MetricInline
              label="Horizonte"
              value={analysis?.model?.horizon ? `${analysis.model.horizon}d` : 'N/D'}
            />
          </div>

          <ConfidenceGauge
            label="Confianza"
            value={analysis?.confidence ?? null}
            threshold={minConfidence}
            tone={gaugeTone}
            className="max-w-md"
          />

          <div className="max-w-md">
            <p className="mb-1.5 text-xs text-slate-500">Distribución del modelo</p>
            <ProbabilityBar probabilities={analysis?.probabilities} />
          </div>

          {signalHistory.length > 0 ? <SignalSparkline signals={signalHistory} /> : null}

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
            <div className="flex flex-wrap gap-2">
              {reasons.map((reason) => (
                <span
                  key={reason}
                  className="rounded-md border border-hairline/70 bg-inset px-2 py-1 text-xs text-slate-300"
                >
                  {reason}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-3">
          <MetricBox
            icon={<ShieldCheck aria-hidden="true" className="h-4 w-4" />}
            label="Posición"
            value={formatPercent(analysis?.risk?.position_size)}
          />
          <MetricBox
            icon={<Gauge aria-hidden="true" className="h-4 w-4" />}
            label="Riesgo esperado"
            value={formatPercent(analysis?.expected_risk ?? null)}
          />
          <button
            ref={editRiskButtonRef}
            type="button"
            onClick={onEditRisk}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-hairline/70 bg-inset px-3 py-2 text-sm text-slate-200 transition hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-cobalt/50"
          >
            <SlidersHorizontal aria-hidden="true" className="h-4 w-4 text-cobalt" />
            Ajustar perfil de riesgo
          </button>
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
    <div className="mt-4 rounded-lg border border-cobalt/20 bg-cobalt/10 p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-cobalt">{title}</p>
          <p className="mt-1 text-sm text-cobalt/70">{detail}</p>
        </div>
        <span className="shrink-0 rounded-md bg-inset px-2 py-1 text-xs text-cobalt">
          {userProfile ? `Perfil ${profileName ?? 'usuario'}` : 'Politica global'}
        </span>
      </div>

      {reasons.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {reasons.map((reason) => (
            <span key={reason} className="rounded-md border border-cobalt/15 bg-inset px-2 py-1 text-xs text-cobalt/80">
              {humanizeReason(reason)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function RiskPanel({ analysis, onEdit }: { analysis: Analysis | null; onEdit?: () => void }) {
  const risk = analysis?.risk;
  const blocked = risk?.blocked_reasons ?? [];
  const profileLabel = risk?.profile_source === 'user' ? risk.profile_name || 'usuario' : 'global';

  return (
    <section className="rounded-lg border border-hairline/70 bg-surface p-4">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldCheck aria-hidden="true" className="h-4 w-4 text-emerald-300" />
          <h2 className="text-sm font-medium text-slate-100">Riesgo</h2>
        </div>
        <div className="flex items-center gap-2">
          {blocked.length > 0 ? (
            <span className="rounded-md bg-amber-300/10 px-2 py-1 text-xs text-amber-200">Bloqueada</span>
          ) : (
            <span className="rounded-md bg-emerald-300/10 px-2 py-1 text-xs text-emerald-200">Activa</span>
          )}
          {onEdit ? (
            <button
              type="button"
              onClick={onEdit}
              className="rounded-md border border-hairline/70 px-2 py-1 text-xs text-slate-300 transition hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-cobalt/50"
            >
              Ajustar
            </button>
          ) : null}
        </div>
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

function ModelPanel({ analysis }: { analysis: Analysis | null }) {
  const model = analysis?.model;
  const feedback = analysis?.feedback;

  return (
    <section className="rounded-lg border border-hairline/70 bg-surface p-4">
      <div className="mb-4 flex items-center gap-2">
        <Brain aria-hidden="true" className="h-4 w-4 text-cobalt" />
        <h2 className="text-sm font-medium text-slate-100">Modelo</h2>
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

function BacktestPanel({ rows, failed }: { rows: BacktestSummaryRow[]; failed?: boolean }) {
  const latest = rows[0];

  return (
    <section className="rounded-lg border border-hairline/70 bg-surface p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <BarChart3 aria-hidden="true" className="h-4 w-4 text-cobalt" />
          <h2 className="text-sm font-medium text-slate-100">Backtests</h2>
        </div>
        <span className="text-xs text-slate-500">{rows.length}</span>
      </div>

      {failed ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudieron cargar los backtests"
        />
      ) : !latest ? (
        <EmptyState
          icon={<BarChart3 aria-hidden="true" className="h-6 w-6" />}
          title="Sin backtests persistidos"
          hint="Se generan al promover un modelo con el job de reentrenamiento."
          command="py -3.14 -m brain.run_retraining_job --tickers <TICKER>"
        />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SmallMetric label="Retorno" value={formatPercent(latest.metrics?.total_return)} />
            <SmallMetric label="Drawdown" value={formatPercent(latest.metrics?.max_drawdown)} />
            <SmallMetric label={<InfoLabel label="Profit factor" hint="Ganancia bruta ÷ pérdida bruta. > 1 = estrategia rentable." />} value={formatNumber(latest.metrics?.profit_factor)} />
            <SmallMetric label="Trades" value={formatCount(latest.metrics?.active_trade_count)} />
          </div>

          <DataTable
            ariaLabel="Backtests persistidos"
            rows={rows}
            getRowKey={(row, i) => row.id ?? row.name ?? String(i)}
            columns={[
              {
                key: 'modelo',
                header: 'Modelo',
                render: (row) => (
                  <span className="block max-w-[220px] truncate text-slate-200">
                    {row.model?.name ?? 'Modelo'}:{row.model?.version ?? row.name ?? 'N/D'}
                  </span>
                ),
              },
              { key: 'retorno', header: 'Retorno', numeric: true, render: (row) => <span className={metricTone(row.metrics?.total_return)}>{formatPercent(row.metrics?.total_return)}</span> },
              { key: 'dd', header: 'Drawdown', numeric: true, render: (row) => formatPercent(row.metrics?.max_drawdown) },
              { key: 'pf', header: 'PF', numeric: true, render: (row) => formatNumber(row.metrics?.profit_factor) },
              { key: 'fecha', header: 'Fecha', numeric: true, priority: 'secondary', render: (row) => (row.created_at ? formatShortDate(row.created_at) : 'N/D') },
            ]}
          />
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
  failed,
}: {
  onPersist: () => void;
  paper: PaperTradingResponse | null;
  runs: PaperTradingRunRow[];
  saving: boolean;
  status: string | null;
  failed?: boolean;
}) {
  const metrics = paper?.metrics;
  const recentSignals = (paper?.timeline ?? []).slice(-5).reverse();
  const recentTrades = (paper?.timeline ?? [])
    .filter((row) => Math.abs(row.exposure_delta ?? 0) > 0)
    .slice(-5)
    .reverse();

  return (
    <section className="rounded-lg border border-hairline/70 bg-surface p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity aria-hidden="true" className="h-4 w-4 text-emerald-300" />
          <h2 className="text-sm font-medium text-slate-100">Paper trading</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded-md px-2 py-1 text-xs ${paperPositionTone(metrics?.open_position)}`}>
            {metrics?.open_position ?? 'FLAT'}
          </span>
          <button
            type="button"
            onClick={onPersist}
            disabled={!paper || saving}
            className="inline-flex h-8 items-center gap-2 rounded-md border border-hairline/70 px-3 text-xs text-slate-200 transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save aria-hidden="true" className="h-3.5 w-3.5" />
            {saving ? 'Guardando' : 'Guardar'}
          </button>
        </div>
      </div>
      {status ? <p className="mb-4 text-xs text-slate-400">{status}</p> : null}

      {failed ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudo cargar la simulación"
        />
      ) : !paper ? (
        <EmptyState
          icon={<Activity aria-hidden="true" className="h-6 w-6" />}
          title="Sin simulación disponible"
          hint="Necesita predicciones guardadas para este activo."
          command="py -3.14 -m brain.run_inference_job"
        />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <SmallMetric label="Equity" value={formatCurrencyOrNA(metrics?.final_equity ?? metrics?.initial_capital)} />
            <SmallMetric label="Retorno" value={formatPercent(metrics?.total_return)} />
            <SmallMetric label="Drawdown" value={formatPercent(metrics?.max_drawdown)} />
            <SmallMetric label="Trades" value={formatCount(metrics?.trade_count)} />
            <SmallMetric label="Exposicion" value={formatPercent(metrics?.average_abs_exposure)} />
          </div>

          <div className="rounded-lg border border-hairline/70 p-3">
            <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-sm font-medium text-slate-100">Curva de equity</h3>
                <p className="text-xs text-slate-500">
                  {formatCount(metrics?.signal_count)} senales, {formatCount(metrics?.active_signal_count)} activas
                </p>
              </div>
              <span className="text-xs text-slate-500">Costo {formatNumber((metrics?.fee_bps ?? 0) + (metrics?.slippage_bps ?? 0))} bps</span>
            </div>
            <Suspense fallback={<ChartLoadingState height={260} />}>
              <EquityCurveChart data={paper.timeline} />
            </Suspense>
          </div>

          {recentTrades.length > 0 ? (
            <div>
              <h3 className="mb-2 text-sm font-medium text-slate-200">Operaciones recientes</h3>
              <DataTable
                ariaLabel="Operaciones recientes de paper trading"
                rows={recentTrades}
                getRowKey={(row, i) => `trade-${row.timestamp ?? i}`}
                columns={[
                  { key: 'fecha', header: 'Fecha', render: (row) => (row.timestamp ? formatShortDate(row.timestamp) : 'N/D') },
                  { key: 'accion', header: 'Acción', render: (row) => <span className={`font-medium ${signalTone(row.action ?? 'HOLD').text}`}>{row.action ?? 'HOLD'}</span> },
                  { key: 'delta', header: 'Delta', numeric: true, priority: 'secondary', render: (row) => formatPercent(row.exposure_delta) },
                  { key: 'costo', header: 'Costo', numeric: true, render: (row) => formatBasisPoints(row.cost) },
                  { key: 'equity', header: 'Equity', numeric: true, render: (row) => formatCurrencyOrNA(row.equity) },
                ]}
              />
            </div>
          ) : null}

          {recentSignals.length === 0 ? (
            <EmptyState
              icon={<Activity aria-hidden="true" className="h-6 w-6" />}
              title="Sin señales simuladas"
            />
          ) : (
            <div>
              <h3 className="mb-2 text-sm font-medium text-slate-200">Señales recientes</h3>
              <DataTable
                ariaLabel="Señales recientes de paper trading"
                rows={recentSignals}
                getRowKey={(row, i) => `signal-${row.timestamp ?? i}`}
                columns={[
                  { key: 'fecha', header: 'Fecha', render: (row) => (row.timestamp ? formatShortDate(row.timestamp) : 'N/D') },
                  { key: 'accion', header: 'Acción', render: (row) => <span className={`font-medium ${signalTone(row.action ?? 'HOLD').text}`}>{row.action ?? 'HOLD'}</span> },
                  { key: 'precio', header: 'Precio', numeric: true, priority: 'secondary', render: (row) => formatCurrencyOrNA(row.price) },
                  { key: 'posicion', header: 'Posición', render: (row) => row.position_state ?? 'FLAT' },
                  { key: 'equity', header: 'Equity', numeric: true, render: (row) => formatCurrencyOrNA(row.equity) },
                ]}
              />
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
    <div className="rounded-lg border border-hairline/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-slate-100">Corridas guardadas</h3>
          <p className="text-xs text-slate-500">
            {rows.length > 0 && best ? `Mejor retorno: ${formatPercent(best.metrics?.total_return)}` : 'Sin historial persistido'}
          </p>
        </div>
        <span className="text-xs text-slate-500">{rows.length}</span>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={<Save aria-hidden="true" className="h-6 w-6" />}
          title="Sin corridas guardadas"
          hint="Guardá una simulación para compararla después."
        />
      ) : (
        <DataTable
          ariaLabel="Corridas de paper trading guardadas"
          rows={rows}
          getRowKey={(row, i) => row.id ?? row.name ?? String(i)}
          columns={[
            {
              key: 'modelo',
              header: 'Modelo',
              render: (row) => (
                <span className="block max-w-[220px] truncate text-slate-200">
                  {row.model?.name ?? row.params?.model_name ?? 'Modelo'}:
                  {row.model?.version ?? row.params?.model_version ?? row.name ?? 'N/D'}
                </span>
              ),
            },
            { key: 'retorno', header: 'Retorno', numeric: true, render: (row) => <span className={metricTone(row.metrics?.total_return)}>{formatPercent(row.metrics?.total_return)}</span> },
            { key: 'dd', header: 'Drawdown', numeric: true, render: (row) => formatPercent(row.metrics?.max_drawdown) },
            { key: 'trades', header: 'Trades', numeric: true, render: (row) => formatCount(row.metrics?.trade_count) },
            { key: 'equity', header: 'Equity', numeric: true, priority: 'secondary', render: (row) => formatCurrencyOrNA(row.metrics?.final_equity) },
            { key: 'fecha', header: 'Fecha', numeric: true, priority: 'secondary', render: (row) => (row.created_at ? formatShortDate(row.created_at) : 'N/D') },
          ]}
        />
      )}
    </div>
  );
}

function FeedbackQualityPanel({
  report,
  failed,
}: {
  report: FeedbackSummaryResponse | null;
  failed?: boolean;
}) {
  const summary = report?.summary;
  const actionRows = report?.by_action ?? [];

  return (
    <section className="rounded-lg border border-hairline/70 bg-surface p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck aria-hidden="true" className="h-4 w-4 text-cobalt" />
          <h2 className="text-sm font-medium text-slate-100">Calidad del modelo</h2>
        </div>
        <span className="text-xs text-slate-500">{formatCount(summary?.evaluated_predictions)}</span>
      </div>

      {failed ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudo cargar el feedback"
        />
      ) : !report || !summary?.evaluated_predictions ? (
        <EmptyState
          icon={<ShieldCheck aria-hidden="true" className="h-6 w-6" />}
          title="Sin feedback evaluado todavía"
          hint="Aparece cuando una predicción pasada ya tiene su etiqueta materializada."
        />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SmallMetric label="Acierto" value={formatPercent(summary.accuracy)} />
            <SmallMetric label="Confianza" value={formatPercent(summary.mean_confidence)} />
            <SmallMetric label="Retorno medio" value={formatPercent(summary.mean_outcome_return)} />
            <SmallMetric label="Retorno total" value={formatPercent(summary.total_outcome_return)} />
          </div>

          <DataTable
            ariaLabel="Calidad del modelo por acción"
            rows={actionRows}
            getRowKey={(row, i) => row.action ?? String(i)}
            columns={[
              { key: 'accion', header: 'Acción', render: (row) => <span className={`font-medium ${signalTone(row.action ?? 'HOLD').text}`}>{row.action ?? 'HOLD'}</span> },
              { key: 'casos', header: 'Casos', numeric: true, render: (row) => formatCount(row.count) },
              { key: 'acierto', header: 'Acierto', numeric: true, render: (row) => formatPercent(row.accuracy) },
              { key: 'conf', header: 'Confianza', numeric: true, priority: 'secondary', render: (row) => formatPercent(row.mean_confidence) },
              { key: 'retorno', header: 'Retorno', numeric: true, render: (row) => <span className={metricTone(row.total_outcome_return)}>{formatPercent(row.total_outcome_return)}</span> },
            ]}
          />
        </div>
      )}
    </section>
  );
}

function PredictionHistoryPanel({
  rows,
  failed,
}: {
  rows: PredictionAuditRow[];
  failed?: boolean;
}) {
  return (
    <section className="rounded-lg border border-hairline/70 bg-surface p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <History aria-hidden="true" className="h-4 w-4 text-emerald-300" />
          <h2 className="text-sm font-medium text-slate-100">Auditoría</h2>
        </div>
        <span className="text-xs text-slate-500">{rows.length}</span>
      </div>

      {failed ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudo cargar el historial"
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Inbox aria-hidden="true" className="h-6 w-6" />}
          title="Sin predicciones históricas"
          hint="Cada corrida de inferencia agrega una fila auditable."
        />
      ) : (
        <DataTable
          ariaLabel="Historial de predicciones"
          rows={rows}
          getRowKey={(row, i) => String(row.prediction_id ?? row.timestamp ?? i)}
          columns={[
            { key: 'fecha', header: 'Fecha', render: (row) => (row.timestamp ? formatShortDate(row.timestamp) : 'N/D') },
            { key: 'accion', header: 'Acción', priority: 'secondary', render: (row) => <span className={`font-medium ${signalTone(row.action).text}`}>{row.action}</span> },
            {
              key: 'modelo',
              header: 'Modelo',
              render: (row) => (
                <span className="block max-w-[200px] truncate text-slate-200">
                  {row.model?.name ?? 'Modelo'}:{row.model?.version ?? 'N/D'}
                </span>
              ),
            },
            { key: 'conf', header: 'Confianza', numeric: true, render: (row) => formatPercent(row.confidence) },
            { key: 'resultado', header: 'Resultado', priority: 'secondary', render: (row) => feedbackLabel(row.feedback) },
            {
              key: 'riesgo',
              header: 'Riesgo',
              priority: 'secondary',
              render: (row) => {
                const blocked = row.risk?.blocked_reasons ?? [];
                return blocked.length > 0
                  ? blocked.map(humanizeReason).join(', ')
                  : formatPercent(row.risk?.position_size);
              },
            },
          ]}
        />
      )}
    </section>
  );
}

function PriceSnapshot({ prices }: { prices: PricePoint[] }) {
  const latest = prices[0];
  if (!latest) {
    return <span className="text-sm text-slate-500">Sin precio</span>;
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-hairline/70 bg-inset px-3 py-2">
      <CircleDollarSign aria-hidden="true" className="h-4 w-4 text-beam" />
      <span className="text-sm font-medium tabular-nums text-slate-100">
        {formatCurrency(Number(latest.close))}
      </span>
    </div>
  );
}

function PricePanel({
  prices,
  ticker,
  signals,
  failed,
  onRetry,
}: {
  prices: PricePoint[];
  ticker: string;
  signals: { timestamp?: string; action: Signal }[];
  failed: boolean;
  onRetry: () => void;
}) {
  const latest = prices[0];
  const oldest = prices[prices.length - 1];
  const asOf = latest?.timestamp ? formatShortDate(latest.timestamp) : null;

  return (
    <section className="rounded-lg border border-hairline/70 bg-surface p-4">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-medium text-slate-100">Precio</h2>
          {asOf ? <p className="text-xs text-slate-500">Último cierre {asOf}</p> : null}
        </div>
        <PriceSnapshot prices={prices} />
      </div>
      {prices.length > 0 ? (
        <>
          <p className="sr-only">
            Gráfico de precio de {ticker || 'el activo'}
            {oldest?.timestamp && latest?.timestamp
              ? `, del ${formatShortDate(oldest.timestamp)} al ${formatShortDate(latest.timestamp)}`
              : ''}
            {latest ? `. Último cierre ${formatCurrency(Number(latest.close))}.` : '.'}
          </p>
          <Suspense fallback={<ChartLoadingState height={420} />}>
            <FinancialChart data={prices} signals={signals} />
          </Suspense>
        </>
      ) : failed ? (
        <EmptyState
          variant="error"
          icon={<AlertTriangle aria-hidden="true" className="h-6 w-6" />}
          title="No se pudo cargar el histórico"
          hint="La API respondió con error para este activo."
          onRetry={onRetry}
          className="min-h-[420px] justify-center"
        />
      ) : (
        <EmptyState
          icon={<BarChart3 aria-hidden="true" className="h-6 w-6" />}
          title="Sin histórico de precio"
          hint="Cargá datos de mercado para este activo."
          command="py -3.14 -m collector.run_market_data_job --tickers <TICKER> --feature-sets technical_v2"
          className="min-h-[420px] justify-center"
        />
      )}
    </section>
  );
}

function StatusPill({ source, loading }: { source?: string; loading: boolean }) {
  if (loading) {
    return (
      <span className="inline-flex items-center gap-2 rounded-lg border border-hairline/70 bg-white/[0.04] px-3 py-2 text-sm text-slate-300">
        <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-cobalt" />
        Actualizando
      </span>
    );
  }

  const isPrediction = source === 'prediction';
  const isDemo = source === 'demo_indicators';
  return (
    <span className="inline-flex items-center gap-2 rounded-lg border border-hairline/70 bg-white/[0.04] px-3 py-2 text-sm text-slate-300">
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

function RelativeTime({ since }: { since: number }) {
  const [now, setNow] = useState(since);
  useEffect(() => {
    const update = () => setNow(Date.now());
    update();
    const id = window.setInterval(update, 15_000);
    return () => window.clearInterval(id);
  }, [since]);
  const secs = Math.max(0, Math.round((now - since) / 1000));
  const label =
    secs < 45
      ? `hace ${secs}s`
      : secs < 3600
        ? `hace ${Math.round(secs / 60)} min`
        : `hace ${Math.round(secs / 3600)} h`;
  return <span title={`Actualizado ${label}`}>Actualizado {label}</span>;
}

function SourceRibbon({ source }: { source?: string }) {
  if (!source || source === 'prediction') return null;
  const demo = source === 'demo_indicators';
  return (
    <div
      role="status"
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
        demo
          ? 'border-red-400/40 bg-red-400/10 text-red-100'
          : 'border-amber-300/40 bg-amber-300/10 text-amber-100'
      }`}
    >
      <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
      <p>
        {demo
          ? 'Modo demo: las lecturas son sintéticas y no representan datos reales de mercado.'
          : 'Sin modelo versionado para este activo: se muestran indicadores técnicos, no una predicción del modelo.'}
      </p>
    </div>
  );
}

function MetricInline({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div>
      <p className="text-sm text-slate-400">{label}</p>
      <p className="text-lg font-medium tabular-nums text-slate-100">{value}</p>
    </div>
  );
}

function MetricBox({ icon, label, value }: { icon?: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-hairline/70 bg-inset p-3">
      {icon ? <div className="mb-2 text-slate-400">{icon}</div> : null}
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-lg font-medium tabular-nums text-slate-100">{value}</p>
    </div>
  );
}

function SmallMetric({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="rounded-lg border border-hairline/70 bg-inset p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-medium tabular-nums text-slate-100">{value}</p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-hairline/45 pb-2 last:border-b-0 last:pb-0">
      <span className="text-slate-500">{label}</span>
      <span className="truncate text-right text-slate-200">{value}</span>
    </div>
  );
}

function ChartLoadingState({ height }: { height: number }) {
  return (
    <div
      className="flex items-center justify-center rounded-lg border border-dashed border-hairline/70 text-sm text-slate-500"
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
    surface: 'border-slate-500/25 bg-slate-500/[0.07]',
    text: 'text-slate-300',
    icon: 'text-slate-300',
    iconBg: 'bg-slate-500/15',
  };
}

function SignalIcon({ signal, className }: { signal: Signal; className: string }) {
  if (signal === 'BUY') return <TrendingUp aria-hidden="true" className={className} />;
  if (signal === 'SELL') return <TrendingDown aria-hidden="true" className={className} />;
  return <MinusCircle aria-hidden="true" className={className} />;
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
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-slate-300';
  if (value > 0) return 'text-emerald-300';
  if (value < 0) return 'text-red-300';
  return 'text-slate-300';
}

function paperPositionTone(position?: string | null) {
  if (position === 'LONG') return 'bg-emerald-300/10 text-emerald-200';
  if (position === 'SHORT') return 'bg-red-300/10 text-red-200';
  return 'bg-slate-800 text-slate-300';
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
