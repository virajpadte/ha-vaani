# Vaani Documentation

## What this add-on is

Vaani runs one fixed realtime voice pipeline - **Sarvam
speech-to-text -> Model -> Home Assistant tools -> Sarvam text-to-speech**,
with optional session memory and web search - rather than a configurable
multi-provider pipeline builder. Speech-to-text and text-to-speech are always
Sarvam AI; only the Model step has a choice (Sarvam Cloud or Local).

## Requirements

- An API key from [Sarvam AI](https://www.sarvam.ai/).
- Home Assistant's own Model Context Protocol server (used automatically
  through the Supervisor connection - nothing extra to install).
- A reachable LAN IP for Home Assistant if ESP32 satellites will connect.
- Optionally, a [Tavily](https://tavily.com/) API key for web search.

## Install/update time

No pre-built image is published for this add-on, so every install and every
update **builds the image from source on your own Home Assistant hardware**:
system packages (ffmpeg, build tools) first, then a genuinely heavy Python
dependency tree required for realtime audio/WebRTC - numpy, numba,
onnxruntime, scipy, aiortc, opencv. That's slow by nature, not a sign
something's wrong:

- Typical x86 hardware: **5-10 minutes**.
- Raspberry Pi or other ARM hardware: **15-20+ minutes**, more on first
  install if any dependency has to compile from source instead of using a
  pre-built wheel.

To watch it happen instead of wondering if it's frozen: go to
**Settings > System > Logs**, then select **Supervisor** from the dropdown
in the top-right corner. The build log is staged with `[1/4]` through
`[4/4]` banners (system packages -> Python dependencies -> app copy -> done)
so you can see concrete progress rather than a wall of unexplained `pip`
output.

## Configuration

Most settings live in the Vaani settings UI, not in Home Assistant
add-on options.

`runner_port`
: Runner port. Keep the default unless you also know how Home Assistant
Ingress and direct clients reach the add-on.

`log_level`
: Application log level.

## Settings UI

The settings screen configures the whole fixed pipeline in one place:

- **Sarvam API key** - required for STT, the Model (when using Sarvam Cloud),
  and TTS.
- **Language** - a dropdown of Sarvam's supported languages (English plus 10
  Indic languages - Hindi, Marathi, Tamil, Telugu, Bengali, Gujarati, Kannada,
  Malayalam, Odia, Punjabi). One setting covers both STT and TTS.
- **Voice** - a dropdown of bulbul speakers grouped and labeled by gender.
  When Language is set to Marathi, the assistant automatically adds a
  matching first-person verb-form rule to its system prompt based on the
  voice you pick (feminine or masculine) - no manual prompt editing needed.
  This rule is Marathi-specific grammar and isn't added for other languages.
- **Model source** - **Sarvam Cloud** (just the Sarvam API key) or **Local
  (OpenAI-compatible)** (a base URL, a model name, and an optional API key -
  see [Local models](#local-models-ollama-vllm-lm-studio-self-hosted-sarvam)
  below).
- **Instructions** and **Greeting** - the system prompt and the opening line.
- **Web search** - toggle plus a Tavily API key. When enabled, the assistant
  calls Tavily's search API directly as a tool; no second LLM is used to do
  the searching.
- **Session memory** - a toggle for short-lived, in-memory conversational
  context across reconnects.
- **Home Assistant MCP status** - shows connected/error state and a **Test**
  control. In a normal add-on install this uses the Supervisor token
  automatically; no manual setup is needed.
- **Advanced** (collapsed by default) - turn-detection timing and audio debug
  recording; see below.

### Home Assistant MCP

In a normal Home Assistant add-on install, Vaani uses the Supervisor
token provided by Home Assistant (`homeassistant_api: true`) to reach
`/api/mcp` - there's nothing to configure beyond confirming the **Test**
control shows a healthy tool count. A manual access token is only needed for
custom deployments where the Supervisor token is unavailable.

### Exposed device context and "turn on/off all" requests

At the start of each session, Vaani loads the list of devices you've
exposed to Assist (name, domain, area) into the model's context, cached for
about a minute. This lets you refer to devices naturally - in your configured
language, English, or mixed - without any device name ever being hardcoded in
this add-on's code or prompts. If what you ask for can't be matched to an
exact device, the assistant asks one short clarifying question instead of
silently failing or guessing.

For requests like "turn off all lights" or "turn on everything in the
kitchen," the assistant prefers one domain/area-wide call when turning things
**off** (Home Assistant supports this directly), falls back to one call per
matching device when turning things **on** (Home Assistant has no built-in
"turn everything on" intent), also matches `switch`-domain entities whose name
contains "lamp" or "light", and confirms out loud exactly which devices
changed.

### Local models (Ollama, vLLM, LM Studio, self-hosted Sarvam)

Switch the Model source to **Local (OpenAI-compatible)** and provide:

- **Base URL** - e.g. `http://localhost:11434/v1` for Ollama, or whatever your
  vLLM/LM Studio/SGLang server exposes.
- **Model name** - whatever name your local server registers the model under.
- **API key** (optional) - most local servers don't require one.

This covers:

- **Ollama**, **vLLM**, or **LM Studio** serving any chat-completions model
  they support.
- A **self-hosted Sarvam open-weight model**, served through vLLM or SGLang
  (both explicitly supported per Sarvam's own model cards):
  - [`sarvamai/sarvam-1`](https://huggingface.co/sarvamai/sarvam-1) - 2B
    params, 10 Indic languages; community GGUF quantizations exist.
  - [`sarvamai/sarvam-30b`](https://huggingface.co/sarvamai/sarvam-30b) -
    mixture-of-experts, 2.4B active parameters, Apache 2.0.
  - [`sarvamai/sarvam-105b`](https://huggingface.co/sarvamai/sarvam-105b) -
    mixture-of-experts with multi-head latent attention, Apache 2.0.

  Sarvam's own release notes mention running these on an H100, an L40S, or
  even a MacBook Pro M3, but **Sarvam does not publish a minimum VRAM figure**
  for any of them, so this documentation won't invent one either - check the
  linked model cards and your serving runtime's own hardware guidance.

STT and TTS stay on Sarvam AI regardless of the Model source - Local is a
Model-step-only option. Home Assistant MCP tool calling works the same either
way, and instructions are sent with the standard `system` role in both cases.

### Audio debug captures

Open **Advanced**, enable **Record audio in/out**, save, and run a voice test
or satellite session. The add-on stores separate input and output WAV files
under `/data/audio-debug` and shows download links. Clear the captures after
troubleshooting since they may contain private household audio.

### Home Assistant MCP call history

The add-on keeps an in-memory, recent-calls log of the Home Assistant MCP
tools the assistant has invoked, useful for debugging what it attempted to
do. This is capped and cleared on restart.

### Session memory

Session memory is enabled by default. It keeps the last few messages for a
browser or satellite client for a limited time, so reconnecting doesn't
immediately lose the conversational context. It is in-memory only and clears
on add-on restart.

## Browser voice test

Open the settings UI, confirm Sarvam and Home Assistant MCP both show as
configured/connected, and use **Talk**. Allow microphone access, wait for
**Connected**, then try (for a Marathi setup - swap in your own language):

- "घरातले कुठले डिव्हाइसेस आहेत?" ("What devices are in the house?")
- "दिवाणखान्यातला लाईट लावा." ("Turn on the living room light.")
- "सगळे लाईट बंद करा." ("Turn off all the lights.")

If the browser can't access the microphone, open Home Assistant over HTTPS or
from a trusted local origin (`localhost`/a secure context) - plain HTTP over a
LAN hostname is not enough for microphone access in most browsers.

## Home Assistant Assist bridge

This verifies the custom Home Assistant entities and MCP tools through the
classic STT -> Conversation -> TTS path (not full-duplex WebRTC).

1. Install the **Vaani** custom component (via HACS or by copying
   `custom_components/vaani` into Home Assistant) and restart.
2. Add **Vaani** from **Settings > Devices & services**.
3. Confirm the suggested add-on URL; the integration asks Supervisor for the
   installed add-on and prefills the first reachable URL.
4. In **Settings > Voice assistants**, select **Vaani** for
   Conversation, Speech-to-text, and Text-to-speech.
5. Speak or type a Home Assistant request in Assist and check the add-on logs
   for MCP tool calls and model responses.

## Lovelace WebRTC card

The custom component automatically registers the dashboard card module. In
the default Lovelace storage mode, open a dashboard, select **Add card**, and
choose **Vaani** from **Custom cards**.

If your Lovelace resources are managed in YAML mode:

```yaml
lovelace:
  resources:
    - url: /vaani/vaani-card.js
      type: module
```

```yaml
type: custom:vaani-card
name: Vaani
animation_on_idle: true
compact_mode: false
accent_color: "#206cff"
audio_buffer_ms: 120
```

The card talks to Home Assistant at `/api/vaani/config` and
`/api/vaani/offer`. The custom component proxies those calls to the
add-on and keeps the add-on Ingress token out of dashboard YAML.

`animation_on_idle` keeps the visualizer moving while nobody is speaking;
`compact_mode` hides the transcript; `accent_color` accepts a HEX color;
`audio_buffer_ms` is a browser WebRTC jitter-buffer hint.

## ESPHome satellite

Open **Advanced > ESPHome satellite** and copy the complete WebSocket
endpoint. It contains the satellite secret. Replace its host with the Home
Assistant LAN address if the displayed Ingress host isn't reachable from the
device, then store the URL in ESPHome `secrets.yaml`.

```yaml
external_components:
  - source: github://virajpadte/ha-vaani@main
    components: [va_pipecat]

va_pipecat:
  id: pipecat_va
  url: !secret pipecat_satellite_url
  microphone:
    microphone: processed_microphone
    channels: 0
  speaker: assistant_speaker
  barge_in: true
```

The endpoint uses PCM16 mono at 16 kHz from the device and PCM16 mono at
24 kHz for assistant playback. Full setup, actions, triggers, and lifecycle:
[components/va_pipecat/README.md](../../components/va_pipecat/README.md).

## Standalone Pipecat ESP32

The SmallWebRTC endpoint remains available for standalone `pipecat-esp32`
firmware:

```bash
export PIPECAT_SMALLWEBRTC_URL="http://<ha-lan-ip>:7860/api/offer?token=<satellite-secret>"
```

## Migrating from an older version

Your Sarvam integration's API key, STT/LLM/TTS models, voice, and language,
and your flow's custom instructions and greeting, all carry over
automatically on the first load after upgrading the add-on - nothing to
re-enter. If you're upgrading from a pre-Sarvam-only build, any other
provider you had configured no longer exists in this build and is dropped.

The add-on's own slug (`sarvam_assist`) did **not** change with this rename,
so the add-on itself updates in place with no reinstall needed. The **Home
Assistant integration's domain did change** (it's been `pipecat_assist`,
then `sarvam_assist`, and is now `vaani`), so you will need to:

- Remove the old `Sarvam Assist` (or `Pipecat Assist`) Home Assistant
  integration entry and add **Vaani** once (update any automation/script
  referencing old `sarvam_assist.*` or `pipecat_assist.*` entity IDs to the
  new `vaani.*` ones).
- Update any Lovelace dashboard using `custom:sarvam-assist-card` or
  `custom:pipecat-assist-card` to `custom:vaani-card`.

## Troubleshooting

- **MCP shows an error or `401`**: open the settings page's Home Assistant
  MCP section and select **Test** again; restart the add-on if it persists.
- **Sarvam API errors**: double-check the API key and that the selected
  model/voice names are still valid per
  [Sarvam's docs](https://docs.sarvam.ai/).
- **Browser voice test has no microphone**: use HTTPS or a trusted local
  origin - plain HTTP over a LAN hostname is not a secure context in most
  browsers, so microphone access is blocked.
- **Local model not responding**: confirm the base URL is reachable from
  inside the add-on's container (not just your browser), and that the model
  name matches exactly what your local server has loaded.
- **Settings disappeared after an update**: use **Update**, not
  **Uninstall** followed by reinstalling - Supervisor only wipes the
  add-on's persistent `/data` (your Sarvam API key, voice, language,
  instructions) on an explicit uninstall; a normal update never touches it.
  If you see an add-on identifier like `<hash>_sarvam_assist` in the
  Supervisor log during what looked like a routine update, that's this: a
  full remove-then-reinstall cycle happened rather than an in-place update.
