<p align="center">
  <img src="logo.png" alt="Sarvam Assist" width="320">
</p>

# Sarvam Assist

Sarvam Assist runs a fixed, Marathi- and Indic-language-first realtime voice
pipeline inside Home Assistant: **Sarvam STT -> Model -> Home Assistant tools
-> Sarvam TTS**, with optional session memory and web search. It connects to
Home Assistant MCP automatically through the Supervisor, serves a settings UI
through Ingress, and exposes WebRTC and ESPHome satellite transports.

This is a focused, Sarvam-only fork of the original multi-provider
[Pipecat Assist](https://github.com/kyvaith/pipecat-homeassistant) project -
there is no provider picker and no visual pipeline builder here, by design.

Open the settings UI after starting the add-on:

- Paste your Sarvam API key, pick a voice (grouped by gender - a matching
  Marathi verb-form system rule is applied automatically) and language.
- Choose the Model source: **Sarvam Cloud** (default) or **Local
  (OpenAI-compatible)** for Ollama, vLLM, LM Studio, or a self-hosted Sarvam
  open-weight model.
- Confirm Home Assistant MCP shows connected (it uses the Supervisor
  connection automatically - no separate MCP add-on needed).
- Optionally enable **Web search** (a Tavily API key) and **Session memory**.
- Use the **Talk** button to try the live pipeline right from the browser.

For setup, migration notes, and troubleshooting, see `DOCS.md`.
