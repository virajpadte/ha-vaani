"""Sarvam AI's supported languages for this add-on's fixed STT -> LLM -> TTS pipeline.

One "language" setting covers both STT and TTS, so the list here is the intersection of
what each supports - verified against Sarvam's own API references, not guessed:

- Text-to-Speech (docs.sarvam.ai .../text-to-speech/convert, "target_language_code"
  allowed values): bn-IN, en-IN, gu-IN, hi-IN, kn-IN, ml-IN, mr-IN, od-IN, pa-IN, ta-IN,
  te-IN - 11 languages.
- Speech-to-Text (docs.sarvam.ai .../speech-to-text/transcribe, "language_code" allowed
  values) accepts a larger set (also as-IN, ur-IN, ne-IN, kok-IN, ks-IN, sd-IN, sa-IN,
  sat-IN, mni-IN, brx-IN, mai-IN, doi-IN, plus "unknown" for auto-detect) - every TTS
  language above is also accepted by STT, so TTS's smaller list is the safe, always-valid
  choice for a single round-trip voice setting. Picking an STT-only code here would
  transcribe fine but fail TTS synthesis entirely (the same class of bug as a TTS
  voice/model mismatch - see app/sarvam_voices.py).
"""

from __future__ import annotations

SARVAM_LANGUAGES = [
    {"code": "bn-IN", "label": "Bengali"},
    {"code": "en-IN", "label": "English"},
    {"code": "gu-IN", "label": "Gujarati"},
    {"code": "hi-IN", "label": "Hindi"},
    {"code": "kn-IN", "label": "Kannada"},
    {"code": "ml-IN", "label": "Malayalam"},
    {"code": "mr-IN", "label": "Marathi"},
    {"code": "od-IN", "label": "Odia"},
    {"code": "pa-IN", "label": "Punjabi"},
    {"code": "ta-IN", "label": "Tamil"},
    {"code": "te-IN", "label": "Telugu"},
]

SARVAM_LANGUAGE_CODES = {item["code"] for item in SARVAM_LANGUAGES}
