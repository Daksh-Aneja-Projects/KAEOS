import asyncio
import json
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Literal

from app.core.tenant import get_tenant_id
from app.services import prompt_guard

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Copilot Chat"])

# Namespaces in the polystore that hold real tenant content the copilot may cite.
_GROUNDING_NAMESPACES = ("enterprise_memory", "hr_kb")
# Below this cosine similarity a hit is not evidence of anything; citing it would
# manufacture the appearance of grounding.
_MIN_SIMILARITY = 0.35
# Bound the transcript so a long thread cannot blow the context window.
_MAX_HISTORY_TURNS = 12

SYSTEM_PROMPT = (
    "You are KAEOS Copilot, an AI assistant for an Enterprise Workforce Operating System. "
    "You help operators understand their AI agents, rules, skills, deployments, and compliance posture. "
    "Be concise, factual, and actionable. Do NOT make up data. "
    "Only state a fact about this tenant if it appears in the retrieved context below. "
    "If you don't know something, say so and suggest where to look."
)


class ChatMessage(BaseModel):
    # The client submits the whole transcript, so an unconstrained role let a
    # caller label a turn "system" and have it rendered above ASSISTANT:.
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


async def _retrieve_grounding(tenant_id: str, query: str, limit: int = 4) -> list[dict]:
    """Tenant-scoped semantic recall over the polystore vector store.

    Returns [] when nothing relevant is stored, so the copilot cites nothing
    rather than naming stores it never queried. Simulated (pseudo-vector)
    embeddings are treated as no grounding at all: they are seeded hashes with
    no semantic meaning, so any "match" they produce is noise, not evidence.
    """
    try:
        from app.core.polystore import get_vector_store
        from app.services.llm_router import get_tenant_router

        llm = await get_tenant_router(tenant_id)
        embedding = (await llm.embed([query]))[0]
        if llm.embeddings_simulated:
            logger.info("[Chat] embeddings are simulated; reporting no grounding.")
            return []

        store = get_vector_store()
        hits: list[dict] = []
        for namespace in _GROUNDING_NAMESPACES:
            for r in await store.search(
                tenant_id=tenant_id, query_embedding=embedding,
                limit=limit, namespace=namespace,
            ):
                score = float(r.get("similarity") or 0.0)
                if r.get("content") and score >= _MIN_SIMILARITY:
                    hits.append({
                        "namespace": namespace,
                        "id": r["id"],
                        "score": round(score, 3),
                        "content": r["content"],
                    })
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]
    except Exception as e:
        logger.warning(f"[Chat] grounding retrieval failed: {e}; answering ungrounded.")
        return []


def _build_prompt(messages: List[ChatMessage], hits: list[dict]) -> str:
    """Transcript + fenced retrieved context. User turns are injection-neutralized."""
    parts: list[str] = []
    if hits:
        # Retrieved chunks are stored content, not instructions: fence them.
        context = "\n\n".join(
            f"[{h['namespace']} :: {h['id']}]\n{h['content']}" for h in hits
        )
        parts.append(
            "Retrieved context from this tenant's own records:\n"
            + prompt_guard.wrap_untrusted(context)
        )
    else:
        parts.append(
            "Retrieved context: NONE. Nothing in this tenant's records matched the "
            "question. Say so plainly and do not invent specifics about this tenant."
        )

    parts.append("Conversation so far:")
    for m in messages[-_MAX_HISTORY_TURNS:]:
        # Every turn is neutralised, not just the ones labelled "user". The
        # whole transcript is client-supplied, so gating on the role meant the
        # guard could be skipped by relabelling the turn.
        content, scan = prompt_guard.neutralize(m.content)
        if scan.detected:
            logger.warning(
                "[Chat] injection patterns in %s turn (risk=%s categories=%s); neutralized.",
                m.role, scan.risk.value, scan.categories,
            )
        parts.append(f"{m.role.upper()}: {content}")
    parts.append("ASSISTANT:")
    return "\n".join(parts)


@router.post("/stream")
async def chat_stream(request: ChatRequest, tenant_id: str = Depends(get_tenant_id)):
    """Stream a chat response from the KAEOS copilot via real LLM.

    Authenticated-only (any role): this is a read-only conversational Q&A
    touchpoint for every user. It answers questions and never mutates state, so
    it is intentionally not role-gated (see the default-deny allowlist).

    Trust signals are earned, not decorated: ``sources`` are the vector records
    actually retrieved for this question (with their real similarity scores), and
    an ungrounded answer says so instead of citing stores it never queried.
    """
    if not request.messages:
        async def empty():
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    last_msg = request.messages[-1].content

    async def event_generator():
        try:
            from app.services.llm_router import get_tenant_router
            router_svc = await get_tenant_router(tenant_id)

            # 1. Retrieve REAL grounding, then report exactly what was found.
            hits = await _retrieve_grounding(tenant_id, last_msg)
            meta_event = {
                "type": "metadata",
                "agent_name": "KAEOS Copilot",
                # Human-readable citation chips: where it came from and how close it matched.
                "sources": [
                    f"{h['namespace']} · {h['id']} ({round(h['score'] * 100)}% match)"
                    for h in hits
                ],
                "grounded": bool(hits),
                "tenant_id": tenant_id,
            }
            yield f"data: {json.dumps(meta_event)}\n\n"

            # 2. Call LLM with the full conversation and stream tokens.
            try:
                response = await router_svc.complete(
                    prompt=_build_prompt(request.messages, hits),
                    model_tier="fast",
                    system_prompt=SYSTEM_PROMPT,
                )
                # response can be str or dict depending on LLMRouter impl
                if isinstance(response, dict):
                    text = response.get("content", response.get("text", str(response)))
                else:
                    text = str(response)

                # Stream word by word for typewriter effect
                for word in text.split(" "):
                    token_event = {"type": "token", "text": word + " "}
                    yield f"data: {json.dumps(token_event)}\n\n"
                    await asyncio.sleep(0.03)

            except Exception as llm_err:
                logger.warning(f"[Chat] LLM call failed: {llm_err}. Reporting honestly.")
                fallback = (
                    "I am unable to answer that right now: the language model behind "
                    "this copilot is unreachable. I have not guessed an answer in its "
                    "place. Please try again shortly, or open the relevant page "
                    "directly to see live data."
                )
                for word in fallback.split(" "):
                    yield f"data: {json.dumps({'type': 'token', 'text': word + ' '})}\n\n"
                    await asyncio.sleep(0.03)

        except Exception as e:
            logger.error(f"[Chat] Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        # 3. Done event
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
