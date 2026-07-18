import React, { useEffect, useState } from 'react';
import type { MarketplaceItem } from '../api/client';
import { api } from '../api/client';
import { Store, Star, Download, Shield, Plus, X } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';

const Marketplace = () => {
 const { colors } = useTheme();
 const [templates, setTemplates] = useState<MarketplaceItem[]>([]);
 const [categories, setCategories] = useState<string[]>([]);
 const [filter, setFilter] = useState('all');
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [isModalOpen, setIsModalOpen] = useState(false);
 const [formData, setFormData] = useState({ name: '', category: 'Sales', description: '', tags: '' });

 const loadData = () => {
  setError(null);
  api.getMarketplace().then(d => { setTemplates(d.templates); setCategories(d.categories); setLoading(false); }).catch((e: any) => { setError(e?.message || 'Failed to load the marketplace'); setLoading(false); });
 };

 useEffect(() => {
  loadData();
 }, []);

 const handleSubmit = async (e: React.FormEvent) => {
   e.preventDefault();
   try {
     await api.createMarketplaceTemplate({
       ...formData,
       author: localStorage.getItem('username') || 'Developer',
       tags: formData.tags.split(',').map(t => t.trim()).filter(t => t)
     });
     setIsModalOpen(false);
     setFormData({ name: '', category: 'Sales', description: '', tags: '' });
     setLoading(true);
     loadData();
   } catch (err) {
     console.error(err);
   }
 };

 const filtered = filter === 'all' ? templates : templates.filter(t => t.category === filter);

 const card: React.CSSProperties = {
  background: colors.surface1, borderRadius: '14px', border: `1px solid ${colors.hairline}`,
 };

 const inputStyle: React.CSSProperties = {
  background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}`,
 };

 if (loading) return <BrainLoading message="Loading the Skills Marketplace…" />;
 if (error) return <BrainError message={error} onRetry={() => { setLoading(true); loadData(); }} />;

 return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <div className="max-w-7xl mx-auto p-6 space-y-5">
    {/* Header */}
    <div className="flex items-start justify-between gap-4 flex-wrap">
     <div className="flex items-start gap-3">
      <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
        style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
       <Store className="w-6 h-6 text-white" />
      </div>
      <div>
       <h1 className="text-[24px] font-bold tracking-tight">Skills Marketplace</h1>
       <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Knowledge templates and agent integrations</p>
      </div>
     </div>
     <button onClick={() => setIsModalOpen(true)}
       className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold transition-all hover:opacity-90"
       style={{ background: colors.primary, color: '#fff' }}>
      <Plus className="w-4 h-4" /> Publish Template
     </button>
    </div>

    {/* Category filters */}
    <div className="flex flex-wrap gap-2">
     <button onClick={() => setFilter('all')}
       className="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all"
       style={filter === 'all'
         ? { background: colors.primary + '1f', color: colors.primary, border: `1px solid ${colors.primary}40` }
         : { background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
      All
     </button>
     {categories.map(c => (
      <button key={c} onClick={() => setFilter(c)}
        className="px-3 py-1.5 rounded-lg text-[12px] font-medium capitalize transition-all"
        style={filter === c
          ? { background: colors.primary + '1f', color: colors.primary, border: `1px solid ${colors.primary}40` }
          : { background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
       {c}
      </button>
     ))}
    </div>

    {filtered.length === 0 ? (
     <BrainEmpty title="No templates here yet" action="Publish a template to share it with your team." icon={Store} />
    ) : (
     <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {filtered.map(t => (
       <div key={t.id} className="p-6 transition-colors" style={card}>
        <div className="flex justify-between items-start mb-3 gap-3">
         <div className="min-w-0">
          <h3 className="font-semibold text-[16px] truncate" style={{ color: colors.ink }}>{t.name}</h3>
          <span className="text-[12px]" style={{ color: colors.inkSubtle }}>{t.author} · v{t.version}</span>
         </div>
         {t.certified && (
          <span className="px-2 py-0.5 text-[11px] rounded-full flex items-center gap-1 shrink-0"
            style={{ background: colors.success + '1f', color: colors.success, border: `1px solid ${colors.success}40` }}>
           <Shield className="w-3 h-3" />Certified
          </span>
         )}
        </div>
        <p className="text-[13px] mb-4" style={{ color: colors.inkSubtle }}>{t.description}</p>
        <div className="flex items-center gap-4 text-[12px] mb-4" style={{ color: colors.inkSubtle }}>
         <span className="flex items-center gap-1"><Star className="w-3 h-3" style={{ color: colors.warning }} />{t.rating}</span>
         <span className="flex items-center gap-1"><Download className="w-3 h-3" />{t.installs.toLocaleString()}</span>
         <span>{t.rules_count} rules · {t.skills_count} skills</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
         {t.tags.map(tag => (
          <span key={tag} className="px-2 py-0.5 text-[11px] rounded"
            style={{ background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>{tag}</span>
         ))}
         {t.compliance_frameworks.map(cf => (
          <span key={cf} className="px-2 py-0.5 text-[11px] rounded"
            style={{ background: colors.primary + '1f', color: colors.primary, border: `1px solid ${colors.primary}40` }}>{cf}</span>
         ))}
        </div>
       </div>
      ))}
     </div>
    )}

    {isModalOpen && (
     <div className="fixed inset-0 flex items-center justify-center z-50 p-4" style={{ background: 'rgba(0,0,0,0.55)' }}>
      <div className="rounded-2xl p-6 w-full max-w-md" style={{ background: colors.surface1, border: `1px solid ${colors.hairlineStrong}` }}>
       <div className="flex justify-between items-center mb-4">
        <h2 className="text-[18px] font-semibold" style={{ color: colors.ink }}>Publish New Template</h2>
        <button onClick={() => setIsModalOpen(false)} className="transition-opacity hover:opacity-70" style={{ color: colors.inkSubtle }}><X className="w-5 h-5" /></button>
       </div>
       <form onSubmit={handleSubmit} className="space-y-4">
        <div>
         <label className="block text-[13px] font-medium mb-1" style={{ color: colors.inkMuted }}>Name</label>
         <input required type="text" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})}
           className="w-full px-3 py-2 rounded-lg outline-none text-[13px] focus:ring-2" style={inputStyle} />
        </div>
        <div>
         <label className="block text-[13px] font-medium mb-1" style={{ color: colors.inkMuted }}>Category</label>
         <select value={formData.category} onChange={e => setFormData({...formData, category: e.target.value})}
           className="w-full px-3 py-2 rounded-lg outline-none text-[13px] focus:ring-2" style={inputStyle}>
          <option>Sales</option><option>Support</option><option>Engineering</option><option>HR</option><option>Finance</option>
         </select>
        </div>
        <div>
         <label className="block text-[13px] font-medium mb-1" style={{ color: colors.inkMuted }}>Description</label>
         <textarea required value={formData.description} onChange={e => setFormData({...formData, description: e.target.value})}
           className="w-full px-3 py-2 rounded-lg outline-none text-[13px] focus:ring-2" style={inputStyle} rows={3} />
        </div>
        <div>
         <label className="block text-[13px] font-medium mb-1" style={{ color: colors.inkMuted }}>Tags (comma separated)</label>
         <input type="text" value={formData.tags} onChange={e => setFormData({...formData, tags: e.target.value})}
           className="w-full px-3 py-2 rounded-lg outline-none text-[13px] focus:ring-2" style={inputStyle} placeholder="e.g. negotiation, automated" />
        </div>
        <div className="flex justify-end gap-2 mt-6">
         <button type="button" onClick={() => setIsModalOpen(false)}
           className="px-4 py-2 text-[13px] font-medium rounded-lg transition-all hover:opacity-80"
           style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>Cancel</button>
         <button type="submit"
           className="px-4 py-2 text-[13px] font-semibold rounded-lg transition-all hover:opacity-90"
           style={{ background: colors.primary, color: '#fff' }}>Publish</button>
        </div>
       </form>
      </div>
     </div>
    )}
   </div>
  </div>
 );
};

export default Marketplace;
