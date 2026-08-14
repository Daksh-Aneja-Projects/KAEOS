import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  ArrowLeft, ShieldCheck, ShieldAlert, ShieldQuestion, MinusCircle,
  Search, Play, Loader2, X, Scale, FileText, Sparkles,
} from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import DomainIcon from '../components/DomainIcon';
import { StatCard } from '../components/shared/StatCard';
import { BrainLoading, BrainError } from '../components/BrainStates';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

/**
 * Compliance Checker Studio - the honest "does THIS action pass?" surface over
 * the deterministic statutory checker registry. Pick frameworks from the
 * department catalog, hand it a context, and read the verdict as live result
 * cards. Fail-closed: an unbacked tag reads as UNBACKED, never a silent pass.
 */

interface Framework {
  framework: string;
  department: string;
  title: string;
  citation: string;
}

interface Finding {
  code: string;
  message: string;
  severity: string;
}

interface CheckResult {
  framework: string;
  status: 'PASS' | 'BLOCK' | 'ADVISORY' | 'NOT_APPLICABLE' | 'UNBACKED';
  passed: boolean;
  blocking: boolean;
  method: string;
  findings: Finding[];
  citations: string[];
  detail: Record<string, unknown>;
}

type StatusKey = CheckResult['status'];

// Verdict presentation: color + plain-English meaning for each deterministic status.
const STATUS: Record<StatusKey, { label: string; color: string; icon: typeof ShieldCheck; blurb: string }> = {
  PASS: { label: 'Pass', color: '#22c55e', icon: ShieldCheck, blurb: 'Verified compliant by a deterministic statutory check.' },
  BLOCK: { label: 'Blocked', color: '#ef4444', icon: ShieldAlert, blurb: 'A rule was violated. This action fails closed and must not proceed.' },
  ADVISORY: { label: 'Advisory', color: '#f59e0b', icon: ShieldQuestion, blurb: 'Could not fully verify from the facts given. Treated as a concern, not a pass.' },
  NOT_APPLICABLE: { label: 'Not applicable', color: '#8a8f98', icon: MinusCircle, blurb: 'This action does not touch the regulated data, so the regime does not apply.' },
  UNBACKED: { label: 'Unbacked', color: '#e5534b', icon: ShieldAlert, blurb: 'No deterministic checker backs this claim. It is NOT verified and fails closed.' },
};

const SEVERITY_COLOR: Record<string, string> = {
  CRIT: '#ef4444', HIGH: '#f59e0b', MEDI: '#3b82f6', LOW: '#8a8f98',
};

// Quick-fill contexts so the operator is not staring at a blank editor. The
// checkers read structured facts; these are the common shapes.
const PRESETS: { label: string; icon: typeof Scale; json: Record<string, unknown> }[] = [
  {
    label: 'Approved financial action', icon: ShieldCheck,
    json: { is_financial: true, has_human_approver: true, maker: 'alice.chen', approver: 'bob.torres' },
  },
  {
    label: 'Missing approver', icon: ShieldAlert,
    json: { is_financial: true, has_human_approver: false, maker: 'alice.chen' },
  },
  {
    label: 'PII export request', icon: FileText,
    json: { involves_pii: true, has_consent: false, data_subject_region: 'EU', purpose: 'analytics' },
  },
];

const DEFAULT_CONTEXT = JSON.stringify(PRESETS[0].json, null, 2);

export default function ComplianceChecker() {
  const { colors } = useTheme();
  const navigate = useNavigate();

  const [catalog, setCatalog] = useState<Framework[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [contextText, setContextText] = useState(DEFAULT_CONTEXT);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [results, setResults] = useState<CheckResult[] | null>(null);

  const load = () => {
    setLoadError(null);
    api.compliance
      .frameworks()
      .then((r: { frameworks: Framework[] }) => setCatalog(r.frameworks || []))
      .catch((e: any) => setLoadError(e?.message || 'Failed to load the framework catalog.'));
  };

  useEffect(load, []);

  // Group the catalog by department for the left rail.
  const grouped = useMemo(() => {
    if (!catalog) return [];
    const q = query.trim().toLowerCase();
    const map = new Map<string, Framework[]>();
    for (const f of catalog) {
      if (q && !(`${f.title} ${f.framework} ${f.department} ${f.citation}`.toLowerCase().includes(q))) continue;
      const list = map.get(f.department) || [];
      list.push(f);
      map.set(f.department, list);
    }
    return [...map.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([dept, items]) => ({ dept, items: items.sort((x, y) => x.framework.localeCompare(y.framework)) }));
  }, [catalog, query]);

  const byTag = useMemo(() => {
    const m = new Map<string, Framework>();
    for (const f of catalog || []) m.set(f.framework.toUpperCase(), f);
    return m;
  }, [catalog]);

  const toggle = (tag: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  };

  // Live parse feedback for the context editor.
  const parsedContext = useMemo<{ ok: boolean; value?: Record<string, unknown>; error?: string }>(() => {
    const t = contextText.trim();
    if (!t) return { ok: true, value: {} };
    try {
      const v = JSON.parse(t);
      if (typeof v !== 'object' || v === null || Array.isArray(v)) return { ok: false, error: 'Context must be a JSON object.' };
      return { ok: true, value: v };
    } catch (e: any) {
      return { ok: false, error: e?.message || 'Invalid JSON.' };
    }
  }, [contextText]);

  const canRun = selected.size > 0 && parsedContext.ok && !running;

  const run = async () => {
    if (!canRun) return;
    setRunning(true);
    setRunError(null);
    try {
      const res = await api.compliance.check({
        frameworks: [...selected],
        context: parsedContext.value || {},
      });
      setResults(res.results || []);
    } catch (e: any) {
      setRunError(e?.message || 'The compliance check failed to run.');
    } finally {
      setRunning(false);
    }
  };

  // Tallies for the live count-up header.
  const tally = useMemo(() => {
    const t: Record<StatusKey, number> = { PASS: 0, BLOCK: 0, ADVISORY: 0, NOT_APPLICABLE: 0, UNBACKED: 0 };
    for (const r of results || []) t[r.status] = (t[r.status] || 0) + 1;
    return t;
  }, [results]);

  const inputStyle: React.CSSProperties = {
    background: colors.surface2,
    border: `1px solid ${colors.hairline}`,
    color: colors.ink,
  };

  return (
    <div className={`h-full flex flex-col overflow-hidden ${PAGE_PAD}`}>
      <style>{`
        @keyframes ccIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
        .cc-in { animation: ccIn .5s cubic-bezier(.16,1,.3,1) both; }
        @media (prefers-reduced-motion: reduce) { .cc-in { animation: none; } }
      `}</style>

      {/* Header */}
      <div className="shrink-0">
        <button
          onClick={() => navigate('/platform/decisions')}
          className="inline-flex items-center gap-1.5 text-[13px] font-medium mb-3 transition-opacity hover:opacity-70"
          style={{ color: colors.inkSubtle }}
        >
          <ArrowLeft className="w-4 h-4" /> Back to Decisions
        </button>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 min-w-0">
            <span className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: colors.primary + '1f', color: colors.primary }}>
              <Scale className="w-6 h-6" />
            </span>
            <div className="min-w-0">
              <h1 className="text-[22px] font-bold leading-tight" style={{ color: colors.ink }}>Compliance Checker Studio</h1>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deterministic statutory checks, one governance spine. Unbacked claims fail closed, never a silent pass.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3 shrink-0">
            <StatCard label="Pass" value={tally.PASS} accent={STATUS.PASS.color} className="!p-3 min-w-[104px]"
              icon={<ShieldCheck className="w-4 h-4" />} />
            <StatCard label="Blocked" value={tally.BLOCK + tally.UNBACKED} accent={STATUS.BLOCK.color} className="!p-3 min-w-[104px]"
              icon={<ShieldAlert className="w-4 h-4" />} />
            <StatCard label="Advisory" value={tally.ADVISORY} accent={STATUS.ADVISORY.color} className="!p-3 min-w-[104px]"
              icon={<ShieldQuestion className="w-4 h-4" />} />
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 mt-5 grid gap-5 lg:grid-cols-[320px_1fr] grid-cols-1">
        {/* Left rail: framework catalog by department */}
        <aside className="min-h-0 flex flex-col rounded-xl overflow-hidden"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="shrink-0 p-3 border-b" style={{ borderColor: colors.hairline }}>
            <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg" style={inputStyle}>
              <Search className="w-4 h-4 shrink-0" style={{ color: colors.inkSubtle }} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search 27 checkers…"
                className="bg-transparent outline-none text-[13px] w-full"
                style={{ color: colors.ink }}
              />
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-3">
            {loadError && <BrainError message={loadError} onRetry={load} />}
            {!catalog && !loadError && <BrainLoading message="Loading the statutory catalog…" />}
            {grouped.map(({ dept, items }) => (
              <div key={dept}>
                <div className="flex items-center gap-2 px-1.5 pb-1.5">
                  <DomainIcon hint={dept} size={22} />
                  <span className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>
                    {humanize(dept)}
                  </span>
                  <span className="text-[11px] ml-auto" style={{ color: colors.inkTertiary }}>{items.length}</span>
                </div>
                <div className="space-y-1">
                  {items.map((f) => {
                    const on = selected.has(f.framework);
                    return (
                      <button
                        key={f.framework}
                        onClick={() => toggle(f.framework)}
                        className="w-full text-left px-2.5 py-2 rounded-lg transition-colors"
                        style={{
                          background: on ? colors.primary + '1f' : 'transparent',
                          border: `1px solid ${on ? colors.primary + '55' : 'transparent'}`,
                        }}
                      >
                        <div className="flex items-center gap-2">
                          <span className="w-4 h-4 rounded-[5px] shrink-0 flex items-center justify-center"
                            style={{ border: `1.5px solid ${on ? colors.primary : colors.hairlineStrong}`, background: on ? colors.primary : 'transparent' }}>
                            {on && <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="#fff" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>}
                          </span>
                          <span className="text-[13px] font-semibold truncate" style={{ color: colors.ink }}>{f.title}</span>
                        </div>
                        <div className="text-[11px] mt-0.5 pl-6 truncate" style={{ color: colors.inkTertiary }}>{f.citation}</div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
            {catalog && grouped.length === 0 && (
              <p className="text-[13px] text-center py-8" style={{ color: colors.inkSubtle }}>No checker matches "{query}".</p>
            )}
          </div>
        </aside>

        {/* Main: run panel + results */}
        <section className="min-h-0 overflow-y-auto pr-0.5 space-y-4">
          {/* Run panel */}
          <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <h2 className="text-[14px] font-semibold" style={{ color: colors.ink }}>Run a check</h2>
              <div className="flex items-center gap-1.5 flex-wrap">
                {PRESETS.map((p) => {
                  const PIcon = p.icon;
                  return (
                    <button key={p.label} onClick={() => setContextText(JSON.stringify(p.json, null, 2))}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium transition-opacity hover:opacity-80"
                      style={{ background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
                      <PIcon className="w-3.5 h-3.5" /> {p.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Selected frameworks */}
            <div className="mt-3">
              <div className="text-[11px] font-medium uppercase tracking-wide mb-1.5" style={{ color: colors.inkSubtle }}>
                Selected frameworks ({selected.size})
              </div>
              {selected.size === 0 ? (
                <p className="text-[12px]" style={{ color: colors.inkTertiary }}>Pick one or more checkers from the catalog on the left.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {[...selected].map((tag) => {
                    const f = byTag.get(tag.toUpperCase());
                    return (
                      <span key={tag} className="inline-flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-md text-[12px] font-medium"
                        style={{ background: colors.primary + '1f', color: colors.primary }}>
                        {f?.title || tag}
                        <button onClick={() => toggle(tag)} className="hover:opacity-70" aria-label={`Remove ${tag}`}>
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Context editor */}
            <div className="mt-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-medium uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Context (JSON facts)</span>
                {!parsedContext.ok && <span className="text-[11px] font-medium" style={{ color: colors.error }}>{parsedContext.error}</span>}
              </div>
              <textarea
                value={contextText}
                onChange={(e) => setContextText(e.target.value)}
                spellCheck={false}
                rows={7}
                className="w-full rounded-lg p-3 text-[12.5px] font-mono outline-none resize-none"
                style={{
                  ...inputStyle,
                  borderColor: parsedContext.ok ? colors.hairline : colors.error,
                }}
              />
            </div>

            <div className="mt-3 flex items-center gap-3 flex-wrap">
              <button
                onClick={run}
                disabled={!canRun}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold transition-opacity"
                style={{
                  background: canRun ? colors.primary : colors.surface3,
                  color: canRun ? '#fff' : colors.inkTertiary,
                  cursor: canRun ? 'pointer' : 'not-allowed',
                }}
              >
                {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                {running ? 'Checking…' : 'Run compliance check'}
              </button>
              {runError && <span className="text-[12px]" style={{ color: colors.error }}>{runError}</span>}
            </div>
          </div>

          {/* Results */}
          {results === null ? (
            <div className="rounded-xl p-10 flex flex-col items-center justify-center gap-2 text-center"
              style={{ background: colors.surface1, border: `1px dashed ${colors.hairline}` }}>
              <Sparkles className="w-7 h-7" style={{ color: colors.inkTertiary }} />
              <p className="text-[13px] font-medium" style={{ color: colors.inkSubtle }}>No check has run yet.</p>
              <p className="text-[12px] max-w-sm" style={{ color: colors.inkTertiary }}>
                Select frameworks, give it a context, and run to see each verdict in plain English with its statute citation.
              </p>
            </div>
          ) : results.length === 0 ? (
            <p className="text-[13px] text-center py-8" style={{ color: colors.inkSubtle }}>No results returned.</p>
          ) : (
            <div className="space-y-3">
              {results.map((r, i) => {
                const cfg = STATUS[r.status] || STATUS.UNBACKED;
                const Icon = cfg.icon;
                const f = byTag.get(r.framework.toUpperCase());
                return (
                  <div key={r.framework + i} className="rounded-xl overflow-hidden cc-in"
                    style={{ background: colors.surface1, border: `1px solid ${cfg.color}44`, animationDelay: `${i * 60}ms` }}>
                    <div className="h-1" style={{ background: cfg.color }} />
                    <div className="p-4">
                      <div className="flex items-start gap-3">
                        <span className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                          style={{ background: cfg.color + '22', color: cfg.color }}>
                          <Icon className="w-5 h-5" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[15px] font-semibold" style={{ color: colors.ink }}>{f?.title || humanize(r.framework)}</span>
                            <span className="text-[11px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-md"
                              style={{ background: cfg.color + '22', color: cfg.color }}>{cfg.label}</span>
                          </div>
                          <p className="text-[12.5px] mt-1" style={{ color: colors.inkSubtle }}>{cfg.blurb}</p>
                        </div>
                      </div>

                      {r.findings.length > 0 && (
                        <div className="mt-3 space-y-1.5">
                          {r.findings.map((fd, k) => (
                            <div key={fd.code + k} className="flex items-start gap-2 rounded-lg px-3 py-2"
                              style={{ background: colors.surface2 }}>
                              <span className="mt-0.5 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded shrink-0"
                                style={{ background: (SEVERITY_COLOR[fd.severity] || colors.inkSubtle) + '22', color: SEVERITY_COLOR[fd.severity] || colors.inkSubtle }}>
                                {humanize(fd.severity)}
                              </span>
                              <span className="text-[12.5px]" style={{ color: colors.inkMuted }}>{fd.message}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {r.citations.length > 0 && (
                        <div className="mt-3 flex items-start gap-2">
                          <FileText className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: colors.inkTertiary }} />
                          <div className="text-[11.5px] leading-relaxed" style={{ color: colors.inkTertiary }}>
                            {r.citations.join(' · ')}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
