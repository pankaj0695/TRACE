import re

_WORD = re.compile(r"[a-z']+")
TOKEN = re.compile(r"[a-z]{4,}")
_SUPERLATIVE = re.compile(
    r"\b(love|great|perfect|excellent|awesome|amazing|beautiful|best|recommend|exceeded|expectations|"
    r"well made|good quality|high quality|five stars|5 stars|as described|worth)\b"
)


def word_count(text: str) -> int:
    return len(_WORD.findall(text.lower()))


def is_generic(text: str, vocab: set[str] | None = None) -> bool:
    """Low-information or short superlative text; with `vocab`, product-specific wording clears the flag."""
    words = word_count(text)
    if words < 6:
        return True
    lowered = text.lower()
    specific = bool(vocab and set(TOKEN.findall(lowered)) & vocab)
    return words < 20 and bool(_SUPERLATIVE.search(lowered)) and not specific
