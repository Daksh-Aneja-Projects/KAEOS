import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { NotificationChannel, NotificationDelivery, NotificationKind } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { toPct, humanize } from '../lib/format';
import { Bell, Mail, MessageSquare, Webhook, Plus, Trash2, Loader2, Send, History, Newspaper, Eye, CheckCircle2, XCircle } from 'lucide-react';

/**
 * Notification settings: SMTP / Slack / webhook channels with per-event
 * subscriptions plus the recent delivery log. Backs the real
 * /notifications/* endpoints - no mock data.
 */

const KIND_META: Record<NotificationKind, { label: string; color: string; Icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }> }> = {
  smtp: { label: 'SMTP', color: '#f59e0b', Icon: Mail },
  slack: { label: 'Slack', color: '#8b5cf6', Icon: MessageSquare },
  webhook: { label: 'Webhook', color: '#06b6d4', Icon: Webhook },
};

const EMPTY_CONFIG: Record<NotificationKind, Record<string, any>> = {
  smtp: { host: '', port: 587, username: '', password: '', use_tls: true, from_addr: '', to_addrs: '' },
  slack: { webhook_url: '' },
  webhook: { url: '', secret: '' },
};

const fmtTime = (s: string) => {
  if (!s) return '';
  const d = new Date(s.includes('T') ? s : s.replace(' ', 'T'));
  return isNaN(d.getTime()) ? s : d.toLocaleString();
};

const NotificationSettings: React.FC = () => {
  const { colors } = useTheme();

  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [events, setEvents] = useState<string[]>([]);
  const [kinds, setKinds] = useState<NotificationKind[]>(['smtp', 'slack', 'webhook']);
  const [deliveries, setDeliveries] = useState<NotificationDelivery[]>([]);
  const [loading, setLoading] = useState(true);

  // Per-channel action state
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; error: string | null }>>({});
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  // Add-channel form
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formKind, setFormKind] = useState<NotificationKind>('slack');
  const [formConfig, setFormConfig] = useState<Record<string, any>>({ ...EMPTY_CONFIG.slack });
  const [formEvents, setFormEvents] = useState<string[]>([]);
  const [formEnabled, setFormEnabled] = useState(true);
  const [formBusy, setFormBusy] = useState(false);
  const [formMsg, setFormMsg] = useState('');

  // Operational digest
  const [digestDays, setDigestDays] = useState(7);
  const [digest, setDigest] = useState<{ payload: Record<string, any>; text: string } | null>(null);
  const [digestBusy, setDigestBusy] = useState<'preview' | 'send' | null>(null);
  const [digestMsg, setDigestMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const previewDigest = async () => {
    setDigestBusy('preview');
    setDigestMsg(null);
    try {
      setDigest(await api.previewDigest(digestDays));
    } catch (e: any) {
      setDigestMsg({ ok: false, text: e?.message || 'Could not build the digest.' });
    } finally {
      setDigestBusy(null);
    }
  };

  const sendDigestNow = async () => {
    const targets = channels.filter(c => c.enabled).length;
    if (!window.confirm(
      `Send the last ${digestDays} days of activity to ${targets} enabled channel${targets === 1 ? '' : 's'} now? Recipients will get it immediately.`
    )) return;
    setDigestBusy('send');
    setDigestMsg(null);
    try {
      const r = await api.sendDigest(digestDays);
      setDigestMsg({
        ok: r.failed === 0,
        text: `Digest delivered to ${r.sent} destination${r.sent === 1 ? '' : 's'}`
          + (r.failed ? `, ${r.failed} failed.` : '.'),
      });
      loadDeliveries();
    } catch (e: any) {
      setDigestMsg({ ok: false, text: e?.message || 'Send failed.' });
    } finally {
      setDigestBusy(null);
    }
  };

  const loadChannels = () => api.getNotificationChannels().then(r => setChannels(r.channels || [])).catch(() => setChannels([]));
  const loadDeliveries = () => api.getNotificationDeliveries(50).then(r => setDeliveries(r.deliveries || [])).catch(() => setDeliveries([]));

  useEffect(() => {
    (async () => {
      setLoading(true);
      await Promise.allSettled([
        api.getNotificationEvents().then(r => { setEvents(r.events || []); if (r.kinds?.length) setKinds(r.kinds); }),
        loadChannels(),
        loadDeliveries(),
      ]);
      setLoading(false);
    })();
  }, []);

  const switchKind = (k: NotificationKind) => {
    setFormKind(k);
    setFormConfig({ ...EMPTY_CONFIG[k] });
  };

  const toggleFormEvent = (ev: string) => {
    setFormEvents(prev => (prev.includes(ev) ? prev.filter(e => e !== ev) : [...prev, ev]));
  };

  const buildConfig = (): Record<string, any> => {
    if (formKind === 'smtp') {
      return {
        host: formConfig.host,
        port: Number(formConfig.port) || 587,
        username: formConfig.username,
        password: formConfig.password,
        use_tls: !!formConfig.use_tls,
        from_addr: formConfig.from_addr,
        to_addrs: String(formConfig.to_addrs || '').split(',').map((s: string) => s.trim()).filter(Boolean),
      };
    }
    if (formKind === 'slack') return { webhook_url: formConfig.webhook_url };
    const cfg: Record<string, any> = { url: formConfig.url };
    if (formConfig.secret) cfg.secret = formConfig.secret;
    return cfg;
  };

  const formValid =
    formName.trim().length > 0 &&
    (formKind === 'smtp' ? !!formConfig.host && !!formConfig.from_addr && String(formConfig.to_addrs || '').trim().length > 0
      : formKind === 'slack' ? !!formConfig.webhook_url
        : !!formConfig.url);

  const createChannel = async () => {
    setFormBusy(true); setFormMsg('');
    try {
      await api.createNotificationChannel({ name: formName.trim(), kind: formKind, config: buildConfig(), events: formEvents, enabled: formEnabled });
      setFormMsg('Channel created.');
      setFormName(''); setFormEvents([]); setFormEnabled(true); setFormConfig({ ...EMPTY_CONFIG[formKind] });
      setShowForm(false);
      await loadChannels();
    } catch (e: any) {
      setFormMsg(e?.message || 'Create failed');
    } finally {
      setFormBusy(false);
    }
  };

  const toggleEnabled = async (c: NotificationChannel) => {
    setRowBusy(c.id);
    try {
      await api.updateNotificationChannel(c.id, { enabled: !c.enabled });
      setChannels(prev => prev.map(ch => (ch.id === c.id ? { ...ch, enabled: !c.enabled } : ch)));
    } catch { /* keep prior state */ } finally { setRowBusy(null); }
  };

  const runTest = async (id: string) => {
    setTesting(id);
    setTestResults(prev => { const n = { ...prev }; delete n[id]; return n; });
    try {
      const res = await api.testNotificationChannel(id);
      setTestResults(prev => ({ ...prev, [id]: res }));
    } catch (e: any) {
      setTestResults(prev => ({ ...prev, [id]: { ok: false, error: e?.message || 'Test failed' } }));
    } finally {
      setTesting(null);
      loadDeliveries();
    }
  };

  const deleteChannel = async (id: string) => {
    setRowBusy(id);
    try {
      await api.deleteNotificationChannel(id);
      setChannels(prev => prev.filter(c => c.id !== id));
    } catch { /* ignore */ } finally { setRowBusy(null); setConfirmDelete(null); }
  };

  const card: React.CSSProperties = { background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: 14 };
  const input: React.CSSProperties = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink, borderRadius: 8, padding: '8px 10px', fontSize: 13, width: '100%' };

  return (
    <div className="space-y-4">
      {/* Channels */}
      <div className="p-5" style={card}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Bell className="w-5 h-5" style={{ color: colors.primary }} />
            <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Notification Channels</span>
          </div>
          <button onClick={() => { setShowForm(v => !v); setFormMsg(''); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium"
            style={{ background: showForm ? colors.surface2 : colors.primary, color: showForm ? colors.ink : '#fff', border: showForm ? `1px solid ${colors.hairline}` : '1px solid transparent' }}>
            <Plus className="w-4 h-4" /> {showForm ? 'Cancel' : 'Add channel'}
          </button>
        </div>
        <p className="text-[12px] mb-4" style={{ color: colors.inkSubtle }}>
          Where KAEOS sends operational alerts: HITL approvals, mission checkpoints, SLA breaches, and security incidents. Secrets are stored server-side and shown masked.
        </p>

        {/* Add channel form */}
        {showForm && (
          <div className="p-4 rounded-lg mb-4 space-y-3" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <input style={input} placeholder="Channel name (e.g. Ops alerts)" value={formName} onChange={e => setFormName(e.target.value)} />
              <select style={input} value={formKind} onChange={e => switchKind(e.target.value as NotificationKind)}>
                {kinds.map(k => <option key={k} value={k}>{KIND_META[k]?.label || k}</option>)}
              </select>
            </div>

            {/* Kind-specific config */}
            {formKind === 'smtp' && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <input style={input} placeholder="SMTP host (e.g. smtp.acme.com)" value={formConfig.host} onChange={e => setFormConfig({ ...formConfig, host: e.target.value })} />
                <input style={input} type="number" placeholder="Port" value={formConfig.port} onChange={e => setFormConfig({ ...formConfig, port: e.target.value })} />
                <input style={input} placeholder="Username" value={formConfig.username} onChange={e => setFormConfig({ ...formConfig, username: e.target.value })} />
                <input style={input} type="password" placeholder="Password" value={formConfig.password} onChange={e => setFormConfig({ ...formConfig, password: e.target.value })} />
                <input style={input} placeholder="From address" value={formConfig.from_addr} onChange={e => setFormConfig({ ...formConfig, from_addr: e.target.value })} />
                <input style={input} placeholder="To addresses (comma-separated)" value={formConfig.to_addrs} onChange={e => setFormConfig({ ...formConfig, to_addrs: e.target.value })} />
                <label className="flex items-center gap-2 text-[13px]" style={{ color: colors.ink }}>
                  <input type="checkbox" checked={!!formConfig.use_tls} onChange={e => setFormConfig({ ...formConfig, use_tls: e.target.checked })} style={{ accentColor: colors.primary }} />
                  Use TLS
                </label>
              </div>
            )}
            {formKind === 'slack' && (
              <input style={input} placeholder="Slack webhook URL (https://hooks.slack.com/...)" value={formConfig.webhook_url} onChange={e => setFormConfig({ ...formConfig, webhook_url: e.target.value })} />
            )}
            {formKind === 'webhook' && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <input style={input} placeholder="Webhook URL (https://...)" value={formConfig.url} onChange={e => setFormConfig({ ...formConfig, url: e.target.value })} />
                <input style={input} type="password" placeholder="Signing secret (optional)" value={formConfig.secret} onChange={e => setFormConfig({ ...formConfig, secret: e.target.value })} />
              </div>
            )}

            {/* Event subscriptions */}
            <div>
              <div className="text-[12px] font-medium mb-1.5" style={{ color: colors.ink }}>Subscribed events</div>
              <p className="text-[11px] mb-2" style={{ color: colors.inkTertiary }}>Leave all unchecked to receive every event.</p>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                {events.map(ev => (
                  <label key={ev} className="flex items-center gap-1.5 text-[12px] font-mono cursor-pointer" style={{ color: colors.ink }}>
                    <input type="checkbox" checked={formEvents.includes(ev)} onChange={() => toggleFormEvent(ev)} style={{ accentColor: colors.primary }} />
                    {ev}
                  </label>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button onClick={createChannel} disabled={formBusy || !formValid}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium disabled:opacity-50"
                style={{ background: colors.primary, color: '#fff' }}>
                {formBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Create channel
              </button>
              <label className="flex items-center gap-2 text-[13px]" style={{ color: colors.ink }}>
                <input type="checkbox" checked={formEnabled} onChange={e => setFormEnabled(e.target.checked)} style={{ accentColor: colors.primary }} />
                Enabled
              </label>
            </div>
            {formMsg && <p className="text-[12px]" style={{ color: colors.inkSubtle }}>{formMsg}</p>}
          </div>
        )}

        {/* Channel list */}
        {!loading && channels.length === 0 && !showForm && (
          <div className="p-8 text-center">
            <Bell className="w-10 h-10 mx-auto mb-3" style={{ color: colors.inkTertiary }} />
            <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
              No channels yet. Add SMTP, Slack, or a webhook so approvals and SLA breaches reach your team.
            </p>
          </div>
        )}
        <div className="space-y-2">
          {channels.map(c => {
            const meta = KIND_META[c.kind] || { label: c.kind, color: colors.primary, Icon: Webhook };
            const KindIcon = meta.Icon;
            const test = testResults[c.id];
            return (
              <div key={c.id} className="px-3 py-2.5 rounded-lg" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="text-[11px] px-2 py-0.5 rounded-full font-medium flex items-center gap-1 flex-shrink-0"
                    style={{ background: meta.color + '1f', color: meta.color }}>
                    <KindIcon className="w-3 h-3" /> {meta.label}
                  </span>
                  <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{c.name}</span>
                  <div className="flex items-center gap-1 flex-wrap">
                    {(c.events || []).length === 0 ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: colors.surface1, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>all events</span>
                    ) : (
                      c.events.map(ev => (
                        <span key={ev} className="text-[11px] px-1.5 py-0.5 rounded font-mono" style={{ background: colors.surface1, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>{ev}</span>
                      ))
                    )}
                  </div>
                  <div className="flex items-center gap-2 ml-auto flex-shrink-0">
                    <button onClick={() => toggleEnabled(c)} disabled={rowBusy === c.id}
                      className="text-[11px] px-2 py-0.5 rounded-full font-medium"
                      style={{
                        background: c.enabled ? colors.success + '1f' : 'rgba(138,143,152,0.12)',
                        color: c.enabled ? colors.success : colors.inkSubtle,
                      }}>
                      {rowBusy === c.id ? '...' : c.enabled ? 'Enabled' : 'Disabled'}
                    </button>
                    <button onClick={() => runTest(c.id)} disabled={testing === c.id}
                      className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md font-semibold disabled:opacity-50"
                      style={{ background: colors.primary + '1f', color: colors.primary }}>
                      {testing === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />} Test
                    </button>
                    {confirmDelete === c.id ? (
                      <button onClick={() => deleteChannel(c.id)} disabled={rowBusy === c.id}
                        className="text-[11px] px-2.5 py-1 rounded-md font-semibold"
                        style={{ background: colors.error, color: '#fff' }}>
                        Confirm delete
                      </button>
                    ) : (
                      <button onClick={() => setConfirmDelete(c.id)} className="p-1.5 rounded" style={{ color: colors.error }} title="Delete channel">
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </div>
                {test && (
                  <p className="text-[12px] mt-1.5" style={{ color: test.ok ? colors.success : colors.error }}>
                    {test.ok ? 'Test message sent.' : `Test failed: ${test.error || 'unknown error'}`}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Operational digest */}
      <div className="p-5" style={card}>
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Newspaper className="w-5 h-5" style={{ color: colors.primary }} />
            <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Operational Digest</span>
          </div>
          <div className="flex items-center gap-2">
            <select value={digestDays} onChange={e => { setDigestDays(Number(e.target.value)); setDigest(null); }}
              aria-label="Digest window"
              className="px-2.5 py-1.5 rounded-lg text-[12px] outline-none"
              style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
              <option value={1}>Last 24 hours</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
            <button onClick={previewDigest} disabled={digestBusy !== null}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium disabled:opacity-50"
              style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairline}` }}>
              {digestBusy === 'preview' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Eye className="w-4 h-4" />} Preview
            </button>
            <button onClick={sendDigestNow} disabled={digestBusy !== null}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium text-white disabled:opacity-50"
              style={{ background: colors.primary }}>
              {digestBusy === 'send' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} Send now
            </button>
          </div>
        </div>
        <p className="text-[12px] mb-3" style={{ color: colors.inkSubtle }}>
          A periodic summary of how much work ran itself, what is waiting on a human, and what it cost. Sent to every enabled channel above.
        </p>

        {digestMsg && (
          <div className="flex items-start gap-2 px-3 py-2 mb-3 rounded-lg text-[12px] font-medium"
            style={{
              background: (digestMsg.ok ? colors.success : colors.error) + '15',
              color: digestMsg.ok ? colors.success : colors.error,
            }}>
            {digestMsg.ok ? <CheckCircle2 className="w-4 h-4 shrink-0 mt-px" /> : <XCircle className="w-4 h-4 shrink-0 mt-px" />}
            <span className="flex-1">{digestMsg.text}</span>
            <button onClick={() => setDigestMsg(null)} className="text-[11px] opacity-70">dismiss</button>
          </div>
        )}

        {digest && (() => {
          const p = digest.payload || {};
          const rate = toPct(p.safe_autonomy_rate);
          const missions = Object.entries((p.missions || {}) as Record<string, number>);
          return (
            <div className="p-4 rounded-lg space-y-4" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
              <p className="text-[13px]" style={{ color: colors.ink }}>
                Over the last <strong>{p.window_days} day{p.window_days === 1 ? '' : 's'}</strong>, KAEOS ran{' '}
                <strong>{(p.executions ?? 0).toLocaleString()}</strong> task{p.executions === 1 ? '' : 's'}
                {rate != null && <> and finished <strong>{rate.toFixed(1)}%</strong> of them safely without a human</>}.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  { label: 'Waiting on a person', value: (p.pending_approvals ?? 0).toLocaleString(), tone: (p.pending_approvals ?? 0) > 0 ? colors.warning : colors.ink },
                  { label: 'Incidents', value: (p.incidents ?? 0).toLocaleString(), tone: (p.incidents ?? 0) > 0 ? colors.error : colors.ink },
                  { label: 'Spend', value: p.spend_usd != null ? `$${Number(p.spend_usd).toFixed(2)}` : 'not measured', tone: colors.ink },
                  { label: 'Tasks run', value: (p.executions ?? 0).toLocaleString(), tone: colors.ink },
                ].map(s => (
                  <div key={s.label} className="p-3 rounded-lg" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                    <div className="text-[20px] font-bold" style={{ color: s.tone }}>{s.value}</div>
                    <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{s.label}</div>
                  </div>
                ))}
              </div>

              {(p.lowest_autonomy_skills || []).length > 0 && (
                <div>
                  <div className="text-[12px] font-medium mb-1.5" style={{ color: colors.ink }}>Needing the most human help</div>
                  <div className="space-y-1">
                    {(p.lowest_autonomy_skills as any[]).map((s, i) => {
                      const r = toPct(s.safe_autonomy_rate);
                      return (
                        <div key={`${s.skill}-${i}`} className="flex items-center gap-2 text-[12px]">
                          <span className="truncate flex-1" style={{ color: colors.inkSubtle }}>
                            {humanize(String(s.skill || 'unnamed skill'))}
                          </span>
                          <span className="font-mono tabular-nums shrink-0"
                            style={{ color: (r ?? 100) < 60 ? colors.warning : colors.ink }}>
                            {r != null ? `${r.toFixed(0)}% on its own` : 'no rate yet'}
                          </span>
                          <span className="shrink-0" style={{ color: colors.inkTertiary }}>
                            of {(s.total ?? 0).toLocaleString()} run{s.total === 1 ? '' : 's'}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {missions.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[12px] font-medium" style={{ color: colors.ink }}>Missions:</span>
                  {missions.map(([state, n]) => (
                    <span key={state} className="text-[11px] px-2 py-0.5 rounded-full"
                      style={{ background: colors.surface1, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
                      {n} {state.replace(/_/g, ' ').toLowerCase()}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })()}
      </div>

      {/* Recent deliveries */}
      <div className="rounded-xl overflow-hidden" style={card}>
        <div className="px-5 py-3 border-b flex items-center gap-2" style={{ borderColor: colors.hairline }}>
          <History className="w-4 h-4" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Recent Deliveries</span>
        </div>
        {deliveries.length === 0 && (
          <div className="p-8 text-center text-[13px]" style={{ color: colors.inkTertiary }}>
            No deliveries yet. Sends and failures will show up here.
          </div>
        )}
        {deliveries.map(d => (
          <div key={d.id} className="px-5 py-2.5 border-b last:border-0 flex items-center gap-3" style={{ borderColor: colors.hairline }}>
            <span className="text-[11px] px-2 py-0.5 rounded font-mono flex-shrink-0" style={{ background: colors.surface2, color: colors.inkSubtle }}>{d.event}</span>
            <span className="text-[13px] flex-1 min-w-0 truncate" style={{ color: colors.ink }}>{d.subject}</span>
            <span className="text-[11px] px-2 py-0.5 rounded-full font-medium flex-shrink-0"
              title={d.error || undefined}
              style={{
                background: d.status === 'SENT' ? colors.success + '1f' : colors.error + '1f',
                color: d.status === 'SENT' ? colors.success : colors.error,
              }}>
              {d.status}
            </span>
            {d.status !== 'SENT' && d.error && (
              <span className="text-[11px] max-w-[240px] truncate flex-shrink-0" title={d.error} style={{ color: colors.error }}>{d.error}</span>
            )}
            <span className="text-[11px] flex-shrink-0" style={{ color: colors.inkTertiary }}>{fmtTime(d.created_at)}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default NotificationSettings;
