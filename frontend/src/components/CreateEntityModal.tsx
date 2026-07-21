import React, { useState } from 'react';
import { Loader2, Plus, X } from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';

/**
 * Config-driven create form for the domain entities exposed by the new
 * POST /{domain}/{entityPath} endpoints. One component serves all 7 domains:
 * the caller passes a field list, the modal renders inputs, validates
 * required fields, POSTs, and reports the result back.
 */

export interface CreateField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'date' | 'textarea' | 'select';
  required?: boolean;
  options?: (string | { value: string; label: string })[];  // for select
  placeholder?: string;
  defaultValue?: string | number;
}

interface Props {
  open: boolean;
  title: string;             // e.g. "New Ticket"
  domain: string;            // e.g. "support"
  entityPath: string;        // e.g. "tickets"
  fields: CreateField[];
  onClose: () => void;
  onCreated: (msg: string) => void;  // refresh callback
}

const CreateEntityModal: React.FC<Props> = ({ open, title, domain, entityPath, fields, onClose, onCreated }) => {
  const { colors } = useTheme();
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  if (!open) return null;

  const val = (f: CreateField) => values[f.key] ?? String(f.defaultValue ?? '');
  const set = (k: string, v: string) => setValues(prev => ({ ...prev, [k]: v }));

  const submit = async () => {
    for (const f of fields) {
      if (f.required && !val(f).trim()) {
        setError(`${f.label} is required`);
        return;
      }
    }
    setBusy(true); setError('');
    const body: Record<string, any> = {};
    for (const f of fields) {
      const raw = val(f).trim();
      if (raw === '') continue;
      body[f.key] = f.type === 'number' ? Number(raw) : raw;
    }
    try {
      await api.createDomainEntity(domain, entityPath, body);
      setValues({});
      onCreated(`${title.replace(/^New /, '')} created`);
      onClose();
    } catch (e: any) {
      setError(e?.message || 'Create failed');
    } finally {
      setBusy(false);
    }
  };

  const inputStyle = {
    background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink,
  } as React.CSSProperties;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.55)' }}
      onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl p-5 space-y-4 max-h-[85vh] overflow-y-auto"
        style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-bold" style={{ color: colors.ink }}>{title}</h2>
          <button onClick={onClose} className="p-1 rounded" style={{ color: colors.inkSubtle }}>
            <X className="w-4 h-4" />
          </button>
        </div>

        {fields.map(f => (
          <div key={f.key}>
            <label className="text-[11px] font-semibold block mb-1" style={{ color: colors.inkSubtle }}>
              {f.label}{f.required && <span style={{ color: '#ef4444' }}> *</span>}
            </label>
            {f.type === 'textarea' ? (
              <textarea value={val(f)} onChange={e => set(f.key, e.target.value)} rows={3}
                placeholder={f.placeholder}
                className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none resize-none" style={inputStyle} />
            ) : f.type === 'select' ? (
              <select value={val(f)} onChange={e => set(f.key, e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle}>
                <option value="">Select…</option>
                {(f.options || []).map(o => {
                  const opt = typeof o === 'string' ? { value: o, label: o.replace(/_/g, ' ') } : o;
                  return <option key={opt.value} value={opt.value}>{opt.label}</option>;
                })}
              </select>
            ) : (
              <input type={f.type} value={val(f)} onChange={e => set(f.key, e.target.value)}
                placeholder={f.placeholder}
                className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle} />
            )}
          </div>
        ))}

        {error && <p className="text-[11px] font-medium" style={{ color: '#ef4444' }}>{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-2 rounded-lg text-[12px] font-semibold"
            style={{ background: 'transparent', color: colors.inkSubtle }}>Cancel</button>
          <button onClick={submit} disabled={busy}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold disabled:opacity-50 text-white"
            style={{ background: colors.primary }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
            Create
          </button>
        </div>
      </div>
    </div>
  );
};

export default CreateEntityModal;
