"""Pipecat Assist add-on entry point."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import time
import unicodedata
import uuid
import wave
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from loguru import logger
from starlette.staticfiles import StaticFiles

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frameworks.rtvi import RTVIObserverParams
from pipecat.runner.run import app, main as runner_main
from pipecat.runner.types import RunnerArguments, WebSocketRunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

from app.config import (
    COMPOSED_STEP_PROVIDER_KINDS,
    DEFAULT_LOCAL_LLM_MODEL,
    DEFAULT_SARVAM_LANGUAGE,
    DEFAULT_SARVAM_LLM_MODEL,
    DEFAULT_SARVAM_STT_MODEL,
    DEFAULT_SARVAM_TTS_MODEL,
    DEFAULT_SARVAM_TTS_VOICE,
    ConfigStore,
    FlowConfig,
    IntegrationConfig,
    RuntimeConfig,
)
from app.audio_debug import (
    audio_debug_file_path,
    clear_audio_recordings,
    create_audio_debug_session,
    list_audio_recordings,
)
from app.esphome_provisioner import ESPHomeProvisioner
from app.mcp_bridge import (
    CombinedMCPBridge,
    check_mcp,
    clear_mcp_call_history,
    clear_mcp_tools_cache,
    list_mcp_call_history,
)
from app.ha_device_context import build_device_list_text
from app.sarvam_voices import gender_instruction
from app.web_search_tool import run_tavily_search, web_search_schema
from app.session_memory import SESSION_MEMORY
from app.text_agent import run_text_conversation
from app.va_pipecat import websocket_transport_params
from app.va_pipecat_protocol import VaPipecatProtocol

STORE = ConfigStore()
STARTED_AT = time.time()
UI_DIR = Path(__file__).parent / "ui"
UI_CACHE_HEADERS = {"Cache-Control": "no-store"}
SUPERVISOR_URL = os.getenv("SUPERVISOR", "http://supervisor").rstrip("/")

DEFAULT_HA_STT_SAMPLE_RATE = 16000
DEFAULT_HA_STT_SAMPLE_WIDTH = 2
DEFAULT_HA_STT_CHANNELS = 1
OPENAI_TTS_FORMATS = {"mp3", "opus", "aac", "flac", "wav", "pcm"}
CONVERSATION_END_SYSTEM_HINT = (
    "If the user clearly ends the conversation, briefly acknowledge it and do not ask "
    "a follow-up question. The client will close the microphone after your farewell."
)
HA_STT_BRIDGE_KINDS = {"sarvam"}
HA_TTS_BRIDGE_KINDS = {"sarvam"}
PROVIDER_RETRY_STATUSES = {429, 500, 502, 503, 504}
TTS_PREFETCH_TTL_SECONDS = 90
TTS_PREFETCH: dict[tuple[str, str, str], tuple[float, Any]] = {}
HA_ASSIST_WARMUP_TASK: asyncio.Task | None = None
ESPHOME_PROVISIONER = ESPHomeProvisioner(
    STORE.load,
    supervisor_url=SUPERVISOR_URL,
    supervisor_token=os.getenv("SUPERVISOR_TOKEN", ""),
)

app.mount("/assets", StaticFiles(directory=UI_DIR), name="assets")


def _configure_logging() -> None:
    config = STORE.load()
    logger.remove()
    logger.add(lambda message: print(message, end=""), level=config.log_level)


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token", "")


def _is_offer_path(path: str) -> bool:
    return path == "/api/offer" or (path.startswith("/sessions/") and path.endswith("/api/offer"))


def _parse_speech_content(value: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for entry in value.split(";"):
        key, _, raw = entry.strip().partition("=")
        if key:
            fields[key] = raw.strip()
    return fields


def _wav_from_pcm(
    audio: bytes,
    *,
    sample_rate: int = DEFAULT_HA_STT_SAMPLE_RATE,
    sample_width: int = DEFAULT_HA_STT_SAMPLE_WIDTH,
    channels: int = DEFAULT_HA_STT_CHANNELS,
) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        writer.writeframes(audio)
    return output.getvalue()


def _audio_for_cloud_stt(request: Request, audio: bytes) -> tuple[bytes, str]:
    """Return a valid upload payload for cloud STT APIs.

    Home Assistant's live Assist pipeline streams raw 16-bit PCM chunks while
    advertising WAV/PCM metadata. Cloud HTTP STT APIs expect a real WAV file.
    """

    content_type = request.headers.get("content-type") or "audio/wav"
    metadata = _parse_speech_content(request.headers.get("x-speech-content", ""))
    return _audio_for_cloud_stt_metadata(audio, metadata, content_type)


def _audio_for_cloud_stt_metadata(
    audio: bytes,
    metadata: dict[str, Any],
    content_type: str = "audio/wav",
) -> tuple[bytes, str]:
    """Return a valid upload payload using parsed Home Assistant speech metadata."""

    audio_format = metadata.get("format", "wav").lower()
    codec = metadata.get("codec", "pcm").lower()
    if audio_format == "wav" and codec == "pcm" and not audio.startswith(b"RIFF"):
        sample_rate = int(metadata.get("sample_rate") or DEFAULT_HA_STT_SAMPLE_RATE)
        bit_rate = int(metadata.get("bit_rate") or 16)
        channels = int(metadata.get("channel") or DEFAULT_HA_STT_CHANNELS)
        sample_width = max(1, bit_rate // 8)
        return _wav_from_pcm(
            audio,
            sample_rate=sample_rate,
            sample_width=sample_width,
            channels=channels,
        ), "audio/wav"
    return audio, content_type


def _provider_status(err: Exception) -> int | None:
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None) or getattr(err, "status_code", None)
    try:
        return int(status) if status else None
    except (TypeError, ValueError):
        return None


def _provider_body(err: Exception) -> Any:
    body = getattr(err, "body", None)
    if body:
        return body
    response = getattr(err, "response", None)
    if response is None:
        return None
    with suppress(Exception):
        return response.json()
    with suppress(Exception):
        return response.text
    return None


def _provider_message_from_body(body: Any) -> str:
    if isinstance(body, list):
        return "; ".join(filter(None, (_provider_message_from_body(item) for item in body)))
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("status") or error.get("code") or "").strip()
        if isinstance(error, str):
            return error.strip()
        return str(body.get("message") or body.get("detail") or "").strip()
    if isinstance(body, str):
        return body.strip()
    return ""


def _provider_safe_detail(label: str, err: Exception) -> str:
    status = _provider_status(err)
    message = _provider_message_from_body(_provider_body(err)) or str(err).split(" for url ")[0]
    message = message.replace("\n", " ").strip()
    if status:
        return f"{label} failed with HTTP {status}: {message}"
    return f"{label} failed: {message}"


def _provider_http_exception(label: str, err: Exception) -> HTTPException:
    if isinstance(err, HTTPException):
        return err
    status = _provider_status(err)
    http_status = status if status in {400, 401, 403, 404, 408, 409, 422, 429, 500, 502, 503, 504} else 502
    if http_status >= 500:
        http_status = 503
    return HTTPException(status_code=http_status, detail=_provider_safe_detail(label, err))


def _provider_retryable(err: Exception) -> bool:
    status = _provider_status(err)
    return bool(status in PROVIDER_RETRY_STATUSES)


async def _provider_call(label: str, request, attempts: int = 3):
    for attempt in range(1, attempts + 1):
        try:
            return await request()
        except HTTPException:
            raise
        except Exception as err:
            if attempt >= attempts or not _provider_retryable(err):
                raise _provider_http_exception(label, err) from err
            logger.warning(
                "{} attempt {}/{} failed, retrying: {}",
                label,
                attempt,
                attempts,
                _provider_safe_detail(label, err),
            )
            await asyncio.sleep(min(2.0, 0.35 * (2 ** (attempt - 1))))

    raise HTTPException(status_code=503, detail=f"{label} failed after retries")


def _stt_metadata_from_start(start: dict[str, Any]) -> dict[str, Any]:
    metadata = start.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _preferred_tts_format(payload: dict[str, Any]) -> str:
    options = payload.get("options")
    if not isinstance(options, dict):
        return "mp3"
    preferred = str(options.get("preferred_format") or "").strip().lower()
    return preferred if preferred in OPENAI_TTS_FORMATS else "mp3"


@app.middleware("http")
async def protect_satellite_offer(request: Request, call_next):
    """Require the shared satellite token for direct SmallWebRTC offers."""

    if _is_offer_path(request.url.path):
        secret = STORE.load().satellite_shared_secret
        if secret and not hmac.compare_digest(_extract_token(request), secret):
            return JSONResponse({"detail": "Invalid satellite token"}, status_code=401)
    try:
        return await call_next(request)
    except Exception as err:
        if _is_offer_path(request.url.path):
            logger.exception("SmallWebRTC offer failed: {}", err)
            return JSONResponse({"detail": str(err) or err.__class__.__name__}, status_code=400)
        raise


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(UI_DIR / "index.html", headers=UI_CACHE_HEADERS)


@app.get("/index.js", include_in_schema=False)
@app.get("/index.css", include_in_schema=False)
@app.get("/logo.svg", include_in_schema=False)
async def ui_asset(request: Request):
    return FileResponse(UI_DIR / request.url.path.lstrip("/"), headers=UI_CACHE_HEADERS)


def _offer_url(config: RuntimeConfig, request: Request) -> str:
    host = config.runner_host
    if host in {"0.0.0.0", "::", ""}:
        host = request.url.hostname or "homeassistant.local"
    token = quote(config.satellite_shared_secret)
    suffix = f"?token={token}" if token else ""
    return f"http://{host}:{config.runner_port}/api/offer{suffix}"


def _offer_path(config: RuntimeConfig) -> str:
    token = quote(config.satellite_shared_secret)
    suffix = f"?token={token}" if token else ""
    return f"api/offer{suffix}"


def _esphome_ws_query(config: RuntimeConfig) -> str:
    values = {
        "token": config.satellite_shared_secret,
        "flow_id": config.selected_flow_id,
    }
    return urlencode({key: value for key, value in values.items() if value})


def _esphome_ws_url(config: RuntimeConfig, request: Request) -> str:
    host = config.runner_host
    if host in {"0.0.0.0", "::", ""}:
        host = request.url.hostname or "homeassistant.local"
    query = _esphome_ws_query(config)
    suffix = f"?{query}" if query else ""
    # The host-network runner port is plain WebSocket even when this response
    # was reached through an HTTPS Home Assistant Ingress page.
    return f"ws://{host}:{config.runner_port}/api/assist/esphome{suffix}"


def _esphome_ws_path(config: RuntimeConfig) -> str:
    query = _esphome_ws_query(config)
    suffix = f"?{query}" if query else ""
    return f"api/assist/esphome{suffix}"


def _va_pipecat_protocol(config: RuntimeConfig) -> VaPipecatProtocol:
    """Build the ESPHome protocol contract from persisted runtime settings."""

    return VaPipecatProtocol(
        _should_end_conversation,
        follow_up_ms=config.esphome_follow_up_ms,
        follow_up_open_delay_ms=config.esphome_follow_up_open_delay_ms,
        wake_open_delay_ms=config.esphome_wake_open_delay_ms,
        playback_prebuffer_ms=config.esphome_playback_prebuffer_ms,
    )


def _config_response(config: RuntimeConfig, request: Request) -> dict[str, Any]:
    data = config.public_dict()
    data["runner_offer_url"] = _offer_url(config, request)
    data["runner_offer_path"] = _offer_path(config)
    data["esphome_ws_url"] = _esphome_ws_url(config, request)
    data["esphome_ws_path"] = _esphome_ws_path(config)
    data["esphome_provisioning"] = ESPHOME_PROVISIONER.status()
    return data


def _is_http_endpoint(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


async def _check_integration_mcp(
    config: RuntimeConfig,
    integration: IntegrationConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    flow = config.selected_flow(payload.get("flow_id"))
    refresh = bool(payload.get("refresh", True))
    if refresh:
        clear_mcp_tools_cache()

    url = config.effective_mcp_url
    token = config.effective_mcp_token

    if not _is_http_endpoint(url):
        return {"ok": False, "error": "MCP server URL is missing.", "tool_count": 0, "tools": []}

    return await check_mcp(
        url,
        token,
        flow.mcp_tool_allowlist,
        cache_enabled=config.mcp_tools_cache_enabled,
        cache_ttl_seconds=config.mcp_tools_cache_ttl_seconds,
        refresh=refresh,
    )


@app.get("/api/assist/status")
async def api_status(request: Request):
    config = STORE.load()
    flow = config.selected_flow(None)
    flow_errors = _runtime_flow_errors(config, flow)
    return {
        "ok": True,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "runner": {
            "host": config.runner_host,
            "port": config.runner_port,
            "offer_url": _offer_url(config, request),
            "offer_path": _offer_path(config),
            "esphome_ws_path": "api/assist/esphome",
        },
        "selected_flow_id": config.selected_flow_id,
        "selected_flow_ready": not flow_errors,
        "selected_flow_errors": flow_errors,
        "flow_count": len(config.flows),
        "mcp_url": config.effective_mcp_url,
        "mcp_token_configured": bool(config.effective_mcp_token),
        "mcp_token_source": config.effective_mcp_token_source,
    }


@app.websocket("/api/assist/esphome")
async def api_esphome_satellite(websocket: WebSocket):
    """Run an authenticated raw-PCM Pipecat session for an ESPHome satellite."""

    config = STORE.load()
    secret = config.satellite_shared_secret
    supplied_token = _extract_token(websocket)
    if secret and not hmac.compare_digest(supplied_token, secret):
        logger.warning("ESPHome satellite rejected: invalid or missing token")
        await websocket.close(code=4401)
        return

    flow_id = str(websocket.query_params.get("flow_id") or "").strip()
    flow = config.selected_flow(flow_id)
    flow_errors = _runtime_flow_errors(config, flow)
    if flow_errors:
        await websocket.close(code=4400, reason=flow_errors[0][:120])
        return

    client_id = (
        str(websocket.query_params.get("client_id") or "").strip()
        or str(websocket.client.host if websocket.client else "")
        or f"esphome-{uuid.uuid4().hex[:12]}"
    )
    session_id = str(uuid.uuid4())
    await websocket.accept()
    await websocket.send_text(_va_pipecat_protocol(config).hello())
    logger.info(
        "ESPHome satellite connected client_id={} flow={} session={}",
        client_id,
        flow.id,
        session_id,
    )

    runner_args = WebSocketRunnerArguments(
        websocket=websocket,
        transport_type="websocket",
        session_id=session_id,
        body={
            "client_id": client_id,
            "device_id": client_id,
            "flow_id": flow.id,
            "transport": "va-pipecat",
        },
    )
    # ESPHome keeps this low-latency control connection open from boot. The
    # generic runner's five-minute idle timeout is useful for browser calls but
    # would churn the satellite pipeline and MCP/model warm state.
    runner_args.pipeline_idle_timeout_secs = None
    try:
        await bot(runner_args)
    except WebSocketDisconnect:
        logger.info("ESPHome satellite disconnected client_id={}", client_id)
    except Exception as err:
        logger.exception("ESPHome satellite session failed client_id={}: {}", client_id, err)
        with suppress(Exception):
            payload = _va_pipecat_protocol(config).error_message(
                "session_failed",
                str(err) or err.__class__.__name__,
                recoverable=True,
            )
            await websocket.send_text(payload)
        with suppress(Exception):
            await websocket.close(code=1011)


@app.get("/api/assist/config")
async def api_get_config(request: Request):
    config = STORE.load()
    return _config_response(config, request)


@app.put("/api/assist/config")
async def api_update_config(payload: dict[str, Any], request: Request):
    config = STORE.update_from_public(payload)
    _schedule_ha_assist_warmup(config, reason="config_update")
    ESPHOME_PROVISIONER.request_scan()
    return _config_response(config, request)


def _static_models_for(integration: IntegrationConfig, capability: str) -> list[dict[str, str]]:
    values: list[str] = []
    if integration.kind == "sarvam":
        if capability == "stt":
            values = ["saaras:v3", "saaras:v2.5", "saarika:v2.5"]
        elif capability == "tts":
            values = ["bulbul:v3", "bulbul:v3-beta", "bulbul:v2"]
        else:
            values = ["sarvam-105b-conversations", "sarvam-105b", "sarvam-30b"]
    elif integration.kind == "local":
        values = [integration.default_model] if integration.default_model else []
    seen: set[str] = set()
    return [
        {"id": value, "label": value}
        for value in values
        if value and not (value in seen or seen.add(value))
    ]


@app.get("/api/assist/integrations/{integration_id}/models")
async def api_integration_models(integration_id: str, capability: str = "llm"):
    config = STORE.load()
    integration = config.integration(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    fallback = _static_models_for(integration, capability)

    if integration.kind == "local" and integration.base_url:
        try:
            headers = {"Authorization": f"Bearer {integration.api_key}"} if integration.api_key else {}
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(
                    integration.base_url.rstrip("/") + "/models",
                    headers=headers,
                )
                response.raise_for_status()
            models = sorted(
                str(item.get("id")) for item in response.json().get("data", []) if item.get("id")
            )
            if models:
                return {"ok": True, "models": [{"id": item, "label": item} for item in models]}
        except Exception as err:
            logger.debug("Model list fetch failed for {}: {}", integration_id, err)

    return {"ok": False, "models": fallback}


def _voices_for_integration(integration: IntegrationConfig) -> list[dict[str, str]]:
    """Return TTS speaker voices for an integration, grouped by gender when known."""

    if integration.kind != "sarvam":
        return []

    from app.sarvam_voices import FEMALE_SPEAKERS, MALE_SPEAKERS

    return [
        {"id": name, "label": name.capitalize(), "gender": "female"} for name in sorted(FEMALE_SPEAKERS)
    ] + [
        {"id": name, "label": name.capitalize(), "gender": "male"} for name in sorted(MALE_SPEAKERS)
    ]


@app.get("/api/assist/integrations/{integration_id}/voices")
async def api_integration_voices(integration_id: str):
    config = STORE.load()
    integration = config.integration(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return {"voices": _voices_for_integration(integration)}


@app.post("/api/assist/mcp/check")
async def api_check_mcp(payload: dict[str, Any] | None = None):
    config = STORE.load()
    payload = payload or {}
    flow = config.selected_flow(payload.get("flow_id"))
    refresh = bool(payload.get("refresh", True))
    if refresh:
        clear_mcp_tools_cache()
    return await check_mcp(
        config.effective_mcp_url,
        config.effective_mcp_token,
        flow.mcp_tool_allowlist,
        cache_enabled=config.mcp_tools_cache_enabled,
        cache_ttl_seconds=config.mcp_tools_cache_ttl_seconds,
        refresh=refresh,
    )


@app.post("/api/assist/mcp/reset")
async def api_reset_mcp(request: Request):
    config = STORE.reset_mcp_defaults()
    return _config_response(config, request)


@app.get("/api/assist/mcp/history")
async def api_mcp_history():
    return list_mcp_call_history()


@app.delete("/api/assist/mcp/history")
async def api_clear_mcp_history():
    return clear_mcp_call_history()


@app.post("/api/assist/integrations/{integration_id}/reset")
async def api_reset_integration(integration_id: str, request: Request):
    try:
        config = STORE.reset_integration_defaults(integration_id)
    except KeyError as err:
        raise HTTPException(status_code=404, detail="Integration not found") from err
    return _config_response(config, request)


@app.post("/api/assist/integrations/{integration_id}/mcp/check")
async def api_check_integration_mcp(integration_id: str, request: Request, payload: dict[str, Any] | None = None):
    config = STORE.load()
    integration = config.integration(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if integration.kind != "home_assistant_mcp":
        raise HTTPException(status_code=400, detail="Integration is not an MCP server")

    payload = payload or {}
    return await _check_integration_mcp(config, integration, payload)


@app.post("/api/assist/conversation")
async def api_conversation(payload: dict[str, Any]):
    started_at = time.perf_counter()
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    config = STORE.load()
    flow = config.selected_flow(payload.get("flow_id"))

    async def request():
        result = await run_text_conversation(
            config,
            text=text,
            language=payload.get("language"),
            conversation_id=payload.get("conversation_id"),
            flow_id=flow.id,
            mcp_token=config.effective_mcp_token,
        )
        end_conversation = _should_end_conversation(text, str(result.get("speech") or ""))
        result["end_conversation"] = end_conversation
        result["continue_conversation"] = (
            not bool(result.get("error"))
            and not end_conversation
        )
        if not result.get("error"):
            _start_tts_prefetch(
                config=config,
                flow=flow,
                text=str(result.get("speech") or ""),
                language=payload.get("language"),
            )
        logger.info(
            "HA Assist conversation served flow={} input={} speech={} error={} total_ms={:.0f}",
            flow.id,
            _text_fingerprint(text),
            _text_fingerprint(str(result.get("speech") or "")),
            result.get("error") or "",
            (time.perf_counter() - started_at) * 1000,
        )
        return result

    return await _provider_call("HA Assist conversation", request, attempts=1)


def _json_from_model_text(text: str) -> Any:
    """Parse JSON from a model answer that should contain only JSON."""

    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(clean[start : end + 1])
        except json.JSONDecodeError as err:
            raise ValueError("Model did not return valid JSON") from err
    start = clean.find("[")
    end = clean.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(clean[start : end + 1])
        except json.JSONDecodeError as err:
            raise ValueError("Model did not return valid JSON") from err
    raise ValueError("Model did not return valid JSON")


def _ai_task_prompt(payload: dict[str, Any]) -> str:
    task_name = str(payload.get("task_name") or "AI Task").strip()
    instructions = str(payload.get("instructions") or "").strip()
    fields = payload.get("structure_fields") if isinstance(payload.get("structure_fields"), list) else []
    if not fields:
        return f"Task: {task_name}\n\n{instructions}"

    field_lines = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        required = "required" if field.get("required") else "optional"
        description = str(field.get("description") or "").strip()
        name = str(field.get("name") or "").strip()
        selector = str(field.get("selector") or "").strip()
        detail = f"{name} ({required})"
        extras = ", ".join(part for part in (description, selector) if part)
        field_lines.append(f"- {detail}: {extras}" if extras else f"- {detail}")

    return (
        f"Task: {task_name}\n\n"
        f"{instructions}\n\n"
        "Return only a JSON object for Home Assistant AI Tasks. "
        "Do not include markdown, commentary, or code fences. Fields:\n"
        + "\n".join(field_lines)
    )


@app.post("/api/assist/ai-task")
async def api_ai_task(payload: dict[str, Any]):
    """Run a Home Assistant AI Task through the selected Pipecat Assist text model."""

    config = STORE.load()
    flow = config.selected_flow(payload.get("flow_id"))
    text = _ai_task_prompt(payload)
    if not text.strip():
        raise HTTPException(status_code=400, detail="instructions are required")

    result = await run_text_conversation(
        config,
        text=text,
        language=payload.get("language"),
        conversation_id=payload.get("conversation_id"),
        flow_id=flow.id,
        mcp_token=config.effective_mcp_token,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result.get("speech") or result.get("error"))

    speech = str(result.get("speech") or "").strip()
    data: Any = speech
    if payload.get("structured"):
        try:
            data = _json_from_model_text(speech)
        except ValueError as err:
            raise HTTPException(status_code=502, detail=str(err)) from err

    return {
        "conversation_id": result.get("conversation_id") or payload.get("conversation_id"),
        "data": data,
    }


async def _transcribe_audio_bytes(
    *,
    config: RuntimeConfig,
    flow: FlowConfig,
    audio: bytes,
    metadata: dict[str, Any],
    content_type: str,
) -> dict[str, str]:
    step, integration = _ha_assist_step_integration(config, flow, "stt", HA_STT_BRIDGE_KINDS)
    if not integration:
        raise _bridge_unavailable("STT", _ha_supported_stt_names())
    integration = _require_integration(integration, "STT", fields=())
    model = _step_model_for(step, integration, "stt", _ha_stt_model_fallback(integration))
    if not audio:
        raise HTTPException(status_code=400, detail="No audio was provided")
    stt_audio, stt_content_type = _audio_for_cloud_stt_metadata(audio, metadata, content_type)

    if integration.kind == "sarvam":
        headers = {"api-subscription-key": _integration_api_key_or_400(integration, "STT")}
        data: dict[str, Any] = {"model": model or DEFAULT_SARVAM_STT_MODEL}
        sarvam_language = _runtime_language(flow, integration)
        if sarvam_language:
            data["language_code"] = sarvam_language

        async def request_sarvam_stt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.sarvam.ai/speech-to-text",
                    headers=headers,
                    data=data,
                    files={"file": ("speech.wav", stt_audio, stt_content_type)},
                )
                response.raise_for_status()
                return response

        response = await _provider_call("Sarvam STT", request_sarvam_stt)
        return {"text": str(response.json().get("transcript", "")).strip()}

    raise HTTPException(
        status_code=400,
        detail=f"HA Assist STT bridge does not support {integration.name}. Use {_ha_supported_stt_names()}.",
    )


@app.post("/api/assist/stt")
async def api_stt(request: Request, flow_id: str | None = None):
    """Best-effort STT bridge for the classic Home Assistant Assist pipeline."""

    config = STORE.load()
    flow = config.selected_flow(flow_id)
    metadata = _parse_speech_content(request.headers.get("x-speech-content", ""))
    content_type = request.headers.get("content-type") or "audio/wav"
    return await _transcribe_audio_bytes(
        config=config,
        flow=flow,
        audio=await request.body(),
        metadata=metadata,
        content_type=content_type,
    )


@app.websocket("/api/assist/stt/stream")
async def api_stt_stream(websocket: WebSocket):
    """Buffered STT bridge for the classic Home Assistant Assist pipeline.

    Sarvam's STT API is request/response, not a streaming socket protocol, so
    this buffers audio and calls ``_transcribe_audio_bytes`` once the client
    signals end-of-speech.
    """

    await websocket.accept()
    chunks: list[bytes] = []
    metadata: dict[str, Any] = {}
    content_type = "audio/wav"
    config = STORE.load()
    flow = config.selected_flow(None)

    try:
        start = await websocket.receive_json()
        if not isinstance(start, dict) or start.get("type") != "start":
            await websocket.send_json({"type": "error", "detail": "Expected start message"})
            await websocket.close(code=1003)
            return

        flow = config.selected_flow(start.get("flow_id"))
        metadata = _stt_metadata_from_start(start)
        content_type = str(start.get("content_type") or "audio/wav")
        logger.info(
            "HA Assist STT stream started flow={} content_type={} metadata={}",
            flow.id,
            content_type,
            metadata,
        )

        step, integration = _ha_assist_step_integration(config, flow, "stt", HA_STT_BRIDGE_KINDS)
        if not integration:
            raise _bridge_unavailable("STT", _ha_supported_stt_names())
        integration = _require_integration(integration, "STT", fields=())
        logger.info(
            "HA Assist STT selected flow={} integration={} kind={} mode=buffered",
            flow.id,
            integration.name,
            integration.kind,
        )
        await websocket.send_json({"type": "ready", "mode": "buffered", "provider": integration.kind})

        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                raise WebSocketDisconnect()
            if data := message.get("bytes"):
                chunks.append(data)
                continue
            raw_text = message.get("text")
            if not raw_text:
                continue
            try:
                event = json.loads(raw_text)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "end":
                break

        audio = b"".join(chunks)
        logger.info(
            "HA Assist STT stream received flow={} chunks={} bytes={}",
            flow.id,
            len(chunks),
            len(audio),
        )

        result = await _transcribe_audio_bytes(
            config=config,
            flow=flow,
            audio=audio,
            metadata=metadata,
            content_type=content_type,
        )
        transcript = result.get("text", "")

        logger.info(
            "HA Assist STT stream finished flow={} transcript={}",
            flow.id,
            _text_fingerprint(transcript),
        )
        await websocket.send_json({"type": "final", "text": transcript.strip()})
        await websocket.close()
    except WebSocketDisconnect:
        logger.info("HA Assist STT stream disconnected flow={}", flow.id)
    except HTTPException as err:
        with suppress(Exception):
            await websocket.send_json({"type": "error", "detail": err.detail})
        with suppress(Exception):
            await websocket.close(code=1011)
    except Exception as err:
        logger.exception("HA Assist streaming STT failed: {}", err)
        with suppress(Exception):
            await websocket.send_json({"type": "error", "detail": str(err)})
        with suppress(Exception):
            await websocket.close(code=1011)


def _tts_prefetch_key(flow_id: str, text: str, response_format: str) -> tuple[str, str, str]:
    return (flow_id, response_format, text.strip())


def _text_fingerprint(text: str) -> str:
    clean = text.strip()
    digest = hashlib.sha1(clean.encode("utf-8")).hexdigest()[:10]
    return f"len={len(clean)} sha1={digest}"


def _conversation_end_text(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").replace("ł", "l").replace("Ł", "L"))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9']+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _should_end_conversation(*texts: str | None) -> bool:
    """Return true when the user or assistant clearly closes the conversation."""

    phrase_patterns = (
        r"\b(to wszystko|wystarczy|dziekuje to wszystko|dzieki to wszystko)\b",
        r"\b(dziekuje koniec|dzieki koniec|ok koniec|okej koniec|dobra koniec)\b",
        r"\b(koniec rozmowy|konczymy rozmowe|zakoncz rozmowe|zakonczmy rozmowe)\b",
        r"\b(przestan sluchac|nie sluchaj|nie nasluchuj)\b",
        r"\b(that is all|that's all|thanks that's all|thank you that's all)\b",
        r"\b(end conversation|stop listening|we are done|goodbye|bye for now)\b",
        r"\b(milego dnia|do uslyszenia|do zobaczenia|na razie)\b",
        r"\b(have a nice day|talk to you later|see you later)\b",
    )
    short_end_pattern = re.compile(
        r"^(?:ok|okej|dobra|no|dziekuje|dzieki|thanks|thank you)?\s*"
        r"(?:koniec|wystarczy|goodbye|bye)\s*$"
    )
    for text in texts:
        clean = _conversation_end_text(text)
        if not clean:
            continue
        if short_end_pattern.search(clean):
            return True
        if any(re.search(pattern, clean) for pattern in phrase_patterns):
            return True
    return False


def _prune_tts_prefetch() -> None:
    now = time.time()
    stale = [
        key
        for key, (created_at, task) in TTS_PREFETCH.items()
        if now - created_at > TTS_PREFETCH_TTL_SECONDS or task.cancelled()
    ]
    for key in stale:
        TTS_PREFETCH.pop(key, None)


def _pop_tts_prefetch(
    flow_id: str,
    text: str,
    response_format: str,
) -> tuple[str, float, Any] | None:
    exact_key = _tts_prefetch_key(flow_id, text, response_format)
    cached = TTS_PREFETCH.pop(exact_key, None)
    if cached:
        return "exact", cached[0], cached[1]

    clean = text.strip()
    for key in list(TTS_PREFETCH):
        cached_flow_id, _, cached_text = key
        if cached_flow_id == flow_id and cached_text == clean:
            created_at, task = TTS_PREFETCH.pop(key)
            return "format-fallback", created_at, task
    return None


async def _sarvam_tts_audio(
    *,
    integration: IntegrationConfig,
    text: str,
    model: str,
    voice: str,
    language: str,
    speed: float,
) -> tuple[bytes, str, str]:
    sample_rate = 24000
    payload: dict[str, Any] = {
        "text": text,
        "language_code": language or DEFAULT_SARVAM_LANGUAGE,
        "model": model or DEFAULT_SARVAM_TTS_MODEL,
        "speaker": voice or DEFAULT_SARVAM_TTS_VOICE,
        "speech_sample_rate": sample_rate,
        "output_audio_codec": "linear16",
    }
    if speed and abs(speed - 1.0) > 0.001:
        payload["pace"] = speed
    headers = {
        "api-subscription-key": _integration_api_key_or_400(integration, "TTS"),
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            "https://api.sarvam.ai/text-to-speech",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
    audios = response.json().get("audios") or []
    audio = b"".join(base64.b64decode(chunk) for chunk in audios)
    if not audio:
        raise RuntimeError("Sarvam TTS returned no audio")
    if audio.startswith(b"RIFF"):
        return audio, "audio/wav", "wav"
    return _wav_from_pcm(audio, sample_rate=sample_rate, sample_width=2, channels=1), "audio/wav", "wav"


async def _synthesize_tts_audio(
    *,
    config: RuntimeConfig,
    flow: FlowConfig,
    text: str,
    payload: dict[str, Any],
) -> tuple[bytes, str, str]:
    started_at = time.perf_counter()
    step, integration = _ha_assist_step_integration(config, flow, "tts", HA_TTS_BRIDGE_KINDS)
    if not integration:
        raise _bridge_unavailable("TTS", _ha_supported_tts_names())
    integration = _require_integration(integration, "TTS", fields=())
    model = _step_model_for(step, integration, "tts", _ha_tts_model_fallback(integration))
    voice = _step_voice(step, integration, _ha_tts_voice_fallback(integration))
    language = _runtime_language(flow, integration, payload.get("language"))
    speed = _runtime_speed(flow, integration)
    logger.info(
        "HA Assist TTS synth started flow={} integration={} kind={} model={} voice={} text={}",
        flow.id,
        integration.name,
        integration.kind,
        model,
        voice,
        _text_fingerprint(text),
    )

    if integration.kind == "sarvam":
        audio = await _provider_call(
            "Sarvam TTS",
            lambda: _sarvam_tts_audio(
                integration=integration,
                text=text,
                model=model,
                voice=voice,
                language=language,
                speed=speed,
            ),
        )
        logger.info(
            "HA Assist TTS synth finished flow={} integration={} model={} voice={} duration_ms={:.0f}",
            flow.id,
            integration.name,
            model or DEFAULT_SARVAM_TTS_MODEL,
            voice or DEFAULT_SARVAM_TTS_VOICE,
            (time.perf_counter() - started_at) * 1000,
        )
        return audio

    raise HTTPException(
        status_code=400,
        detail=f"HA Assist TTS bridge does not support {integration.name}. Use {_ha_supported_tts_names()}.",
    )


def _start_tts_prefetch(
    *,
    config: RuntimeConfig,
    flow: FlowConfig,
    text: str,
    language: str | None,
) -> None:
    text = text.strip()
    if not text:
        return
    _prune_tts_prefetch()
    payload = {
        "text": text,
        "language": language or flow.language or "en",
        "options": {"preferred_format": "mp3"},
        "flow_id": flow.id,
    }
    key = _tts_prefetch_key(flow.id, text, "mp3")
    if key in TTS_PREFETCH:
        return

    async def runner() -> tuple[bytes, str, str]:
        started_at = time.perf_counter()
        try:
            return await _synthesize_tts_audio(config=config, flow=flow, text=text, payload=payload)
        finally:
            logger.info(
                "HA Assist TTS prefetch finished flow={} text={} duration_ms={:.0f}",
                flow.id,
                _text_fingerprint(text),
                (time.perf_counter() - started_at) * 1000,
            )

    task = asyncio.create_task(runner())
    logger.info(
        "HA Assist TTS prefetch started flow={} text={} format={}",
        flow.id,
        _text_fingerprint(text),
        "mp3",
    )
    task.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)
    TTS_PREFETCH[key] = (time.time(), task)


@app.post("/api/assist/tts")
async def api_tts(payload: dict[str, Any]):
    """Best-effort TTS bridge for the classic Home Assistant Assist pipeline."""

    started_at = time.perf_counter()
    config = STORE.load()
    flow = config.selected_flow(payload.get("flow_id"))
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text was provided")

    response_format = _preferred_tts_format(payload)
    _prune_tts_prefetch()
    cached = _pop_tts_prefetch(flow.id, text, response_format)
    cache_status = "miss"
    prefetch_age_ms = 0.0
    wait_started_at = time.perf_counter()
    if cached:
        cache_status, created_at, task = cached
        prefetch_age_ms = max(0.0, (time.time() - created_at) * 1000)
        try:
            audio, media_type, extension = await task
        except Exception as err:
            logger.debug("Prefetched TTS failed; synthesizing on demand: {}", err)
            cache_status = f"{cache_status}-failed"
            audio, media_type, extension = await _synthesize_tts_audio(
                config=config,
                flow=flow,
                text=text,
                payload=payload,
            )
    else:
        audio, media_type, extension = await _synthesize_tts_audio(
            config=config,
            flow=flow,
            text=text,
            payload=payload,
        )
    logger.info(
        "HA Assist TTS served flow={} text={} cache={} prefetch_age_ms={:.0f} requested_format={} output={} bytes={} wait_ms={:.0f} total_ms={:.0f}",
        flow.id,
        _text_fingerprint(text),
        cache_status,
        prefetch_age_ms,
        response_format,
        extension,
        len(audio),
        (time.perf_counter() - wait_started_at) * 1000,
        (time.perf_counter() - started_at) * 1000,
    )
    return Response(content=audio, media_type=media_type, headers={"X-Audio-Extension": extension})


@app.get("/api/assist/debug/audio")
async def api_audio_debug():
    config = STORE.load()
    return {
        "enabled": config.audio_debug_enabled,
        "keep_sessions": config.audio_debug_keep_sessions,
        "recordings": list_audio_recordings(),
    }


@app.delete("/api/assist/debug/audio")
async def api_clear_audio_debug():
    config = STORE.load()
    clear_audio_recordings()
    return {
        "enabled": config.audio_debug_enabled,
        "keep_sessions": config.audio_debug_keep_sessions,
        "recordings": [],
    }


@app.get("/api/assist/debug/audio/{filename}")
async def api_audio_debug_file(filename: str):
    try:
        path = audio_debug_file_path(filename)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio debug file not found")
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=filename,
        headers=UI_CACHE_HEADERS,
    )


def _runtime_language(
    flow: FlowConfig,
    integration: IntegrationConfig | None,
    override: str | None = None,
) -> str:
    return (override or "").strip() or (integration.language if integration else "") or flow.language or "en"


def _runtime_speed(flow: FlowConfig, integration: IntegrationConfig | None) -> float:
    return float((integration.speed if integration else None) or flow.speed or 1.0)


def _vad_eagerness(flow: FlowConfig) -> str:
    step = next((item for item in flow.steps if item.kind == "vad"), None)
    return str((step.settings or {}).get("eagerness", "medium") if step else "medium")


def _transport_params(config: RuntimeConfig, flow: FlowConfig) -> dict[str, Any]:
    return {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "websocket": lambda: websocket_transport_params(
            _should_end_conversation,
            follow_up_ms=config.esphome_follow_up_ms,
            follow_up_open_delay_ms=config.esphome_follow_up_open_delay_ms,
            wake_open_delay_ms=config.esphome_wake_open_delay_ms,
            playback_prebuffer_ms=config.esphome_playback_prebuffer_ms,
        ),
    }


def _rtvi_observer_params() -> RTVIObserverParams:
    """Expose live transcript and assistant text events to the WebRTC clients."""

    return RTVIObserverParams(
        bot_output_enabled=True,
        bot_llm_enabled=True,
        bot_tts_enabled=True,
        bot_speaking_enabled=True,
        user_llm_enabled=True,
        user_speaking_enabled=True,
        user_transcription_enabled=True,
        metrics_enabled=True,
    )


def _enabled_step(flow: FlowConfig, kind: str):
    return next((step for step in flow.steps if step.kind == kind and step.enabled), None)


def _step_integration(
    config: RuntimeConfig,
    flow: FlowConfig,
    kind: str,
) -> tuple[Any, IntegrationConfig | None]:
    step = _enabled_step(flow, kind)
    if not step:
        return None, None
    return step, config.integration(step.integration_id)


def _configured_integration(integration: IntegrationConfig | None) -> bool:
    return bool(integration and integration.enabled)


def _ha_assist_step_integration(
    config: RuntimeConfig,
    flow: FlowConfig,
    kind: str,
    supported_kinds: set[str],
) -> tuple[Any, IntegrationConfig | None]:
    """Return the explicit HA Assist step integration without provider fallback."""

    step, integration = _step_integration(config, flow, kind)
    if not step:
        return None, None
    if not integration:
        return step, None
    if integration.kind not in supported_kinds:
        raise HTTPException(
            status_code=400,
            detail=(
                f"HA Assist {kind.upper()} bridge cannot use {integration.name} "
                f"({integration.kind}). Select a {kind.upper()} integration supported by HA Assist."
            ),
        )
    return step, integration


def _bridge_unavailable(role: str, supported_names: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=(
            f"HA Assist {role} requires an enabled explicit {role} step. "
            f"Configure one of: {supported_names}."
        ),
    )


def _ha_supported_stt_names() -> str:
    return "Sarvam AI"


def _ha_supported_tts_names() -> str:
    return "Sarvam AI"


def _ha_stt_model_fallback(integration: IntegrationConfig | None) -> str:
    if not integration:
        return ""
    if integration.kind == "sarvam":
        return integration.default_stt_model or DEFAULT_SARVAM_STT_MODEL
    return integration.default_model or ""


def _ha_tts_model_fallback(integration: IntegrationConfig | None) -> str:
    if not integration:
        return ""
    if integration.kind == "sarvam":
        return integration.default_tts_model or DEFAULT_SARVAM_TTS_MODEL
    return integration.default_tts_model or integration.default_model or ""


def _ha_tts_voice_fallback(integration: IntegrationConfig | None) -> str:
    if not integration:
        return ""
    if integration.kind == "sarvam":
        return integration.default_voice or DEFAULT_SARVAM_TTS_VOICE
    return integration.default_voice or ""


async def _warm_mcp_tools_schema(
    config: RuntimeConfig,
    flow: FlowConfig,
) -> ToolsSchema | None:
    mcp_servers = config.enabled_mcp_servers(config.effective_mcp_token) if flow.mcp_enabled else []
    if not mcp_servers:
        return None
    bridge = CombinedMCPBridge(mcp_servers, flow.mcp_tool_allowlist)
    try:
        await bridge.start()
        tools = await bridge.tools_schema(
            cache_enabled=config.mcp_tools_cache_enabled,
            cache_ttl_seconds=config.mcp_tools_cache_ttl_seconds,
            refresh=False,
        )
        logger.info(
            "HA Assist warmup cached MCP schema flow={} tools={}",
            flow.id,
            len(tools.standard_tools),
        )
        return tools if tools.standard_tools else None
    finally:
        with suppress(Exception):
            await bridge.close()


async def _warm_ha_assist_flow(config: RuntimeConfig, flow: FlowConfig, reason: str) -> None:
    started_at = time.perf_counter()
    try:
        try:
            await _warm_mcp_tools_schema(config, flow)
        except Exception as err:
            logger.debug("HA Assist MCP warmup skipped/failed for flow {}: {}", flow.id, err)
        logger.info(
            "HA Assist warmup finished flow={} reason={} duration_ms={:.0f}",
            flow.id,
            reason,
            (time.perf_counter() - started_at) * 1000,
        )
    except asyncio.CancelledError:
        raise
    except Exception as err:
        logger.debug("HA Assist warmup skipped/failed for flow {}: {}", flow.id, err)


def _schedule_ha_assist_warmup(
    config: RuntimeConfig | None = None,
    *,
    reason: str = "startup",
) -> None:
    global HA_ASSIST_WARMUP_TASK
    try:
        config = config or STORE.load()
        flow = config.selected_flow(None)
    except Exception as err:
        logger.debug("HA Assist warmup could not load configuration: {}", err)
        return

    if HA_ASSIST_WARMUP_TASK and not HA_ASSIST_WARMUP_TASK.done():
        HA_ASSIST_WARMUP_TASK.cancel()
    HA_ASSIST_WARMUP_TASK = asyncio.create_task(_warm_ha_assist_flow(config, flow, reason))

    def _log_result(task: asyncio.Task) -> None:
        with suppress(asyncio.CancelledError):
            if err := task.exception():
                logger.debug("HA Assist warmup task failed: {}", err)

    HA_ASSIST_WARMUP_TASK.add_done_callback(_log_result)


@app.on_event("startup")
async def _startup_warm_ha_assist() -> None:
    _schedule_ha_assist_warmup(reason="startup")
    ESPHOME_PROVISIONER.start()


@app.on_event("shutdown")
async def _shutdown_esphome_provisioner() -> None:
    await ESPHOME_PROVISIONER.stop()


def _secret(integration: IntegrationConfig | None, field: str = "api_key") -> str:
    if not integration:
        return ""
    return str(getattr(integration, field, "") or "").strip()


def _require_integration(
    integration: IntegrationConfig | None,
    role: str,
    fields: tuple[str, ...] = ("api_key",),
) -> IntegrationConfig:
    if not integration:
        raise RuntimeError(f"{role} integration is not selected")
    if not integration.enabled:
        raise RuntimeError(f"{integration.name} is disabled")
    if fields and not any(_secret(integration, field) for field in fields):
        readable = " or ".join(fields)
        raise RuntimeError(f"{integration.name} is missing {readable}")
    return integration


def _enabled_web_search_step(flow: FlowConfig):
    return _enabled_step(flow, "web_search")


def _web_search_enabled(flow: FlowConfig) -> bool:
    return bool(flow.web_search_enabled or _enabled_web_search_step(flow))


def _memory_enabled(config: RuntimeConfig, flow: FlowConfig) -> bool:
    memory_step = _enabled_step(flow, "memory")
    return config.session_memory_enabled and (flow.memory_enabled or memory_step is not None)


def _web_search_announces(flow: FlowConfig) -> bool:
    step = _enabled_web_search_step(flow)
    if not step:
        return False
    return bool((step.settings or {}).get("announce", True))


def _tools_include_device_list(flow: FlowConfig) -> bool:
    step = _enabled_step(flow, "tools")
    if not step:
        return False
    return bool((step.settings or {}).get("include_device_list", True))


def _effective_instructions(flow: FlowConfig, voice: str = "") -> str:
    instructions = flow.instructions
    if CONVERSATION_END_SYSTEM_HINT not in instructions:
        instructions += f"\n\n{CONVERSATION_END_SYSTEM_HINT}"
    if _web_search_announces(flow):
        instructions += (
            "\n\nWhen you decide to use web search, first say "
            '"Please hold, I\'m checking." Then run the search and answer briefly.'
        )
    gender_rule = gender_instruction(voice)
    if gender_rule:
        instructions += f"\n\n{gender_rule}"
    return instructions


def _web_search_tool_schema(config: RuntimeConfig, flow: FlowConfig) -> FunctionSchema | None:
    """Return the web_search tool schema for a flow, when enabled and configured.

    The model calls this tool directly against Tavily's search API - no LLM
    is used to do the searching itself.
    """

    if not _web_search_enabled(flow):
        return None
    _, integration = _step_integration(config, flow, "web_search")
    integration = integration or config.integration("web-search")
    if not integration or not integration.enabled or not integration.api_key.strip():
        return None

    api_key = integration.api_key.strip()

    async def search(query: str) -> str:
        return await run_tavily_search(api_key, query)

    return web_search_schema(search)


def _merge_tools_schema(
    base_schema,
    extra_tools: list[FunctionSchema] | None = None,
) -> ToolsSchema | None:
    """Return one ToolsSchema with MCP and local assistant tools."""

    tools: list[FunctionSchema] = []
    if base_schema and getattr(base_schema, "standard_tools", None):
        tools.extend(base_schema.standard_tools)
    tools.extend(extra_tools or [])
    return ToolsSchema(standard_tools=tools) if tools else None


def _register_local_tool_handlers(llm, tools: list[FunctionSchema]) -> None:
    """Register local function handlers when the LLM service needs explicit callbacks."""

    for schema in tools:
        handler = getattr(schema, "handler", None)
        if handler:
            llm.register_function(schema.name, handler)


def _integration_api_key(
    integration: IntegrationConfig,
    role: str,
    fallback: str = "",
) -> str:
    api_key = (integration.api_key or fallback or "").strip()
    if not api_key:
        raise RuntimeError(f"{integration.name} is missing api_key for {role}")
    return api_key


def _integration_api_key_or_400(
    integration: IntegrationConfig,
    role: str,
    fallback: str = "",
) -> str:
    try:
        return _integration_api_key(integration, role, fallback)
    except RuntimeError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


def _step_model(step, integration: IntegrationConfig | None, fallback: str = "") -> str:
    return (
        (getattr(step, "model", "") if step else "")
        or (integration.default_model if integration else "")
        or fallback
    ).strip()


def _step_model_for(
    step,
    integration: IntegrationConfig | None,
    capability: str,
    fallback: str = "",
) -> str:
    if getattr(step, "model", ""):
        return step.model.strip()
    if not integration:
        return fallback.strip()
    if capability == "stt":
        return (integration.default_stt_model or fallback).strip()
    if capability == "tts":
        return (integration.default_tts_model or integration.default_model or fallback).strip()
    return (integration.default_model or fallback).strip()


def _step_voice(step, integration: IntegrationConfig | None, fallback: str = "") -> str:
    return (
        (getattr(step, "voice", "") if step else "")
        or (integration.default_voice if integration else "")
        or fallback
    ).strip()


def _instruction_role(integration: IntegrationConfig | None) -> str:
    """Return the chat role used for system instructions in composed context messages.

    Sarvam's own adapter (app/sarvam_llm.py) converts "developer" to "system"
    itself. Generic OpenAI-compatible "local" servers (Ollama/vLLM/LM Studio)
    don't get that conversion from vanilla OpenAILLMService, so build the
    message with the right role directly instead of relying on one.
    """

    return "system" if integration and integration.kind == "local" else "developer"


def _provider_names_for_kinds(config: RuntimeConfig, kinds: set[str]) -> str:
    names = sorted({item.name for item in config.integrations if item.kind in kinds})
    return ", ".join(names or sorted(kinds))


def _runtime_flow_errors(config: RuntimeConfig, flow: FlowConfig) -> list[str]:
    """Return pipeline errors that would prevent a WebRTC runtime from starting."""

    errors: list[str] = []
    if not flow.enabled:
        errors.append(f"Pipeline {flow.name} is disabled.")

    role_labels = {"stt": "STT", "llm": "LLM", "tts": "TTS"}
    for kind, supported_kinds in COMPOSED_STEP_PROVIDER_KINDS.items():
        step, integration = _step_integration(config, flow, kind)
        label = role_labels[kind]
        if not step:
            errors.append(f"Composed pipeline needs an enabled {label} step.")
            continue
        if not step.integration_id:
            errors.append(f"{step.label or label} needs an integration.")
            continue
        if not integration:
            errors.append(f"{step.label or label} uses missing integration {step.integration_id}.")
            continue
        if integration.kind not in supported_kinds:
            supported_names = _provider_names_for_kinds(config, supported_kinds)
            errors.append(
                f"{integration.name} cannot be used as {label} in this pipeline. "
                f"Use one of: {supported_names}."
            )
            continue
        if not integration.enabled:
            errors.append(f"{integration.name} is disabled.")

    return errors


def _runner_body(runner_args: RunnerArguments) -> dict[str, Any]:
    body = runner_args.body if isinstance(runner_args.body, dict) else {}
    request_data = body.get("request_data")
    return request_data if isinstance(request_data, dict) else body


def _session_client_id(runner_args: RunnerArguments, flow: FlowConfig) -> str:
    body = _runner_body(runner_args)
    for key in ("client_id", "device_id", "satellite_id", "source"):
        value = str(body.get(key, "")).strip()
        if value:
            return f"{flow.id}:{value}"
    return f"{flow.id}:default"


def _composed_vad_analyzer(flow: FlowConfig):
    """Return local VAD tuned for browser and ESP32 composed pipelines."""

    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams

    stop_secs_by_eagerness = {
        "high": 0.2,
        "medium": 0.2,
        "auto": 0.2,
        "low": 0.2,
    }
    return SileroVADAnalyzer(
        params=VADParams(
            confidence=0.7,
            start_secs=0.12,
            stop_secs=stop_secs_by_eagerness.get(_vad_eagerness(flow), 0.45),
            min_volume=0.02,
        )
    )


def _build_stt_service(
    config: RuntimeConfig,
    flow: FlowConfig,
    language_override: str | None = None,
):
    step, integration = _step_integration(config, flow, "stt")
    integration = _require_integration(integration, "STT", fields=())
    model = _step_model_for(step, integration, "stt")
    language = _runtime_language(flow, integration, language_override)
    if integration.kind == "sarvam":
        # Sarvam's language is a fixed pipeline setting, not something a
        # client-sent locale hint should be able to override.
        language = (integration.language or DEFAULT_SARVAM_LANGUAGE).strip()
    logger.info(
        "Building composed STT service integration={} kind={} model={} language={}",
        integration.name,
        integration.kind,
        model or "",
        language,
    )

    if integration.kind == "sarvam":
        from pipecat.services.sarvam.stt import SarvamSTTService

        return SarvamSTTService(
            api_key=_integration_api_key(integration, "STT"),
            settings=SarvamSTTService.Settings(
                model=model or DEFAULT_SARVAM_STT_MODEL,
                language=language,
            ),
        )

    raise RuntimeError(f"STT provider {integration.kind} is not supported by composed runtime")


def _build_llm_service(config: RuntimeConfig, flow: FlowConfig, tools_schema=None, voice: str = ""):
    step, integration = _step_integration(config, flow, "llm")
    integration = _require_integration(integration, "LLM", fields=())
    model = _step_model_for(step, integration, "llm")

    if integration.kind == "sarvam":
        from app.sarvam_llm import SarvamLLMService

        sarvam_reasoning_effort = (
            flow.reasoning_effort if flow.reasoning_effort in {"low", "medium", "high"} else None
        )
        settings_kwargs: dict[str, Any] = {
            "model": model or DEFAULT_SARVAM_LLM_MODEL,
            "system_instruction": _effective_instructions(flow, voice),
            "reasoning_effort": sarvam_reasoning_effort,
        }
        if flow.max_output_tokens:
            settings_kwargs["max_tokens"] = flow.max_output_tokens
        return SarvamLLMService(
            api_key=_integration_api_key(integration, "LLM"),
            settings=SarvamLLMService.Settings(**settings_kwargs),
        )
    if integration.kind == "local":
        from pipecat.services.openai.llm import OpenAILLMService

        settings_kwargs: dict[str, Any] = {
            "model": model or integration.default_model or DEFAULT_LOCAL_LLM_MODEL,
            "system_instruction": _effective_instructions(flow, voice),
        }
        if flow.max_output_tokens:
            settings_kwargs["max_tokens"] = flow.max_output_tokens
        return OpenAILLMService(
            api_key=integration.api_key or "not-needed",
            base_url=integration.base_url or None,
            settings=OpenAILLMService.Settings(**settings_kwargs),
        )

    raise RuntimeError(f"LLM provider {integration.kind} is not supported by composed runtime")


def _build_tts_service(config: RuntimeConfig, flow: FlowConfig):
    step, integration = _step_integration(config, flow, "tts")
    integration = _require_integration(integration, "TTS", fields=())
    model = _step_model_for(step, integration, "tts")
    voice = _step_voice(step, integration)
    speed = _runtime_speed(flow, integration)

    if integration.kind == "sarvam":
        from pipecat.services.sarvam.tts import SarvamTTSService

        sarvam_language = (integration.language or DEFAULT_SARVAM_LANGUAGE).strip()
        return SarvamTTSService(
            api_key=_integration_api_key(integration, "TTS"),
            text_aggregation_mode=None,
            settings=SarvamTTSService.Settings(
                model=model or DEFAULT_SARVAM_TTS_MODEL,
                voice=voice or DEFAULT_SARVAM_TTS_VOICE,
                language=sarvam_language,
                pace=speed,
            ),
        )

    raise RuntimeError(f"TTS provider {integration.kind} is not supported by composed runtime")


async def run_bot(
    transport: BaseTransport,
    runner_args: RunnerArguments,
    config: RuntimeConfig,
    flow: FlowConfig,
    mcp_token: str = "",
):
    """Run one Pipecat session."""

    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    session_body = _runner_body(runner_args)
    is_esphome_satellite = session_body.get("transport") == "va-pipecat"
    client_id = _session_client_id(runner_args, flow)
    language_override = str(session_body.get("language") or "").strip() or None

    bridge: CombinedMCPBridge | None = None
    mcp_tools_schema = None
    mcp_servers = config.enabled_mcp_servers(mcp_token) if flow.mcp_enabled else []
    if mcp_servers:
        bridge = CombinedMCPBridge(mcp_servers, flow.mcp_tool_allowlist)
        try:
            await bridge.start()
            mcp_tools_schema = await bridge.tools_schema(
                cache_enabled=config.mcp_tools_cache_enabled,
                cache_ttl_seconds=config.mcp_tools_cache_ttl_seconds,
            )
            if not mcp_tools_schema.standard_tools:
                mcp_tools_schema = None
        except asyncio.CancelledError as err:
            with suppress(Exception):
                await bridge.close()
            bridge = None
            raise RuntimeError(f"MCP tools are enabled but startup was cancelled: {err}") from err
        except Exception as err:
            with suppress(Exception):
                await bridge.close()
            bridge = None
            raise RuntimeError(f"MCP tools are enabled but unavailable: {err}") from err

    local_tool_schemas = [schema for schema in [_web_search_tool_schema(config, flow)] if schema]
    tools_schema = _merge_tools_schema(mcp_tools_schema, local_tool_schemas)

    tts_step, tts_integration = _step_integration(config, flow, "tts")
    speaker_voice = _step_voice(tts_step, tts_integration)

    stt = _build_stt_service(config, flow, language_override=language_override)
    llm = _build_llm_service(config, flow, tools_schema=tools_schema, voice=speaker_voice)
    _register_local_tool_handlers(llm, local_tool_schemas)
    tts = _build_tts_service(config, flow)

    _, stt_integration = _step_integration(config, flow, "stt")
    llm_step, llm_integration = _step_integration(config, flow, "llm")
    llm_model = _step_model(llm_step, llm_integration)
    provider_label = "+".join(
        item.kind
        for item in (stt_integration, llm_integration, tts_integration)
        if item is not None
    )
    logger.info(
        "Starting composed realtime pipeline {} with LLM {} for flow {}",
        provider_label,
        llm_model,
        flow.id,
    )

    instruction_role = _instruction_role(llm_integration)
    context_messages = [
        {"role": instruction_role, "content": _effective_instructions(flow, speaker_voice)}
    ]
    if flow.greeting.strip():
        context_messages.append({"role": instruction_role, "content": flow.greeting})
    if bridge and _tools_include_device_list(flow):
        try:
            device_entities = await bridge.device_context()
            device_list_text = build_device_list_text(device_entities)
            if device_list_text:
                context_messages.append({"role": instruction_role, "content": device_list_text})
                logger.info(
                    "Loaded {} exposed Home Assistant devices into context for flow {}",
                    len(device_entities),
                    flow.id,
                )
        except Exception as err:
            logger.warning("Device context unavailable for flow {}: {}", flow.id, err)
    context_messages = SESSION_MEMORY.restore(
        client_id,
        context_messages,
        enabled=_memory_enabled(config, flow),
        reuse_seconds=config.session_memory_reuse_seconds,
        max_messages=config.session_memory_max_messages,
    )
    context = LLMContext(context_messages, tools_schema) if tools_schema else LLMContext(context_messages)
    context_for_memory = context
    vad_step = _enabled_step(flow, "vad")
    vad_processor = VADProcessor(vad_analyzer=_composed_vad_analyzer(flow)) if vad_step else None
    if vad_step:
        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(
                    stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.2)]
                ),
                user_turn_stop_timeout=2.0,
            ),
        )
    else:
        context_aggregator = LLMContextAggregatorPair(context)

    if bridge and mcp_tools_schema:
        await bridge.register_tools_schema(mcp_tools_schema, llm)

    audio_debug = None
    if config.audio_debug_enabled:
        try:
            audio_debug = create_audio_debug_session(
                config,
                flow,
                provider_label or "composed",
                llm_model,
            )
        except Exception as err:
            logger.warning("Audio debug recorder could not start: {}", err)

    processors = [transport.input()]
    if vad_processor:
        processors.append(vad_processor)
    if audio_debug:
        processors.append(audio_debug.input_recorder)
    processors.extend([stt, context_aggregator.user(), llm, tts])
    if audio_debug:
        processors.append(audio_debug.output_recorder)
    processors.extend([transport.output(), context_aggregator.assistant()])

    pipeline = Pipeline(processors)
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        rtvi_observer_params=_rtvi_observer_params(),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected to composed flow {}", flow.id)
        if flow.greeting.strip() and not is_esphome_satellite:
            await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected from flow {}", flow.id)
        await worker.cancel()

    try:
        runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
        await runner.add_workers(worker)
        await runner.run()
    finally:
        if context_for_memory:
            SESSION_MEMORY.cache(
                client_id,
                context_for_memory,
                enabled=_memory_enabled(config, flow),
                max_messages=config.session_memory_max_messages,
            )
        if bridge:
            await bridge.close()
        if audio_debug:
            with suppress(Exception):
                audio_debug.close()


async def bot(runner_args: RunnerArguments):
    """Pipecat runner entry point."""

    config = STORE.load()
    body = _runner_body(runner_args)
    flow = config.selected_flow(body.get("flow_id"))
    flow_errors = _runtime_flow_errors(config, flow)
    if flow_errors:
        raise RuntimeError(flow_errors[0])
    transport = await create_transport(runner_args, _transport_params(config, flow))
    await run_bot(transport, runner_args, config, flow, mcp_token=config.effective_mcp_token)


def main() -> None:
    _configure_logging()
    parser = argparse.ArgumentParser(description="Pipecat Assist")
    runner_main(parser)


if __name__ == "__main__":
    main()
