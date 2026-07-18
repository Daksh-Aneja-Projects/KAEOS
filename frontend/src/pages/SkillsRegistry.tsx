import React, { useEffect, useState } from 'react';
import type { SkillItem, ExecutionItem } from '../api/client';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainEmpty } from '../components/BrainStates';
import SkillContractViewer from '../components/SkillContractViewer';
import { BrainCircuit, Search, Play, CheckCircle, XCircle, Clock, ChevronDown, ChevronRight, Zap, FileCode2 } from 'lucide-react';

export default function SkillsRegistry({ domain = 'All Domains' }: { domain?: string }) {
  const { colors } = useTheme();
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [totalExec, setTotalExec] = useState(0);
  const [avgSr, setAvgSr] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [viewContract, setViewContract] = useState<SkillItem | null>(null);
  const [execs, setExecs] = useState<ExecutionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    setLoading(true);
    const d = domain.toLowerCase() === 'all domains' ? 'all' : domain.toLowerCase();
    const params = d === 'all' ? {} : { domain: d };

    api.getSkills().then((r) => {
      setSkills(r.skills);
      setTotalExec(r.total_executions);
      setAvgSr(r.avg_success_rate);
      setLoading(false);
    });
  }, [domain]);

  useEffect(() => {
    if (selected) {
      api.getExecutions(selected).then(setExecs);
    }
  }, [selected]);

  const filteredSkills = skills.filter(s =>
    s.skill_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    s.department.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) return <BrainLoading message="Loading the Skill Compiler…" />;

  // Show contract viewer if a skill is selected for contract view
  if (viewContract) {
    return <SkillContractViewer skill={viewContract} colors={colors} onClose={() => setViewContract(null)} />;
  }

  const card: React.CSSProperties = {
    background: colors.surface1,
    border: `1px solid ${colors.hairline}`,
    borderRadius: '14px',
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
              <BrainCircuit className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">Skills Registry</h1>
              <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
                Skill Compiler - {skills.length} compiled skills · {totalExec.toLocaleString()} total executions · {(avgSr * 100).toFixed(1)}% avg success
              </p>
            </div>
          </div>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
            <input
              type="text"
              placeholder="Search skills..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10 pr-4 py-2 rounded-lg text-[13px] w-64 outline-none transition-all focus:ring-2"
              style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}
            />
          </div>
        </div>

        {filteredSkills.length === 0 ? (
          <div style={card}>
            <BrainEmpty
              title="No skills match your search"
              action="Try a different term or clear the search box."
              icon={BrainCircuit}
            />
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredSkills.map((s) => {
              const isSelected = selected === s.skill_id;
              const gaugeColor = s.confidence >= 0.9 ? colors.success : s.confidence >= 0.8 ? colors.primary : colors.warning;
              return (
                <div
                  key={s.id}
                  className="transition-all"
                  style={{
                    ...card,
                    borderColor: isSelected ? colors.primary : colors.hairline,
                    boxShadow: isSelected ? `0 0 0 2px ${colors.primary}33` : 'none',
                  }}
                >
                  <div className="p-6">
                    {/* Header */}
                    <div className="flex items-start justify-between mb-4">
                      <div>
                        <h3 className="text-[15px] font-bold" style={{ color: colors.ink }}>{s.skill_id.replace(/_/g, ' ')}</h3>
                        <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>{s.department} · v{s.version}</p>
                      </div>
                      <span className="px-2.5 py-1 rounded-full text-[11px] font-bold tracking-wide"
                        style={s.status === 'ACTIVE'
                          ? { background: colors.success + '1f', color: colors.success, border: `1px solid ${colors.success}3d` }
                          : { background: colors.warning + '1f', color: colors.warning, border: `1px solid ${colors.warning}3d` }}>
                        {s.status}
                      </span>
                    </div>

                    {/* Confidence Gauge */}
                    <div className="flex items-center gap-4 mb-5">
                      <svg width="56" height="56" viewBox="0 0 56 56">
                        <circle cx="28" cy="28" r="24" fill="none" stroke={colors.surface3} strokeWidth="4" />
                        <circle
                          cx="28" cy="28" r="24" fill="none"
                          stroke={gaugeColor}
                          strokeWidth="4"
                          strokeDasharray={`${s.confidence * 150.8} 150.8`}
                          strokeLinecap="round"
                          transform="rotate(-90 28 28)"
                        />
                        <text x="28" y="32" textAnchor="middle" fill={colors.ink} fontSize="13" fontWeight="700">
                          {(s.confidence * 100).toFixed(0)}
                        </text>
                      </svg>
                      <div>
                        <div className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: colors.inkSubtle }}>Confidence</div>
                        <div className="text-[13px] font-medium" style={{ color: colors.inkMuted }}>{s.confidence_tier?.replace(/_/g, ' ')}</div>
                      </div>
                    </div>

                    {/* Stats Grid */}
                    <div className="grid grid-cols-4 gap-3 rounded-xl p-3" style={{ background: colors.canvas }}>
                      <div className="text-center">
                        <div className="text-[12px]" style={{ color: colors.inkSubtle }}>Executions</div>
                        <div className="text-[13px] font-bold mt-0.5 tabular-nums" style={{ color: colors.ink }}>{s.execution_count.toLocaleString()}</div>
                      </div>
                      <div className="text-center">
                        <div className="text-[12px]" style={{ color: colors.inkSubtle }}>Success</div>
                        <div className="text-[13px] font-bold mt-0.5 tabular-nums" style={{ color: colors.success }}>{(s.success_rate * 100).toFixed(1)}%</div>
                      </div>
                      <div className="text-center">
                        <div className="text-[12px]" style={{ color: colors.inkSubtle }}>Half-Life</div>
                        <div className="text-[13px] font-bold mt-0.5 tabular-nums" style={{ color: colors.ink }}>{s.half_life_days}d</div>
                      </div>
                      <div className="text-center">
                        <div className="text-[12px]" style={{ color: colors.inkSubtle }}>Tools</div>
                        <div className="text-[13px] font-bold mt-0.5 tabular-nums" style={{ color: colors.ink }}>{s.mcp_tool_bindings?.length || 0}</div>
                      </div>
                    </div>

                    {/* Compliance Tags */}
                    {s.compliance_tags?.length > 0 && (
                      <div className="mt-3 flex gap-1.5 flex-wrap">
                        {s.compliance_tags.map((t) => (
                          <span key={t} className="px-2 py-0.5 text-[10px] font-semibold rounded"
                            style={{ background: colors.info + '18', color: colors.info, border: `1px solid ${colors.info}30` }}>{t}</span>
                        ))}
                      </div>
                    )}

                    {/* Action Buttons */}
                    <div className="mt-4 flex gap-2">
                      <button
                        onClick={() => setViewContract(s)}
                        className="flex-1 text-center text-[12px] font-medium flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg transition-all hover:opacity-90"
                        style={{ background: `${colors.primary}15`, color: colors.primary, border: `1px solid ${colors.primary}30` }}
                      >
                        <FileCode2 className="w-3 h-3" /> View Contract
                      </button>
                      <button
                        onClick={() => setSelected(isSelected ? null : s.skill_id)}
                        className="text-[12px] flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg transition-all hover:opacity-90"
                        style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}
                      >
                        {isSelected ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                        {isSelected ? 'Collapse' : 'Executions'}
                      </button>
                    </div>
                  </div>

                  {/* Expanded Detail */}
                  {isSelected && (
                    <div className="p-6 space-y-5" style={{ borderTop: `1px solid ${colors.hairline}`, background: colors.canvas }}>
                      <div>
                        <h4 className="text-[13px] font-semibold mb-2 flex items-center gap-2" style={{ color: colors.ink }}>
                          <Zap className="w-4 h-4" style={{ color: colors.primary }} /> MCP Tool Bindings
                        </h4>
                        <div className="flex gap-2 flex-wrap">
                          {s.mcp_tool_bindings?.map((t) => (
                            <span key={t} className="px-2.5 py-1 rounded-lg text-[12px] font-mono"
                              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.primary }}>{t}</span>
                          ))}
                        </div>
                      </div>

                      <div>
                        <h4 className="text-[13px] font-semibold mb-3 flex items-center gap-2" style={{ color: colors.ink }}>
                          <Play className="w-4 h-4" style={{ color: colors.success }} /> Recent Executions
                        </h4>
                        <div className="space-y-2">
                          {execs.slice(0, 5).map((e) => {
                            const ok = e.status.includes('SUCCESS');
                            return (
                              <div key={e.id} className="flex items-center gap-3 rounded-xl p-3"
                                style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                                {ok
                                  ? <CheckCircle className="w-4 h-4 flex-shrink-0" style={{ color: colors.success }} />
                                  : e.status === 'HUMAN_OVERRIDDEN'
                                  ? <Clock className="w-4 h-4 flex-shrink-0" style={{ color: colors.warning }} />
                                  : <XCircle className="w-4 h-4 flex-shrink-0" style={{ color: colors.error }} />}
                                <span className="text-[13px] flex-1 truncate" style={{ color: colors.inkMuted }}>{e.task_intent}</span>
                                <span className="text-[12px] font-mono tabular-nums" style={{ color: colors.inkSubtle }}>{e.duration_ms}ms</span>
                                <span className="px-2 py-0.5 rounded text-[10px] font-bold"
                                  style={ok
                                    ? { background: colors.success + '18', color: colors.success, border: `1px solid ${colors.success}30` }
                                    : { background: colors.warning + '18', color: colors.warning, border: `1px solid ${colors.warning}30` }}>
                                  {e.status.replace(/_/g, ' ')}
                                </span>
                              </div>
                            );
                          })}
                          {execs.length === 0 && (
                            <div className="text-[12px] text-center py-4" style={{ color: colors.inkTertiary }}>No executions recorded yet.</div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
