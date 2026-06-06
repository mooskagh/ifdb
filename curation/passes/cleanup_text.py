"""Small canonical text cleanups for curation drafts."""

import re

from curation.edit import GameEditPass, GameEditState, register_pass


@register_pass
class CleanupTextPass(GameEditPass):
    name = "cleanup_text"

    def apply(self, state: GameEditState, params: dict) -> None:
        if state.current.description is not None:
            state.current.description = cleanup_canonical_text(
                state.current.description
            )


def cleanup_canonical_text(text: str) -> str:
    """Normalize the markdown body of canonical game text."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"^[ *]*\*[ *]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^ +$", "", text, flags=re.MULTILINE)
    text = remove_empty_sections(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + "\n"


def remove_empty_sections(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        level = header_level(line)
        if level is None:
            continue
        next_line = next(
            (candidate for candidate in lines[i + 1 :] if candidate), None
        )
        if next_line is None or next_line == "---":
            lines[i] = ""
            continue
        next_level = header_level(next_line or "")
        if next_level is not None and next_level <= level:
            lines[i] = ""
    return "\n".join(lines)


def header_level(line: str) -> int | None:
    match = re.match(r"^(#+)", line)
    return len(match.group(1)) if match else None
