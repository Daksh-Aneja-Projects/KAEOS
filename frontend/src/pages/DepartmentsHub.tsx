import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { Building2, ArrowRight, Users, Bot, Zap, Activity, Package, LayoutGrid, Waypoints, GitFork } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';
import DomainIcon from '../components/DomainIcon';
import { CountUp } from '../components/CountUp';
import { toPct, humanize } from '../lib/format';
import { canSeeDepartment } from '../lib/departments';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { BrainError } from '../components/BrainStates';
import NeuralMapView from '../components/neural/NeuralMap';
import HierarchyView from '../components/neural/HierarchyView';

/**
 * Departments directory - the single place to jump into any of the governed AI
 * departments. Distinct from the Dashboard (which is the workforce-wide metrics
 * overview); this is the "pick a department" hub.
 */
type HubView = 'grid' | 'neural' | 'hierarchy';

export default function DepartmentsHub() {
  const { colors } = useTheme();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const view = (params.get('view') as HubView) || 'grid';
  const setView = (v: HubView) => setParams(v === 'grid' ? {} : { view: v }, { replace: true });
  const [allDepts, setAllDepts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Department-scoped users only see their own department here; org-wide
  // users (department = null) see the full directory.
  const depts = allDepts.filter(d => canSeeDepartment(user?.department, d.slug || d.id));

  // `silent === true` skips the spinner so the interval refresh updates the grid
  // in place; the initial load and the error-retry still show it.
  const load = React.useCallback((silent?: boolean) => {
    if (silent !== true) setLoading(true);
    setError(null);
    return api.getWorkforceDepartments()
      .then((d: any) => {
        const arr = Array.isArray(d) ? d : (d?.departments || []);
        setAllDepts(arr);
      })
      .catch((e: any) => setError(e?.message || 'Failed to load departments'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(() => load(true), { intervalMs: 20000 });

  const card: React.CSSProperties = {
    background: colors.surface1, borderRadius: '14px', border: `1px solid ${colors.hairline}`,
  };

  const VIEWS: { id: HubView; label: string; icon: React.ElementType }[] = [
    { id: 'grid', label: 'Grid', icon: LayoutGrid },
    { id: 'neural', label: 'Neural map', icon: Waypoints },
    { id: 'hierarchy', label: 'Hierarchy', icon: GitFork },
  ];

  return (
    <div className="h-full flex flex-col min-h-0" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="w-full max-w-7xl mx-auto px-6 pt-6 pb-4 shrink-0">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
              <Building2 className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">Departments</h1>
              <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
                {view === 'neural'
                  ? 'Your company as a free-flow living graph: agents, tasks, systems and the brain that links every department. Drag anything, click any node.'
                  : view === 'hierarchy'
                    ? 'The chain of command: you, the Copilot, and every department it orchestrates.'
                    : 'Your governed AI departments. Open one to see its live work, or add a new one from the marketplace.'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {/* View switcher */}
            <div className="flex items-center p-0.5 rounded-lg"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}
              role="tablist" aria-label="Departments view">
              {VIEWS.map(v => (
                <button key={v.id} onClick={() => setView(v.id)} role="tab" aria-selected={view === v.id}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-semibold transition-all"
                  style={view === v.id
                    ? { background: colors.primary, color: '#fff' }
                    : { color: colors.inkSubtle }}>
                  <v.icon className="w-3.5 h-3.5" /> {v.label}
                </button>
              ))}
            </div>
            <button onClick={() => navigate('/marketplace')}
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-[13px] font-semibold text-white transition-all hover:opacity-90"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
              <Package className="w-4 h-4" /> Add from marketplace
            </button>
          </div>
        </div>
      </div>

      <div className={view === 'neural' ? 'flex-1 min-h-0 w-full' : 'flex-1 min-h-0 w-full max-w-7xl mx-auto px-6 pb-6'}>
        {view === 'neural' ? (
          <NeuralMapView onOpenDept={(slug) => navigate(`/departments/${slug}`)} />
        ) : view === 'hierarchy' ? (
          <HierarchyView />
        ) : (
        <div className="h-full overflow-y-auto space-y-5">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />
          </div>
        ) : error ? (
          <BrainError message={error} onRetry={load} />
        ) : depts.length === 0 ? (
          <div style={card} className="text-center py-16 px-6">
            <Building2 className="w-9 h-9 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
            <div className="text-[15px] font-semibold">No departments yet</div>
            <p className="text-[13px] mt-1 max-w-sm mx-auto" style={{ color: colors.inkSubtle }}>
              Browse the marketplace and deploy your first governed AI department from a domain pack in a few guided steps.
            </p>
            <button onClick={() => navigate('/marketplace')}
              className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: colors.primary }}>
              <Package className="w-4 h-4" /> Browse marketplace
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {depts.map(d => {
              const health = toPct(d.health_score);
              const slug = d.slug || d.id;
              return (
                <div key={d.id} style={card}
                  onClick={() => navigate(`/departments/${slug}`)}
                  role="button" tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/departments/${slug}`); }}
                  className="p-5 cursor-pointer transition-all hover:-translate-y-0.5 group">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <DomainIcon hint={d.slug || d.icon} fallbackHint={d.name} size={44} />
                      <div className="min-w-0">
                        <h3 className="text-[15px] font-bold truncate group-hover:text-primary transition-colors" title={d.name} style={{ color: colors.ink }}>{d.name}</h3>
                        <span className="text-[11px] font-medium px-1.5 py-0.5 rounded-full"
                          style={{ background: (d.status === 'ACTIVE' ? colors.success : colors.inkSubtle) + '20', color: d.status === 'ACTIVE' ? colors.success : colors.inkSubtle }}>
                          {humanize(d.status || 'Active')}
                        </span>
                      </div>
                    </div>
                    {health != null && (
                      <div className="flex items-center gap-1 shrink-0 text-[12px] font-semibold" style={{ color: health >= 80 ? colors.success : health >= 60 ? colors.warning : colors.error }}>
                        <Activity className="w-3.5 h-3.5" /> <CountUp value={Math.round(health)} suffix="%" />
                      </div>
                    )}
                  </div>
                  <p className="text-[12px] mt-3 line-clamp-2" style={{ color: colors.inkSubtle }}>
                    {d.description || `AI-powered ${d.name} department.`}
                  </p>
                  <div className="grid grid-cols-4 gap-2 mt-4 pt-3 border-t" style={{ borderColor: colors.hairline }}>
                    {[
                      { icon: Users, label: 'Staff', value: d.employee_count ?? 0 },
                      { icon: Bot, label: 'Agents', value: d.agent_count ?? 0 },
                      { icon: Zap, label: 'Caps', value: d.capability_count ?? 0 },
                      { icon: Activity, label: 'Procs', value: d.process_count ?? 0 },
                    ].map(s => (
                      <div key={s.label} className="text-center">
                        <div className="text-[15px] font-bold tabular-nums" style={{ color: colors.ink }}><CountUp value={s.value} /></div>
                        <div className="text-[11px] uppercase tracking-wider mt-0.5" style={{ color: colors.inkTertiary }}>{s.label}</div>
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center justify-end gap-1 mt-3 text-[12px] font-medium" style={{ color: colors.primary }}>
                    Open <ArrowRight className="w-3.5 h-3.5" />
                  </div>
                </div>
              );
            })}
          </div>
        )}
        </div>
        )}
      </div>
    </div>
  );
}
