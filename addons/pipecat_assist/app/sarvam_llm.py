"""Overrides for pipecat-ai 1.4.0's native Sarvam LLM service.

``pipecat.services.sarvam.llm.SarvamLLMService`` has two gaps that matter for
a realtime voice assistant:

1. Its model whitelist (``_validate_model``) only accepts
   ``sarvam-30b``/``sarvam-30b-16k``/``sarvam-105b``/``sarvam-105b-32k`` and
   rejects ``sarvam-105b-conversations`` — the model Sarvam's own docs
   recommend for conversational/voice use, and ``sarvam-30b`` is now
   deprecated on Sarvam's side. Rather than track Sarvam's model list in two
   places, don't validate here at all; let Sarvam's own API reject a model
   name it doesn't recognize.
2. It sets ``supports_developer_role = False``, which makes pipecat's OpenAI
   adapter convert "developer"-role messages (how this add-on represents
   system instructions/greeting) to "user" rather than "system". Sarvam's
   chat API accepts "system" directly (confirmed against
   https://docs.sarvam.ai/api/api-guides-tutorials/chat-completion/overview),
   so route developer messages there instead via a small adapter override.
   Left as "user", the system instructions and greeting read to the model as
   something the human said on every single turn (full history is resent on
   every chat completion call, as with any stateless chat API), inflating
   both token usage and reasoning effort.
3. The base class's reasoning_effort handling only adds the field to the
   request when a real value is set — passing ``None`` just omits the field,
   leaving Sarvam at its own default ("low", i.e. reasoning still on) rather
   than actually disabling it. Always send the configured value explicitly,
   including ``None`` (which Sarvam's docs confirm fully disables reasoning).
"""

from __future__ import annotations

from typing import Any

from pipecat.adapters.services.open_ai_adapter import OpenAILLMAdapter
from pipecat.services.sarvam.llm import SarvamLLMService as _BaseSarvamLLMService


class _SarvamLLMAdapter(OpenAILLMAdapter):
    def _from_universal_context_messages(self, messages, *, convert_developer_to_user):
        # Ignore the incoming flag — convert to "system" ourselves instead of
        # letting the base adapter convert to "user".
        result = super()._from_universal_context_messages(
            messages, convert_developer_to_user=False
        )
        for message in result:
            if message.get("role") == "developer":
                message["role"] = "system"
        return result


class SarvamLLMService(_BaseSarvamLLMService):
    """Sarvam LLM service with a current model list and correct system-role handling."""

    adapter_class = _SarvamLLMAdapter

    def _validate_model(self, model: str) -> None:
        return

    def build_chat_completion_params(self, params_from_context: Any) -> dict[str, Any]:
        params = super().build_chat_completion_params(params_from_context)
        params["reasoning_effort"] = self._settings.reasoning_effort
        return params
