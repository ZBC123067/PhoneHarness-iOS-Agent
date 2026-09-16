#!/usr/bin/env python3
"""Static boundary tests for TEST-23 Semantic Observation Layer."""

from __future__ import annotations

import json
import unittest

from phoneharness_agent import (
    Observation,
    ObservationUnavailable,
    SemanticObservation,
    SemanticObservationIntelligence,
)


def observation(
    elements: tuple[dict[str, object], ...],
    *,
    source: str = "AX",
    confidence: float = 0.9,
) -> Observation:
    return Observation(
        source=source,
        timestamp=123,
        confidence=confidence,
        elements=elements,
        semantic_labels=tuple(sorted({str(element["role"]) for element in elements})),
    )


class SemanticObservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intelligence = SemanticObservationIntelligence()

    def test_search_page_classifies_intent_and_actionability(self) -> None:
        summary = self.intelligence.summarize(
            observation(({"role": "search_field", "interactive": True}, {"role": "button", "interactive": True}))
        )
        self.assertEqual("search", summary.page_type)
        self.assertTrue(summary.actionable)
        self.assertEqual(
            [
                {"intent": "activate", "count": 1, "actionable": True},
                {"intent": "search", "count": 1, "actionable": True},
            ],
            summary.schema()["intents"],
        )

    def test_text_field_is_a_form_without_reading_input_content(self) -> None:
        summary = self.intelligence.summarize(
            observation(({"role": "text_field", "interactive": True}, {"role": "text", "interactive": False}))
        )
        self.assertEqual("form", summary.page_type)
        self.assertEqual(
            [{"intent": "inspect", "count": 1, "actionable": False}, {"intent": "text_entry", "count": 1, "actionable": True}],
            summary.schema()["intents"],
        )

    def test_switch_and_slider_identify_a_settings_page(self) -> None:
        summary = self.intelligence.summarize(
            observation(({"role": "switch", "interactive": True}, {"role": "slider", "interactive": False}))
        )
        self.assertEqual("settings", summary.page_type)
        self.assertEqual(
            [
                {"intent": "adjust", "count": 1, "actionable": False},
                {"intent": "toggle", "count": 1, "actionable": True},
            ],
            summary.schema()["intents"],
        )

    def test_visual_page_has_only_aggregate_inspection_metadata(self) -> None:
        summary = self.intelligence.summarize(
            observation(({"role": "image", "interactive": False}, {"role": "text", "interactive": False}))
        )
        self.assertEqual("visual", summary.page_type)
        self.assertFalse(summary.actionable)
        self.assertEqual([{"intent": "inspect", "count": 2, "actionable": False}], summary.schema()["intents"])

    def test_unknown_role_reduces_confidence_without_exposing_element_identity(self) -> None:
        summary = self.intelligence.summarize(
            observation(({"role": "other", "interactive": False},), confidence=0.8)
        )
        self.assertEqual("content", summary.page_type)
        self.assertEqual(0.52, summary.confidence)
        self.assertEqual([{"intent": "unknown", "count": 1, "actionable": False}], summary.schema()["intents"])

    def test_summary_rejects_private_observation_fields_before_classification(self) -> None:
        private_observation = Observation(
            source="AX",
            timestamp=123,
            confidence=0.9,
            elements=({"role": "button", "interactive": True, "text": "private"},),
            semantic_labels=("button",),
        )
        with self.assertRaisesRegex(ObservationUnavailable, "unsupported fields"):
            self.intelligence.summarize(private_observation)

    def test_public_schema_excludes_content_and_replay_data(self) -> None:
        summary = self.intelligence.summarize(
            observation(({"role": "button", "interactive": True}, {"role": "button", "interactive": False}))
        )
        serialized = json.dumps(summary.schema(), ensure_ascii=False).casefold()
        self.assertEqual(
            {"source", "timestamp", "confidence", "page_type", "intents", "actionable"},
            set(summary.schema()),
        )
        for forbidden in (
            '"text"',
            '"label"',
            '"value"',
            '"password"',
            '"input"',
            '"rect"',
            '"frame"',
            '"tap"',
            '"screenshot"',
            '"ocr"',
            '"raw_response"',
            '"role"',
            '"index"',
        ):
            self.assertNotIn(forbidden, serialized)

    def test_future_semantic_schema_private_fields_are_rejected(self) -> None:
        private_summary = SemanticObservation(
            source="AX",
            timestamp=123,
            confidence=0.9,
            page_type="content",
            intents=({"intent": "activate", "count": 1, "actionable": True, "rect": {"x": 1}},),
            actionable=True,
        )
        with self.assertRaisesRegex(ObservationUnavailable, "unsupported fields"):
            private_summary.validate_public_schema()


if __name__ == "__main__":
    unittest.main(verbosity=2)
