import React, { useState } from 'react';
import { Plus, X, Loader2, Layers, Link2, Shapes, ChevronRight, RefreshCw, Filter } from 'lucide-react';
import { api } from '../../api/client';
import { useTheme } from '../../context/ThemeContext';
import { useEnterprisePanel } from '../../hooks/useEnterprisePanel';
import { EnterpriseNotice } from '../EnterpriseNotice';
import { BrainLoading, BrainEmpty, BrainError } from '../BrainStates';
import { humanize } from '../../lib/format';
import { BASE_TYPES, FIELD_CLASS, mutationTone } from './shared';
import { InlineFeedback } from './InlineFeedback';

/**
 * The Object Explorer's schema-catalog tabs: Value Types, Interfaces, Link
 * Types and Object Sets. Split out of ObjectExplorer.tsx (which keeps the
 * data-plane object browser + detail panel) because these four are all the
 * same "browse the tenant's declared schema, offer a create form" shape -
 * co-located the way ObjectExplorer.tsx itself co-locates its own small
 * components, just in a sibling file so that one page file doesn't grow
 * past a readable size.
 */

export type ObjectTypeOption = { api_name: string; display_name: string };

// ── Value Types ──────────────────────────────────────────────────────────────

type ValueTypeRow = { id: string; api_name: string; display_name: string; base_type: string; constraint: Record<string, any> };

/** Mirrors exactly what kaeos_enterprise.ontology.value_types.validate_value
 * checks - regex OR enum (never both), optionally combined with min/max. */
function describeConstraint(c: Record<string, any> | null | undefined): string {
  if (!c || Object.keys(c).length === 0) return 'No constraint - accepts any value of this type.';
  const parts: string[] = [];
  if (c.regex) parts.push(`must match pattern ${c.regex}`);
  if (c.enum) parts.push(`must be one of ${c.enum.join(', ')}`);
  if (c.min !== undefined) parts.push(`at least ${c.min}`);
  if (c.max !== undefined) parts.push(`at most ${c.max}`);
  return parts.length ? parts.join('; ') : 'No constraint - accepts any value of this type.';
}

function CreateValueTypeForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const { colors } = useTheme();
  const inputStyle = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink };
  const [apiName, setApiName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [baseType, setBaseType] = useState('string');
  const [kind, setKind] = useState<'none' | 'regex' | 'enum' | 'range'>('none');
  const [regex, setRegex] = useState('');
  const [enumValues, setEnumValues] = useState('');
  const [min, setMin] = useState('');
  const [max, setMax] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ notice: boolean; message: string } | null>(null);

  const submit = async () => {
    setBusy(true); setFeedback(null);
    try {
      const constraint: Record<string, any> = {};
      if (kind === 'regex' && regex.trim()) constraint.regex = regex.trim();
      if (kind === 'enum' && enumValues.trim()) constraint.enum = enumValues.split(',').map(s => s.trim()).filter(Boolean);
      if (kind === 'range') {
        if (min !== '') constraint.min = Number(min);
        if (max !== '') constraint.max = Number(max);
      }
      await api.createValueType({ api_name: apiName.trim(), display_name: displayName.trim(), base_type: baseType, constraint });
      onCreated();
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl p-4 space-y-3" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center justify-between">
        <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>New value type</div>
        <button onClick={onCancel} aria-label="Cancel" style={{ color: colors.inkSubtle }}><X className="w-4 h-4" /></button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>API name *</label>
          <input value={apiName} onChange={e => setApiName(e.target.value)} placeholder="priority_level"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Display name *</label>
          <input value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Priority level"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
      </div>
      <div>
        <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Underlying type</label>
        <select value={baseType} onChange={e => setBaseType(e.target.value)} className={FIELD_CLASS} style={inputStyle}>
          {BASE_TYPES.map(t => <option key={t} value={t}>{humanize(t)}</option>)}
        </select>
      </div>
      <div>
        <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Constraint</label>
        <select value={kind} onChange={e => setKind(e.target.value as any)} className={FIELD_CLASS} style={inputStyle}>
          <option value="none">None - accepts any value</option>
          <option value="regex">Pattern (regex)</option>
          <option value="enum">Fixed list of values</option>
          <option value="range">Numeric range</option>
        </select>
      </div>
      {kind === 'regex' && (
        <input value={regex} onChange={e => setRegex(e.target.value)} placeholder="^[A-Z]{3}$"
          className={FIELD_CLASS} style={inputStyle} />
      )}
      {kind === 'enum' && (
        <input value={enumValues} onChange={e => setEnumValues(e.target.value)} placeholder="LOW, MEDIUM, HIGH"
          className={FIELD_CLASS} style={inputStyle} />
      )}
      {kind === 'range' && (
        <div className="grid grid-cols-2 gap-2">
          <input type="number" value={min} onChange={e => setMin(e.target.value)} placeholder="Min"
            className={FIELD_CLASS} style={inputStyle} />
          <input type="number" value={max} onChange={e => setMax(e.target.value)} placeholder="Max"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
      )}
      {feedback && <InlineFeedback {...feedback} />}
      <button onClick={submit} disabled={busy || !apiName.trim() || !displayName.trim()}
        className="w-full px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
        style={{ background: colors.primary, color: colors.canvas }}>
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />} Create
      </button>
    </div>
  );
}

export function ValueTypesPanel() {
  const { colors } = useTheme();
  const list = useEnterprisePanel(() => api.listValueTypes());
  const [showCreate, setShowCreate] = useState(false);
  const rows: ValueTypeRow[] = (list.data as any)?.value_types || [];

  if (list.loading) return <BrainLoading message="Reading value types…" />;
  if (list.notice) return <EnterpriseNotice message={list.notice} />;
  if (list.error) return <BrainError message={list.error} onRetry={list.reload} />;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between gap-3 mb-3 shrink-0">
        <p className="text-[12px] max-w-md" style={{ color: colors.inkSubtle }}>
          Reusable constraints - a pattern, a fixed list, or a numeric range - a PropertyType can point at.
        </p>
        <button onClick={() => setShowCreate(s => !s)}
          className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-2 shrink-0"
          style={{ background: colors.primary + '18', color: colors.primary }}>
          <Plus className="w-3.5 h-3.5" /> New
        </button>
      </div>
      {showCreate && (
        <div className="mb-3 shrink-0">
          <CreateValueTypeForm onCreated={() => { setShowCreate(false); list.reload(); }} onCancel={() => setShowCreate(false)} />
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto rounded-xl" style={{ border: `1px solid ${colors.hairline}` }}>
        {rows.length === 0 ? (
          <div className="p-6"><BrainEmpty title="No value types yet" icon={Shapes} /></div>
        ) : rows.map(r => (
          <div key={r.id} className="px-4 py-3 text-[13px]" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold" style={{ color: colors.ink }}>{r.display_name}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" style={{ background: colors.surface2, color: colors.inkTertiary }}>
                {humanize(r.base_type)}
              </span>
            </div>
            <div className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>{describeConstraint(r.constraint)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Interfaces ───────────────────────────────────────────────────────────────

type InterfaceRow = { api_name: string; display_name: string; required_properties: { api_name: string; base_type?: string }[] };

function CreateInterfaceForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const { colors } = useTheme();
  const inputStyle = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink };
  const [apiName, setApiName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [required, setRequired] = useState<{ api_name: string; base_type: string }[]>([{ api_name: '', base_type: 'string' }]);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ notice: boolean; message: string } | null>(null);

  const updateRow = (i: number, patch: Partial<{ api_name: string; base_type: string }>) =>
    setRequired(rows => rows.map((r, idx) => idx === i ? { ...r, ...patch } : r));

  const submit = async () => {
    setBusy(true); setFeedback(null);
    try {
      const required_properties = required.filter(r => r.api_name.trim())
        .map(r => ({ api_name: r.api_name.trim(), base_type: r.base_type }));
      await api.createInterface({ api_name: apiName.trim(), display_name: displayName.trim(), required_properties });
      onCreated();
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl p-4 space-y-3" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center justify-between">
        <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>New interface</div>
        <button onClick={onCancel} aria-label="Cancel" style={{ color: colors.inkSubtle }}><X className="w-4 h-4" /></button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>API name *</label>
          <input value={apiName} onChange={e => setApiName(e.target.value)} placeholder="Locatable"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Display name *</label>
          <input value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Locatable"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
      </div>
      <div>
        <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Required properties</label>
        <div className="space-y-2">
          {required.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <input value={r.api_name} onChange={e => updateRow(i, { api_name: e.target.value })} placeholder="property api name"
                className={FIELD_CLASS} style={inputStyle} />
              <select value={r.base_type} onChange={e => updateRow(i, { base_type: e.target.value })}
                className="px-2 py-2 rounded-lg text-[13px] outline-none shrink-0" style={inputStyle}>
                {BASE_TYPES.map(t => <option key={t} value={t}>{humanize(t)}</option>)}
              </select>
              <button onClick={() => setRequired(rows => rows.filter((_, idx) => idx !== i))} aria-label="Remove property"
                style={{ color: colors.inkSubtle }}>
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
        <button onClick={() => setRequired(rows => [...rows, { api_name: '', base_type: 'string' }])}
          className="mt-2 text-[12px] font-medium flex items-center gap-1" style={{ color: colors.primary }}>
          <Plus className="w-3.5 h-3.5" /> Add property
        </button>
      </div>
      {feedback && <InlineFeedback {...feedback} />}
      <button onClick={submit} disabled={busy || !apiName.trim() || !displayName.trim()}
        className="w-full px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
        style={{ background: colors.primary, color: colors.canvas }}>
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />} Create
      </button>
    </div>
  );
}

export function InterfacesPanel() {
  const { colors } = useTheme();
  const list = useEnterprisePanel(() => api.listInterfaces());
  const [showCreate, setShowCreate] = useState(false);
  const rows: InterfaceRow[] = (list.data as any)?.interfaces || [];

  if (list.loading) return <BrainLoading message="Reading interfaces…" />;
  if (list.notice) return <EnterpriseNotice message={list.notice} />;
  if (list.error) return <BrainError message={list.error} onRetry={list.reload} />;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between gap-3 mb-3 shrink-0">
        <p className="text-[12px] max-w-md" style={{ color: colors.inkSubtle }}>
          A named, required shape. An ObjectType claims to implement one, then verifies it truly has every required property.
        </p>
        <button onClick={() => setShowCreate(s => !s)}
          className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-2 shrink-0"
          style={{ background: colors.primary + '18', color: colors.primary }}>
          <Plus className="w-3.5 h-3.5" /> New
        </button>
      </div>
      {showCreate && (
        <div className="mb-3 shrink-0">
          <CreateInterfaceForm onCreated={() => { setShowCreate(false); list.reload(); }} onCancel={() => setShowCreate(false)} />
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto rounded-xl" style={{ border: `1px solid ${colors.hairline}` }}>
        {rows.length === 0 ? (
          <div className="p-6"><BrainEmpty title="No interfaces yet" icon={Layers} /></div>
        ) : rows.map(r => (
          <div key={r.api_name} className="px-4 py-3 text-[13px]" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <div className="font-semibold" style={{ color: colors.ink }}>{r.display_name}</div>
            <div className="text-[12px] mt-0.5" style={{ color: colors.inkSubtle }}>
              Requires: {(r.required_properties || []).map(p => p.api_name).join(', ') || 'nothing declared'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Link Types ───────────────────────────────────────────────────────────────

export type LinkTypeRow = {
  api_name: string; source_object_type: string; target_object_type: string;
  relation: string; cardinality: string; forward_name: string; reverse_name: string;
};

const CARDINALITIES = ['one_to_one', 'one_to_many', 'many_to_one', 'many_to_many'];

function CreateLinkTypeForm({ objectTypeOptions, onCreated, onCancel }: {
  objectTypeOptions: ObjectTypeOption[]; onCreated: () => void; onCancel: () => void;
}) {
  const { colors } = useTheme();
  const inputStyle = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink };
  const [apiName, setApiName] = useState('');
  const [sourceType, setSourceType] = useState(objectTypeOptions[0]?.api_name || '');
  const [targetType, setTargetType] = useState(objectTypeOptions[0]?.api_name || '');
  const [relation, setRelation] = useState('');
  const [cardinality, setCardinality] = useState('many_to_many');
  const [forwardName, setForwardName] = useState('');
  const [reverseName, setReverseName] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ notice: boolean; message: string } | null>(null);

  const submit = async () => {
    setBusy(true); setFeedback(null);
    try {
      await api.createLinkType({
        api_name: apiName.trim(), source_object_type: sourceType, target_object_type: targetType,
        relation: relation.trim(), cardinality, forward_name: forwardName.trim(), reverse_name: reverseName.trim(),
      });
      onCreated();
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl p-4 space-y-3" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center justify-between">
        <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>New link type</div>
        <button onClick={onCancel} aria-label="Cancel" style={{ color: colors.inkSubtle }}><X className="w-4 h-4" /></button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>API name *</label>
          <input value={apiName} onChange={e => setApiName(e.target.value)} placeholder="ticket_assigned_to_agent"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Relation *</label>
          <input value={relation} onChange={e => setRelation(e.target.value)} placeholder="ASSIGNED_TO"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Source type *</label>
          <select value={sourceType} onChange={e => setSourceType(e.target.value)} className={FIELD_CLASS} style={inputStyle}>
            {objectTypeOptions.map(t => <option key={t.api_name} value={t.api_name}>{t.display_name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Target type *</label>
          <select value={targetType} onChange={e => setTargetType(e.target.value)} className={FIELD_CLASS} style={inputStyle}>
            {objectTypeOptions.map(t => <option key={t.api_name} value={t.api_name}>{t.display_name}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Cardinality</label>
        <select value={cardinality} onChange={e => setCardinality(e.target.value)} className={FIELD_CLASS} style={inputStyle}>
          {CARDINALITIES.map(c => <option key={c} value={c}>{humanize(c)}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Forward name *</label>
          <input value={forwardName} onChange={e => setForwardName(e.target.value)} placeholder="assigned agent"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
        <div>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Reverse name *</label>
          <input value={reverseName} onChange={e => setReverseName(e.target.value)} placeholder="assigned tickets"
            className={FIELD_CLASS} style={inputStyle} />
        </div>
      </div>
      {feedback && <InlineFeedback {...feedback} />}
      <button onClick={submit}
        disabled={busy || !apiName.trim() || !relation.trim() || !forwardName.trim() || !reverseName.trim() || !sourceType || !targetType}
        className="w-full px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
        style={{ background: colors.primary, color: colors.canvas }}>
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />} Create
      </button>
    </div>
  );
}

export function LinkTypesPanel({ objectTypeOptions }: { objectTypeOptions: ObjectTypeOption[] }) {
  const { colors } = useTheme();
  const list = useEnterprisePanel(() => api.listLinkTypes());
  const [showCreate, setShowCreate] = useState(false);
  const rows: LinkTypeRow[] = (list.data as any)?.link_types || [];

  if (list.loading) return <BrainLoading message="Reading link types…" />;
  if (list.notice) return <EnterpriseNotice message={list.notice} />;
  if (list.error) return <BrainError message={list.error} onRetry={list.reload} />;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between gap-3 mb-3 shrink-0">
        <p className="text-[12px] max-w-md" style={{ color: colors.inkSubtle }}>
          Typed, cardinality-checked relationships between object types - browse an object's linked objects from its own detail panel.
        </p>
        <button onClick={() => setShowCreate(s => !s)} disabled={objectTypeOptions.length === 0}
          className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-2 shrink-0 disabled:opacity-50"
          style={{ background: colors.primary + '18', color: colors.primary }}>
          <Plus className="w-3.5 h-3.5" /> New
        </button>
      </div>
      {showCreate && (
        <div className="mb-3 shrink-0">
          <CreateLinkTypeForm objectTypeOptions={objectTypeOptions}
            onCreated={() => { setShowCreate(false); list.reload(); }} onCancel={() => setShowCreate(false)} />
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto rounded-xl" style={{ border: `1px solid ${colors.hairline}` }}>
        {rows.length === 0 ? (
          <div className="p-6"><BrainEmpty title="No link types yet" icon={Link2} /></div>
        ) : rows.map(r => (
          <div key={r.api_name} className="px-4 py-3 text-[13px]" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold" style={{ color: colors.ink }}>{r.forward_name}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" style={{ background: colors.surface2, color: colors.inkTertiary }}>
                {humanize(r.cardinality)}
              </span>
            </div>
            <div className="text-[12px] mt-0.5 flex items-center gap-1.5" style={{ color: colors.inkSubtle }}>
              {r.source_object_type} <ChevronRight className="w-3 h-3 shrink-0" /> {r.target_object_type}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Object Sets ──────────────────────────────────────────────────────────────

const OBJECT_SET_KINDS = ['static', 'dynamic', 'temporary', 'permanent'];
const FILTER_OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains'];

export function ObjectSetsPanel({ objectTypeOptions }: { objectTypeOptions: ObjectTypeOption[] }) {
  const { colors } = useTheme();
  const inputStyle = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink };
  const [objectType, setObjectType] = useState(objectTypeOptions[0]?.api_name || '');
  const [kind, setKind] = useState('static');
  const [name, setName] = useState('');
  const [staticIds, setStaticIds] = useState('');
  const [field, setField] = useState('');
  const [op, setOp] = useState('eq');
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ notice: boolean; message: string } | null>(null);
  const [created, setCreated] = useState<{ id: string; kind: string; object_type: string } | null>(null);
  const [members, setMembers] = useState<string[] | null>(null);
  const [membersBusy, setMembersBusy] = useState(false);

  const submit = async () => {
    setBusy(true); setFeedback(null); setMembers(null); setCreated(null);
    try {
      const definition: Record<string, any> = kind === 'static'
        ? { ids: staticIds.split(/[,\n]/).map(s => s.trim()).filter(Boolean) }
        : field.trim() ? { filter: { field: field.trim(), op, value: /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value } } : {};
      const res = await api.createObjectSet({ object_type: objectType, kind, definition, name: name.trim() || null });
      setCreated(res);
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusy(false);
    }
  };

  const loadMembers = async () => {
    if (!created) return;
    setMembersBusy(true); setFeedback(null);
    try {
      const res = await api.getObjectSetMembers(created.id);
      setMembers(res.members || []);
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setMembersBusy(false);
    }
  };

  if (objectTypeOptions.length === 0) {
    return <div className="p-6"><BrainEmpty title="Create an object type first" action="Object sets group objects of one type." icon={Filter} /></div>;
  }

  return (
    <div className="flex flex-col h-full min-h-0 overflow-y-auto">
      <p className="text-[12px] max-w-md mb-3 shrink-0" style={{ color: colors.inkSubtle }}>
        A saved handle onto a group of objects - a fixed list, or a live filter resolved fresh every time it is viewed.
      </p>
      <div className="rounded-xl p-4 space-y-3 shrink-0" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Object type</label>
            <select value={objectType} onChange={e => setObjectType(e.target.value)} className={FIELD_CLASS} style={inputStyle}>
              {objectTypeOptions.map(t => <option key={t.api_name} value={t.api_name}>{t.display_name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Kind</label>
            <select value={kind} onChange={e => setKind(e.target.value)} className={FIELD_CLASS} style={inputStyle}>
              {OBJECT_SET_KINDS.map(k => <option key={k} value={k}>{humanize(k)}</option>)}
            </select>
          </div>
        </div>
        {kind === 'permanent' && (
          <div>
            <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Name *</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="at-risk accounts"
              className={FIELD_CLASS} style={inputStyle} />
          </div>
        )}
        {kind === 'static' ? (
          <div>
            <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>
              Object IDs (comma or newline separated) *
            </label>
            <textarea value={staticIds} onChange={e => setStaticIds(e.target.value)} rows={2}
              className={FIELD_CLASS} style={inputStyle} />
          </div>
        ) : (
          <div>
            <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>
              Filter - {humanize(kind)} sets resolve this live, every time it's viewed
            </label>
            <div className="grid grid-cols-3 gap-2">
              <input value={field} onChange={e => setField(e.target.value)} placeholder="field (e.g. status)"
                className={FIELD_CLASS} style={inputStyle} />
              <select value={op} onChange={e => setOp(e.target.value)} className={FIELD_CLASS} style={inputStyle}>
                {FILTER_OPS.map(o => <option key={o} value={o}>{humanize(o)}</option>)}
              </select>
              <input value={value} onChange={e => setValue(e.target.value)} placeholder="value"
                className={FIELD_CLASS} style={inputStyle} />
            </div>
            <p className="text-[11px] mt-1" style={{ color: colors.inkTertiary }}>
              One condition here - combine conditions with and/or through the API directly.
            </p>
          </div>
        )}
        {feedback && <InlineFeedback {...feedback} />}
        <button onClick={submit}
          disabled={busy || !objectType || (kind === 'permanent' && !name.trim()) || (kind === 'static' ? !staticIds.trim() : !field.trim())}
          className="w-full px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
          style={{ background: colors.primary, color: colors.canvas }}>
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />} Create object set
        </button>
      </div>

      {created && (
        <div className="mt-3 rounded-xl p-4 space-y-2 shrink-0" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="text-[12px]" style={{ color: colors.ink }}>
              Created <span className="font-mono">{created.id.slice(0, 12)}</span> - {humanize(created.kind)}, {created.object_type}
            </div>
            <button onClick={loadMembers} disabled={membersBusy}
              className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-2 shrink-0 disabled:opacity-50"
              style={{ background: colors.primary + '18', color: colors.primary }}>
              {membersBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />} View members
            </button>
          </div>
          {members !== null && (
            members.length === 0 ? (
              <div className="text-[12px]" style={{ color: colors.inkTertiary }}>This set has no members right now.</div>
            ) : (
              <div className="text-[12px] space-y-1 max-h-40 overflow-y-auto">
                {members.map(m => <div key={m} className="font-mono" style={{ color: colors.inkMuted }}>{m}</div>)}
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
