"""
Shared tolerant JSON extraction for LLM output.

Model families differ in how they wrap JSON: some emit clean objects, some wrap
in markdown fences, some prepend prose. Under load, even the same model varies.
Every service that parses model output must go through here — a bare
json.loads(content) on LLM output is a latent 500 (this bug class has bitten
ExplainabilityEngine and others).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Union

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.search(text)
    return match.group(1).strip() if match else text.strip()


def extract_json(content: str) -> Union[Dict[str, Any], List[Any]]:
    """
    Extract a JSON object or array from raw model output.
    Raises ValueError when nothing parseable is present.
    """
    if content is None:
        raise ValueError("No content to parse")

    text = _strip_fences(str(content))

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost object/array span present in the text.
    candidates = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            candidates.append((start, text[start:end + 1]))

    # Prefer whichever structure appears first in the output.
    for _, snippet in sorted(candidates):
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Could not extract JSON from model output: {text[:200]}")


def compact_context(
    context: Dict[str, Any],
    max_chars: int = 6000,
    priority_keys: tuple = ("instruction", "intent", "task_intent"),
    drop_keys: tuple = ("_skill_obj", "execution_id", "tenant_id"),
) -> str:
    """
    Render an execution context for an LLM prompt without losing the parts that
    steer the model.

    The previous approach was ``str(context)[:600]``. That is a Python repr
    sliced mid-token, and because dict order puts short control fields last, the
    ``instruction`` ("output strict JSON…") was routinely cut off entirely while
    a candidate's resume ate the budget. The model then got a mangled fragment
    and no output contract — a large share of "LLM returned bad JSON" failures.

    Here: control fields are emitted FIRST and never trimmed; bulky payload
    fields are trimmed individually so every key stays visible and the structure
    stays parseable.
    """
    if not context:
        return "{}"

    payload = {k: v for k, v in context.items() if k not in drop_keys}

    head = {k: payload.pop(k) for k in priority_keys if k in payload}
    head_str = json.dumps(head, default=str) if head else ""
    remaining = max(500, max_chars - len(head_str))

    # Share the remaining budget across the bulky fields rather than letting the
    # first long value consume all of it.
    bulky = {k: v for k, v in payload.items()}
    per_field = max(200, remaining // max(len(bulky), 1))

    body = {}
    for k, v in bulky.items():
        s = v if isinstance(v, str) else json.dumps(v, default=str)
        body[k] = s if len(s) <= per_field else s[:per_field] + f"…[+{len(s) - per_field} chars]"

    rendered = {**head, **body}
    return json.dumps(rendered, default=str, indent=None)


def extract_json_object(content: str) -> Dict[str, Any]:
    """extract_json(), but guarantees a dict."""
    parsed = extract_json(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")
    return parsed


def extract_json_list(content: str) -> List[Any]:
    """extract_json(), but guarantees a list."""
    parsed = extract_json(content)
    if isinstance(parsed, dict):
        return [parsed]
    if not isinstance(parsed, list):
        raise ValueError(f"Expected a JSON array, got {type(parsed).__name__}")
    return parsed

def plain_facts(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize ORM column values to JSON-safe primitives for LLM prompts.

    Decimal reprs like Decimal('10500.00') leak into f-string prompts and the
    model mimics them back, producing unparseable JSON. Enums and dates get the
    same treatment so a facts dict always serializes cleanly.
    """
    from datetime import date, datetime
    from decimal import Decimal

    def _norm(v: Any) -> Any:
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, (date, datetime)):
            return str(v)
        if isinstance(v, dict):
            return {k: _norm(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_norm(x) for x in v]
        if hasattr(v, "value") and not isinstance(v, (str, int, float, bool)):
            return v.value
        return v

    return {k: _norm(v) for k, v in facts.items()}

