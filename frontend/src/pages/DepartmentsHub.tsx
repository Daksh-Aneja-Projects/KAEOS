import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Building2, ArrowRight, Users, Bot, Zap, Activity, Rocket } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import DomainIcon from '../components/DomainIcon';
import { toPct } from '../lib/format';

/**
 * Departments directory - the single place to jump into any of the governed AI
 * departments. Distinct from the Dashboard (which is the workforce-wide metrics
 * overview); this is the "pick a department" hub.
 */
export default function DepartmentsHub() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [depts, setDepts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.getWorkforceDepartments()
      .then((d: any) => {
        if (cancelled) return;
        const arr = Array.isArray(d) ? d : (d?.departments || []);
        setDepts(arr);
      })
      .catch(() => setDepts([]))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const card: React.CSSProperties = {
    background: colors.surface1, borderRadius: '14px', border: `1px solid ${colors.hairline}`,
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
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
                Your governed AI departments. Open one to see its live work, or deploy a new one.
              </p>
            </div>
          </div>
          <button onClick={() => navigate('/deploy')}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-[13px] font-semibold text-white transition-all hover:opacity-90"
            style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
            <Rocket className="w-4 h-4" /> Deploy department
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />
          </div>
        ) : depts.length === 0 ? (
          <div style={card} className="text-center py-16 px-6">
            <Building2 className="w-9 h-9 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
            <div className="text-[15px] font-semibold">No departments yet</div>
            <p className="text-[13px] mt-1 max-w-sm mx-auto" style={{ color: colors.inkSubtle }}>
              Deploy your first governed AI department from a domain pack in four guided steps.
            </p>
            <button onClick={() => navigate('/deploy')}
              className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: colors.primary }}>
              <Rocket className="w-4 h-4" /> Deploy a department
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
                        <h3 className="text-[15px] font-bold truncate group-hover:text-primary transition-colors" style={{ color: colors.ink }}>{d.name}</h3>
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full"
                          style={{ background: (d.status === 'ACTIVE' ? colors.success : colors.inkSubtle) + '20', color: d.status === 'ACTIVE' ? colors.success : colors.inkSubtle }}>
                          {d.status || 'ACTIVE'}
                        </span>
                      </div>
                    </div>
                    {health != null && (
                      <div className="flex items-center gap-1 shrink-0 text-[12px] font-semibold" style={{ color: health >= 80 ? colors.success : health >= 60 ? colors.warning : colors.error }}>
                        <Activity className="w-3.5 h-3.5" /> {Math.round(health)}%
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
                        <div className="text-[15px] font-bold tabular-nums" style={{ color: colors.ink }}>{s.value}</div>
                        <div className="text-[9px] uppercase tracking-wider mt-0.5" style={{ color: colors.inkTertiary }}>{s.label}</div>
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
    </div>
  );
}
