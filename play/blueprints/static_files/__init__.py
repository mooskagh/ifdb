import codecs
import re
import shutil
import tempfile
from pathlib import Path

import charset_normalizer

from core.archives import Archive, ArchiveError, extract_archive, open_archive
from play.blueprint import BlueprintSpec, GenerateSpec

_INDEX_NAMES = frozenset(("index.html", "index.htm"))
_IGNORED_ROOTS = frozenset(("__MACOSX",))
_IGNORED_NAMES = frozenset((".DS_Store",))


def _split_clean_parts(member: str) -> list[str]:
    return [p for p in member.replace("\\", "/").split("/") if p and p != "."]


def _is_ignored(parts: list[str]) -> bool:
    if not parts:
        return True
    if parts[0] in _IGNORED_ROOTS:
        return True
    if parts[0] in _IGNORED_NAMES or parts[-1] in _IGNORED_NAMES:
        return True
    return False


def _is_file_member(member: str) -> bool:
    return not member.endswith("/")


def _is_html_file(name: str) -> bool:
    lower = name.lower()
    return (
        lower.endswith(".html") or lower.endswith(".htm")
    ) and not name.startswith(".")


def find_unpack_target(archive: Archive) -> str | None:
    valid_members: list[tuple[str, list[str]]] = []
    for member in archive.namelist():
        parts = _split_clean_parts(member)
        if _is_ignored(parts):
            continue
        valid_members.append((member, parts))

    for member, parts in valid_members:
        if (
            len(parts) == 1
            and parts[0] in _INDEX_NAMES
            and _is_file_member(member)
        ):
            return ""

    all_html_files = [
        member
        for member, parts in valid_members
        if _is_file_member(member) and _is_html_file(parts[-1])
    ]

    root_html_files = [
        parts[0]
        for member, parts in valid_members
        if len(parts) == 1
        and _is_file_member(member)
        and _is_html_file(parts[0])
    ]
    if len(root_html_files) == 1 and len(all_html_files) == 1:
        return ""

    top_levels: set[str] = {parts[0] for _, parts in valid_members}
    if len(top_levels) != 1:
        return None

    root_dir = next(iter(top_levels))
    for member, parts in valid_members:
        if (
            len(parts) == 2
            and parts[0] == root_dir
            and parts[1] in _INDEX_NAMES
            and _is_file_member(member)
        ):
            return root_dir

    subdir_html_files = [
        parts[1]
        for member, parts in valid_members
        if len(parts) == 2
        and parts[0] == root_dir
        and _is_file_member(member)
        and _is_html_file(parts[1])
    ]
    if len(subdir_html_files) == 1 and len(all_html_files) == 1:
        return root_dir

    return None


def get_spec() -> BlueprintSpec:
    return BlueprintSpec(name="Static files", versions=["1"])


def accepts(filename: Path) -> bool:
    try:
        with open_archive(filename) as archive:
            return find_unpack_target(archive) is not None
    except (ArchiveError, OSError):
        return False


def _publish(stage: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    stage.rename(destination)


_TEXT_EXTENSIONS = frozenset((
    ".html",
    ".htm",
    ".js",
    ".css",
    ".json",
    ".txt",
    ".csv",
    ".tsv",
    ".md",
))

_META_CHARSET_RE = re.compile(
    r'(<meta\s+[^>]*charset=[\'"]?)[^\'"\s>]+([\'"\s>])',
    re.IGNORECASE,
)
_RAW_META_CHARSET_RE = re.compile(
    rb'(?:<meta\s+[^>]*charset=[\'"]?)([\w\-]+)',
    re.IGNORECASE,
)
_HEAD_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)


def _detect_encoding(raw: bytes, is_html: bool) -> str | None:
    if is_html:
        meta_match = _RAW_META_CHARSET_RE.search(raw[:2048])
        if meta_match:
            declared = meta_match.group(1).decode("ascii", errors="ignore")
            try:
                codecs.lookup(declared)
                return declared
            except LookupError:
                pass

    match = charset_normalizer.from_bytes(raw).best()
    if match is not None and match.encoding:
        return str(match.encoding)
    return None


def _normalize_html_content(text: str, was_transcoded: bool) -> str:
    if _META_CHARSET_RE.search(text):
        return _META_CHARSET_RE.sub(r"\g<1>utf-8\g<2>", text)
    if was_transcoded:
        head_match = _HEAD_RE.search(text)
        if head_match:
            pos = head_match.end()
            return text[:pos] + '\n<meta charset="utf-8">' + text[pos:]
    return text


def _normalize_file_encoding(path: Path) -> None:
    try:
        raw = path.read_bytes()
    except OSError:
        return

    is_html = _is_html_file(path.name)
    was_transcoded = False

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        encoding = _detect_encoding(raw, is_html=is_html)
        if not encoding:
            return
        try:
            text = raw.decode(encoding)
            was_transcoded = True
        except (UnicodeDecodeError, LookupError):
            return

    if is_html:
        new_text = _normalize_html_content(text, was_transcoded=was_transcoded)
        if new_text != text:
            text = new_text
            was_transcoded = True

    if was_transcoded:
        try:
            path.write_bytes(text.encode("utf-8"))
        except OSError:
            return


def _normalize_tree_encoding(stage: Path) -> None:
    for path in stage.rglob("*"):
        if (
            path.is_file()
            and not path.is_symlink()
            and (
                _is_html_file(path.name)
                or path.suffix.lower() in _TEXT_EXTENSIONS
            )
        ):
            _normalize_file_encoding(path)


def generate(spec: GenerateSpec) -> None:
    if spec.config:
        raise ValueError("Static files generation does not support config")

    with open_archive(spec.game_file) as archive:
        target = find_unpack_target(archive)

    if target is None:
        raise ValueError(
            f"Archive {spec.game_file.name} does not contain "
            "index.html or index.htm at root or in a single root directory"
        )

    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{spec.destination.name}.", dir=spec.destination.parent
        )
    )
    try:
        with tempfile.TemporaryDirectory(
            dir=spec.destination.parent
        ) as temp_extract_str:
            temp_extract = Path(temp_extract_str)
            extract_archive(spec.game_file, temp_extract)

            source_dir = temp_extract / target if target else temp_extract
            if not source_dir.is_dir():
                raise ValueError(
                    f"Target directory {source_dir.name} not found in "
                    "extracted archive"
                )

            for item in source_dir.iterdir():
                if item.name in _IGNORED_ROOTS or item.name in _IGNORED_NAMES:
                    continue
                shutil.move(str(item), str(stage / item.name))

            if (
                not (stage / "index.html").exists()
                and not (stage / "index.htm").exists()
            ):
                html_files = [
                    item
                    for item in stage.iterdir()
                    if item.is_file() and _is_html_file(item.name)
                ]
                if len(html_files) == 1:
                    html_files[0].rename(stage / "index.html")

            _normalize_tree_encoding(stage)

        _publish(stage, spec.destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
