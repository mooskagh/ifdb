import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from core.archives import Archive, ArchiveError, extract_archive, open_archive
from play.blueprint import BlueprintSpec, GenerateResult, GenerateSpec

ASSETS_DIR = Path(__file__).parent / "assets"

SUPPORTED_EXTENSIONS = frozenset((
    ".z3",
    ".z4",
    ".z5",
    ".z8",
    ".zblorb",
    ".zlb",
    ".ulx",
    ".gblorb",
    ".glb",
    ".t3",
    ".gam",
))

_TADS2_HEADER = b"TADS2 bin\n\r\x1a\x00"
_TADS3_HEADER = b"T3-image\x0d\x0a\x1a"

_RELEASE_NAME = re.compile(
    r"^parchment-(?:single-file-)?(?P<version>\d+(?:[-.]\d+)*)\.zip$"
)
_PARCHMENT_OPTIONS = re.compile(
    rb"<script>\s*parchment_options\s*=\s*\{(?P<options>[^}]*)\}\s*</script>"
)
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
    if parts[-1].startswith("._"):
        return True
    return False


def _is_tads2_file(path: Path, tags: list[str] | None = None) -> bool:
    if tags:
        lower_tags = [t.lower() for t in tags]
        if any("qsp" in t for t in lower_tags):
            return False
        if any("tads" in t for t in lower_tags):
            return True
    try:
        with path.open("rb") as f:
            header = f.read(len(_TADS2_HEADER))
        return header == _TADS2_HEADER
    except OSError:
        return False


def _is_tads2_archive_member(
    archive_path: Path, member: str, tags: list[str] | None = None
) -> bool:
    if tags:
        lower_tags = [t.lower() for t in tags]
        if any("qsp" in t for t in lower_tags):
            return False
        if any("tads" in t for t in lower_tags):
            return True
    if is_zipfile(archive_path):
        try:
            with ZipFile(archive_path) as zf:
                actual_name = next(
                    (
                        n
                        for n in zf.namelist()
                        if n.replace("\\", "/") == member
                    ),
                    member,
                )
                header = zf.read(actual_name)[: len(_TADS2_HEADER)]
                return header == _TADS2_HEADER
        except Exception:
            return False
    return False


def _find_game_file_in_archive(
    archive: Archive,
    archive_path: Path | None = None,
    tags: list[str] | None = None,
) -> str | None:
    candidates: list[tuple[int, str]] = []
    for member in archive.namelist():
        if member.endswith("/"):
            continue
        parts = _split_clean_parts(member)
        if _is_ignored(parts):
            continue
        ext = Path(parts[-1]).suffix.lower()
        if ext == ".gam":
            if archive_path and not _is_tads2_archive_member(
                archive_path, member, tags
            ):
                continue
            if not archive_path and tags:
                lower_tags = [t.lower() for t in tags]
                if any("qsp" in t for t in lower_tags) or not any(
                    "tads" in t for t in lower_tags
                ):
                    continue
        if ext in SUPPORTED_EXTENSIONS:
            candidates.append((len(parts), member))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def accepts(
    filename: Path, *, tags: list[str] | None = None, **kwargs: object
) -> bool:
    if not filename.is_file():
        return False

    ext = filename.suffix.lower()
    if ext == ".gam":
        return _is_tads2_file(filename, tags)
    if ext in SUPPORTED_EXTENSIONS:
        return True

    try:
        with open_archive(filename) as archive:
            return (
                _find_game_file_in_archive(archive, filename, tags) is not None
            )
    except (ArchiveError, OSError):
        return False


def _release_paths() -> dict[str, Path]:
    releases: dict[str, Path] = {}
    for path in sorted(ASSETS_DIR.rglob("*.zip"), key=str):
        if not path.is_file():
            continue

        match = _RELEASE_NAME.fullmatch(path.name)
        if match:
            releases[match.group("version")] = path

    return releases


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(component) for component in re.split(r"[-.]", version))


def get_spec() -> BlueprintSpec:
    versions = sorted(_release_paths(), key=_version_key)
    return BlueprintSpec(name="Parchment", versions=versions)


_TITLE_REGEX = b"/([/=])([^/=]+)$/"
_TITLE_REPLACEMENT = b"/([/=]|^)([^/=]+)$/"


def _patch_parchment_options(html: bytes, game_filename: str) -> bytes:
    match = _PARCHMENT_OPTIONS.search(html)
    if not match:
        raise ValueError("Could not find parchment_options in parchment.html")
    replacement = (
        f"<script>parchment_options = {{\n"
        f'  "single_file": 1,\n'
        f'  "story": "./{game_filename}"\n'
        f"}}</script>"
    ).encode()
    patched = html[: match.start()] + replacement + html[match.end() :]
    return patched.replace(_TITLE_REGEX, _TITLE_REPLACEMENT, 1)


def _write_runtime(
    runtime_path: Path, stage: Path, game_filename: str
) -> None:
    with ZipFile(runtime_path) as runtime:
        launcher_name = next(
            (
                name
                for name in runtime.namelist()
                if Path(name).name == "parchment.html"
            ),
            None,
        )
        if not launcher_name:
            raise ValueError("parchment.html not found in runtime archive")
        html = runtime.read(launcher_name)

    patched = _patch_parchment_options(html, game_filename)
    (stage / "index.html").write_bytes(patched)


def _publish(stage: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    stage.rename(destination)


def generate(spec: GenerateSpec) -> GenerateResult:
    if spec.config:
        raise ValueError("Parchment generation does not support config")

    releases = _release_paths()
    if spec.version not in releases:
        raise ValueError(f"Unknown Parchment version: {spec.version}")
    runtime_path = releases[spec.version]

    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{spec.destination.name}.", dir=spec.destination.parent
        )
    )
    try:
        if spec.game_file.suffix.lower() in SUPPORTED_EXTENSIONS:
            game_ext = spec.game_file.suffix.lower()
            shutil.copyfile(spec.game_file, stage / f"game{game_ext}")
        else:
            with open_archive(spec.game_file) as archive:
                member_name = _find_game_file_in_archive(
                    archive, spec.game_file, spec.tags
                )
            if not member_name:
                raise ValueError(
                    f"Archive {spec.game_file.name} does not contain "
                    "any supported game files"
                )
            game_ext = Path(member_name).suffix.lower()
            with tempfile.TemporaryDirectory(
                dir=spec.destination.parent
            ) as temp_extract_str:
                temp_extract = Path(temp_extract_str)
                extract_archive(spec.game_file, temp_extract)
                source = temp_extract / member_name
                if not source.is_file():
                    source = next(
                        p
                        for p in temp_extract.rglob("*")
                        if p.is_file() and p.name == Path(member_name).name
                    )
                shutil.copyfile(source, stage / f"game{game_ext}")

        _write_runtime(runtime_path, stage, f"game{game_ext}")
        _publish(stage, spec.destination)
        return GenerateResult(
            player_name="Parchment",
            player_url="https://iplayif.com",
        )
    finally:
        if stage.exists():
            shutil.rmtree(stage)
