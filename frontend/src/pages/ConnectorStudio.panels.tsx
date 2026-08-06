/**
 * ConnectorStudio — Sync / Health / Feed panels.
 *
 * The three live sub-screens extracted from ConnectorStudio.tsx so the page
 * component stays under the size budget. Each backs real /integrations and
 * /connectors endpoints and is driven entirely by props; behavior is unchanged.
 */
import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { BrainError, BrainEmpty } from '../components/BrainStates';
import {
  CheckCircle, XCircle, Loader2, RefreshCw, Plug,
  KeyRound, Send, Inbox, ArrowUpFromLine, Copy,
} from 'lucide-react';
import { humanize } from '../lib/format';


/**
 * Sync Operations — the real, live half of the Sync screen.
 *   - rotate the HMAC secret an inbound webhook must sign with
 *   - the two-way sync ledger (what actually moved, and whether it landed)
 *   - the outbound queue, with a manual dispatch for when you cannot wait
 * All three back real endpoints under /integrations.
 */
export function SyncOperations({ connectors, selectedConnector, colors, card }: any) {
  const [target, setTarget] = useState<string>(selectedConnector?.id || '');
  const [rotating, setRotating] = useState(false);
  const [secret, setSecret] = useState<{ webhook_secret: string; ingest_url: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [ledger, setLedger] = useState<any[] | null>(null);
  const [outbound, setOutbound] = useState<any[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [dispatching, setDispatching] = useState(false);
  const [banner, setBanner] = useState<{ ok: boolean; text: string } | null>(null);

  const loadQueues = React.useCallback(async () => {
    setLoadErr(null);
    const [l, o] = await Promise.allSettled([api.getSyncLedger(50), api.getOutboundQueue(50)]);
    if (l.status === 'rejected' && o.status === 'rejected') {
      setLoadErr((l.reason as any)?.message || 'The sync service is unreachable.');
      return;
    }
    setLedger(l.status === 'fulfilled' ? (l.value.ledger || []) : []);
    setOutbound(o.status === 'fulfilled' ? (o.value.outbound || []) : []);
  }, []);

  useEffect(() => { loadQueues(); }, [loadQueues]);

  const rotate = async () => {
    if (!target) return;
    const name = connectors.find((c: any) => c.id === target)?.name || 'this connector';
    if (!window.confirm(
      `Issue a new signing secret for ${name}? The current one stops working immediately, so anything already sending events must be updated.`
    )) return;
    setRotating(true);
    setBanner(null);
    setSecret(null);
    try {
      const r = await api.rotateWebhookSecret(target);
      setSecret({ webhook_secret: r.webhook_secret, ingest_url: r.ingest_url });
    } catch (e: any) {
      setBanner({ ok: false, text: e?.message || 'Could not issue a new secret.' });
    } finally {
      setRotating(false);
    }
  };

  const dispatch = async () => {
    setDispatching(true);
    setBanner(null);
    try {
      const r = await api.dispatchOutbound();
      setBanner({
        ok: r.failed === 0,
        text: `${r.sent} change${r.sent === 1 ? '' : 's'} delivered`
          + (r.failed ? `, ${r.failed} failed` : '')
          + (r.skipped ? `, ${r.skipped} skipped because the connector has no credentials` : '') + '.',
      });
      await loadQueues();
    } catch (e: any) {
      setBanner({ ok: false, text: e?.message || 'Dispatch failed.' });
    } finally {
      setDispatching(false);
    }
  };

  const statusTone = (s: string) => {
    if (s === 'SENT' || s === 'OK' || s === 'SUCCESS') return '#22c55e';
    if (s === 'FAILED' || s === 'ERROR') return '#ef4444';
    if (s === 'PENDING') return '#f59e0b';
    return colors.inkSubtle;
  };
  // Never show a raw SKIPPED_NO_CREDENTIALS to a human.
  const statusLabel = (s: string) => (s || 'unknown').replace(/_/g, ' ').toLowerCase();

  const pending = (outbound || []).filter(o => o.status === 'PENDING').length;

  return (
    <div className="space-y-4">
      {banner && (
        <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg text-[12px] font-medium"
          style={{ background: (banner.ok ? '#22c55e' : '#ef4444') + '15', color: banner.ok ? '#22c55e' : '#ef4444' }}>
          {banner.ok ? <CheckCircle className="w-4 h-4 shrink-0 mt-px" /> : <XCircle className="w-4 h-4 shrink-0 mt-px" />}
          <span className="flex-1">{banner.text}</span>
          <button onClick={() => setBanner(null)} className="text-[11px] opacity-70">dismiss</button>
        </div>
      )}

      {/* Inbound signing secret */}
      <div style={card(colors.surface1)}>
        <div className="flex items-center gap-2 mb-1">
          <KeyRound className="w-4 h-4" style={{ color: colors.primary }} />
          <h3 className="text-[13px] font-semibold">Inbound Webhook Secret</h3>
        </div>
        <p className="text-[11px] mb-3" style={{ color: colors.inkSubtle }}>
          Events pushed to KAEOS must be signed with this shared secret. Issuing a new one retires the old one at once, and the value is shown only this once.
        </p>
        <div className="flex items-end gap-2 flex-wrap">
          <div className="min-w-[240px]">
            <label className="text-[11px] uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Connector</label>
            <select value={target} onChange={e => { setTarget(e.target.value); setSecret(null); }}
              className="w-full px-3 py-2 rounded-lg text-[12px] outline-none"
              style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
              <option value="">Choose a connector…</option>
              {connectors.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <button onClick={rotate} disabled={!target || rotating}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-white disabled:opacity-50"
            style={{ background: colors.primary }}>
            {rotating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <KeyRound className="w-3.5 h-3.5" />}
            Issue new secret
          </button>
        </div>
        {secret && (
          <div className="mt-3 p-3 rounded-lg space-y-2" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2">
              <code className="text-[12px] font-mono flex-1 truncate" style={{ color: colors.ink }}>{secret.webhook_secret}</code>
              <button onClick={() => {
                navigator.clipboard?.writeText(secret.webhook_secret).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1800);
                }).catch(() => { /* clipboard blocked - the value is on screen to copy by hand */ });
              }}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold shrink-0"
                style={{ background: colors.primary + '15', color: colors.primary }}>
                <Copy className="w-3 h-3" /> {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="text-[11px]" style={{ color: colors.inkSubtle }}>
              Send events to <span className="font-mono">{secret.ingest_url}</span> with header{' '}
              <span className="font-mono">X-KAEOS-Signature</span> set to the HMAC-SHA256 of the raw body.
            </div>
          </div>
        )}
      </div>

      {loadErr && (
        <BrainError message={loadErr} onRetry={loadQueues} />
      )}

      {!loadErr && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* Outbound queue */}
          <div style={card(colors.surface1)}>
            <div className="flex items-center gap-2 mb-1">
              <ArrowUpFromLine className="w-4 h-4" style={{ color: '#f59e0b' }} />
              <h3 className="text-[13px] font-semibold">Waiting to go out</h3>
              <span className="ml-auto flex items-center gap-2">
                <button onClick={loadQueues} className="p-1 rounded" style={{ color: colors.inkSubtle }} title="Refresh">
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
                <button onClick={dispatch} disabled={dispatching || pending === 0}
                  title={pending === 0 ? 'Nothing is waiting to be sent' : undefined}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white disabled:opacity-40"
                  style={{ background: colors.primary }}>
                  {dispatching ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
                  {dispatching ? 'Sending…' : 'Dispatch now'}
                </button>
              </span>
            </div>
            <p className="text-[11px] mb-3" style={{ color: colors.inkSubtle }}>
              {pending} change{pending === 1 ? '' : 's'} queued for your systems of record. They send on the next cycle, or right now.
            </p>
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {outbound === null ? (
                <div className="flex items-center gap-2 py-3 text-[11px]" style={{ color: colors.inkSubtle }}>
                  <Loader2 className="w-3 h-3 animate-spin" /> Loading queue…
                </div>
              ) : outbound.length === 0 ? (
                <BrainEmpty title="Nothing waiting to go out" action="Changes KAEOS makes to external systems queue up here first." icon={ArrowUpFromLine} />
              ) : outbound.map(o => (
                <div key={o.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded text-[11px]"
                  style={{ background: colors.surface2 }}>
                  <span className="px-1.5 py-0.5 rounded text-[11px] font-bold shrink-0"
                    style={{ background: statusTone(o.status) + '20', color: statusTone(o.status) }}>
                    {statusLabel(o.status)}
                  </span>
                  <span className="font-medium truncate" style={{ color: colors.ink }}>
                    {(o.op || 'change').toLowerCase()} {humanize(o.entity_type || 'record')}
                  </span>
                  <span className="truncate" style={{ color: colors.inkSubtle }}>via {o.provider || 'unknown provider'}</span>
                  {(o.attempts ?? 0) > 1 && (
                    <span className="shrink-0" style={{ color: colors.inkTertiary }}>{o.attempts} tries</span>
                  )}
                  <span className="ml-auto shrink-0" style={{ color: colors.inkTertiary }}>
                    {o.created_at ? new Date(o.created_at.replace(' ', 'T')).toLocaleTimeString() : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Sync ledger */}
          <div style={card(colors.surface1)}>
            <div className="flex items-center gap-2 mb-1">
              <Inbox className="w-4 h-4" style={{ color: colors.primary }} />
              <h3 className="text-[13px] font-semibold">Recent sync activity</h3>
            </div>
            <p className="text-[11px] mb-3" style={{ color: colors.inkSubtle }}>
              Every record that crossed the boundary in either direction, and whether it landed.
            </p>
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {ledger === null ? (
                <div className="flex items-center gap-2 py-3 text-[11px]" style={{ color: colors.inkSubtle }}>
                  <Loader2 className="w-3 h-3 animate-spin" /> Loading ledger…
                </div>
              ) : ledger.length === 0 ? (
                <BrainEmpty title="No sync activity yet" action="Connect a system and run a sync to see records move." icon={Inbox} />
              ) : ledger.map(l => (
                <div key={l.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded text-[11px]"
                  style={{ background: colors.surface2 }}>
                  <span className="px-1.5 py-0.5 rounded text-[11px] font-bold shrink-0"
                    style={{ background: colors.primary + '18', color: colors.primary }}>
                    {l.direction === 'IN' ? 'incoming' : 'outgoing'}
                  </span>
                  <span className="font-medium truncate" style={{ color: colors.ink }}>
                    {humanize(l.entity_type || 'record')}
                  </span>
                  <span className="truncate" style={{ color: colors.inkSubtle }}>{l.provider || 'unknown provider'}</span>
                  <span className="shrink-0 font-semibold" style={{ color: statusTone(l.status) }}>{statusLabel(l.status)}</span>
                  <span className="ml-auto shrink-0" style={{ color: colors.inkTertiary }}>
                    {l.created_at ? new Date(l.created_at.replace(' ', 'T')).toLocaleTimeString() : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Connector Health Cards - fetches real health data from backend.
 * Replaces Math.random() for Records/hr, Error rate, Freshness.
 */
export function ConnectorHealthCards({ connectors, healthData, setHealthData, colors, card }: any) {
  useEffect(() => {
    connectors.forEach((c: any) => {
      if (!healthData[c.id]) {
        api.getConnectorHealth(c.id).then(h => {
          setHealthData((prev: any) => ({ ...prev, [c.id]: h }));
        }).catch(() => {});
      }
    });
  }, [connectors]);

  const freshnessColor = (pct: number) => pct > 70 ? '#22c55e' : pct > 40 ? '#f59e0b' : '#ef4444';
  const errorColor = (pct: number) => pct < 1 ? '#22c55e' : pct < 5 ? '#f59e0b' : '#ef4444';

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {connectors.map((c: any) => {
        const h = healthData[c.id];
        return (
          <div key={c.id} style={card(colors.surface1)}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[14px]"><Plug className="w-4 h-4" /></span>
              <span className="text-[12px] font-semibold">{c.name}</span>
            </div>
            {h ? (
              <div className="space-y-1 text-[11px]" style={{ color: colors.inkSubtle }}>
                <div className="flex justify-between"><span>Records/hr</span><span className="font-mono" style={{ color: colors.ink }}>{h.records_per_hour.toLocaleString()}</span></div>
                <div className="flex justify-between"><span>Error rate</span><span className="font-mono" style={{ color: errorColor(h.error_rate_pct) }}>{h.error_rate_pct}%</span></div>
                <div className="flex justify-between"><span>Freshness</span><span className="font-mono" style={{ color: freshnessColor(h.freshness_pct) }}>{h.freshness_pct}%</span></div>
              </div>
            ) : (
              <div className="text-[11px] py-2" style={{ color: colors.inkSubtle }}>Loading health…</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Connector Feed Panel - fetches real Signal records from backend.
 * Replaces Array.from({length:12}) fake events.
 */
export function ConnectorFeedPanel({ connectors, colors, card }: any) {
  const [feedEvents, setFeedEvents] = useState<any[]>([]);
  const [feedLoading, setFeedLoading] = useState(true);

  useEffect(() => {
    if (connectors.length === 0) { setFeedLoading(false); return; }
    const firstConnected = connectors[0];
    api.getConnectorFeed(firstConnected.id, 20)
      .then(r => { setFeedEvents(r?.events || []); setFeedLoading(false); })
      .catch(() => setFeedLoading(false));
  }, [connectors]);

  const typeColor = (t: string) => {
    if (t === 'DECISION' || t === 'APPROVAL') return '#22c55e';
    if (t === 'EXCEPTION') return '#ef4444';
    return colors.primary;
  };

  return (
    <div style={card(colors.surface1)}>
      <h3 className="text-[13px] font-semibold mb-3">Live Ingestion Feed</h3>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {feedLoading ? (
          <div className="flex items-center gap-2 py-4 text-[11px]" style={{ color: colors.inkSubtle }}>
            <span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" /> Loading feed…
          </div>
        ) : feedEvents.length === 0 ? (
          <BrainEmpty title="No recent ingestion events" action="Connect a data source and start syncing to see real-time events" />
        ) : (
          feedEvents.map((evt, i) => (
            <div key={evt.id} className="flex items-center gap-3 px-3 py-1.5 rounded text-[11px]"
              style={{ background: i === 0 ? typeColor(evt.signal_type) + '08' : 'transparent' }}>
              <span className="font-mono text-[11px]" style={{ color: colors.inkSubtle }}>
                {evt.created_at ? new Date(evt.created_at).toLocaleTimeString() : '-'}
              </span>
              <span className="px-1.5 py-0.5 rounded text-[11px] font-bold" style={{ background: typeColor(evt.signal_type) + '20', color: typeColor(evt.signal_type) }}>
                {evt.signal_type}
              </span>
              <span style={{ color: colors.inkSubtle }}>
                {evt.summary || `${evt.source_type}: ${evt.source_entity}`}
                {evt.pii_present && <span className="ml-1 text-[11px] font-bold" style={{ color: '#ef4444' }}>PII</span>}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
