import React, { useCallback, useEffect, useState } from 'react';
import type { RuleItem } from '../api/client';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainEmpty, BrainError } from '../components/BrainStates';
import {
  BookOpen, Search, ChevronDown, ChevronRight, Shield, Clock, CheckCircle,
  Plus, Upload, Download, Loader2, BadgeCheck, Copy, History, FlaskConical,
  XCircle, AlertTriangle,
} from 'lucide-react';

const DOMAINS = ['all', 'support', 'sales', 'engineering', 'finance', 'hr'];

/** What-if scenarios the backend understands, in plain English. */
const SCENARIOS: { key: string; label: string; hint: string }[] = [
  { key: 'decay_30d', label: 'Let it age 30 days', hint: 'Confidence after a month with no re-validation' },
  { key: 'decay_90d', label: 'Let it age 90 days', hint: 'Confidence after a quarter with no re-validation' },
  { key: 'boost_confidence', label: 'Department head validates it', hint: 'Confidence if a department head signs off today' },
  { key: 'remove_rule', label: 'Retire this rule', hint: 'Which skills lose their grounding if it goes away' },
];

/** A safe JSON.parse for the two structured fields on the create form. */
function parseJsonField(raw: string, label: string): Record<string, any> {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error(`${label} is not valid JSON.`);
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object, for example {"event": "invoice_received"}.`);
  }
  return parsed as Record<string, any>;
}

/** Turn any in-browser payload into a downloaded file (these exports return JSON, not a file body). */
function saveAs(content: string, filename: string, mime: string) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

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
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');

  // Toolbar / authoring state
  const [banner, setBanner] = useState<{ ok: boolean; text: string } | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    statement: '', domain: 'general', trigger: '{}', action: '{}',
    half_life_days: 180, compliance_tags: '',
  });
  const [createBusy, setCreateBusy] = useState(false);
  const [toolBusy, setToolBusy] = useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  // Per-rule inspector results, keyed by rule id.
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, any>>({});
  const [simResult, setSimResult] = useState<Record<string, any>>({});
  const [scenario, setScenario] = useState<Record<string, string>>({});

  // Sync localDomain with the incoming domain prop
  useEffect(() => {
    if (domain) {
      setLocalDomain(domain.toLowerCase() === 'all domains' ? 'all' : domain.toLowerCase());
    }
  }, [domain]);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const params = localDomain === 'all' ? {} : { domain: localDomain };
    api.getRules(params)
      .then((r) => { setRules(r.rules); setTotal(r.total); setLoading(false); })
      .catch((e: any) => { setError(e?.message || 'Failed to load rules'); setLoading(false); });
  }, [localDomain]);

  useEffect(() => { load(); }, [load]);

  // ── Toolbar actions ──────────────────────────────────────────────────────
  const createRule = async () => {
    setCreateBusy(true);
    setBanner(null);
    try {
      const body = {
        statement: form.statement.trim(),
        trigger_json: parseJsonField(form.trigger, 'The trigger'),
        action_json: parseJsonField(form.action, 'The action'),
        domain: form.domain.trim() || 'general',
        half_life_days: Number(form.half_life_days) || 180,
        compliance_tags: form.compliance_tags.split(',').map(t => t.trim()).filter(Boolean),
      };
      const r = await api.createRule(body);
      setBanner({ ok: true, text: `Rule created at ${r.confidence_tier?.replace(/_/g, ' ').toLowerCase()} confidence. It stays non-executable until a human validates it.` });
      setShowCreate(false);
      setForm({ statement: '', domain: 'general', trigger: '{}', action: '{}', half_life_days: 180, compliance_tags: '' });
      load();
    } catch (e: any) {
      setBanner({ ok: false, text: e?.message || 'Could not create the rule.' });
    } finally {
      setCreateBusy(false);
    }
  };

  const exportRules = async (format: 'json' | 'csv') => {
    setToolBusy(`export-${format}`);
    setBanner(null);
    try {
      const r = await api.exportRules(format);
      const stamp = new Date().toISOString().slice(0, 10);
      if (format === 'csv') {
        saveAs(r?.csv || '', `kaeos-rules-${stamp}.csv`, 'text/csv');
      } else {
        saveAs(JSON.stringify(r?.rules ?? r, null, 2), `kaeos-rules-${stamp}.json`, 'application/json');
      }
      setBanner({ ok: true, text: `Exported ${r?.count ?? 0} rules.` });
    } catch (e: any) {
      setBanner({ ok: false, text: e?.message || 'Export failed.' });
    } finally {
      setToolBusy(null);
    }
  };

  const importRules = async (file: File) => {
    setToolBusy('import');
    setBanner(null);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      // Accept both a bare array and the shape our own export produces.
      const list = Array.isArray(parsed) ? parsed : parsed?.rules;
      if (!Array.isArray(list)) throw new Error('That file does not contain a list of rules.');
      const r = await api.importRules(list);
      setBanner({ ok: true, text: `Imported ${r?.count ?? list.length} rules from ${file.name}.` });
      load();
    } catch (e: any) {
      setBanner({ ok: false, text: e?.message || 'Import failed.' });
    } finally {
      setToolBusy(null);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  // ── Per-rule actions ─────────────────────────────────────────────────────
  const runRowAction = async (key: string, fn: () => Promise<void>) => {
    setRowBusy(key);
    setBanner(null);
    try {
      await fn();
    } catch (e: any) {
      setBanner({ ok: false, text: e?.message || 'That action did not complete.' });
    } finally {
      setRowBusy(null);
    }
  };

  const validateRule = (id: string) => runRowAction(`${id}-validate`, async () => {
    const r = await api.validateRule(id);
    setBanner({ ok: true, text: `Validation recorded. Confidence is now ${r.confidence_scalar.toFixed(2)} (${r.confidence_tier?.replace(/_/g, ' ').toLowerCase()}).` });
    load();
  });

  const cloneRule = (id: string) => runRowAction(`${id}-clone`, async () => {
    const target = window.prompt('Clone this rule into which domain? Leave blank to keep the current one.');
    if (target === null) return;
    const r = await api.cloneRule(id, target.trim() || undefined);
    setBanner({ ok: true, text: `Copy created${target.trim() ? ` in ${target.trim()}` : ''}. It starts at 80% of the original confidence and is not executable until validated.` });
    if (r) load();
  });

  const loadVersions = (id: string) => runRowAction(`${id}-versions`, async () => {
    const r = await api.getRuleVersions(id);
    setVersions(prev => ({ ...prev, [id]: r }));
  });

  const runSimulation = (id: string) => runRowAction(`${id}-simulate`, async () => {
    const sc = scenario[id] || SCENARIOS[0].key;
    const r = await api.simulate(id, sc);
    setSimResult(prev => ({ ...prev, [id]: r }));
  });

  const filteredRules = rules.filter(r =>
    r.statement.toLowerCase().includes(searchTerm.toLowerCase()) ||
    r.domain.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) return <BrainLoading message="Loading the Knowledge Polystore…" />;
  if (error) return <BrainError message={error} onRetry={load} />;

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

        {/* Toolbar: author, move rules in and out of the polystore */}
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => { setShowCreate(v => !v); setBanner(null); }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white transition-all hover:brightness-110"
            style={{ background: colors.primary }}>
            <Plus className="w-3.5 h-3.5" /> {showCreate ? 'Close' : 'New Rule'}
          </button>
          <button onClick={() => fileRef.current?.click()} disabled={toolBusy === 'import'}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium disabled:opacity-50"
            style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
            {toolBusy === 'import' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />} Import
          </button>
          <input ref={fileRef} type="file" accept="application/json,.json" className="hidden"
            aria-label="Import rules from a JSON file"
            onChange={e => { const f = e.target.files?.[0]; if (f) importRules(f); }} />
          <button onClick={() => exportRules('json')} disabled={toolBusy === 'export-json'}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium disabled:opacity-50"
            style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
            {toolBusy === 'export-json' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Export JSON
          </button>
          <button onClick={() => exportRules('csv')} disabled={toolBusy === 'export-csv'}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium disabled:opacity-50"
            style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
            {toolBusy === 'export-csv' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Export CSV
          </button>
          <span className="text-[11px] ml-1" style={{ color: colors.inkTertiary }}>
            Expand any rule for validation, versions, cloning, and what-if.
          </span>
        </div>

        {/* Action feedback */}
        {banner && (
          <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg text-[12px] font-medium"
            style={{
              background: (banner.ok ? colors.success : colors.error) + '15',
              color: banner.ok ? colors.success : colors.error,
            }}>
            {banner.ok ? <CheckCircle className="w-4 h-4 shrink-0 mt-px" /> : <XCircle className="w-4 h-4 shrink-0 mt-px" />}
            <span className="flex-1">{banner.text}</span>
            <button onClick={() => setBanner(null)} className="text-[10px] opacity-70">dismiss</button>
          </div>
        )}

        {/* Create rule */}
        {showCreate && (
          <div className="p-5 space-y-3" style={card}>
            <h3 className="text-[14px] font-semibold" style={{ color: colors.ink }}>New Rule</h3>
            <p className="text-[11px]" style={{ color: colors.inkTertiary }}>
              New rules start speculative and stay non-executable until a human validates them.
            </p>
            <textarea value={form.statement} onChange={e => setForm({ ...form, statement: e.target.value })}
              placeholder="Plain-English statement, e.g. Invoices over $10,000 need a second approver."
              className="w-full h-16 px-3 py-2 rounded-lg text-[13px] outline-none resize-y"
              style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Domain</label>
                <input value={form.domain} onChange={e => setForm({ ...form, domain: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-[13px] outline-none"
                  style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
              </div>
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Half-life (days)</label>
                <input type="number" min={1} value={form.half_life_days}
                  onChange={e => setForm({ ...form, half_life_days: Number(e.target.value) })}
                  className="w-full px-3 py-2 rounded-lg text-[13px] outline-none"
                  style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
              </div>
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Compliance tags</label>
                <input value={form.compliance_tags} onChange={e => setForm({ ...form, compliance_tags: e.target.value })}
                  placeholder="SOX, GDPR"
                  className="w-full px-3 py-2 rounded-lg text-[13px] outline-none"
                  style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>When this happens (JSON)</label>
                <textarea value={form.trigger} onChange={e => setForm({ ...form, trigger: e.target.value })}
                  className="w-full h-20 px-3 py-2 rounded-lg text-[12px] font-mono outline-none resize-y"
                  style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
              </div>
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Do this (JSON)</label>
                <textarea value={form.action} onChange={e => setForm({ ...form, action: e.target.value })}
                  className="w-full h-20 px-3 py-2 rounded-lg text-[12px] font-mono outline-none resize-y"
                  style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowCreate(false)}
                className="px-4 py-2 rounded-lg text-[13px]"
                style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>Cancel</button>
              <button onClick={createRule} disabled={createBusy || !form.statement.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white disabled:opacity-50"
                style={{ background: colors.primary }}>
                {createBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Create Rule
              </button>
            </div>
          </div>
        )}

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

                              {/* Per-rule operations */}
                              <div className="mt-6 pt-5 flex flex-wrap items-center gap-2" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                                <button onClick={() => validateRule(r.id)} disabled={rowBusy === `${r.id}-validate`}
                                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold disabled:opacity-50"
                                  style={{ background: colors.success + '18', color: colors.success, border: `1px solid ${colors.success}30` }}>
                                  {rowBusy === `${r.id}-validate` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <BadgeCheck className="w-3.5 h-3.5" />}
                                  Validate
                                </button>
                                <button onClick={() => cloneRule(r.id)} disabled={rowBusy === `${r.id}-clone`}
                                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium disabled:opacity-50"
                                  style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
                                  {rowBusy === `${r.id}-clone` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Copy className="w-3.5 h-3.5" />}
                                  Clone to another domain
                                </button>
                                <button onClick={() => loadVersions(r.id)} disabled={rowBusy === `${r.id}-versions`}
                                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium disabled:opacity-50"
                                  style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
                                  {rowBusy === `${r.id}-versions` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <History className="w-3.5 h-3.5" />}
                                  History
                                </button>
                                <div className="flex items-center gap-1.5 ml-auto">
                                  <select value={scenario[r.id] || SCENARIOS[0].key}
                                    onChange={e => setScenario(prev => ({ ...prev, [r.id]: e.target.value }))}
                                    aria-label="What-if scenario"
                                    className="px-2.5 py-1.5 rounded-lg text-[12px] outline-none"
                                    style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                                    {SCENARIOS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
                                  </select>
                                  <button onClick={() => runSimulation(r.id)} disabled={rowBusy === `${r.id}-simulate`}
                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white disabled:opacity-50"
                                    style={{ background: colors.primary }}>
                                    {rowBusy === `${r.id}-simulate` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />}
                                    Run what-if
                                  </button>
                                </div>
                              </div>

                              {/* What-if outcome */}
                              {simResult[r.id] && (
                                <div className="mt-3 p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                                  <h4 className="text-[12px] font-semibold mb-2 flex items-center gap-1.5" style={{ color: colors.ink }}>
                                    <FlaskConical className="w-3.5 h-3.5" style={{ color: colors.primary }} />
                                    {SCENARIOS.find(s => s.key === simResult[r.id].scenario)?.label || 'What-if result'}
                                  </h4>
                                  {simResult[r.id].error ? (
                                    <p className="text-[12px] flex items-center gap-1.5" style={{ color: colors.warning }}>
                                      <AlertTriangle className="w-3.5 h-3.5" /> {simResult[r.id].error}
                                    </p>
                                  ) : (
                                    <div className="text-[12px] space-y-1" style={{ color: colors.inkMuted }}>
                                      <p>
                                        Today this rule sits at{' '}
                                        <strong style={{ color: colors.ink }}>{simResult[r.id].current_state?.confidence?.toFixed(2)}</strong>{' '}
                                        confidence and is{' '}
                                        <strong style={{ color: simResult[r.id].current_state?.is_executable ? colors.success : colors.warning }}>
                                          {simResult[r.id].current_state?.is_executable ? 'safe to run automatically' : 'held back from automatic execution'}
                                        </strong>.
                                      </p>
                                      {simResult[r.id].projected && (
                                        <p>
                                          Under this scenario it would move to{' '}
                                          <strong style={{ color: colors.ink }}>{simResult[r.id].projected.confidence?.toFixed(2)}</strong> and{' '}
                                          <strong style={{ color: simResult[r.id].projected.is_executable ? colors.success : colors.warning }}>
                                            {simResult[r.id].projected.is_executable ? 'stay eligible to run automatically' : 'stop being eligible to run automatically'}
                                          </strong>.
                                        </p>
                                      )}
                                      {simResult[r.id].impact && (
                                        <p style={{ color: colors.warning }}>
                                          {simResult[r.id].impact.affected_skills} skill{simResult[r.id].impact.affected_skills === 1 ? '' : 's'} would lose their grounding. {simResult[r.id].impact.warning}
                                        </p>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )}

                              {/* Provenance history */}
                              {versions[r.id] && (
                                <div className="mt-3 p-4 rounded-xl" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                                  <h4 className="text-[12px] font-semibold mb-2 flex items-center gap-1.5" style={{ color: colors.ink }}>
                                    <History className="w-3.5 h-3.5" style={{ color: colors.info }} />
                                    {versions[r.id].total_versions} recorded change{versions[r.id].total_versions === 1 ? '' : 's'}
                                  </h4>
                                  {versions[r.id].total_versions === 0 ? (
                                    <p className="text-[12px]" style={{ color: colors.inkSubtle }}>Nothing has changed this rule since it was created.</p>
                                  ) : (
                                    <div className="space-y-1.5">
                                      {(versions[r.id].versions || []).map((v: any) => (
                                        <div key={`${v.version}-${v.chain_hash}`} className="flex items-center gap-3 text-[12px]">
                                          <span className="font-mono w-8 shrink-0" style={{ color: colors.inkTertiary }}>v{v.version}</span>
                                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold shrink-0"
                                            style={{ background: colors.primary + '18', color: colors.primary }}>
                                            {v.event_type?.replace(/_/g, ' ').toLowerCase()}
                                          </span>
                                          <span className="truncate flex-1" style={{ color: colors.inkMuted }}>{v.reasoning || 'No note recorded'}</span>
                                          <span className="font-mono tabular-nums shrink-0" style={{ color: colors.inkSubtle }}>{v.confidence_at?.toFixed(2)}</span>
                                          <span className="shrink-0" style={{ color: colors.inkTertiary }}>
                                            {v.timestamp ? new Date(v.timestamp).toLocaleDateString() : ''}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              )}
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
