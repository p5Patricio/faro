import { useEffect, useRef } from 'react';
import {
  AreaSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';

export interface PricePoint {
  timestamp: string;
  open?: number | string;
  high?: number | string;
  low?: number | string;
  close: number | string;
  volume?: number | string;
}

export interface ChartSignal {
  timestamp?: string;
  action: string;
}

interface ChartProps {
  data: PricePoint[];
  /** BUY / SELL decisions to overlay as markers (HOLD is ignored). */
  signals?: ChartSignal[];
  colors?: {
    backgroundColor?: string;
    lineColor?: string;
    textColor?: string;
    areaTopColor?: string;
    areaBottomColor?: string;
  };
}

export function FinancialChart({
  data,
  signals = [],
  colors: {
    // Faro palette: navy surface, amber-gold price line (the lighthouse beam).
    backgroundColor = '#111b34',
    lineColor = '#f2b33a',
    textColor = '#cbd5e1',
    areaTopColor = 'rgba(242, 179, 58, 0.24)',
    areaBottomColor = 'rgba(242, 179, 58, 0.02)',
  } = {},
}: ChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: backgroundColor },
        textColor,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.06)' },
        horzLines: { color: 'rgba(255,255,255,0.06)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(255,255,255,0.08)',
      },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)',
      },
      width: chartContainerRef.current.clientWidth,
      height: 420,
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor,
      topColor: areaTopColor,
      bottomColor: areaBottomColor,
    });

    const formattedData = data
      .map((item) => ({
        time: item.timestamp.split('T')[0],
        value: Number(item.close),
      }))
      .filter((item) => Number.isFinite(item.value))
      .sort((a, b) => a.time.localeCompare(b.time));

    series.setData(formattedData);

    const markers: SeriesMarker<Time>[] = signals
      .filter((s) => s.timestamp && (s.action === 'BUY' || s.action === 'SELL'))
      .map((s) => {
        const sell = s.action === 'SELL';
        return {
          time: (s.timestamp as string).split('T')[0] as Time,
          position: sell ? 'aboveBar' : 'belowBar',
          color: sell ? '#fda4af' : '#6ee7b7',
          shape: sell ? 'arrowDown' : 'arrowUp',
          text: s.action,
        } satisfies SeriesMarker<Time>;
      })
      .sort((a, b) => String(a.time).localeCompare(String(b.time)));
    if (markers.length > 0) createSeriesMarkers(series, markers);

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (!chartContainerRef.current) return;
      chartRef.current?.applyOptions({ width: chartContainerRef.current.clientWidth });
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [data, signals, backgroundColor, lineColor, textColor, areaTopColor, areaBottomColor]);

  return <div ref={chartContainerRef} className="h-[420px] w-full" />;
}
