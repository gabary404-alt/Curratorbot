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

LIVE_CAPABILITIES = {
    "rw": "Twaganira mu Kinyarwanda cyangwa mu Cyongereza. Nshobora kugusobanurira ibintu no kugushakira amakuru.",
    "en": "We can talk in English or Kinyarwanda. I can explain things, work through a question with you, or look up information.",
}

SMALL_TALK = {
    "rw": {
        "likes": "Nkunda ibiganiro nk'ibi! Ni iki wowe ukunda kuganiraho?",
        "mind": "Niteguye kukumva. Ni iki ushaka ko tuganiraho?",
    },
    "en": {
        "likes": "I enjoy helping people figure things out. What do you like talking about?",
        "mind": "I'm curious about what brought you here. What's on your mind today?",
    },
}

FIXED_VOICE_REPLIES = set(LIVE_CAPABILITIES.values()) | {
    replies[intent] for replies in REPLIES.values() for intent in ("hello", "name", "thanks")
} | {line for replies in SMALL_TALK.values() for line in replies.values()}


def quick_reply(text: str, language: str) -> tuple[str, Language] | None:
    """Answer standalone greetings, thanks, and introductions without a network call."""
    normalized = " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))
    phrases = {
        "rw": {
            "hello": ("muraho", "muraho neza", "mwaramutse", "mwiriwe"),
            "name": ("witwa nde", "muraho witwa nde", "muraho neza witwa nde"),
            "thanks": ("urakoze", "murakoze", "murakoze cyane"),
            "can": ("ushobora gukora iki", "ni iki ushobora gukora"),
            "likes": ("ukunda iki", "ukunda iki se", "ni iki ukunda"),
            "mind": ("uratekereza iki", "utekereza iki"),
        },
        "en": {
            "hello": ("hello", "hi", "hey"),
            "name": ("what s your name", "what is your name", "who are you"),
            "thanks": ("thanks", "thank you", "thank you very much"),
            "can": ("what can you do", "what can you help me with"),
            "likes": ("what do you like", "what do you enjoy"),
            "mind": ("what s on your mind", "whats on your mind", "what is on your mind"),
        },
    }
    for selected in ("rw", "en"):
        if language not in ("auto", selected):
            continue
        for intent, variants in phrases[selected].items():
            greetings = ("hello", "hey", "hi") if selected == "en" else ("muraho neza", "muraho")
            message = normalized
            for greeting in greetings:
                if message.startswith(greeting + " "):
                    message = message[len(greeting) + 1:]
                    break
            if normalized in variants or message in variants:
                if intent in SMALL_TALK[selected]:
                    return SMALL_TALK[selected][intent], selected
                if intent == "can":
                    return LIVE_CAPABILITIES[selected], selected
                return REPLIES[selected][intent], selected
    return None


def rehearsal_reply(text: str, language: Language) -> str:
    normalized = " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))
    for intent in ("name", "can", "thanks", "hello"):
        if any(f" {phrase} " in f" {normalized} " for phrase in INTENTS[language][intent]):
            return REPLIES[language][intent]
    return REPLIES[language]["fallback"]
