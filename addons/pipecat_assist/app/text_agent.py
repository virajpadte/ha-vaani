"""Text bridge used by the Home Assistant Conversation integration."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any

from openai import AsyncOpenAI

from app.config import DEFAULT_LOCAL_LLM_MODEL, DEFAULT_SARVAM_LLM_MODEL, RuntimeConfig
from app.mcp_bridge import CombinedMCPBridge

CONVERSATION_END_SYSTEM_HINT = (
    "If the user clearly ends the conversation, briefly acknowledge it and do not ask "
    "a follow-up question. The client will close the microphone after your farewell."
)

SARVAM_OPENAI_BASE_URL = "https://api.sarvam.ai/v1"


def _format_openai_tools(tools_schema) -> list[dict[str, Any]]:
    """Convert Pipecat FunctionSchema objects to OpenAI Chat tools."""

    formatted: list[dict[str, Any]] = []
    for tool in tools_schema.standard_tools:
        formatted.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": tool.properties,
                        "required": tool.required,
                    },
                },
            }
        )
    return formatted


def _tool_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _web_search_step(flow):
    return next((step for step in flow.steps if step.kind == "web_search" and step.enabled), None)


def _web_search_announces(flow) -> bool:
    step = _web_search_step(flow)
    return bool(step and (step.settings or {}).get("announce", True))


def _effective_instructions(flow) -> str:
    instructions = flow.instructions
    if CONVERSATION_END_SYSTEM_HINT not in instructions:
        instructions += f"\n\n{CONVERSATION_END_SYSTEM_HINT}"
    if _web_search_announces(flow):
        instructions += (
            "\n\nWhen you decide to use web search, first say "
            '"Please hold, I\'m checking." Then run the search and answer briefly.'
        )
    return instructions


def _text_model(integration, flow) -> str:
    step = flow.model_step()
    for candidate in (
        getattr(step, "model", "") if step else "",
        integration.default_model if integration else "",
    ):
        clean = str(candidate or "").strip()
        if clean:
            return clean
    if integration and integration.kind == "local":
        return DEFAULT_LOCAL_LLM_MODEL
    return DEFAULT_SARVAM_LLM_MODEL


async def run_text_conversation(
    config: RuntimeConfig,
    *,
    text: str,
    language: str | None,
    conversation_id: str | None,
    flow_id: str | None = None,
    mcp_token: str = "",
) -> dict[str, Any]:
    """Run a text request through the selected LLM provider with HA MCP tools."""

    flow = config.selected_flow(flow_id)
    integration = config.model_integration(flow)
    provider_kind = integration.kind if integration else ""
    if provider_kind not in {"sarvam", "local"}:
        return {
            "speech": f"HA Assist conversation does not support {provider_kind or 'no'} LLM provider.",
            "conversation_id": conversation_id,
            "continue_conversation": False,
            "error": "unsupported_text_provider",
        }

    api_key = (integration.api_key or "").strip()
    if provider_kind == "local" and not api_key:
        api_key = "not-needed"
    if not api_key:
        return {
            "speech": "Pipecat Assist is missing an API key for the selected model provider.",
            "conversation_id": conversation_id,
            "continue_conversation": False,
            "error": "missing_provider_api_key",
        }

    system = (
        f"{_effective_instructions(flow)}\n\n"
        "You are answering through Home Assistant Conversation text mode. "
        "Use MCP tools silently for explicit smart-home requests. "
        "Keep the final answer short and natural."
    )
    if language and str(language).lower() != "pipecat-assist":
        system += f"\nThe user's language is {language}."

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]

    tools: list[dict[str, Any]] = []

    bridge: CombinedMCPBridge | None = None
    mcp_servers = config.enabled_mcp_servers(mcp_token) if flow.mcp_enabled else []
    if mcp_servers:
        bridge = CombinedMCPBridge(mcp_servers, flow.mcp_tool_allowlist)
        try:
            await bridge.start()
            tools_schema = await bridge.tools_schema(
                cache_enabled=config.mcp_tools_cache_enabled,
                cache_ttl_seconds=config.mcp_tools_cache_ttl_seconds,
            )
            tools.extend(_format_openai_tools(tools_schema))
        except asyncio.CancelledError as err:
            with suppress(Exception):
                await bridge.close()
            bridge = None
            return {
                "speech": f"Home Assistant MCP is not available: {err}",
                "conversation_id": conversation_id,
                "continue_conversation": False,
                "error": "mcp_unavailable",
            }
        except Exception as err:
            with suppress(Exception):
                await bridge.close()
            bridge = None
            return {
                "speech": f"Home Assistant MCP is not available: {err}",
                "conversation_id": conversation_id,
                "continue_conversation": False,
                "error": "mcp_unavailable",
            }

    async def call_tool(name: str, arguments: dict[str, Any]) -> str:
        if bridge is None:
            return "Home Assistant MCP is not connected."
        return await bridge.call_tool(name, arguments)

    try:
        if provider_kind == "sarvam":
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=SARVAM_OPENAI_BASE_URL,
                default_headers={"api-subscription-key": api_key},
            )
        else:
            client = AsyncOpenAI(api_key=api_key, base_url=integration.base_url or None)

        model = _text_model(integration, flow)
        for _ in range(6):
            kwargs: dict[str, Any] = {"model": model, "messages": messages}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            response = await client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            messages.append(message.model_dump(exclude_none=True))

            tool_calls = message.tool_calls or []
            if not tool_calls:
                speech = message.content or ""
                return {
                    "speech": speech.strip() or "Done.",
                    "conversation_id": conversation_id,
                    "continue_conversation": False,
                }

            if bridge is None:
                return {
                    "speech": "I need Home Assistant MCP tools for that, but MCP is not connected.",
                    "conversation_id": conversation_id,
                    "continue_conversation": False,
                    "error": "mcp_not_connected",
                }

            for tool_call in tool_calls:
                arguments = _tool_args(tool_call.function.arguments)
                result = await call_tool(tool_call.function.name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        return {
            "speech": "The request needed too many tool calls and was stopped.",
            "conversation_id": conversation_id,
            "continue_conversation": False,
            "error": "tool_loop_limit",
        }
    finally:
        if bridge:
            await bridge.close()
