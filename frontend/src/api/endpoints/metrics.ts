import { request } from '../http';

/* ─── Response shapes (bound to app/api/routes/safe_autonomy.py) ─── */

export type MetricKey = 'safe_autonomy_rate' | 'cost_usd' | 'execution_volume';

export interface MetricTimeseriesPoint {
  captured_at: string;
  value: number;
}

export interface MetricTimeseries {
  metric: string;
  interval: 'hour' | 'day';
  from: string;
  to: string;
  series: MetricTimeseriesPoint[];
  // Honest-by-design: null when samples exist, an explanatory sentence when
  // the stored series has nothing for this window yet (never a fabricated 0).
  note: string | null;
}

export interface LatencyTierStats {
  calls: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  max_ms: number;
}

export interface LatencyReport {
  window_hours: number;
  model_calls: Record<string, LatencyTierStats>;
  by_model: Record<string, LatencyTierStats>;
  recent_executions: Array<Record<string, unknown>>;
  note: string;
}

export const metricsApi = {
  // The STORED metric series (app/models/metrics_ts.py MetricSample), rolled
  // up on a leader-guarded interval - not reconstructed on every call.
  getTimeseries: (
    metric: MetricKey = 'safe_autonomy_rate',
    opts?: { from?: string; to?: string; interval?: 'hour' | 'day' },
  ) => {
    const params = new URLSearchParams({ metric, interval: opts?.interval || 'day' });
    if (opts?.from) params.set('from', opts.from);
    if (opts?.to) params.set('to', opts.to);
    return request<MetricTimeseries>(`/metrics/timeseries?${params.toString()}`);
  },

  // Where the seconds go: model-call latency by tier/model over the window.
  getLatency: (hours = 24) => request<LatencyReport>(`/metrics/latency?hours=${hours}`),
};
