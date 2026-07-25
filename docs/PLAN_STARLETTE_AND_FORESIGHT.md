# KAEOS — Definitive Plan: Starlette 1.x Upgrade + Foresight USP + Missing Touchpoints

Status: PROPOSED (authored 2026-07-25). One plan, two workstreams, executed in order.
Workstream A (secure base) first, then Workstream B (product surface).

Each phase is self-contained for a fresh chat context: it lists exact files, the
change, the verification command, and anti-patterns to avoid. Do not start a phase
until the prior phase's verification checklist passes.

---

## Phase 0 — Discovery findings (already gathered this session; re-confirm the two ⚠️ items at execution time)

### A. Dependency facts (verified in Docker, python:3.12-slim, against real `backend/requirements.txt`)
- All 6 remaining backend Dependabot advisories are on `starlette==0.48.0`:
  PYSEC-2026-161, 248, 249, 1942, 2280, 2281. Five are fixed only in Starlette 1.x; PYSEC-2026-1942 is fixed in 0.49.1.
- The pin comment in `requirements.txt` ("no released FastAPI supports Starlette 1.x") is **stale**.
  `fastapi==0.140.0` requires `starlette>=0.46.0` (no upper cap). The full set resolves with **zero conflicts**:
  - `fastapi 0.119.1 → 0.140.0`
  - `starlette 0.48.0 → 1.3.1`
  - `prometheus-fastapi-instrumentator 7.1.0 → 8.0.2`  (8.0.2 *requires* `starlette>=1.0.0,<2.0.0` — this bump is mandatory)
  - `opentelemetry-instrumentation-fastapi==0.63b1` — its fastapi pin is a soft `instruments` extra; no change needed.
- Frontend `brace-expansion` HIGH advisory (GHSA-mh99-v99m-4gvg) already fixed + pushed (commit 7544795).

### B. Docker validation result under the new pins: **18 failed / 319 passed / 3 skipped** — triaged:
1. **~15 failures = route-introspection only** (NOT runtime regressions):
   - `tests/test_rbac_coverage.py::test_gated_route_declares_require_role[...]` — helper `_find_route` (line 60-64) walks flat `app.routes` and reads `route.dependant`; `_dependant_uses_require_role` (line 48-57).
   - `tests/test_default_deny.py::test_sensitive_mutations_are_gated[...]` — walks `app.routes` (line 83) and reads `route.dependant.dependencies` (line 62).
   - Root cause: under Starlette 1.x, `include_router` nests routes beneath a `Mount`, so the top-level `app.routes` entries no longer expose the leaf `APIRoute.dependant`. The `require_role` `Depends()` gates **still fire at request time** (FastAPI DI is unaffected by the Mount refactor) — the tests just can't *see* them through the new tree.
2. **1 failure = a security WIN**: `tests/test_tenant_middleware.py::test_poisoned_host_header_cannot_bypass_auth_gate`. Its precondition `assert request.url.path == "/health"` asserts the GHSA-86qp Host-poisoning bug *still exists*. Starlette 1.3.1 **patches** it, so `request.url.path` now returns the real path. The test's own comment says: "If a future Starlette bump patches GHSA-86qp, this will flip to the real path — revisit the pin/ignore in that case."
3. **2 failures = unrelated**: `tests/test_real_data_loaders.py::{test_sales_crm_is_relationally_consistent, test_account_limit_bounds_the_result}` — data-availability in the throwaway container. ⚠️ Re-confirm these fail identically on the CURRENT pins (they are skipped locally without the Kaggle data) so they are not attributed to Starlette.

### C. Frontend coverage facts (verified against `frontend/src/api/client.ts` + pages)
- **Already wired — do NOT re-add (would duplicate):**
  - `pioneer` `/intelligence/*` + `/org-intelligence/*` → client.ts 900-915; rendered in `ExecutiveCockpit.tsx` as `pioneer_alerts` ("external intelligence signals").
  - `regulatory` `/overview` + `/evidence/{framework}` → `ComplianceDashboard.tsx` (`getRegulatoryEvidence`).
  - `outcomes` `/impact` + record → `EvolutionTimeline.tsx` (`getOutcomeImpact`, `recordOutcome`, lines 26-53).
  - `event_mesh` `/signals/ingest` → client.ts 1134 (`ingestSignal`). ⚠️ Confirm whether any PAGE renders the mesh feed; API method exists but may be unrendered.
  - `safe-autonomy` (client.ts 1102) + precog forecast (client.ts 1110) → OrgPulse / RealityExperience / WorkforceDashboard.
- **Truly headless — real gaps:**
  - `predictive` `/ghost-executions`, `/discover-patterns`, `/analyze-signal/{id}` → **no client method, no page**. (The "what the org is about to do" engine.)
  - `event_mesh` feed **render** (governed responses timeline) → ⚠️ verify no page shows it; if not, it is a gap.
- Routing: pages are `lazy()`-imported and registered as `<Route path=... element=...>` in `frontend/src/App.tsx` (RealityExperience at line 68; route table starts ~line 548). New pages follow that exact pattern.
- Reality views live in `frontend/src/pages/RealityExperience.tsx` as modes: `shock`, `whatif`, `wargame`, `replay`. Backend: `app/api/routes/reality.py` (`/twin`, `/provenance`, `/learning`, `/decision`, `/shock`, `/simulate`).

### Anti-patterns to avoid (whole plan)
- Do NOT "migrate" the introspection tests by loosening assertions to make them pass. Replace fragile private-attribute introspection with **runtime** behavior assertions (below).
- Do NOT add a new frontend page for anything except the Foresight USP. Every other capability attaches to an existing page.
- Do NOT invent client methods; extend `frontend/src/api/client.ts` following the existing `request<T>(...)` shape.
- Do NOT drop the `scope["path"]` auth-gate mitigation; keep it as belt-and-suspenders even though upstream now patches GHSA-86qp.

---

# WORKSTREAM A — Resolve Starlette 1.x properly (no shortcuts)

## Phase A1 — Prove runtime auth is intact under Starlette 1.3.1 (the one unverified thing)
**Why first:** the entire upgrade rests on "gates still fire at runtime." Prove it before changing pins in the repo.
**What to implement (in a throwaway Docker run, no repo change yet):**
1. Build the container exactly as validation did: mount `backend/` read-only, copy to `/app`, `sed` the 3 version bumps into `requirements.txt`, `pip install -r requirements.txt`.
2. Add a temporary runtime probe (a `pytest` using `fastapi.testclient.TestClient(app)` OR an inline script): for each `(method, path)` in `test_rbac_coverage.ALL_GATED`, issue the request with NO auth header and assert status is `401` or `403` (never `200`/`404`).
   - Example gated routes to probe: `POST /api/v1/polymorphic/synthesize` (admin), `POST /api/v1/pipeline/run` (operator).
**Verification checklist:**
- [ ] Every `ALL_GATED` route returns 401/403 unauthenticated under Starlette 1.3.1.
- [ ] If ANY returns 200 → STOP. Real regression; escalate/confirm design before proceeding.
**Anti-pattern guard:** don't assert on route introspection here — assert on HTTP status only.

## Phase A2 — Convert the introspection tests to runtime default-deny assertions
**Files:** `backend/tests/test_rbac_coverage.py`, `backend/tests/test_default_deny.py`.
**What to implement:**
- In `test_rbac_coverage.py`: keep `ALL_GATED` and `test_require_role_denies_and_permits_by_level` (pure-logic, unaffected). Replace `_find_route`/`test_gated_route_declares_require_role` with a `TestClient`-based check: unauthenticated request to each gated route asserts 401/403. This is framework-refactor-proof and tests the property that actually matters (default-deny), closing the introspection→runtime gap permanently.
- In `test_default_deny.py`: the discovery loop over `app.routes` (line 83) must find leaf routes. Add a recursive walker that descends `Mount.routes` (Starlette `Mount` exposes `.routes`) so both flat and nested trees work; keep the existing default-deny intent. Prefer, where practical, the same runtime-assertion approach.
**Documentation references:** copy the DI-safe pattern from the Phase A1 probe; Starlette `Mount.routes` is the child route list.
**Verification checklist:**
- [ ] `pytest tests/test_rbac_coverage.py tests/test_default_deny.py -q` passes on BOTH the current pins (0.48.0) and the bumped pins (regression-safe either way).
**Anti-pattern guard:** do not delete coverage; the new assertions must cover every path the old ones did (diff `ALL_GATED` and the default-deny discovery set before/after).

## Phase A3 — Flip the Host-poisoning test to the patched-Starlette reality
**File:** `backend/tests/test_tenant_middleware.py` (`test_poisoned_host_header_cannot_bypass_auth_gate`, precondition ~line 72).
**What to implement:**
- Starlette 1.3.1 patches GHSA-86qp: `request.url.path` no longer reconstructs from the poisoned Host. Update the precondition + assertions to the patched behavior, while STILL asserting the middleware keys off `request.scope["path"]` (keep the mitigation as belt-and-suspenders and keep a regression assertion that the gate cannot be bypassed).
**Verification checklist:**
- [ ] `pytest tests/test_tenant_middleware.py -q` passes under the bumped pins.
- [ ] The test still fails if someone reverts the middleware to `request.url.path`.

## Phase A4 — Land the version bumps + docs + policy, then gate on the full suite
**Files:** `backend/requirements.txt`, `.github/dependabot.yml`, `SECURITY.md`, `CHANGELOG.md`, memory `kaeos-starlette-security-ceiling`.
**What to implement:**
1. `requirements.txt`: bump the 3 pins; rewrite the stale Starlette block comment (lines ~3-14) and the prometheus comment (line ~62-63) to state the new reality (fastapi 0.140 lifts the cap; pfi 8.x requires starlette≥1.0).
2. `.github/dependabot.yml`: remove the `starlette >=1.0.0` ignore rule (lines ~19-32); refresh the header note.
3. `SECURITY.md`: rewrite "Starlette advisories — disposition" — the multipart/form + GHSA-86qp + 82w8 advisories are now **Fixed** (Starlette 1.3.1), not Accepted. Keep the `scope["path"]` note as defense-in-depth.
4. `CHANGELOG.md`: `Unreleased` → move the fix under a security bump entry.
5. Update the `kaeos-starlette-security-ceiling` memory: ceiling **lifted** as of fastapi 0.140 / starlette 1.3.1; record the introspection-test learning.
**Gating checkpoint (MANDATORY before commit):**
- [ ] Full non-e2e suite is **340 passed** under the new pins, run in Docker `python:3.12` to match CI (`pytest tests/ --ignore=tests/e2e`).
- [ ] `ruff check .` clean; `bandit -r app -ll` clean.
- [ ] Then commit + push to `main`. Confirm the GitHub Dependabot count drops (starlette alerts clear).
**Anti-pattern guard:** do not push if even one test is red or if Phase A1 found a runtime 200.

---

# WORKSTREAM B — Foresight USP (one new page) + missing touchpoints (into existing pages)

> Reminder (user constraint): the ONLY new page is Foresight. Everything else attaches to an existing page. Verify current usage before adding any widget so nothing duplicates.

## Phase B1 — Backend: Foresight aggregation endpoint (compose, don't rebuild)
**Files:** new `backend/app/api/routes/reality.py` addition (or a small `foresight.py` router mounted under `/api/v1/reality/foresight`), reusing existing services.
**What to implement — reuse existing substrate, add only the scoring aggregation:**
- `GET /reality/foresight/premortem` → returns ranked "Inevitable Surprises". For each candidate scenario (reuse the shock catalog in `RealityExperience.tsx` labels + `reality.py` `/shock` blast-radius traversal `traverse_blast_radius`):
  `exposure = likelihood × blast_radius × preparedness_gap`, where
  - likelihood ← `predictive` signals + `event_mesh` recent signals,
  - blast_radius ← `reality_twin.traverse_blast_radius`,
  - preparedness_gap ← is there a governed, tested response (a mission/skill) covering it? (query missions/skills).
  Each item carries a `commission_mission` payload (reuse the missions create path) for the one-click gap-closer.
- `GET /reality/foresight/trajectory` → compose EXISTING endpoints: `safe_autonomy/forecast` (north-star curve) + committed `missions` (next 30/60/90d autonomous actions) + `outcomes/impact` (realized-vs-predicted) + the human decision points (pending HITL/approvals).
**⚠️ Confirm before building:** exact response shapes of `predictive.py` (`/ghost-executions`, `/discover-patterns`) and `event_mesh` signal store — read the route + service to reuse real fields (no invented fields).
**Verification checklist:**
- [ ] New endpoints return real DB-derived numbers for `tenant_acme` (no random/seeded fiction).
- [ ] `require_role` gate present (default-deny) — add to `ALL_GATED` in the (now runtime) rbac test.
- [ ] A backend test seeds a scenario with no covering mission and asserts it ranks with a high `preparedness_gap`.

## Phase B2 — Frontend: the Foresight page (the USP; the one new page)
**Files:** new `frontend/src/pages/Foresight.tsx`; register a `lazy()` import + `<Route path="/foresight" ...>` in `frontend/src/App.tsx` (copy the RealityExperience registration at line 68 + a route line ~548); add nav entry wherever RealityExperience is linked; extend `frontend/src/api/client.ts` with `getForesightPremortem()` / `getForesightTrajectory()` following the existing `request<T>` shape.
**What to implement:** two lanes — **Pre-Mortem Radar** (ranked Inevitable Surprises cards, each with "Commission a mission to close this gap") and **Prescriptive Trajectory** (safe-autonomy north-star curve + 30/60/90d autonomous-action projection + flagged human decision points). Reuse existing chart/card components used by RealityExperience/OrgPulse; follow `DomainIcon` / no-emoji / no-em-dash conventions.
**Verification checklist:**
- [ ] `npm run build` + `npm test` green; `npm run lint` no new errors.
- [ ] Browser-verify (preview): both lanes render real data; "commission a mission" creates a real mission.
**Anti-pattern guard:** don't duplicate the reactive What-if/Shock UI here — Foresight is autonomous/prescriptive (machine-proposed), not user-prompted.

## Phase B3 — Missing touchpoint #1: Ghost Executions → existing ExecutiveCockpit (no new page)
**Files:** `frontend/src/pages/ExecutiveCockpit.tsx` (+ `client.ts`).
**What to implement:** add a "What the org is about to do" panel fed by `predictive` `/ghost-executions` (+ optionally `/discover-patterns`). Add client methods; place beside the existing pioneer "external intelligence signals" panel.
**⚠️ Confirm first:** grep ExecutiveCockpit for any existing ghost/predictive widget (there is none as of this plan) to avoid duplication.
**Verification checklist:**
- [ ] Panel renders real `/ghost-executions` output; empty-state uses `BrainEmpty` like siblings.
- [ ] `npm run build`/`test`/`lint` green.

## Phase B4 — Missing touchpoint #2: Event Mesh feed → existing OrgPulse or CommandCenter (no new page)
**Files:** `frontend/src/pages/OrgPulse.tsx` (or `src/views/CommandCenter.tsx`) (+ `client.ts`).
**⚠️ Confirm first:** verify no page already renders the mesh feed (client `ingestSignal` exists at client.ts 1134 but the *feed render* appears absent). If a render exists, SKIP this phase.
**What to implement:** a live "nervous system" timeline — recent `event_mesh` signals correlated to the twin + their governed responses (`/{id}/respond`). Read-only feed; reuse existing activity-feed component.
**Verification checklist:**
- [ ] Feed shows real signals + governed responses for `tenant_acme`.
- [ ] No duplicate of an existing OrgPulse widget; `npm run build`/`test`/`lint` green.

---

## Final Phase — Whole-plan verification
- [ ] Backend: full non-e2e suite green in Docker `python:3.12` under the new pins (340 passed); `ruff`/`bandit` clean.
- [ ] Frontend: `npm run build`, `npm test`, `npm run lint` (no new errors).
- [ ] Dependabot: starlette alerts cleared on GitHub after push; frontend already at 0.
- [ ] No new pages except Foresight; grep confirms no duplicated widgets (ghost/mesh added exactly once).
- [ ] Docs updated: `requirements.txt` comments, `SECURITY.md`, `dependabot.yml`, `CHANGELOG.md`, memory.
- [ ] README + CHANGELOG updated per milestone convention; commit + push to `main`.

## Decisions — CONFIRMED by user (2026-07-25)
1. **Foresight placement** → **Standalone `/foresight` top-level page** with its own nav entry (the one new page; the USP).
2. **Event Mesh feed home** → **OrgPulse** (Phase B4), only if not already rendered.
3. **"Commission a mission to close this gap"** → **Auto-draft, human approves** — KAEOS drafts the mission; it enters the normal HITL/approval flow (autonomy that DOES, still governed).
