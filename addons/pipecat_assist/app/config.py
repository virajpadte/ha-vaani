"""Runtime configuration for the Vaani add-on."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DATA_DIR = Path(os.getenv("PIPECAT_ASSIST_DATA_DIR", "/data"))
CONFIG_PATH = DATA_DIR / "pipecat_assist.json"
REDACTED = "__redacted__"

DEFAULT_INSTRUCTIONS = (
    "You are a realtime Home Assistant voice agent. Speak naturally and briefly. "
    "Use Home Assistant MCP tools only when the user clearly asks to control, "
    "inspect, or automate the home. Never invent device state. If a room, "
    "device, or action is ambiguous, ask one short clarification."
)

DEFAULT_SARVAM_STT_MODEL = "saaras:v3"
DEFAULT_SARVAM_TTS_MODEL = "bulbul:v3"
DEFAULT_SARVAM_TTS_VOICE = "shubh"
DEFAULT_SARVAM_LLM_MODEL = "sarvam-105b-conversations"
DEFAULT_SARVAM_LANGUAGE = "en-IN"
DEFAULT_LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LOCAL_LLM_MODEL = "llama3.2"
DEFAULT_MCP_URL = "http://supervisor/core/api/mcp"

SECRET_FIELDS = ("api_key", "token")

COMPOSED_STT_PROVIDER_KINDS = {"sarvam"}
COMPOSED_LLM_PROVIDER_KINDS = {"sarvam", "local"}
COMPOSED_TTS_PROVIDER_KINDS = {"sarvam"}
COMPOSED_STEP_PROVIDER_KINDS = {
    "stt": COMPOSED_STT_PROVIDER_KINDS,
    "llm": COMPOSED_LLM_PROVIDER_KINDS,
    "tts": COMPOSED_TTS_PROVIDER_KINDS,
}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _is_http_url(value: str | None) -> bool:
    value = (value or "").strip().lower()
    return value.startswith("http://") or value.startswith("https://")


def _validate_id(value: str, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{label} cannot be empty")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if any(char not in allowed for char in clean):
        raise ValueError(f"{label} may only contain letters, numbers, _ and -")
    return clean


class IntegrationConfig(BaseModel):
    """One cloud/local model provider or Home Assistant integration."""

    id: str
    name: str
    kind: Literal["sarvam", "local", "web_search", "home_assistant_mcp"]
    enabled: bool = False
    api_key: str = ""
    token: str = ""
    base_url: str = ""
    language: str = "en"
    speed: float = Field(default=1.0, ge=0.25, le=1.5)
    default_model: str = ""
    default_stt_model: str = ""
    default_tts_model: str = ""
    default_voice: str = ""

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_id(value, "Integration id")


class PipelineStepConfig(BaseModel):
    """One step in the fixed Vaani pipeline."""

    id: str
    kind: Literal["transport", "memory", "vad", "stt", "llm", "web_search", "tools", "tts"]
    label: str
    enabled: bool = True
    integration_id: str = ""
    model: str = ""
    voice: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_id(value, "Pipeline step id")


def default_integrations() -> list[IntegrationConfig]:
    """Return first-run integrations shown in the UI."""

    return [
        IntegrationConfig(
            id="sarvam",
            name="Sarvam AI",
            kind="sarvam",
            enabled=bool(os.getenv("SARVAM_API_KEY")),
            api_key=os.getenv("SARVAM_API_KEY", ""),
            language=os.getenv("SARVAM_LANGUAGE", DEFAULT_SARVAM_LANGUAGE),
            default_model=os.getenv("SARVAM_LLM_MODEL", DEFAULT_SARVAM_LLM_MODEL),
            default_stt_model=os.getenv("SARVAM_STT_MODEL", DEFAULT_SARVAM_STT_MODEL),
            default_tts_model=os.getenv("SARVAM_TTS_MODEL", DEFAULT_SARVAM_TTS_MODEL),
            default_voice=os.getenv("SARVAM_TTS_VOICE", DEFAULT_SARVAM_TTS_VOICE),
        ),
        IntegrationConfig(
            id="local",
            name="Local (OpenAI-compatible)",
            kind="local",
            enabled=False,
            base_url=os.getenv("LOCAL_LLM_BASE_URL", DEFAULT_LOCAL_LLM_BASE_URL),
            default_model=os.getenv("LOCAL_LLM_MODEL", DEFAULT_LOCAL_LLM_MODEL),
        ),
        IntegrationConfig(
            id="web-search",
            name="Web Search",
            kind="web_search",
            enabled=False,
            api_key=os.getenv("TAVILY_API_KEY", ""),
        ),
        IntegrationConfig(
            id="ha-mcp",
            name="Home Assistant MCP",
            kind="home_assistant_mcp",
            enabled=True,
            base_url=os.getenv("HA_MCP_URL", ""),
            token=os.getenv("LONGLIVED_TOKEN", ""),
        ),
    ]


def default_steps() -> list[PipelineStepConfig]:
    """Return the fixed Vaani pipeline: STT -> LLM -> Tools -> TTS, +Memory/VAD."""

    return [
        PipelineStepConfig(id="transport", kind="transport", label="WebRTC"),
        PipelineStepConfig(id="memory", kind="memory", label="Session memory"),
        PipelineStepConfig(
            id="vad",
            kind="vad",
            label="Turn detection",
            settings={"eagerness": "medium"},
        ),
        PipelineStepConfig(id="stt", kind="stt", label="STT", integration_id="sarvam"),
        PipelineStepConfig(id="llm", kind="llm", label="Model", integration_id="sarvam"),
        PipelineStepConfig(
            id="web-search",
            kind="web_search",
            label="Web Search",
            enabled=False,
            integration_id="web-search",
            settings={"announce": True},
        ),
        PipelineStepConfig(
            id="tools",
            kind="tools",
            label="HA MCP tools",
            integration_id="ha-mcp",
            settings={"include_device_list": True},
        ),
        PipelineStepConfig(id="tts", kind="tts", label="TTS", integration_id="sarvam"),
    ]


class FlowConfig(BaseModel):
    """The Vaani pipeline for one Home Assistant voice flow."""

    id: str = "home-default"
    name: str = "Vaani"
    enabled: bool = True
    speed: float = Field(default=1.0, ge=0.25, le=1.5)
    language: str | None = "en-IN"
    instructions: str = DEFAULT_INSTRUCTIONS
    greeting: str = "Greet the user briefly and wait for their request."
    max_output_tokens: int | None = Field(default=None, ge=1, le=4096)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    mcp_enabled: bool = True
    mcp_tool_allowlist: list[str] = Field(default_factory=list)
    memory_enabled: bool = True
    web_search_enabled: bool = False
    steps: list[PipelineStepConfig] = Field(default_factory=default_steps)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_id(value, "Flow id")

    def model_step(self) -> PipelineStepConfig | None:
        """Return the primary LLM step."""

        return next((step for step in self.steps if step.kind == "llm" and step.enabled), None)


class RuntimeConfig(BaseModel):
    """Persisted runtime configuration edited by the web UI."""

    version: int = 22
    ha_mcp_url: str = ""
    longlived_token: str = ""
    satellite_shared_secret: str = ""
    runner_host: str = ""
    runner_port: int = Field(default=7860, ge=1024, le=65535)
    esphome_follow_up_ms: int = Field(default=30000, ge=0, le=60000)
    esphome_follow_up_open_delay_ms: int = Field(default=80, ge=0, le=5000)
    esphome_wake_open_delay_ms: int = Field(default=0, ge=0, le=5000)
    esphome_playback_prebuffer_ms: int = Field(default=300, ge=0, le=2000)
    esp32_mode: bool = False
    enable_default_ice_servers: bool = False
    audio_debug_enabled: bool = False
    audio_debug_keep_sessions: int = Field(default=10, ge=1, le=100)
    session_memory_enabled: bool = True
    session_memory_reuse_seconds: int = Field(default=300, ge=0, le=86400)
    session_memory_max_messages: int = Field(default=12, ge=0, le=100)
    mcp_tools_cache_enabled: bool = True
    mcp_tools_cache_ttl_seconds: int = Field(default=300, ge=0, le=86400)
    selected_flow_id: str = "home-default"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    integrations: list[IntegrationConfig] = Field(default_factory=default_integrations)
    flows: list[FlowConfig] = Field(default_factory=lambda: [FlowConfig()])

    @field_validator("flows")
    @classmethod
    def validate_flows(cls, value: list[FlowConfig]) -> list[FlowConfig]:
        if not value:
            raise ValueError("At least one flow is required")
        ids = [flow.id for flow in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Flow ids must be unique")
        return value

    @field_validator("integrations")
    @classmethod
    def validate_integrations(cls, value: list[IntegrationConfig]) -> list[IntegrationConfig]:
        if not value:
            raise ValueError("At least one integration is required")
        ids = [integration.id for integration in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Integration ids must be unique")
        return value

    def selected_flow(self, requested_flow_id: str | None = None) -> FlowConfig:
        """Return the requested flow, falling back to selected/default flow."""

        candidates = [requested_flow_id, self.selected_flow_id, self.flows[0].id]
        for candidate in candidates:
            if not candidate:
                continue
            for flow in self.flows:
                if flow.id == candidate:
                    return flow
        return self.flows[0]

    def integration(self, integration_id: str | None) -> IntegrationConfig | None:
        """Return an integration by id."""

        if not integration_id:
            return None
        return next((item for item in self.integrations if item.id == integration_id), None)

    def model_integration(self, flow: FlowConfig) -> IntegrationConfig | None:
        """Return the integration used by the primary model step."""

        step = flow.model_step()
        return self.integration(step.integration_id if step else None)

    @property
    def mcp_integration(self) -> IntegrationConfig | None:
        """Return the Home Assistant MCP integration."""

        return next(
            (item for item in self.integrations if item.kind == "home_assistant_mcp"),
            None,
        )

    @property
    def effective_mcp_url(self) -> str:
        """Return the MCP URL used by the add-on."""

        integration = self.mcp_integration
        for candidate in (
            integration.base_url if integration else "",
            self.ha_mcp_url,
            os.getenv("HA_MCP_URL"),
            DEFAULT_MCP_URL,
        ):
            if _is_http_url(candidate):
                return candidate.strip()
        return DEFAULT_MCP_URL

    @property
    def effective_mcp_token(self) -> str:
        """Return the Home Assistant token used for MCP."""

        integration = self.mcp_integration
        return (
            (integration.token if integration else "")
            or self.longlived_token
            or os.getenv("LONGLIVED_TOKEN")
            or os.getenv("SUPERVISOR_TOKEN", "")
        )

    @property
    def effective_mcp_token_source(self) -> str:
        """Return where the effective MCP token came from."""

        integration = self.mcp_integration
        if integration and integration.token:
            return "integration"
        if self.longlived_token or os.getenv("LONGLIVED_TOKEN"):
            return "long-lived"
        if os.getenv("SUPERVISOR_TOKEN"):
            return "supervisor"
        return ""

    def enabled_mcp_servers(self, token_override: str = "") -> list[dict[str, Any]]:
        """Return the enabled Home Assistant MCP server connection spec (Supervisor only)."""

        integration = self.mcp_integration
        if not integration or not integration.enabled:
            return []
        url = self.effective_mcp_url
        token = token_override or self.effective_mcp_token
        if not _is_http_url(url):
            return []
        return [
            {
                "id": integration.id,
                "name": integration.name,
                "url": url,
                "token": token,
                "prefer_unprefixed": True,
            }
        ]

    def public_dict(self) -> dict[str, Any]:
        """Return configuration safe enough for the UI."""

        data = self.model_dump()
        for key in ("longlived_token", "satellite_shared_secret"):
            configured = bool(data.get(key))
            data[f"{key}_configured"] = configured
            data[key] = REDACTED if configured else ""

        for integration in data["integrations"]:
            for key in SECRET_FIELDS:
                configured = bool(integration.get(key))
                integration[f"{key}_configured"] = configured
                integration[key] = REDACTED if configured else ""

        data["effective_mcp_url"] = self.effective_mcp_url
        data["mcp_token_source"] = self.effective_mcp_token_source
        return data


def default_config_from_environment() -> RuntimeConfig:
    """Create the first-run configuration from add-on options or environment."""

    instructions = os.getenv("INSTRUCTIONS") or DEFAULT_INSTRUCTIONS
    tool_allowlist = _split_csv(os.getenv("MCP_TOOL_ALLOWLIST"))
    flow = FlowConfig(
        instructions=instructions,
        mcp_tool_allowlist=tool_allowlist,
    )
    return RuntimeConfig(
        ha_mcp_url=os.getenv("HA_MCP_URL", ""),
        longlived_token=os.getenv("LONGLIVED_TOKEN", ""),
        satellite_shared_secret=os.getenv("SATELLITE_SHARED_SECRET", ""),
        runner_host=os.getenv("RUNNER_HOST", ""),
        runner_port=_env_int("RUNNER_PORT", 7860),
        esphome_follow_up_ms=max(0, min(60000, _env_int("ESPHOME_FOLLOW_UP_MS", 30000))),
        esphome_follow_up_open_delay_ms=max(
            0, min(5000, _env_int("ESPHOME_FOLLOW_UP_OPEN_DELAY_MS", 80))
        ),
        esphome_wake_open_delay_ms=max(0, min(5000, _env_int("ESPHOME_WAKE_OPEN_DELAY_MS", 0))),
        esphome_playback_prebuffer_ms=max(
            0, min(2000, _env_int("ESPHOME_PLAYBACK_PREBUFFER_MS", 300))
        ),
        esp32_mode=_env_bool("ESP32_MODE", False),
        audio_debug_enabled=_env_bool("AUDIO_DEBUG_ENABLED", False),
        audio_debug_keep_sessions=min(100, max(1, _env_int("AUDIO_DEBUG_KEEP_SESSIONS", 10))),
        session_memory_enabled=_env_bool("SESSION_MEMORY_ENABLED", True),
        session_memory_reuse_seconds=max(0, min(86400, _env_int("SESSION_MEMORY_REUSE_SECONDS", 300))),
        session_memory_max_messages=max(0, min(100, _env_int("SESSION_MEMORY_MAX_MESSAGES", 12))),
        mcp_tools_cache_enabled=_env_bool("MCP_TOOLS_CACHE_ENABLED", True),
        mcp_tools_cache_ttl_seconds=max(0, min(86400, _env_int("MCP_TOOLS_CACHE_TTL_SECONDS", 300))),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        flows=[flow],
    )


_VALID_INTEGRATION_KINDS = {"sarvam", "local", "web_search", "home_assistant_mcp"}
_VALID_STEP_KINDS = {"transport", "memory", "vad", "stt", "llm", "web_search", "tools", "tts"}
_STEP_DEFAULT_INTEGRATION = {
    "stt": "sarvam",
    "llm": "sarvam",
    "tts": "sarvam",
    "tools": "ha-mcp",
    "web_search": "web-search",
}


def _sanitize_legacy_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Drop providers/steps from older (pre-Sarvam-only) configs that no longer validate.

    Pydantic silently ignores unknown dict *fields*, but a ``kind`` value outside the
    current (now much narrower) Literal would hard-fail validation - this runs on the raw
    JSON before validation so an in-place upgrade from the old multi-provider config loads
    instead of crashing. Any step left pointing at a removed integration is remapped to the
    equivalent fixed-pipeline default rather than left dangling.
    """

    data = dict(raw)
    integrations = data.get("integrations")
    valid_ids: set[str] = set()
    if isinstance(integrations, list):
        kept = [
            item
            for item in integrations
            if isinstance(item, dict) and item.get("kind") in _VALID_INTEGRATION_KINDS
        ]
        data["integrations"] = kept
        valid_ids = {item.get("id") for item in kept}

    flows = data.get("flows")
    if isinstance(flows, list):
        new_flows = []
        for flow in flows:
            if not isinstance(flow, dict):
                continue
            flow = dict(flow)
            steps = flow.get("steps")
            if isinstance(steps, list):
                kept_steps = []
                for step in steps:
                    if not isinstance(step, dict) or step.get("kind") not in _VALID_STEP_KINDS:
                        continue
                    if step.get("integration_id") not in valid_ids:
                        step = dict(step)
                        step["integration_id"] = _STEP_DEFAULT_INTEGRATION.get(step.get("kind"), "")
                    kept_steps.append(step)
                flow["steps"] = kept_steps
            new_flows.append(flow)
        data["flows"] = new_flows

    return data


def _repair_mcp_url_overrides(config: RuntimeConfig) -> bool:
    """Clear custom MCP URLs that httpx cannot use."""

    changed = False
    if config.ha_mcp_url and not _is_http_url(config.ha_mcp_url):
        config.ha_mcp_url = ""
        changed = True

    mcp = config.mcp_integration
    if mcp and mcp.base_url and not _is_http_url(mcp.base_url):
        mcp.base_url = ""
        changed = True

    return changed


def _repair_provider_defaults(config: RuntimeConfig) -> bool:
    """Repair provider defaults that can be pasted across integrations."""

    changed = False

    sarvam = config.integration("sarvam")
    if sarvam:
        if sarvam.name != "Sarvam AI":
            sarvam.name = "Sarvam AI"
            changed = True
        if not sarvam.language:
            sarvam.language = os.getenv("SARVAM_LANGUAGE", DEFAULT_SARVAM_LANGUAGE)
            changed = True
        else:
            from app.sarvam_languages import SARVAM_LANGUAGE_CODES

            if sarvam.language.strip() not in SARVAM_LANGUAGE_CODES:
                sarvam.language = DEFAULT_SARVAM_LANGUAGE
                changed = True
        if not sarvam.default_model or sarvam.default_model in {"sarvam-30b", "sarvam-30b-16k"}:
            sarvam.default_model = os.getenv("SARVAM_LLM_MODEL", DEFAULT_SARVAM_LLM_MODEL)
            changed = True
        if not sarvam.default_stt_model or sarvam.default_stt_model == "saaras:v4":
            sarvam.default_stt_model = os.getenv("SARVAM_STT_MODEL", DEFAULT_SARVAM_STT_MODEL)
            changed = True
        if not sarvam.default_tts_model:
            sarvam.default_tts_model = os.getenv("SARVAM_TTS_MODEL", DEFAULT_SARVAM_TTS_MODEL)
            changed = True
        if not sarvam.default_voice:
            sarvam.default_voice = os.getenv("SARVAM_TTS_VOICE", DEFAULT_SARVAM_TTS_VOICE)
            changed = True
        else:
            from app.sarvam_voices import speakers_for_model

            valid_voices = speakers_for_model(sarvam.default_tts_model)
            if sarvam.default_voice.strip().lower() not in valid_voices:
                # Sarvam's bulbul:v2 and bulbul:v3/v3-beta have disjoint speaker sets; a
                # voice saved for one model 400s outright against the other. Fall back to
                # the add-on default if it fits this model, else any valid speaker.
                sarvam.default_voice = (
                    DEFAULT_SARVAM_TTS_VOICE
                    if DEFAULT_SARVAM_TTS_VOICE in valid_voices
                    else next(iter(sorted(valid_voices)), "")
                )
                changed = True

    local = config.integration("local")
    if local:
        if local.name != "Local (OpenAI-compatible)":
            local.name = "Local (OpenAI-compatible)"
            changed = True
        if not local.base_url:
            local.base_url = os.getenv("LOCAL_LLM_BASE_URL", DEFAULT_LOCAL_LLM_BASE_URL)
            changed = True
        if not local.default_model:
            local.default_model = os.getenv("LOCAL_LLM_MODEL", DEFAULT_LOCAL_LLM_MODEL)
            changed = True

    return changed


def _ensure_composed_vad_step(flow: FlowConfig) -> bool:
    """Add local turn detection to flows created before a VAD step existed."""

    if any(step.kind == "vad" for step in flow.steps):
        return False

    existing_ids = {step.id for step in flow.steps}
    step_id = "vad"
    suffix = 2
    while step_id in existing_ids:
        step_id = f"vad-{suffix}"
        suffix += 1

    insert_at = next(
        (index + 1 for index, step in enumerate(flow.steps) if step.kind == "transport"),
        1,
    )
    flow.steps.insert(
        min(insert_at, len(flow.steps)),
        PipelineStepConfig(
            id=step_id,
            kind="vad",
            label="Turn detection",
            settings={"eagerness": "medium"},
        ),
    )
    return True


def _ensure_control_steps(flow: FlowConfig) -> bool:
    """Add non-audio pipeline control steps introduced after early configs."""

    changed = False
    existing = {step.kind for step in flow.steps}

    def insert_after(after_kind: str, step: PipelineStepConfig) -> None:
        nonlocal changed
        if step.kind in existing:
            return
        insert_at = next(
            (index + 1 for index, item in enumerate(flow.steps) if item.kind == after_kind),
            len(flow.steps),
        )
        flow.steps.insert(min(insert_at, len(flow.steps)), step)
        existing.add(step.kind)
        changed = True

    insert_after(
        "transport",
        PipelineStepConfig(
            id="memory",
            kind="memory",
            label="Session memory",
            enabled=flow.memory_enabled,
        ),
    )
    insert_after(
        "llm",
        PipelineStepConfig(
            id="web-search",
            kind="web_search",
            label="Web Search",
            enabled=flow.web_search_enabled,
            integration_id="web-search",
            settings={"announce": True},
        ),
    )
    insert_after(
        "web_search",
        PipelineStepConfig(
            id="tools",
            kind="tools",
            label="HA MCP tools",
            integration_id="ha-mcp",
            settings={"include_device_list": True},
        ),
    )

    has_memory = any(step.kind == "memory" and step.enabled for step in flow.steps)
    has_web_search = any(step.kind == "web_search" and step.enabled for step in flow.steps)
    if flow.memory_enabled != has_memory:
        flow.memory_enabled = has_memory
        changed = True
    if flow.web_search_enabled != has_web_search:
        flow.web_search_enabled = has_web_search
        changed = True

    return changed


class ConfigStore:
    """Read and write runtime configuration."""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path

    def load(self) -> RuntimeConfig:
        """Load persisted config, creating it when absent."""

        default = default_config_from_environment()
        if not self.path.exists():
            if not default.satellite_shared_secret:
                default.satellite_shared_secret = secrets.token_urlsafe(24)
            self.save(default)
            return default

        with self.path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
        raw = _sanitize_legacy_payload(raw)
        data = default.model_dump()
        data.update(raw)
        config = RuntimeConfig.model_validate(data)

        changed = False
        integration_ids = {item.id for item in config.integrations}
        for integration in default.integrations:
            if integration.id not in integration_ids:
                config.integrations.append(integration)
                integration_ids.add(integration.id)
                changed = True

        for key in ("runner_port", "esp32_mode", "log_level"):
            default_value = getattr(default, key)
            if getattr(config, key) != default_value:
                setattr(config, key, default_value)
                changed = True

        changed = _repair_provider_defaults(config) or changed

        mcp = config.mcp_integration
        if config.ha_mcp_url and mcp and not mcp.base_url:
            mcp.base_url = config.ha_mcp_url
            changed = True
        if config.longlived_token and mcp and not mcp.token:
            mcp.token = config.longlived_token
            changed = True

        if not config.satellite_shared_secret:
            config.satellite_shared_secret = (
                default.satellite_shared_secret or secrets.token_urlsafe(24)
            )
            changed = True

        if config.version < 22:
            # Collapsed from the old multi-provider migration ladder: _sanitize_legacy_payload
            # already dropped removed providers/steps above; this just ensures every flow has
            # the fixed pipeline's control steps (VAD/memory/web-search/tools) present.
            config.version = 22
            for flow in config.flows:
                changed = _ensure_composed_vad_step(flow) or changed
                changed = _ensure_control_steps(flow) or changed
            changed = True

        for flow in config.flows:
            if not flow.language:
                flow.language = "en-IN"
                changed = True
        changed = _repair_mcp_url_overrides(config) or changed

        if changed:
            self.save(config)
        return config

    def save(self, config: RuntimeConfig) -> None:
        """Persist config atomically enough for a single add-on process."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(config.model_dump(), file, indent=2, sort_keys=True)
            file.write("\n")
        tmp_path.replace(self.path)

    def reset_mcp_defaults(self) -> RuntimeConfig:
        """Reset Home Assistant MCP settings to the Supervisor-backed defaults."""

        config = self.load()
        config.ha_mcp_url = ""
        config.longlived_token = ""

        integration = config.mcp_integration
        if not integration:
            integration = IntegrationConfig(
                id="ha-mcp",
                name="Home Assistant MCP",
                kind="home_assistant_mcp",
                enabled=True,
            )
            config.integrations.append(integration)

        integration.enabled = True
        integration.base_url = ""
        integration.token = ""

        self.save(config)
        return config

    def reset_integration_defaults(self, integration_id: str) -> RuntimeConfig:
        """Reset one integration to the add-on defaults."""

        config = self.load()
        current = config.integration(integration_id)
        if not current:
            raise KeyError(integration_id)

        defaults = default_config_from_environment().integrations
        replacement = next(
            (item for item in defaults if item.id == current.id or item.kind == current.kind),
            None,
        )
        if replacement:
            next_item = replacement.model_copy(deep=True)
            next_item.id = current.id
            next_item.name = current.name
        else:
            next_item = IntegrationConfig(id=current.id, name=current.name, kind=current.kind)

        config.integrations = [
            next_item if item.id == integration_id else item for item in config.integrations
        ]
        self.save(config)
        return config

    def update_from_public(self, payload: dict[str, Any]) -> RuntimeConfig:
        """Apply a UI update while preserving redacted secrets."""

        current = self.load()
        data = current.model_dump()
        data.update(payload)
        for key in ("longlived_token", "satellite_shared_secret"):
            incoming = payload.get(key)
            if incoming in (None, "", REDACTED):
                data[key] = getattr(current, key)

        current_integrations = {item.id: item for item in current.integrations}
        for item in data.get("integrations", []):
            current_item = current_integrations.get(item.get("id"))
            if not current_item:
                continue
            for key in SECRET_FIELDS:
                if item.get(key) in (None, "", REDACTED):
                    item[key] = getattr(current_item, key)

        config = RuntimeConfig.model_validate(data)
        _repair_provider_defaults(config)
        _repair_mcp_url_overrides(config)
        self.save(config)
        return config
