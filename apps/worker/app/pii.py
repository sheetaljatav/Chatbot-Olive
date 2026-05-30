"""PII redaction wrapper around Presidio.

We don't lazy-load Presidio per call — its engines are expensive to construct.
Build once at process start; redact() is the hot path.
"""
from __future__ import annotations

import logging
from typing import Iterable

log = logging.getLogger("worker.pii")


class Redactor:
    def __init__(self, *, enabled: bool, entities: Iterable[str]) -> None:
        self.enabled = enabled
        self.entities = list(entities)
        self._analyzer = None
        self._anonymizer = None
        if not self.enabled:
            return
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine

            # Pin the spaCy model to en_core_web_sm — the one the Dockerfile
            # installs. AnalyzerEngine() with no args defaults to en_core_web_lg
            # and triggers a ~400MB download on every process start.
            nlp_engine = NlpEngineProvider(
                nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
                }
            ).create_engine()
            self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
            self._anonymizer = AnonymizerEngine()
        except Exception as exc:  # noqa: BLE001
            log.warning("Presidio unavailable, falling back to no-op redaction: %s", exc)
            self.enabled = False

    def redact(self, text: str | None) -> str | None:
        if text is None or not self.enabled or self._analyzer is None or self._anonymizer is None:
            return text
        try:
            results = self._analyzer.analyze(text=text, entities=self.entities, language="en")
            if not results:
                return text
            anon = self._anonymizer.anonymize(text=text, analyzer_results=results)
            return anon.text
        except Exception as exc:  # noqa: BLE001
            log.warning("redaction failed, returning original: %s", exc)
            return text
