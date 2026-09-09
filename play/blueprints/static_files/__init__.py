import shutil
import tempfile
from pathlib import Path

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

        _publish(stage, spec.destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
