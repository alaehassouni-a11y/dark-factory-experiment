"""The supported languages, their voices, and detection.

MISSION hard invariant 1: the supported set is exactly French, English, German and Arabic.
This module is the ONE definition of that set. Detection, greetings, the no-answer phrase
and the voice locales all derive from it here, so there is nothing elsewhere to drift.

Detection is deterministic and local: Arabic by script, the three Latin-script languages
by function words. It returns None rather than guessing when the evidence is not there,
because a wrong language spoken aloud is worse than a question.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"fr", "en", "de", "ar"})

LANGUAGE_NAMES: dict[str, str] = {
    "fr": "French",
    "en": "English",
    "de": "German",
    "ar": "Arabic",
}

VOICE_LOCALES: dict[str, str] = {
    "fr": "fr-FR",
    "en": "en-US",
    "de": "de-DE",
    "ar": "ar-SA",
}

# What the agent says to open a session, per language. The greeting is a question.
GREETINGS: dict[str, str] = {
    "fr": "Bonjour, comment puis-je vous aider ?",
    "en": "Hello, how can I help you today?",
    "de": "Hallo, wie kann ich Ihnen helfen?",
    "ar": "مرحبا، كيف يمكنني مساعدتك؟",
}

# What the agent says when neither the wiki nor the web had an answer.
NO_ANSWER_TEXTS: dict[str, str] = {
    "fr": "Je suis désolé, je n'ai pas trouvé de réponse à cette question.",
    "en": "I'm sorry, I could not find an answer to that question.",
    "de": "Es tut mir leid, ich konnte keine Antwort auf diese Frage finden.",
    "ar": "أنا آسف، لم أتمكن من العثور على إجابة لهذا السؤال.",
}

# What the agent asks when it cannot tell which language the client is using.
ASK_LANGUAGE_TEXT: str = (
    "I'm sorry, I did not understand. Could you please continue in French, English, "
    "German or Arabic?"
)

_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# Function words that are distinctive for each language. Words shared between two of the
# languages are deliberately absent so they cannot vote for the wrong one.
_FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        """the is are was were what how where when why which who do does did can could
        i you my your our and of to for with this that it please hello hi thanks thank
        would like need want have has be not about we they there from yes some any
        should will shall am into his her their them us tell painted""".split()
    ),
    "fr": frozenset(
        """le la les un une est sont je tu il elle nous vous ils elles que qui quoi
        comment où quand pourquoi pour avec dans sur pas ne mon ma mes votre vos bonjour
        merci oui ce cette ces du et ou à au aux plaît puis peux voudrais besoin faire avez
        être très aussi quel quelle quels quelles""".split()
    ),
    "de": frozenset(
        """der das ein eine ist sind ich du er sie wir ihr was wie wo wann warum für mit
        auf nicht mein meine ihre hallo danke ja nein und oder zu von bitte kann können
        möchte brauche haben habe sein sehr auch bei nach aus dem den einen einem welche
        welcher welches wer hat""".split()
    ),
}

_DIACRITIC_HINTS: dict[str, str] = {
    "fr": "éèêëçàâùûîôœ",
    "de": "ßäöü",
}


@dataclass(frozen=True)
class Detection:
    language: str
    confidence: float


def _strip_diacritics(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    """Lower-cased words, diacritics stripped for Latin script, Arabic kept intact."""
    out: list[str] = []
    for w in _WORD.findall(text.lower()):
        out.append(w if _ARABIC.search(w) else _strip_diacritics(w))
    return out


def detect(text: str) -> Detection | None:
    """Return the supported language the text is most likely in, or None.

    None means "no evidence for any of the four", never "probably English".
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    arabic = sum(1 for c in letters if _ARABIC.match(c))
    ratio = arabic / len(letters)
    if ratio >= 0.3:
        return Detection("ar", round(min(1.0, ratio), 2))

    raw_words = _WORD.findall(text.lower())
    if not raw_words:
        return None
    scores: dict[str, float] = {"en": 0.0, "fr": 0.0, "de": 0.0}
    for w in raw_words:
        bare = _strip_diacritics(w)
        for code, words in _FUNCTION_WORDS.items():
            if w in words or bare in words:
                scores[code] += 1.0
        for code, hints in _DIACRITIC_HINTS.items():
            if any(c in hints for c in w):
                scores[code] += 0.5

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    second_score = ranked[1][1]
    # At least one whole function word: a diacritic alone is a hint, never evidence.
    if best_score < 1.0 or best_score == second_score:
        return None
    confidence = min(1.0, best_score / len(raw_words))
    return Detection(best, round(max(confidence, 0.2), 2))


def voice_locale(language: str) -> str:
    return VOICE_LOCALES[language]


def supported_languages_payload() -> list[dict[str, str]]:
    return [
        {"code": code, "name": LANGUAGE_NAMES[code], "voice_locale": VOICE_LOCALES[code]}
        for code in sorted(SUPPORTED_LANGUAGES)
    ]
