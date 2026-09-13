from collections.abc import Iterable
from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset((".qsp", ".aqsp", ".qsps"))
LEGACY_EXTENSIONS = frozenset((".gam",))
ALL_QSP_EXTENSIONS = SUPPORTED_EXTENSIONS | LEGACY_EXTENSIONS

_TADS2_HEADER = b"TADS2 bin\n\r\x1a\x00"
_UTF16LE_QSP_HEADER = b"Q\x00S\x00P\x00G\x00A\x00M\x00E\x00\r\x00\n\x00"
_ASCII_QSP_HEADER = b"QSPGAME\r\n"

_IGNORED_ROOTS = frozenset(("__MACOSX",))
_IGNORED_NAMES = frozenset((".DS_Store",))
_IGNORED_SUBDIRS = frozenset(("libs", "modules", "data", "mod", "mods"))


def split_clean_parts(member: str) -> list[str]:
    return [p for p in member.replace("\\", "/").split("/") if p and p != "."]


def is_ignored(parts: list[str]) -> bool:
    if not parts:
        return True
    if parts[0] in _IGNORED_ROOTS:
        return True
    if parts[0] in _IGNORED_NAMES or parts[-1] in _IGNORED_NAMES:
        return True
    if parts[-1].startswith("._"):
        return True
    return False


def is_tads2_header(data: bytes) -> bool:
    return data.startswith(_TADS2_HEADER)


def is_qsp_header(data: bytes) -> bool:
    if data.startswith(_UTF16LE_QSP_HEADER) or data.startswith(
        _ASCII_QSP_HEADER
    ):
        return True
    sample = data[:128]
    if b"Ij\r\n" in sample or b"\r\nIj\r\n" in sample:
        return True
    return False


def detect_qsp_mode(
    game_file: Path | None = None,
    members: Iterable[str] | None = None,
    tags: list[str] | None = None,
) -> str:
    if tags:
        lower_tags = [t.lower() for t in tags]
        if any("aero" in t for t in lower_tags):
            return "aero"

    if game_file and game_file.suffix.lower() == ".aqsp":
        return "aero"

    if members:
        for m in members:
            parts = split_clean_parts(m)
            if is_ignored(parts):
                continue
            name_lower = parts[-1].lower()
            if name_lower == "config.xml" or name_lower.endswith(".aqsp"):
                return "aero"

    return "classic"


def find_primary_qsp_file(
    candidates: list[str], preferred_stem: str | None = None
) -> str | None:
    valid_candidates: list[str] = []
    for c in candidates:
        parts = split_clean_parts(c)
        if is_ignored(parts):
            continue
        valid_candidates.append(c)

    if not valid_candidates:
        return None

    if len(valid_candidates) == 1:
        return valid_candidates[0]

    normalized_preferred = (
        preferred_stem.lower().strip() if preferred_stem else None
    )

    def candidate_score(item: str) -> tuple[int, int, int, int, int]:
        parts = split_clean_parts(item)
        filename = parts[-1].lower()
        stem = Path(filename).stem

        # Priority 1: Exact match with preferred stem
        stem_match = (
            0 if normalized_preferred and stem == normalized_preferred else 1
        )

        # Priority 2: Penalize test or backup files
        is_secondary = (
            1
            if any(
                tag in filename
                for tag in ("test", "old", "bak", "backup", "copy")
            )
            else 0
        )

        # Priority 3: Penalize files placed in known library / mod directories
        in_library_dir = (
            1
            if any(part.lower() in _IGNORED_SUBDIRS for part in parts[:-1])
            else 0
        )

        # Priority 4: Depth (shallower paths preferred)
        depth = len(parts)

        # Priority 5: Extension preference (.qsp > .aqsp > .qsps > .gam)
        ext = Path(filename).suffix
        ext_rank = {".qsp": 0, ".aqsp": 1, ".qsps": 2, ".gam": 3}.get(ext, 4)

        return (stem_match, is_secondary, in_library_dir, depth, ext_rank)

    valid_candidates.sort(key=candidate_score)
    return valid_candidates[0]
