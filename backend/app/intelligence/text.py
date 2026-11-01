from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3,5}\)?[\s-]?)\d{3,5}[\s-]?\d{4}(?!\d)")),
    ("AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("ACCOUNT", re.compile(r"\b(?:a/c|account|acct|acc)\s*(?:no\.?|number)?\s*[:#-]?\s*\d{6,18}\b", re.IGNORECASE)),
    ("IFSC_ACCOUNT", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("UPI_ID", re.compile(r"\b[\w.-]{2,}@[a-zA-Z]{2,}\b")),
    ("NAME", re.compile(r"\b(?:my name is|name is|this is)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", re.IGNORECASE)),
    ("URL", re.compile(r"https?://\S+", re.IGNORECASE)),
]

REPORTING_PREFIXES = [
    r"today,?\s*",
    r"for me,?\s*",
    r"since the recent update,?\s*",
    r"one issue i noticed is that\s*",
    r"i wanted to share this:?\s*",
    r"i also noticed that\s*",
    r"another thing is that\s*",
    r"on top of that,?\s*",
    r"also,?\s*",
    r"additionally,?\s*",
    r"however,?\s*",
    r"please look into this\.?\s*",
    r"hope this can be improved\.?\s*",
    r"this is frustrating\.?\s*",
]

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those",
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does", "did", "doing",
    "i", "me", "my", "we", "our", "you", "your", "it", "its", "they", "their", "them",
    "to", "of", "in", "on", "at", "for", "with", "from", "by", "as", "about", "into",
    "not", "no", "can", "cannot", "cant", "could", "would", "should", "will", "shall",
    "have", "has", "had", "also", "very", "too", "so", "just", "when", "while", "because",
    "app", "application", "banking", "bank", "customer", "please", "get", "got", "seems",
}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u200b", "").replace("\xa0", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def redact_pii(text: str) -> tuple[str, list[str]]:
    redacted = normalize_text(text)
    found: list[str] = []
    for label, pattern in PII_PATTERNS:
        if pattern.search(redacted):
            found.append(label)
            redacted = pattern.sub(f"[{label}]", redacted)
    # Redact long bare digit sequences that were not caught by specific rules.
    def long_digits(match: re.Match[str]) -> str:
        value = re.sub(r"\D", "", match.group(0))
        if len(value) >= 9:
            found.append("NUMBER")
            return "[NUMBER]"
        return match.group(0)

    redacted = re.sub(r"(?<!\w)\d[\d\s-]{8,}\d(?!\w)", long_digits, redacted)
    return normalize_text(redacted), sorted(set(found))


@dataclass(frozen=True)
class Span:
    text: str
    start: int
    end: int


CLAUSE_BOUNDARY = re.compile(
    r"(?:[.!?]+(?=\s|$)|;+|\s+(?:but|although|however|whereas|while)\s+|\s+(?:also|additionally)\s+"
    r"|\s+on top of that,?\s+|\s+another thing is that\s+)",
    re.IGNORECASE,
)


def _spans_from_boundaries(text: str, pattern: re.Pattern[str], min_chars: int = 2) -> list[Span]:
    spans: list[Span] = []
    cursor = 0
    for match in pattern.finditer(text):
        piece = text[cursor : match.start()].strip()
        if len(piece) >= min_chars:
            start = text.find(piece, cursor)
            spans.append(Span(text=piece, start=start, end=start + len(piece)))
        cursor = match.end()
    tail = text[cursor:].strip()
    if len(tail) >= min_chars:
        start = text.find(tail, cursor)
        spans.append(Span(text=tail, start=start, end=start + len(tail)))
    return spans or ([Span(text=text.strip(), start=0, end=len(text.strip()))] if text.strip() else [])


def split_sentences(text: str) -> list[Span]:
    sentence_boundary = re.compile(r"(?:[.!?]+(?=\s|$)|;+)")
    return _spans_from_boundaries(text, sentence_boundary, min_chars=2)


def split_clauses(sentence: str, offset: int = 0) -> list[Span]:
    spans = _spans_from_boundaries(sentence, CLAUSE_BOUNDARY, min_chars=8)
    return [Span(text=s.text, start=s.start + offset, end=s.end + offset) for s in spans]


def clean_clause(text: str) -> str:
    value = normalize_text(text)
    changed = True
    while changed:
        changed = False
        for prefix in REPORTING_PREFIXES:
            new_value = re.sub(rf"^(?:{prefix})", "", value, flags=re.IGNORECASE).strip()
            if new_value != value:
                value = new_value
                changed = True
    return value.strip(" :-")


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9'-]*", (text or "").lower())
        if token not in STOPWORDS and len(token) > 2
    ]


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def to_neutral_statement(text: str) -> str:
    value = clean_clause(text)
    replacements = [
        (r"\bI cannot\b", "Customer cannot"),
        (r"\bI can't\b", "Customer cannot"),
        (r"\bI am unable to\b", "Customer is unable to"),
        (r"\bI'm unable to\b", "Customer is unable to"),
        (r"\bI could not\b", "Customer could not"),
        (r"\bI couldn't\b", "Customer could not"),
        (r"\bI have to\b", "Customer has to"),
        (r"\bI had to\b", "Customer had to"),
        (r"\bI keep\b", "Customer keeps"),
        (r"\bI received\b", "Customer received"),
        (r"\bI see\b", "Customer sees"),
        (r"\bI notice\b", "Customer notices"),
        (r"\bI noticed\b", "Customer noticed"),
        (r"\bI entered\b", "Customer entered"),
        (r"\bI opted\b", "Customer opted"),
        (r"\bI accidentally\b", "Customer accidentally"),
        (r"\bI reported\b", "Customer reported"),
        (r"\bI raised\b", "Customer raised"),
        (r"\bI requested\b", "Customer requested"),
        (r"\bI tried\b", "Customer tried"),
        (r"\bI face\b", "Customer faces"),
        (r"\bI want\b", "Customer wants"),
        (r"\bI wanted\b", "Customer wanted"),
        (r"\bI need\b", "Customer needs"),
        (r"\bI expect\b", "Customer expects"),
        (r"\bI expected\b", "Customer expected"),
        (r"\bI was\b", "Customer was"),
        (r"\bI were\b", "Customer were"),
        (r"\bI will\b", "Customer will"),
        (r"\bI would\b", "Customer would"),
        (r"\bI should\b", "Customer should"),
        (r"\bI was given\b", "Customer was given"),
        (r"\bI like\b", "Customer likes"),
        (r"\bI am\b", "Customer is"),
        (r"\bI'm\b", "Customer is"),
        (r"\bI've\b", "Customer has"),
        (r"\bI\b", "Customer"),
        (r"\bmy\b", "their"),
        (r"\bMy\b", "Their"),
        (r"\bme\b", "them"),
        (r"\bwe\b", "customers"),
        (r"\bour\b", "their"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    value = value.replace("Customer Customer", "Customer")
    value = re.sub(r"\bthe app\b", "the app", value, flags=re.IGNORECASE)
    if value:
        value = value[0].upper() + value[1:]
    return value[:280].strip()


def sentence_case(value: str) -> str:
    value = (value or "").strip()
    return value[0].upper() + value[1:] if value else value
