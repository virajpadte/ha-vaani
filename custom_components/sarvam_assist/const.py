"""Constants for Sarvam Assist."""

DOMAIN = "sarvam_assist"
VERSION = "0.1.80"
CONF_URL = "url"
CONF_TOKEN = "token"
CONF_FLOW_ID = "flow_id"
DEFAULT_URL = "http://127.0.0.1:7860"
DEFAULT_LANGUAGE = "en-IN"
# Sarvam's actual supported languages for this add-on's STT/TTS pipeline - verified
# against docs.sarvam.ai's Text-to-Speech API reference (the limiting factor, since
# Speech-to-Text accepts a larger set); kept in sync with
# addons/pipecat_assist/app/sarvam_languages.py.
SUPPORTED_LANGUAGES = [
    "bn-IN",
    "en-IN",
    "gu-IN",
    "hi-IN",
    "kn-IN",
    "ml-IN",
    "mr-IN",
    "od-IN",
    "pa-IN",
    "ta-IN",
    "te-IN",
]
