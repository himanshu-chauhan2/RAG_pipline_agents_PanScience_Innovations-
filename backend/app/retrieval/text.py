import re

STOPWORDS = frozenset(
    "a an and are as at be by can could do does for from has have how i if in is it its "
    "me my of on or our so than that the their them then there these this to was we what "
    "when where which who will with would you your am any about into must should".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def normalize(text: str) -> str:
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return [
        token.rstrip("s") if len(token) > 3 and not token[0].isdigit() else token
        for token in _TOKEN.findall(text.lower())
        if token not in STOPWORDS
    ]


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE.split(normalize(text)) if part.strip()]


def is_verbatim(quote: str, source: str) -> bool:
    candidate = normalize(quote).strip(" \"'")
    return len(candidate) >= 8 and candidate.casefold() in normalize(source).casefold()
