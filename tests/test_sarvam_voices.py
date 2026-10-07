"""Tests for the Sarvam bulbul speaker gender map and its Marathi verb-form rule."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1] / "addons" / "pipecat_assist"
if ADDON_ROOT.is_dir():
    sys.path.insert(0, str(ADDON_ROOT))

from app.sarvam_voices import (  # noqa: E402
    V2_SPEAKERS,
    V3_SPEAKERS,
    gender_instruction,
    speaker_gender,
    speakers_for_model,
)


class SpeakerGenderTests(unittest.TestCase):
    def test_confirmed_female_speaker(self):
        self.assertEqual(speaker_gender("ishita"), "female")

    def test_confirmed_male_speaker(self):
        self.assertEqual(speaker_gender("shubh"), "male")

    def test_is_case_and_whitespace_insensitive(self):
        self.assertEqual(speaker_gender("  Ishita  "), "female")
        self.assertEqual(speaker_gender("SHUBH"), "male")

    def test_inferred_speaker_still_resolves(self):
        self.assertEqual(speaker_gender("kavya"), "female")
        self.assertEqual(speaker_gender("rahul"), "male")

    def test_unknown_speaker_returns_none(self):
        self.assertIsNone(speaker_gender("not-a-real-voice"))

    def test_empty_speaker_returns_none(self):
        self.assertIsNone(speaker_gender(""))


class GenderInstructionTests(unittest.TestCase):
    """The Marathi verb-form rule's grammar is Marathi-specific, so it must only ever be
    returned when the configured language is Marathi - gender agreement rules differ
    across Sarvam's other supported languages and have not been verified here."""

    def test_confirmed_female_speaker_gets_exact_feminine_rule_for_marathi(self):
        self.assertEqual(
            gender_instruction("ishita", "mr-IN"),
            "You are a woman; use feminine first-person Marathi verb forms (करते, शकते, "
            "सांगते, आले, केले), never masculine (करतो, शकतो, आलो). Verbs that agree with "
            "an object (e.g. 'light बंद केला') stay as they are.",
        )

    def test_confirmed_male_speaker_gets_symmetric_masculine_rule_for_marathi(self):
        self.assertEqual(
            gender_instruction("shubh", "mr-IN"),
            "You are a man; use masculine first-person Marathi verb forms (करतो, शकतो, "
            "सांगतो, आलो, केला), never feminine (करते, शकते, आले). Verbs that agree with "
            "an object (e.g. 'light बंद केला') stay as they are.",
        )

    def test_inferred_speaker_still_gets_a_rule_for_marathi(self):
        self.assertTrue(gender_instruction("kavya", "mr-IN").startswith("You are a woman"))
        self.assertTrue(gender_instruction("rahul", "mr-IN").startswith("You are a man"))

    def test_unknown_speaker_returns_empty_string(self):
        self.assertEqual(gender_instruction("not-a-real-voice", "mr-IN"), "")

    def test_no_speaker_selected_returns_empty_string(self):
        self.assertEqual(gender_instruction("", "mr-IN"), "")

    def test_non_marathi_language_suppresses_the_rule_even_for_a_known_speaker(self):
        self.assertEqual(gender_instruction("ishita", "hi-IN"), "")
        self.assertEqual(gender_instruction("shubh", "ta-IN"), "")
        self.assertEqual(gender_instruction("ishita", "en-IN"), "")

    def test_no_language_specified_suppresses_the_rule(self):
        self.assertEqual(gender_instruction("ishita"), "")
        self.assertEqual(gender_instruction("ishita", ""), "")

    def test_marathi_match_is_case_insensitive(self):
        self.assertTrue(gender_instruction("ishita", "MR-IN").startswith("You are a woman"))


class SpeakersForModelTests(unittest.TestCase):
    def test_v2_model_returns_only_v2_speakers(self):
        self.assertEqual(speakers_for_model("bulbul:v2"), V2_SPEAKERS)

    def test_v3_model_returns_only_v3_speakers(self):
        self.assertEqual(speakers_for_model("bulbul:v3"), V3_SPEAKERS)

    def test_v3_beta_model_also_returns_v3_speakers(self):
        self.assertEqual(speakers_for_model("bulbul:v3-beta"), V3_SPEAKERS)

    def test_empty_model_defaults_to_v3_speakers(self):
        self.assertEqual(speakers_for_model(""), V3_SPEAKERS)

    def test_v2_and_v3_speaker_sets_do_not_overlap(self):
        self.assertEqual(V2_SPEAKERS & V3_SPEAKERS, set())

    def test_vidya_is_v2_only_matching_sarvams_live_api_error(self):
        # Regression test for a real production bug: a config saved voice="vidya" paired
        # with model="bulbul:v3", which Sarvam's API rejects outright with an HTTP 400.
        self.assertIn("vidya", V2_SPEAKERS)
        self.assertNotIn("vidya", V3_SPEAKERS)
        self.assertNotIn("vidya", speakers_for_model("bulbul:v3"))


if __name__ == "__main__":
    unittest.main()
