from typing import Dict, Any

class PII_Scrubber:
    """L1 - Intelligent Ingestion & Signal Extraction"""
    
    def __init__(self):
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()
        except ImportError:
            raise RuntimeError("Microsoft Presidio is required for production PII scrubbing but is not installed.")

    def scrub(self, text: str) -> Dict[str, Any]:
        """Replaces sensitive info with reversible tokens using Presidio."""
        results = self.analyzer.analyze(text=text, entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN"], language='en')
        anonymized_result = self.anonymizer.anonymize(text=text, analyzer_results=results)
        
        return {
            "original_length": len(text),
            "scrubbed_text": anonymized_result.text,
            "pii_present": len(results) > 0
        }

class IngestionPipeline:
    def __init__(self, scrubber: PII_Scrubber):
        self.scrubber = scrubber

    async def process_raw_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Transforms raw source event into clean structured signal."""
        import asyncio
        payload_text = event.get('payload', '')
        
        # 1. PII Scrubbing
        loop = asyncio.get_running_loop()
        scrub_result = await loop.run_in_executor(None, self.scrubber.scrub, payload_text)
        
        # 2. Source Authority Scoring
        authority_score = self._compute_authority(event.get('actor_role'), event.get('domain'))
        
        return {
            "signal_id": f"sig_{event.get('event_id')}",
            "domain": event.get('domain', 'general'),
            "clean_payload": scrub_result['scrubbed_text'],
            "pii_present": scrub_result['pii_present'],
            "authority_score": authority_score
        }

    def _compute_authority(self, role: str, domain: str) -> float:
        role_weights = {"VP": 0.9, "Director": 0.8, "Manager": 0.6, "IC": 0.4}
        return role_weights.get(role, 0.5)
