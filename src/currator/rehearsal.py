"""Prepared answers for rehearsing speech and playback without Gemini."""
from __future__ import annotations

import re
import unicodedata

from .models import Language

REPLIES = {
    "rw": {
        "hello": "Muraho neza! Nishimiye kuganira nawe.",
        "name": "Nitwa Nshuti. Ndi roboti ishobora kuganira nawe mu Kinyarwanda no mu Cyongereza.",
        "can": "Ubu ndi mu myitozo. Nshobora kumva no kuvuga mu Kinyarwanda.",
        "thanks": "Urakoze nawe!",
        "fallback": "Ubu ndi mu myitozo. Gerageza kumbaza uti: Witwa nde?",
    },
    "en": {
        "hello": "Hello! I'm glad to meet you.",
        "name": "My name is Nshuti. I'm a robot assistant for Kinyarwanda and English.",
        "can": "I'm in rehearsal mode. You can ask my name, greet me, or ask what I can do.",
        "thanks": "You're welcome!",
        "fallback": "I'm using prepared answers for this rehearsal. Try asking, What's your name?",
    },
}
INTENTS = {
    "rw": {"hello": ("muraho", "mwaramutse", "mwiriwe"), "name": ("witwa nde",),
           "can": ("ukora iki", "ushobora gukora iki"), "thanks": ("urakoze", "murakoze")},
    "en": {"hello": ("hello", "hi", "hey"), "name": ("your name", "who are you"),
           "can": ("what can you do",), "thanks": ("thank you", "thanks")},
}


def quick_reply(text: str, language: str) -> tuple[str, Language] | None:
    """Answer standalone greetings, thanks, and introductions without a network call."""
    normalized = " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))
    phrases = {
        "rw": {
            "hello": ("muraho", "muraho neza", "mwaramutse", "mwiriwe"),
            "name": ("witwa nde", "muraho witwa nde", "muraho neza witwa nde"),
            "thanks": ("urakoze", "murakoze", "murakoze cyane"),
        },
        "en": {
            "hello": ("hello", "hi", "hey"),
            "name": ("what s your name", "what is your name", "who are you"),
            "thanks": ("thanks", "thank you", "thank you very much"),
        },
    }
    for selected in ("rw", "en"):
        if language not in ("auto", selected):
            continue
        for intent, variants in phrases[selected].items():
            if normalized in variants:
                return REPLIES[selected][intent], selected
    return None


def rehearsal_reply(text: str, language: Language) -> str:
    normalized = " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))
    for intent in ("name", "can", "thanks", "hello"):
        if any(f" {phrase} " in f" {normalized} " for phrase in INTENTS[language][intent]):
            return REPLIES[language][intent]
    return REPLIES[language]["fallback"]
