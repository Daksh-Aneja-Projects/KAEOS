# KAEOS — Navigation IA + Zero-Mock-Data Plan

> **Two workstreams**, both grounded in a full audit of the running app (backend `:8001`, frontend `:5174`).
> **A. Navigation IA** — remove duplicate sidebar/top-bar navigation; sequence pages and sub-pages properly.
> **B. Zero mock/hardcoded data** — every page renders real API data or a proper empty state.
> Executed in tested, individually-committed batches with live browser verification.

---

## Phase 0 — Ground truth (from audits)

### A. Navigation duplication (the core complaint)
For **all 7 departments**, the contextual sidebar sub-nav AND the in-view top-bar tabs list the **same destinations twice**. Evidence:

| Dept | Sidebar sub-nav | In-view tab bar (duplicate) |
|---|---|---|
| HR | `App.tsx:96` `HR_NAV` | `WorkforceView.tsx:596` |
| Finance | `App.tsx:104` | `FinanceView.tsx:131` |
| Legal | `App.tsx:114` | `LegalView.tsx:108` |
| Support | `App.tsx:123` | `SupportView.tsx:111` |
| Sales | `App.tsx:131` | `SalesView.tsx:109` |
| Operations | `App.tsx:139` | `OperationsView.tsx:111` |
| Engineering | `App.tsx:148` | `EngineeringView.tsx:18` |

Other nav defects:
- **Tab clicks don't update the URL** (local `useState`) → sidebar highlight goes stale; tabs aren't deep-linkable.
- **Orphan tabs** (no route, tab-only): the "Analytics" tab in all 7 dept views + HR "Directory".
- **Third nav copy** drifts: `SEARCHABLE_MODULES` (`App.tsx:245-261`) hardcodes the nav map (already lists `/deploy` which no sidebar shows).
- **Orphan routes**: `/deploy` (`:643`), `/departments/engineering/services` (`:692`). **Silent fallback** `*`→dashboard (`:724`) masks broken links.
- **Sequencing**: "Getting Started" pinned above "Dashboard"; Platform lists admin tooling above daily-use Knowledge/Agents/Decisions.
- Platform views (Decisions `:19`, Agents `:17`, Knowledge `:18`, Settings `:58`) have legit in-page tabs with **no** sidebar duplicate — **keep these**.

### B. Mock/hardcoded data (concentrated, not everywhere)
Most DecisionsView tabs are genuinely real (ExecutiveCockpit, HITLQueue, Compliance, ProvenanceLedger, RedTeam, ConflictArena, CommandCenter — all real API + empty states). Violations:

| # | Location | Verdict |
|---|---|---|
| B-1 | `backend workforce/api/analytics.py` | agents_active read empty table (0); automation read unpopulated column (0). **Fixed in code**, pending verify+commit |
| B-2 | `AnalystWorkspace.tsx:199-224` Scenario Modeller | fully fabricated (no API, dead button) |
| B-3 | `AnalystWorkspace.tsx:265-290` Confidence Explorer | fully hardcoded 5D vector |
| B-4 | `AnalystWorkspace.tsx:91-100,136` Knowledge Graph | real nodes, **index-hashed fake coordinates** + hardcoded `0.72` |
| B-5 | `AgentMonitor.tsx:18-20` | executions keyed off a hardcoded 6-skill whitelist |
| B-6 | `ExecutiveAdvisor.tsx:8-36` | fully mock, self-labeled, **dead code** (never imported) |
| B-7 | 5 dashboards (`Sales/Support/Operations/Legal/Finance`) | empty-state bug: `{dept?.capabilities && ...}` (truthy `[]`) + always-on agents header |

Clean template to copy for B-7: `HRDashboard.tsx:151` — `{(dept?.capabilities || []).length > 0 && (`.

---

## Workstream A — Navigation IA

**Decision: Option B (top-bar tabs own department sub-sections; sidebar stops at the department).** Lowest-risk, matches the existing tabbed UI; the fix is to remove the *duplicate* sidebar sub-nav and make tabs URL-driven.

### A1 — De-duplicate department navigation
- In `App.tsx`, collapse each department sub-nav (`HR_NAV`…`ENGINEERING_NAV`, `:96-154`) so the sidebar shows a **single** department entry (the department overview), not the sub-section list. Keep the contextual-render blocks (`:330-411`) but point them at the single entry.
- In each department **view**, make tab clicks **push the URL** (`navigate('/departments/finance/ap')`) instead of only `setTab`, and derive the active tab from the URL (the `defaultTab` bridge already exists). This fixes the stale-highlight + deep-link bugs.
- **Anti-pattern guard**: never list a destination in both the sidebar and a tab bar. After the change, grep that no `*_NAV` array contains the same paths as its view's tab array.
- **Verify**: on `/departments/finance/ap`, "Accounts Payable" is highlighted in exactly one place (the tab); the sidebar shows "Finance" active only. Reload keeps the tab; back/forward works.

### A2 — Deep-link the orphan tabs
- Add routes for the tab-only destinations: `/departments/<dept>/analytics` (all 7) and HR `/departments/hr/directory`, so they're bookmarkable and the tabs sync. (Wire in `App.tsx` routes `:639-725`, mapping to the view's `defaultTab`.)
- **Verify**: each Analytics tab has a URL; pasting it opens that tab.

### A3 — Single source of truth + sequencing
- Derive `SEARCHABLE_MODULES` from the nav arrays instead of the hardcoded copy (`:245-261`), so search can't drift.
- Remove/redirect orphan routes (`/deploy`, `/departments/engineering/services`); replace the `*` fallback (`:724`) with a real NotFound page (so broken links surface instead of silently rendering the dashboard).
- Reorder: Dashboard above Getting Started (demote GS to a dismissible banner or bottom); promote "My Work"; in Platform put Knowledge/Agents/Decisions first, admin (Client Onboarding, User Management) last, Settings last.
- **Verify**: search results match the live nav; unknown URL shows NotFound; sidebar order matches the spec.

---

## Workstream B — Zero mock/hardcoded data

### B1 — Analytics (backend) — DONE, verify + commit
Already implemented in `workforce/api/analytics.py`: `agents_active` = Σ `Department.agent_count` (35); automation computed from the 140 real executions (autonomous/total, per-department via a Skill-join). **Verify** live: `GET /workforce/analytics` returns non-zero `agents_active` and `automation_coverage_pct`; the Analytics page shows real Automation and Agent Fleet numbers.

### B2 — AnalystWorkspace — make the three fake surfaces real
- **Confidence Explorer** (`:265-290`): bind to a real skill's `confidence_vector` (the `Skill` model already carries `source_breadth/source_authority/temporal_freshness/outcome_validation/explicit_validation`). Add/point at an endpoint returning a skill's vector; render that instead of the literal array.
- **Scenario Modeller** (`:199-224`): wire "Run Simulation" to a real endpoint (`/simulation/what-if` or `/10x/physics/simulate`) and render the returned impact; if no suitable endpoint, remove the tab rather than fake it.
- **Knowledge Graph** (`:91-100,136`): replace index-hashed coordinates with a real deterministic layout computed from the `source→target` edges (so drawn lines represent real relationships), and replace the hardcoded `0.72` with the computed avg confidence from `graphData`.
- **Verify**: grep `AnalystWorkspace.tsx` for literal metric values → none; edges connect real node pairs.

### B3 — AgentMonitor — derive the skill list from the registry
- Replace the hardcoded 6-skill array (`:18-20`) with the live skill registry (`api.getSkills()` / equivalent), so every skill's executions can appear.
- **Verify**: a newly added skill's executions show up without a code change.

### B4 — Delete the dead mock
- Remove `ExecutiveAdvisor.tsx` (unused, fully mock). Grep confirms no imports.
- **Verify**: `grep -r ExecutiveAdvisor src` → none.

### B5 — Fix the 5 dashboards' empty-state bug
- In `Sales/Support/Operations/Legal/FinanceDashboard.tsx`, copy the correct guard from `HRDashboard.tsx:151`: gate the Capabilities card on `(dept?.capabilities || []).length > 0` and give the Agents card a real empty state ("No agents deployed yet") instead of a bare header.
- **Verify**: a department with no capabilities/agents shows a clean empty state, not a blank header.

---

## Final Phase — Verification
1. `grep -rE "Math\.random|Array\.from\(\{length|mock|dummy|hardcod" frontend/src` → only comments documenting removals.
2. No `*_NAV` path also appears in its view's tab array (nav-dedup check).
3. `npm run build` + `npm test` green; backend suite green.
4. Live browser pass: each department page (single active highlight, URL-synced tabs), Analytics (real numbers), AnalystWorkspace (real graph + vectors), each dashboard empty state.
5. Update CHANGELOG/README; commit per batch.

---

## Anti-patterns to forbid
- ❌ Listing a destination in both the sidebar and a top-bar tab.
- ❌ Tab state that doesn't reflect in the URL.
- ❌ Rendering a section header with no content and no empty state.
- ❌ Hardcoded metric values, index-based fake coordinates, or `Math.random()` data.
- ❌ A third hardcoded nav copy (`SEARCHABLE_MODULES`) — derive it.
