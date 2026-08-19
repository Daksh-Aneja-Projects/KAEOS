import React, { useEffect, useId, useState } from 'react';
import {
  Activity, Stethoscope, FileLock2, UserCheck, ClipboardList,
  Search, RefreshCw, Loader2, ShieldCheck, CheckCircle2, XCircle,
  AlertTriangle, HeartPulse, Ban, BarChart3, Plus, X, Sparkles, Hash, Send,
  FileCheck2,
} from 'lucide-react';
import { api } from '../api/client';
import type {
  HealthcareDashboard, HealthcareEncounter, PHIDisclosureRow, ConsentRow, ClinicalTaskRow,
  ComplianceReportRow,
} from '../api/endpoints/healthcare';
import { useTheme } from '../context/ThemeContext';
import { CountUp } from '../components/CountUp';
import Ring from '../components/shared/Ring';
import StatCard from '../components/shared/StatCard';
import TabBar from '../components/shared/TabBar';
import { useTabParam } from '../hooks/useTabParam';
import { MiniDonut } from '../components/shared/MiniDonut';
import TableCard from '../components/shared/TableCard';
import EmptyState from '../components/shared/EmptyState';
import LiveBadge from '../components/LiveBadge';
import DomainAnalytics from '../components/DomainAnalytics';
import { humanize } from '../lib/format';
import { formatDate } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { DEPARTMENT_COLORS } from '../lib/departments';
import { useLiveRefresh } from '../hooks/useLiveRefresh';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { announce } from '../components/a11y/LiveRegion';

const ACCENT = DEPARTMENT_COLORS.healthcare;

type Tab = 'overview' | 'encounters' | 'disclosures' | 'consent' | 'tasks' | 'analytics';
const VALID: Tab[] = ['overview', 'encounters', 'disclosures', 'consent', 'tasks', 'analytics'];

/** Plain-English translation for a disclosure purpose code. */
const PURPOSE_COPY: Record<string, string> = {
  payment: 'Payment and billing',
  treatment: 'Treatment and care coordination',
  operations: 'Health-care operations',
  healthcare_operations: 'Health-care operations',
  marketing: 'Marketing',
  research: 'Research',
};
const purposeLabel = (p: string) => PURPOSE_COPY[(p || '').toLowerCase()] || humanize(p);

/** Best-effort plain-English rendering of a backend error. The gated-pipeline
 * and workflow-transition errors carry a structured JSON detail (not a plain
 * string) - never show that raw JSON to a clinician. */
function friendlyError(raw: string): string {
  try {
    const d = JSON.parse(raw);
    if (!d || typeof d !== 'object') return raw;
    if (d.reason) return String(d.reason);
    if (d.error === 'invalid_transition') {
      return `This cannot move from ${humanize(d.from_state)} to ${humanize(d.to_state)} right now.`;
    }
    if (d.error === 'unknown_state') return `"${d.to_state}" is not a recognized status.`;
    if (d.error) return humanize(String(d.error));
    return raw;
  } catch {
    return raw;
  }
}

type QField = {
  key: string; label: string; type: 'text' | 'textarea' | 'select';
  options?: { value: string; label: string }[]; required?: boolean; placeholder?: string;
};

/** Lightweight, config-driven modal shared by every create/action form on this
 * page. Mirrors CreateEntityModal's look, but calls a caller-supplied submit
 * handler directly (the typed createHealthcare* wrappers / agent actions)
 * instead of the generic domain-entity endpoint, since disclosures need a
 * richer, gate-aware body than a flat field list can express. */
const QuickModal: React.FC<{
  open: boolean; title: string; submitLabel: string; icon: React.ElementType; fields: QField[];
  onClose: () => void; onSubmit: (values: Record<string, string>) => Promise<void>;
}> = ({ open, title, submitLabel, icon: Icon, fields, onClose, onSubmit }) => {
  const { colors } = useTheme();
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const titleId = useId();
  const trapRef = useFocusTrap<HTMLDivElement>(open, onClose);

  useEffect(() => { if (open) { setValues({}); setError(''); } }, [open]);

  if (!open) return null;

  const val = (f: QField) => values[f.key] ?? '';
  const set = (k: string, v: string) => setValues(p => ({ ...p, [k]: v }));

  const submit = async () => {
    for (const f of fields) {
      if (f.required && !val(f).trim()) {
        const msg = `${f.label} is required`;
        setError(msg);
        announce(msg, 'assertive');
        return;
      }
    }
    setBusy(true); setError('');
    try {
      await onSubmit(values);
    } catch (e: any) {
      const msg = friendlyError(e?.message || 'Action failed');
      setError(msg);
      announce(msg, 'assertive');
    } finally {
      setBusy(false);
    }
  };

  const inputStyle = { background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink } as React.CSSProperties;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.55)' }}
      onClick={onClose}>
      <div ref={trapRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className="w-full max-w-md rounded-2xl p-5 space-y-4 max-h-[85vh] overflow-y-auto"
        style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 id={titleId} className="text-[15px] font-bold flex items-center gap-2" style={{ color: colors.ink }}>
            <Icon className="w-4 h-4" style={{ color: ACCENT }} />{title}
          </h2>
          <button onClick={onClose} aria-label="Close dialog" className="p-1 rounded" style={{ color: colors.inkSubtle }}>
            <X className="w-4 h-4" />
          </button>
        </div>

        {fields.map(f => {
          const fieldId = `${titleId}-${f.key}`;
          return (
            <div key={f.key}>
              <label htmlFor={fieldId} className="text-[11px] font-semibold block mb-1" style={{ color: colors.inkSubtle }}>
                {f.label}{f.required && <span style={{ color: colors.error }}> *</span>}
              </label>
              {f.type === 'textarea' ? (
                <textarea id={fieldId} value={val(f)} onChange={e => set(f.key, e.target.value)} rows={3}
                  placeholder={f.placeholder}
                  className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none resize-none" style={inputStyle} />
              ) : f.type === 'select' ? (
                <select id={fieldId} value={val(f)} onChange={e => set(f.key, e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle}>
                  <option value="">Select…</option>
                  {(f.options || []).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : (
                <input id={fieldId} type="text" value={val(f)} onChange={e => set(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle} />
              )}
            </div>
          );
        })}

        {error && <p role="alert" className="text-[11px] font-medium" style={{ color: colors.error }}>{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-2 rounded-lg text-[12px] font-semibold"
            style={{ background: 'transparent', color: colors.inkSubtle }}>Cancel</button>
          <button onClick={submit} disabled={busy}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold disabled:opacity-50 text-white"
            style={{ background: ACCENT }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Icon className="w-3.5 h-3.5" />}
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

const ENCOUNTER_TYPES = ['office_visit', 'telehealth', 'inpatient', 'emergency',
  'outpatient_surgery', 'behavioral_health', 'imaging'].map(v => ({ value: v, label: humanize(v) }));
const DISCLOSURE_PURPOSES = ['payment', 'treatment', 'operations', 'marketing', 'research']
  .map(v => ({ value: v, label: purposeLabel(v) }));
const TASK_TYPES = ['coding', 'prior_auth', 'referral', 'follow_up'].map(v => ({ value: v, label: humanize(v) }));
const YES_NO = [{ value: 'no', label: 'No' }, { value: 'yes', label: 'Yes' }];

type CreateKind = 'encounter' | 'disclosure' | 'consent' | 'task';
const CREATE_LABEL: Partial<Record<Tab, { kind: CreateKind; label: string }>> = {
  encounters: { kind: 'encounter', label: 'New Encounter' },
  disclosures: { kind: 'disclosure', label: 'New Disclosure' },
  consent: { kind: 'consent', label: 'New Consent' },
  tasks: { kind: 'task', label: 'New Task' },
};

const statusColor = (s: string, colors: ReturnType<typeof useTheme>['colors']) => {
  const n = (s || '').toUpperCase();
  if (['CLOSED', 'CODED', 'DONE', 'ACTIVE'].includes(n)) return colors.success;
  if (['OPEN', 'TRIAGED', 'IN_PROGRESS', 'PENDING_HITL'].includes(n)) return colors.warning;
  if (['BLOCKED', 'CANCELLED'].includes(n)) return colors.error;
  if (['URGENT', 'EMERGENT'].includes(n)) return colors.error;
  return colors.inkSubtle;
};

// Module scope on purpose: declared inside the render body this was a fresh
// component type every render, so React remounted every badge on each keystroke.
const Badge = ({ status }: { status: string }) => {
  const { colors } = useTheme();
  return (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status, colors) + '18', color: statusColor(status, colors) }}>
      {humanize(status) || 'N/A'}
    </span>
  );
};

const HealthcareView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useTabParam<Tab>(VALID, 'overview', defaultTab);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [revoking, setRevoking] = useState<string | null>(null);
  const [triagingId, setTriagingId] = useState<string | null>(null);
  const [codingId, setCodingId] = useState<string | null>(null);
  const [priorAuthEncounter, setPriorAuthEncounter] = useState<string | null>(null);
  const [createKind, setCreateKind] = useState<CreateKind | null>(null);
  const [lastSync, setLastSync] = useState<number | null>(null);

  const [dash, setDash] = useState<HealthcareDashboard | null>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [encounters, setEncounters] = useState<HealthcareEncounter[]>([]);
  const [disclosures, setDisclosures] = useState<PHIDisclosureRow[]>([]);
  const [consent, setConsent] = useState<ConsentRow[]>([]);
  const [tasks, setTasks] = useState<ClinicalTaskRow[]>([]);
  const [complianceReports, setComplianceReports] = useState<ComplianceReportRow[]>([]);

  useEffect(() => { loadData(); }, []);
  // Live: refresh on any tenant event and keep the cockpit ticking even when the
  // socket is quiet.
  useLiveRefresh(loadData, { intervalMs: 20000 });

  async function loadData() {
    setLoading(true);
    const r = await Promise.allSettled([
      api.getHealthcareDashboard(),
      api.getHealthcareAnalytics(),
      api.getHealthcareEncounters(),
      api.getHealthcareDisclosures(),
      api.getHealthcareConsent(),
      api.getHealthcareTasks(),
      api.getHealthcareComplianceReports(),
    ]);
    const val = (i: number, d: any) => (r[i].status === 'fulfilled' ? (r[i] as any).value ?? d : d);
    setDash(val(0, null));
    setAnalytics(val(1, null));
    setEncounters(val(2, []));
    setDisclosures(val(3, []));
    setConsent(val(4, []));
    setTasks(val(5, []));
    setComplianceReports(val(6, []));
    setLastSync(Date.now());
    setLoading(false);
  }

  async function revoke(id: string) {
    setRevoking(id); setActionMsg('');
    try {
      await api.revokeHealthcareConsent(id);
      setActionMsg('Consent revoked. Future disclosures under this consent will be refused.');
      await loadData();
    } catch (e: any) {
      setActionMsg(`Could not revoke consent: ${friendlyError(e?.message || String(e))}`);
    } finally { setRevoking(null); }
  }

  async function handleTriage(encounterId: string) {
    setTriagingId(encounterId); setActionMsg('');
    try {
      const res = await api.triageEncounter(encounterId);
      announce('Encounter triaged');
      setActionMsg(`Triage complete: ${humanize(res.priority || '')} priority, routed to `
        + `${humanize(res.status)} for governance review.`);
      await loadData();
    } catch (e: any) {
      setActionMsg(`Could not triage encounter: ${friendlyError(e?.message || String(e))}`);
    } finally { setTriagingId(null); }
  }

  async function handleSuggestCodes(encounterId: string) {
    setCodingId(encounterId); setActionMsg('');
    try {
      const res = await api.suggestEncounterCodes(encounterId);
      announce('Coding suggestion requested');
      setActionMsg(res.suggested_codes && res.suggested_codes.length
        ? `Coding suggestion ready for human review: ${res.suggested_codes.join(', ')}.`
        : `Coding suggestion routed to a human coder for review (${humanize(res.status)}).`);
      await loadData();
    } catch (e: any) {
      setActionMsg(`Could not suggest codes: ${friendlyError(e?.message || String(e))}`);
    } finally { setCodingId(null); }
  }

  async function handlePriorAuth(values: Record<string, string>) {
    if (!priorAuthEncounter) return;
    const res = await api.requestPriorAuth(priorAuthEncounter, {
      procedure: values.procedure, payer: values.payer || undefined,
    });
    setPriorAuthEncounter(null);
    announce('Prior authorization requested');
    setActionMsg(`Prior-authorization request drafted for a human reviewer (${humanize(res.status)}).`);
    await loadData();
  }

  async function handleCreate(values: Record<string, string>) {
    if (createKind === 'encounter') {
      await api.createHealthcareEncounter({
        patient_ref: values.patient_ref, encounter_type: values.encounter_type,
        reason: values.reason || undefined,
      });
      setActionMsg('Encounter created.');
    } else if (createKind === 'consent') {
      await api.createHealthcareConsent({
        patient_ref: values.patient_ref, scope: values.scope, part2: values.part2 === 'yes',
      });
      setActionMsg('Consent recorded.');
    } else if (createKind === 'task') {
      await api.createHealthcareTask({
        task_type: values.task_type, encounter_id: values.encounter_id || undefined,
        assignee: values.assignee || undefined,
      });
      setActionMsg('Clinical task created.');
    } else if (createKind === 'disclosure') {
      const splitList = (s: string) => s.split(',').map(x => x.trim()).filter(Boolean);
      await api.createHealthcareDisclosure({
        purpose: values.purpose, recipient: values.recipient,
        fields: splitList(values.fields || ''),
        minimum_necessary_justification: values.minimum_necessary_justification,
        encounter_id: values.encounter_id || undefined,
        diagnosis_codes: splitList(values.diagnosis_codes || ''),
        part2_records: values.part2_records === 'yes',
        authorization: values.authorization_signed === 'yes' ? { signed: true } : undefined,
        part2_consent: values.part2_consent_signed === 'yes' ? { signed: true } : undefined,
      });
      setActionMsg('PHI disclosure recorded, it cleared the HIPAA and 42 CFR Part 2 gate.');
    }
    setCreateKind(null);
    announce('Created');
    await loadData();
  }

  const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
    { key: 'overview', label: 'Overview', icon: Activity },
    { key: 'encounters', label: 'Encounters', icon: Stethoscope },
    { key: 'disclosures', label: 'PHI Disclosures', icon: FileLock2 },
    { key: 'consent', label: 'Consent', icon: UserCheck },
    { key: 'tasks', label: 'Clinical Tasks', icon: ClipboardList },
    { key: 'analytics', label: 'Analytics', icon: BarChart3 },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;
  const createSpec = CREATE_LABEL[tab];

  // Encounters-by-status donut from the real analytics aggregate.
  const encChart = (analytics?.charts || []).find((c: any) => c.key === 'enc_status');
  const encDonut = (encChart?.items || []).map((it: any) => ({ label: humanize(it.label), value: it.value }));
  const encounterOptions = encounters.map(e => ({
    value: e.id, label: `${e.encounter_number} · ${e.patient_ref}`,
  }));
  const latestReport = complianceReports[0];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-5`}>
        {/* Header */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight flex items-center gap-2">
              <activeTab.icon className="w-6 h-6" style={{ color: ACCENT }} />
              {activeTab.label}
            </h1>
            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
              Healthcare Department · clinical operations under the PHI-disclosure gate
            </p>
          </div>
          <div className="flex items-center gap-3">
            {createSpec && (
              <button onClick={() => setCreateKind(createSpec.kind)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white"
                style={{ background: ACCENT }}>
                <Plus className="w-3.5 h-3.5" /> {createSpec.label}
              </button>
            )}
            <LiveBadge lastSync={lastSync} />
            <button onClick={loadData} aria-label="Refresh healthcare data"
              className="p-2 rounded-lg transition-colors" style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <TabBar tabs={TABS} value={tab} onChange={setTab}
          idPrefix="hc" ariaLabel="Healthcare sections" accent={ACCENT} />

        {/* Action feedback */}
        {actionMsg && (
          <div className="px-4 py-2.5 rounded-lg text-[12px] font-medium flex items-center gap-2"
            style={{ background: actionMsg.startsWith('Could not') ? colors.error + '15' : colors.success + '15',
                     color: actionMsg.startsWith('Could not') ? colors.error : colors.success }}>
            {actionMsg.startsWith('Could not') ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
            {actionMsg}
            <button onClick={() => setActionMsg('')} className="ml-auto text-[11px] opacity-60 hover:opacity-100">dismiss</button>
          </div>
        )}

        {/* Search (hidden on overview/analytics) */}
        {tab !== 'overview' && tab !== 'analytics' && (
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
            <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
              placeholder={`Search ${activeTab.label.toLowerCase()}...`}
              className="w-full pl-9 pr-4 py-2 rounded-lg border text-[12px] focus:outline-none focus:ring-1"
              style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
          </div>
        )}

        {loading && !dash ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 animate-spin" style={{ color: ACCENT }} />
          </div>
        ) : (
          <>
            {/* ═══ OVERVIEW ═══ */}
            {tab === 'overview' && (
              <div className="space-y-5">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  {/* Live encounter-load ring */}
                  <div className="rounded-xl p-5 flex items-center gap-5"
                    style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <Ring value={dash?.open_encounters || 0} max={Math.max(1, dash?.total_encounters || 0)}
                      size={104} color={ACCENT} label="open" />
                    <div className="min-w-0">
                      <p className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>
                        Active clinical load
                      </p>
                      <p className="text-[13px] mt-1" style={{ color: colors.ink }}>
                        <CountUp value={dash?.open_encounters || 0} className="font-bold" /> of{' '}
                        <CountUp value={dash?.total_encounters || 0} className="font-bold" /> encounters are still open or in triage.
                      </p>
                      <p className="text-[12px] mt-1.5" style={{ color: colors.inkSubtle }}>
                        <CountUp value={dash?.open_clinical_tasks || 0} className="font-semibold" /> coding and prior-auth tasks are queued.
                      </p>
                    </div>
                  </div>
                  {/* Encounters by status */}
                  <div className="rounded-xl p-5 flex flex-col" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <p className="text-[12px] font-semibold uppercase tracking-wide mb-3" style={{ color: colors.inkSubtle }}>
                      Encounters by status
                    </p>
                    {encDonut.length > 0
                      ? <MiniDonut items={encDonut} size={92} centerLabel="visits" />
                      : <p className="text-[12px] my-auto" style={{ color: colors.inkTertiary }}>No encounters recorded yet.</p>}
                  </div>
                  {/* Governance narrative */}
                  <div className="rounded-xl p-5" style={{ background: ACCENT + '10', border: `1px solid ${ACCENT}33` }}>
                    <div className="flex items-center gap-2 mb-2">
                      <ShieldCheck className="w-4 h-4" style={{ color: ACCENT }} />
                      <p className="text-[12px] font-semibold" style={{ color: ACCENT }}>PHI-disclosure gate</p>
                    </div>
                    <p className="text-[12.5px] leading-relaxed" style={{ color: colors.ink }}>
                      <CountUp value={dash?.phi_disclosures || 0} className="font-bold" /> disclosures cleared the HIPAA minimum-necessary and
                      authorization checks before any PHI left the building.{' '}
                      <CountUp value={dash?.active_consents || 0} className="font-bold" /> patient consents are active. A release that fails a
                      statutory check is refused, never recorded.
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
                  <StatCard label="Total Encounters" value={dash?.total_encounters || 0} icon={<Stethoscope className="w-4 h-4" />} accent={ACCENT} />
                  <StatCard label="Open Encounters" value={dash?.open_encounters || 0} icon={<HeartPulse className="w-4 h-4" />} accent="#f59e0b" />
                  <StatCard label="PHI Disclosures" value={dash?.phi_disclosures || 0} icon={<FileLock2 className="w-4 h-4" />} accent="#6366f1" />
                  <StatCard label="Active Consents" value={dash?.active_consents || 0} icon={<UserCheck className="w-4 h-4" />} accent={colors.success} />
                  <StatCard label="Open Clinical Tasks" value={dash?.open_clinical_tasks || 0} icon={<ClipboardList className="w-4 h-4" />} accent="#ec4899" />
                </div>

                {/* Insights from the analytics service */}
                {(analytics?.insights || []).length > 0 && (
                  <div className="space-y-2">
                    {analytics.insights.map((ins: any, i: number) => {
                      const c = ins.severity === 'critical' ? colors.error : ins.severity === 'warning' ? colors.warning : ACCENT;
                      return (
                        <div key={i} className="flex items-center gap-2.5 px-4 py-2.5 rounded-lg text-[12px]" style={{ background: c + '12' }}>
                          <AlertTriangle className="w-4 h-4 shrink-0" style={{ color: c }} />
                          <span style={{ color: colors.ink }}>{ins.message}</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Compliance report */}
                <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex items-center gap-2 mb-3">
                    <FileCheck2 className="w-4 h-4" style={{ color: ACCENT }} />
                    <p className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>
                      Compliance reporting
                    </p>
                  </div>
                  {latestReport ? (
                    <div>
                      <div className="flex items-center justify-between flex-wrap gap-2">
                        <p className="text-[13.5px] font-semibold" style={{ color: colors.ink }}>
                          {latestReport.report_name} · {latestReport.period_year}
                        </p>
                        <Badge status={latestReport.status} />
                      </div>
                      <p className="text-[12px] mt-2 leading-relaxed" style={{ color: colors.inkSubtle }}>
                        {latestReport.data?.summary || 'No summary available for this report.'}
                      </p>
                      <p className="text-[11px] mt-2" style={{ color: colors.inkTertiary }}>
                        Generated {formatDate(latestReport.generated_at) || 'recently'} · {humanize(latestReport.framework)} framework
                      </p>
                    </div>
                  ) : (
                    <p className="text-[12px]" style={{ color: colors.inkTertiary }}>No compliance reports generated yet.</p>
                  )}
                </div>
              </div>
            )}

            {/* ═══ ENCOUNTERS ═══ */}
            {tab === 'encounters' && (() => {
              const rows = encounters.filter(e => !searchQ
                || e.encounter_number.toLowerCase().includes(searchQ.toLowerCase())
                || e.patient_ref.toLowerCase().includes(searchQ.toLowerCase())
                || (e.reason || '').toLowerCase().includes(searchQ.toLowerCase()));
              return rows.length === 0
                ? <EmptyState compact icon={Stethoscope} title="No encounters" sub="Clinical encounters appear here once recorded." />
                : (
                  <TableCard minWidth={980}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Encounter', 'Patient', 'Type', 'Priority', 'Status', 'Reason', 'Diagnosis codes', 'Actions'].map(h => (
                            <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(e => (
                          <tr key={e.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            <td className="px-4 py-3 font-medium font-mono">{e.encounter_number}</td>
                            <td className="px-4 py-3">{e.patient_ref}</td>
                            <td className="px-4 py-3">{humanize(e.type)}</td>
                            <td className="px-4 py-3">{e.priority ? <Badge status={e.priority} /> : <span style={{ color: colors.inkTertiary }}>-</span>}</td>
                            <td className="px-4 py-3"><Badge status={e.status} /></td>
                            <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{e.reason || '-'}</td>
                            <td className="px-4 py-3">
                              {e.diagnosis_codes.length
                                ? <span className="font-mono text-[11px]">{e.diagnosis_codes.join(', ')}</span>
                                : <span style={{ color: colors.inkTertiary }}>none coded</span>}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-1.5">
                                <button onClick={() => handleTriage(e.id)} disabled={e.status !== 'OPEN' || triagingId === e.id}
                                  title="Triage this encounter (Intake Agent)"
                                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold transition-colors disabled:opacity-40"
                                  style={{ background: '#6366f115', color: '#6366f1' }}>
                                  {triagingId === e.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                                  Triage
                                </button>
                                <button onClick={() => handleSuggestCodes(e.id)} disabled={codingId === e.id}
                                  title="Suggest ICD-10 codes (Coding Agent)"
                                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold transition-colors disabled:opacity-40"
                                  style={{ background: ACCENT + '15', color: ACCENT }}>
                                  {codingId === e.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Hash className="w-3 h-3" />}
                                  Codes
                                </button>
                                <button onClick={() => setPriorAuthEncounter(e.id)}
                                  title="Request prior authorization (Prior-Auth Agent)"
                                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold transition-colors"
                                  style={{ background: '#f59e0b15', color: '#f59e0b' }}>
                                  <Send className="w-3 h-3" />
                                  Prior auth
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableCard>
                );
            })()}

            {/* ═══ PHI DISCLOSURES (the governance story) ═══ */}
            {tab === 'disclosures' && (() => {
              const rows = disclosures.filter(d => !searchQ
                || d.recipient.toLowerCase().includes(searchQ.toLowerCase())
                || purposeLabel(d.purpose).toLowerCase().includes(searchQ.toLowerCase()));
              return (
                <div className="space-y-3">
                  <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
                    Every release below cleared the fail-closed HIPAA and 42 CFR Part 2 gate, routed through the PHI Governance Agent's full
                    7-gate pipeline, before it was recorded. A disclosure that exceeds minimum-necessary scope, lacks authorization, or
                    touches substance-use records without consent is refused and never appears here.
                  </p>
                  {rows.length === 0
                    ? <EmptyState compact icon={FileLock2} title="No PHI disclosures" sub="Authorized releases appear here with their gate outcome." />
                    : rows.map(d => (
                      <div key={d.id} className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                        <div className="flex items-start justify-between gap-3 flex-wrap">
                          <div className="min-w-0">
                            <p className="text-[13.5px] font-semibold" style={{ color: colors.ink }}>
                              Authorized release to {d.recipient}
                            </p>
                            <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
                              Purpose: {purposeLabel(d.purpose)} · {d.fields.length} data field{d.fields.length === 1 ? '' : 's'} disclosed
                              {d.fields.length ? ` (${d.fields.map(f => humanize(f)).join(', ')})` : ''}
                            </p>
                          </div>
                          <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0"
                            style={{ background: colors.success + '18', color: colors.success }}>
                            <ShieldCheck className="w-3 h-3" /> Cleared the gate
                          </span>
                        </div>
                        {/* The three statutory checks, in plain English */}
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3">
                          <GateChip title="Minimum necessary" passed sub={`Scope justified: "${d.justification}"`} colors={colors} />
                          <GateChip title="Patient authorization" passed={d.authorized}
                            sub={d.authorized ? 'A valid authorization was on file.' : 'Authorization could not be verified.'} colors={colors} />
                          <GateChip title="42 CFR Part 2" passed neutral={!d.part2}
                            sub={d.part2 ? 'Substance-use records: consent verified.' : 'No substance-use records involved.'} colors={colors} />
                        </div>
                      </div>
                    ))}
                </div>
              );
            })()}

            {/* ═══ CONSENT ═══ */}
            {tab === 'consent' && (() => {
              const rows = consent.filter(c => !searchQ
                || c.patient_ref.toLowerCase().includes(searchQ.toLowerCase())
                || c.scope.toLowerCase().includes(searchQ.toLowerCase()));
              return rows.length === 0
                ? <EmptyState compact icon={UserCheck} title="No consent records" sub="Patient consents appear here as they are captured." />
                : (
                  <TableCard minWidth={760}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Patient', 'Scope', 'Part 2', 'Status', 'Granted', 'Revoked', ''].map(h => (
                            <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(c => (
                          <tr key={c.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            <td className="px-4 py-3 font-medium">{c.patient_ref}</td>
                            <td className="px-4 py-3">{humanize(c.scope)}</td>
                            <td className="px-4 py-3">
                              {c.part2
                                ? <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: '#6366f118', color: '#6366f1' }}>Substance-use</span>
                                : <span style={{ color: colors.inkTertiary }}>General</span>}
                            </td>
                            <td className="px-4 py-3"><Badge status={c.active ? 'ACTIVE' : 'REVOKED'} /></td>
                            <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{formatDate(c.granted_at) || '-'}</td>
                            <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>{formatDate(c.revoked_at) || '-'}</td>
                            <td className="px-4 py-3">
                              {c.active && (
                                <button onClick={() => revoke(c.id)} disabled={revoking === c.id}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors"
                                  style={{ background: colors.error + '15', color: colors.error }}>
                                  {revoking === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Ban className="w-3 h-3" />}
                                  Revoke
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableCard>
                );
            })()}

            {/* ═══ CLINICAL TASKS ═══ */}
            {tab === 'tasks' && (() => {
              const rows = tasks.filter(t => !searchQ
                || humanize(t.type).toLowerCase().includes(searchQ.toLowerCase())
                || (t.assignee || '').toLowerCase().includes(searchQ.toLowerCase()));
              return rows.length === 0
                ? <EmptyState compact icon={ClipboardList} title="No clinical tasks" sub="Coding and prior-authorization work items appear here." />
                : (
                  <TableCard minWidth={640}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Task', 'Status', 'Assignee', 'Linked encounter'].map(h => (
                            <th key={h} className="text-left px-4 py-3 font-semibold" style={{ color: colors.inkSubtle }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(t => (
                          <tr key={t.id} style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                            <td className="px-4 py-3 font-medium">{humanize(t.type)}</td>
                            <td className="px-4 py-3"><Badge status={t.status} /></td>
                            <td className="px-4 py-3">{t.assignee || <span style={{ color: colors.inkTertiary }}>Unassigned</span>}</td>
                            <td className="px-4 py-3" style={{ color: colors.inkSubtle }}>
                              {t.encounter_id
                                ? (encounters.find(e => e.id === t.encounter_id)?.encounter_number || 'Linked encounter')
                                : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableCard>
                );
            })()}

            {/* ═══ ANALYTICS ═══ */}
            {tab === 'analytics' && <DomainAnalytics domain="healthcare" />}
          </>
        )}
      </div>

      {/* Create modals - one shared shell, four typed submit handlers */}
      <QuickModal open={createKind === 'encounter'} title="New Encounter" submitLabel="Create" icon={Stethoscope}
        onClose={() => setCreateKind(null)} onSubmit={handleCreate}
        fields={[
          { key: 'patient_ref', label: 'Patient reference', type: 'text', required: true, placeholder: 'pt-anon-0000' },
          { key: 'encounter_type', label: 'Encounter type', type: 'select', required: true, options: ENCOUNTER_TYPES },
          { key: 'reason', label: 'Reason (chief complaint)', type: 'textarea', placeholder: 'e.g. annual wellness visit' },
        ]} />

      <QuickModal open={createKind === 'consent'} title="New Consent" submitLabel="Record" icon={UserCheck}
        onClose={() => setCreateKind(null)} onSubmit={handleCreate}
        fields={[
          { key: 'patient_ref', label: 'Patient reference', type: 'text', required: true, placeholder: 'pt-anon-0000' },
          { key: 'scope', label: 'Consent scope', type: 'text', required: true, placeholder: 'e.g. treatment_payment_operations' },
          { key: 'part2', label: '42 CFR Part 2 (substance-use) consent', type: 'select', options: YES_NO },
        ]} />

      <QuickModal open={createKind === 'task'} title="New Clinical Task" submitLabel="Create" icon={ClipboardList}
        onClose={() => setCreateKind(null)} onSubmit={handleCreate}
        fields={[
          { key: 'task_type', label: 'Task type', type: 'select', required: true, options: TASK_TYPES },
          { key: 'encounter_id', label: 'Linked encounter', type: 'select', options: encounterOptions },
          { key: 'assignee', label: 'Assignee', type: 'text', placeholder: 'e.g. coding_agent' },
        ]} />

      <QuickModal open={createKind === 'disclosure'} title="New PHI Disclosure" submitLabel="Submit for review" icon={FileLock2}
        onClose={() => setCreateKind(null)} onSubmit={handleCreate}
        fields={[
          { key: 'purpose', label: 'Purpose', type: 'select', required: true, options: DISCLOSURE_PURPOSES },
          { key: 'recipient', label: 'Recipient', type: 'text', required: true, placeholder: 'e.g. Dr. Alvarez, Cardiology' },
          { key: 'fields', label: 'Fields disclosed (comma-separated)', type: 'text', required: true, placeholder: 'name, dob, diagnosis_codes' },
          { key: 'minimum_necessary_justification', label: 'Minimum-necessary justification', type: 'textarea', required: true },
          { key: 'encounter_id', label: 'Linked encounter', type: 'select', options: encounterOptions },
          { key: 'diagnosis_codes', label: 'Diagnosis codes (comma-separated)', type: 'text', placeholder: 'F41.1, I10' },
          { key: 'authorization_signed', label: 'Signed patient authorization on file', type: 'select', options: YES_NO },
          { key: 'part2_records', label: 'Touches 42 CFR Part 2 substance-use records', type: 'select', options: YES_NO },
          { key: 'part2_consent_signed', label: 'Signed Part 2 consent on file', type: 'select', options: YES_NO },
        ]} />

      <QuickModal open={!!priorAuthEncounter} title="Request Prior Authorization" submitLabel="Draft request" icon={Send}
        onClose={() => setPriorAuthEncounter(null)}
        onSubmit={handlePriorAuth}
        fields={[
          { key: 'procedure', label: 'Procedure', type: 'text', required: true, placeholder: 'e.g. MRI lumbar spine' },
          { key: 'payer', label: 'Payer', type: 'text', placeholder: 'e.g. Aetna' },
        ]} />
    </div>
  );
};

/** A single plain-English statutory-check chip. */
function GateChip({ title, sub, passed, neutral, colors }: {
  title: string; sub: string; passed: boolean; neutral?: boolean; colors: Record<string, string>;
}) {
  const c = neutral ? colors.inkSubtle : passed ? colors.success : colors.error;
  return (
    <div className="rounded-lg p-2.5" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center gap-1.5">
        {neutral ? <ShieldCheck className="w-3.5 h-3.5" style={{ color: c }} />
          : passed ? <CheckCircle2 className="w-3.5 h-3.5" style={{ color: c }} />
            : <XCircle className="w-3.5 h-3.5" style={{ color: c }} />}
        <span className="text-[11.5px] font-semibold" style={{ color: colors.ink }}>{title}</span>
      </div>
      <p className="text-[11px] mt-1 leading-snug" style={{ color: colors.inkSubtle }}>{sub}</p>
    </div>
  );
}

export default HealthcareView;
