"""
KAEOS L1 — PII Scrubber Transform (KAEOS Data Fabric)
Uses Microsoft Presidio for real PII detection.

Actions per entity type:
- MASK: Replace with *** — irreversible
- REDACT: Replace with [ENTITY_TYPE] — irreversible, type-preserving
- TOKENIZE: Replace with reversible token
- FLAG: Pass through but record detection
- HALT: Stop pipeline and alert
"""
from app.transforms.base import BaseTransformNode, TransformRecord, TransformResult
import logging
import asyncio
import re

logger = logging.getLogger(__name__)

# Direct, structured identifiers that are reliably regex-detectable. Shared by
# the no-Presidio fallback analyzer AND the deterministic egress backstop, so
# both stay in lock-step. Names / free-text PII are NOT here — those need NER.
STRUCTURED_PII_PATTERNS: dict[str, str] = {
    "EMAIL_ADDRESS": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "US_SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "CREDIT_CARD": r"\b(?:\d[ -]?){13,15}\d\b",
    "PHONE_NUMBER": r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b",
    "IP_ADDRESS": r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b",
    "IBAN_CODE": r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
}


def redact_structured_pii(text: str) -> tuple[str, int]:
    """Deterministically redact structured direct identifiers → ``[ENTITY]``.

    Regex-only (no Presidio dependency), so it is safe to run in the LLM egress
    hot path as a backstop under Presidio's NER — which, at its default
    confidence threshold, can miss a bare phone number or SSN. Returns
    ``(redacted_text, num_redactions)``. Overlapping matches are de-duplicated so
    the reverse-splice never corrupts shifted indices.
    """
    if not text:
        return text, 0
    spans = []
    for ent, pat in STRUCTURED_PII_PATTERNS.items():
        for m in re.finditer(pat, text):
            spans.append((m.start(), m.end(), ent))
    if not spans:
        return text, 0
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept, last_end = [], -1
    for start, end, ent in spans:
        if start >= last_end:
            kept.append((start, end, ent))
            last_end = end
    out = text
    for start, end, ent in sorted(kept, key=lambda s: s[0], reverse=True):
        out = out[:start] + f"[{ent}]" + out[end:]
    return out, len(kept)

# Lazy load Presidio
_presidio_loaded = False
_analyzer_engine = None
_anonymizer_engine = None


def _load_presidio():
    global _presidio_loaded, _analyzer_engine, _anonymizer_engine
    if not _presidio_loaded:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            _analyzer_engine = AnalyzerEngine()
            _anonymizer_engine = AnonymizerEngine()
        except ImportError:
            logger.warning("Microsoft Presidio not installed. Falling back to basic regex PII scrubber.")
            _analyzer_engine = None
            _anonymizer_engine = None
        _presidio_loaded = True


class PIIScrubberNode(BaseTransformNode):
    """
    Detect and handle PII in text content using Microsoft Presidio.

    Config:
        action: "mask" | "redact" | "tokenize" | "flag" | "halt"
        confidence_threshold: float (0.0-1.0) — default 0.85
        entity_types: list[str] — which PII types to detect
        language: str — default "en"
        per_entity_actions: dict — override action per entity type
    """

    DEFAULT_ENTITIES = [
        "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
        "US_SSN", "US_BANK_NUMBER", "IP_ADDRESS", "IBAN_CODE",
        "MEDICAL_LICENSE",
    ]

    def validate_config(self) -> list[str]:
        errors = []
        action = self.config.get("action", "redact")
        if action not in ("mask", "redact", "tokenize", "flag", "halt"):
            errors.append(f"Invalid PII action: {action}")
        threshold = self.config.get("confidence_threshold", 0.85)
        if not (0.0 <= threshold <= 1.0):
            errors.append("confidence_threshold must be between 0.0 and 1.0")
        return errors

    def _regex_analyze(self, text: str, entity_types: list[str]) -> list:
        class RegexResult:
            def __init__(self, entity_type, start, end, score):
                self.entity_type = entity_type
                self.start = start
                self.end = end
                self.score = score
        
        results = []
        # Fallback for when Presidio is not installed — shares the structured
        # identifier patterns with the egress backstop (redact_structured_pii).
        for ent in entity_types:
            pat = STRUCTURED_PII_PATTERNS.get(ent)
            if not pat:
                continue
            for match in re.finditer(pat, text):
                results.append(RegexResult(ent, match.start(), match.end(), 0.9))
        # Drop overlapping matches (keep the earliest-starting / longest) so the
        # reverse-splice anonymization below never corrupts shifted indices — an
        # SSN also partially matching the phone pattern must not double-redact.
        results.sort(key=lambda r: (r.start, -(r.end - r.start)))
        deduped, last_end = [], -1
        for r in results:
            if r.start >= last_end:
                deduped.append(r)
                last_end = r.end
        return deduped

    async def process(self, records: list[TransformRecord]) -> TransformResult:
        _load_presidio()

        action = self.config.get("action", "redact")
        threshold = self.config.get("confidence_threshold", 0.85)
        language = self.config.get("language", "en")
        entity_types = self.config.get("entity_types", self.DEFAULT_ENTITIES)
        per_entity_actions = self.config.get("per_entity_actions", {})

        total_detections = 0
        total_scrubbed = 0
        halt_triggered = False
        processed = []

        for record in records:
            text = record.text_content
            if not text:
                processed.append(record)
                continue

            results = []
            loop = asyncio.get_running_loop()

            if _analyzer_engine is not None:
                # Analyze for PII using Microsoft Presidio
                results = await loop.run_in_executor(
                    None,
                    # Bind loop vars as defaults: the lambda is awaited within this
                    # iteration today, but late-binding would scrub the WRONG record's
                    # text the moment anyone gathers these futures concurrently.
                    lambda text=text: _analyzer_engine.analyze(
                        text=text, language=language,
                        entities=entity_types, score_threshold=threshold,
                    )
                )
            else:
                # Fallback to local regex analysis
                results = self._regex_analyze(text, entity_types)

            if not results:
                processed.append(record)
                continue

            # Record detections
            for result in results:
                record.pii_detections.append({
                    "entity_type": result.entity_type,
                    "start": result.start, "end": result.end,
                    "score": result.score,
                    "action": per_entity_actions.get(result.entity_type, action),
                })
                total_detections += 1

            # Check for HALT
            if action == "halt" or any(
                per_entity_actions.get(r.entity_type) == "halt" for r in results
            ):
                halt_triggered = True
                record.metadata["pii_halt"] = True
                processed.append(record)
                continue

            # Apply anonymization
            if action == "flag":
                record.metadata["pii_flagged"] = True
                record.metadata["pii_count"] = len(results)
            elif action in ("mask", "redact"):
                if _anonymizer_engine is not None:
                    from presidio_anonymizer.entities import OperatorConfig
                    if action == "mask":
                        operators = {"DEFAULT": OperatorConfig("replace", {"new_value": "***"})}
                    else:
                        operators = {"DEFAULT": OperatorConfig("replace", {"new_value": ""})}
                        for entity in entity_types:
                            ea = per_entity_actions.get(entity, action)
                            if ea == "redact":
                                operators[entity] = OperatorConfig("replace", {"new_value": f"[{entity}]"})
                            elif ea == "mask":
                                operators[entity] = OperatorConfig("replace", {"new_value": "***"})

                    anonymized = await loop.run_in_executor(
                        None,
                        lambda text=text, results=results, operators=operators:
                            _anonymizer_engine.anonymize(
                                text=text, analyzer_results=results, operators=operators,
                            )
                    )
                    record.text_content = anonymized.text
                    total_scrubbed += len(results)
                else:
                    # Fallback basic anonymization
                    results.sort(key=lambda r: r.start, reverse=True)
                    new_text = text
                    for r in results:
                        ent_action = per_entity_actions.get(r.entity_type, action)
                        val = ""
                        if ent_action == "mask":
                            val = "***"
                        elif ent_action == "redact":
                            val = f"[{r.entity_type}]"
                        new_text = new_text[:r.start] + val + new_text[r.end:]
                    record.text_content = new_text
                    total_scrubbed += len(results)

            self.add_lineage(record, f"pii_scrubbed:{action}:{len(results)}_entities")
            processed.append(record)

        return TransformResult(
            records=processed,
            stats={
                "total_records": len(records),
                "total_pii_detections": total_detections,
                "total_pii_scrubbed": total_scrubbed,
                "halt_triggered": halt_triggered,
            },
            errors=[{"type": "pii_halt", "message": "Pipeline halted due to PII detection"}]
            if halt_triggered else [],
        )
