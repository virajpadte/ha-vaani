"""Tests for ConfigStore's upgrade path from the old multi-provider config shape."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1] / "addons" / "pipecat_assist"
if ADDON_ROOT.is_dir():
    sys.path.insert(0, str(ADDON_ROOT))

from app.config import ConfigStore  # noqa: E402


def _old_shape_payload() -> dict:
    """A config as a pre-Sarvam-only build of this add-on would have saved it."""

    return {
        "version": 12,
        "integrations": [
            {
                "id": "sarvam",
                "name": "Sarvam AI",
                "kind": "sarvam",
                "enabled": True,
                "api_key": "sarvam-real-key",
                "language": "mr-IN",
                "default_model": "sarvam-105b-conversations",
                "default_stt_model": "saaras:v3",
                "default_tts_model": "bulbul:v3",
                "default_voice": "ishita",
            },
            {
                "id": "gemini",
                "name": "Google Gemini Live",
                "kind": "gemini",
                "enabled": False,
                "api_key": "gemini-old-key",
            },
            {
                "id": "openai-cloud",
                "name": "OpenAI Cloud",
                "kind": "openai_cloud",
                "enabled": False,
                "api_key": "openai-old-key",
            },
            {
                "id": "ha-mcp",
                "name": "Home Assistant MCP",
                "kind": "home_assistant_mcp",
                "enabled": True,
            },
        ],
        "flows": [
            {
                "id": "home-default",
                "name": "Home",
                "instructions": "Custom instructions that must survive the upgrade.",
                "greeting": "Custom greeting that must survive the upgrade.",
                "steps": [
                    {"id": "transport", "kind": "transport", "label": "WebRTC"},
                    {"id": "stt", "kind": "stt", "label": "STT", "integration_id": "sarvam"},
                    {"id": "llm", "kind": "llm", "label": "Model", "integration_id": "sarvam"},
                    {"id": "flow", "kind": "flow", "label": "Pizza Flow", "integration_id": ""},
                    {"id": "tools", "kind": "tools", "label": "Tools", "integration_id": "ha-mcp"},
                    {"id": "tts", "kind": "tts", "label": "TTS", "integration_id": "sarvam"},
                ],
            }
        ],
    }


class ConfigMigrationTests(unittest.TestCase):
    def test_old_multi_provider_config_migrates_without_losing_sarvam_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pipecat_assist.json"
            path.write_text(json.dumps(_old_shape_payload()), encoding="utf-8")

            config = ConfigStore(path).load()

            sarvam = config.integration("sarvam")
            self.assertIsNotNone(sarvam)
            self.assertEqual(sarvam.api_key, "sarvam-real-key")
            self.assertEqual(sarvam.language, "mr-IN")
            self.assertEqual(sarvam.default_model, "sarvam-105b-conversations")
            self.assertEqual(sarvam.default_stt_model, "saaras:v3")
            self.assertEqual(sarvam.default_tts_model, "bulbul:v3")
            self.assertEqual(sarvam.default_voice, "ishita")

            flow = config.flows[0]
            self.assertEqual(flow.instructions, "Custom instructions that must survive the upgrade.")
            self.assertEqual(flow.greeting, "Custom greeting that must survive the upgrade.")

            # Removed providers and the removed Pipecat Flows step must not survive, and
            # must not crash validation on the way out.
            self.assertIsNone(config.integration("gemini"))
            self.assertIsNone(config.integration("openai-cloud"))
            self.assertNotIn("flow", {step.kind for step in flow.steps})

            # The fixed pipeline's kept steps (stt/llm/tools/tts) still point at the
            # integrations the old config already had configured for them.
            by_kind = {step.kind: step for step in flow.steps}
            self.assertEqual(by_kind["stt"].integration_id, "sarvam")
            self.assertEqual(by_kind["llm"].integration_id, "sarvam")
            self.assertEqual(by_kind["tts"].integration_id, "sarvam")
            self.assertEqual(by_kind["tools"].integration_id, "ha-mcp")

    def test_reloading_the_migrated_config_is_stable(self):
        """A second load of the already-migrated file should not change anything further."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pipecat_assist.json"
            path.write_text(json.dumps(_old_shape_payload()), encoding="utf-8")

            store = ConfigStore(path)
            first = store.load()
            second = store.load()

            self.assertEqual(
                first.integration("sarvam").api_key,
                second.integration("sarvam").api_key,
            )
            self.assertEqual(first.flows[0].instructions, second.flows[0].instructions)


if __name__ == "__main__":
    unittest.main()
