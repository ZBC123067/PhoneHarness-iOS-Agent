#!/usr/bin/env python3
"""Static boundary tests for TEST-22 Vision and OCR observation providers."""

from __future__ import annotations

import json
import unittest

from phoneharness_agent import (
    AXObservationProvider,
    OCRObservationProvider,
    Observation,
    ObservationProvider,
    ObservationProviderRouter,
    ObservationUnavailable,
    ObservationVerifier,
    VLMObservationProvider,
    VisionObservationProvider,
)


def empty_ax_payload() -> dict[str, object]:
    return {"source": "accessibility", "element_count": 0, "elements": []}


class RecordingProvider(ObservationProvider):
    def __init__(self, source: str, calls: list[str], observation: Observation) -> None:
        self.source = source
        self.calls = calls
        self.observation = observation

    def observe(self, read_screen):  # type: ignore[no-untyped-def]
        del read_screen
        self.calls.append(self.source)
        return self.observation


class VisionOCRProviderTests(unittest.TestCase):
    def test_default_provider_registration_preserves_the_declared_order(self) -> None:
        router = ObservationProviderRouter()
        self.assertEqual(["AX", "Vision", "OCR", "VLM"], [provider.source for provider in router.providers])

    def test_ax_with_safe_elements_prevents_visual_and_ocr_reads(self) -> None:
        visual_reads: list[str] = []
        ocr_reads: list[str] = []
        router = ObservationProviderRouter(
            (
                AXObservationProvider(),
                VisionObservationProvider(lambda: visual_reads.append("Vision") or {"regions": []}),
                OCRObservationProvider(lambda: ocr_reads.append("OCR") or {"ocr_texts": []}),
                VLMObservationProvider(),
            )
        )
        observation = router.observe(
            lambda: {"elements": [{"type": "AXButton", "clickable": True}]}
        )
        self.assertEqual("AX", observation.source)
        self.assertEqual([], visual_reads)
        self.assertEqual([], ocr_reads)

    def test_empty_ax_falls_back_to_vision_and_discards_region_data(self) -> None:
        reads: list[str] = []
        router = ObservationProviderRouter(
            (
                AXObservationProvider(),
                VisionObservationProvider(
                    lambda: reads.append("Vision")
                    or {
                        "regions": [
                            {
                                "kind": "button",
                                "text": "private label",
                                "rect": {"x": 1, "y": 2, "width": 3, "height": 4},
                                "confidence": 0.92,
                                "actionable": True,
                            }
                        ]
                    }
                ),
                OCRObservationProvider(),
            )
        )
        observation = router.observe(empty_ax_payload)
        self.assertEqual("Vision", observation.source)
        self.assertEqual(["Vision"], reads)
        self.assertEqual([{"role": "button", "interactive": True}], observation.schema()["elements"])
        self.assertEqual(("button",), observation.semantic_labels)
        self.assertEqual(0.92, observation.confidence)

    def test_empty_ax_and_unavailable_vision_fall_back_to_ocr(self) -> None:
        router = ObservationProviderRouter(
            (
                AXObservationProvider(),
                VisionObservationProvider(),
                OCRObservationProvider(
                    lambda: {
                        "ocr_texts": [
                            {
                                "text": "private OCR content",
                                "confidence": 0.81,
                                "rect": {"x": 1, "y": 2, "width": 3, "height": 4},
                                "tap": {"x": 2, "y": 3},
                            }
                        ]
                    }
                ),
            )
        )
        observation = router.observe(empty_ax_payload)
        self.assertEqual("OCR", observation.source)
        self.assertEqual([{"role": "text", "interactive": False}], observation.schema()["elements"])
        self.assertEqual(0.81, observation.confidence)
        self.assertTrue(ObservationVerifier().verify_nonempty(observation)["passed"])

    def test_vision_and_ocr_schema_never_retain_sensitive_or_replay_fields(self) -> None:
        observations = (
            VisionObservationProvider(
                lambda: {"regions": [{"kind": "image", "screenshot": "private", "frame": [1, 2]}]}
            ).observe(lambda: {}),
            OCRObservationProvider(
                lambda: {"ocr_texts": [{"text": "private", "password": "secret", "tap": {"x": 1}}]}
            ).observe(lambda: {}),
        )
        forbidden = (
            "private",
            "secret",
            '"password"',
            '"rect"',
            '"frame"',
            '"tap"',
            '"screenshot"',
        )
        for observation in observations:
            serialized = json.dumps(observation.schema(), ensure_ascii=False).casefold()
            for field in forbidden:
                self.assertNotIn(field, serialized)

    def test_empty_fallback_results_do_not_count_as_an_observation(self) -> None:
        router = ObservationProviderRouter(
            (
                AXObservationProvider(),
                VisionObservationProvider(lambda: {"regions": []}),
                OCRObservationProvider(lambda: {"ocr_texts": []}),
            )
        )
        with self.assertRaisesRegex(ObservationUnavailable, "insufficient safe semantic elements"):
            router.observe(empty_ax_payload)

    def test_provider_source_mismatch_remains_rejected_after_fallback(self) -> None:
        calls: list[str] = []
        unsafe = RecordingProvider(
            "Vision",
            calls,
            Observation(
                source="OCR",
                timestamp=1,
                confidence=0.9,
                elements=({"role": "text", "interactive": False},),
                semantic_labels=("text",),
            ),
        )
        with self.assertRaisesRegex(ObservationUnavailable, "mismatched source"):
            ObservationProviderRouter((unsafe,)).observe(empty_ax_payload)
        self.assertEqual(["Vision"], calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
