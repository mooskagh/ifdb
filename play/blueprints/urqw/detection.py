import re

SUPPORTED_EXTENSIONS = frozenset((".qst", ".qs1", ".qs2", ".qsz"))

_FIREURQ_VARS = re.compile(
    r"\b(textpane_\w+|screen_\w+|hide_btn_echo|dosurq_count)\b",
    re.IGNORECASE,
)
_FIREURQ_DECORATORS = re.compile(
    r"\{(?:color:[^}]+|img:[^}]+|font:[^}]+|size:[^}]+|align:[^}]+|/?b|/?i|/?u)\}",
    re.IGNORECASE,
)
_WIKI_LINK = re.compile(r"\[\[[^\]]+\|[^\]]+\]\]")
_HTML_TAGS = re.compile(
    r"<a\s+href=[\"']btn:|<(?:font|table|span|div|b|i|u|center)\b",
    re.IGNORECASE,
)
_COUNT_VAR = re.compile(r"\bcount_[a-zA-Zа-яА-Я0-9_]+\b", re.IGNORECASE)
_LABEL_DEF = re.compile(r"^\s*:([a-zA-Zа-яА-Я0-9_]+)", re.MULTILINE)


def detect_encoding(data: bytes) -> str:
    """Detect whether quest bytes are UTF-8 or CP1251 (or CP866)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "UTF-8"

    try:
        data.decode("utf-8")
        if any(b > 127 for b in data):
            return "UTF-8"
    except UnicodeDecodeError:
        pass

    # Compare CP1251 vs CP866 vowel frequency
    # In CP1251: 'а', 'е', 'и', 'о' are 0xe0, 0xe5, 0xe8, 0xee
    # In CP866: 'а', 'е', 'и', 'о' are 0xa0, 0xa5, 0xa8, 0xae
    c1251_vowels = sum(1 for byte in data if byte in (0xE0, 0xE5, 0xE8, 0xEE))
    c866_vowels = sum(1 for byte in data if byte in (0xA0, 0xA5, 0xA8, 0xAE))

    if c866_vowels > c1251_vowels and c866_vowels > 0:
        return "CP866"

    return "CP1251"


def detect_urq_mode(
    content: str | bytes | None = None,
    tags: list[str] | None = None,
) -> tuple[str, bool]:
    """Detect the URQ flavor/mode and whether this is a FireURQ game.

    Returns:
        tuple of (urq_mode, is_fireurq) where urq_mode is one of:
        'urqw', 'ripurq', 'dosurq', 'akurq'.
    """
    text_content: str | None
    if isinstance(content, bytes):
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            text_content = content.decode("cp1251", "replace")
    else:
        text_content = content

    if tags:
        lower_tags = [t.lower() for t in tags]
        if any("fire" in t for t in lower_tags):
            return "akurq", True
        if any("rip" in t for t in lower_tags):
            return "ripurq", False
        if any("dos" in t for t in lower_tags):
            return "dosurq", False
        if any("ak" in t for t in lower_tags):
            return "akurq", False
        if any("urqw" in t for t in lower_tags):
            return "urqw", False

    if text_content:
        content_lower = text_content.lower()

        # Check explicit runtime environment detections
        if "urqw_version" in content_lower:
            return "urqw", False
        if "urq_type" in content_lower:
            return "akurq", False
        if "urq_delay" in content_lower:
            return "dosurq", False
        if (
            _FIREURQ_VARS.search(text_content)
            or _FIREURQ_DECORATORS.search(text_content)
            or "fireurq" in content_lower
        ):
            return "akurq", True

        # UrqW wiki-links
        if _WIKI_LINK.search(text_content):
            return "urqw", False

        # AkURQ HTML constructs
        if _HTML_TAGS.search(text_content):
            return "akurq", False

        # DOS / AkURQ count_<label> counters
        if _COUNT_VAR.search(text_content):
            return "dosurq", False

        # RipURQ label-as-counter checks (e.g. `if loc1 = 1`)
        labels = set(_LABEL_DEF.findall(text_content))
        for lbl in labels:
            if len(lbl) <= 1 or lbl.isdigit():
                continue
            if re.search(r"\bif\s+" + re.escape(lbl) + r"\b", content_lower):
                return "ripurq", False

    return "urqw", False
