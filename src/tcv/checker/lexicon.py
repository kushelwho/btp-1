"""Word lists for the router's lexical pre-pass and for modality.

Pure code, versioned: the version is recorded with every run, because
changing a pattern changes which claims skip the model router.

These are *candidate* detectors. A lexical hit is a strong hint, not a
verdict — the router model confirms ambiguous cases, and router accuracy is
measured against human labels rather than assumed.
"""

from __future__ import annotations

import re

from tcv.schemas import Modality, Operator

LEXICON_VERSION = "lex-v2"  # v2: cues missed on the first pilot draft (contrast/similarity/each/class counts)

_NUM = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)"
_NUM_WORDS_2UP = r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
# Plural nouns naming *kinds of work* — a count or generalisation over these
# ranges over papers ("three designs", "recent frameworks"), unlike a count of
# parts inside one system ("three agents", "two metrics").
_WORKS = r"(?:frameworks|methods|systems|approaches|works|studies|papers|pipelines)"
_KINDS = (r"(?:approaches|frameworks|designs|architectures|families|categories|types|strategies|paradigms|"
          r"mechanisms|methods|systems|lines of work|classes|kinds|schools)")

DISCOURSE_MARKERS = tuple(re.compile(p, re.I) for p in (
    r"^(?:we|this section|the following|next|finally|in (?:this|the next) section)\b",
    r"\bturns? to\b",
    r"^in summary\b",
    r"\bto (?:summari[sz]e|conclude)\b",
    r"^(?:the remainder of|the rest of) this\b",
))

# Checked in order; the first match wins. COUNT precedes PROPORTION so that
# "two of the five" is a count rather than a vague proportion.
AGGREGATIVE_MARKERS: tuple[tuple[Operator, re.Pattern], ...] = tuple(
    (op, re.compile(p, re.I)) for op, p in (
        (Operator.COUNT, rf"\b{_NUM} (?:out )?of (?:the )?(?:\w+ ){{0,2}}{_NUM}\b|"
                         rf"\b{_NUM_WORDS_2UP} (?:[\w-]+ ){{0,2}}{_KINDS}\b"),
        (Operator.CONTRAST, r"\b(?:unlike|in contrast|by contrast|whereas|as opposed to|conversely|"
                            r"on the other hand|differ(?:s|ed)?(?: \w+ly)? (?:in|from|on))\b"),
        (Operator.TREND, r"\b(?:trend|increasingly|decreasingly|over time|has (?:grown|shifted|moved)|"
                         r"from (?:19|20)\d\d to (?:19|20)\d\d)\b"),
        (Operator.COMPARISON, r"\b(?:outperform\w*|better than|worse than|exceed\w*|higher than|lower than|"
                              r"more \w+ than|less \w+ than|similarly|likewise|in the same way|"
                              r"compared (?:to|with))\b"),
        (Operator.UNIVERSAL, r"\b(?:all (?:of )?(?:the )?(?:\w+ )?(?:frameworks|methods|systems|approaches|papers|"
                             r"studies|models|works)|every|none of|no (?:\w+ )?(?:framework|method|system|approach|"
                             r"paper|study|work)s?\b|consistently|always|never|without exception|"
                             r"each (?:[\w-]+ )?(?:framework|method|system|approach|paper|study|work)|"
                             rf"(?:recent|early|earlier|existing|prior|current|modern) (?:[\w-]+ ){{0,3}}{_WORKS})\b"),
        (Operator.PROPORTION, r"\b(?:most|many|few|several|the majority|a minority|half) of\b|"
                              rf"\b(?:most|many|few|several) (?:[\w-]+ ){{0,2}}{_WORKS}\b"),
        (Operator.EXISTENTIAL, r"\b(?:at least one|only one|some of)\b"),
    )
)

# Hedges dominate: "may demonstrate" is hedged, not strong.
_HEDGES = re.compile(r"\b(?:may|might|could|possibly|perhaps|suggests?|suggesting|suggested|hints?|"
                     r"appears? to|seems? to)\b", re.I)
MODALITY_LADDER: tuple[tuple[Modality, re.Pattern], ...] = tuple(
    (m, re.compile(p, re.I)) for m, p in (
        (Modality.PROVES, r"\b(?:proves?|proven|definitively|conclusively|undeniably|establish(?:es|ed)? beyond)\b"),
        (Modality.DEMONSTRATES, r"\b(?:demonstrates?|demonstrated|establish(?:es|ed)?|confirms?|confirmed|clearly)\b"),
        (Modality.SHOWS, r"\b(?:shows?|showed|shown|finds?|found|reports?|reported|observes?|observed)\b"),
        (Modality.INDICATES, r"\b(?:indicates?|indicated|points? to|is consistent with)\b"),
    )
)


def is_discourse(text: str) -> bool:
    return any(p.search(text.strip()) for p in DISCOURSE_MARKERS)


def aggregative_operator(text: str) -> Operator | None:
    for op, pattern in AGGREGATIVE_MARKERS:
        if pattern.search(text):
            return op
    return None


def modality(text: str) -> Modality:
    if _HEDGES.search(text):
        return Modality.SUGGESTS
    for m, pattern in MODALITY_LADDER:
        if pattern.search(text):
            return m
    return Modality.NONE
