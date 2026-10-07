<p align="center">
  <img src="logo.png" alt="Vaani" width="320">
</p>

# Vaani

Vaani runs a fixed, Indic-language realtime voice pipeline inside Home
Assistant: **Sarvam STT -> Model -> Home Assistant tools -> Sarvam TTS**, with
optional session memory and web search. It connects to Home Assistant MCP
automatically through the Supervisor, serves a settings UI through Ingress,
and exposes WebRTC and ESPHome satellite transports.

This is a focused, Sarvam-only fork of the original multi-provider
[Pipecat Assist](https://github.com/kyvaith/pipecat-homeassistant) project -
there is no provider picker and no visual pipeline builder here, by design.

> **Heads up: install/update is slow, and that's expected.** No pre-built
> image is published, so this builds from source on your own hardware every
> time - typically 5-10 minutes on x86, 15-20+ minutes on a Raspberry Pi or
> other ARM device. Click into the install progress to watch the live build
> log; it's staged with `[1/4]`-`[4/4]` markers so you can see it's actually
> working, not stuck.

Open the settings UI after starting the add-on:

- Paste your Sarvam API key, pick a language from the dropdown (English plus
  10 Indic languages), and pick a voice (grouped by gender - for Marathi, a
  matching verb-form system rule is applied automatically).
- Choose the Model source: **Sarvam Cloud** (default) or **Local
  (OpenAI-compatible)** for Ollama, vLLM, LM Studio, or a self-hosted Sarvam
  open-weight model.
- Confirm Home Assistant MCP shows connected (it uses the Supervisor
  connection automatically - no separate MCP add-on needed).
- Optionally enable **Web search** (a Tavily API key) and **Session memory**.
- Use the **Talk** button to try the live pipeline right from the browser.

For setup, migration notes, and troubleshooting, see `DOCS.md`.
