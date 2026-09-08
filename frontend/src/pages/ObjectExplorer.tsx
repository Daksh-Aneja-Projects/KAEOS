import React, { useEffect, useMemo, useState } from 'react';
import {
  Boxes, Search, Plus, ChevronRight, Lock, Zap, X, Loader2, RefreshCw, Tag, Sparkles,
  Shapes, Layers, Link2, Filter, GitBranch, ShieldCheck, Pencil, Check,
} from 'lucide-react';
import { api, ApiError } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';
import { EnterpriseNotice } from '../components/EnterpriseNotice';
import { useEnterprisePanel } from '../hooks/useEnterprisePanel';
import { humanize, formatDateTime } from '../lib/format';
import { PAGE_PAD, PAGE_PAD_X } from '../lib/layout';
import { FIELD_CLASS, mutationTone } from '../components/ontology/shared';
import { InlineFeedback } from '../components/ontology/InlineFeedback';
import {
  ValueTypesPanel, InterfacesPanel, LinkTypesPanel, ObjectSetsPanel,
  type ObjectTypeOption, type LinkTypeRow,
} from '../components/ontology/SchemaPanels';

/**
 * Object Explorer: the frontend payoff of the Enterprise Ontology (F8-F13) -
 * a generic entity browser instead of one hand-built page per department.
 * Every ObjectType, PropertyType and ActionType shown here is read live from
 * the ontology's own metadata; nothing in this page is a hardcoded list.
 *
 * "Objects" is the original F13 data-plane browser (browse/create objects,
 * apply ActionTypes). The four sibling tabs (Value types / Interfaces /
 * Link types / Object sets) are the schema-authoring surfaces added on top,
 * plus in-place object editing, an "implements/verify conformance" strip and
 * dataset-branch history on the object-type header, and a "linked objects"
 * section on the object detail panel.
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

// ── Editable property row (object detail) ───────────────────────────────────

/**
 * One property row in the object detail panel, with an inline edit mode.
 * Never offers to edit a masked property whose real value came back
 * REDACTED (this caller cannot see it, so cannot safely overwrite it), and
 * never edits a mapped ObjectType (the ontology write path is native-only -
 * see object_store.update_object). Submits `expected_versions` sourced from
 * this object's own `property_versions`, and on a 409 (a concurrent edit
 * bumped the same property since this object was read) shows a plain
 * "refresh and retry" message rather than silently overwriting.
 */
function EditablePropertyRow({
  objectType, object, prop, value, onUpdated,
}: {
  objectType: ObjectTypeMeta; object: ObjectRow; prop: PropertyMeta | undefined; value: any;
  onUpdated: (updated: ObjectRow) => void;
}) {
  const { colors } = useTheme();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<any>(value);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [feedback, setFeedback] = useState<{ notice: boolean; message: string } | null>(null);

  const canEdit = objectType.binding_mode === 'native' && value !== REDACTED && !!prop;

  const startEdit = () => { setDraft(value); setEditing(true); setFeedback(null); setConflict(false); };

  const refreshObject = async () => {
    try {
      const fresh = await api.getObject(objectType.api_name, object.pk);
      onUpdated(fresh);
      setEditing(false); setConflict(false); setFeedback(null);
    } catch (e: any) {
      setFeedback(mutationTone(e));
    }
  };

  const save = async () => {
    if (!prop) return;
    setBusy(true); setFeedback(null); setConflict(false);
    try {
      const coerced = coerceForSubmit(prop.base_type, draft);
      const expectedVersion = object.property_versions?.[prop.api_name] ?? 0;
      const updated = await api.updateObject(objectType.api_name, object.pk, {
        changes: { [prop.api_name]: coerced },
        expected_versions: { [prop.api_name]: expectedVersion },
      });
      onUpdated(updated);
      setEditing(false);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setConflict(true);
        setFeedback({
          notice: false,
          message: `${prop.display_name} changed since this object was loaded - refresh to see the latest value before editing again.`,
        });
      } else {
        setFeedback(mutationTone(e));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="px-3 py-2.5 text-[13px]" style={{ borderColor: colors.hairline }}>
      <div className="flex items-center justify-between mb-0.5">
        <div className="text-[11px] font-medium" style={{ color: colors.inkSubtle }}>
          {prop?.display_name || humanize(prop?.api_name)}
        </div>
        {canEdit && !editing && (
          <button onClick={startEdit} aria-label={`Edit ${prop?.display_name || ''}`} style={{ color: colors.inkTertiary }}>
            <Pencil className="w-3 h-3" />
          </button>
        )}
      </div>
      {editing && prop ? (
        <div className="space-y-1.5">
          {prop.base_type === 'boolean' ? (
            <input type="checkbox" checked={!!draft} onChange={e => setDraft(e.target.checked)} />
          ) : (prop.base_type === 'array' || prop.base_type === 'json') ? (
            <textarea value={draft ?? ''} rows={2} onChange={e => setDraft(e.target.value)}
              className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
          ) : (
            <input type={inputTypeFor(prop.base_type)} value={draft ?? ''} onChange={e => setDraft(e.target.value)}
              className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
          )}
          {conflict && feedback ? (
            <div className="flex items-start gap-1.5 text-[12px]" style={{ color: colors.warning }}>
              <RefreshCw className="w-3.5 h-3.5 shrink-0 mt-0.5" /> <span>{feedback.message}</span>
            </div>
          ) : feedback && <InlineFeedback {...feedback} />}
          <div className="flex items-center gap-2">
            {conflict ? (
              <button onClick={refreshObject}
                className="px-2.5 py-1 rounded-lg text-[11px] font-semibold flex items-center gap-1.5"
                style={{ background: colors.warning + '18', color: colors.warning }}>
                <RefreshCw className="w-3 h-3" /> Refresh this object
              </button>
            ) : (
              <button onClick={save} disabled={busy}
                className="px-2.5 py-1 rounded-lg text-[11px] font-semibold flex items-center gap-1.5 disabled:opacity-50"
                style={{ background: colors.primary, color: colors.canvas }}>
                {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} Save
              </button>
            )}
            <button onClick={() => setEditing(false)} className="px-2.5 py-1 rounded-lg text-[11px]" style={{ color: colors.inkSubtle }}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div style={{ color: colors.ink }}><PropertyValue value={value} /></div>
      )}
    </div>
  );
}

// ── Linked objects (object detail) ───────────────────────────────────────────

/**
 * Traverses every LinkType touching this ObjectType (as source -> forward,
 * as target -> reverse) for this specific object's pk, and offers a small
 * form to create a new forward link. Uses GraphService's real traversal
 * (link_types.traverse) - see kaeos_enterprise/ontology/link_types.py.
 */
function LinkedObjectsSection({
  objectType, object, linkTypes,
}: { objectType: ObjectTypeMeta; object: ObjectRow; linkTypes: LinkTypeRow[] }) {
  const { colors } = useTheme();
  const relevant = useMemo(() => [
    ...linkTypes.filter(l => l.source_object_type === objectType.api_name)
      .map(l => ({ linkType: l, direction: 'forward' as const, label: l.forward_name })),
    ...linkTypes.filter(l => l.target_object_type === objectType.api_name)
      .map(l => ({ linkType: l, direction: 'reverse' as const, label: l.reverse_name })),
  ], [linkTypes, objectType.api_name]);

  const [openKey, setOpenKey] = useState<string | null>(null);
  const [related, setRelated] = useState<Record<string, any>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ notice: boolean; message: string } | null>(null);
  const [targetIdByLink, setTargetIdByLink] = useState<Record<string, string>>({});

  const keyFor = (apiName: string, direction: string) => `${apiName}:${direction}`;

  const loadRelated = async (apiName: string, direction: 'forward' | 'reverse') => {
    const key = keyFor(apiName, direction);
    setBusyKey(key); setFeedback(null);
    try {
      const res = await api.getLinkInstances(apiName, object.pk, direction);
      setRelated(r => ({ ...r, [key]: res.related }));
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusyKey(null);
    }
  };

  const createLink = async (apiName: string) => {
    const targetId = (targetIdByLink[apiName] || '').trim();
    if (!targetId) return;
    setBusyKey(apiName); setFeedback(null);
    try {
      await api.createLinkInstance(apiName, { source_id: object.pk, target_id: targetId });
      setTargetIdByLink(v => ({ ...v, [apiName]: '' }));
      await loadRelated(apiName, 'forward');
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusyKey(null);
    }
  };

  if (relevant.length === 0) return null;

  return (
    <div className="mt-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: colors.inkTertiary }}>
        Linked objects
      </div>
      <div className="space-y-2">
        {relevant.map(({ linkType, direction, label }) => {
          const key = keyFor(linkType.api_name, direction);
          const isOpen = openKey === key;
          const raw = related[key];
          const list: any[] = raw == null ? [] : Array.isArray(raw) ? raw : [raw];
          return (
            <div key={key} className="rounded-lg" style={{ border: `1px solid ${colors.hairline}` }}>
              <button
                onClick={() => {
                  const willOpen = openKey !== key;
                  setOpenKey(willOpen ? key : null);
                  if (willOpen && !(key in related)) loadRelated(linkType.api_name, direction);
                }}
                className="w-full flex items-center justify-between px-3 py-2 text-[12px] font-medium" style={{ color: colors.ink }}>
                <span className="flex items-center gap-2"><Link2 className="w-3.5 h-3.5" style={{ color: colors.primary }} />{humanize(label)}</span>
                <ChevronRight className="w-3.5 h-3.5 transition-transform" style={{ transform: isOpen ? 'rotate(90deg)' : undefined, color: colors.inkTertiary }} />
              </button>
              {isOpen && (
                <div className="px-3 pb-3 space-y-2">
                  <button onClick={() => loadRelated(linkType.api_name, direction)} disabled={busyKey === key}
                    className="text-[11px] font-medium flex items-center gap-1.5 disabled:opacity-50" style={{ color: colors.primary }}>
                    {busyKey === key ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />} Refresh
                  </button>
                  {list.length === 0 ? (
                    <div className="text-[12px]" style={{ color: colors.inkTertiary }}>Nothing linked yet.</div>
                  ) : list.map((node, i) => (
                    <div key={node?.id ?? i} className="rounded-lg px-2.5 py-2 text-[12px]" style={{ background: colors.surface2 }}>
                      <div className="font-mono text-[11px]" style={{ color: colors.inkSubtle }}>{node?.id ?? JSON.stringify(node)}</div>
                      {node && typeof node === 'object' && Object.entries(node)
                        .filter(([k]) => k !== 'id' && k !== 'tenant_id')
                        .map(([k, v]) => (
                          <div key={k} style={{ color: colors.ink }}>{humanize(k)}: <PropertyValue value={v} /></div>
                        ))}
                    </div>
                  ))}
                  {direction === 'forward' && (
                    <div className="flex items-center gap-2 pt-1">
                      <input value={targetIdByLink[linkType.api_name] || ''} placeholder={`${linkType.target_object_type} id to link`}
                        onChange={e => setTargetIdByLink(v => ({ ...v, [linkType.api_name]: e.target.value }))}
                        className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
                      <button onClick={() => createLink(linkType.api_name)} disabled={busyKey === linkType.api_name}
                        aria-label="Create link" className="px-3 py-2 rounded-lg shrink-0 disabled:opacity-50"
                        style={{ background: colors.primary + '18', color: colors.primary }}>
                        {busyKey === linkType.api_name ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {feedback && <InlineFeedback {...feedback} />}
    </div>
  );
}

// ── Object detail panel ──────────────────────────────────────────────────────

function ObjectDetail({
  objectType, object, actionTypes, propertyTypes, linkTypes, onClose, onChanged, onObjectUpdated,
}: {
  objectType: ObjectTypeMeta; object: ObjectRow; actionTypes: ActionTypeMeta[]; propertyTypes: PropertyMeta[];
  linkTypes: LinkTypeRow[]; onClose: () => void; onChanged: () => void; onObjectUpdated: (updated: ObjectRow) => void;
}) {
  const { colors } = useTheme();
  const applicable = actionTypes.filter(a => a.target_object_type === objectType.api_name);
  const propByName = useMemo(() => new Map(propertyTypes.map(p => [p.api_name, p])), [propertyTypes]);

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
          <EditablePropertyRow key={key} objectType={objectType} object={object} prop={propByName.get(key)}
            value={value} onUpdated={onObjectUpdated} />
        ))}
      </div>

      <LinkedObjectsSection objectType={objectType} object={object} linkTypes={linkTypes} />

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

// ── Object-type schema bar: implements + verify conformance ────────────────

function ObjectTypeSchemaBar({ objectType }: { objectType: ObjectTypeMeta }) {
  const { colors } = useTheme();
  const [verifying, setVerifying] = useState(false);
  const [result, setResult] = useState<{ tone: 'ok' | 'bad' | 'notice'; message: string } | null>(null);

  const verify = async () => {
    setVerifying(true); setResult(null);
    try {
      const res = await api.verifyConformance(objectType.api_name);
      setResult({
        tone: 'ok',
        message: res.implements.length === 0
          ? 'Conforms (no interfaces declared, so there is nothing to check).'
          : `Conforms to every implemented interface (${res.implements.join(', ')}).`,
      });
    } catch (e: any) {
      const { notice, message } = mutationTone(e);
      setResult({ tone: notice ? 'notice' : 'bad', message });
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="flex items-center gap-2 flex-wrap mb-3 shrink-0">
      <span className="text-[11px] font-medium" style={{ color: colors.inkTertiary }}>Implements:</span>
      {objectType.implements.length === 0 ? (
        <span className="text-[11px]" style={{ color: colors.inkTertiary }}>Nothing declared</span>
      ) : objectType.implements.map(name => (
        <span key={name} className="px-2 py-0.5 rounded-full text-[11px]" style={{ background: colors.surface2, color: colors.inkMuted }}>
          {name}
        </span>
      ))}
      <button onClick={verify} disabled={verifying}
        className="px-2 py-1 rounded-lg text-[11px] font-semibold flex items-center gap-1.5 disabled:opacity-50"
        style={{ background: colors.primary + '18', color: colors.primary }}>
        {verifying ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />} Verify conformance
      </button>
      {result && (
        <span className="text-[11px]" style={{
          color: result.tone === 'ok' ? colors.success : result.tone === 'notice' ? colors.primary : colors.error,
        }}>{result.message}</span>
      )}
    </div>
  );
}

// ── Dataset branches (object-type header, native types only) ───────────────

const TXN_TYPES = ['snapshot', 'append', 'update', 'delete'];

/**
 * F11: branch/transaction history for a connector dataset. The Ontology has
 * no formal ObjectType -> dataset_id link today (ObjectType carries no such
 * column - verified against metamodel.py) - so the dataset id is a manually
 * entered, per-object-type-remembered field, not a fabricated lookup. The
 * demo seed's convention is "connector:<source>:<table>" (e.g.
 * "connector:demo:support_tickets" for SupportTicket).
 */
function DatasetBranchesSection({ objectType }: { objectType: ObjectTypeMeta }) {
  const { colors } = useTheme();
  const storageKey = `kaeos-dataset-id:${objectType.api_name}`;
  const [open, setOpen] = useState(false);
  const [datasetId, setDatasetId] = useState(() => {
    try { return localStorage.getItem(storageKey) || ''; } catch { return ''; }
  });
  const [branch, setBranch] = useState('main');
  const [history, setHistory] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ notice: boolean; message: string } | null>(null);
  const [newBranchName, setNewBranchName] = useState('');
  const [txnType, setTxnType] = useState('snapshot');
  const [recordCount, setRecordCount] = useState('0');

  const rememberDatasetId = (v: string) => {
    setDatasetId(v);
    try { localStorage.setItem(storageKey, v); } catch { /* private mode etc - non-fatal */ }
  };

  // branchOverride lets a caller that just switched branches (createBranch)
  // load THAT branch's history immediately, instead of racing the `branch`
  // state update - setBranch() inside the same handler would not be visible
  // to this closure until the next render, so the stale value must never be
  // relied on for the very call that follows it.
  const loadHistory = async (branchOverride?: string) => {
    if (!datasetId.trim()) return;
    setBusy(true); setFeedback(null);
    try {
      const res = await api.getDatasetBranchHistory(datasetId.trim(), (branchOverride ?? branch).trim() || 'main');
      setHistory(res.transactions || []);
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusy(false);
    }
  };

  const createBranch = async () => {
    if (!datasetId.trim() || !newBranchName.trim()) return;
    setBusy(true); setFeedback(null);
    try {
      const name = newBranchName.trim();
      await api.createDatasetBranch(datasetId.trim(), { name, from_branch: branch.trim() || 'main' });
      setBranch(name);
      setNewBranchName('');
      await loadHistory(name);
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusy(false);
    }
  };

  const logTransaction = async () => {
    if (!datasetId.trim()) return;
    setBusy(true); setFeedback(null);
    try {
      const txn = await api.beginDatasetTransaction(datasetId.trim(), { txn_type: txnType, branch: branch.trim() || 'main' });
      await api.commitDatasetTransaction(txn.id, Number(recordCount) || 0);
      await loadHistory();
    } catch (e: any) {
      setFeedback(mutationTone(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl mb-3 shrink-0" style={{ border: `1px solid ${colors.hairline}` }}>
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between px-3 py-2 text-[12px] font-medium" style={{ color: colors.ink }}>
        <span className="flex items-center gap-2"><GitBranch className="w-3.5 h-3.5" style={{ color: colors.primary }} />Dataset branches</span>
        <ChevronRight className="w-3.5 h-3.5 transition-transform" style={{ transform: open ? 'rotate(90deg)' : undefined, color: colors.inkTertiary }} />
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-3">
          <p className="text-[11px]" style={{ color: colors.inkTertiary }}>
            The Ontology has no formal link from an ObjectType to a connector dataset yet - enter the dataset id this
            type syncs from (the demo seed uses one shaped like "connector:demo:support_tickets").
          </p>
          <div className="grid grid-cols-2 gap-2">
            <input value={datasetId} onChange={e => rememberDatasetId(e.target.value)} placeholder="dataset id"
              className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
            <input value={branch} onChange={e => setBranch(e.target.value)} placeholder="branch"
              className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
          </div>
          <button onClick={() => loadHistory()} disabled={busy || !datasetId.trim()}
            className="px-3 py-1.5 rounded-lg text-[12px] font-semibold flex items-center gap-2 disabled:opacity-50"
            style={{ background: colors.primary + '18', color: colors.primary }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />} Load history
          </button>

          {history !== null && (
            history.length === 0 ? (
              <div className="text-[12px]" style={{ color: colors.inkTertiary }}>No committed transactions on this branch yet.</div>
            ) : (
              <div className="rounded-lg overflow-hidden" style={{ border: `1px solid ${colors.hairline}` }}>
                {history.map(t => (
                  <div key={t.id} className="px-3 py-2 text-[12px] flex items-center justify-between gap-2" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
                    <span style={{ color: colors.ink }}>{humanize(t.txn_type)}</span>
                    <span style={{ color: colors.inkSubtle }}>{t.record_count} records</span>
                    <span style={{ color: colors.inkTertiary }}>{t.committed_at ? formatDateTime(t.committed_at) : 'Not committed'}</span>
                  </div>
                ))}
              </div>
            )
          )}

          <div className="flex items-end gap-2 pt-2" style={{ borderTop: `1px solid ${colors.hairline}` }}>
            <div className="flex-1">
              <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>New what-if branch name</label>
              <input value={newBranchName} onChange={e => setNewBranchName(e.target.value)} placeholder="surge-pricing-scenario"
                className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
            </div>
            <button onClick={createBranch} disabled={busy || !datasetId.trim() || !newBranchName.trim()}
              className="px-3 py-2 rounded-lg text-[12px] font-semibold flex items-center gap-2 disabled:opacity-50 shrink-0"
              style={{ background: colors.primary, color: colors.canvas }}>
              <Plus className="w-3.5 h-3.5" /> Create branch
            </button>
          </div>

          <div className="flex items-end gap-2">
            <div>
              <label className="text-[11px] font-medium block mb-1" style={{ color: colors.inkSubtle }}>Log a transaction</label>
              <select value={txnType} onChange={e => setTxnType(e.target.value)}
                className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                {TXN_TYPES.map(t => <option key={t} value={t}>{humanize(t)}</option>)}
              </select>
            </div>
            <input type="number" value={recordCount} onChange={e => setRecordCount(e.target.value)} placeholder="record count"
              className={FIELD_CLASS} style={{ background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink, width: 120 }} />
            <button onClick={logTransaction} disabled={busy || !datasetId.trim()}
              className="px-3 py-2 rounded-lg text-[12px] font-semibold shrink-0 disabled:opacity-50"
              style={{ background: colors.surface2, color: colors.ink }}>
              Commit
            </button>
          </div>

          {feedback && <InlineFeedback {...feedback} />}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type Tab = 'objects' | 'value-types' | 'interfaces' | 'link-types' | 'object-sets';

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'objects', label: 'Objects', icon: Boxes },
  { id: 'value-types', label: 'Value types', icon: Shapes },
  { id: 'interfaces', label: 'Interfaces', icon: Layers },
  { id: 'link-types', label: 'Link types', icon: Link2 },
  { id: 'object-sets', label: 'Object sets', icon: Filter },
];

export default function ObjectExplorer() {
  const { colors } = useTheme();
  const status = useEnterprisePanel(() => api.getEnterpriseStatus());
  const objectTypes = useEnterprisePanel(() => api.listObjectTypes());
  const actionTypes = useEnterprisePanel(() => api.listActionTypes());
  const linkTypesPanel = useEnterprisePanel(() => api.listLinkTypes());
  const [tab, setTab] = useState<Tab>('objects');
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [propertyTypes, setPropertyTypes] = useState<PropertyMeta[]>([]);
  const [selectedObject, setSelectedObject] = useState<ObjectRow | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const types: ObjectTypeMeta[] = (objectTypes.data as any)?.object_types || [];
  const actions: ActionTypeMeta[] = (actionTypes.data as any)?.action_types || [];
  const linkTypeRows: LinkTypeRow[] = (linkTypesPanel.data as any)?.link_types || [];
  const objectTypeOptions: ObjectTypeOption[] = useMemo(
    () => types.map(t => ({ api_name: t.api_name, display_name: t.display_name })), [types],
  );
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

  const handleObjectUpdated = (updated: ObjectRow) => {
    setSelectedObject(updated);
    setReloadToken(t => t + 1);
  };

  if (status.loading || objectTypes.loading) return <BrainLoading message="Reading the ontology…" />;
  if (status.notice) return <div className={PAGE_PAD}><EnterpriseNotice message={status.notice} /></div>;
  if (objectTypes.notice) return <div className={PAGE_PAD}><EnterpriseNotice message={objectTypes.notice} /></div>;
  if (objectTypes.error) return <div className={PAGE_PAD}><BrainError message={objectTypes.error} onRetry={objectTypes.reload} /></div>;

  return (
    <div className="h-full overflow-hidden flex flex-col" style={{ background: colors.canvas, color: colors.ink }}>
      <div className={`${PAGE_PAD} pb-3 shrink-0`}>
        <div className="flex items-start gap-3 mb-3">
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
        <div className="flex items-center flex-wrap gap-1 rounded-xl p-1 w-fit max-w-full" role="tablist" aria-label="Object Explorer sections"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          {TABS.map(t => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
              className="px-3 py-1.5 rounded-lg text-[12px] font-medium flex items-center gap-2 transition-colors"
              style={{ background: tab === t.id ? colors.navActive : 'transparent', color: tab === t.id ? colors.navActiveText : colors.inkSubtle }}>
              <t.icon className="w-3.5 h-3.5" />{t.label}
            </button>
          ))}
        </div>
      </div>

      {tab !== 'objects' && (
        <div className={`${PAGE_PAD_X} pb-6 flex-1 overflow-hidden min-h-0`} role="tabpanel">
          {tab === 'value-types' && <ValueTypesPanel />}
          {tab === 'interfaces' && <InterfacesPanel />}
          {tab === 'link-types' && <LinkTypesPanel objectTypeOptions={objectTypeOptions} />}
          {tab === 'object-sets' && <ObjectSetsPanel objectTypeOptions={objectTypeOptions} />}
        </div>
      )}

      {/* Below md: stacked (sidebar strip, then list full-width, detail as a
          full-screen overlay). At md+: the 3-column layout. Same components,
          just re-flowed - no separate mobile page to maintain. */}
      {tab === 'objects' && (
      <div className={`${PAGE_PAD} flex-1 overflow-hidden flex flex-col md:flex-row gap-4 min-h-0`} role="tabpanel">
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
            <ObjectTypeSchemaBar objectType={selected} />
            {selected.binding_mode === 'native' && <DatasetBranchesSection objectType={selected} />}
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
            <ObjectDetail objectType={selected} object={selectedObject} actionTypes={actions} propertyTypes={propertyTypes}
              linkTypes={linkTypeRows} onClose={() => setSelectedObject(null)}
              onChanged={() => setReloadToken(t => t + 1)} onObjectUpdated={handleObjectUpdated} />
          </div>
        )}
      </div>
      )}
    </div>
  );
}
