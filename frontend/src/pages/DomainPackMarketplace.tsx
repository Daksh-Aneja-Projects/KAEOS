/**
 * KAEOS - Domain Pack Marketplace
 * Browse, search, and install department packs.
 * 
 * API: GET /workforce/packs/ + GET /workforce/packs/installations
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading, BrainEmpty } from '../components/BrainStates';
import {
  Package, Search, Star, Download, Shield, Zap, Bot,
  CheckCircle, ArrowRight, Filter, TrendingUp
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';

export default function DomainPackMarketplace({ domain }: { domain?: string }) {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [packs, setPacks] = useState<any[]>([]);
  const [installations, setInstallations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [filterCat, setFilterCat] = useState('all');
  const [selectedPack, setSelectedPack] = useState<any>(null);

  useEffect(() => {
    Promise.all([
      api.getDomainPacks().catch(() => ({ packs: [] })),
      api.getDomainPackInstallations().catch(() => ({ installations: [] })),
    ]).then(([p, inst]) => {
      setPacks(p?.packs || []);
      setInstallations(inst?.installations || []);
      setLoading(false);
    });
  }, []);

  if (loading) return <BrainLoading message="Loading marketplace..." />;

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
      <div className="max-w-7xl mx-auto p-6 space-y-6">
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
                className="px-3 py-1.5 rounded-lg text-[11px] font-medium capitalize transition-all"
                style={{
                  background: filterCat === cat ? colors.primary + '15' : colors.surface1,
                  color: filterCat === cat ? colors.primary : colors.inkSubtle,
                  border: `1px solid ${filterCat === cat ? colors.primary + '30' : colors.hairline}`,
                }}>
                {cat}
              </button>
            ))}
          </div>
        </div>

        {/* Grid */}
        {filteredPacks.length === 0 ? (
          <BrainEmpty title="No packs match your search" action="Try a different search term or category" />
        ) : (
          <div className="grid grid-cols-2 gap-5">
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
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full" style={{ background: colors.primary + '10', color: colors.primary }}>v{pack.version}</span>
                          <span className="text-[10px]" style={{ color: colors.inkSubtle }}>by {pack.author}</span>
                          <span className="text-[10px] capitalize px-2 py-0.5 rounded-full" style={{ background: colors.surface1, color: colors.inkSubtle }}>{pack.category}</span>
                        </div>
                      </div>
                    </div>
                    {installed ? (
                      <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold" style={{ background: '#22c55e20', color: '#22c55e' }}>
                        <CheckCircle className="w-3 h-3" /> Installed
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold" style={{ background: colors.primary + '15', color: colors.primary }}>
                        <Download className="w-3 h-3" /> Available
                      </span>
                    )}
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
                    {pack.rating > 0 && (
                      <div className="flex items-center gap-1 text-[11px]" style={{ color: '#f59e0b' }}>
                        <Star className="w-3 h-3 fill-current" /> {pack.rating.toFixed(1)}
                      </div>
                    )}
                    {(pack.install_count || 0) > 0 && (
                      <div className="flex items-center gap-1 text-[11px]" style={{ color: colors.inkSubtle }}>
                        <TrendingUp className="w-3 h-3" /> {pack.install_count} installs
                      </div>
                    )}
                  </div>

                  {/* Compliance */}
                  {(pack.compliance_frameworks || []).length > 0 && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {pack.compliance_frameworks.map((f: string) => (
                        <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold"
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
                              {typeof cap === 'string' ? cap : cap.name}
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
                              <span key={i} className="px-2 py-1 rounded text-[11px] capitalize" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                                {ri.category} ({(ri.examples || []).join(', ')})
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {/* Deploy Button — carries the chosen pack into the wizard,
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
