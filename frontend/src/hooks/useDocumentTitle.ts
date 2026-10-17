import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { humanize } from '../lib/format';

const ROUTE_TITLES: Record<string, string> = {
  '/': 'Workforce',
  '/departments': 'Departments',
  '/deploy': 'Deploy',
  '/marketplace': 'Marketplace',
  '/integrations': 'Integrations',
  '/analytics': 'Analytics',
  '/pulse': 'Org pulse',
  '/my-work': 'My work',
  '/automation': 'Automation',
  '/getting-started': 'Getting started',
  '/platform/foundry': 'AI foundry',
  '/platform/onboarding': 'Client onboarding',
  '/platform/foresight': 'Foresight',
  '/platform/knowledge': 'Knowledge',
  '/platform/agents': 'Agents',
  '/platform/decisions': 'Decisions',
  '/platform/trust': 'Governed decisions',
  '/platform/authority': 'Authority',
  '/platform/authority/balance': 'Authority balance',
  '/platform/compliance-checker': 'Compliance checker',
  '/platform/users': 'Users',
  '/platform/operator': 'Operator console',
  '/platform/settings': 'Settings',
};

/** Set the browser tab title to "<title> - KAEOS". */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} - KAEOS` : 'KAEOS: The Governed AI Workforce';
  }, [title]);
}

/** Derive the tab title from the current route; used once by the app shell. */
export function useRouteTitle() {
  const { pathname } = useLocation();
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  const title = ROUTE_TITLES[path]
    ?? (path.startsWith('/departments/') ? humanize(path.split('/').filter(Boolean).slice(1).join(' ')) : humanize(path.split('/').filter(Boolean).pop() || ''));
  useDocumentTitle(title);
}
