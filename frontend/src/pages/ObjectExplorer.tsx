import React, { useEffect, useMemo, useState } from 'react';
import {
  Boxes, Search, Plus, ChevronRight, Lock, Zap, X, Loader2, RefreshCw, Tag, Sparkles,
} from 'lucide-react';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';
import { EnterpriseNotice } from '../components/EnterpriseNotice';
import { useEnterprisePanel } from '../hooks/useEnterprisePanel';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';

/**
 * Object Explorer: the frontend payoff of the Enterprise Ontology (F8-F10) -
 * a generic entity browser instead of one hand-built page per department.
 * Every ObjectType, PropertyType and ActionType shown here is read live from
 * the ontology's own metadata; nothing in this page is a hardcoded list.
 */

const REDACTED = '<redacted>';

type ObjectTypeMeta = {
  api_name: string; display_name: string; description?: string | null;
  binding_mode: 'mapped' | 'native'; implements: string[]; default_markings: string[];
};
type PropertyMeta = { api_name: string; display_name: string; base_type: string; masked: boolean; required: boolean };
type ActionTypeMeta = {
  api_name: string; display_name: string; backing: string;
  skill_id?: string | null; target_object_type?: string | null;
};
type ActionSchema = { type: string; properties: Record<string, { type: string; title: string }>; required: string[] };
type ObjectRow = { pk: string; properties: Record<string, any>; property_versions?: Record<string, number> };

function PropertyValue({ value }: { value: any }) {
  const { colors } = useTheme();
  if (value === REDACTED) {
    return (
      <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: colors.inkTertiary }}>
        <Lock className="w-3 h-3" /> Restricted
      </span>
    );
  }
  if (value === null || value === undefined || value === '') {
    return <span style={{ color: colors.inkTertiary }}>Not set</span>;
  }
  if (typeof value === 'boolean') return <span>{value ? 'Yes' : 'No'}</span>;
  if (Array.isArray(value) || typeof value === 'object') {
    return <span className="font-mono text-[12px] break-all">{JSON.stringify(value)}</span>;
  }
  return <span className="break-words">{String(value)}</span>;
}

/** base_type -> the HTML input best suited to it. Deliberately small - the
 * F8 base types are a closed set (string/integer/float/boolean/timestamp/
 * geopoint/array/json), covered exactly, no speculative extra cases. */
function inputTypeFor(baseType: string): string {
  if (baseType === 'integer' || baseType === 'float') return 'number';
  if (baseType === 'boolean') return 'checkbox';
  if (baseType === 'timestamp') return 'datetime-local';
  return 'text';
}

function coerceForSubmit(baseType: string, raw: any): any {
  if (baseType === 'integer') return raw === '' ? null : parseInt(raw, 10);
  if (baseType === 'float') return raw === '' ? null : parseFloat(raw);
  if (baseType === 'boolean') return !!raw;
  if (baseType === 'array' || baseType === 'json') {
    if (raw === '' || raw === undefined) return baseType === 'array' ? [] : {};
    return JSON.parse(raw); // caller catches - a malformed JSON body must not submit silently
  }
  return raw;
}

const FIELD_CLASS = 'w-full px-3 py-2 rounded-lg text-[13px] outline-none';

// ── Object type sidebar ─────────────────────────────────────────────────────

function TypeSidebar({
  types, selected, onSelect, onSeedDemo,
}: { types: ObjectTypeMeta[]; selected: string | null; onSelect: (t: string) => void; onSeedDemo: () => void }) {
  const { colors } = useTheme();
  return (
    // Below md: a horizontal scrolling strip (own scroller, page never
    // scrolls sideways). At md+: the usual vertical column.
    <div className="w-full md:w-56 shrink-0 md:h-full overflow-x-auto md:overflow-y-auto md:overflow-x-hidden pb-2 md:pb-0 md:pr-2"
      style={{ borderBottom: '1px solid transparent', borderRightColor: colors.hairline }}>
      <div className="hidden md:block text-[11px] font-semibold uppercase tracking-wide mb-2 px-1" style={{ color: colors.inkTertiary }}>
        Object types
      </div>
      <div className="flex md:hidden gap-2 shrink-0">
        {types.length === 0 && (
          <button onClick={onSeedDemo}
            className="whitespace-nowrap px-3 py-2 rounded-lg text-[12px] flex items-center gap-2"
            style={{ background: colors.primary + '12', color: colors.primary }}>
            <Sparkles className="w-3.5 h-3.5 shrink-0" /> Seed demo data
          </button>
        )}
        {types.map(t => (
          <button key={t.api_name} onClick={() => onSelect(t.api_name)}
            className="whitespace-nowrap px-3 py-2 rounded-lg text-[13px] flex items-center gap-2 transition-colors"
            style={{
              background: selected === t.api_name ? colors.navActive : colors.surface1,
              color: selected === t.api_name ? colors.navActiveText : colors.inkMuted,
            }}>
            {t.display_name}
          </button>
        ))}
      </div>
      {types.length === 0 && (
        <button onClick={onSeedDemo}
          className="hidden md:flex w-full text-left px-3 py-2.5 rounded-lg text-[12px] items-center gap-2 mb-2"
          style={{ background: colors.primary + '12', color: colors.primary }}>
          <Sparkles className="w-3.5 h-3.5 shrink-0" /> Seed demo data
        </button>
      )}
      <div className="hidden md:block space-y-0.5">
        {types.map(t => (
          <button key={t.api_name} onClick={() => onSelect(t.api_name)}
            className="w-full text-left px-3 py-2 rounded-lg text-[13px] flex items-center justify-between gap-2 transition-colors"
            style={{
              background: selected === t.api_name ? colors.navActive : 'transparent',
              color: selected === t.api_name ? colors.navActiveText : colors.inkMuted,
            }}>
            <span className="truncate">{t.display_name}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full shrink-0"
              style={{ background: colors.surface2, color: colors.inkTertiary }}>
              {t.binding_mode}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Object list ──────────────────────────────────────────────────────────────

function ObjectList({
  objectType, propertyTypes, selectedPk, onSelectObject, reloadToken,
}: {
  objectType: ObjectTypeMeta; propertyTypes: PropertyMeta[]; selectedPk: string | null;
  onSelectObject: (row: ObjectRow) => void; reloadToken: number;
}) {
  const { colors } = useTheme();
  const [query, setQuery] = useState('');
  const rows = useEnterprisePanel(
    () => api.searchObjects(objectType.api_name, { filter: {}, limit: 200 }),
  );
  // reloadToken forces a fresh fetch after a create/action apply without
  // adding a second effect dependency chain.
  const results: ObjectRow[] = useMemo(() => {
    const all: ObjectRow[] = (rows.data as any)?.objects || [];
    if (!query.trim()) return all;
    const q = query.toLowerCase();
    return all.filter(r => JSON.stringify(r.properties).toLowerCase().includes(q));
  }, [rows.data, query]);
  const firstProps = propertyTypes.slice(0, 3);

  useEffect(() => { rows.reload(); }, [objectType.api_name, reloadToken]); // eslint-disable-line react-hooks/exhaustive-deps

  if (rows.loading) return <BrainLoading message="Reading objects…" />;
  if (rows.notice) return <EnterpriseNotice message={rows.notice} />;
  if (rows.error) return <BrainError message={rows.error} onRetry={rows.reload} />;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 mb-3 shrink-0">
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.inkTertiary }} />
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter loaded objects"
            className="w-full pl-8 pr-3 py-2 rounded-lg text-[13px] outline-none"
            style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
        </div>
        <button onClick={() => rows.reload()} className="p-2 rounded-lg" style={{ color: colors.inkSubtle }} aria-label="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto rounded-xl" style={{ border: `1px solid ${colors.hairline}` }}>
        {results.length === 0 ? (
          <div className="p-6"><BrainEmpty title={`No ${objectType.display_name.toLowerCase()} objects yet`} /></div>
        ) : results.map(r => (
          <button key={r.pk} onClick={() => onSelectObject(r)}
            className="w-full text-left px-4 py-3 flex items-center gap-3 text-[13px] transition-colors"
            style={{
              borderBottom: `1px solid ${colors.hairline}`,
              background: selectedPk === r.pk ? colors.surface2 : 'transparent',
              color: colors.inkMuted,
            }}>
            <div className="flex-1 min-w-0 flex items-center gap-4">
              {firstProps.map(p => (
                <div key={p.api_name} className="min-w-0 truncate">
                  <PropertyValue value={r.properties[p.api_name]} />
                </div>
              ))}
              {firstProps.length === 0 && <span className="font-mono text-[11px]">{r.pk.slice(0, 12)}</span>}
            </div>
            <ChevronRight className="w-4 h-4 shrink-0" style={{ color: colors.inkTertiary }} />
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Create-object form (native types only) ─────────────────────────────────

function CreateObjectForm({
  objectType, propertyTypes, onCreated, onCancel,
}: { objectType: ObjectTypeMeta; propertyTypes: PropertyMeta[]; onCreated: () => void; onCancel: () => void }) {
  const { colors } = useTheme();
  const [values, setValues] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const properties: Record<string, any> = {};
      for (const p of propertyTypes) {
        if (values[p.api_name] === undefined || values[p.api_name] === '') continue;
        properties[p.api_name] = coerceForSubmit(p.base_type, values[p.api_name]);
      }
      await api.createObject(objectType.api_name, { properties });
      onCreated();
    } catch (e: any) {
      setError(e?.message || 'Could not create the object.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl p-4 space-y-3" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-center justify-between">
        <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>New {objectType.display_name.toLowerCase()}</div>
        <button onClick={onCancel} aria-label="Cancel" style={{ color: colors.inkSubtle }}><X className="w-4 h-4" /></button>
      </div>
      {propertyTypes.map(p => (
        <div key={p.api_name}>
          <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>
            {p.display_name}{p.required ? ' *' : ''}
          </label>
          {p.base_type === 'boolean' ? (
            <input type="checkbox" checked={!!values[p.api_name]}
              onChange={e => setValues(v => ({ ...v, [p.api_name]: e.target.checked }))} />
          ) : (p.base_type === 'array' || p.base_type === 'json') ? (
            <textarea value={values[p.api_name] ?? ''} rows={2} placeholder={p.base_type === 'array' ? '[]' : '{}'}
              onChange={e => setValues(v => ({ ...v, [p.api_name]: e.target.value }))}
              className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
          ) : (
            <input type={inputTypeFor(p.base_type)} value={values[p.api_name] ?? ''}
              onChange={e => setValues(v => ({ ...v, [p.api_name]: e.target.value }))}
              className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
          )}
        </div>
      ))}
      {error && <div className="text-[12px]" style={{ color: colors.error }}>{error}</div>}
      <button onClick={submit} disabled={busy}
        className="w-full px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
        style={{ background: colors.primary, color: colors.canvas }}>
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />} Create
      </button>
    </div>
  );
}

// ── Action-apply mini form ───────────────────────────────────────────────────

function ActionCard({ action, targetPk, onApplied }: { action: ActionTypeMeta; targetPk: string; onApplied: () => void }) {
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const [schema, setSchema] = useState<ActionSchema | null>(null);
  const [values, setValues] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);
  // tone reflects what the GOVERNED SKILL actually returned, not just
  // whether the HTTP call succeeded - a call that succeeds but comes back
  // FAILED/BLOCKED must never render as a green success.
  const [result, setResult] = useState<{ tone: 'ok' | 'warn' | 'bad'; message: string } | null>(null);

  const expand = async () => {
    setOpen(o => !o);
    if (!schema) {
      const s = await api.getActionTypeSchema(action.api_name);
      setSchema(s.schema);
    }
  };

  const apply = async () => {
    setBusy(true); setResult(null);
    try {
      const parameters: Record<string, any> = {};
      Object.entries(values).forEach(([k, v]) => { if (v !== '') parameters[k] = v; });
      const res = await api.applyActionType(action.api_name, { parameters, target_pk: targetPk });
      const status = String(res.result?.status || 'unknown');
      const tone = status.startsWith('SUCCESS') ? 'ok' : status.startsWith('FAILED') || status.startsWith('BLOCKED') ? 'bad' : 'warn';
      setResult({ tone, message: `Status: ${humanize(status)}.` });
      onApplied();
    } catch (e: any) {
      setResult({ tone: 'bad', message: e?.message || 'The action was refused.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg" style={{ border: `1px solid ${colors.hairline}` }}>
      <button onClick={expand} className="w-full flex items-center justify-between px-3 py-2 text-[12px] font-medium"
        style={{ color: colors.ink }}>
        <span className="flex items-center gap-2"><Zap className="w-3.5 h-3.5" style={{ color: colors.primary }} />{action.display_name}</span>
        <ChevronRight className="w-3.5 h-3.5 transition-transform" style={{ transform: open ? 'rotate(90deg)' : undefined, color: colors.inkTertiary }} />
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2">
          {!schema ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : Object.entries(schema.properties).map(([key, spec]) => (
            <div key={key}>
              <label className="text-[11px] block mb-1" style={{ color: colors.inkSubtle }}>
                {spec.title}{schema.required.includes(key) ? ' *' : ''}
              </label>
              <input type={spec.type === 'integer' || spec.type === 'number' ? 'number' : 'text'}
                value={values[key] ?? ''} onChange={e => setValues(v => ({ ...v, [key]: e.target.value }))}
                className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
            </div>
          ))}
          {result && (
            <div className="text-[12px]" style={{
              color: result.tone === 'ok' ? colors.success : result.tone === 'bad' ? colors.error : colors.warning,
            }}>{result.message}</div>
          )}
          <button onClick={apply} disabled={busy}
            className="w-full px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
            style={{ background: colors.primary + '18', color: colors.primary }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />} Apply
          </button>
        </div>
      )}
    </div>
  );
}

// ── Object detail panel ──────────────────────────────────────────────────────

function ObjectDetail({
  objectType, object, actionTypes, onClose, onChanged,
}: { objectType: ObjectTypeMeta; object: ObjectRow; actionTypes: ActionTypeMeta[]; onClose: () => void; onChanged: () => void }) {
  const { colors } = useTheme();
  const applicable = actionTypes.filter(a => a.target_object_type === objectType.api_name);

  return (
    <div className="w-full md:w-96 shrink-0 md:h-full overflow-y-auto md:pl-4" style={{ borderLeft: 'none' }}>
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>{objectType.display_name}</div>
          <div className="text-[11px] font-mono" style={{ color: colors.inkTertiary }}>{object.pk}</div>
        </div>
        <button onClick={onClose} aria-label="Close" style={{ color: colors.inkSubtle }}><X className="w-4 h-4" /></button>
      </div>

      {(objectType.default_markings.length > 0) && (
        <div className="flex items-center gap-1.5 flex-wrap mb-3">
          {objectType.default_markings.map(m => (
            <span key={m} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px]"
              style={{ background: colors.warning + '18', color: colors.warning }}>
              <Tag className="w-3 h-3" />{m}
            </span>
          ))}
        </div>
      )}

      <div className="rounded-xl divide-y" style={{ border: `1px solid ${colors.hairline}`, borderColor: colors.hairline }}>
        {Object.entries(object.properties).map(([key, value]) => (
          <div key={key} className="px-3 py-2.5 text-[13px]" style={{ borderColor: colors.hairline }}>
            <div className="text-[11px] font-medium mb-0.5" style={{ color: colors.inkSubtle }}>{humanize(key)}</div>
            <div style={{ color: colors.ink }}><PropertyValue value={value} /></div>
          </div>
        ))}
      </div>

      <div className="mt-4">
        <div className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: colors.inkTertiary }}>
          Available actions
        </div>
        {applicable.length === 0 ? (
          <div className="text-[12px]" style={{ color: colors.inkTertiary }}>
            No ActionTypes target {objectType.display_name.toLowerCase()} yet.
          </div>
        ) : (
          <div className="space-y-2">
            {applicable.map(a => <ActionCard key={a.api_name} action={a} targetPk={object.pk} onApplied={onChanged} />)}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ObjectExplorer() {
  const { colors } = useTheme();
  const status = useEnterprisePanel(() => api.getEnterpriseStatus());
  const objectTypes = useEnterprisePanel(() => api.listObjectTypes());
  const actionTypes = useEnterprisePanel(() => api.listActionTypes());
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [propertyTypes, setPropertyTypes] = useState<PropertyMeta[]>([]);
  const [selectedObject, setSelectedObject] = useState<ObjectRow | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const types: ObjectTypeMeta[] = (objectTypes.data as any)?.object_types || [];
  const actions: ActionTypeMeta[] = (actionTypes.data as any)?.action_types || [];
  const selected = types.find(t => t.api_name === selectedType) || null;

  const selectType = async (apiName: string) => {
    setSelectedType(apiName); setSelectedObject(null); setShowCreate(false);
    try {
      const res = await api.listPropertyTypes(apiName);
      setPropertyTypes(res.properties || []);
    } catch { setPropertyTypes([]); }
  };

  const seedDemoData = async () => {
    setBootstrapError(null);
    try {
      // "demo" seeds SupportTicket + OnboardingCase (with sample objects,
      // ActionTypes and a Marking) AND the Agent dogfood type in one call -
      // idempotent, safe to click again later.
      await api.bootstrapOntologyType('demo');
      await objectTypes.reload();
    } catch (e: any) {
      setBootstrapError(e?.message || 'Could not seed the demo data.');
    }
  };

  if (status.loading || objectTypes.loading) return <BrainLoading message="Reading the ontology…" />;
  if (status.notice) return <div className={PAGE_PAD}><EnterpriseNotice message={status.notice} /></div>;
  if (objectTypes.notice) return <div className={PAGE_PAD}><EnterpriseNotice message={objectTypes.notice} /></div>;
  if (objectTypes.error) return <div className={PAGE_PAD}><BrainError message={objectTypes.error} onRetry={objectTypes.reload} /></div>;

  return (
    <div className="h-full overflow-hidden flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} pb-3 shrink-0`}>
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0" style={{ background: colors.primary + '18' }}>
            <Boxes className="w-5 h-5" style={{ color: colors.primary }} />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-[20px] font-semibold tracking-tight" style={{ color: colors.ink }}>Object Explorer</h1>
            <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
              Every business entity, typed and governed by the Enterprise Ontology - read live, nothing hardcoded.
            </p>
          </div>
          {bootstrapError && <div className="text-[12px]" style={{ color: colors.error }}>{bootstrapError}</div>}
        </div>
      </div>

      {/* Below md: stacked (sidebar strip, then list full-width, detail as a
          full-screen overlay). At md+: the 3-column layout. Same components,
          just re-flowed - no separate mobile page to maintain. */}
      <div className={`${PAGE_PAD} flex-1 overflow-hidden flex flex-col md:flex-row gap-4 min-h-0`}>
        <TypeSidebar types={types} selected={selectedType} onSelect={selectType} onSeedDemo={seedDemoData} />

        {!selected ? (
          <div className="flex-1 flex items-center justify-center">
            <BrainEmpty title="Pick an object type to browse its objects" />
          </div>
        ) : (
          <div className="flex-1 min-w-0 flex flex-col min-h-0">
            <div className="flex items-center justify-between mb-3 shrink-0">
              <div className="min-w-0">
                <div className="text-[14px] font-semibold truncate" style={{ color: colors.ink }}>{selected.display_name}</div>
                {selected.description && <div className="text-[12px] truncate" style={{ color: colors.inkSubtle }}>{selected.description}</div>}
              </div>
              {selected.binding_mode === 'native' ? (
                <button onClick={() => setShowCreate(s => !s)}
                  className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-2 shrink-0"
                  style={{ background: colors.primary + '18', color: colors.primary }}>
                  <Plus className="w-3.5 h-3.5" /> New
                </button>
              ) : (
                <span className="text-[11px] px-2 py-1 rounded-full shrink-0 whitespace-nowrap" style={{ background: colors.surface2, color: colors.inkTertiary }}>
                  Read-only
                </span>
              )}
            </div>
            {showCreate && (
              <div className="mb-3 shrink-0">
                <CreateObjectForm objectType={selected} propertyTypes={propertyTypes}
                  onCreated={() => { setShowCreate(false); setReloadToken(t => t + 1); }}
                  onCancel={() => setShowCreate(false)} />
              </div>
            )}
            <div className="flex-1 min-h-0">
              <ObjectList objectType={selected} propertyTypes={propertyTypes} selectedPk={selectedObject?.pk || null}
                onSelectObject={setSelectedObject} reloadToken={reloadToken} />
            </div>
          </div>
        )}

        {selected && selectedObject && (
          <div className="fixed inset-0 z-40 p-4 overflow-y-auto md:relative md:inset-auto md:z-auto md:p-0"
            style={{ background: colors.canvas, borderLeft: `1px solid ${colors.hairline}` }}>
            <ObjectDetail objectType={selected} object={selectedObject} actionTypes={actions}
              onClose={() => setSelectedObject(null)}
              onChanged={() => setReloadToken(t => t + 1)} />
          </div>
        )}
      </div>
    </div>
  );
}
