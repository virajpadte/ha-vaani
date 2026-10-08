"""Home Assistant exposed-device context: fetch, compact for the system prompt, and
fuzzy-match against on a failed HA intent tool call.

Two Home Assistant core contracts this depends on (verified against HA's actual source,
not guessed):

- ``GetLiveContextTool`` (``homeassistant/components/homeassistant/llm.py``). Its MCP tool
  name is ``"homeassistant__GetLiveContext"`` as of HA 2026.9 (older HA exposed it
  unprefixed as ``"GetLiveContext"``). It returns a YAML dump of a list of entity dicts
  (keys: ``names`` comma-joined, ``domain``, optionally ``areas``/``state``/``attributes``)
  wrapped in a preamble sentence, itself wrapped in ``{"result": "..."}``.
- ``MatchFailedError`` surfaced to an LLM/MCP caller via HA's ``IntentTool``
  (``homeassistant/helpers/llm.py``), which returns structured data instead of raising:
  ``{"error": "MatchFailedError", "reason": "name", "constraints": {"name": "..."}}``.
  ``reason`` is the lowercased ``MatchFailedReason`` enum name (name/area/domain/...).

Both envelopes can still drift across HA versions, so every parser here is defensive and
never raises — a surprising shape just yields an empty/None result.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field

import yaml
from loguru import logger

_VOWELS = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "i",
    "उ": "u",
    "ऊ": "u",
    "ऋ": "ri",
    "ॠ": "ri",
    "ऌ": "lri",
    "ॡ": "lri",
    "ऍ": "ae",
    "ऎ": "e",
    "ए": "e",
    "ऐ": "ai",
    "ऑ": "o",
    "ऒ": "o",
    "ओ": "o",
    "औ": "au",
    "ॲ": "a",
}

# Consonants, with their inherent "a" vowel included.
_CONSONANTS = {
    "क": "ka", "ख": "kha", "ग": "ga", "घ": "gha", "ङ": "nga",
    "च": "cha", "छ": "chha", "ज": "ja", "झ": "jha", "ञ": "nya",
    "ट": "ta", "ठ": "tha", "ड": "da", "ढ": "dha", "ण": "na",
    "त": "ta", "थ": "tha", "द": "da", "ध": "dha", "न": "na",
    "प": "pa", "फ": "pha", "ब": "ba", "भ": "bha", "म": "ma",
    "य": "ya", "र": "ra", "ल": "la", "व": "va",
    "श": "sha", "ष": "sha", "स": "sa", "ह": "ha",
    "ळ": "la", "ऴ": "la",
    # Nukta variants approximated to their base consonant sound.
    "क़": "ka", "ख़": "kha", "ग़": "ga", "ज़": "za",
    "ड़": "ra", "ढ़": "rha", "फ़": "fa", "य़": "ya",
}

# Vowel signs (matras) combine with the preceding consonant, replacing its inherent "a".
_MATRAS = {
    "ा": "aa",
    "ि": "i",
    "ी": "i",
    "ु": "u",
    "ू": "u",
    "ृ": "ri",
    "ॄ": "ri",
    "ॅ": "ae",
    "ॆ": "e",
    "े": "e",
    "ै": "ai",
    "ॉ": "o",
    "ॊ": "o",
    "ो": "o",
    "ौ": "au",
}

_VIRAMA = "्"
_ANUSVARA = "ं"
_CHANDRABINDU = "ँ"
_VISARGA = "ः"
_AVAGRAHA = "ऽ"
_DIGIT_BASE = ord("०")


def transliterate_devanagari(text: str) -> str:
    """Phonetic-approximate Devanagari -> Latin, good enough for fuzzy matching.

    Not a linguistically exact transliteration scheme - just close enough that
    difflib scores it well against the intended English word (e.g. "स्ट्रीम" becomes
    something close to "stream"). Non-Devanagari characters pass through unchanged.
    """

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in _CONSONANTS:
            base = _CONSONANTS[ch]
            stem = base[:-1] if base.endswith("a") else base
            if i + 1 < n and text[i + 1] == _VIRAMA:
                out.append(stem)
                i += 2
                continue
            if i + 1 < n and text[i + 1] in _MATRAS:
                out.append(stem + _MATRAS[text[i + 1]])
                i += 2
                continue
            out.append(base)
            i += 1
            continue
        if ch in _VOWELS:
            out.append(_VOWELS[ch])
            i += 1
            continue
        if ch in (_ANUSVARA, _CHANDRABINDU):
            out.append("n")
            i += 1
            continue
        if ch == _VISARGA:
            out.append("h")
            i += 1
            continue
        if ch == _AVAGRAHA or ch == _VIRAMA:
            i += 1
            continue
        if ch in _MATRAS:
            out.append(_MATRAS[ch])
            i += 1
            continue
        if "०" <= ch <= "९":
            out.append(chr(ord(ch) - _DIGIT_BASE + ord("0")))
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _match_variants(text: str) -> list[str]:
    """A string plus its transliteration, casefolded, for comparison."""

    text = (text or "").strip()
    if not text:
        return []
    variants = {text.casefold(), transliterate_devanagari(text).casefold()}
    return [variant for variant in variants if variant]


def parse_live_context(raw_text: str) -> list[dict]:
    """Parse GetLiveContext's output into a normalized entity list.

    Returns ``[{"name": str, "aliases": [str], "domain": str, "areas": [str]}, ...]``.
    Defensive: tries a ``{"result": "..."}`` JSON envelope first (HA's actual shape), then
    falls back to treating the input as the raw text directly. Never raises - returns ``[]``
    on anything it can't make sense of.
    """

    if not raw_text or not raw_text.strip():
        return []

    text = raw_text
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and isinstance(data.get("result"), str):
            text = data["result"]
    except (json.JSONDecodeError, TypeError):
        pass

    # HA prefixes the YAML with a "Live Context: ..." sentence on its own line before the
    # actual YAML list - skip to the first "- " list marker rather than parsing that too.
    lines = text.splitlines()
    yaml_start = next((idx for idx, line in enumerate(lines) if line.lstrip().startswith("- ")), 0)
    yaml_text = "\n".join(lines[yaml_start:]) or text

    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as err:
        logger.warning("Could not parse GetLiveContext output as YAML: {}", err)
        return []

    if not isinstance(parsed, list):
        return []

    entities: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        names_field = item.get("names") or item.get("name") or ""
        names = [part.strip() for part in str(names_field).split(",") if part.strip()]
        if not names:
            continue
        areas_field = item.get("areas") or item.get("area") or []
        if isinstance(areas_field, str):
            areas = [areas_field] if areas_field.strip() else []
        elif isinstance(areas_field, list):
            areas = [str(area).strip() for area in areas_field if str(area).strip()]
        else:
            areas = []
        entities.append(
            {
                "name": names[0],
                "aliases": names[1:],
                "domain": str(item.get("domain") or "").strip(),
                "areas": areas,
            }
        )
    return entities


def build_device_list_text(entities: list[dict]) -> str:
    """Compact "Exposed devices: ..." line plus the name-mapping rule for the system prompt."""

    if not entities:
        return ""

    parts = []
    for entity in entities:
        area = entity["areas"][0] if entity["areas"] else ""
        label = f"{entity['name']} ({entity['domain']}, {area})" if area else f"{entity['name']} ({entity['domain']})"
        parts.append(label)

    return (
        "Exposed devices: "
        + "; ".join(parts)
        + ". In tool calls, always use these exact English names and areas. The user may "
        "say them in another language or script (e.g. Devanagari); map what they say to "
        "the closest entry in this list. "
        "For a request to turn OFF all devices, or all devices of one kind, in a room or "
        "the whole house (e.g. 'turn off all lights'), prefer one domain/area-wide turn-off "
        "call over calling it per device, and also include switch-domain entities whose name "
        "contains 'lamp' or 'light'. There is no equivalent all-at-once call for turning "
        "devices ON, so for a request like 'turn on all lights' call turn-on once for every "
        "matching device from this list (also including switch entities named lamp/light) so "
        "none are missed. After making a change, confirm out loud which device(s) changed - "
        "never just say it is done without naming them. Use the exact technical name from "
        "this list only in tool calls. When speaking to the user, say each device's name "
        "naturally in the conversation's language instead of reading the raw technical name "
        "verbatim - drop vendor names, model numbers, or codes (e.g. say 'Deck Lights', not "
        "'TP-LINK_Smart Plug_036D Deck Lights')."
    )


def is_match_failed(result_text: str) -> dict | None:
    """Detect a Home Assistant intent-matching failure in a tool call result.

    Returns ``{"reason": str, "constraints": dict, "no_match_name": str | None}`` when the
    result indicates a match failure, else ``None``.
    """

    if not result_text:
        return None

    try:
        data = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        data = None

    if isinstance(data, dict) and data.get("error") == "MatchFailedError":
        return {
            "reason": str(data.get("reason") or ""),
            "constraints": data.get("constraints") or {},
            "no_match_name": data.get("no_match_name"),
        }

    if "MatchFailedError" in result_text:
        return {"reason": "", "constraints": {}, "no_match_name": None}

    return None


@dataclass
class MatchCandidate:
    entity: dict
    score: float
    fields: dict = field(default_factory=dict)


def find_best_match(
    requested_name: str,
    requested_area: str | None,
    requested_domain: str | list | None,
    entities: list[dict],
) -> tuple[dict | None, float]:
    """Fuzzy-match a failed tool call's requested name/area against known entities.

    Domain (if given) is filtered exactly - it isn't script-ambiguous. Name and area are
    scored with difflib against both the raw and transliterated requested text. Returns the
    single best ``(entity, score)``, or ``(None, 0.0)`` if nothing is close.
    """

    if not requested_name or not entities:
        return None, 0.0

    domains = requested_domain if isinstance(requested_domain, list) else [requested_domain] if requested_domain else []
    domains = {str(d).strip().casefold() for d in domains if d}
    candidates = [e for e in entities if not domains or e["domain"].casefold() in domains] or entities

    name_variants = _match_variants(requested_name)
    area_variants = _match_variants(requested_area) if requested_area else []

    best_entity: dict | None = None
    best_score = 0.0
    for entity in candidates:
        entity_names = [entity["name"], *entity["aliases"]]
        # Also compare against individual words (e.g. "Deck" alone should match "Deck
        # Lights" even without "Lights" spoken, and even with no separate alias for it).
        entity_names = entity_names + [word for name in entity_names for word in name.split()]
        name_score = max(
            (
                difflib.SequenceMatcher(None, req, cand.casefold()).ratio()
                for req in name_variants
                for cand in entity_names
            ),
            default=0.0,
        )
        if area_variants and entity["areas"]:
            area_score = max(
                (
                    difflib.SequenceMatcher(None, req, cand.casefold()).ratio()
                    for req in area_variants
                    for cand in entity["areas"]
                ),
                default=0.0,
            )
            score = 0.7 * name_score + 0.3 * area_score
        else:
            score = name_score
        if score > best_score:
            best_score = score
            best_entity = entity

    if best_entity is None or best_score < 0.5:
        return None, best_score
    return best_entity, best_score


def build_fallback_message(candidate: dict, score: float, requested_name: str, requested_area: str | None) -> str:
    """Tool-result text asking the model to confirm a fuzzy-matched device, not auto-run it."""

    area = candidate["areas"][0] if candidate["areas"] else ""
    where = f" in {area}" if area else ""
    return (
        f'No exact match for "{requested_name}"'
        + (f' in area "{requested_area}"' if requested_area else "")
        + f'. The closest exposed device{where} is "{candidate["name"]}" ({candidate["domain"]}). '
        "Ask the user a short one-line confirmation in the conversation's language (e.g. "
        f'"Turn on {candidate["name"]}?") before acting. If they confirm, retry this exact '
        f'tool call using name="{candidate["name"]}"'
        + (f', area="{area}"' if area else "")
        + ". Do not guess silently and do not report that the device was not found."
    )


def build_no_candidate_message(requested_name: str, requested_area: str | None) -> str:
    """Tool-result text for when no exposed device is even a plausible match."""

    where = f' in area "{requested_area}"' if requested_area else ""
    return (
        f'No exposed device matches "{requested_name}"{where}. Ask the user which device '
        "or room they meant, in the conversation's language. Do not just report failure."
    )
