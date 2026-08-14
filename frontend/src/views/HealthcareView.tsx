import React, { useEffect, useState } from 'react';
import {
  Activity, Stethoscope, FileLock2, UserCheck, ClipboardList,
  Search, RefreshCw, Loader2, ShieldCheck, CheckCircle2, XCircle,
  AlertTriangle, HeartPulse, Ban,
} from 'lucide-react';
import { api } from '../api/client';
import type {
  HealthcareDashboard, HealthcareEncounter, PHIDisclosureRow, ConsentRow, ClinicalTaskRow,
} from '../api/endpoints/healthcare';
import { useTheme } from '../context/ThemeContext';
import { CountUp } from '../components/CountUp';
import Ring from '../components/shared/Ring';
import StatCard from '../components/shared/StatCard';
import { MiniDonut } from '../components/shared/MiniDonut';
import TableCard from '../components/shared/TableCard';
import LiveBadge from '../components/LiveBadge';
import { humanize } from '../lib/format';
import { formatDate } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { useLiveRefresh } from '../hooks/useLiveRefresh';

const ACCENT = '#14b8a6';

type Tab = 'overview' | 'encounters' | 'disclosures' | 'consent' | 'tasks';
const VALID: Tab[] = ['overview', 'encounters', 'disclosures', 'consent', 'tasks'];

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

const HealthcareView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>(
    defaultTab && VALID.includes(defaultTab as Tab) ? (defaultTab as Tab) : 'overview',
  );
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [revoking, setRevoking] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<number | null>(null);

  const [dash, setDash] = useState<HealthcareDashboard | null>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [encounters, setEncounters] = useState<HealthcareEncounter[]>([]);
  const [disclosures, setDisclosures] = useState<PHIDisclosureRow[]>([]);
  const [consent, setConsent] = useState<ConsentRow[]>([]);
  const [tasks, setTasks] = useState<ClinicalTaskRow[]>([]);

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
    ]);
    const val = (i: number, d: any) => (r[i].status === 'fulfilled' ? (r[i] as any).value ?? d : d);
    setDash(val(0, null));
    setAnalytics(val(1, null));
    setEncounters(val(2, []));
    setDisclosures(val(3, []));
    setConsent(val(4, []));
    setTasks(val(5, []));
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
      setActionMsg(`Could not revoke consent: ${e?.message || e}`);
    } finally { setRevoking(null); }
  }

  const statusColor = (s: string) => {
    const n = (s || '').toUpperCase();
    if (['CLOSED', 'CODED', 'DONE', 'ACTIVE'].includes(n)) return colors.success;
    if (['OPEN', 'TRIAGED', 'IN_PROGRESS', 'PENDING_HITL'].includes(n)) return colors.warning;
    if (['BLOCKED', 'CANCELLED'].includes(n)) return colors.error;
    if (['URGENT', 'EMERGENT'].includes(n)) return colors.error;
    return colors.inkSubtle;
  };
  const Badge = ({ status }: { status: string }) => (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status) + '18', color: statusColor(status) }}>
      {humanize(status) || 'N/A'}
    </span>
  );

  const EmptyState = ({ icon: Icon, title, sub }: { icon: React.ElementType; title: string; sub: string }) => (
    <div className="rounded-xl p-14 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Icon className="w-11 h-11 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
      <p className="text-[14px] font-medium" style={{ color: colors.inkSubtle }}>{title}</p>
      <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>{sub}</p>
    </div>
  );

  const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
    { key: 'overview', label: 'Overview', icon: Activity },
    { key: 'encounters', label: 'Encounters', icon: Stethoscope },
    { key: 'disclosures', label: 'PHI Disclosures', icon: FileLock2 },
    { key: 'consent', label: 'Consent', icon: UserCheck },
    { key: 'tasks', label: 'Clinical Tasks', icon: ClipboardList },
  ];
  const activeTab = TABS.find(t => t.key === tab)!;

  const moveTab = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next.key);
    document.getElementById(`hc-tab-${next.key}`)?.focus();
  };

  // Encounters-by-status donut from the real analytics aggregate.
  const encChart = (analytics?.charts || []).find((c: any) => c.key === 'enc_status');
  const encDonut = (encChart?.items || []).map((it: any) => ({ label: humanize(it.label), value: it.value }));

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
            <LiveBadge lastSync={lastSync} />
            <button onClick={loadData} aria-label="Refresh healthcare data"
              className="p-2 rounded-lg transition-colors" style={{ color: colors.inkSubtle }}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" role="tablist" aria-label="Healthcare sections"
          style={{ background: colors.surface1 }}>
          {TABS.map((t, i) => (
            <button key={t.key} id={`hc-tab-${t.key}`} role="tab" aria-selected={tab === t.key}
              tabIndex={tab === t.key ? 0 : -1} onClick={() => setTab(t.key)} onKeyDown={e => moveTab(e, i)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap"
              style={{
                background: tab === t.key ? colors.canvas : 'transparent',
                color: tab === t.key ? ACCENT : colors.inkSubtle,
                boxShadow: tab === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              }}>
              <t.icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          ))}
        </div>

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

        {/* Search (hidden on overview) */}
        {tab !== 'overview' && (
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
              </div>
            )}

            {/* ═══ ENCOUNTERS ═══ */}
            {tab === 'encounters' && (() => {
              const rows = encounters.filter(e => !searchQ
                || e.encounter_number.toLowerCase().includes(searchQ.toLowerCase())
                || e.patient_ref.toLowerCase().includes(searchQ.toLowerCase())
                || (e.reason || '').toLowerCase().includes(searchQ.toLowerCase()));
              return rows.length === 0
                ? <EmptyState icon={Stethoscope} title="No encounters" sub="Clinical encounters appear here once recorded." />
                : (
                  <TableCard minWidth={820}>
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                          {['Encounter', 'Patient', 'Type', 'Priority', 'Status', 'Reason', 'Diagnosis codes'].map(h => (
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
                    Every release below cleared the fail-closed HIPAA and 42 CFR Part 2 gate before it was recorded. A disclosure that
                    exceeds minimum-necessary scope, lacks authorization, or touches substance-use records without consent is refused and
                    never appears here.
                  </p>
                  {rows.length === 0
                    ? <EmptyState icon={FileLock2} title="No PHI disclosures" sub="Authorized releases appear here with their gate outcome." />
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
                ? <EmptyState icon={UserCheck} title="No consent records" sub="Patient consents appear here as they are captured." />
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
                ? <EmptyState icon={ClipboardList} title="No clinical tasks" sub="Coding and prior-authorization work items appear here." />
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
                            <td className="px-4 py-3 font-mono text-[11px]" style={{ color: colors.inkSubtle }}>
                              {t.encounter_id ? t.encounter_id.slice(0, 8) : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableCard>
                );
            })()}
          </>
        )}
      </div>
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
