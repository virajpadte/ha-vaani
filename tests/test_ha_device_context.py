"""Tests for Home Assistant exposed-device context parsing and fuzzy matching."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1] / "addons" / "pipecat_assist"
if ADDON_ROOT.is_dir():
    sys.path.insert(0, str(ADDON_ROOT))

from app.ha_device_context import (  # noqa: E402
    build_device_list_text,
    build_fallback_message,
    build_no_candidate_message,
    find_best_match,
    is_match_failed,
    parse_live_context,
    transliterate_devanagari,
)

# A realistic GetLiveContext fixture matching HA's confirmed output shape:
# ToolResult(data={"result": "Live Context: ...\n" + yaml.dump(entities)}).
_LIVE_CONTEXT_YAML = (
    "- names: Stream Lights, Stream\n"
    "  domain: light\n"
    "  areas: Office\n"
    "  state: 'off'\n"
    "- names: Deck Lights\n"
    "  domain: light\n"
    "  areas: Deck\n"
    "  state: 'on'\n"
    "- names: Office Fan\n"
    "  domain: fan\n"
    "  areas: Office\n"
    "  state: 'off'\n"
)
_LIVE_CONTEXT_PREAMBLE = "Live Context: An overview of the areas and the devices in this smart home:\n"


def _sample_entities() -> list[dict]:
    return parse_live_context(json.dumps({"result": _LIVE_CONTEXT_PREAMBLE + _LIVE_CONTEXT_YAML}))


class ParseLiveContextTests(unittest.TestCase):
    def test_parses_json_enveloped_yaml(self):
        entities = _sample_entities()
        self.assertEqual(
            entities,
            [
                {"name": "Stream Lights", "aliases": ["Stream"], "domain": "light", "areas": ["Office"]},
                {"name": "Deck Lights", "aliases": [], "domain": "light", "areas": ["Deck"]},
                {"name": "Office Fan", "aliases": [], "domain": "fan", "areas": ["Office"]},
            ],
        )

    def test_parses_raw_yaml_without_json_envelope(self):
        entities = parse_live_context(_LIVE_CONTEXT_YAML)
        self.assertEqual(len(entities), 3)
        self.assertEqual(entities[0]["name"], "Stream Lights")

    def test_garbage_input_returns_empty_list_without_raising(self):
        self.assertEqual(parse_live_context("not valid at all {{{"), [])
        self.assertEqual(parse_live_context(""), [])
        self.assertEqual(parse_live_context(json.dumps({"result": 42})), [])

    def test_entities_without_names_are_skipped(self):
        entities = parse_live_context(json.dumps({"result": "- domain: light\n  areas: Office\n"}))
        self.assertEqual(entities, [])


class BuildDeviceListTextTests(unittest.TestCase):
    def test_compact_format_and_mapping_rule(self):
        text = build_device_list_text(_sample_entities())
        self.assertIn("Stream Lights (light, Office)", text)
        self.assertIn("Deck Lights (light, Deck)", text)
        self.assertIn("Office Fan (fan, Office)", text)
        self.assertIn("exact English names", text)
        # No per-entity state should leak into the compact line.
        self.assertNotIn("'off'", text)
        self.assertNotIn("'on'", text)

    def test_empty_entities_returns_empty_string(self):
        self.assertEqual(build_device_list_text([]), "")


class TransliterationAndFuzzyMatchTests(unittest.TestCase):
    def setUp(self):
        self.entities = _sample_entities()

    def test_stream_devanagari_matches_stream_lights(self):
        candidate, score = find_best_match("स्ट्रीम", "ऑफिस", ["light"], self.entities)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["name"], "Stream Lights")
        self.assertGreaterEqual(score, 0.5)

    def test_deck_lights_devanagari_matches_deck_lights(self):
        candidate, score = find_best_match("डेक लाईट्स", None, None, self.entities)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["name"], "Deck Lights")
        self.assertGreaterEqual(score, 0.5)

    def test_short_devanagari_name_alone_still_matches(self):
        # "डेक" (just "deck") has no separate alias for it - word-level matching against
        # "Deck Lights" must still find it.
        candidate, score = find_best_match("डेक", None, None, self.entities)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["name"], "Deck Lights")

    def test_unrelated_request_finds_no_candidate(self):
        candidate, score = find_best_match("पूर्णपणे न जुळणारे काहीतरी", None, None, self.entities)
        self.assertIsNone(candidate)

    def test_domain_filter_excludes_non_matching_domain(self):
        # "Stream Lights" would otherwise match itself exactly, but constraining to domain
        # "fan" must filter it out - nothing in the fan domain is a plausible match for it.
        candidate, _ = find_best_match("Stream Lights", None, ["fan"], self.entities)
        self.assertIsNone(candidate)

    def test_domain_filter_picks_correct_entity_within_domain(self):
        candidate, _ = find_best_match("Office Fan", None, ["fan"], self.entities)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["name"], "Office Fan")

    def test_transliteration_passes_through_latin_text(self):
        self.assertEqual(transliterate_devanagari("Stream Lights"), "Stream Lights")

    def test_transliteration_is_non_empty_for_devanagari(self):
        self.assertTrue(transliterate_devanagari("स्ट्रीम"))
        self.assertTrue(transliterate_devanagari("डेक"))


class MatchFailedDetectionTests(unittest.TestCase):
    def test_structured_json_error_is_detected(self):
        result = is_match_failed(
            json.dumps(
                {
                    "error": "MatchFailedError",
                    "reason": "name",
                    "constraints": {"name": "स्ट्रीम", "area": "ऑफिस", "domain": ["light"]},
                }
            )
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["reason"], "name")
        self.assertEqual(result["constraints"]["name"], "स्ट्रीम")

    def test_invalid_area_carries_no_match_name(self):
        result = is_match_failed(
            json.dumps(
                {
                    "error": "MatchFailedError",
                    "reason": "invalid_area",
                    "constraints": {"area": "Nowhere"},
                    "no_match_name": "Nowhere",
                }
            )
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["no_match_name"], "Nowhere")

    def test_legacy_plain_text_error_is_detected(self):
        result = is_match_failed("Error calling intent: MatchFailedError(no_match_reason=NAME)")
        self.assertIsNotNone(result)

    def test_successful_result_is_not_a_match_failure(self):
        self.assertIsNone(is_match_failed(json.dumps({"success": True, "response": "Turned on"})))
        self.assertIsNone(is_match_failed("Turned on Stream Lights"))
        self.assertIsNone(is_match_failed(""))


class FallbackMessageTests(unittest.TestCase):
    def test_fallback_message_includes_exact_retry_name(self):
        entities = _sample_entities()
        message = build_fallback_message(entities[0], 0.75, "स्ट्रीम", "ऑफिस")
        self.assertIn('name="Stream Lights"', message)
        self.assertIn("confirmation", message)
        # It must instruct the model NOT to report failure, not actually report it.
        self.assertIn("do not report", message.lower())

    def test_no_candidate_message_asks_for_clarification(self):
        message = build_no_candidate_message("काहीतरी", None)
        self.assertIn("which device", message.lower())


if __name__ == "__main__":
    unittest.main()
