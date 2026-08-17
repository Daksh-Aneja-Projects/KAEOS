/**
 * KAEOS - API Client
 * Typed fetch wrapper for all backend endpoints - ZERO hardcoded data
 */

declare global { interface Window { __kaeos_reloading?: boolean; } }

export const API_BASE = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8001/api/v1`;

// The app root, with the versioned "/api/v1" segment stripped. A couple of
// endpoints (the public /status page) are mounted at the root, not under the
// versioned API — see backend app/main.py.
export const API_ORIGIN = API_BASE.replace(/\/api\/v\d+\/?$/, '');

/**
 * Unauthenticated GET against the app root (no bearer token, no tenant header).
 * For public endpoints like /status. Returns the parsed JSON body even on a
 * 503 — /status reports "degraded" with a 503 so a load balancer can act on it,
 * and the public page still wants to render that degraded state. Only a genuine
 * network failure (fetch rejects) propagates to the caller.
 */
export async function requestPublic<T>(path: string): Promise<T> {
  const res = await fetch(`${API_ORIGIN}${path}`);
  return res.json() as Promise<T>;
}

/**
 * Error thrown for non-OK API responses. Additive over the plain Error the
 * client used to throw: `message` is unchanged (the backend `detail`, e.g. a
 * 402's "feature X needs plan Y"), and `status` carries the HTTP code so
 * callers that care (billing/entitlement surfaces) can branch on it. Every
 * existing `catch (e) { e.message }` site keeps working untouched.
 */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function _exec<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('kaeos-token');
  const authHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    authHeaders['Authorization'] = `Bearer ${token}`;
  }
  // DEV-ONLY tenant override: when `kaeos-dev-tenant` is set in localStorage the
  // client asks the backend to serve that tenant. The backend honors X-Tenant-ID
  // ONLY in DEV_MODE (see TenantMiddleware); in production the header is ignored
  // and the tenant is derived from the JWT — so this is a no-op there.
  const devTenant = localStorage.getItem('kaeos-dev-tenant');
  if (devTenant) {
    authHeaders['X-Tenant-ID'] = devTenant;
  }
  // Spread options FIRST, then set the merged headers - otherwise `...options`
  // (when a caller passes its own `headers`, e.g. X-Admin-Secret) would clobber
  // the merged object and drop Content-Type/Authorization, which FastAPI then
  // rejects with a 422 on any JSON body.
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders, ...options?.headers },
  });
  if (!res.ok) {
    // Session expired or token revoked - drop the stale token so the
    // AuthGuard returns the user to the login page instead of a dead UI.
    if (res.status === 401 && token && !path.startsWith('/auth/login')) {
      localStorage.removeItem('kaeos-token');
      if (!window.__kaeos_reloading) {
        window.__kaeos_reloading = true;
        window.location.reload();
      }
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    // FastAPI validation errors return `detail` as an array of {loc,msg,type};
    // coerce anything non-string to a readable message so the UI never shows
    // "[object Object]".
    let detail = err?.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((d: any) => d?.msg || JSON.stringify(d)).join('; ');
    } else if (detail && typeof detail === 'object') {
      detail = detail.msg || JSON.stringify(detail);
    }
    // 402 Payment Required is the backend's entitlement/needs-plan contract.
    // Broadcast the message so the app root (NeedsPlanToast) can surface an
    // upgrade CTA; every caller's existing `catch` still gets the ApiError.
    if (res.status === 402) {
      window.dispatchEvent(new CustomEvent('kaeos:needs-plan', {
        detail: { message: typeof detail === 'string' ? detail : undefined },
      }));
    }
    throw new ApiError(detail || `API Error ${res.status}`, res.status);
  }
  // 204 No Content (e.g. DELETE /notifications/channels/{id}) has no body to parse.
  if (res.status === 204) return undefined as T;
  return res.json();
}

/**
 * Authenticated file download. The CSV/export endpoints are auth-gated, so a
 * plain `<a href>` (which cannot carry an Authorization header) gets a 401 and
 * saves an error page instead of the file. Fetch with the token, then save the
 * blob through a throwaway anchor.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const token = localStorage.getItem('kaeos-token');
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const devTenant = localStorage.getItem('kaeos-dev-tenant');
  if (devTenant) headers['X-Tenant-ID'] = devTenant;
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.detail || `Download failed (${res.status})`);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Authenticated multipart upload. FormData must NOT get a manual Content-Type
 * (the browser sets the boundary), so this bypasses _exec's JSON header.
 */
export async function uploadForm<T>(path: string, form: FormData): Promise<T> {
  const token = localStorage.getItem('kaeos-token');
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const devTenant = localStorage.getItem('kaeos-dev-tenant');
  if (devTenant) headers['X-Tenant-ID'] = devTenant;
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', headers, body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    let detail = err?.detail;
    if (Array.isArray(detail)) detail = detail.map((d: any) => d?.msg || JSON.stringify(d)).join('; ');
    throw new Error(detail || `Upload failed (${res.status})`);
  }
  return res.json();
}

// In-flight GET deduplication: many screens fire the same read on mount AND on a
// live-refresh tick, and several components can request the same endpoint at once.
// If an identical GET is already in flight, share its promise instead of issuing a
// duplicate network call. Zero staleness (it only collapses CONCURRENT identical
// requests; once one settles the entry is cleared), so live data stays live.
const _inflightGets = new Map<string, Promise<any>>();

// Stale-while-revalidate for GETs: navigating back to a page renders instantly
// from the last response while a background refetch updates the cache. The TTL
// sits under the 20s live-refresh convention, so polling pages always hit the
// network on their next tick - live data stays live, only remounts get faster.
// Any mutation flushes the whole cache: coarse, but it can never serve a read
// the user's own write just invalidated.
const _getCache = new Map<string, { t: number; data: any }>();
const _SWR_TTL_MS = 15_000;

export function request<T>(path: string, options?: RequestInit): Promise<T> {
  const method = (options?.method || 'GET').toUpperCase();
  if (method !== 'GET') {
    _getCache.clear();
    return _exec<T>(path, options);
  }
  // The dev tenant override changes what a path returns - key by it.
  const key = (localStorage.getItem('kaeos-dev-tenant') || '') + '|' + path
    + (options?.headers ? '|' + JSON.stringify(options.headers) : '');

  const fetchFresh = (): Promise<T> => {
    const existing = _inflightGets.get(key);
    if (existing) return existing as Promise<T>;
    const p = _exec<T>(path, options)
      .then((data) => { _getCache.set(key, { t: Date.now(), data }); return data; })
      .finally(() => _inflightGets.delete(key));
    _inflightGets.set(key, p);
    return p;
  };

  const cached = _getCache.get(key);
  if (cached && Date.now() - cached.t < _SWR_TTL_MS) {
    void fetchFresh().catch(() => {}); // revalidate in the background
    return Promise.resolve(cached.data as T);
  }
  return fetchFresh();
}
