import React, { useEffect, useState } from 'react';
import type { RuleItem } from '../api/client';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainEmpty } from '../components/BrainStates';
import { BookOpen, Search, ChevronDown, ChevronRight, Shield, Clock, CheckCircle } from 'lucide-react';

const DOMAINS = ['all', 'support', 'sales', 'engineering', 'finance', 'hr'];

// Tier accent colors keyed to the theme's status palette.
function tierColor(tier: string, colors: ReturnType<typeof useTheme>['colors']): string {
  switch (tier) {
    case 'SPECULATIVE': return colors.error;
    case 'INFERRED': return colors.warning;
    case 'VALIDATED_PEER': return colors.info;
    case 'VALIDATED_MANAGER':
    case 'VALIDATED_DH': return colors.primary;
    case 'VERIFIED': return colors.success;
    default: return colors.inkSubtle;
  }
}

export default function RulesExplorer({ domain = 'All Domains' }: { domain?: string }) {
  const { colors } = useTheme();
  const [rules, setRules] = useState<RuleItem[]>([]);
  const [total, setTotal] = useState(0);
  const [localDomain, setLocalDomain] = useState('all');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  // Sync localDomain with the incoming domain prop
  useEffect(() => {
    if (domain) {
      setLocalDomain(domain.toLowerCase() === 'all domains' ? 'all' : domain.toLowerCase());
    }
  }, [domain]);

  useEffect(() => {
    setLoading(true);
    const params = localDomain === 'all' ? {} : { domain: localDomain };
    api.getRules(params).then((r) => { setRules(r.rules); setTotal(r.total); setLoading(false); });
  }, [localDomain]);

  const filteredRules = rules.filter(r =>
    r.statement.toLowerCase().includes(searchTerm.toLowerCase()) ||
    r.domain.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) return <BrainLoading message="Loading the Knowledge Polystore…" />;

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
              <BookOpen className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">Rules Explorer</h1>
              <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
                Knowledge Polystore - {total} rules across {DOMAINS.length - 1} domains
              </p>
            </div>
          </div>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
            <input
              type="text"
              placeholder="Search rules..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10 pr-4 py-2 rounded-lg text-[13px] w-64 outline-none transition-all focus:ring-2"
              style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}
            />
          </div>
        </div>

        {/* Domain Filter Pills */}
        <div className="flex gap-2 flex-wrap">
          {DOMAINS.map((d) => {
            const active = localDomain === d;
            return (
              <button
                key={d}
                onClick={() => setLocalDomain(d)}
                className="px-4 py-1.5 rounded-full text-[13px] font-semibold capitalize transition-all hover:opacity-90"
                style={active
                  ? { background: colors.primary, color: '#fff' }
                  : { background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}
              >
                {d}
              </button>
            );
          })}
        </div>

        {/* Rules Table */}
        <div style={{ ...card, overflow: 'hidden' }}>
          {filteredRules.length === 0 ? (
            <BrainEmpty
              title="No rules match your filters"
              action="Try a different domain or clear the search."
              icon={BookOpen}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr style={{ background: colors.canvas, borderBottom: `1px solid ${colors.hairline}` }}>
                    <th className="px-6 py-3.5 text-[11px] font-semibold uppercase tracking-wider w-8" style={{ color: colors.inkSubtle }}></th>
                    <th className="px-6 py-3.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Rule Statement</th>
                    <th className="px-6 py-3.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Domain</th>
                    <th className="px-6 py-3.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Confidence</th>
                    <th className="px-6 py-3.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Tier</th>
                    <th className="px-6 py-3.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Executable</th>
                    <th className="px-6 py-3.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>Compliance</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRules.map((r) => {
                    const tc = tierColor(r.confidence_tier, colors);
                    return (
                      <React.Fragment key={r.id}>
                        <tr
                          onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                          className="transition-colors cursor-pointer group"
                          style={{ borderBottom: `1px solid ${colors.hairline}` }}
                        >
                          <td className="px-6 py-4" style={{ color: colors.inkSubtle }}>
                            {expanded === r.id
                              ? <ChevronDown className="w-4 h-4" />
                              : <ChevronRight className="w-4 h-4" />}
                          </td>
                          <td className="px-6 py-4">
                            <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{r.statement}</span>
                          </td>
                          <td className="px-6 py-4 text-[13px] capitalize" style={{ color: colors.inkMuted }}>{r.domain}</td>
                          <td className="px-6 py-4">
                            <span className="text-[13px] font-bold font-mono tabular-nums" style={{ color: colors.ink }}>{r.confidence_scalar.toFixed(2)}</span>
                          </td>
                          <td className="px-6 py-4">
                            <span className="px-2 py-0.5 rounded text-[11px] font-semibold"
                              style={{ background: tc + '1f', color: tc, border: `1px solid ${tc}3d` }}>
                              {r.confidence_tier?.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            {r.is_executable
                              ? <CheckCircle className="w-4 h-4" style={{ color: colors.success }} />
                              : <span className="text-[12px]" style={{ color: colors.inkTertiary }}>No</span>}
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex gap-1 flex-wrap">
                              {r.compliance_tags?.map((t) => (
                                <span key={t} className="px-2 py-0.5 text-[10px] font-semibold rounded"
                                  style={{ background: colors.info + '18', color: colors.info, border: `1px solid ${colors.info}30` }}>{t}</span>
                              ))}
                            </div>
                          </td>
                        </tr>
                        {expanded === r.id && (
                          <tr>
                            <td colSpan={7} className="px-8 py-6" style={{ background: colors.canvas }}>
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                                <div>
                                  <h3 className="text-[13px] font-semibold mb-4 flex items-center gap-2" style={{ color: colors.ink }}>
                                    <Shield className="w-4 h-4" style={{ color: colors.primary }} /> Confidence Vector (L6)
                                  </h3>
                                  <div className="space-y-3">
                                    {r.confidence_vector && Object.entries(r.confidence_vector).map(([dim, val]) => (
                                      <div key={dim} className="flex items-center gap-3">
                                        <span className="w-36 text-[12px] capitalize" style={{ color: colors.inkSubtle }}>{dim.replace(/_/g, ' ')}</span>
                                        <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: colors.surface3 }}>
                                          <div className="h-full rounded-full transition-all" style={{ width: `${(val as number) * 100}%`, background: colors.primary }} />
                                        </div>
                                        <span className="text-[12px] font-mono tabular-nums w-10 text-right" style={{ color: colors.inkMuted }}>{(val as number).toFixed(2)}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                                <div>
                                  <h3 className="text-[13px] font-semibold mb-4 flex items-center gap-2" style={{ color: colors.ink }}>
                                    <Clock className="w-4 h-4" style={{ color: colors.info }} /> Metadata
                                  </h3>
                                  <div className="space-y-2 text-[13px]" style={{ color: colors.inkMuted }}>
                                    <div className="flex justify-between"><span>Half-Life</span><span className="font-medium" style={{ color: colors.ink }}>{r.half_life_days} days</span></div>
                                    <div className="flex justify-between"><span>Created</span><span className="font-medium" style={{ color: colors.ink }}>{r.created_at ? new Date(r.created_at).toLocaleDateString() : 'N/A'}</span></div>
                                    <div className="flex justify-between"><span>Validated</span><span className="font-medium" style={{ color: colors.ink }}>{r.validated_at ? new Date(r.validated_at).toLocaleDateString() : 'Pending'}</span></div>
                                    <div className="flex justify-between"><span>Compliance</span><span className="font-medium" style={{ color: colors.ink }}>{r.compliance_tags?.join(', ') || 'None'}</span></div>
                                  </div>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
