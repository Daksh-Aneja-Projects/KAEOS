import React, { useEffect, useState } from 'react';
import { Wrench, Shield, Key, Search } from 'lucide-react';
import { api } from '../api/client';
import type { MCPToolItem } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';

// The API never returns a stored key (only `key_configured`), so the editable
// row carries a LOCAL api_key field: blank means "leave the stored key as is".
type EditableMCPTool = Partial<MCPToolItem> & {
  tool_id: string;
  is_active: boolean;
  rate_limit_per_hour: number;
  api_key: string;
};

export default function MCPToolManager() {
  const { colors } = useTheme();
  const [tools, setTools] = useState<EditableMCPTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');

  const defaultTools = ['crm_bulk_api', 'payment_gateway', 'helpdesk_connector', 'issue_tracker'];

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getMCPTools();
      // Ensure default tools exist in the UI even if not in DB yet
      const merged: EditableMCPTool[] = defaultTools.map(t => {
        const existing = data.find(d => d.tool_id === t);
        return existing
          ? { ...existing, api_key: '' }
          : { tool_id: t, is_active: false, rate_limit_per_hour: 100, api_key: '' };
      });
      setTools(merged);
    } catch (error: any) {
      console.error('Failed to load MCP tools', error);
      setError(error?.message || 'Failed to load MCP tools');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleUpdate = (tool_id: string, field: string, value: any) => {
    const newTools = [...tools];
    const index = newTools.findIndex(t => t.tool_id === tool_id);
    if (index >= 0) {
      newTools[index] = { ...newTools[index], [field]: value };
      setTools(newTools);
    }
  };

  const handleSave = async (tool_id: string) => {
    const tool = tools.find(t => t.tool_id === tool_id);
    if (tool) {
      await api.updateMCPTool({
        tool_id: tool.tool_id,
        is_active: tool.is_active,
        rate_limit_per_hour: tool.rate_limit_per_hour,
        // Blank = keep the stored key; the API never sends it back to us.
        api_key: tool.api_key || null,
      });
      // Optional: show a toast notification here
      await fetchData();
    }
  };

  const filteredTools = tools.filter(t => t.tool_id.toLowerCase().includes(searchTerm.toLowerCase()));

  const inputStyle: React.CSSProperties = {
    background: colors.inputBg, color: colors.ink, border: `1px solid ${colors.hairline}`,
  };

  if (loading) return <BrainLoading message="Loading the MCP Tool Registry…" />;
  if (error) return <BrainError message={error} onRetry={fetchData} />;

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
              <Wrench className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">MCP Tool Registry</h1>
              <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Manage dynamic Model Context Protocol tool bindings and rate limits</p>
            </div>
          </div>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
            <input
              type="text"
              placeholder="Search tools..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-lg text-[13px] outline-none focus:ring-2 w-64"
              style={inputStyle}
            />
          </div>
        </div>

        {filteredTools.length === 0 ? (
          <BrainEmpty title="No tools match your search" action="Clear the search to see all registered tools." icon={Wrench} />
        ) : (
          <div className="grid gap-4">
            {filteredTools.map(tool => (
              <div key={tool.tool_id} className="p-6" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: '14px' }}>
                <div className="flex items-start justify-between mb-6 gap-3">
                  <div>
                    <h3 className="text-[15px] font-bold font-mono px-2 py-1 rounded inline-block"
                      style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairline}` }}>
                      {tool.tool_id}
                    </h3>
                    <div className="flex items-center gap-4 mt-3">
                      <label className="flex items-center gap-2 cursor-pointer select-none">
                        <div className="w-10 h-6 rounded-full transition-colors flex items-center px-1"
                             style={{ background: tool.is_active ? colors.success : colors.surface3 }}
                             onClick={() => handleUpdate(tool.tool_id, 'is_active', !tool.is_active)}>
                          <div className={`w-4 h-4 rounded-full transition-transform ${tool.is_active ? 'translate-x-4' : 'translate-x-0'}`} style={{ background: '#fff' }} />
                        </div>
                        <span className="text-[13px] font-medium" style={{ color: colors.inkMuted }}>{tool.is_active ? 'Active' : 'Disabled'}</span>
                      </label>
                    </div>
                  </div>
                  <button
                    onClick={() => handleSave(tool.tool_id)}
                    className="px-4 py-2 rounded-lg text-[13px] font-semibold transition-all hover:opacity-90 shrink-0"
                    style={{ background: colors.primary, color: '#fff' }}
                  >
                    Save Changes
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 p-4 rounded-xl" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
                  <div>
                    <label className="text-[13px] font-medium mb-2 flex items-center gap-2" style={{ color: colors.inkMuted }}>
                      <Shield className="w-4 h-4" style={{ color: colors.inkSubtle }} /> Rate Limit (per hour)
                    </label>
                    <input
                      type="number"
                      value={tool.rate_limit_per_hour}
                      onChange={(e) => handleUpdate(tool.tool_id, 'rate_limit_per_hour', parseInt(e.target.value) || 0)}
                      className="w-full px-4 py-2 rounded-lg outline-none text-[13px] focus:ring-2"
                      style={{ background: colors.surface1, color: colors.ink, border: `1px solid ${colors.hairline}` }}
                    />
                    <p className="text-[12px] mt-2" style={{ color: colors.inkSubtle }}>Hard cap to prevent excessive API consumption by agents.</p>
                  </div>

                  <div>
                    <label className="text-[13px] font-medium mb-2 flex items-center gap-2" style={{ color: colors.inkMuted }}>
                      <Key className="w-4 h-4" style={{ color: colors.inkSubtle }} /> Provider API Key
                    </label>
                    <input
                      type="password"
                      value={tool.api_key}
                      onChange={(e) => handleUpdate(tool.tool_id, 'api_key', e.target.value)}
                      placeholder={tool.key_configured ? 'Key configured - leave blank to keep it' : 'Encrypted at rest...'}
                      className="w-full px-4 py-2 rounded-lg outline-none font-mono text-[13px] focus:ring-2"
                      style={{ background: colors.surface1, color: colors.ink, border: `1px solid ${colors.hairline}` }}
                    />
                    <p className="text-[12px] mt-2" style={{ color: colors.inkSubtle }}>Required for tool execution. Never exposed to agents directly.</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
