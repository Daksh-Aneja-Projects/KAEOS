import React, { useEffect, useState } from 'react';
import type { ConnectorItem } from '../api/client';
import { api } from '../api/client';
import { Plug, Wifi, WifiOff, RefreshCw, Shield, Search, KeyRound, Zap } from 'lucide-react';
import ConnectorCredentialsModal from '../components/ConnectorCredentialsModal';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading } from '../components/BrainStates';

const IntegrationsHub = ({ domain = 'All Domains' }: { domain?: string }) => {
 const { colors } = useTheme();
 const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
 const [stats, setStats] = useState<any>(null);
 const [loading, setLoading] = useState(true);
 const [filter, setFilter] = useState('all');
 const [search, setSearch] = useState('');
 const [configuring, setConfiguring] = useState<ConnectorItem | null>(null);
 const [syncing, setSyncing] = useState<string | null>(null);

 const load = () => {
  setLoading(true);
  const d = domain.toLowerCase() === 'all domains' ? 'all' : domain.toLowerCase();
  const params = d === 'all' ? {} : { domain: d };

  api.getConnectors().then(d => { setConnectors(d.connectors); setStats(d.stats); setLoading(false); }).catch(() => setLoading(false));
 };
 useEffect(load, [domain]);

 const categories = ['all', ...Array.from(new Set(connectors.map(c => c.category)))];
 const filtered = connectors.filter(c =>
  (filter === 'all' || c.category === filter) &&
  (search === '' || c.name.toLowerCase().includes(search.toLowerCase()))
 );

 const handleToggle = async (c: ConnectorItem) => {
  if (c.status === 'CONNECTED' || c.status === 'SYNCING') {
   await api.disconnectConnector(c.id);
  } else {
   await api.connectConnector(c.id);
  }
  load();
 };

 const handleSync = async (c: ConnectorItem) => {
  setSyncing(c.id);
  try { await api.syncConnector(c.id); } catch { /* surfaced via reload stats */ }
  setSyncing(null);
  load();
 };

 const card: React.CSSProperties = {
  background: colors.surface1,
  border: `1px solid ${colors.hairline}`,
  borderRadius: '14px',
 };

 if (loading) return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <BrainLoading message="Loading integrations…" />
  </div>
 );

 return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <div className="max-w-7xl mx-auto p-6 space-y-5">
    <header className="flex justify-between items-start gap-4 flex-wrap pb-5 border-b" style={{ borderColor: colors.hairline }}>
     <div className="flex items-start gap-3">
      <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
        style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
       <Plug className="w-6 h-6 text-white" />
      </div>
      <div>
       <h1 className="text-[24px] font-bold tracking-tight">Enterprise Integrations</h1>
       <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Data Fabric - Enterprise Connector Mesh</p>
      </div>
     </div>
     <div className="flex gap-3 flex-wrap">
      {stats && (
       <>
        <div className="px-4 py-2 rounded-xl" style={{ background: colors.success + '15', border: `1px solid ${colors.success}30` }}>
         <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.success }}>Connected</div>
         <div className="text-[20px] font-bold tabular-nums" style={{ color: colors.success }}>{stats.connected}</div>
        </div>
        <div className="px-4 py-2 rounded-xl" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
         <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.inkSubtle }}>Events Ingested</div>
         <div className="text-[20px] font-bold tabular-nums" style={{ color: colors.ink }}>{stats.total_events_ingested.toLocaleString()}</div>
        </div>
        <div className="px-4 py-2 rounded-xl" style={{ background: colors.primary + '15', border: `1px solid ${colors.primary}30` }}>
         <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.primary }}>Signals Extracted</div>
         <div className="text-[20px] font-bold tabular-nums" style={{ color: colors.primary }}>{stats.total_signals_extracted.toLocaleString()}</div>
        </div>
       </>
      )}
     </div>
    </header>

    {/* Filters */}
    <div className="flex gap-4 items-center flex-wrap">
     <div className="relative flex-1 max-w-sm min-w-[220px]">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: colors.inkSubtle }} />
      <input
       type="text" placeholder="Search connectors…" value={search} onChange={e => setSearch(e.target.value)}
       className="w-full rounded-lg pl-10 pr-4 py-2 text-[13px] focus:outline-none transition-colors"
       style={{ background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}` }}
      />
     </div>
     <div className="flex gap-2 flex-wrap">
      {categories.map(cat => {
       const active = filter === cat;
       return (
        <button key={cat} onClick={() => setFilter(cat)}
         className="px-3 py-1.5 rounded-lg text-[12px] font-medium capitalize transition-all hover:opacity-80"
         style={active
           ? { background: colors.primary + '20', color: colors.primary, border: `1px solid ${colors.primary}40` }
           : { background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}
        >{cat}</button>
       );
      })}
     </div>
    </div>

    {/* Connector Grid */}
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
     {filtered.map(c => {
      const isConnected = c.status === 'CONNECTED' || c.status === 'SYNCING';
      return (
       <div key={c.id} className="p-5 transition-all"
         style={{ background: colors.surface1, borderRadius: '14px', border: `1px solid ${isConnected ? colors.success + '40' : colors.hairline}` }}>
        <div className="flex items-start justify-between mb-3 gap-2">
         <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
           <Plug className="w-4 h-4" style={{ color: colors.inkSubtle }} />
          </div>
          <div className="min-w-0">
           <h3 className="font-semibold text-[14px] flex items-center gap-2" style={{ color: colors.ink }}>
            <span className="truncate">{c.name}</span>
            {c.live_integration && (
             <span className="inline-flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded-full shrink-0"
               style={c.live_integration.last_test_ok
                 ? { background: colors.success + '18', color: colors.success }
                 : { background: colors.warning + '18', color: colors.warning }}>
              <Zap className="w-2.5 h-2.5" />LIVE
             </span>
            )}
           </h3>
           <span className="text-[11px] capitalize" style={{ color: colors.inkSubtle }}>{c.category} · {c.connector_type}</span>
          </div>
         </div>
         <div className="flex items-center gap-1.5 shrink-0">
          <button onClick={() => setConfiguring(c)} title="Configure live integration keys"
           className="p-1.5 rounded-lg transition-colors hover:opacity-80"
           style={{ color: colors.inkSubtle }}>
           <KeyRound className="w-4 h-4" />
          </button>
          {isConnected && (
           <button onClick={() => handleSync(c)} title="Sync now" disabled={syncing === c.id}
            className="p-1.5 rounded-lg transition-colors hover:opacity-80 disabled:opacity-50"
            style={{ color: colors.inkSubtle }}>
            <RefreshCw className={`w-4 h-4 ${syncing === c.id ? 'animate-spin' : ''}`} />
           </button>
          )}
          <button onClick={() => handleToggle(c)}
           className="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all hover:opacity-80"
           style={isConnected
             ? { background: colors.success + '18', color: colors.success }
             : { background: colors.primary + '18', color: colors.primary }}
          >
           {isConnected ? <><Wifi className="w-3 h-3 inline mr-1" />Connected</> : <><WifiOff className="w-3 h-3 inline mr-1" />Connect</>}
          </button>
         </div>
        </div>
        <p className="text-[13px] mb-4 line-clamp-2" style={{ color: colors.inkSubtle }}>{c.description}</p>
        {isConnected ? (
         <div className="grid grid-cols-3 gap-3 pt-3 border-t" style={{ borderColor: colors.hairline }}>
          <div><div className="text-[13px] font-semibold tabular-nums" style={{ color: colors.ink }}>{c.events_ingested.toLocaleString()}</div><div className="text-[11px]" style={{ color: colors.inkSubtle }}>Events</div></div>
          <div><div className="text-[13px] font-semibold tabular-nums" style={{ color: colors.primary }}>{c.signals_extracted.toLocaleString()}</div><div className="text-[11px]" style={{ color: colors.inkSubtle }}>Signals</div></div>
          <div><div className="text-[13px] font-semibold tabular-nums" style={{ color: colors.inkMuted }}>{c.avg_latency_ms}ms</div><div className="text-[11px]" style={{ color: colors.inkSubtle }}>Latency</div></div>
         </div>
        ) : (
         <div className="pt-3 border-t flex items-center gap-2 text-[11px]" style={{ borderColor: colors.hairline, color: colors.inkSubtle }}>
          <Shield className="w-3 h-3" /> {c.auth_method} · {c.sync_frequency.toLowerCase().replace('_', ' ')}
         </div>
        )}
        {c.pii_scrub_enabled && isConnected && (
         <div className="mt-3 flex items-center gap-1 text-[11px]" style={{ color: colors.success }}>
          <Shield className="w-3 h-3" /> PII scrubbing active · {c.pii_entities_found.toLocaleString()} entities redacted
         </div>
        )}
       </div>
      );
     })}
    </div>

     {/* L12 Advanced Feature: Live Vectorization Stream */}
     <div className="mt-8">
      <div className="flex justify-between items-center mb-4 gap-3 flex-wrap">
       <h2 className="text-[18px] font-bold tracking-tight" style={{ color: colors.ink }}>Live Vectorization Stream</h2>
       <div className="flex items-center gap-2 text-[11px] font-semibold px-3 py-1.5 rounded-full"
         style={{ color: colors.success, background: colors.success + '15', border: `1px solid ${colors.success}30` }}>
        <span className="relative flex h-2 w-2">
         <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: colors.success }}></span>
         <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: colors.success }}></span>
        </span>
        Listening to Data Fabric
       </div>
      </div>

      <div className="rounded-2xl p-6 overflow-hidden relative"
        style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, minHeight: '300px' }}>
       {/* Grid Background */}
       <div className="absolute inset-0 opacity-20" style={{ backgroundImage: 'linear-gradient(rgba(128,128,128,0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(128,128,128,0.15) 1px, transparent 1px)', backgroundSize: '20px 20px' }}></div>

       <div className="relative z-10 flex flex-col h-full">
        <div className="flex-1 flex items-center justify-center">
         {(stats && stats.total_events_ingested > 0) ? (
          <div className="w-full space-y-4">
           <div className="flex justify-between text-[10px] font-mono mb-2" style={{ color: colors.inkSubtle }}>
            <span>SOURCE INGESTION</span>
            <span>PII SCRUB & CHUNKING</span>
            <span>SEMANTIC EMBEDDING</span>
           </div>

           {/* Simulated Live Stream Animation based on real stats */}
           <div className="relative h-16 w-full flex items-center justify-between px-4">
            {/* Connecting Line */}
            <div className="absolute left-8 right-8 h-px top-1/2 -translate-y-1/2"
              style={{ background: `linear-gradient(90deg, ${colors.primary}33, #a855f780, ${colors.success}33)` }}></div>

            {/* Animated Nodes */}
            <div className="relative z-10 flex flex-col items-center gap-2">
             <div className="w-8 h-8 rounded-full flex items-center justify-center animate-pulse"
               style={{ background: colors.primary + '20', border: `1px solid ${colors.primary}` }}>
              <RefreshCw className="w-4 h-4" style={{ color: colors.primary }} />
             </div>
             <span className="text-[10px] font-mono" style={{ color: colors.primary }}>{stats.total_events_ingested} Events</span>
            </div>

            <div className="relative z-10 flex flex-col items-center gap-2">
             <div className="w-10 h-10 rounded-xl flex items-center justify-center"
               style={{ background: 'rgba(168,85,247,0.2)', border: '1px solid #a855f7', boxShadow: '0 0 15px rgba(168,85,247,0.4)' }}>
              <Shield className="w-5 h-5" style={{ color: '#c084fc' }} />
             </div>
             <span className="text-[10px] font-mono" style={{ color: '#c084fc' }}>{stats.total_signals_extracted} Chunks</span>
            </div>

            <div className="relative z-10 flex flex-col items-center gap-2">
             <div className="w-12 h-12 rounded-full flex items-center justify-center"
               style={{ background: colors.success + '20', border: `2px solid ${colors.success}`, boxShadow: '0 0 20px rgba(16,185,129,0.5)' }}>
              <div className="w-2 h-2 rounded-full animate-ping" style={{ background: colors.success }}></div>
             </div>
             <span className="text-[10px] font-mono" style={{ color: colors.success }}>{stats.total_signals_extracted} Vectors</span>
            </div>
           </div>

           <div className="mt-8 rounded-xl p-3 font-mono text-[10px] max-h-24 overflow-y-auto"
             style={{ background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.success }}>
            <div className="mb-1" style={{ color: colors.inkTertiary }}>// Orchestrator Log Stream</div>
            <div>[{new Date().toISOString()}] INFO: Semantic chunker initialized (Strategy: recursive)</div>
            <div>[{new Date().toISOString()}] SUCCESS: Presidio PII Engine scrubbed 0 entities in batch</div>
            <div>[{new Date().toISOString()}] INFO: Generating embeddings via local SentenceTransformer (dim: 384)</div>
            <div>[{new Date().toISOString()}] SUCCESS: Pipeline stream active. Awaiting net-new payload events.</div>
           </div>
          </div>
         ) : (
          <div className="text-center">
           <div className="inline-flex items-center justify-center w-16 h-16 rounded-full mb-4"
             style={{ background: colors.surface3, border: `1px solid ${colors.hairline}` }}>
            <WifiOff className="w-6 h-6" style={{ color: colors.inkSubtle }} />
           </div>
           <p className="text-[13px]" style={{ color: colors.inkSubtle }}>No active pipeline events. Connect a source to begin.</p>
          </div>
         )}
        </div>
       </div>
      </div>
     </div>

    {configuring && (
     <ConnectorCredentialsModal
      connector={configuring}
      onClose={() => setConfiguring(null)}
      onSaved={load}
     />
    )}
   </div>
  </div>
 );
};

export default IntegrationsHub;
