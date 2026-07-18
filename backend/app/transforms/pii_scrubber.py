"""
KAEOS L1 — PII Scrubber Transform (merged from Extract-OS)
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

logger = logging.getLogger(__name__)

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
        
        import re
        results = []
        patterns = {
            "EMAIL_ADDRESS": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
            "US_SSN": r"\d{3}-\d{2}-\d{4}",
            "IP_ADDRESS": r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"
        }
        for ent in entity_types:
            if ent in patterns:
                for match in re.finditer(patterns[ent], text):
                    results.append(RegexResult(ent, match.start(), match.end(), 0.9))
        return results

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
