# Bring Your Own Model (BYOK) - the platform adapts to your model

Back to the [README](../README.md). Related: [Architecture](ARCHITECTURE.md) |
[Security model](SECURITY_MODEL.md)

KAEOS is model-agnostic via LiteLLM (OpenAI, Anthropic, Mistral, Groq, Cohere, Azure, self-hosted
Ollama, or any OpenAI-compatible endpoint). But "bring your own model" is a quality lottery unless
the platform knows what your model can actually do. So it measures.

## Configure -> probe -> the gates adapt

```
PUT  /config/llm-routing              # your model + key for a tier (key encrypted at rest)
POST /config/llm-routing/{tier}/probe # calibrate it
GET  /config/llm-routing              # capability profile - never returns the key
```

The probe runs a small battery - JSON compliance, multi-step reasoning, strict instruction
following - and produces a **`tier_ceiling`**: the maximum confidence any decision may claim on that
model. A weaker model earns a lower ceiling, which pushes its decisions below the 0.82 HITL
threshold and routes them to a human **automatically**.

## Tiers

| Tier | Powers |
|------|--------|
| `TIER_1_COMPLEX` | Debates, fairness scoring, blueprint generation, agent reasoning |
| `TIER_2_STANDARD` | Extraction, summarization, explainability |
| `TIER_3_FAST` | Intent routing, formatting, simple operations |
| `TIER_EMBEDDING` | Vector search and retrieval |

## The measured ceiling, demonstrated

Measured example - `phi4-mini` probes at a **0.70 ceiling**: it solves multi-step arithmetic
perfectly (1.0) but fails strict instruction-following (0.0) and wraps JSON in prose (0.75). Put it
on the reasoning tier and an identical high-confidence skill flips from `SUCCESS_CLEAN` to
`PENDING_HITL`. Swap to a stronger model and autonomy returns.

The ceiling is enforced at **Gate 3 of the agent pipeline itself** - every domain agent (finance,
legal, sales, support, operations, engineering) inherits it, not just the `/skills` routes. A weak
model mechanically routes more of the whole platform's decisions to humans. If the ceiling lookup
itself fails (cache or store outage), the gate fails closed: a conservative failsafe ceiling below
the autonomous-execution threshold is applied, routing decisions to a human until the lookup
recovers.

**Model choice becomes a governance dial, not a gamble.** An unprobed tier imposes no cap, changing
a model invalidates its stale profile, and keys are Fernet-encrypted, write-only, and tenant-scoped.
The local default is `qwen2.5-coder:7b` (strong strict-JSON compliance, fits a 6GB GPU).

## Data residency

`DATA_RESIDENCY` pins inference to a local Ollama-only model and strips every cloud
credential/endpoint; pre-egress PII scrubbing applies to every cloud LLM call by default.
See [Connectors - PII handling](CONNECTORS.md#pii-handling).
