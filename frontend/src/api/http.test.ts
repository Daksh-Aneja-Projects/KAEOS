/**
 * src/api/http.ts is the chokepoint for every backend call: SWR cache,
 * in-flight dedup, 401 logout, 402 entitlement broadcast, FastAPI detail
 * coercion, and the cache-key trust boundary (the admin secret must never
 * be stored inside a cache key). These tests pin those guarantees.
 *
 * Each test re-imports the module (vi.resetModules) so the module-level
 * cache/inflight Maps start empty every time.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

type HttpModule = typeof import('./http');

const okRes = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const errRes = (status: number, body: unknown, statusText = '') =>
  ({ ok: false, status, statusText, json: async () => body });

let http: HttpModule;
let fetchMock: ReturnType<typeof vi.fn>;
let n: number; // increments per fetch CALL, so payloads reveal cache hit vs refetch

const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  delete window.__kaeos_reloading;
  n = 0;
  fetchMock = vi.fn(async () => okRes({ n: ++n }));
  vi.stubGlobal('fetch', fetchMock);
  http = await import('./http');
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('SWR cache', () => {
  it('within the 15s window: resolves from cache AND revalidates in background', async () => {
    // Note: the module has no separate "fresh, skip network" state - EVERY
    // within-TTL hit returns the cached body and fires a background refetch.
    vi.useFakeTimers();
    expect(await http.request('/w')).toEqual({ n: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(14_999); // still inside the window
    expect(await http.request('/w')).toEqual({ n: 1 }); // served from cache...
    expect(fetchMock).toHaveBeenCalledTimes(2); // ...while a background refetch fired
  });

  it('past the 15s TTL: blocks on a fresh network fetch', async () => {
    vi.useFakeTimers();
    await http.request('/t');
    vi.advanceTimersByTime(15_000); // TTL check is strict `<`, so exactly 15s is expired
    expect(await http.request('/t')).toEqual({ n: 2 }); // awaited the network, not the cache
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('background revalidation refreshes the cached value', async () => {
    await http.request('/r');                     // n=1 cached
    expect(await http.request('/r')).toEqual({ n: 1 }); // hit; reval (n=2) fired
    await flush();                                // let the revalidation land
    expect(await http.request('/r')).toEqual({ n: 2 }); // hit now serves the new body
  });

  it('any mutation flushes the whole cache', async () => {
    await http.request('/m'); // n=1 cached
    await http.request('/other', { method: 'POST', body: '{}' }); // n=2, clears cache
    expect(await http.request('/m')).toEqual({ n: 3 }); // real refetch, not the n=1 entry
  });
});

describe('LRU bound', () => {
  it('caps the cache at 300 entries and evicts the least recently used', async () => {
    for (let i = 0; i < 300; i++) await http.request(`/lru/${i}`); // n = 1..300
    await http.request('/lru/0'); // touch: hit (n=1), background reval -> n=301
    await flush();                // reval stored: /lru/0 is now {n:301}, at the LRU tail
    await http.request('/lru/300'); // 301st distinct key (n=302) -> evicts the LRU entry
    // /lru/1 (oldest untouched) was evicted: this must be a real refetch.
    expect(await http.request('/lru/1')).toEqual({ n: 303 });
    // /lru/0 was touched, so it survived: still served from cache.
    expect(await http.request('/lru/0')).toEqual({ n: 301 });
  });
});

describe('in-flight dedup', () => {
  it('collapses concurrent identical GETs into one network call', async () => {
    let release!: () => void;
    fetchMock.mockImplementation(
      () => new Promise((resolve) => { release = () => resolve(okRes({ n: ++n })); }),
    );
    const a = http.request('/dedup');
    const b = http.request('/dedup');
    expect(fetchMock).toHaveBeenCalledTimes(1); // second call joined the first
    release();
    expect(await a).toEqual({ n: 1 });
    expect(await b).toEqual({ n: 1 });
  });
});

describe('401 handling', () => {
  it('drops the stale token and sets the single-reload guard', async () => {
    localStorage.setItem('kaeos-token', 'stale');
    fetchMock.mockImplementation(async () => errRes(401, { detail: 'Session expired' }));
    await http.request('/protected').catch(() => {}); // jsdom cannot really reload
    expect(localStorage.getItem('kaeos-token')).toBeNull();
    expect(window.__kaeos_reloading).toBe(true);
  });

  it('does NOT log the user out on a failed login attempt', async () => {
    localStorage.setItem('kaeos-token', 't');
    fetchMock.mockImplementation(async () => errRes(401, { detail: 'Bad credentials' }));
    await expect(http.request('/auth/login', { method: 'POST', body: '{}' }))
      .rejects.toMatchObject({ name: 'ApiError', status: 401, message: 'Bad credentials' });
    expect(localStorage.getItem('kaeos-token')).toBe('t');
    expect(window.__kaeos_reloading).toBeUndefined();
  });
});

describe('402 entitlement broadcast', () => {
  it('dispatches kaeos:needs-plan with the backend message and still rejects', async () => {
    fetchMock.mockImplementation(async () => errRes(402, { detail: 'Wargaming needs the Scale plan' }));
    const seen: unknown[] = [];
    const onNeedsPlan = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener('kaeos:needs-plan', onNeedsPlan);
    try {
      await expect(http.request('/wargame'))
        .rejects.toMatchObject({ status: 402, message: 'Wargaming needs the Scale plan' });
    } finally {
      window.removeEventListener('kaeos:needs-plan', onNeedsPlan);
    }
    expect(seen).toEqual([{ message: 'Wargaming needs the Scale plan' }]);
  });
});

describe('FastAPI detail coercion', () => {
  it('passes a string detail through as the error message', async () => {
    fetchMock.mockImplementation(async () => errRes(403, { detail: 'Forbidden by policy' }));
    await expect(http.request('/x')).rejects.toThrow('Forbidden by policy');
  });

  it('joins a validation-error array into readable text', async () => {
    fetchMock.mockImplementation(async () => errRes(422, {
      detail: [
        { loc: ['body', 'amount'], msg: 'field required', type: 'missing' },
        { note: 'no msg key' },
      ],
    }));
    await expect(http.request('/x')).rejects.toThrow('field required; {"note":"no msg key"}');
  });

  it('flattens an object detail to its msg', async () => {
    fetchMock.mockImplementation(async () => errRes(400, { detail: { msg: 'nested message' } }));
    await expect(http.request('/x')).rejects.toThrow('nested message');
  });

  it('falls back to the status text when the body is not JSON', async () => {
    fetchMock.mockImplementation(async () =>
      ({ ok: false, status: 502, statusText: 'Bad Gateway', json: async () => { throw new Error('no json'); } }));
    await expect(http.request('/x')).rejects.toThrow('Bad Gateway');
  });
});

describe('cache keying at the admin trust boundary', () => {
  it('never keys on the admin secret VALUE: two secrets share one entry', async () => {
    const r1 = await http.request('/ops/overview', { headers: { 'X-Admin-Secret': 'secret-A' } });
    const r2 = await http.request('/ops/overview', { headers: { 'X-Admin-Secret': 'secret-B' } });
    expect(r1).toEqual({ n: 1 });
    // Same key -> cache hit. If the secret value were part of the key, this
    // would be a miss and resolve {n:2} - which is exactly what leaks the
    // secret into a plain Map readable by XSS or a devtools heap snapshot.
    expect(r2).toEqual({ n: 1 });
  });

  it('still separates admin-scoped from tenant-scoped responses', async () => {
    expect(await http.request('/ops/overview', { headers: { 'X-Admin-Secret': 'secret-A' } }))
      .toEqual({ n: 1 });
    // No admin header -> different scope -> must NOT be served the admin body.
    expect(await http.request('/ops/overview')).toEqual({ n: 2 });
  });

  it('keys by the dev-tenant override', async () => {
    localStorage.setItem('kaeos-dev-tenant', 'tenant_a');
    expect(await http.request('/p')).toEqual({ n: 1 });
    localStorage.setItem('kaeos-dev-tenant', 'tenant_b');
    expect(await http.request('/p')).toEqual({ n: 2 }); // different tenant, different entry
  });
});
