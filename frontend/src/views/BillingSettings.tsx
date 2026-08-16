import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { BillingEntitlements, SkillValueBaseline } from '../api/types';
import { useTheme } from '../context/ThemeContext';
import { humanize } from '../lib/format';
import { CountUp } from '../components/CountUp';
import { Ring } from '../components/shared/Ring';
import {
  CreditCard, Check, Lock, Loader2, ArrowUpRight, ExternalLink, Gauge, Scale, Plus, AlertTriangle,
} from 'lucide-react';

/**
 * Tenant billing surface (billing.py): current plan and entitlements, metered
 * usage against the plan allowance, the plan catalog with self-service
 * upgrade/portal (managed cloud only - a self-hosted install has every
 * feature and nothing to buy), and the per-skill value baselines that turn
 * the ROI tile's "Value delivered: Not configured" into a measured number.
 * Admin-only on the backend (require_role("admin") on every mutation).
 */

const PLAN_ORDER = ['free', 'oss', 'team', 'business', 'enterprise'];
const PAID_PLANS = new Set(['team', 'business', 'enterprise']);

const BillingSettings: React.FC = () => {
  const { colors } = useTheme();

  const card: React.CSSProperties = { background: colors.surface1, border: `1px solid ${colors.hairline}`, borderRadius: 14 };
  const input: React.CSSProperties = { background: colors.surface2, border: `1px solid ${colors.hairline}`, color: colors.ink, borderRadius: 8, padding: '8px 10px', fontSize: 13, width: '100%' };

  const [ent, setEnt] = useState<BillingEntitlements | null>(null);
  const [entFailed, setEntFailed] = useState(false);
  const [billingMsg, setBillingMsg] = useState('');
  const [checkoutBusy, setCheckoutBusy] = useState<string | null>(null);
  const [portalBusy, setPortalBusy] = useState(false);

  const [baselines, setBaselines] = useState<SkillValueBaseline[]>([]);
  const [blForbidden, setBlForbidden] = useState(false);
  const [blForm, setBlForm] = useState({ skill_name: '', baseline_minutes: '', hourly_rate: '' });
  const [blBusy, setBlBusy] = useState(false);
  const [blMsg, setBlMsg] = useState('');

  const loadAll = useCallback(() => {
    api.getBillingEntitlements()
      .then(e => { setEnt(e); setEntFailed(false); })
      .catch(() => { setEnt(null); setEntFailed(true); });
    api.getBaselines()
      .then(r => { setBaselines(r.baselines || []); setBlForbidden(false); })
      .catch((e: any) => { setBaselines([]); setBlForbidden(e?.status === 403); });
  }, []);
  useEffect(() => { loadAll(); }, [loadAll]);

  const doCheckout = async (tier: string) => {
    setCheckoutBusy(tier); setBillingMsg('');
    try {
      const { url } = await api.createCheckoutSession(tier);
      window.location.assign(url);
    } catch (e: any) {
      // A 404 here means no billing provider is wired on this install; the
      // backend detail says so plainly - surface it, never pretend it worked.
      setBillingMsg(e?.message || 'Checkout is not available on this install.');
    } finally { setCheckoutBusy(null); }
  };

  const openPortal = async () => {
    setPortalBusy(true); setBillingMsg('');
    try {
      const { url } = await api.createPortalSession();
      window.location.assign(url);
    } catch (e: any) {
      setBillingMsg(e?.message || 'The billing portal is not available on this install.');
    } finally { setPortalBusy(false); }
  };

  const saveBaseline = async () => {
    const name = blForm.skill_name.trim();
    const minutes = parseInt(blForm.baseline_minutes, 10);
    if (!name || !Number.isFinite(minutes) || minutes < 0) return;
    setBlBusy(true); setBlMsg('');
    try {
      const body: { skill_name: string; baseline_minutes: number; hourly_rate?: number } = { skill_name: name, baseline_minutes: minutes };
      const rate = parseFloat(blForm.hourly_rate);
      if (Number.isFinite(rate)) body.hourly_rate = rate;
      await api.putBaseline(body);
      setBlForm({ skill_name: '', baseline_minutes: '', hourly_rate: '' });
      setBaselines((await api.getBaselines()).baselines || []);
    } catch (e: any) { setBlMsg(e?.message || 'Failed to save baseline'); }
    finally { setBlBusy(false); }
  };

  const usage = ent?.usage;
  const managed = ent?.managed_cloud === true;
  const planIds = ent
    ? [...PLAN_ORDER.filter(p => p in ent.plans), ...Object.keys(ent.plans).filter(p => !PLAN_ORDER.includes(p))]
    : [];

  return (
    <div className="space-y-4">
      {/* Current plan + entitlements */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-3">
          <CreditCard className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Plan &amp; Entitlements</span>
        </div>
        {!ent ? (
          <p className="text-[12px]" style={{ color: colors.inkSubtle }}>
            {entFailed ? 'Billing information could not be loaded.' : 'Loading plan…'}
          </p>
        ) : (
          <>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[22px] font-bold" style={{ color: colors.ink }}>{humanize(ent.plan)}</span>
              <span className="text-[11px] px-2 py-0.5 rounded-full font-medium"
                style={managed
                  ? { background: colors.primary + '1f', color: colors.primary }
                  : { background: 'rgba(39,166,68,0.12)', color: colors.success }}>
                {managed ? 'Managed Cloud' : 'Self-hosted'}
              </span>
              {ent.seats != null && (
                <span className="text-[11px] px-2 py-0.5 rounded-full font-medium"
                  style={{ background: colors.surface2, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
                  {ent.seats} seat{ent.seats === 1 ? '' : 's'}
                </span>
              )}
              {managed && (
                <button onClick={openPortal} disabled={portalBusy}
                  className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium"
                  style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairline}` }}>
                  {portalBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ExternalLink className="w-3.5 h-3.5" />} Manage billing
                </button>
              )}
            </div>

            {/* Feature checklist. Self-host is never feature-gated. */}
            <div className="mt-4">
              {!managed ? (
                <p className="text-[12px] flex items-center gap-1.5" style={{ color: colors.success }}>
                  <Check className="w-4 h-4" /> Self-hosted: all platform features included.
                </p>
              ) : (
                <div className="flex flex-wrap gap-x-5 gap-y-2">
                  {Object.entries(ent.features).map(([f, on]) => (
                    <span key={f} className="flex items-center gap-1.5 text-[12px]" style={{ color: on ? colors.ink : colors.inkTertiary }}>
                      {on ? <Check className="w-3.5 h-3.5" style={{ color: colors.success }} /> : <Lock className="w-3.5 h-3.5" />}
                      {humanize(f)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
        {billingMsg && <p className="text-[12px] mt-3" style={{ color: colors.error }}>{billingMsg}</p>}
      </div>

      {/* Usage vs allowance */}
      {usage && (
        <div className="p-5" style={card}>
          <div className="flex items-center gap-2 mb-3">
            <Gauge className="w-5 h-5" style={{ color: colors.primary }} />
            <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Usage This Period</span>
          </div>
          <div className="flex items-center gap-6 flex-wrap">
            <Ring
              value={usage.metered_executions}
              max={Math.max(usage.included_allowance, 1)}
              size={96}
              label="used"
              color={usage.overage_units > 0 ? colors.warning : colors.primary}
            />
            <div className="flex-1 min-w-[180px]">
              <div style={{ color: colors.ink }}>
                <CountUp value={usage.metered_executions} className="text-[24px] font-bold" />
                <span className="text-[13px]" style={{ color: colors.inkSubtle }}>
                  {' '}of {usage.included_allowance.toLocaleString()} included governed executions
                </span>
              </div>
              <p className="text-[12px] mt-1" style={{ color: colors.inkSubtle }}>
                Period started {usage.period_start}. The allowance resets monthly.
              </p>
              {usage.overage_units > 0 && (
                <div className="mt-3 p-3 rounded-lg flex items-start gap-2"
                  style={{ background: 'rgba(245,166,35,0.10)', border: `1px solid ${colors.warning}40` }}>
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" style={{ color: colors.warning }} />
                  <p className="text-[12px]" style={{ color: colors.ink }}>
                    <CountUp value={usage.overage_units} className="font-bold" /> executions over the included allowance this period.{' '}
                    {managed ? 'Overage is billed through your metered subscription.' : 'Self-hosted installs are not billed for overage.'}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Plan comparison */}
      {ent && (
        <div className="p-5" style={card}>
          <div className="flex items-center gap-2 mb-1">
            <ArrowUpRight className="w-5 h-5" style={{ color: colors.primary }} />
            <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Plans</span>
          </div>
          {!managed && (
            <p className="text-[12px] mb-3" style={{ color: colors.inkSubtle }}>
              Purchases apply to KAEOS managed cloud. This self-hosted install already includes everything.
            </p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-2">
            {planIds.filter(p => p !== 'oss' || p === ent.plan).map(p => {
              const cat = ent.plans[p];
              const current = p === ent.plan;
              return (
                <div key={p} className="p-4 rounded-xl flex flex-col"
                  style={{ background: colors.surface2, border: `1px solid ${current ? colors.primary : colors.hairline}` }}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[14px] font-semibold" style={{ color: colors.ink }}>{humanize(p)}</span>
                    {current && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0"
                        style={{ background: colors.primary + '1f', color: colors.primary }}>Current</span>
                    )}
                  </div>
                  <p className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>
                    {cat.allowance > 0
                      ? `${cat.allowance.toLocaleString()} governed executions / month`
                      : 'No metered allowance'}
                  </p>
                  <div className="mt-2 space-y-1 flex-1">
                    {cat.features.length === 0
                      ? <p className="text-[11px]" style={{ color: colors.inkTertiary }}>Core platform</p>
                      : cat.features.map(f => (
                        <div key={f} className="flex items-center gap-1.5 text-[11px]" style={{ color: colors.inkSubtle }}>
                          <Check className="w-3 h-3 shrink-0" style={{ color: colors.success }} /> {humanize(f)}
                        </div>
                      ))}
                  </div>
                  {managed && PAID_PLANS.has(p) && !current && (
                    <button onClick={() => doCheckout(p)} disabled={checkoutBusy !== null}
                      className="mt-3 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium"
                      style={{ background: colors.primary, color: '#fff', opacity: checkoutBusy && checkoutBusy !== p ? 0.5 : 1 }}>
                      {checkoutBusy === p ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowUpRight className="w-3.5 h-3.5" />} Upgrade
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Value baselines - the tenant input the honest ROI figure needs */}
      <div className="p-5" style={card}>
        <div className="flex items-center gap-2 mb-1">
          <Scale className="w-5 h-5" style={{ color: colors.primary }} />
          <span className="text-[16px] font-medium" style={{ color: colors.ink }}>Value Baselines</span>
        </div>
        <p className="text-[12px] mb-3" style={{ color: colors.inkSubtle }}>
          Tell KAEOS what this work costs a human, per skill: how many minutes a person takes,
          and their loaded hourly rate. This is what turns the ROI tile from
          "Value delivered: Not configured" into a measured number. KAEOS never invents a dollar figure.
        </p>
        {blForbidden && (
          <p className="text-[12px] mb-3" style={{ color: colors.inkSubtle }}>
            Viewing and editing value baselines needs an admin account. Ask a workspace admin
            to configure them.
          </p>
        )}
        {baselines.length > 0 && (
          <div className="overflow-x-auto mb-4">
            <table className="w-full text-left">
              <thead>
                <tr>
                  {['Skill', 'Human baseline', 'Hourly rate'].map(h => (
                    <th key={h} className="text-[11px] font-medium uppercase tracking-wide pb-2 pr-4"
                      style={{ color: colors.inkTertiary }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {baselines.map(b => (
                  <tr key={b.skill_name} className="border-t" style={{ borderColor: colors.hairline }}>
                    <td className="py-2 pr-4 text-[13px] font-medium whitespace-nowrap" style={{ color: colors.ink }}>{humanize(b.skill_name)}</td>
                    <td className="py-2 pr-4 text-[13px] whitespace-nowrap" style={{ color: colors.inkSubtle }}>{b.baseline_minutes} min</td>
                    <td className="py-2 pr-4 text-[13px] whitespace-nowrap" style={{ color: colors.inkSubtle }}>${b.hourly_rate.toFixed(2)}/hr</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!blForbidden && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <input style={input} placeholder="Skill name (e.g. invoice-matching)"
                value={blForm.skill_name} onChange={e => setBlForm({ ...blForm, skill_name: e.target.value })} />
              <input style={input} type="number" min={0} placeholder="Minutes a person takes"
                value={blForm.baseline_minutes} onChange={e => setBlForm({ ...blForm, baseline_minutes: e.target.value })} />
              <input style={input} type="number" min={0} step="0.01" placeholder="Loaded hourly rate (USD)"
                value={blForm.hourly_rate} onChange={e => setBlForm({ ...blForm, hourly_rate: e.target.value })} />
            </div>
            <button onClick={saveBaseline} disabled={blBusy || !blForm.skill_name.trim() || blForm.baseline_minutes === ''}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium mt-3"
              style={{ background: colors.primary, color: '#fff', opacity: (!blForm.skill_name.trim() || blForm.baseline_minutes === '') ? 0.5 : 1 }}>
              {blBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Save baseline
            </button>
            {blMsg && <p className="text-[12px] mt-2" style={{ color: colors.error }}>{blMsg}</p>}
          </>
        )}
      </div>
    </div>
  );
};

export default BillingSettings;
