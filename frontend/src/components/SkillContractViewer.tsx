import React, { useState } from 'react';
import type { SkillItem } from '../api/client';
import {
  FileCode2, Play, ShieldCheck, AlertTriangle, Gauge, Wrench,
  ChevronDown, ChevronRight, CheckCircle2, XCircle, ArrowRight,
  Clock, Link2, Eye, Sparkles
} from 'lucide-react';

interface Props {
  skill: SkillItem;
  colors: any;
  onClose: () => void;
}

export default function SkillContractViewer({ skill, colors, onClose }: Props) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(['triggers', 'steps', 'guardrails'])
  );

  const toggle = (id: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const confColor = (v: number) =>
    v >= 0.85 ? colors.success : v >= 0.7 ? colors.info : v >= 0.5 ? colors.warning : colors.error;

  // ── Section wrapper ─────────────────────────────────────────────────────
  const Section = ({ id, title, icon: Icon, count, children }: {
    id: string; title: string; icon: any; count?: number; children: React.ReactNode;
  }) => {
    const open = expandedSections.has(id);
    return (
      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <button onClick={() => toggle(id)}
          className="w-full flex items-center gap-3 px-5 py-3.5 text-left transition-colors"
          style={{ borderBottom: open ? `1px solid ${colors.hairline}` : 'none' }}
          onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
          onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
          <Icon className="w-4 h-4" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium flex-1" style={{ color: colors.ink }}>{title}</span>
          {count != null && (
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full"
              style={{ background: `${colors.primary}12`, color: colors.primary }}>{count}</span>
          )}
          {open
            ? <ChevronDown className="w-4 h-4" style={{ color: colors.inkTertiary }} />
            : <ChevronRight className="w-4 h-4" style={{ color: colors.inkTertiary }} />}
        </button>
        {open && <div className="px-5 py-4">{children}</div>}
      </div>
    );
  };

  const steps = (skill.steps || []) as any[];
  const exceptions = (skill.exceptions || []) as any[];
  const guardrails = (skill.guardrails || {}) as any;
  const triggers = (skill.triggers || []) as any[];
  const confVector = skill.confidence_vector || {};

  return (
    <div className="p-6 max-w-[1100px] mx-auto space-y-5">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <button onClick={onClose} className="flex items-center gap-1.5 text-[13px] font-medium"
        style={{ color: colors.primary }}>
        <ChevronRight className="w-4 h-4 rotate-180" /> Back to Skills
      </button>

      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <FileCode2 className="w-6 h-6" style={{ color: colors.primaryHover }} />
            <h1 className="text-[24px] font-bold tracking-tight" style={{ letterSpacing: '-0.5px', color: colors.ink }}>
              {skill.skill_id.replace(/_/g, ' ')}
            </h1>
            <span className="text-[11px] font-bold px-2 py-0.5 rounded-full"
              style={{
                background: skill.status === 'ACTIVE' ? 'rgba(39,166,68,0.12)' : 'rgba(245,166,35,0.12)',
                color: skill.status === 'ACTIVE' ? colors.success : colors.warning,
              }}>{skill.status}</span>
          </div>
          <div className="flex items-center gap-3 text-[12px]" style={{ color: colors.inkSubtle }}>
            <span>{skill.department}</span>
            <span>·</span>
            <span>{skill.domain}</span>
            <span>·</span>
            <span>v{skill.version}</span>
            <span>·</span>
            <span>{skill.execution_count?.toLocaleString()} executions</span>
          </div>
        </div>
      </div>

      {/* ── 5D Confidence Radar ────────────────────────────────────────────── */}
      <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="flex items-center gap-2 mb-4">
          <Gauge className="w-4 h-4" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Confidence Vector</span>
          <span className="text-[20px] font-bold ml-auto" style={{ color: confColor(skill.confidence) }}>
            {(skill.confidence * 100).toFixed(0)}%
          </span>
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full"
            style={{ background: `${confColor(skill.confidence)}15`, color: confColor(skill.confidence) }}>
            {skill.confidence_tier?.replace(/_/g, ' ')}
          </span>
        </div>
        <div className="grid grid-cols-5 gap-3">
          {[
            { key: 'source_breadth', label: 'Breadth' },
            { key: 'source_authority', label: 'Authority' },
            { key: 'temporal_freshness', label: 'Freshness' },
            { key: 'outcome_validation', label: 'Outcome' },
            { key: 'explicit_validation', label: 'Explicit' },
          ].map(d => {
            const val = (confVector as any)[d.key] || 0;
            return (
              <div key={d.key} className="text-center">
                <div className="text-[10px] uppercase font-semibold mb-2" style={{ color: colors.inkTertiary }}>{d.label}</div>
                <div className="relative mx-auto" style={{ width: 52, height: 52 }}>
                  <svg width="52" height="52" viewBox="0 0 52 52">
                    <circle cx="26" cy="26" r="22" fill="none" stroke={colors.surface3} strokeWidth="4" />
                    <circle cx="26" cy="26" r="22" fill="none"
                      stroke={confColor(val)} strokeWidth="4"
                      strokeDasharray={`${val * 138.2} 138.2`}
                      strokeLinecap="round" transform="rotate(-90 26 26)" />
                    <text x="26" y="30" textAnchor="middle" fill={colors.ink} fontSize="12" fontWeight="700">
                      {(val * 100).toFixed(0)}
                    </text>
                  </svg>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Triggers ──────────────────────────────────────────────────────── */}
      <Section id="triggers" title="Triggers" icon={Play} count={triggers.length}>
        <div className="space-y-2">
          {triggers.map((t: any, i: number) => (
            <div key={i} className="flex items-center gap-3 p-3 rounded-lg"
              style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
              <Play className="w-4 h-4 flex-shrink-0" style={{ color: colors.success }} />
              <span className="text-[13px] font-mono" style={{ color: colors.inkMuted }}>
                {typeof t === 'string' ? t : t.condition || JSON.stringify(t)}
              </span>
            </div>
          ))}
          {triggers.length === 0 && <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No triggers defined</p>}
        </div>
      </Section>

      {/* ── Execution Steps (Visual Pipeline) ─────────────────────────────── */}
      <Section id="steps" title="Execution Steps" icon={ArrowRight} count={steps.length}>
        <div className="space-y-1">
          {steps.map((step: any, i: number) => (
            <div key={step.id || i}>
              <div className="flex items-start gap-3 p-3 rounded-lg"
                style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                {/* Step Number */}
                <div className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 text-[11px] font-bold"
                  style={{ background: `${colors.primary}15`, color: colors.primary, border: `1px solid ${colors.primary}30` }}>
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium" style={{ color: colors.ink }}>
                      {(step.action || step.id || '').replace(/_/g, ' ')}
                    </span>
                    {step.tool && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                        style={{ background: `${colors.info}12`, color: colors.info }}>
                        <Wrench className="w-3 h-3 inline mr-0.5" />{step.tool}
                      </span>
                    )}
                  </div>
                  {step.condition && (
                    <div className="flex items-center gap-1.5 mt-1.5">
                      <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded"
                        style={{ background: `${colors.warning}12`, color: colors.warning }}>IF</span>
                      <span className="text-[11px] font-mono" style={{ color: colors.inkSubtle }}>{step.condition}</span>
                    </div>
                  )}
                  {step.thresholds && (
                    <div className="flex gap-2 mt-1.5 flex-wrap">
                      {Object.entries(step.thresholds).map(([k, v]) => (
                        <span key={k} className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                          style={{ background: colors.surface3, color: colors.inkSubtle }}>
                          {k}: {String(v)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              {/* Connector */}
              {i < steps.length - 1 && (
                <div className="flex items-center justify-center py-0.5">
                  <div className="w-px h-3" style={{ background: colors.hairlineStrong }} />
                </div>
              )}
            </div>
          ))}
        </div>
      </Section>

      {/* ── Exceptions ────────────────────────────────────────────────────── */}
      <Section id="exceptions" title="Exceptions & Overrides" icon={AlertTriangle} count={exceptions.length}>
        <div className="space-y-2">
          {exceptions.map((exc: any, i: number) => (
            <div key={exc.id || i} className="flex items-start gap-3 p-3 rounded-lg"
              style={{ background: 'rgba(245,166,35,0.04)', border: '1px solid rgba(245,166,35,0.15)' }}>
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: colors.warning }} />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>
                    {(exc.id || '').replace(/_/g, ' ')}
                  </span>
                  {exc.auto_apply && (
                    <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full"
                      style={{ background: 'rgba(229,83,75,0.1)', color: colors.error }}>AUTO-APPLY</span>
                  )}
                  {exc.confidence != null && (
                    <span className="text-[10px] font-mono ml-auto" style={{ color: colors.inkTertiary }}>
                      conf: {exc.confidence}
                    </span>
                  )}
                </div>
                <p className="text-[11px] font-mono mt-1" style={{ color: colors.inkSubtle }}>{exc.condition}</p>
                {exc.override && <p className="text-[11px] mt-1" style={{ color: colors.warning }}>Override: {exc.override}</p>}
              </div>
            </div>
          ))}
          {exceptions.length === 0 && <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No exceptions defined</p>}
        </div>
      </Section>

      {/* ── Guardrails ────────────────────────────────────────────────────── */}
      <Section id="guardrails" title="Guardrails" icon={ShieldCheck}
        count={(guardrails.pre_execution?.length || 0) + (guardrails.post_execution?.length || 0)}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Pre-execution */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[11px] font-bold uppercase" style={{ color: colors.warning }}>Pre-Execution</span>
            </div>
            <div className="space-y-1.5">
              {(guardrails.pre_execution || []).map((g: string, i: number) => (
                <div key={i} className="flex items-start gap-2 p-2.5 rounded-lg"
                  style={{ background: 'rgba(245,166,35,0.04)', border: '1px solid rgba(245,166,35,0.12)' }}>
                  <Eye className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" style={{ color: colors.warning }} />
                  <span className="text-[11px] font-mono" style={{ color: colors.inkMuted }}>{g}</span>
                </div>
              ))}
            </div>
          </div>
          {/* Post-execution */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[11px] font-bold uppercase" style={{ color: colors.success }}>Post-Execution</span>
            </div>
            <div className="space-y-1.5">
              {(guardrails.post_execution || []).map((g: string, i: number) => (
                <div key={i} className="flex items-start gap-2 p-2.5 rounded-lg"
                  style={{ background: 'rgba(39,166,68,0.04)', border: '1px solid rgba(39,166,68,0.12)' }}>
                  <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" style={{ color: colors.success }} />
                  <span className="text-[11px] font-mono" style={{ color: colors.inkMuted }}>{g}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Section>

      {/* ── MCP Tool Bindings ──────────────────────────────────────────────── */}
      <Section id="tools" title="MCP Tool Bindings" icon={Link2} count={skill.mcp_tool_bindings?.length || 0}>
        <div className="flex gap-2 flex-wrap">
          {(skill.mcp_tool_bindings || []).map((tool: string) => (
            <div key={tool} className="flex items-center gap-1.5 px-3 py-2 rounded-lg"
              style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
              <Wrench className="w-3.5 h-3.5" style={{ color: colors.primary }} />
              <span className="text-[12px] font-mono font-medium" style={{ color: colors.ink }}>{tool}</span>
            </div>
          ))}
        </div>
      </Section>

      {/* ── Compliance Tags ────────────────────────────────────────────────── */}
      {skill.compliance_tags?.length > 0 && (
        <div className="flex items-center gap-3 px-5 py-3 rounded-xl"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <ShieldCheck className="w-4 h-4" style={{ color: colors.info }} />
          <span className="text-[12px] font-medium" style={{ color: colors.inkSubtle }}>Compliance:</span>
          {skill.compliance_tags.map((tag: string) => (
            <span key={tag} className="text-[10px] font-bold px-2 py-0.5 rounded"
              style={{ background: `${colors.info}12`, color: colors.info, border: `1px solid ${colors.info}25` }}>
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* ── Metadata Footer ───────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 text-[11px] px-2" style={{ color: colors.inkTertiary }}>
        <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> Half-life: {skill.half_life_days}d</span>
        <span className="flex items-center gap-1"><Sparkles className="w-3 h-3" /> Success: {(skill.success_rate * 100).toFixed(1)}%</span>
      </div>
    </div>
  );
}
