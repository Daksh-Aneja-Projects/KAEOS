# Demo Video (placeholder)

Back to the [README](../README.md).

The README links here for the product demo. The video is not yet recorded; this
stub defines what it should show so the recording has a target.

## Target: one continuous 3-4 minute capture of a running instance

1. **Dashboard (15s).** Open on the workforce dashboard: safe-autonomy rate,
   live departments, earned-autonomy skills. State that this is a live app on a
   seeded demo tenant against PostgreSQL, not a mockup.
2. **A governed decision end to end (60s).** Trigger a department agent action
   (e.g. a contract review at 0.75 confidence). Show the gate trace: compliance,
   fairness, confidence. Show it pause at `PENDING_HITL`, approve it in the HITL
   queue, and show the resumed execution and its provenance entry.
3. **The measured ceiling (60s).** The single most differentiated moment: switch
   the reasoning tier to `phi4-mini`, run the probe, show the 0.70 ceiling, then
   re-run the same high-confidence skill and watch `SUCCESS_CLEAN` flip to
   `PENDING_HITL`. Swap back to `qwen2.5-coder:7b` and autonomy returns.
4. **A mission (45s).** Enter a plain-language goal in Mission Control; show the
   cross-department plan, an autonomous step completing, and a high-consequence
   step pausing at a human checkpoint.
5. **Honesty beat (20s).** Show `hours_saved: null` in the ROI response and the
   benchmark table that includes losses. Say why: invented numbers are worse
   than absent ones.
6. **Close (10s).** The Foresight board or the enterprise twin under a shock,
   whichever demos better on the day.

## Recording notes

- Record against the seeded demo tenant with Ollama running locally so gate
  latencies are real but tolerable; cut dead air between model calls.
- Capture at 1080p minimum; keep the browser at 100% zoom.
- No audio narration required for the first cut; on-screen captions suffice.
- When recorded, embed or link it from the README section "Demo".
