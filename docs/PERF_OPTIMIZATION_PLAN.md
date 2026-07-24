# KAEOS — Speed & Latency Optimization Plan (next phase)

> Goal: cut end-to-end decision latency (a single gated execution is ~30s–3min on the
> local model) and make the app feel instant, WITHOUT weakening governance or faking
> the LLM. Ordered by ROI: do Phase 1–2 first (they alone should 2–4× the gate
> pipeline). Every phase is independently shippable, measurable, and reversible.

## Phase 0 — Measure first (do before changing anything)
The pipeline is LLM-bound; guessing wastes effort. Add lightweight timing.
- Instrument each gate in `backend/app/agents/runtime.py` (`execute_skill`): wrap Gates 1–6
  with a monotonic timer and log `{gate, ms, model_tier}` (there is already `_gate_cost`;
  add `_gate_ms`). Emit a per-execution `stage_timings` dict in the result.
- Instrument `LLMRouter.complete` (`services/llm_router.py:322`) to log `{tier, model, ms, tokens}`
  (a `_record_cost` hook already exists — add wall-ms there).
- Add a dev-only `GET /metrics/latency` that aggregates recent per-gate + per-tier ms
  (reuse the cost-telemetry pattern in `infrastructure.py`).
- **Verify:** run one gated execution; confirm the log shows where the seconds go
  (expectation: Gate 4 debate + Gate 5 execute dominate).
- **Anti-pattern:** do not optimize a gate before you have its measured ms.

## Hardware reality (researched 2026-07-25) — READ BEFORE tier changes
Dev box: i5-13450HX (16 threads), 15.7GB RAM (~3.7GB free), **RTX 3050 Laptop 6GB VRAM**.
- The resident `qwen2.5-coder:7b` uses **4.33GB VRAM**, leaving **~1.7GB free**.
- Ollama defaults to keeping **ONE** model loaded. So pointing a tier at a *different*
  model causes a **model swap** (multi-second reload) on every tier switch within a
  decision — which would make the pipeline SLOWER, not faster. (Measured: 1.5b was not
  faster than 7b on short structured output; the swap dominates.)
- Only model that can **co-reside** with the 7b in 6GB is **`qwen2.5-coder:1.5b` (~1.4GB)**
  (3b/phi4-mini would evict the 7b). Co-residency requires `OLLAMA_MAX_LOADED_MODELS=2`
  + a long `OLLAMA_KEEP_ALIVE` (both set persistently, User scope; activates on next
  Ollama restart).
- **Verdict:** do NOT split the DECISION-PATH tiers on this hardware (thrash + quality
  risk). Use the lighter `nano` (1.5b) tier ONLY for genuinely non-reasoning, off-path
  decorative text (e.g. the mission plan narrative — already wired to `nano`). The
  real safe LLM win here is **eliminating repeat calls via caching** (embedding cache
  shipped; compliance caching intentionally NOT done — a verdict depends on context, so
  caching it could rubber-stamp a changed context).

## Phase 1 — Right-size the model tiers (biggest, cheapest win — hardware-gated, see above)
Today ALL tiers point at `qwen2.5-coder:7b` (`llm_router.py:119-123`), including "fast" and
"classification". Installed and much faster: `qwen2.5-coder:1.5b`, `qwen2.5-coder:3b`,
`phi4-mini`. A 1.5–3b model is ~2–4× faster and is fine for formatting/scoring/classification.
- Change `MODEL_TIERS`: `fast → ollama/qwen2.5-coder:1.5b`, `classification → ollama/qwen2.5-coder:3b`
  (or `phi4-mini`), keep `reasoning → qwen2.5-coder:7b` (optionally try `3b` for reasoning and
  A/B the quality). Keep the cloud fallback chains.
- The gate LLM calls that are really "fast" work but currently request `reasoning`:
  audit/format/summary steps in `skill_executor.py` already use `fast` — they now get the 1.5b.
- **Verify:** re-run Phase 0 timing; fast/classification calls should drop 2–4×. Spot-check a
  few real decisions for unchanged verdicts (governance correctness must not regress).
- **Anti-pattern:** do NOT downgrade the compliance (Gate 1) or debate (Gate 4) REASONING calls
  to a tiny model without an A/B — those need judgment. Right-size only genuinely-cheap calls.

## Phase 2 — Parallelize + short-circuit the gate pipeline
The 7 gates run sequentially and the debate makes 3 SEQUENTIAL reasoning calls
(`debate_engine.py:129,144,160` — proposer → opposer → arbiter). This is the single biggest cost.
- **Parallelize the debate:** run proposer + opposer concurrently (`asyncio.gather`), then the
  arbiter. ~33% off the debate. (They are independent; only the arbiter depends on both.)
- **Parallelize independent gates:** Gate 1 (compliance) and Gate 2 (fairness) are independent —
  run them with `asyncio.gather` before the HITL/debate gates. Keep ordering only where a gate's
  BLOCK must stop the next.
- **Skip gates that cannot apply:** Gate 1's LLM call only runs when regulated tags are present
  (already true) — confirm and extend: skip fairness LLM when no HCM/`requires_fairness` context;
  skip debate (Gate 4) unless high-consequence OR confidence within a band of threshold (avoid
  debating a clearly-safe or clearly-blocked action). Wire these as early `continue`s.
- **Verify:** timing shows debate wall-time ≈ max(proposer,opposer)+arbiter, and safe autonomous
  actions skip debate entirely. Re-run `tests/test_debate.py`, `test_gate3_byok_ceiling.py`,
  `test_default_deny.py`, `test_fairness_structural.py` — all green.
- **Anti-pattern:** never skip a gate that could BLOCK; short-circuit only when the gate provably
  cannot change the outcome (e.g., no regulated tags → no compliance violation possible).

## Phase 3 — Cache the deterministic-ish LLM work
Many gate calls repeat for the same inputs (same skill + tags + similar context).
- **Compliance-by-tags cache:** `ComplianceEngine.check_before_execution` is a pure function of
  `(sorted(tags), context-shape)`. Add an in-process TTL cache keyed by a hash of tags + the
  compliance-relevant context fields (not the whole context). Reuse the 30s-cache pattern from
  `services/autonomy_policy.py`.
- **Embedding cache:** cache `nomic-embed-text` results by text hash (RAG re-embeds identical
  chunks). Big win for extraction/RAG paths.
- **Debate memoization (optional):** key by `(skill_id, decision-shape)`; short TTL. Governance-safe
  because it only reuses a *reasoning transcript*, not an approval.
- **Verify:** second identical decision skips the cached LLM calls (timing + a cache-hit counter).
- **Anti-pattern:** never cache a HITL approval, an actuation, or anything tenant-crossing; key
  every cache by `tenant_id` and keep TTLs short.

## Phase 4 — Make long work async, stream the rest
A gated execution that takes minutes should not block an HTTP request or a UI spinner.
- **Missions:** `advance_mission` already does one step per call; move step execution to a
  background task (`asyncio.create_task` with its own `AsyncSessionLocal`, guarded by a per-mission
  running flag) and let the UI poll `GET /missions/{id}` (it already renders live). Mirror the
  existing deployment-reaper background pattern; add crash-recovery like `run_deployment_reaper`.
- **Stream gate progress:** the WS `_emit_gate` events already exist — surface them in the Reality/
  Decisions UI so the user sees "compliance ✓ … debating …" instead of a blank wait.
- **Verify:** launching a mission returns instantly; the UI streams step/gate progress; a killed
  worker leaves no mission stuck (reaper transitions it).
- **Anti-pattern:** no fire-and-forget without crash recovery (that is the bug Phase 3 of v2 fixed).

## Phase 5 — Database & query hygiene
- Grep for N+1s in the new services (missions/actuation/regulatory/causal/time_machine already
  batch — keep it). Add composite indexes for the hottest filters: `skill_executions
  (tenant_id, started_at)`, `mission_steps (mission_id, seq)` (present), `action_records
  (tenant_id, created_at)` (present), `external_signals (tenant_id, created_at)` (present).
- Confirm async pool sizing in `core/database.py` (pool_size/max_overflow) for concurrent gate
  sessions; the mission engine opens its own session — ensure the pool covers it.
- **Verify:** SQL echo shows no per-row query loops on list endpoints; p95 of `/metrics/*`,
  `/regulatory/overview`, `/causal/discover` under ~200ms on the dev DB.

## Phase 6 — Frontend perceived performance
- Add a server-state cache (TanStack Query) so navigating back to a page is instant and refetches
  are deduped/stale-while-revalidate. Start with the heavy reads (Org Pulse, Decisions cockpit,
  analytics). (This is the Phase-6 "server-state library" item from V2_MAJOR_UPGRADE_PLAN.)
- Code-split the heaviest routes (RealityExperience, TwinGraph, analytics) — already lazy; verify
  the main bundle (~294KB) isn't importing them eagerly.
- Memoize expensive chart renders (`React.memo` + stable props) so the new interactive charts don't
  re-render on unrelated state; debounce hover state where needed.
- **Verify:** Lighthouse / bundle report; back-navigation is instant (cache hit); no chart re-render
  storms in the React profiler.

## Phase 7 — Test-suite speed (it is itself a latency problem)
The full backend suite takes >15min because some tests exercise the real model.
- Ensure EVERY LLM-touching test runs under `KAEOS_FAKE_LLM=1` (audit for direct httpx/ollama calls
  that bypass `LLMRouter.complete`'s fake short-circuit; route them through the router or mock).
- Add `pytest-xdist` and run `-n auto` in CI (the suite is I/O-bound and parallelizes well).
- Mark the few genuinely-integration (real-model) tests with `@pytest.mark.slow` and exclude them
  from the default lane; run them nightly.
- **Verify:** `pytest -n auto` on the fake-LLM lane completes in < ~90s, fully green.

## Final verification
1. Phase 0 latency report: before vs after per gate/tier (target: safe autonomous decision < ~5s,
   high-consequence with debate < ~20s on the local 7b).
2. Full governance test suite green (fake-LLM lane) + a real-model smoke of one high-consequence
   decision (verdict unchanged).
3. UI: mission launch instant + streamed progress; back-nav instant; charts smooth.
4. Update README + CHANGELOG per milestone; commit+push each phase.

## Guardrails (do not violate)
- Never weaken a gate to gain speed; only right-size cheap calls, parallelize independent work,
  cache pure functions, and skip gates that provably cannot change the outcome.
- Keep running on real models (no simulated-LLM lane when Ollama is up).
- Every cache/parallel path stays tenant-scoped and fail-closed.
