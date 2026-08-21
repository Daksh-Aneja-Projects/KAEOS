import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { Database, Zap, Cpu, CheckCircle2, AlertTriangle, ArrowRight, RefreshCw } from 'lucide-react';
import { requestPublic } from '../api/http';
import { useTheme } from '../context/ThemeContext';
import { useVisiblePoll } from '../hooks/useLiveRefresh';
import { formatDuration } from '../lib/time';
import KaeosLogo from '../components/KaeosLogo';

interface StatusResponse {
  status: 'ok' | 'degraded';
  version: string;
  uptime_seconds: number;
  dependencies: { db: boolean; redis: boolean; llm: boolean };
}

const DEP_META: { key: keyof StatusResponse['dependencies']; label: string; sub: string; icon: typeof Database }[] = [
  { key: 'db', label: 'Database', sub: 'Primary data store', icon: Database },
  { key: 'redis', label: 'Cache & Queue', sub: 'Redis coordination', icon: Zap },
  { key: 'llm', label: 'AI Runtime', sub: 'Model inference', icon: Cpu },
];

export default function StatusPage() {
  const { colors } = useTheme();
  const [data, setData] = useState<StatusResponse | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [loading, setLoading] = useState(true);
  // Locally-ticked uptime so the number visibly climbs between server polls.
  const baseRef = useRef<{ uptime: number; at: number } | null>(null);
  const [, setTick] = useState(0);

  const load = async () => {
    try {
      const d = await requestPublic<StatusResponse>('/status');
      setData(d);
      setUnreachable(false);
      baseRef.current = { uptime: d.uptime_seconds, at: Date.now() };
    } catch {
      setUnreachable(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);
  // Status pages live in background tabs; both timers pause while hidden and
  // re-fire on return, so a parked tab burns no requests and no renders.
  useVisiblePoll(load, 10_000);                       // re-probe liveness
  useVisiblePoll(() => setTick(t => t + 1), 1_000);   // count the clock up

  const liveUptime = baseRef.current
    ? baseRef.current.uptime + (Date.now() - baseRef.current.at) / 1000
    : 0;

  const allUp = data && Object.values(data.dependencies).every(Boolean);
  const overallOk = data?.status === 'ok';

  return (
    <div className="min-h-screen w-full flex items-center justify-center px-5 py-10"
      style={{ background: colors.canvas, color: colors.ink, fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }}>
      <div className="w-full max-w-lg">
        {/* Brand */}
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: colors.primary }}>
            <KaeosLogo className="w-6 h-6" color="#ffffff" />
          </div>
          <div className="flex flex-col">
            <span className="text-[18px] font-semibold tracking-tight" style={{ color: colors.ink }}>KAEOS</span>
            <span className="text-[11px] -mt-0.5 tracking-wide uppercase" style={{ color: colors.inkSubtle }}>System Status</span>
          </div>
        </div>

        {/* Overall banner */}
        <div className="rounded-2xl p-6 mb-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          {loading ? (
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 border-2 rounded-full animate-spin" style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />
              <span className="text-[14px]" style={{ color: colors.inkSubtle }}>Checking system health…</span>
            </div>
          ) : unreachable ? (
            <div className="flex items-center gap-3">
              <span className="relative flex w-3 h-3">
                <span className="absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping" style={{ background: colors.error }} />
                <span className="relative inline-flex rounded-full w-3 h-3" style={{ background: colors.error }} />
              </span>
              <div>
                <div className="text-[16px] font-semibold" style={{ color: colors.error }}>Cannot reach KAEOS</div>
                <div className="text-[12px]" style={{ color: colors.inkSubtle }}>The status endpoint did not respond. Retrying automatically.</div>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <span className="relative flex w-3 h-3 flex-shrink-0">
                  <span className="absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping"
                    style={{ background: overallOk ? colors.success : colors.warning }} />
                  <span className="relative inline-flex rounded-full w-3 h-3"
                    style={{ background: overallOk ? colors.success : colors.warning }} />
                </span>
                <div className="min-w-0">
                  <div className="text-[16px] font-semibold" style={{ color: overallOk ? colors.success : colors.warning }}>
                    {overallOk ? (allUp ? 'All systems operational' : 'Operational, degraded dependency') : 'Service degraded'}
                  </div>
                  <div className="text-[12px]" style={{ color: colors.inkSubtle }}>
                    {overallOk ? 'Core services are responding normally.' : 'A critical dependency is unavailable.'}
                  </div>
                </div>
              </div>
              {overallOk
                ? <CheckCircle2 className="w-6 h-6 flex-shrink-0" style={{ color: colors.success }} />
                : <AlertTriangle className="w-6 h-6 flex-shrink-0" style={{ color: colors.warning }} />}
            </div>
          )}
        </div>

        {/* Dependencies */}
        {data && (
          <div className="rounded-2xl overflow-hidden mb-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            {DEP_META.map(({ key, label, sub, icon: Icon }, i) => {
              const up = data.dependencies[key];
              return (
                <div key={key} className="flex items-center gap-3 px-5 py-4"
                  style={{ borderTop: i === 0 ? 'none' : `1px solid ${colors.hairline}` }}>
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ background: (up ? colors.success : colors.error) + '18' }}>
                    <Icon className="w-4 h-4" style={{ color: up ? colors.success : colors.error }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[14px] font-medium truncate" style={{ color: colors.ink }}>{label}</div>
                    <div className="text-[12px] truncate" style={{ color: colors.inkTertiary }}>{sub}</div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="relative flex w-2.5 h-2.5">
                      {up && <span className="absolute inline-flex h-full w-full rounded-full opacity-50 animate-ping" style={{ background: colors.success }} />}
                      <span className="relative inline-flex rounded-full w-2.5 h-2.5" style={{ background: up ? colors.success : colors.error }} />
                    </span>
                    <span className="text-[12px] font-medium" style={{ color: up ? colors.success : colors.error }}>
                      {up ? 'Operational' : 'Down'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Meta */}
        <div className="flex items-center justify-between text-[12px] px-1" style={{ color: colors.inkSubtle }}>
          <div className="flex items-center gap-4">
            {data && <span>Version <span className="font-mono" style={{ color: colors.inkMuted }}>{data.version}</span></span>}
            {data && <span>Uptime <span className="font-mono tabular-nums" style={{ color: colors.inkMuted }}>{formatDuration(liveUptime)}</span></span>}
          </div>
          <span className="inline-flex items-center gap-1"><RefreshCw className="w-3 h-3" /> live</span>
        </div>

        {/* Navigation — never trap the visitor on the public page. */}
        <div className="mt-8 text-center">
          <Link to="/" className="inline-flex items-center gap-1.5 text-[13px] font-medium transition-colors"
            style={{ color: colors.primary }}>
            Go to KAEOS <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    </div>
  );
}
