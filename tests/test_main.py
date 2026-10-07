"""Tests for the composed LLM service construction in app.main.

Requires pipecat-ai to be installed (it is inside the add-on's own
environment / the built Docker image); these tests are not part of the
lightweight "Python syntax" CI job, which only exercises modules that don't
import pipecat-ai.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1] / "addons" / "pipecat_assist"
if ADDON_ROOT.is_dir():
    sys.path.insert(0, str(ADDON_ROOT))

import app.main as main  # noqa: E402
from app.config import (  # noqa: E402
    FlowConfig,
    RuntimeConfig,
    default_integrations,
    default_steps,
)


def _config_with_llm_kind(kind: str) -> tuple[RuntimeConfig, FlowConfig]:
    integrations = default_integrations()
    for item in integrations:
        if item.id == "sarvam":
            item.enabled = True
            item.api_key = "sarvam-test-key"
        if item.id == "local":
            item.enabled = True
            item.base_url = "http://localhost:11434/v1"
            item.default_model = "llama3.2"

    flow = FlowConfig(steps=default_steps())
    for step in flow.steps:
        if step.kind == "llm":
            step.integration_id = "local" if kind == "local" else "sarvam"

    config = RuntimeConfig(integrations=integrations, flows=[flow])
    return config, flow


class BuildLlmServiceTests(unittest.TestCase):
    def test_sarvam_branch_builds_sarvam_service_with_system_adapter(self):
        config, flow = _config_with_llm_kind("sarvam")
        llm = main._build_llm_service(config, flow)

        from app.sarvam_llm import SarvamLLMService, _SarvamLLMAdapter

        self.assertIsInstance(llm, SarvamLLMService)
        self.assertIs(type(llm).adapter_class, _SarvamLLMAdapter)

        integration = config.model_integration(flow)
        self.assertEqual(main._instruction_role(integration), "developer")

    def test_local_branch_builds_openai_compatible_service(self):
        config, flow = _config_with_llm_kind("local")
        llm = main._build_llm_service(config, flow)

        from pipecat.services.openai.llm import OpenAILLMService

        self.assertIsInstance(llm, OpenAILLMService)
        self.assertEqual(str(llm._client.base_url), "http://localhost:11434/v1/")

        integration = config.model_integration(flow)
        self.assertEqual(integration.kind, "local")
        self.assertEqual(main._instruction_role(integration), "system")

    def test_local_context_messages_use_system_role_not_developer(self):
        """The composed run_bot branch builds context messages with the role
        from _instruction_role - for "local" that must be "system", never
        "developer", since vanilla OpenAILLMService does not convert it."""

        config, flow = _config_with_llm_kind("local")
        integration = config.model_integration(flow)
        role = main._instruction_role(integration)

        context_messages = [{"role": role, "content": main._effective_instructions(flow)}]
        if flow.greeting.strip():
            context_messages.append({"role": role, "content": flow.greeting})

        self.assertTrue(context_messages)
        for message in context_messages:
            self.assertEqual(message["role"], "system")
            self.assertNotEqual(message["role"], "developer")

    def test_local_llm_gets_non_empty_tools_schema_when_mcp_tools_exist(self):
        from pipecat.adapters.schemas.function_schema import FunctionSchema
        from pipecat.processors.aggregators.llm_context import LLMContext

        config, flow = _config_with_llm_kind("local")
        tool = FunctionSchema(
            name="HassTurnOn",
            description="Turn on a device.",
            properties={"name": {"type": "string"}},
            required=["name"],
        )
        mcp_tools_schema = main._merge_tools_schema(None, [tool])
        self.assertIsNotNone(mcp_tools_schema)
        self.assertEqual(len(mcp_tools_schema.standard_tools), 1)

        llm = main._build_llm_service(config, flow, tools_schema=mcp_tools_schema)
        context = LLMContext(
            [{"role": "system", "content": "hi"}],
            mcp_tools_schema,
        )
        self.assertIs(context.tools, mcp_tools_schema)
        self.assertEqual(len(context.tools.standard_tools), 1)
        self.assertEqual(context.tools.standard_tools[0].name, "HassTurnOn")
        del llm  # constructed only to prove it accepts tools_schema without error


class EffectiveInstructionsGenderRuleTests(unittest.TestCase):
    def test_confirmed_female_speaker_adds_feminine_rule(self):
        config, flow = _config_with_llm_kind("sarvam")
        for step in flow.steps:
            if step.kind == "tts":
                step.voice = "ishita"
        instructions = main._effective_instructions(flow, "ishita")
        self.assertIn("You are a woman", instructions)

    def test_confirmed_male_speaker_adds_masculine_rule(self):
        config, flow = _config_with_llm_kind("sarvam")
        instructions = main._effective_instructions(flow, "shubh")
        self.assertIn("You are a man", instructions)

    def test_unknown_speaker_adds_no_gender_rule(self):
        config, flow = _config_with_llm_kind("sarvam")
        instructions = main._effective_instructions(flow, "not-a-real-voice")
        self.assertNotIn("You are a woman", instructions)
        self.assertNotIn("You are a man", instructions)

    def test_no_voice_selected_adds_no_gender_rule(self):
        config, flow = _config_with_llm_kind("sarvam")
        instructions = main._effective_instructions(flow, "")
        self.assertNotIn("You are a woman", instructions)
        self.assertNotIn("You are a man", instructions)

    def test_build_llm_service_passes_voice_through_to_system_instruction(self):
        config, flow = _config_with_llm_kind("sarvam")
        llm = main._build_llm_service(config, flow, voice="ishita")
        self.assertIn("You are a woman", llm._settings.system_instruction)


class VoicesForIntegrationTests(unittest.TestCase):
    def test_sarvam_voices_are_grouped_by_gender(self):
        config, _flow = _config_with_llm_kind("sarvam")
        voices = main._voices_for_integration(config.integration("sarvam"))
        genders = {voice["id"]: voice["gender"] for voice in voices}
        self.assertEqual(genders["ishita"], "female")
        self.assertEqual(genders["shubh"], "male")

    def test_non_sarvam_integration_returns_no_voices(self):
        config, _flow = _config_with_llm_kind("local")
        voices = main._voices_for_integration(config.integration("local"))
        self.assertEqual(voices, [])

    def test_v2_only_voice_is_excluded_when_model_is_v3(self):
        config, _flow = _config_with_llm_kind("sarvam")
        integration = config.integration("sarvam")
        integration.default_tts_model = "bulbul:v3"
        voices = main._voices_for_integration(integration)
        ids = {voice["id"] for voice in voices}
        self.assertNotIn("vidya", ids)
        self.assertIn("shubh", ids)

    def test_v3_only_voice_is_excluded_when_model_is_v2(self):
        config, _flow = _config_with_llm_kind("sarvam")
        integration = config.integration("sarvam")
        integration.default_tts_model = "bulbul:v2"
        voices = main._voices_for_integration(integration)
        ids = {voice["id"] for voice in voices}
        self.assertIn("vidya", ids)
        self.assertNotIn("shubh", ids)

    def test_explicit_model_param_overrides_integration_default(self):
        config, _flow = _config_with_llm_kind("sarvam")
        integration = config.integration("sarvam")
        integration.default_tts_model = "bulbul:v3"
        voices = main._voices_for_integration(integration, model="bulbul:v2")
        ids = {voice["id"] for voice in voices}
        self.assertIn("vidya", ids)
        self.assertNotIn("shubh", ids)


if __name__ == "__main__":
    unittest.main()
