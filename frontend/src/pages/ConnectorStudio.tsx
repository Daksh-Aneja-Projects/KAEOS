import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainError, BrainEmpty, BrainLoading } from '../components/BrainStates';
import {
  Database, Search, Filter, CheckCircle, AlertCircle, XCircle, Loader2,
  ArrowRight, Lock, Eye, RefreshCw, Zap, Clock, ChevronRight, Upload,
  Settings, Activity, MapPin, Shield, BarChart3, Layers, Plug,
  KeyRound, Send, Inbox, ArrowUpFromLine, Copy
} from 'lucide-react';

type Screen = 'library' | 'mapper' | 'sync' | 'monitor';

export default function ConnectorStudio({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const [screen, setScreen] = useState<Screen>('library');
  const [connectors, setConnectors] = useState<any[]>([]);
  const [selectedConnector, setSelectedConnector] = useState<any>(null);
  const [mappings, setMappings] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [filterCat, setFilterCat] = useState('all');
  const [healthData, setHealthData] = useState<Record<string, any>>({});
  const [feedData, setFeedData] = useState<any[]>([]);
  const [feedLoading, setFeedLoading] = useState(false);
  const [mappingError, setMappingError] = useState(false);
  const [catalog, setCatalog] = useState<any>(null);

  useEffect(() => {
    api.getConnectors().then(r => { setConnectors(r.connectors || []); setLoading(false); }).catch(() => setLoading(false));
    api.getConnectorProviders().then(setCatalog).catch(() => setCatalog(null));
  }, []);

  const filtered = connectors.filter(c => {
    const matchSearch = !searchQ || c.name.toLowerCase().includes(searchQ.toLowerCase());
    const matchCat = filterCat === 'all' || c.category === filterCat;
    return matchSearch && matchCat;
  });

  const categories = ['all', ...new Set(connectors.map(c => c.category))];

  const statusColor = (s: string) => {
    if (s === 'CONNECTED') return '#22c55e';
    if (s === 'SYNCING') return '#f59e0b';
    if (s === 'ERROR') return '#ef4444';
    return colors.inkSubtle;
  };

  const statusIcon = (s: string) => {
    if (s === 'CONNECTED') return <CheckCircle className="w-4 h-4" style={{ color: '#22c55e' }} />;
    if (s === 'SYNCING') return <Loader2 className="w-4 h-4 animate-spin" style={{ color: '#f59e0b' }} />;
    if (s === 'ERROR') return <XCircle className="w-4 h-4" style={{ color: '#ef4444' }} />;
    return <Database className="w-4 h-4" style={{ color: colors.inkSubtle }} />;
  };

  const confColor = (tier: string) => {
    if (tier === 'GREEN') return '#22c55e';
    if (tier === 'AMBER') return '#f59e0b';
    return '#ef4444';
  };

  const openMapper = async (c: any) => {
    setSelectedConnector(c);
    // Fetch real schema fields from connector, fall back to connector's stored fields
    let sourceFields = c.source_fields || c.schema_fields || [];
    if (!sourceFields.length) {
      try {
        const schemaResp = await api.getConnectorHealth(c.id);
        sourceFields = schemaResp?.source_fields || schemaResp?.schema || [];
      } catch { /* use fallback */ }
    }
    // Minimal fallback only if connector has no schema at all
    if (!sourceFields.length) {
      sourceFields = [
        { field_name: 'id', object_type: 'Record', data_type: 'string' },
        { field_name: 'name', object_type: 'Record', data_type: 'string' },
        { field_name: 'email', object_type: 'Record', data_type: 'string' },
      ];
    }
    api.proposeSchemaMappings(c.id, sourceFields)
      .then(r => { setMappings(r || []); setMappingError(false); setScreen('mapper'); })
      .catch(() => {
        setMappings([]);
        setMappingError(true);
        setScreen('mapper');
      });
  };


  const screens: { id: Screen; label: string; icon: any }[] = [
    { id: 'library', label: 'Source Library', icon: Database },
    { id: 'mapper', label: 'Schema Mapper', icon: Layers },
    { id: 'sync', label: 'Sync Config', icon: RefreshCw },
    { id: 'monitor', label: 'Ingestion Monitor', icon: Activity },
  ];

  const card = (bg: string) => ({
    background: bg, borderRadius: '10px', border: `1px solid ${colors.hairline}`,
    padding: '16px', transition: 'all 0.2s'
  });

  return (
    <div className="h-full flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      {/* Screen Tabs */}
      <div className="flex items-center gap-1 px-6 py-2 border-b" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
        {screens.map(s => (
          <button key={s.id} onClick={() => setScreen(s.id)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-[12px] font-medium transition-all"
            style={{
              background: screen === s.id ? colors.primary + '18' : 'transparent',
              color: screen === s.id ? colors.primary : colors.inkSubtle,
              border: screen === s.id ? `1px solid ${colors.primary}30` : '1px solid transparent'
            }}>
            <s.icon className="w-3.5 h-3.5" />
            {s.label}
          </button>
        ))}
        {selectedConnector && (
          <div className="ml-auto flex items-center gap-2 text-[11px]" style={{ color: colors.inkSubtle }}>
            <ChevronRight className="w-3 h-3" />
            <span className="font-medium" style={{ color: colors.ink }}>{selectedConnector.name}</span>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {/* Screen 1: Source Library */}
        {screen === 'library' && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[18px] font-semibold tracking-tight">Connector Library</h2>
                <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
                  Pre-built connectors for SaaS, On-Prem, and File systems. OAuth credentials stored in Vault.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
                  <input value={searchQ} onChange={e => setSearchQ(e.target.value)}
                    placeholder="Search connectors..."
                    className="pl-8 pr-3 py-1.5 rounded-lg border text-[12px] focus:outline-none"
                    style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink, width: 200 }} />
                </div>
              </div>
            </div>

            {/* Supported integrations - the live adapter catalog from the backend */}
            {catalog && (
              <div className="rounded-xl p-4" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Plug className="w-4 h-4" style={{ color: colors.primary }} />
                    <span className="text-[13px] font-semibold" style={{ color: colors.ink }}>
                      Supported Integrations
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full font-bold"
                      style={{ background: colors.primary + '18', color: colors.primary }}>
                      {catalog.total} live adapters
                    </span>
                  </div>
                  <span className="text-[11px]" style={{ color: colors.inkTertiary }}>
                    Credentials are encrypted at rest and never returned by the API
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-3">
                  {Object.entries(catalog.by_domain).sort().map(([domain, ids]: [string, any]) => (
                    <div key={domain} className="p-2.5 rounded-lg" style={{ background: colors.surface2 }}>
                      <div className="text-[11px] font-bold uppercase tracking-wide mb-1.5 capitalize"
                        style={{ color: colors.inkTertiary }}>
                        {domain} · {ids.length}
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {ids.map((id: string) => {
                          const p = catalog.providers.find((x: any) => x.id === id);
                          return (
                            <span key={id}
                              title={p?.handles_pii ? 'Handles PII - scrubbed on ingest' : undefined}
                              className="px-1.5 py-0.5 rounded text-[11px] font-medium flex items-center gap-1"
                              style={{ background: colors.surface1, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
                              {id}
                              {p?.handles_pii && <Shield className="w-2.5 h-2.5" style={{ color: '#f59e0b' }} />}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Category Filter */}
            <div className="flex items-center gap-2 flex-wrap">
              {categories.map(cat => (
                <button key={cat} onClick={() => setFilterCat(cat)}
                  className="px-3 py-1 rounded-full text-[11px] font-medium transition-all capitalize"
                  style={{
                    background: filterCat === cat ? colors.primary + '20' : colors.surface1,
                    color: filterCat === cat ? colors.primary : colors.inkSubtle,
                    border: `1px solid ${filterCat === cat ? colors.primary + '40' : colors.hairline}`
                  }}>
                  {cat}
                </button>
              ))}
            </div>

            {/* Connector Grid */}
            {loading ? (
              <div className="flex items-center gap-2 py-8 justify-center text-[13px]" style={{ color: colors.inkSubtle }}>
                <Loader2 className="w-4 h-4 animate-spin" /> Loading connectors...
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-4">
                {filtered.map(c => (
                  <div key={c.id} style={card(colors.surface1)}
                    className="hover:shadow-lg cursor-pointer group"
                    onClick={() => c.status === 'CONNECTED' ? openMapper(c) : null}>
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg flex items-center justify-center text-[18px]"
                          style={{ background: colors.primary + '15' }}>
                          <Plug className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="text-[14px] font-semibold">{c.name}</div>
                          <div className="text-[11px] capitalize" style={{ color: colors.inkSubtle }}>{c.category} • {c.connector_type}</div>
                        </div>
                      </div>
                      {statusIcon(c.status)}
                    </div>
                    <p className="text-[11px] mb-3 line-clamp-2" style={{ color: colors.inkSubtle }}>{c.description}</p>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3 text-[11px]" style={{ color: colors.inkSubtle }}>
                        <span>{c.events_ingested?.toLocaleString() || 0} events</span>
                        <span>{c.signals_extracted || 0} signals</span>
                      </div>
                      {c.status === 'CONNECTED' ? (
                        <button onClick={(e) => { e.stopPropagation(); openMapper(c); }}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium"
                          style={{ background: colors.primary + '15', color: colors.primary }}>
                          <MapPin className="w-3 h-3" /> Map Schema
                        </button>
                      ) : (
                        <button onClick={(e) => { e.stopPropagation(); api.connectConnector(c.id).then(() => window.location.reload()); }}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium"
                          style={{ background: '#22c55e15', color: '#22c55e' }}>
                          <Zap className="w-3 h-3" /> Connect
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Screen 2: Schema Mapper (AI-First) */}
        {screen === 'mapper' && mappingError && (
          <BrainError message="Schema analysis unavailable. Connect the data source and retry." onRetry={() => selectedConnector && openMapper(selectedConnector)} />
        )}
        {screen === 'mapper' && !mappingError && mappings.length === 0 && (
          <BrainEmpty title="No schema mappings available" action="Connect a data source to enable AI-powered schema mapping" />
        )}
        {screen === 'mapper' && !mappingError && mappings.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[18px] font-semibold tracking-tight">AI Schema Mapper</h2>
                <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
                  AI-suggested mappings. <span style={{ color: '#22c55e' }}>Green &gt;85%</span> auto-accepted.{' '}
                  <span style={{ color: '#f59e0b' }}>Amber</span> needs review.{' '}
                  <span style={{ color: '#ef4444' }}>Red</span> requires manual mapping.
                </p>
              </div>
              <div className="flex items-center gap-2 text-[11px]">
                <span className="inline-flex items-center gap-1" style={{ color: '#22c55e' }}><CheckCircle className="w-3 h-3" /> {mappings.filter(m => m.confidence_tier === 'GREEN').length} auto</span>
                <span className="inline-flex items-center gap-1" style={{ color: '#f59e0b' }}><AlertCircle className="w-3 h-3" /> {mappings.filter(m => m.confidence_tier === 'AMBER').length} review</span>
                <span style={{ color: '#ef4444' }}>{mappings.filter(m => m.confidence_tier === 'RED').length} manual</span>
              </div>
            </div>

            {/* Mapping Table */}
            <div className="rounded-xl border overflow-hidden" style={{ borderColor: colors.hairline }}>
              <div className="grid grid-cols-12 gap-0 text-[11px] font-semibold uppercase tracking-wider px-4 py-2.5"
                style={{ background: colors.surface1, color: colors.inkSubtle, borderBottom: `1px solid ${colors.hairline}` }}>
                <div className="col-span-2">Source Field</div>
                <div className="col-span-1">Object</div>
                <div className="col-span-1">Type</div>
                <div className="col-span-1 text-center">→</div>
                <div className="col-span-2">Target Entity</div>
                <div className="col-span-2">Target Field</div>
                <div className="col-span-1 text-center">Confidence</div>
                <div className="col-span-1 text-center">PII</div>
                <div className="col-span-1 text-center">Status</div>
              </div>
              {mappings.map((m, i) => (
                <div key={m.id || i}
                  className="grid grid-cols-12 gap-0 items-center px-4 py-2.5 text-[12px] transition-colors hover:bg-surface2"
                  style={{ borderBottom: `1px solid ${colors.hairline}`, background: i % 2 === 0 ? 'transparent' : colors.surface1 + '40' }}>
                  <div className="col-span-2 font-mono text-[11px]" style={{ color: colors.primary }}>{m.source_field}</div>
                  <div className="col-span-1 text-[11px]" style={{ color: colors.inkSubtle }}>{m.source_object}</div>
                  <div className="col-span-1 text-[11px] font-mono" style={{ color: colors.inkSubtle }}>{m.source_type}</div>
                  <div className="col-span-1 text-center">
                    <ArrowRight className="w-3 h-3 mx-auto" style={{ color: confColor(m.confidence_tier) }} />
                  </div>
                  <div className="col-span-2 font-medium">{m.target_entity}</div>
                  <div className="col-span-2 font-mono text-[11px]">{m.target_field}</div>
                  <div className="col-span-1 text-center">
                    <span className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                      style={{ background: confColor(m.confidence_tier) + '20', color: confColor(m.confidence_tier) }}>
                      {(m.ai_confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="col-span-1 text-center">
                    {m.is_pii ? (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-bold"
                        style={{ background: '#ef444420', color: '#ef4444' }}>
                        <Lock className="w-2.5 h-2.5" /> {m.pii_category || 'PII'}
                      </span>
                    ) : <span className="text-[11px]" style={{ color: colors.inkSubtle }}>-</span>}
                  </div>
                  <div className="col-span-1 text-center">
                    {m.admin_confirmed ? (
                      <CheckCircle className="w-4 h-4 mx-auto" style={{ color: '#22c55e' }} />
                    ) : (
                      <button onClick={() => {
                        api.confirmSchemaMapping(m.id, 'admin').catch(() => {});
                        setMappings(prev => prev.map(p => p.id === m.id ? { ...p, admin_confirmed: true } : p));
                      }}
                        className="px-2 py-0.5 rounded text-[11px] font-medium"
                        style={{ background: colors.primary + '15', color: colors.primary }}>
                        Confirm
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-3">
              <button onClick={() => setMappings(prev => prev.map(m => ({ ...m, admin_confirmed: true })))}
                className="px-4 py-2 rounded-lg text-[12px] font-medium"
                style={{ background: '#22c55e15', color: '#22c55e', border: '1px solid #22c55e30' }}>
                Confirm All Green
              </button>
              <button onClick={() => setScreen('sync')}
                className="px-4 py-2 rounded-lg text-[12px] font-medium text-white"
                style={{ background: colors.primary }}>
                Continue to Sync Config →
              </button>
            </div>
          </div>
        )}

        {/* Screen 3: Sync Configuration */}
        {screen === 'sync' && (
          <div className="space-y-5 max-w-7xl">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight">Sync Configuration</h2>
              <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
                Configure how data flows from {selectedConnector?.name || 'source'} to the Knowledge Graph.
              </p>
            </div>

            {/* Live sync plane: inbound signing secret, what has moved, what is queued out */}
            <SyncOperations connectors={connectors} selectedConnector={selectedConnector} colors={colors} card={card} />

            {/* Sync Mode */}
            <div style={card(colors.surface1)}>
              <h3 className="text-[13px] font-semibold mb-3">Sync Mode</h3>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { id: 'realtime', label: 'Real-Time', desc: 'Kafka streaming', icon: Zap, color: '#22c55e' },
                  { id: 'scheduled', label: 'Scheduled Batch', desc: 'Cron-based', icon: Clock, color: '#f59e0b' },
                  { id: 'manual', label: 'Manual Trigger', desc: 'On-demand', icon: Upload, color: colors.primary },
                ].map(mode => (
                  <div key={mode.id} className="p-3 rounded-lg border cursor-pointer transition-all hover:shadow-md"
                    style={{ borderColor: colors.hairline, background: colors.canvas }}>
                    <div className="flex items-center gap-2 mb-1">
                      <mode.icon className="w-4 h-4" style={{ color: mode.color }} />
                      <span className="text-[12px] font-semibold">{mode.label}</span>
                    </div>
                    <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{mode.desc}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Entity Selection */}
            <div style={card(colors.surface1)}>
              <h3 className="text-[13px] font-semibold mb-3">Entity Types to Sync</h3>
              <div className="grid grid-cols-3 gap-2">
                {['Employee', 'OrgUnit', 'Role', 'Policy', 'Contract', 'Asset'].map(ent => (
                  <label key={ent} className="flex items-center gap-2 p-2 rounded border cursor-pointer text-[12px]"
                    style={{ borderColor: colors.hairline }}>
                    <input type="checkbox" defaultChecked className="rounded" />
                    {ent}
                  </label>
                ))}
              </div>
            </div>

            {/* CDC Toggle */}
            <div style={card(colors.surface1)}>
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-[13px] font-semibold">Change Data Capture (CDC)</h3>
                  <p className="text-[11px]" style={{ color: colors.inkSubtle }}>Delta-only sync after initial full load via Debezium</p>
                </div>
                <div className="w-10 h-5 rounded-full relative cursor-pointer" style={{ background: '#22c55e' }}>
                  <div className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-white shadow" />
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3">
              <button onClick={() => setScreen('monitor')}
                className="px-4 py-2 rounded-lg text-[12px] font-medium text-white"
                style={{ background: colors.primary }}>
                Start Full Crawl →
              </button>
            </div>
          </div>
        )}

        {/* Screen 4: Ingestion Monitor */}
        {screen === 'monitor' && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[18px] font-semibold tracking-tight">Ingestion Monitor</h2>
                <p className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
                  Real-time ingestion feed with connector health and freshness heatmap.
                </p>
              </div>
              <div className="flex items-center gap-2 text-[11px] font-bold px-3 py-1.5 rounded-full"
                style={{ background: '#22c55e15', color: '#22c55e' }}>
                <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" /> Live
              </div>
            </div>

            {/* Connector Health Cards - real data from /connectors/{id}/health */}
            <ConnectorHealthCards connectors={connectors.filter(c => c.status === 'CONNECTED').slice(0, 4)} healthData={healthData} setHealthData={setHealthData} colors={colors} card={card} />

            {/* Freshness Heatmap - real entity data from health endpoint */}
            <div style={card(colors.surface1)}>
              <h3 className="text-[13px] font-semibold mb-3">Entity Freshness Heatmap</h3>
              <div className="grid grid-cols-6 gap-2">
                {(() => {
                  const allEntities = Object.values(healthData).flatMap((h: any) => h?.entity_freshness || []);
                  if (allEntities.length === 0) return <span className="text-[11px] col-span-6 text-center py-4" style={{ color: colors.inkSubtle }}>No entity freshness data yet. Connectors must sync first.</span>;
                  return allEntities.slice(0, 6).map((ent: any) => {
                    const f = ent.freshness_pct / 100;
                    const color = f > 0.8 ? '#22c55e' : f > 0.6 ? '#f59e0b' : '#ef4444';
                    return (
                      <div key={ent.entity_type} className="p-3 rounded-lg text-center" style={{ background: color + '15' }}>
                        <div className="text-[20px] font-bold" style={{ color }}>{ent.freshness_pct.toFixed(0)}%</div>
                        <div className="text-[11px] font-medium mt-1">{ent.entity_type}</div>
                      </div>
                    );
                  });
                })()}
              </div>
            </div>

            {/* Live Feed - real Signal records from /connectors/{id}/feed */}
            <ConnectorFeedPanel connectors={connectors.filter(c => c.status === 'CONNECTED')} colors={colors} card={card} />
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Sync Operations — the real, live half of the Sync screen.
 *   - rotate the HMAC secret an inbound webhook must sign with
 *   - the two-way sync ledger (what actually moved, and whether it landed)
 *   - the outbound queue, with a manual dispatch for when you cannot wait
 * All three back real endpoints under /integrations.
 */
function SyncOperations({ connectors, selectedConnector, colors, card }: any) {
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
                    {(o.op || 'change').toLowerCase()} {(o.entity_type || 'record').replace(/_/g, ' ')}
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
                    {(l.entity_type || 'record').replace(/_/g, ' ')}
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
function ConnectorHealthCards({ connectors, healthData, setHealthData, colors, card }: any) {
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
    <div className="grid grid-cols-4 gap-4">
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
function ConnectorFeedPanel({ connectors, colors, card }: any) {
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
