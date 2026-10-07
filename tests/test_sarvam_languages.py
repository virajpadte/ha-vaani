"""Tests for Sarvam's supported-language list."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1] / "addons" / "pipecat_assist"
if ADDON_ROOT.is_dir():
    sys.path.insert(0, str(ADDON_ROOT))

from app.sarvam_languages import SARVAM_LANGUAGE_CODES, SARVAM_LANGUAGES  # noqa: E402


class SarvamLanguagesTests(unittest.TestCase):
    def test_every_entry_has_a_bcp47_code_and_label(self):
        for item in SARVAM_LANGUAGES:
            self.assertIn("code", item)
            self.assertIn("label", item)
            self.assertRegex(item["code"], r"^[a-z]{2,3}-IN$")
            self.assertTrue(item["label"])

    def test_codes_are_unique(self):
        codes = [item["code"] for item in SARVAM_LANGUAGES]
        self.assertEqual(len(codes), len(set(codes)))

    def test_marathi_and_english_are_present(self):
        self.assertIn("mr-IN", SARVAM_LANGUAGE_CODES)
        self.assertIn("en-IN", SARVAM_LANGUAGE_CODES)

    def test_code_set_matches_eleven_verified_tts_languages(self):
        self.assertEqual(
            SARVAM_LANGUAGE_CODES,
            {
                "bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN",
                "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN",
            },
        )


if __name__ == "__main__":
    unittest.main()
