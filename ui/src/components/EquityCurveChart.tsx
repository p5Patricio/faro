import { useEffect, useMemo, useRef } from 'react';
import {
  AreaSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts';

export interface EquityCurvePoint {
  timestamp?: string;
  action?: string;
  equity?: number | null;
  exposure_delta?: number | null;
}

interface EquityCurveChartProps {
  data: EquityCurvePoint[];
  height?: number;
}

export function EquityCurveChart({ data, height = 260 }: EquityCurveChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const chartData = useMemo(
    () =>
      data
        .map((row) => {
          const time = toUtcTimestamp(row.timestamp);
          const value = Number(row.equity);
          if (!time || !Number.isFinite(value)) return null;
          return { time, value };
        })
        .filter((row): row is { time: UTCTimestamp; value: number } => row !== null)
        .sort((a, b) => a.time - b.time),
    [data],
  );

  const markers = useMemo<SeriesMarker<UTCTimestamp>[]>(
    () =>
      data
        .reduce<SeriesMarker<UTCTimestamp>[]>((items, row) => {
          const time = toUtcTimestamp(row.timestamp);
          const value = Number(row.equity);
          const action = row.action ?? 'HOLD';
          const changedExposure = Math.abs(Number(row.exposure_delta ?? 0)) > 0;
          if (!time || !Number.isFinite(value) || !changedExposure) return items;

          items.push({
            time,
            position: action === 'SELL' ? 'aboveBar' : 'belowBar',
            color: action === 'SELL' ? '#fda4af' : '#6ee7b7',
            shape: action === 'SELL' ? 'arrowDown' : 'arrowUp',
            text: action,
            size: 1.1,
          });
          return items;
        }, [])
        .sort((a, b) => a.time - b.time),
    [data],
  );

  useEffect(() => {
    if (!chartContainerRef.current || chartData.length === 0) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#111b34' },
        textColor: '#cbd5e1',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.05)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(255,255,255,0.08)',
      },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)',
        timeVisible: true,
      },
      width: chartContainerRef.current.clientWidth,
      height,
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor: '#4472e6',
      topColor: 'rgba(68, 114, 230, 0.26)',
      bottomColor: 'rgba(68, 114, 230, 0.02)',
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });

    series.setData(chartData);
    createSeriesMarkers(series, markers);
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
      chartRef.current = null;
    };
  }, [chartData, height, markers]);

  if (chartData.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-hairline/70 text-sm text-slate-500"
        style={{ height }}
      >
        Sin curva de equity
      </div>
    );
  }

  return <div ref={chartContainerRef} className="w-full" style={{ height }} />;
}

function toUtcTimestamp(value?: string): UTCTimestamp | null {
  if (!value) return null;
  const milliseconds = new Date(value).getTime();
  if (!Number.isFinite(milliseconds)) return null;
  return Math.floor(milliseconds / 1000) as UTCTimestamp;
}
