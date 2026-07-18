import React from 'react';
import {
  Building2, Users, Landmark, Scale, Settings, TrendingUp, Headphones,
  Package, Boxes, Rocket, Target, HeartPulse, Zap, Briefcase, ShoppingCart,
  ShieldCheck, FileText, GraduationCap, Wallet, Clock, BarChart3, Bot,
  ClipboardCheck, Wrench, Globe, Database, MessageSquare, type LucideIcon,
} from 'lucide-react';

/**
 * Premium SVG icon for departments, capabilities, and domain packs.
 * Resolves a slug / name / legacy emoji string to a lucide icon rendered in a
 * tinted tile - replaces all raw emoji rendering across the UI.
 */

const ICONS: Record<string, { icon: LucideIcon; color: string }> = {
  // departments (by slug and legacy emoji)
  hr: { icon: Users, color: '#22c55e' },
  finance: { icon: Landmark, color: '#ec4899' },
  legal: { icon: Scale, color: '#6366f1' },
  operations: { icon: Settings, color: '#ef4444' },
  sales: { icon: TrendingUp, color: '#f59e0b' },
  support: { icon: Headphones, color: '#3b82f6' },
  it: { icon: Database, color: '#06b6d4' },
  procurement: { icon: ShoppingCart, color: '#8b5cf6' },
  marketing: { icon: Globe, color: '#f97316' },
  '👥': { icon: Users, color: '#22c55e' },
  '💰': { icon: Landmark, color: '#ec4899' },
  '⚖️': { icon: Scale, color: '#6366f1' },
  '⚙️': { icon: Settings, color: '#ef4444' },
  '📈': { icon: TrendingUp, color: '#f59e0b' },
  '🎧': { icon: Headphones, color: '#3b82f6' },
  '🏢': { icon: Building2, color: '#5e6ad2' },
  '📦': { icon: Package, color: '#8b5cf6' },
  // capabilities (by keyword and legacy emoji)
  '🏥': { icon: HeartPulse, color: '#ef4444' },
  '🚀': { icon: Rocket, color: '#5e6ad2' },
  '🎯': { icon: Target, color: '#f59e0b' },
  '⚡': { icon: Zap, color: '#06b6d4' },
  '💼': { icon: Briefcase, color: '#8b5cf6' },
  '🛡️': { icon: ShieldCheck, color: '#22c55e' },
  '📄': { icon: FileText, color: '#64748b' },
  '🎓': { icon: GraduationCap, color: '#f97316' },
  '💳': { icon: Wallet, color: '#ec4899' },
  '⏰': { icon: Clock, color: '#3b82f6' },
  '📊': { icon: BarChart3, color: '#06b6d4' },
  '🤖': { icon: Bot, color: '#8b5cf6' },
  '✅': { icon: ClipboardCheck, color: '#22c55e' },
  '🔧': { icon: Wrench, color: '#64748b' },
  '💬': { icon: MessageSquare, color: '#3b82f6' },
};

const KEYWORDS: [string, keyof typeof ICONS][] = [
  ['human resources', 'hr'], ['recruit', '🎯'], ['talent', '🎯'],
  ['onboard', '🚀'], ['benefit', '🏥'], ['payroll', '💳'], ['compensation', '💳'],
  ['finance', 'finance'], ['account', 'finance'], ['legal', 'legal'],
  ['compliance', '🛡️'], ['contract', '📄'], ['operation', 'operations'],
  ['sales', 'sales'], ['crm', 'sales'], ['support', 'support'],
  ['success', 'support'], ['ticket', '💬'], ['learning', '🎓'],
  ['performance', '📊'], ['time', '⏰'], ['quality', '✅'],
  ['procure', 'procurement'], ['vendor', '🔧'], ['project', '📊'],
];

function resolve(hint?: string | null): { icon: LucideIcon; color: string } {
  if (hint) {
    const direct = ICONS[hint] || ICONS[hint.toLowerCase()];
    if (direct) return direct;
    const lower = hint.toLowerCase();
    for (const [kw, key] of KEYWORDS) {
      if (lower.includes(kw)) return ICONS[key];
    }
  }
  return { icon: Building2, color: '#5e6ad2' };
}

interface Props {
  /** slug, name, or legacy emoji - anything that hints at the entity */
  hint?: string | null;
  /** secondary hint (e.g. name when hint is an unknown emoji) */
  fallbackHint?: string | null;
  /** tile size in px (default 40) */
  size?: number;
  className?: string;
}

export default function DomainIcon({ hint, fallbackHint, size = 40, className = '' }: Props) {
  let match = resolve(hint);
  if (match.icon === Building2 && fallbackHint) {
    const second = resolve(fallbackHint);
    if (second.icon !== Building2) match = second;
  }
  const Icon = match.icon;
  return (
    <div
      className={`rounded-xl flex items-center justify-center flex-shrink-0 ${className}`}
      style={{ width: size, height: size, background: match.color + '18' }}
    >
      <Icon style={{ width: size * 0.5, height: size * 0.5, color: match.color }} />
    </div>
  );
}
