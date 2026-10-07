"""Tests for the Sarvam bulbul speaker gender map and its Marathi verb-form rule."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1] / "addons" / "pipecat_assist"
if ADDON_ROOT.is_dir():
    sys.path.insert(0, str(ADDON_ROOT))

from app.sarvam_voices import gender_instruction, speaker_gender  # noqa: E402


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
    def test_confirmed_female_speaker_gets_exact_feminine_rule(self):
        self.assertEqual(
            gender_instruction("ishita"),
            "You are a woman; use feminine first-person Marathi verb forms (करते, शकते, "
            "सांगते, आले, केले), never masculine (करतो, शकतो, आलो). Verbs that agree with "
            "an object (e.g. 'light बंद केला') stay as they are.",
        )

    def test_confirmed_male_speaker_gets_symmetric_masculine_rule(self):
        self.assertEqual(
            gender_instruction("shubh"),
            "You are a man; use masculine first-person Marathi verb forms (करतो, शकतो, "
            "सांगतो, आलो, केला), never feminine (करते, शकते, आले). Verbs that agree with "
            "an object (e.g. 'light बंद केला') stay as they are.",
        )

    def test_inferred_speaker_still_gets_a_rule(self):
        self.assertTrue(gender_instruction("kavya").startswith("You are a woman"))
        self.assertTrue(gender_instruction("rahul").startswith("You are a man"))

    def test_unknown_speaker_returns_empty_string(self):
        self.assertEqual(gender_instruction("not-a-real-voice"), "")

    def test_no_speaker_selected_returns_empty_string(self):
        self.assertEqual(gender_instruction(""), "")


if __name__ == "__main__":
    unittest.main()
