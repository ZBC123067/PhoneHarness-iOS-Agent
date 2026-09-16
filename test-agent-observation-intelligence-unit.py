#!/usr/bin/env python3
"""Static boundary tests for TEST-21 Observation Intelligence Layer."""

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


def payload() -> dict[str, object]:
    return {
        "source": "accessibility",
        "element_count": 2,
        "elements": [
            {
                "role": "AXButton",
                "text": "Private Account Name",
                "value": "secret-value",
                "password": "secret-password",
                "rect": {"x": 1, "y": 2},
                "clickable": True,
            },
            {"type": "AXStaticText", "label": "Private message"},
        ],
    }


class StaticObservationProvider(ObservationProvider):
    def __init__(self, source: str, calls: list[str], unavailable: bool = False) -> None:
        self.source = source
        self.calls = calls
        self.unavailable = unavailable

    def observe(self, read_screen):  # type: ignore[no-untyped-def]
        self.calls.append(self.source)
        if self.unavailable:
            raise ObservationUnavailable("synthetic unavailable")
        del read_screen
        return Observation(
            source=self.source,
            timestamp=1,
            confidence=0.9,
            elements=({"role": "button", "interactive": True},),
            semantic_labels=("button",),
        )


class ObservationIntelligenceTests(unittest.TestCase):
    def test_ax_provider_returns_the_public_schema(self) -> None:
        observation = AXObservationProvider().observe(payload)
        self.assertEqual("AX", observation.source)
        self.assertEqual(0.95, observation.confidence)
        self.assertEqual(("button", "text"), observation.semantic_labels)
        self.assertEqual(
            [{"role": "button", "interactive": True}, {"role": "text", "interactive": False}],
            observation.schema()["elements"],
        )

    def test_vision_ocr_and_vlm_interfaces_do_not_read_the_screen(self) -> None:
        reads = []

        def forbidden_read():  # type: ignore[no-untyped-def]
            reads.append("read")
            raise AssertionError("unavailable provider must not request an observation")

        for provider in (VisionObservationProvider(), OCRObservationProvider(), VLMObservationProvider()):
            with self.assertRaises(ObservationUnavailable):
                provider.observe(forbidden_read)
        self.assertEqual([], reads)

    def test_router_falls_back_in_the_declared_priority_order(self) -> None:
        calls: list[str] = []
        router = ObservationProviderRouter(
            (
                StaticObservationProvider("AX", calls, unavailable=True),
                StaticObservationProvider("Vision", calls),
                StaticObservationProvider("OCR", calls),
            )
        )
        observation = router.observe(payload)
        self.assertEqual("Vision", observation.source)
        self.assertEqual(["AX", "Vision"], calls)

    def test_router_rejects_out_of_order_providers(self) -> None:
        with self.assertRaises(ValueError):
            ObservationProviderRouter((VisionObservationProvider(), AXObservationProvider()))

    def test_router_rejects_future_provider_private_fields(self) -> None:
        class UnsafeProvider(ObservationProvider):
            source = "Vision"

            def observe(self, read_screen):  # type: ignore[no-untyped-def]
                del read_screen
                return Observation(
                    source="Vision",
                    timestamp=1,
                    confidence=0.9,
                    elements=({"role": "button", "interactive": True, "text": "private"},),
                    semantic_labels=("button",),
                )

        with self.assertRaises(ObservationUnavailable):
            ObservationProviderRouter((UnsafeProvider(),)).observe(payload)

    def test_privacy_filter_removes_content_and_replay_data(self) -> None:
        serialized = json.dumps(AXObservationProvider().observe(payload).schema(), ensure_ascii=False).casefold()
        for forbidden in (
            "private account name",
            "private message",
            "secret-value",
            "secret-password",
            '"rect":',
            '"password":',
            '"text":',
            '"label":',
            '"value":',
        ):
            self.assertNotIn(forbidden, serialized)

    def test_verifier_consumes_without_mutating_observation(self) -> None:
        observation = AXObservationProvider().observe(payload)
        before = observation.schema()
        result = ObservationVerifier().verify_nonempty(observation)
        self.assertTrue(result["passed"])
        self.assertEqual("AX", result["source"])
        self.assertEqual(before, observation.schema())


if __name__ == "__main__":
    unittest.main(verbosity=2)
