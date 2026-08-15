/**
 * KAEOS - Domain Pack Marketplace
 * Browse, search, and install department packs.
 * 
 * API: GET /workforce/packs/ + GET /workforce/packs/installations
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainEmpty, BrainError } from '../components/BrainStates';
import {
  Package, Search, Download, Shield, Zap, Bot,
  CheckCircle, ArrowRight, Filter, Loader2, Trash2, XCircle
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

export default function DomainPackMarketplace({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [packs, setPacks] = useState<any[]>([]);
  const [installations, setInstallations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQ, setSearchQ] = useState('');
  const [filterCat, setFilterCat] = useState('all');
  const [selectedPack, setSelectedPack] = useState<any>(null);
  // Install / uninstall state. `busyPack` is the pack id currently mutating.
  const [busyPack, setBusyPack] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = React.useCallback(() => {
    setLoading(true);
    setError(null);
    // The pack catalog is the anchor; a failed installations call still renders.
    Promise.allSettled([
      api.getDomainPacks(),
      api.getDomainPackInstallations(),
    ]).then(([p, inst]) => {
      if (p.status === 'rejected') {
        setError((p.reason as any)?.message || 'Failed to load the marketplace');
        setLoading(false);
        return;
      }
      setPacks(p.value?.packs || []);
      setInstallations(inst.status === 'fulfilled' ? (inst.value?.installations || []) : []);
      setLoading(false);
    });
  }, []);

  useEffect(() => { load(); }, [load]);

  // Only the installations list changes on install/uninstall, so refresh that
  // alone - reloading the whole catalog would blank the grid mid-interaction.
  const refreshInstallations = async () => {
    try {
      const r = await api.getDomainPackInstallations();
      setInstallations(r?.installations || []);
    } catch { /* the optimistic banner already told the user what happened */ }
  };

  const handleInstall = async (pack: any) => {
    setBusyPack(pack.id);
    setActionMsg(null);
    try {
      const r = await api.installDomainPack(pack.id);
      await refreshInstallations();
      setActionMsg({ ok: true, text: r?.message || `${pack.name} installed.` });
    } catch (e: any) {
      setActionMsg({ ok: false, text: `Could not install ${pack.name}: ${e?.message || 'unknown error'}` });
    } finally {
      setBusyPack(null);
    }
  };

  const handleUninstall = async (pack: any) => {
    if (!window.confirm(
      `Remove "${pack.name}" from this workspace? Its capabilities and agent definitions stop being available. You can install it again later.`
    )) return;
    setBusyPack(pack.id);
    setActionMsg(null);
    try {
      const r = await api.uninstallDomainPack(pack.id);
      await refreshInstallations();
      setActionMsg({ ok: true, text: r?.message || `${pack.name} removed.` });
    } catch (e: any) {
      setActionMsg({ ok: false, text: `Could not remove ${pack.name}: ${e?.message || 'unknown error'}` });
    } finally {
      setBusyPack(null);
    }
  };

  if (loading) return <BrainLoading message="Loading marketplace..." />;
  if (error) return <BrainError message={error} onRetry={load} />;

  const categories = ['all', ...Array.from(new Set(packs.map(p => p.category)))];
  const filteredPacks = packs.filter(p => {
    if (filterCat !== 'all' && p.category !== filterCat) return false;
    if (searchQ && !p.name.toLowerCase().includes(searchQ.toLowerCase()) && !(p.description || '').toLowerCase().includes(searchQ.toLowerCase())) return false;
    return true;
  });

  const isInstalled = (packId: string) => installations.some(i => i.domain_pack_id === packId);
  const card = { background: colors.surface1, borderRadius: '14px', border: `1px solid ${colors.hairline}`, padding: '24px' };

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} space-y-6`}>
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[24px] font-bold tracking-tight">Department Marketplace</h1>
            <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
              Pre-built department packs - install, customize, and deploy in minutes.
            </p>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg" style={{ background: colors.primary + '10' }}>
            <Package className="w-4 h-4" style={{ color: colors.primary }} />
            <span className="text-[13px] font-semibold" style={{ color: colors.primary }}>{packs.length} Packs Available</span>
          </div>
        </div>

        {/* Search + Filters */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
            <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
              placeholder="Search packs by name or description..."
              className="w-full pl-9 pr-3 py-2.5 rounded-lg border text-[13px] focus:outline-none focus:ring-1 transition-all"
              style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.ink }} />
          </div>
          <div className="flex items-center gap-1.5">
            <Filter className="w-4 h-4" style={{ color: colors.inkSubtle }} />
            {categories.map(cat => (
              <button key={cat} onClick={() => setFilterCat(cat)}
                className="px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all"
                style={{
                  background: filterCat === cat ? colors.primary + '15' : colors.surface1,
                  color: filterCat === cat ? colors.primary : colors.inkSubtle,
                  border: `1px solid ${filterCat === cat ? colors.primary + '30' : colors.hairline}`,
                }}>
                {humanize(cat)}
              </button>
            ))}
          </div>
        </div>

        {/* Install / uninstall feedback */}
        {actionMsg && (
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-[12px] font-medium"
            style={{
              background: (actionMsg.ok ? colors.success : colors.error) + '15',
              color: actionMsg.ok ? colors.success : colors.error,
            }}>
            {actionMsg.ok ? <CheckCircle className="w-4 h-4 shrink-0" /> : <XCircle className="w-4 h-4 shrink-0" />}
            <span>{actionMsg.text}</span>
            <button onClick={() => setActionMsg(null)} className="ml-auto text-[11px] opacity-70">dismiss</button>
          </div>
        )}

        {/* Grid */}
        {filteredPacks.length === 0 ? (
          <BrainEmpty title="No packs match your search" action="Try a different search term or category" />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {filteredPacks.map(pack => {
              const installed = isInstalled(pack.id);
              return (
                <div key={pack.id} onClick={() => setSelectedPack(selectedPack?.id === pack.id ? null : pack)}
                  className="cursor-pointer transition-all hover:shadow-lg group" style={{
                    ...card,
                    border: selectedPack?.id === pack.id ? `2px solid ${colors.primary}` : `1px solid ${colors.hairline}`,
                  }}>
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="w-14 h-14 rounded-xl flex items-center justify-center text-[28px]"
                        style={{ background: colors.primary + '08' }}>
                        <DomainIcon hint={pack.slug || pack.icon} fallbackHint={pack.name} size={44} />
                      </div>
                      <div>
                        <h3 className="text-[17px] font-bold group-hover:text-primary transition-colors">{pack.name}</h3>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full" style={{ background: colors.primary + '10', color: colors.primary }}>v{pack.version}</span>
                          <span className="text-[11px]" style={{ color: colors.inkSubtle }}>by {pack.author}</span>
                          <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: colors.surface1, color: colors.inkSubtle }}>{humanize(pack.category)}</span>
                        </div>
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-2 shrink-0">
                      {installed ? (
                        <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold" style={{ background: '#22c55e20', color: '#22c55e' }}>
                          <CheckCircle className="w-3 h-3" /> Installed
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold" style={{ background: colors.primary + '15', color: colors.primary }}>
                          <Download className="w-3 h-3" /> Available
                        </span>
                      )}
                      {installed ? (
                        <button onClick={(e) => { e.stopPropagation(); handleUninstall(pack); }}
                          disabled={busyPack === pack.id}
                          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all disabled:opacity-50"
                          style={{ background: colors.error + '15', color: colors.error, border: `1px solid ${colors.error}30` }}>
                          {busyPack === pack.id
                            ? <Loader2 className="w-3 h-3 animate-spin" />
                            : <Trash2 className="w-3 h-3" />}
                          {busyPack === pack.id ? 'Removing' : 'Uninstall'}
                        </button>
                      ) : (
                        <button onClick={(e) => { e.stopPropagation(); handleInstall(pack); }}
                          disabled={busyPack === pack.id}
                          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white transition-all disabled:opacity-50"
                          style={{ background: colors.primary }}>
                          {busyPack === pack.id
                            ? <Loader2 className="w-3 h-3 animate-spin" />
                            : <Download className="w-3 h-3" />}
                          {busyPack === pack.id ? 'Installing' : 'Install'}
                        </button>
                      )}
                    </div>
                  </div>

                  <p className="text-[12px] mb-4 line-clamp-2" style={{ color: colors.inkSubtle }}>
                    {pack.description || pack.long_description}
                  </p>

                  {/* Stats Row */}
                  <div className="flex items-center gap-5 mb-3">
                    <div className="flex items-center gap-1.5 text-[11px]" style={{ color: colors.inkSubtle }}>
                      <Zap className="w-3 h-3" style={{ color: '#f59e0b' }} />
                      <span>{(pack.capabilities || []).length} capabilities</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px]" style={{ color: colors.inkSubtle }}>
                      <Bot className="w-3 h-3" style={{ color: '#8b5cf6' }} />
                      <span>{(pack.agent_definitions || []).length} agents</span>
                    </div>
                  </div>

                  {/* Compliance */}
                  {(pack.compliance_frameworks || []).length > 0 && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {pack.compliance_frameworks.map((f: string) => (
                        <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold"
                          style={{ background: '#8b5cf610', color: '#8b5cf6' }}>
                          <Shield className="w-2.5 h-2.5" /> {f}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Expanded detail */}
                  {selectedPack?.id === pack.id && (
                    <div className="mt-4 pt-4 border-t space-y-3" style={{ borderColor: colors.hairline }}>
                      {/* Capabilities List */}
                      <div>
                        <h4 className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: colors.inkSubtle }}>Capabilities</h4>
                        <div className="grid grid-cols-2 gap-1.5">
                          {(pack.capabilities || []).map((cap: any, i: number) => (
                            <div key={i} className="flex items-center gap-2 text-[12px]">
                              <Zap className="w-3 h-3 flex-shrink-0" style={{ color: '#f59e0b' }} />
                              {typeof cap === 'string' ? humanize(cap) : (cap.name || humanize(cap.slug))}
                            </div>
                          ))}
                        </div>
                      </div>
                      {/* Required Integrations */}
                      {(pack.required_integrations || []).length > 0 && (
                        <div>
                          <h4 className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: colors.inkSubtle }}>Required Integrations</h4>
                          <div className="flex items-center gap-2 flex-wrap">
                            {pack.required_integrations.map((ri: any, i: number) => (
                              <span key={i} className="px-2 py-1 rounded text-[11px]" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                                {humanize(ri.category)} ({(ri.examples || []).join(', ')})
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {/* Deploy Button - carries the chosen pack into the wizard,
                          which skips its own catalog step and starts at Connect. */}
                      <button onClick={(e) => { e.stopPropagation(); navigate('/deploy', { state: { packId: pack.id || pack.slug } }); }}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white w-full justify-center"
                        style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}cc)` }}>
                        {isInstalled(pack.id) ? 'Deploy Again' : 'Deploy This Pack'} <ArrowRight className="w-4 h-4" />
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
