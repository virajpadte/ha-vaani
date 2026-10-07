import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Copy,
  Download,
  Moon,
  Radio,
  RefreshCw,
  RotateCcw,
  Save,
  Settings,
  Sun,
  Trash2,
} from "lucide-react";
import "./styles.css";

const UI_TRANSLATIONS = {
  pl: {
    "Loading": "Ładowanie",
    "Interface did not load": "Interfejs się nie załadował",
    "Retry": "Ponów",
    "Save": "Zapisz",
    "Light mode": "Tryb jasny",
    "Dark mode": "Tryb ciemny",
    "ready": "gotowy",
    "setup needed": "wymagana konfiguracja",
    "Ready": "Gotowy",
    "Refresh": "Odśwież",
    "Clear": "Wyczyść",
    "Record audio in/out": "Nagrywaj audio wej./wyj.",
    "Session memory": "Pamięć sesji",
    "Memory reuse": "Ponowne użycie pamięci",
    "Memory messages": "Wiadomości pamięci",
    "MCP tools cache": "Cache narzędzi MCP",
    "MCP cache TTL": "TTL cache MCP",
    "Home Assistant actions": "Akcje Home Assistant",
    "Enabled": "Włączone",
    "Test MCP": "Test MCP",
  },
};

function detectLocale() {
  const candidates = [
    document.documentElement.lang,
    window.localStorage.getItem("selectedLanguage"),
    window.localStorage.getItem("language"),
    navigator.language,
    ...(navigator.languages || []),
  ].filter(Boolean);
  return candidates.some((value) => String(value).toLowerCase().startsWith("pl")) ? "pl" : "en";
}

const UI_LOCALE = detectLocale();

function t(value) {
  return UI_TRANSLATIONS[UI_LOCALE]?.[value] || value;
}

function documentBaseUrl() {
  const script = [...document.scripts].find((item) => {
    if (!item.src) return false;
    try {
      return new URL(item.src).pathname.endsWith("/index.js");
    } catch {
      return false;
    }
  });
  return script ? new URL("./", script.src).href : new URL("./", window.location.href).href;
}

function appUrl(path) {
  return new URL(path, documentBaseUrl()).href;
}

const OPUS_AUDIO_QUALITY_PARAMS = {
  minptime: "20",
  useinbandfec: "1",
  maxplaybackrate: "48000",
  maxaveragebitrate: "96000",
  usedtx: "0",
};
const OPUS_AUDIO_REMOVE_PARAMS = new Set(["stereo", "sprop-stereo"]);
const ASSISTANT_CARD_VERSION = "0.1.90";
const ASSISTANT_CARD_ACCENT_HEX = "#206cff";
const ASSISTANT_CARD_AUDIO_BUFFER_MS = 120;
const STREAM_FADE_GROUPS = 4;
const STREAM_CHARS_PER_GROUP = 2;
const STREAM_FADE_LEN = STREAM_FADE_GROUPS * STREAM_CHARS_PER_GROUP;
const END_CONVERSATION_PATTERNS = [
  /\b(to wszystko|wystarczy|dziekuje to wszystko|dzieki to wszystko)\b/,
  /\b(dziekuje koniec|dzieki koniec|ok koniec|okej koniec|dobra koniec)\b/,
  /\b(koniec rozmowy|konczymy rozmowe|zakoncz rozmowe|zakonczmy rozmowe)\b/,
  /\b(przestan sluchac|nie sluchaj|nie nasluchuj)\b/,
  /\b(that is all|that's all|thanks that's all|thank you that's all)\b/,
  /\b(end conversation|stop listening|we are done|goodbye|bye for now)\b/,
  /\b(milego dnia|do uslyszenia|do zobaczenia|na razie)\b/,
  /\b(have a nice day|talk to you later|see you later)\b/,
];
const SHORT_END_CONVERSATION_PATTERN =
  /^(?:ok|okej|dobra|no|dziekuje|dzieki|thanks|thank you)?\s*(?:koniec|wystarczy|goodbye|bye)\s*$/;

const ASSISTANT_CARD_TRANSLATIONS = {
  en: {
    ready: "Ready",
    connecting: "Connecting",
    connected: "Connected",
    error: "Error",
    greeting: "What would you like to do today?",
    talk: "Talk",
    stop: "Stop",
    enableAudio: "Enable audio",
    audioBlocked: "Audio is connected, but the browser blocked playback.",
    waitingForMicrophone: "Waiting for microphone permission",
    microphoneUnavailable: "Microphone access is not available from this browser context.",
    microphoneBlocked: "Microphone access is blocked. Allow microphone access and retry.",
    connectedDetail: "Connected. Speak to Sarvam Assist.",
    connectingAudio: "Connecting audio",
    setupNeeded: "Setup needed",
  },
  pl: {
    ready: "Gotowy",
    connecting: "Łączenie",
    connected: "Połączono",
    error: "Błąd",
    greeting: "Co chciałbyś dzisiaj zrobić?",
    talk: "Mów",
    stop: "Zatrzymaj",
    enableAudio: "Włącz dźwięk",
    audioBlocked: "Dźwięk jest połączony, ale przeglądarka zablokowała odtwarzanie.",
    waitingForMicrophone: "Oczekiwanie na zgodę użycia mikrofonu",
    microphoneUnavailable: "Dostęp do mikrofonu nie jest dostępny w tej przeglądarce.",
    microphoneBlocked: "Dostęp do mikrofonu jest zablokowany. Zezwól na mikrofon i spróbuj ponownie.",
    connectedDetail: "Połączono. Powiedz coś do Sarvam Assist.",
    connectingAudio: "Łączenie audio",
    setupNeeded: "Wymagana konfiguracja",
  },
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function hexToRgb(value) {
  const fallback = ASSISTANT_CARD_ACCENT_HEX;
  const raw = String(value || "").trim();
  const short = /^#?([0-9a-f]{3})$/i.exec(raw);
  const full = /^#?([0-9a-f]{6})$/i.exec(raw);
  const hex = short
    ? short[1].split("").map((part) => `${part}${part}`).join("")
    : full
      ? full[1]
      : fallback.slice(1);
  return {
    r: Number.parseInt(hex.slice(0, 2), 16),
    g: Number.parseInt(hex.slice(2, 4), 16),
    b: Number.parseInt(hex.slice(4, 6), 16),
  };
}

function normalizeTranscriptText(value) {
  return String(value || "")
    .replace(/ /g, " ")
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?%…)\]}])/g, "$1")
    .replace(/([,.;:!?])(?=\p{L}|\p{N})/gu, "$1 ")
    .replace(/([([{])\s+/g, "$1")
    .trim();
}

function compactTranscript(value) {
  return normalizeTranscriptText(value)
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "");
}

function transcriptOverlapSize(existing, incoming) {
  const max = Math.min(existing.length, incoming.length, 160);
  const existingLower = existing.toLocaleLowerCase();
  const incomingLower = incoming.toLocaleLowerCase();
  for (let length = max; length > 0; length -= 1) {
    if (existingLower.slice(-length) === incomingLower.slice(0, length)) return length;
  }
  return 0;
}

function transcriptJoiner(existing, incoming, rawIncoming) {
  if (!existing || !incoming) return "";
  if (/^\s/.test(String(rawIncoming || ""))) return " ";
  if (/^[,.;:!?%…)\]}]/.test(incoming)) return "";
  if (/[(\[{]$/.test(existing)) return "";
  if (/[-/–—]$/.test(existing) || /^[-/–—]/.test(incoming)) return "";
  return " ";
}

function mergeTranscript(existing, chunk) {
  const current = normalizeTranscriptText(existing);
  const rawText = String(chunk || "");
  const text = normalizeTranscriptText(rawText);
  if (!text) return current;
  if (!current) return text;

  const currentCompact = compactTranscript(current);
  const textCompact = compactTranscript(text);
  if (!textCompact) return current;
  if (textCompact === currentCompact) return current;
  if (textCompact.startsWith(currentCompact) && text.length >= current.length) return text;

  const currentTail = compactTranscript(current.slice(-320));
  if (textCompact.length > 3 && currentTail.includes(textCompact)) return current;

  const overlap = transcriptOverlapSize(current, text);
  if (overlap > 0) {
    return normalizeTranscriptText(`${current}${text.slice(overlap)}`);
  }

  return normalizeTranscriptText(`${current}${transcriptJoiner(current, text, rawText)}${text}`);
}

function transcriptWords(value) {
  return normalizeTranscriptText(value)
    .toLocaleLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((word) => word.length > 2);
}

function transcriptTokenParts(value) {
  const text = normalizeTranscriptText(value);
  return [...text.matchAll(/\p{L}[\p{L}\p{N}]*/gu)]
    .map((match) => ({
      text: match[0],
      compact: compactTranscript(match[0]),
      start: match.index,
      end: match.index + match[0].length,
    }))
    .filter((token) => token.compact);
}

function transcriptWordSimilarity(left, right) {
  const leftWords = new Set(transcriptWords(left));
  const rightWords = new Set(transcriptWords(right));
  if (!leftWords.size || !rightWords.size) return 0;
  let matched = 0;
  for (const word of leftWords) {
    if (rightWords.has(word)) matched += 1;
  }
  return matched / Math.min(leftWords.size, rightWords.size);
}

function fragmentedTranscriptScore(value) {
  return normalizeTranscriptText(value)
    .split(/\s+/)
    .filter((part) => /^\p{L}$/u.test(part))
    .length;
}

function hasTerminalTranscriptPunctuation(text) {
  return /[.!?]\s*$/.test(normalizeTranscriptText(text));
}

function isLikelyTranscriptReplacement(existing, incoming) {
  const current = normalizeTranscriptText(existing);
  const text = normalizeTranscriptText(incoming);
  if (!current || !text) return false;
  const currentCompact = compactTranscript(current);
  const textCompact = compactTranscript(text);
  if (textCompact === currentCompact) return true;
  if (textCompact.startsWith(currentCompact) && text.length >= current.length) return true;
  if (currentCompact.includes(textCompact) && textCompact.length < currentCompact.length * 0.72) return false;

  const similarity = transcriptWordSimilarity(current, text);
  const currentFragmented = fragmentedTranscriptScore(current);
  const incomingFragmented = fragmentedTranscriptScore(text);
  if (hasTerminalTranscriptPunctuation(text) && similarity >= 0.52 && text.length >= current.length * 0.55) return true;
  if (currentFragmented >= incomingFragmented + 2 && similarity >= 0.4) return true;
  return similarity >= 0.72 && text.length >= current.length * 0.75 && incomingFragmented <= currentFragmented;
}

function isTranscriptFragment(text, reference) {
  const incoming = compactTranscript(text);
  const existing = compactTranscript(reference);
  if (!incoming || !existing || incoming.length > existing.length) return false;
  if (existing.includes(incoming)) return true;
  const incomingWords = transcriptWords(text);
  if (incoming.length > 12 || incomingWords.length !== 1) return false;
  return transcriptWords(reference)
    .map((word) => compactTranscript(word))
    .some((word) => word && (word.startsWith(incoming) || incoming.startsWith(word)));
}

function mergeDisplayTurnText(existing, incoming) {
  const current = normalizeTranscriptText(existing);
  const text = normalizeTranscriptText(incoming);
  if (!text) return current;
  if (!current || isLikelyTranscriptReplacement(current, text)) return text;
  if (isTranscriptFragment(text, current)) return current;
  return mergeTranscript(current, text);
}

function removeTranscriptEchoSpan(text, reference) {
  const cleanText = normalizeTranscriptText(text);
  const refTokens = transcriptTokenParts(reference);
  const tokens = transcriptTokenParts(cleanText);
  if (refTokens.length < 2 || tokens.length < 2) return cleanText;

  let best = null;
  for (let start = 0; start < tokens.length; start += 1) {
    let length = 0;
    while (
      start + length < tokens.length
      && length < refTokens.length
      && tokens[start + length].compact === refTokens[length].compact
    ) {
      length += 1;
    }
    const enough = length >= Math.min(3, refTokens.length) || (refTokens.length === 2 && length === 2);
    if (enough && length / refTokens.length >= 0.62 && (!best || length > best.length)) {
      best = { start, length };
    }
  }

  if (!best) return cleanText;
  const first = tokens[best.start];
  const last = tokens[best.start + best.length - 1];
  return normalizeTranscriptText(`${cleanText.slice(0, first.start)} ${cleanText.slice(last.end)}`);
}

function isLikelyTranscriptEcho(text, reference) {
  const incoming = compactTranscript(text);
  const existing = compactTranscript(reference);
  if (incoming.length < 6 || existing.length < 6) return false;
  if (existing.includes(incoming)) return true;

  const incomingWords = transcriptWords(text);
  if (incomingWords.length < 2) return false;
  const existingWords = new Set(transcriptWords(reference));
  const matched = incomingWords.filter((word) => existingWords.has(word)).length;
  return matched >= 2 && matched / incomingWords.length >= 0.75;
}

function mergeAssistantTurnText(existing, incoming, priority, currentPriority) {
  const current = normalizeTranscriptText(existing);
  const text = normalizeTranscriptText(incoming);
  if (!text) return current;
  if (!current) return text;

  if (hasTerminalTranscriptPunctuation(current) && isTranscriptFragment(text, current)) return current;
  if (priority > currentPriority) {
    if (isTranscriptFragment(text, current) && !isLikelyTranscriptReplacement(current, text)) return current;
    return text;
  }
  if (isLikelyTranscriptReplacement(current, text)) return text;
  return mergeTranscript(current, text);
}

function firstString(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

function rtviAssistantTextPriority(type) {
  if (type === "bot-output") return 4;
  if (type === "bot-transcription") return 3;
  if (type === "bot-tts-text") return 2;
  if (type === "bot-llm-text") return 1;
  if (type.startsWith("assistant-")) return 2;
  return 0;
}

function isRtviUserTextType(type) {
  return type === "user-transcription" || type === "user-llm-text" || type.startsWith("user-");
}

function isRtviAssistantTextType(type) {
  return rtviAssistantTextPriority(type) > 0;
}

function shouldEndConversation(text) {
  const clean = String(text || "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9']+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!clean) return false;
  return SHORT_END_CONVERSATION_PATTERN.test(clean)
    || END_CONVERSATION_PATTERNS.some((pattern) => pattern.test(clean));
}

function assistantCardT(key) {
  return ASSISTANT_CARD_TRANSLATIONS[UI_LOCALE]?.[key] || ASSISTANT_CARD_TRANSLATIONS.en[key] || key;
}

function mergeOpusFmtp(existing) {
  const params = new Map();
  for (const part of existing.split(";").map((item) => item.trim()).filter(Boolean)) {
    const [rawKey, ...rest] = part.split("=");
    const key = rawKey.trim().toLowerCase();
    if (!key || OPUS_AUDIO_REMOVE_PARAMS.has(key)) continue;
    params.set(key, rest.length ? rest.join("=").trim() : "");
  }
  for (const [key, value] of Object.entries(OPUS_AUDIO_QUALITY_PARAMS)) params.set(key, value);
  return [...params.entries()].map(([key, value]) => (value ? `${key}=${value}` : key)).join(";");
}

function preferFullbandOpus(sdp) {
  if (!sdp) return sdp;
  const separator = sdp.includes("\r\n") ? "\r\n" : "\n";
  const lines = sdp.split(/\r?\n/);
  const opusPayloads = new Set();
  const fmtpPayloads = new Set();

  for (const line of lines) {
    const rtpmap = /^a=rtpmap:(\d+)\s+opus\/48000(?:\/2)?/i.exec(line);
    if (rtpmap) opusPayloads.add(rtpmap[1]);
    const fmtp = /^a=fmtp:(\d+)\s+/i.exec(line);
    if (fmtp) fmtpPayloads.add(fmtp[1]);
  }

  return lines
    .map((line) => {
      const fmtp = /^a=fmtp:(\d+)\s*(.*)$/i.exec(line);
      if (fmtp && opusPayloads.has(fmtp[1])) {
        return `a=fmtp:${fmtp[1]} ${mergeOpusFmtp(fmtp[2] || "")}`;
      }
      const rtpmap = /^a=rtpmap:(\d+)\s+opus\/48000(?:\/2)?/i.exec(line);
      if (rtpmap && !fmtpPayloads.has(rtpmap[1])) {
        return `${line}${separator}a=fmtp:${rtpmap[1]} ${mergeOpusFmtp("")}`;
      }
      return line;
    })
    .join(separator);
}

const API = {
  config: appUrl("api/assist/config"),
  status: appUrl("api/assist/status"),
  mcp: appUrl("api/assist/mcp/check"),
  mcpHistory: appUrl("api/assist/mcp/history"),
  mcpReset: appUrl("api/assist/mcp/reset"),
  audioDebug: appUrl("api/assist/debug/audio"),
  models: (integrationId, capability = "llm") =>
    appUrl(`api/assist/integrations/${encodeURIComponent(integrationId)}/models?capability=${encodeURIComponent(capability)}`),
  voices: (integrationId) =>
    appUrl(`api/assist/integrations/${encodeURIComponent(integrationId)}/voices`),
  languages: appUrl("api/assist/sarvam/languages"),
};

const REDACTED = "__redacted__";

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

// crypto.randomUUID() only exists in secure contexts (HTTPS, or localhost).
// Home Assistant's ingress is commonly plain http:// on a LAN hostname/IP,
// which browsers do not treat as secure, so that call throws there and
// crypto.getRandomValues() (not secure-context-gated) is used instead.
function randomId(length = 8) {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID().replace(/-/g, "").slice(0, length);
    } catch {
      // fall through to getRandomValues/Math.random below
    }
  }
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = new Uint8Array(Math.ceil(length / 2));
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"))
      .join("")
      .slice(0, length);
  }
  return Math.random().toString(16).slice(2).padEnd(length, "0").slice(0, length);
}

function secretValue(value) {
  return value === REDACTED ? "" : value || "";
}

function secretStatus(item, key) {
  if (!item) return "missing";
  if (item[`${key}_configured`] || item[key] === REDACTED) return "configured";
  return secretValue(item[key]) ? "pending" : "missing";
}

function secretPlaceholder(item, key, fallback = "") {
  return secretStatus(item, key) === "configured" ? "configured" : fallback;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTimestamp(value) {
  if (!value) return "running";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}

function formatDuration(ms) {
  const value = Number(ms || 0);
  if (!value) return "";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function ensureShape(config) {
  const shaped = clone(config);
  // Sarvam (STT/TTS, and optionally LLM) and the Supervisor-automatic Home
  // Assistant MCP integration are always part of this fixed pipeline - there
  // is no UI toggle for either, so force them on here rather than leaving
  // whatever the backend's first-run default happened to be.
  shaped.integrations = (shaped.integrations || []).map((item) =>
    item.id === "sarvam" || item.kind === "home_assistant_mcp" ? { ...item, enabled: true } : item,
  );
  shaped.flows = shaped.flows?.length ? shaped.flows : [];
  shaped.selected_flow_id ||= shaped.flows[0]?.id || "";
  return shaped;
}

function syncFlow(flow) {
  const steps = (flow.steps || []).map((step) => {
    if (step.kind === "memory") return { ...step, enabled: Boolean(flow.memory_enabled) };
    if (step.kind === "web_search") return { ...step, enabled: Boolean(flow.web_search_enabled) };
    return step;
  });
  return {
    ...flow,
    steps,
    max_output_tokens: flow.max_output_tokens ? Number(flow.max_output_tokens) : null,
    mcp_tool_allowlist: Array.isArray(flow.mcp_tool_allowlist)
      ? flow.mcp_tool_allowlist
      : String(flow.mcp_tool_allowlist || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
  };
}

function mcpMode(config, status) {
  const mcp = config.integrations.find((item) => item.kind === "home_assistant_mcp");
  const source = status?.mcp_token_source || config.mcp_token_source || "";
  const manual = Boolean(mcp?.base_url || mcp?.token_configured || mcp?.token === REDACTED || config.longlived_token_configured);
  if (manual) return { label: "Manual", tone: "manual" };
  if (source === "supervisor") return { label: "Automatic", tone: "ok" };
  return { label: "Error", tone: "error" };
}

function flowModelIntegration(config, flow) {
  const modelStep = flow.steps?.find((step) => step.kind === "llm" && step.enabled);
  const integrationId = modelStep?.integration_id || "sarvam";
  return config.integrations.find((integration) => integration.id === integrationId) || null;
}

function voiceReadiness(config, flow) {
  const integration = flowModelIntegration(config, flow);
  if (!integration) {
    return { ok: false, detail: "No model integration is configured." };
  }
  if (!integration.enabled) {
    return { ok: false, detail: `${integration.name} is disabled.` };
  }

  const keyStatus = integration.kind === "sarvam" ? secretStatus(integration, "api_key") : "configured";
  if (keyStatus === "missing") {
    return {
      ok: false,
      detail: `${integration.name} API key is missing. Add it in Settings, save, then retry.`,
    };
  }
  if (keyStatus === "pending") {
    return {
      ok: false,
      detail: `Save configuration before starting the voice test; the add-on cannot use the new ${integration.name} key yet.`,
    };
  }
  if (integration.kind === "local" && !integration.base_url) {
    return { ok: false, detail: "Local model base URL is missing." };
  }

  const sarvam = config.integrations.find((item) => item.id === "sarvam");
  if (!sarvam?.enabled || secretStatus(sarvam, "api_key") === "missing") {
    return { ok: false, detail: "Sarvam API key is missing (needed for speech-to-text and text-to-speech)." };
  }

  const mcp = config.integrations.find((item) => item.kind === "home_assistant_mcp");
  if (flow.mcp_enabled && config.mcp_token_source === "supervisor" && secretStatus(mcp, "token") === "missing") {
    return { ok: true, detail: "Ready. MCP will use the Home Assistant Supervisor token." };
  }
  if (flow.mcp_enabled && secretStatus(mcp, "token") === "missing" && !config.longlived_token_configured) {
    return { ok: true, detail: "Ready. Home Assistant MCP token is missing, so device tools may be unavailable." };
  }

  return { ok: true, detail: `Ready for ${flow.name}.` };
}

function hasReadyAssistantSetup(config) {
  return (config.flows || []).some((candidate) => voiceReadiness(config, candidate).ok);
}

async function offerErrorMessage(response) {
  const body = await response.text();
  let detail = body;
  try {
    const parsed = JSON.parse(body);
    detail = parsed.detail || parsed.error || body;
  } catch {
    detail = body;
  }

  if (response.status === 401) {
    return "SmallWebRTC offer token was rejected. Reload the panel and retry after saving configuration.";
  }
  return detail || `SmallWebRTC offer failed with HTTP ${response.status}.`;
}

function friendlyWebRtcError(err) {
  const message = err?.message || String(err);
  if (err?.name === "NotAllowedError" || err?.name === "PermissionDeniedError") {
    return "Microphone access is blocked. Allow microphone access in the browser and start the voice test again.";
  }
  if (err?.name === "NotFoundError") {
    return "No microphone was found for this browser session.";
  }
  if (message === "Failed to fetch") {
    return "Could not reach the SmallWebRTC offer endpoint. Check that the add-on is running in Home Assistant Ingress.";
  }
  return message;
}

function mcpStatusLabel(config, status) {
  const source = status?.mcp_token_source || config.mcp_token_source || "";
  if (source === "integration" || source === "long-lived") return "token ready";
  if (source === "supervisor") return "supervisor token";
  return "token pending";
}

function Button({ children, icon: Icon, variant = "primary", title, ...props }) {
  return (
    <button className={`button ${variant}`} title={title} {...props}>
      {Icon && <Icon size={16} strokeWidth={2} />}
      {children && <span>{children}</span>}
    </button>
  );
}

function Field({ label, children, wide = false }) {
  return (
    <label className={wide ? "field wide" : "field"}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function Toggle({ checked, onChange, label }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={Boolean(checked)} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

function App() {
  const [config, setConfig] = useState(null);
  const [status, setStatus] = useState(null);
  const [audioDebug, setAudioDebug] = useState({ recordings: [] });
  const [mcpHistory, setMcpHistory] = useState({ calls: [] });
  const [tab, setTab] = useState("assistant");
  const [modelOptions, setModelOptions] = useState({});
  const [voiceOptions, setVoiceOptions] = useState({});
  const [languageOptions, setLanguageOptions] = useState([]);
  const [mcpResult, setMcpResult] = useState(null);
  const [message, setMessage] = useState({ text: "", tone: "" });
  const [fatalError, setFatalError] = useState("");
  const [saving, setSaving] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem("pipecat-assist-theme") || "dark");

  useEffect(() => {
    load().catch((err) => setFatalError(String(err)));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("pipecat-assist-theme", theme);
  }, [theme]);

  const flow = useMemo(() => (config ? config.flows[0] : null), [config]);

  async function load() {
    setFatalError("");
    const [configResponse, statusResponse, audioResponse, mcpHistoryResponse] = await Promise.all([
      fetch(API.config),
      fetch(API.status),
      fetch(API.audioDebug).catch(() => null),
      fetch(API.mcpHistory).catch(() => null),
    ]);
    if (!configResponse.ok) {
      throw new Error(`Config API failed: ${configResponse.status}`);
    }
    if (!statusResponse.ok) {
      throw new Error(`Status API failed: ${statusResponse.status}`);
    }
    const nextConfig = ensureShape(await configResponse.json());
    setConfig(nextConfig);
    setStatus(await statusResponse.json());
    if (audioResponse?.ok) {
      setAudioDebug(await audioResponse.json());
    }
    if (mcpHistoryResponse?.ok) {
      setMcpHistory(await mcpHistoryResponse.json());
    }
  }

  async function refreshStatus() {
    const response = await fetch(API.status);
    if (response.ok) {
      setStatus(await response.json());
    }
  }

  async function refreshAudioDebug() {
    const response = await fetch(API.audioDebug);
    if (response.ok) {
      setAudioDebug(await response.json());
    }
  }

  async function refreshMcpHistory() {
    const response = await fetch(API.mcpHistory);
    if (response.ok) {
      setMcpHistory(await response.json());
    }
  }

  async function clearMcpHistory() {
    const response = await fetch(API.mcpHistory, { method: "DELETE" });
    if (response.ok) {
      setMcpHistory(await response.json());
      setMessage({ text: "MCP history cleared", tone: "ok" });
    }
  }

  function updateConfig(updater) {
    setConfig((current) => ensureShape(updater(clone(current))));
  }

  function updateFlow(updater) {
    updateConfig((draft) => {
      draft.flows = draft.flows.map((item, index) => (index === 0 ? syncFlow(updater(clone(item))) : item));
      return draft;
    });
  }

  function updateStepByKind(kind, updater) {
    updateFlow((item) => {
      item.steps = item.steps.map((step) => (step.kind === kind ? updater(clone(step)) : step));
      return item;
    });
  }

  function updateIntegration(integrationId, updater) {
    updateConfig((draft) => {
      draft.integrations = draft.integrations.map((item) =>
        item.id === integrationId ? updater(clone(item)) : item,
      );
      return draft;
    });
  }

  async function loadModelOptions(integrationId, capability = "llm") {
    const key = `${integrationId}:${capability}`;
    if (modelOptions[key]) return;
    const response = await fetch(API.models(integrationId, capability));
    if (!response.ok) return;
    const result = await response.json();
    setModelOptions((current) => ({ ...current, [key]: result.models || [] }));
  }

  async function loadVoiceOptions(integrationId) {
    if (voiceOptions[integrationId]) return;
    const response = await fetch(API.voices(integrationId));
    if (!response.ok) return;
    const result = await response.json();
    setVoiceOptions((current) => ({ ...current, [integrationId]: result.voices || [] }));
  }

  async function loadLanguageOptions() {
    if (languageOptions.length) return;
    const response = await fetch(API.languages);
    if (!response.ok) return;
    const result = await response.json();
    setLanguageOptions(result.languages || []);
  }

  async function persistConfig(payload, successText = "Saved") {
    setSaving(true);
    setMessage({ text: "Saving", tone: "" });
    const normalized = {
      ...payload,
      flows: payload.flows.map((item) => syncFlow(item)),
    };
    const response = await fetch(API.config, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(normalized),
    });
    setSaving(false);
    if (!response.ok) {
      setMessage({ text: await response.text(), tone: "error" });
      return null;
    }
    const nextConfig = ensureShape(await response.json());
    setConfig(nextConfig);
    await refreshStatus();
    setMessage({ text: successText, tone: "ok" });
    return nextConfig;
  }

  async function save() {
    await persistConfig(config);
  }

  async function checkMcp() {
    setMessage({ text: "Checking MCP", tone: "" });
    const response = await fetch(API.mcp, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ flow_id: flow.id, refresh: true }),
    });
    const result = await response.json();
    setMcpResult(result);
    setMessage(
      result.ok
        ? { text: `MCP connected: ${result.tool_count} tools`, tone: "ok" }
        : { text: result.error || "MCP check failed", tone: "error" },
    );
    await refreshMcpHistory();
  }

  async function resetMcpDefaults() {
    setMessage({ text: "Resetting MCP", tone: "" });
    const response = await fetch(API.mcpReset, { method: "POST" });
    if (!response.ok) {
      setMessage({ text: await response.text(), tone: "error" });
      return;
    }
    setConfig(ensureShape(await response.json()));
    setMcpResult(null);
    await refreshStatus();
    setMessage({ text: "MCP reset to Supervisor defaults", tone: "ok" });
  }

  async function clearAudioDebug() {
    setMessage({ text: "Clearing audio captures", tone: "" });
    const response = await fetch(API.audioDebug, { method: "DELETE" });
    if (!response.ok) {
      setMessage({ text: await response.text(), tone: "error" });
      return;
    }
    setAudioDebug(await response.json());
    setMessage({ text: "Audio captures cleared", tone: "ok" });
  }

  async function copyEspHomeUrl() {
    await navigator.clipboard.writeText(config.esphome_ws_url || "");
    setMessage({ text: "ESPHome endpoint copied", tone: "ok" });
  }

  if (!config || !flow) {
    return (
      <main className="loading">
        <img src="assets/logo.svg" alt="" />
        {fatalError ? (
          <>
            <strong>{t("Interface did not load")}</strong>
            <span>{fatalError}</span>
            <Button icon={RefreshCw} variant="secondary" onClick={() => load().catch((err) => setFatalError(String(err)))}>
              {t("Retry")}
            </Button>
          </>
        ) : (
          <span>{t("Loading")}</span>
        )}
      </main>
    );
  }

  const readiness = voiceReadiness(config, flow);

  return (
    <div className="app-shell">
      <aside className="nav">
        <div className="brand">
          <img src="assets/logo.svg" alt="" />
          <div>
            <h1>Sarvam Assist</h1>
            <span className={readiness.ok ? "state ok" : "state error"}>
              {readiness.ok ? t("ready") : t("setup needed")}
            </span>
          </div>
        </div>

        <nav className="tabs" aria-label="Sarvam Assist">
          {[
            ["assistant", "Assistant", Bot],
            ["settings", "Settings", Settings],
          ].map(([id, label, Icon]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
              <Icon size={17} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h2>{tab === "assistant" ? "Assistant" : "Settings"}</h2>
            <span>{readiness.detail}</span>
          </div>
          <div className="actions">
            <button
              className="theme-toggle icon-only"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              title={theme === "dark" ? t("Light mode") : t("Dark mode")}
              aria-label={theme === "dark" ? t("Light mode") : t("Dark mode")}
            >
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </header>

        {tab === "assistant" && <AssistantView config={config} flow={flow} status={status} />}

        {tab === "settings" && (
          <SettingsView
            config={config}
            flow={flow}
            status={status}
            mcpResult={mcpResult}
            modelOptions={modelOptions}
            loadModelOptions={loadModelOptions}
            voiceOptions={voiceOptions}
            loadVoiceOptions={loadVoiceOptions}
            languageOptions={languageOptions}
            loadLanguageOptions={loadLanguageOptions}
            updateConfig={updateConfig}
            updateFlow={updateFlow}
            updateStepByKind={updateStepByKind}
            updateIntegration={updateIntegration}
            checkMcp={checkMcp}
            resetMcpDefaults={resetMcpDefaults}
            save={save}
            saving={saving}
            audioDebug={audioDebug}
            refreshAudioDebug={refreshAudioDebug}
            clearAudioDebug={clearAudioDebug}
            mcpHistory={mcpHistory}
            refreshMcpHistory={refreshMcpHistory}
            clearMcpHistory={clearMcpHistory}
            copyEspHomeUrl={copyEspHomeUrl}
          />
        )}

        <div className={message.tone ? `message ${message.tone}` : "message"} role="status">
          {message.tone === "ok" && <CheckCircle2 size={16} />}
          {message.tone === "error" && <AlertCircle size={16} />}
          <span>{message.text}</span>
        </div>
      </main>
    </div>
  );
}

function AssistantView({ config, flow, status }) {
  const readiness = voiceReadiness(config, flow);
  const showSetupHint = !hasReadyAssistantSetup(config);
  return (
    <div className="assistant-grid">
      <section className="assistant-hero blue">
        <div className="assistant-badge">
          <Bot size={34} />
        </div>
        <div className="assistant-title">
          <span>Sarvam Assist</span>
          <h3>{flow.name}</h3>
          <strong>{readiness.ok ? t("Ready") : readiness.detail}</strong>
        </div>
        {showSetupHint && (
          <div className="setup-callout">
            <AlertCircle size={20} />
            <div>
              <strong>Add your Sarvam API key to get started.</strong>
              <span>
                Get a key from{" "}
                <a href="https://dashboard.sarvam.ai" target="_blank" rel="noreferrer">
                  the Sarvam AI dashboard
                </a>{" "}
                and paste it into Settings.
              </span>
            </div>
          </div>
        )}
        <VoiceTest config={config} flow={flow} status={status} />
      </section>
    </div>
  );
}

function SettingsSection({ title, status, children }) {
  return (
    <div className="settings-section">
      {(title || status) && (
        <div className="section-title">
          {title && <strong>{title}</strong>}
          {status && <span>{status}</span>}
        </div>
      )}
      <div className="form-grid">{children}</div>
    </div>
  );
}

function TextSetting({ integration, field, label, updateIntegration, wide = false }) {
  return (
    <Field label={label} wide={wide}>
      <input
        autoComplete="off"
        value={integration?.[field] || ""}
        onChange={(event) =>
          updateIntegration(integration.id, (item) => ({ ...item, [field]: event.target.value }))
        }
      />
    </Field>
  );
}

function ModelSetting({
  integration,
  field,
  label,
  updateIntegration,
  modelOptions,
  loadModelOptions,
  capability = "llm",
  wide = false,
}) {
  const key = `${integration.id}:${capability}`;
  const options = modelOptions?.[key] || [];
  const listId = `models-${integration.id}-${field}-${capability}`;
  return (
    <Field label={label} wide={wide}>
      <input
        autoComplete="off"
        list={listId}
        value={integration?.[field] || ""}
        onFocus={() => loadModelOptions?.(integration.id, capability)}
        onChange={(event) =>
          updateIntegration(integration.id, (item) => ({ ...item, [field]: event.target.value }))
        }
      />
      <datalist id={listId}>
        {options.map((model) => (
          <option key={model.id} value={model.id}>
            {model.label}
          </option>
        ))}
      </datalist>
    </Field>
  );
}

function SecretSetting({ integration, field, label, updateIntegration, wide = false }) {
  const [editing, setEditing] = useState(secretStatus(integration, field) !== "configured");
  const configured = secretStatus(integration, field) === "configured";

  useEffect(() => {
    setEditing(secretStatus(integration, field) !== "configured");
  }, [integration.id, field, integration[`${field}_configured`]]);

  if (configured && !editing) {
    return (
      <Field label={label} wide={wide}>
        <div className="locked-secret">
          <input value="configured" readOnly />
          <Button icon={RotateCcw} variant="secondary" onClick={() => setEditing(true)}>
            Replace
          </Button>
        </div>
      </Field>
    );
  }

  return (
    <Field label={label} wide={wide}>
      <input
        type="password"
        autoComplete="new-password"
        value={secretValue(integration[field])}
        placeholder={secretPlaceholder(integration, field)}
        onChange={(event) => updateIntegration(integration.id, (item) => ({ ...item, [field]: event.target.value }))}
      />
    </Field>
  );
}

function LanguageSetting({ sarvamIntegration, languageOptions, loadLanguageOptions, updateIntegration }) {
  const value = sarvamIntegration?.language || "en-IN";
  const known = languageOptions.some((language) => language.code === value);

  return (
    <Field label="Language">
      <select
        value={value}
        onFocus={() => loadLanguageOptions()}
        onChange={(event) =>
          updateIntegration("sarvam", (item) => ({ ...item, language: event.target.value }))
        }
      >
        {!known && <option value={value}>{value}</option>}
        {languageOptions.map((language) => (
          <option key={language.code} value={language.code}>
            {language.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

function VoiceSetting({ ttsStep, sarvamIntegration, voiceOptions, loadVoiceOptions, updateStepByKind }) {
  const options = voiceOptions?.sarvam || [];
  const female = options.filter((voice) => voice.gender === "female");
  const male = options.filter((voice) => voice.gender === "male");
  const value = ttsStep?.voice || sarvamIntegration?.default_voice || "";

  return (
    <Field label="Voice">
      <select
        value={value}
        onFocus={() => loadVoiceOptions("sarvam")}
        onChange={(event) => updateStepByKind("tts", (step) => ({ ...step, voice: event.target.value }))}
      >
        {!options.length && value && <option value={value}>{value}</option>}
        {female.length > 0 && (
          <optgroup label="Female">
            {female.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.label}
              </option>
            ))}
          </optgroup>
        )}
        {male.length > 0 && (
          <optgroup label="Male">
            {male.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.label}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </Field>
  );
}

function ModelSourceSetting({ flow, integrations, updateFlow, updateIntegration, modelOptions, loadModelOptions }) {
  const llmStep = flow.steps.find((step) => step.kind === "llm");
  const source = llmStep?.integration_id === "local" ? "local" : "sarvam";
  const sarvam = integrations.find((item) => item.id === "sarvam");
  const local = integrations.find((item) => item.id === "local");

  function setSource(nextSource) {
    updateFlow((item) => {
      item.steps = item.steps.map((step) =>
        step.kind === "llm" ? { ...step, integration_id: nextSource } : step,
      );
      return item;
    });
    updateIntegration("local", (item) => ({ ...item, enabled: nextSource === "local" }));
  }

  return (
    <SettingsSection title="Model">
      <Field label="Source">
        <select value={source} onChange={(event) => setSource(event.target.value)}>
          <option value="sarvam">Sarvam Cloud</option>
          <option value="local">Local (OpenAI-compatible)</option>
        </select>
      </Field>
      {source === "sarvam" ? (
        <ModelSetting
          integration={sarvam}
          field="default_model"
          label="LLM model"
          updateIntegration={updateIntegration}
          modelOptions={modelOptions}
          loadModelOptions={loadModelOptions}
          capability="llm"
        />
      ) : (
        <>
          <TextSetting integration={local} field="base_url" label="Base URL" updateIntegration={updateIntegration} wide />
          <TextSetting integration={local} field="default_model" label="Model" updateIntegration={updateIntegration} />
          <SecretSetting integration={local} field="api_key" label="API key (optional)" updateIntegration={updateIntegration} />
          <div className="empty-state wide">
            Point this at Ollama, vLLM, LM Studio, or a self-hosted Sarvam open-weight model's
            OpenAI-compatible endpoint. STT and TTS always use Sarvam Cloud above.
          </div>
        </>
      )}
    </SettingsSection>
  );
}

function SettingsView({
  config,
  flow,
  status,
  mcpResult,
  modelOptions,
  loadModelOptions,
  voiceOptions,
  loadVoiceOptions,
  languageOptions,
  loadLanguageOptions,
  updateConfig,
  updateFlow,
  updateStepByKind,
  updateIntegration,
  checkMcp,
  resetMcpDefaults,
  save,
  saving,
  audioDebug,
  refreshAudioDebug,
  clearAudioDebug,
  mcpHistory,
  refreshMcpHistory,
  clearMcpHistory,
  copyEspHomeUrl,
}) {
  const sarvam = config.integrations.find((item) => item.id === "sarvam");
  const webSearch = config.integrations.find((item) => item.id === "web-search");
  const mcp = config.integrations.find((item) => item.kind === "home_assistant_mcp");
  const ttsStep = flow.steps.find((step) => step.kind === "tts");
  const vadStep = flow.steps.find((step) => step.kind === "vad");
  const mode = mcpMode(config, status);
  const [manualMcpOpen, setManualMcpOpen] = useState(false);

  useEffect(() => {
    setManualMcpOpen(Boolean(mcp?.base_url || mcp?.token_configured || mcp?.token === REDACTED));
  }, [mcp?.id]);

  useEffect(() => {
    loadVoiceOptions("sarvam");
    loadLanguageOptions();
  }, []);

  return (
    <div className="integration-detail">
      <section className="panel inspector settings-editor">
        <SettingsSection title="Sarvam AI" status={secretStatus(sarvam, "api_key")}>
          <SecretSetting integration={sarvam} field="api_key" label="API key" updateIntegration={updateIntegration} wide />
          <LanguageSetting
            sarvamIntegration={sarvam}
            languageOptions={languageOptions}
            loadLanguageOptions={loadLanguageOptions}
            updateIntegration={updateIntegration}
          />
          <VoiceSetting
            ttsStep={ttsStep}
            sarvamIntegration={sarvam}
            voiceOptions={voiceOptions}
            loadVoiceOptions={loadVoiceOptions}
            updateStepByKind={updateStepByKind}
          />
          <div className="empty-state wide">
            This one language covers both speech-to-text and text-to-speech.
          </div>
        </SettingsSection>

        <ModelSourceSetting
          flow={flow}
          integrations={config.integrations}
          updateFlow={updateFlow}
          updateIntegration={updateIntegration}
          modelOptions={modelOptions}
          loadModelOptions={loadModelOptions}
        />

        <SettingsSection title="Instructions">
          <Field label="Instructions" wide>
            <textarea
              rows={4}
              value={flow.instructions}
              onChange={(event) => updateFlow((item) => ({ ...item, instructions: event.target.value }))}
            />
          </Field>
          <Field label="Greeting" wide>
            <textarea
              rows={2}
              value={flow.greeting}
              onChange={(event) => updateFlow((item) => ({ ...item, greeting: event.target.value }))}
            />
          </Field>
        </SettingsSection>

        <SettingsSection title="Web Search" status={webSearch?.enabled ? "enabled" : "disabled"}>
          <Toggle
            checked={Boolean(flow.web_search_enabled)}
            onChange={(value) => {
              updateFlow((item) => ({ ...item, web_search_enabled: value }));
              updateIntegration("web-search", (item) => ({ ...item, enabled: value }));
            }}
            label="Enable web search"
          />
          {flow.web_search_enabled && (
            <SecretSetting
              integration={webSearch}
              field="api_key"
              label="Tavily API key"
              updateIntegration={updateIntegration}
              wide
            />
          )}
        </SettingsSection>

        <SettingsSection title="Session memory">
          <Toggle
            checked={Boolean(flow.memory_enabled)}
            onChange={(value) => updateFlow((item) => ({ ...item, memory_enabled: value }))}
            label={t("Session memory")}
          />
        </SettingsSection>

        <SettingsSection title="Home Assistant MCP" status={mode.label}>
          <div className={`mcp-mode ${mode.tone} wide`}>
            <strong>{mode.label}</strong>
            <span>
              {mode.label === "Automatic"
                ? "Using Home Assistant Supervisor MCP and token."
                : mode.label === "Manual"
                  ? "Manual URL or token override is configured."
                  : "MCP token is not available."}
            </span>
          </div>
          {mcpResult && (
            <div className={mcpResult.ok ? "mcp-result ok wide" : "mcp-result error wide"}>
              <strong>{mcpResult.ok ? `${mcpResult.tool_count} tools available` : "MCP test failed"}</strong>
              <span>{mcpResult.ok ? (mcpResult.tools || []).slice(0, 8).join(", ") : mcpResult.error}</span>
            </div>
          )}
          {manualMcpOpen && (
            <>
              <TextSetting integration={mcp} field="base_url" label="Manual MCP URL" updateIntegration={updateIntegration} wide />
              <SecretSetting integration={mcp} field="token" label="Manual access token" updateIntegration={updateIntegration} wide />
            </>
          )}
          <div className="button-row wide">
            <Button icon={RefreshCw} variant="secondary" onClick={checkMcp}>
              {t("Test MCP")}
            </Button>
            <Button icon={Settings} variant="secondary" onClick={() => setManualMcpOpen((value) => !value)}>
              {manualMcpOpen ? "Hide manual" : "Manual override"}
            </Button>
            <Button icon={RotateCcw} variant="secondary" onClick={resetMcpDefaults}>
              Automatic defaults
            </Button>
          </div>
        </SettingsSection>

        <div className="divider" />
        <EspHomeSatellitePanel config={config} copyEspHomeUrl={copyEspHomeUrl} updateConfig={updateConfig} />

        <div className="divider" />
        <details className="advanced-section">
          <summary>Advanced</summary>
          <div className="form-grid">
            <Field label="Turn detection sensitivity">
              <select
                value={vadStep?.settings?.eagerness || "medium"}
                onChange={(event) =>
                  updateStepByKind("vad", (step) => ({
                    ...step,
                    settings: { ...step.settings, eagerness: event.target.value },
                  }))
                }
              >
                <option value="low">Low (waits longer)</option>
                <option value="medium">Medium</option>
                <option value="high">High (cuts in sooner)</option>
              </select>
            </Field>
            <Field label="Reasoning effort">
              <select
                value={flow.reasoning_effort || ""}
                onChange={(event) =>
                  updateFlow((item) => ({ ...item, reasoning_effort: event.target.value || null }))
                }
              >
                <option value="">Default (low)</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </Field>
            <Field label="Max response tokens">
              <input
                type="number"
                min="1"
                max="4096"
                placeholder="no limit"
                value={flow.max_output_tokens || ""}
                onChange={(event) =>
                  updateFlow((item) => ({
                    ...item,
                    max_output_tokens: event.target.value ? Number(event.target.value) : null,
                  }))
                }
              />
            </Field>
            <Toggle
              checked={config.audio_debug_enabled}
              onChange={(value) => updateConfig((draft) => ({ ...draft, audio_debug_enabled: value }))}
              label={t("Record audio in/out")}
            />
            <Field label="Keep sessions">
              <input
                type="number"
                min="1"
                max="100"
                value={config.audio_debug_keep_sessions || 10}
                onChange={(event) =>
                  updateConfig((draft) => ({
                    ...draft,
                    audio_debug_keep_sessions: Math.min(100, Math.max(1, Number(event.target.value || 1))),
                  }))
                }
              />
            </Field>
            <Field label={t("Memory reuse")}>
              <select
                value={String(config.session_memory_reuse_seconds ?? 300)}
                onChange={(event) =>
                  updateConfig((draft) => ({ ...draft, session_memory_reuse_seconds: Number(event.target.value) }))
                }
              >
                <option value="0">Off</option>
                <option value="120">2 minutes</option>
                <option value="300">5 minutes</option>
                <option value="900">15 minutes</option>
                <option value="3600">1 hour</option>
              </select>
            </Field>
            <Field label={t("Memory messages")}>
              <input
                type="number"
                min="0"
                max="100"
                value={config.session_memory_max_messages ?? 12}
                onChange={(event) =>
                  updateConfig((draft) => ({ ...draft, session_memory_max_messages: Number(event.target.value || 0) }))
                }
              />
            </Field>
            <Toggle
              checked={config.mcp_tools_cache_enabled}
              onChange={(value) => updateConfig((draft) => ({ ...draft, mcp_tools_cache_enabled: value }))}
              label={t("MCP tools cache")}
            />
            <Field label={t("MCP cache TTL")}>
              <select
                value={String(config.mcp_tools_cache_ttl_seconds ?? 300)}
                onChange={(event) =>
                  updateConfig((draft) => ({ ...draft, mcp_tools_cache_ttl_seconds: Number(event.target.value) }))
                }
              >
                <option value="0">No cache</option>
                <option value="60">1 minute</option>
                <option value="300">5 minutes</option>
                <option value="900">15 minutes</option>
              </select>
            </Field>
          </div>

          <div className="recording-list">
            {(audioDebug?.recordings || []).length ? (
              audioDebug.recordings.map((recording) => (
                <div className="recording-row" key={recording.id}>
                  <div className="recording-meta">
                    <strong>{formatTimestamp(recording.started_at)}</strong>
                    <span>
                      {[recording.flow_name || recording.flow_id, recording.provider, recording.model]
                        .filter(Boolean)
                        .join(" / ")}
                    </span>
                  </div>
                  <div className="recording-actions">
                    <AudioDebugDownload file={recording.input} label="Input" />
                    <AudioDebugDownload file={recording.output} label="Output" />
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">No audio captures</div>
            )}
          </div>
          <div className="button-row">
            <Button icon={RefreshCw} variant="secondary" onClick={refreshAudioDebug}>
              {t("Refresh")}
            </Button>
            <Button
              icon={Trash2}
              variant="danger"
              onClick={clearAudioDebug}
              disabled={!(audioDebug?.recordings || []).length}
            >
              {t("Clear")}
            </Button>
          </div>
        </details>

        <div className="editor-actions">
          <Button icon={Save} onClick={save} disabled={saving}>
            {t("Save")}
          </Button>
        </div>

        <div className="divider" />
        <McpHistoryPanel mcpHistory={mcpHistory} refreshMcpHistory={refreshMcpHistory} clearMcpHistory={clearMcpHistory} />
      </section>
    </div>
  );
}

function offerPath(config) {
  if (config.runner_offer_path) return appUrl(config.runner_offer_path);
  try {
    const url = new URL(config.runner_offer_url || "api/offer", window.location.href);
    const token = url.searchParams.get("token");
    return appUrl(`api/offer${token ? `?token=${encodeURIComponent(token)}` : ""}`);
  } catch {
    return appUrl("api/offer");
  }
}

function browserClientId() {
  const key = "pipecat-assist-client-id";
  try {
    const existing = localStorage.getItem(key);
    if (existing) return existing;
    const created = randomId(32);
    localStorage.setItem(key, created);
    return created;
  } catch {
    return `browser-${Math.random().toString(16).slice(2)}`;
  }
}

function waitForIceGatheringComplete(peerConnection, timeoutMs = 2500) {
  if (peerConnection.iceGatheringState === "complete") return Promise.resolve();

  return new Promise((resolve) => {
    let done = false;
    let timer;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      peerConnection.removeEventListener("icegatheringstatechange", onChange);
      resolve();
    };
    const onChange = () => {
      if (peerConnection.iceGatheringState === "complete") finish();
    };
    timer = setTimeout(finish, timeoutMs);
    peerConnection.addEventListener("icegatheringstatechange", onChange);
  });
}

function VoiceTest({ config, flow }) {
  const audioRef = useRef(null);
  const canvasRef = useRef(null);
  const channelRef = useRef(null);
  const closingRef = useRef(false);
  const connectTimeoutRef = useRef(null);
  const pingRef = useRef(null);
  const peerRef = useRef(null);
  const readySentRef = useRef(false);
  const streamRef = useRef(null);
  const lastStoppedRef = useRef(0);
  const stateRef = useRef("idle");
  const messagesRef = useRef([]);
  const transcriptFlowRef = useRef(null);
  const transcriptSeqRef = useRef(0);
  const currentUserMessageIdRef = useRef("");
  const currentAssistantMessageIdRef = useRef("");
  const streamAssistantMessageIdRef = useRef("");
  const userTranscriptRef = useRef("");
  const assistantTranscriptRef = useRef("");
  const partialTranscriptRef = useRef("");
  const currentUserTextRef = useRef("");
  const currentUserUpdatedAtRef = useRef(0);
  const assistantTurnBaseRef = useRef("");
  const assistantTurnTextRef = useRef("");
  const assistantTurnPriorityRef = useRef(0);
  const assistantTurnActiveRef = useRef(false);
  const assistantLastTurnTextRef = useRef("");
  const assistantLastTurnPriorityRef = useRef(0);
  const assistantLastTurnFinishedAtRef = useRef(0);
  const lastAssistantTextAtRef = useRef(0);
  const lastUserTextAtRef = useRef(0);
  const botSpeakingRef = useRef(false);
  const ignoreLocalSpeechUntilRef = useRef(0);
  const assistantTurnFinishTimerRef = useRef(null);
  const endConversationPendingRef = useRef(false);
  const endConversationTimerRef = useRef(null);
  const endConversationStoppingRef = useRef(false);
  const localSpeechRecognitionRef = useRef(null);
  const localSpeechEndingRef = useRef(false);
  const localSpeechPausedForAssistantRef = useRef(false);
  const localSpeechResumeTimerRef = useRef(null);
  const scrollFrameRef = useRef(null);
  const scrollPosRef = useRef(0);
  const scrollTargetRef = useRef(0);
  const scrollLastTsRef = useRef(0);
  const visualizerContextRef = useRef(null);
  const visualizerEnergyRef = useRef(0);
  const visualizerFrameRef = useRef(null);
  const visualizerInputsRef = useRef({});
  const [state, setState] = useState("idle");
  const [detail, setDetail] = useState(assistantCardT("ready"));
  const [messages, setMessages] = useState([]);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const readiness = voiceReadiness(config, flow);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    visualizerFrameRef.current = requestAnimationFrame(drawVisualizer);
    return () => {
      disposeSession(true, false);
      stopLocalSpeechRecognition();
      cancelLocalSpeechResume();
      clearEndConversationRequest();
      stopTranscriptScroll();
      if (assistantTurnFinishTimerRef.current) clearTimeout(assistantTurnFinishTimerRef.current);
      if (visualizerFrameRef.current) cancelAnimationFrame(visualizerFrameRef.current);
      disconnectVisualizerInputs(true);
    };
  }, []);

  useEffect(() => {
    scrollTranscriptToEnd();
  }, [messages]);

  useEffect(() => {
    if (state === "error" && readiness.ok) {
      setSessionState("idle", assistantCardT("ready"));
    }
  }, [readiness.ok, state]);

  function setSessionState(nextState, nextDetail = detail) {
    stateRef.current = nextState;
    setState(nextState);
    setDetail(nextDetail);
  }

  function clearEndConversationRequest() {
    if (endConversationTimerRef.current) {
      clearTimeout(endConversationTimerRef.current);
      endConversationTimerRef.current = null;
    }
    endConversationPendingRef.current = false;
  }

  function finishConversationAfterAssistant(delayMs = 350) {
    if (endConversationStoppingRef.current) return;
    endConversationStoppingRef.current = true;
    clearEndConversationRequest();
    window.setTimeout(() => {
      stopVoiceTest();
      endConversationStoppingRef.current = false;
    }, delayMs);
  }

  function requestConversationEnd(fallbackMs = 8000) {
    endConversationPendingRef.current = true;
    if (endConversationTimerRef.current) clearTimeout(endConversationTimerRef.current);
    endConversationTimerRef.current = window.setTimeout(() => {
      finishConversationAfterAssistant(0);
    }, fallbackMs);
  }

  function commitMessages(updater) {
    const next = updater(messagesRef.current);
    messagesRef.current = next;
    setMessages(next);
  }

  function chatMessageById(id) {
    return messagesRef.current.find((message) => message.id === id) || null;
  }

  function appendChatMessage(type, text) {
    const id = `m${++transcriptSeqRef.current}`;
    const message = { id, type, text: normalizeTranscriptText(text), entered: false, streaming: false };
    commitMessages((current) => {
      const next = [...current, message];
      while (next.length > 12) {
        const removed = next.shift();
        if (removed?.id === currentUserMessageIdRef.current) currentUserMessageIdRef.current = "";
        if (removed?.id === currentAssistantMessageIdRef.current) currentAssistantMessageIdRef.current = "";
        if (removed?.id === streamAssistantMessageIdRef.current) streamAssistantMessageIdRef.current = "";
      }
      return next;
    });
    requestAnimationFrame(() => {
      commitMessages((current) => current.map((item) => (item.id === id ? { ...item, entered: true } : item)));
    });
    return id;
  }

  function updateChatMessage(id, text, options = {}) {
    const clean = normalizeTranscriptText(text);
    commitMessages((current) =>
      current.map((message) =>
        message.id === id ? { ...message, text: clean, streaming: Boolean(options.stream) } : message,
      ),
    );
  }

  function setCurrentUserCaption(text, startsNewTurn) {
    const clean = normalizeTranscriptText(text);
    if (!clean) return;
    if (startsNewTurn || !currentUserMessageIdRef.current || !chatMessageById(currentUserMessageIdRef.current)) {
      currentUserMessageIdRef.current = appendChatMessage("user", clean);
    } else {
      updateChatMessage(currentUserMessageIdRef.current, clean);
    }
  }

  function setCurrentAssistantCaption(text) {
    const clean = normalizeTranscriptText(text);
    if (!clean) return;
    if (!currentAssistantMessageIdRef.current || !chatMessageById(currentAssistantMessageIdRef.current)) {
      currentAssistantMessageIdRef.current = appendChatMessage("assistant", clean);
    }
    streamAssistantMessageIdRef.current = currentAssistantMessageIdRef.current;
    updateChatMessage(currentAssistantMessageIdRef.current, clean, { stream: true });
  }

  function finalizeAssistantCaption() {
    if (!currentAssistantMessageIdRef.current || !assistantTurnTextRef.current) return;
    updateChatMessage(currentAssistantMessageIdRef.current, assistantTurnTextRef.current);
    streamAssistantMessageIdRef.current = "";
  }

  function clearTranscriptData() {
    userTranscriptRef.current = "";
    assistantTranscriptRef.current = "";
    partialTranscriptRef.current = "";
    currentUserTextRef.current = "";
    currentUserUpdatedAtRef.current = 0;
    assistantTurnBaseRef.current = "";
    assistantTurnTextRef.current = "";
    assistantTurnPriorityRef.current = 0;
    assistantTurnActiveRef.current = false;
    assistantLastTurnTextRef.current = "";
    assistantLastTurnPriorityRef.current = 0;
    assistantLastTurnFinishedAtRef.current = 0;
    lastAssistantTextAtRef.current = 0;
    lastUserTextAtRef.current = 0;
    botSpeakingRef.current = false;
    ignoreLocalSpeechUntilRef.current = 0;
    clearEndConversationRequest();
    currentUserMessageIdRef.current = "";
    currentAssistantMessageIdRef.current = "";
    streamAssistantMessageIdRef.current = "";
    transcriptSeqRef.current = 0;
    stopTranscriptScroll();
    scrollPosRef.current = 0;
    scrollTargetRef.current = 0;
    messagesRef.current = [];
    setMessages([]);
  }

  function renderTranscriptText(message) {
    if (!message.streaming || message.text.length <= STREAM_FADE_LEN) return message.text;
    const solid = message.text.slice(0, message.text.length - STREAM_FADE_LEN);
    const tail = message.text.slice(message.text.length - STREAM_FADE_LEN);
    return (
      <>
        {solid}
        {Array.from({ length: STREAM_FADE_GROUPS }, (_, index) => (
          <span key={index} style={{ opacity: ((STREAM_FADE_GROUPS - index) / STREAM_FADE_GROUPS).toFixed(2) }}>
            {tail.slice(index * STREAM_CHARS_PER_GROUP, index * STREAM_CHARS_PER_GROUP + STREAM_CHARS_PER_GROUP)}
          </span>
        ))}
      </>
    );
  }

  function scrollTranscriptToEnd() {
    const el = transcriptFlowRef.current;
    if (!el) return;
    const max = el.scrollHeight - el.clientHeight;
    if (max <= 0) return;
    scrollTargetRef.current = max;
    startTranscriptScroll();
  }

  function startTranscriptScroll() {
    if (scrollFrameRef.current) return;
    const el = transcriptFlowRef.current;
    if (el) scrollPosRef.current = el.scrollTop;
    scrollTargetRef.current = Math.max(scrollTargetRef.current || 0, el ? el.scrollHeight - el.clientHeight : 0);
    scrollLastTsRef.current = 0;
    scrollFrameRef.current = requestAnimationFrame(transcriptScrollTick);
  }

  function stopTranscriptScroll() {
    if (scrollFrameRef.current) {
      cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = null;
    }
    scrollLastTsRef.current = 0;
  }

  function transcriptScrollTick(timestamp) {
    const el = transcriptFlowRef.current;
    if (!el) {
      stopTranscriptScroll();
      return;
    }
    const max = el.scrollHeight - el.clientHeight;
    if (max <= 0) {
      stopTranscriptScroll();
      return;
    }
    if (!scrollLastTsRef.current) scrollLastTsRef.current = timestamp;
    const deltaMs = timestamp - scrollLastTsRef.current;
    scrollLastTsRef.current = timestamp;
    const target = Math.min(max, Math.max(scrollTargetRef.current || 0, max));
    const distance = target - scrollPosRef.current;
    const absDistance = Math.abs(distance);
    if (absDistance <= 0.5) {
      el.scrollTop = target;
      stopTranscriptScroll();
      return;
    }
    const easing = Math.max(0.08, Math.min(0.32, deltaMs / 160));
    const minStep = Math.min(absDistance, Math.max(0.7, deltaMs * 0.06));
    const step = Math.sign(distance) * Math.max(minStep, absDistance * easing);
    scrollPosRef.current = Math.min(max, Math.max(0, scrollPosRef.current + step));
    el.scrollTop = scrollPosRef.current;
    scrollFrameRef.current = requestAnimationFrame(transcriptScrollTick);
  }

  function ensureVisualizerInput(name, stream) {
    if (!stream?.getAudioTracks?.().length) return;
    const trackIds = stream.getAudioTracks().map((track) => track.id).join(",");
    if (visualizerInputsRef.current[name]?.trackIds === trackIds) return;
    disconnectVisualizerInput(name);

    const AudioContextConstructor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextConstructor) return;
    try {
      if (!visualizerContextRef.current || visualizerContextRef.current.state === "closed") {
        visualizerContextRef.current = new AudioContextConstructor();
      }
      if (visualizerContextRef.current.state === "suspended") {
        visualizerContextRef.current.resume().catch(() => {});
      }
      const source = visualizerContextRef.current.createMediaStreamSource(stream);
      const analyser = visualizerContextRef.current.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = name === "remote" ? 0.72 : 0.82;
      source.connect(analyser);
      visualizerInputsRef.current[name] = {
        analyser,
        data: new Uint8Array(analyser.frequencyBinCount),
        source,
        trackIds,
      };
    } catch {
      disconnectVisualizerInput(name);
    }
  }

  function disconnectVisualizerInput(name) {
    const input = visualizerInputsRef.current[name];
    if (!input) return;
    try {
      input.source.disconnect();
    } catch {
      // Ignore already disconnected visualizer nodes.
    }
    delete visualizerInputsRef.current[name];
  }

  function disconnectVisualizerInputs(closeContext = false) {
    for (const name of Object.keys(visualizerInputsRef.current)) disconnectVisualizerInput(name);
    if (closeContext && visualizerContextRef.current && visualizerContextRef.current.state !== "closed") {
      visualizerContextRef.current.close().catch(() => {});
      visualizerContextRef.current = null;
    }
    visualizerEnergyRef.current = 0;
  }

  function visualizerEnergyFor(name) {
    const input = visualizerInputsRef.current[name];
    if (!input?.analyser) return 0;
    input.analyser.getByteFrequencyData(input.data);
    const limit = Math.min(input.data.length, 96);
    let sum = 0;
    for (let index = 0; index < limit; index += 1) sum += input.data[index];
    return Math.min(1, sum / Math.max(1, limit) / 150);
  }

  function drawVisualizer() {
    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.floor(rect.width * dpr));
      const height = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }

      const ctx = canvas.getContext("2d");
      const accent = hexToRgb(ASSISTANT_CARD_ACCENT_HEX);
      const localEnergy = visualizerEnergyFor("local");
      const remoteEnergy = visualizerEnergyFor("remote");
      const running = ["requesting", "connecting", "connected"].includes(stateRef.current);
      const audioActive = Math.max(localEnergy, remoteEnergy) > 0.018
        || botSpeakingRef.current
        || assistantTurnActiveRef.current
        || Boolean(partialTranscriptRef.current);
      const idleEnergy = running ? 0.06 : 0.025;
      const targetEnergy = Math.max(localEnergy, remoteEnergy, idleEnergy);
      visualizerEnergyRef.current = visualizerEnergyRef.current * 0.82 + targetEnergy * 0.18;
      const energy = visualizerEnergyRef.current;
      const time = audioActive || running ? performance.now() / 1000 : 0;

      ctx.clearRect(0, 0, width, height);
      const horizon = height * 0.68;
      const gradient = ctx.createLinearGradient(0, 0, 0, height);
      gradient.addColorStop(0, `rgba(${accent.r}, ${accent.g}, ${accent.b}, 0)`);
      gradient.addColorStop(0.24, `rgba(${accent.r}, ${accent.g}, ${accent.b}, 0.025)`);
      gradient.addColorStop(0.68, `rgba(${accent.r}, ${accent.g}, ${accent.b}, 0.18)`);
      gradient.addColorStop(1, `rgba(${accent.r}, ${accent.g}, ${accent.b}, 0.55)`);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);

      ctx.save();
      ctx.translate(width / 2, horizon + height * 0.68);
      ctx.scale(1, 0.32);
      ctx.beginPath();
      ctx.arc(0, 0, width * (0.5 + energy * 0.07), 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(190, 220, 255, ${0.34 + energy * 0.28})`;
      ctx.lineWidth = Math.max(1, 1.4 * dpr);
      ctx.shadowColor = `rgba(${accent.r}, ${accent.g}, ${accent.b}, 0.88)`;
      ctx.shadowBlur = 18 * dpr + energy * 30 * dpr;
      ctx.stroke();
      ctx.restore();

      const drawWave = (color, offset, amplitude, widthScale, alpha) => {
        ctx.beginPath();
        for (let x = 0; x <= width; x += Math.max(2, width / 120)) {
          const progress = x / width;
          const envelope = Math.sin(progress * Math.PI);
          const y = height * 0.62
            + Math.sin(progress * Math.PI * 4.6 + time * 2.2 + offset) * amplitude * envelope
            + Math.sin(progress * Math.PI * 9.2 - time * 1.4 - offset) * amplitude * 0.28 * envelope;
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = Math.max(1, widthScale * dpr);
        ctx.globalAlpha = alpha;
        ctx.stroke();
        ctx.globalAlpha = 1;
      };

      drawWave(`rgba(${accent.r}, ${accent.g}, ${accent.b}, 0.9)`, 0, 10 + energy * 46, 2.4, 0.55 + energy * 0.35);
      drawWave("rgba(190, 220, 255, 0.85)", 1.6, 7 + energy * 30, 1.6, 0.4 + energy * 0.3);
      drawWave(`rgba(${accent.r}, ${accent.g}, ${accent.b}, 0.6)`, 3.1, 5 + energy * 18, 1.1, 0.3 + energy * 0.25);
    }
    visualizerFrameRef.current = requestAnimationFrame(drawVisualizer);
  }

  function applyRemoteAudioBuffer(receiver) {
    try {
      const params = receiver.getParameters?.() || {};
      params.playoutDelayHint = ASSISTANT_CARD_AUDIO_BUFFER_MS / 1000;
      receiver.setParameters?.(params);
    } catch {
      // Not all browsers support playoutDelayHint; ignore.
    }
  }

  function attachAudio(stream) {
    const audio = audioRef.current;
    if (!audio || !stream) return;
    audio.srcObject = stream;
    const playPromise = audio.play();
    if (playPromise?.catch) {
      playPromise.catch(() => setAudioBlocked(true));
    }
  }

  function stopLocalSpeechRecognition() {
    const recognition = localSpeechRecognitionRef.current;
    if (!recognition) return;
    localSpeechEndingRef.current = true;
    try {
      recognition.onresult = null;
      recognition.onend = null;
      recognition.onerror = null;
      recognition.stop();
    } catch {
      // Ignore stop errors from an already-stopped recognizer.
    }
    localSpeechRecognitionRef.current = null;
  }

  function cancelLocalSpeechResume() {
    if (localSpeechResumeTimerRef.current) {
      clearTimeout(localSpeechResumeTimerRef.current);
      localSpeechResumeTimerRef.current = null;
    }
  }

  function disposeSession(skipClose = false, resetState = true) {
    closingRef.current = true;
    if (connectTimeoutRef.current) {
      clearTimeout(connectTimeoutRef.current);
      connectTimeoutRef.current = null;
    }
    if (pingRef.current) {
      clearInterval(pingRef.current);
      pingRef.current = null;
    }
    if (channelRef.current) {
      try {
        channelRef.current.close();
      } catch {
        // Ignore already-closed data channels.
      }
      channelRef.current = null;
    }
    if (peerRef.current && !skipClose) {
      try {
        peerRef.current.close();
      } catch {
        // Ignore already-closed peer connections.
      }
    }
    peerRef.current = null;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    disconnectVisualizerInputs();
    readySentRef.current = false;
    if (audioRef.current) audioRef.current.srcObject = null;
    setAudioBlocked(false);
    if (resetState) clearTranscriptData();
    closingRef.current = false;
  }

  function markConnected() {
    if (connectTimeoutRef.current) {
      clearTimeout(connectTimeoutRef.current);
      connectTimeoutRef.current = null;
    }
    setSessionState("connected", assistantCardT("connectedDetail"));
    lastStoppedRef.current = 0;
  }

  function failWebRtc(message) {
    disposeSession();
    setSessionState("error", message);
  }

  function clearSession(nextState = "idle", nextDetail = assistantCardT("ready")) {
    disposeSession();
    setSessionState(nextState, nextDetail);
  }

  function handleRtviMessage(raw) {
    let payload;
    try {
      payload = JSON.parse(raw);
    } catch {
      return;
    }
    const type = String(payload?.type || payload?.label || "");
    const data = payload?.data || payload;

    if (type === "bot-ready" || type === "ready") {
      readySentRef.current = true;
      return;
    }

    if (type === "bot-started-speaking") {
      botSpeakingRef.current = true;
      return;
    }
    if (type === "bot-stopped-speaking") {
      botSpeakingRef.current = false;
      finalizeAssistantCaption();
      if (endConversationPendingRef.current) finishConversationAfterAssistant();
      return;
    }
    if (type === "user-started-speaking") {
      ignoreLocalSpeechUntilRef.current = 0;
      return;
    }
    if (type === "user-stopped-speaking") {
      return;
    }

    if (isRtviUserTextType(type)) {
      const text = firstString(data?.text, data?.transcript, data?.data?.text);
      if (!text) return;
      const final = data?.final !== false;
      partialTranscriptRef.current = final ? "" : text;
      if (final) {
        userTranscriptRef.current = mergeDisplayTurnText(userTranscriptRef.current, text);
        lastUserTextAtRef.current = Date.now();
        setCurrentUserCaption(userTranscriptRef.current, Date.now() - lastAssistantTextAtRef.current < 200);
      } else {
        setCurrentUserCaption(mergeDisplayTurnText(userTranscriptRef.current, text), false);
      }
      return;
    }

    if (isRtviAssistantTextType(type)) {
      const text = firstString(data?.text, data?.data?.text);
      if (!text) return;
      const priority = rtviAssistantTextPriority(type);
      const now = Date.now();
      const startsNewTurn =
        !assistantTurnActiveRef.current
        || now - assistantLastTurnFinishedAtRef.current > 1200;
      if (startsNewTurn) {
        assistantTurnBaseRef.current = "";
        assistantTurnTextRef.current = "";
        assistantTurnPriorityRef.current = 0;
        assistantTurnActiveRef.current = true;
        currentAssistantMessageIdRef.current = "";
      }
      const cleaned = isLikelyTranscriptEcho(text, userTranscriptRef.current)
        ? removeTranscriptEchoSpan(text, userTranscriptRef.current)
        : text;
      assistantTurnTextRef.current = mergeAssistantTurnText(
        assistantTurnTextRef.current,
        cleaned,
        priority,
        assistantTurnPriorityRef.current,
      );
      assistantTurnPriorityRef.current = Math.max(assistantTurnPriorityRef.current, priority);
      lastAssistantTextAtRef.current = now;
      setCurrentAssistantCaption(assistantTurnTextRef.current);

      if (assistantTurnFinishTimerRef.current) clearTimeout(assistantTurnFinishTimerRef.current);
      assistantTurnFinishTimerRef.current = window.setTimeout(() => {
        assistantLastTurnTextRef.current = assistantTurnTextRef.current;
        assistantLastTurnPriorityRef.current = assistantTurnPriorityRef.current;
        assistantLastTurnFinishedAtRef.current = Date.now();
        assistantTurnActiveRef.current = false;
        finalizeAssistantCaption();
        if (shouldEndConversation(assistantTurnTextRef.current)) requestConversationEnd();
      }, 900);
      return;
    }
  }

  async function startVoiceTest() {
    if (!readiness.ok) return;
    clearTranscriptData();
    setAudioBlocked(false);
    setSessionState("requesting", assistantCardT("waitingForMicrophone"));

    let stream;
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw Object.assign(new Error(assistantCardT("microphoneUnavailable")), { name: "NotFoundError" });
      }
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setSessionState("error", friendlyWebRtcError(err));
      return;
    }

    streamRef.current = stream;
    ensureVisualizerInput("local", stream);
    setSessionState("connecting", assistantCardT("connecting"));

    try {
      const peerConnection = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      });
      peerRef.current = peerConnection;

      stream.getTracks().forEach((track) => peerConnection.addTrack(track, stream));
      peerConnection.addTransceiver("audio", { direction: "recvonly" });

      peerConnection.addEventListener("track", (event) => {
        if (event.track.kind !== "audio") return;
        const [remoteStream] = event.streams;
        attachAudio(remoteStream);
        ensureVisualizerInput("remote", remoteStream);
      });

      peerConnection.addEventListener("connectionstatechange", () => {
        if (closingRef.current) return;
        if (peerConnection.connectionState === "connected") {
          markConnected();
        } else if (["failed", "closed"].includes(peerConnection.connectionState)) {
          failWebRtc("WebRTC connection was lost. Restart the voice test.");
        }
      });

      const channel = peerConnection.createDataChannel("rtvi-ai", { ordered: true });
      channelRef.current = channel;
      channel.addEventListener("message", (event) => handleRtviMessage(event.data));
      channel.addEventListener("open", () => {
        pingRef.current = window.setInterval(() => {
          try {
            channel.send(JSON.stringify({ label: "rtvi-ai", type: "client-ready", id: randomId(8) }));
          } catch {
            // Ignore send failures on a closing channel.
          }
        }, 20000);
      });

      const offer = await peerConnection.createOffer();
      offer.sdp = preferFullbandOpus(offer.sdp);
      await peerConnection.setLocalDescription(offer);
      await waitForIceGatheringComplete(peerConnection);

      const response = await fetch(offerPath(config), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sdp: peerConnection.localDescription.sdp,
          type: peerConnection.localDescription.type,
          request_data: {
            flow_id: flow.id,
            source: "ui_voice_test",
            client_id: browserClientId(),
            language: navigator.language || UI_LOCALE || "en",
          },
        }),
      });

      if (!response.ok) {
        throw new Error(await offerErrorMessage(response));
      }

      const answer = await response.json();
      await peerConnection.setRemoteDescription({
        sdp: answer.sdp,
        type: answer.type,
      });
      peerConnection.getReceivers?.()
        .filter((receiver) => receiver.track?.kind === "audio")
        .forEach((receiver) => applyRemoteAudioBuffer(receiver));
      setDetail(assistantCardT("connectingAudio"));
      if (
        peerConnection.connectionState === "connected" ||
        ["connected", "completed"].includes(peerConnection.iceConnectionState)
      ) {
        markConnected();
      } else {
        connectTimeoutRef.current = window.setTimeout(() => {
          failWebRtc("WebRTC audio did not connect after the offer was accepted. Restart the add-on after updating and check the add-on logs for ICE errors.");
        }, 15000);
      }
    } catch (err) {
      clearSession("error", friendlyWebRtcError(err));
    }
  }

  function stopVoiceTest() {
    clearSession();
  }

  const running = ["requesting", "connecting", "connected"].includes(state);
  const stateLabel = state === "idle" && !readiness.ok ? assistantCardT("setupNeeded") : {
    connected: assistantCardT("connected"),
    connecting: assistantCardT("connecting"),
    error: assistantCardT("error"),
    idle: assistantCardT("ready"),
    requesting: assistantCardT("connecting"),
  }[state];
  const statusClass = state === "idle" && !readiness.ok
    ? "error"
    : state === "connected"
      ? "connected"
      : state === "requesting" || state === "connecting"
        ? "connecting"
        : state === "error"
          ? "error"
          : "ready";
  const startDisabled = state === "idle" && !readiness.ok;

  return (
    <div className="assistant-card-test" style={{ "--assistant-card-accent": ASSISTANT_CARD_ACCENT_HEX }}>
      <div className="assistant-card-head">
        <div className="assistant-card-title">
          <h3>Sarvam Assist</h3>
          <span className={`assistant-card-status ${statusClass}`}>{stateLabel}</span>
        </div>
        <div className="assistant-card-actions">
          {running && audioBlocked && (
            <button className="secondary" type="button" onClick={() => {
              setAudioBlocked(false);
              setDetail(assistantCardT("connectedDetail"));
              attachAudio(audioRef.current?.srcObject);
            }}>
              {assistantCardT("enableAudio")}
            </button>
          )}
          <button
            className={`main-button ${running ? "stop" : "talk"}`}
            type="button"
            onClick={running ? () => stopVoiceTest() : startVoiceTest}
            disabled={startDisabled}
          >
            {running ? assistantCardT("stop") : assistantCardT("talk")}
          </button>
        </div>
      </div>
      <div className="assistant-card-transcript-layer" aria-live="polite">
        <div className="assistant-card-transcript-flow" ref={transcriptFlowRef}>
          {messages.length ? (
            messages.map((message) => (
              <div
                key={message.id}
                className={`assistant-card-transcript-msg ${message.type}${message.entered ? "" : " new-message"}`}
              >
                <span className="assistant-card-transcript-text">{renderTranscriptText(message)}</span>
              </div>
            ))
          ) : (
            <div
              className={state === "error" ? "assistant-card-transcript-placeholder error" : "assistant-card-transcript-placeholder"}
            >
              {state === "idle" ? assistantCardT("greeting") : detail}
            </div>
          )}
        </div>
      </div>
      <div className="assistant-card-visualizer-shell" aria-hidden="true">
        <canvas className="assistant-card-visualizer" ref={canvasRef} />
      </div>
      <span className="assistant-card-version">v{ASSISTANT_CARD_VERSION}</span>
      <audio ref={audioRef} autoPlay playsInline />
    </div>
  );
}

function AudioDebugDownload({ file, label }) {
  if (!file) {
    return <span className="recording-empty">{label}: pending</span>;
  }
  return (
    <a className="button secondary" href={appUrl(file.url)} download={file.filename}>
      <Download size={16} strokeWidth={2} />
      <span>
        {label} ({formatBytes(file.size)})
      </span>
    </a>
  );
}

function McpHistoryPanel({ mcpHistory, refreshMcpHistory, clearMcpHistory }) {
  const calls = mcpHistory?.calls || [];
  return (
    <section className="mcp-history-panel">
      <div className="panel-head">
        <div>
          <h3>{t("Home Assistant actions")}</h3>
          <span>{calls.length ? `${calls.length} recent MCP calls` : "no MCP calls yet"}</span>
        </div>
        <div className="button-row">
          <Button icon={RefreshCw} variant="secondary" onClick={refreshMcpHistory}>
            {t("Refresh")}
          </Button>
          <Button icon={Trash2} variant="danger" onClick={clearMcpHistory} disabled={!calls.length}>
            {t("Clear")}
          </Button>
        </div>
      </div>
      <div className="mcp-history-list">
        {calls.length ? (
          calls.map((call) => (
            <div key={call.id} className={call.ok ? "mcp-call ok" : "mcp-call error"}>
              <div className="mcp-call-head">
                <strong>{call.tool || "unknown tool"}</strong>
                <span>{[formatTimestamp(call.started_at), formatDuration(call.duration_ms)].filter(Boolean).join(" / ")}</span>
              </div>
              {call.arguments && <pre>{call.arguments}</pre>}
              <small>{call.ok ? call.result || "Tool completed" : call.error || "Tool failed"}</small>
            </div>
          ))
        ) : (
          <div className="empty-state">No Home Assistant MCP calls recorded yet.</div>
        )}
      </div>
    </section>
  );
}

function EspHomeSatellitePanel({ config, copyEspHomeUrl, updateConfig }) {
  const provisioning = config.esphome_provisioning || {};
  const provisionedCount = Number(provisioning.provisioned_count || 0);
  const provisioningMessage = provisioning.last_error
    ? provisioning.last_error
    : provisionedCount > 0
      ? `${provisionedCount} compatible satellite${provisionedCount === 1 ? "" : "s"} provisioned automatically.`
      : "Waiting for a compatible ESPHome satellite to connect to Home Assistant.";

  return (
    <>
      <div className="panel-head">
        <div>
          <h3>ESPHome satellite</h3>
          <span>Raw PCM full-duplex transport with server-driven conversation states</span>
        </div>
      </div>
      <div className="setup-callout">
        <Radio size={20} />
        <div>
          <strong>ESPHome endpoint provisioning is automatic.</strong>
          <span>
            {provisioningMessage} The authenticated URL is delivered through the native ESPHome
            API and is never published as an entity.
          </span>
        </div>
      </div>
      <div className="satellite-endpoint">
        <Field label="Manual fallback endpoint" wide>
          <input readOnly spellCheck="false" value={config.esphome_ws_url || ""} />
        </Field>
        <Button icon={Copy} variant="secondary" onClick={copyEspHomeUrl}>
          Copy endpoint
        </Button>
      </div>
      <div className="form-grid satellite-settings">
        <Field label="Device-reachable host override" wide>
          <input
            spellCheck="false"
            placeholder="homeassistant.local or 192.168.1.10"
            value={config.runner_host || ""}
            onChange={(event) =>
              updateConfig((draft) => ({ ...draft, runner_host: event.target.value.trim() }))
            }
          />
        </Field>
        <Field label="Follow-up listening (ms)">
          <input
            type="number"
            min="0"
            max="60000"
            step="100"
            value={config.esphome_follow_up_ms}
            onChange={(event) =>
              updateConfig((draft) => ({
                ...draft,
                esphome_follow_up_ms: Math.min(60000, Math.max(0, Number(event.target.value || 0))),
              }))
            }
          />
        </Field>
        <Field label="Follow-up mic delay (ms)">
          <input
            type="number"
            min="0"
            max="5000"
            step="20"
            value={config.esphome_follow_up_open_delay_ms}
            onChange={(event) =>
              updateConfig((draft) => ({
                ...draft,
                esphome_follow_up_open_delay_ms: Math.min(
                  5000,
                  Math.max(0, Number(event.target.value || 0)),
                ),
              }))
            }
          />
        </Field>
        <Field label="Wake mic delay (ms)">
          <input
            type="number"
            min="0"
            max="5000"
            step="20"
            value={config.esphome_wake_open_delay_ms}
            onChange={(event) =>
              updateConfig((draft) => ({
                ...draft,
                esphome_wake_open_delay_ms: Math.min(
                  5000,
                  Math.max(0, Number(event.target.value || 0)),
                ),
              }))
            }
          />
        </Field>
        <Field label="Playback prebuffer (ms)">
          <input
            type="number"
            min="0"
            max="2000"
            step="20"
            value={config.esphome_playback_prebuffer_ms}
            onChange={(event) =>
              updateConfig((draft) => ({
                ...draft,
                esphome_playback_prebuffer_ms: Math.min(
                  2000,
                  Math.max(0, Number(event.target.value || 0)),
                ),
              }))
            }
          />
        </Field>
      </div>
      <p className="field-help">
        Save Settings after changing the host. The endpoint is regenerated with the same secret.
        Follow-up 0 disables continuous conversation; playback prebuffer trades latency for jitter
        tolerance.
      </p>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
