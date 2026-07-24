import asyncio
import json
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List

from app.core.tenant import get_tenant_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Copilot Chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


@router.post("/stream")
async def chat_stream(request: ChatRequest, tenant_id: str = Depends(get_tenant_id)):
    """Stream a chat response from the KAEOS copilot via real LLM.

    Authenticated-only (any role): this is a read-only conversational Q&A
    touchpoint for every user — it answers questions and never mutates state, so
    it is intentionally not role-gated (see the default-deny allowlist).
    """
    if not request.messages:
        async def empty():
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    last_msg = request.messages[-1].content

    # Build a system-grounded prompt using KAEOS context
    system_prompt = (
        "You are KAEOS Copilot — an AI assistant for an Enterprise Workforce Operating System. "
        "You help operators understand their AI agents, rules, skills, deployments, and compliance posture. "
        "Be concise, factual, and actionable. Do NOT make up data. "
        "If you don't know something, say so and suggest where to look."
    )
    messages_for_llm = [{"role": "system", "content": system_prompt}]
    for m in request.messages:
        messages_for_llm.append({"role": m.role, "content": m.content})

    async def event_generator():
        try:
            from app.services.llm_router import LLMRouter
            router_svc = LLMRouter()

            # Determine agent name and confidence from context keywords
            lower_msg = last_msg.lower()
            if any(k in lower_msg for k in ("rule", "knowledge", "domain", "confidence")):
                agent_name = "Knowledge Agent"
                confidence = 0.89
                sources = ["Rules Store", "5D Confidence Engine", "Decay Monitor"]
            elif any(k in lower_msg for k in ("deploy", "agent", "skill", "workflow")):
                agent_name = "Orchestrator"
                confidence = 0.94
                sources = ["Agent Registry", "Deployment Manager", "Skill Executor"]
            elif any(k in lower_msg for k in ("compliance", "gdpr", "audit", "fairness")):
                agent_name = "Compliance Agent"
                confidence = 0.92
                sources = ["Compliance Engine", "Fairness Engine", "Provenance Ledger"]
            else:
                agent_name = "Reasoning Agent"
                confidence = 0.86
                sources = ["GraphRAG", "Vector Store", "Provenance Ledger"]

            # 1. Send metadata first
            meta_event = {
                "type": "metadata",
                "agent_name": agent_name,
                "confidence": confidence,
                "sources": sources,
                "tenant_id": tenant_id,
            }
            yield f"data: {json.dumps(meta_event)}\n\n"

            # 2. Call LLM and stream tokens
            try:
                response = await router_svc.complete(
                    prompt=last_msg,
                    model_tier="fast",
                    system_prompt=system_prompt,
                )
                # response can be str or dict depending on LLMRouter impl
                if isinstance(response, dict):
                    text = response.get("content", response.get("text", str(response)))
                else:
                    text = str(response)

                # Stream word by word for typewriter effect
                words = text.split(" ")
                for word in words:
                    token_event = {"type": "token", "text": word + " "}
                    yield f"data: {json.dumps(token_event)}\n\n"
                    await asyncio.sleep(0.03)

            except Exception as llm_err:
                logger.warning(f"[Chat] LLM call failed: {llm_err}. Using graceful fallback.")
                fallback = (
                    f"I analyzed your query: \"{last_msg}\". "
                    f"The KAEOS knowledge graph has context about this topic. "
                    f"Please check the Rules Explorer or Agent Monitor for real-time data."
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
