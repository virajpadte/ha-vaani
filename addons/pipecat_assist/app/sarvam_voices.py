"""Gender of each Sarvam bulbul TTS speaker, and the Marathi verb-form rule that follows
from it.

Genders marked "confirmed" below are stated directly by Sarvam's own docs:

- bulbul:v2 (docs.sarvam.ai .../text-to-speech, speaker list): female = anushka, manisha,
  vidya, arya; male = abhilash, karun, hitesh.
- bulbul:v3 / v3-beta (docs.sarvam.ai .../text-to-speech/best-practices, "Speaker Selection
  by Language" table): 13 of the 37 voices have a gender stated there - male = ratan, shubh,
  ashutosh, rehan, rohan, mani; female = ishita, priya, suhani, neha, roopa, ritu, pooja.

The remaining 24 bulbul:v3 speaker names are not gendered anywhere in Sarvam's docs. Those
below are assigned by standard Indian given-name convention ("inferred") - flagged
separately so a wrong guess is easy to spot and fix.
"""

from __future__ import annotations

# Confirmed directly from Sarvam's documentation.
_CONFIRMED_FEMALE = {
    "anushka", "manisha", "vidya", "arya",  # bulbul:v2
    "ishita", "priya", "suhani", "neha", "roopa", "ritu", "pooja",  # bulbul:v3
}
_CONFIRMED_MALE = {
    "abhilash", "karun", "hitesh",  # bulbul:v2
    "ratan", "shubh", "ashutosh", "rehan", "rohan", "mani",  # bulbul:v3
}

# Inferred from standard Indian given-name convention - not stated by Sarvam's docs.
_INFERRED_FEMALE = {
    "simran", "kavya", "shreya", "tanya", "shruti", "kavitha", "rupali",
}
_INFERRED_MALE = {
    "aditya", "rahul", "amit", "dev", "varun", "manan", "sumit", "kabir", "aayan",
    "advait", "anand", "tarun", "sunny", "gokul", "vijay", "mohit", "soham",
}

FEMALE_SPEAKERS = _CONFIRMED_FEMALE | _INFERRED_FEMALE
MALE_SPEAKERS = _CONFIRMED_MALE | _INFERRED_MALE

_FEMALE_RULE = (
    "You are a woman; use feminine first-person Marathi verb forms (करते, शकते, सांगते, "
    "आले, केले), never masculine (करतो, शकतो, आलो). Verbs that agree with an object (e.g. "
    "'light बंद केला') stay as they are."
)
_MALE_RULE = (
    "You are a man; use masculine first-person Marathi verb forms (करतो, शकतो, सांगतो, "
    "आलो, केला), never feminine (करते, शकते, आले). Verbs that agree with an object (e.g. "
    "'light बंद केला') stay as they are."
)


def speaker_gender(voice: str) -> str | None:
    """Return "female", "male", or None for an unrecognized speaker name."""

    name = (voice or "").strip().lower()
    if not name:
        return None
    if name in FEMALE_SPEAKERS:
        return "female"
    if name in MALE_SPEAKERS:
        return "male"
    return None


def gender_instruction(voice: str) -> str:
    """Return the Marathi first-person verb-form rule for a speaker, or "" if unknown."""

    gender = speaker_gender(voice)
    if gender == "female":
        return _FEMALE_RULE
    if gender == "male":
        return _MALE_RULE
    return ""
